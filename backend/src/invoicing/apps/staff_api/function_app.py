"""staff-api entry point. Deployed as the package root's `function_app.py`
(ci/code-deploy.sh), so imports are absolute."""

import logging
from pathlib import Path

import azure.functions as func
from azure.identity import ManagedIdentityCredential

from invoicing.adapters.blob_corrections import BlobCorrectionsStore
from invoicing.adapters.blob_images import BlobImageStore
from invoicing.adapters.key_vault import PrivateKeyLoader
from invoicing.adapters.logging import log_event
from invoicing.adapters.postgres.admin_actions import PostgresAdminActions
from invoicing.adapters.postgres.admin_item import PostgresAdminItemReader
from invoicing.adapters.postgres.admin_queue import PostgresAdminQueueReader
from invoicing.adapters.postgres.engine import entra_token_provider, postgres_engine
from invoicing.adapters.queue import StorageQueueSender
from invoicing.adapters.static import spa_endpoint
from invoicing.apps.common import health_endpoint, load_settings, start_telemetry
from invoicing.apps.staff_api.actions import action_endpoints
from invoicing.apps.staff_api.item import item_endpoints
from invoicing.apps.staff_api.me import me_endpoint
from invoicing.apps.staff_api.queue import queue_endpoint
from invoicing.apps.staff_api.settings import StaffApiSettings
from invoicing.domain.errors import ErrorCode

# Fails at start-up, naming any missing setting.
settings = load_settings(StaffApiSettings)
# Once per app, before any function runs (AD-17); off, with one warning, when unset.
start_telemetry(settings, "staff-api")

# Sign-in is enforced by built-in auth at the platform (AD-14, Story 2.7), so the
# functions themselves need no keys. Every API route but api/health also checks the
# platform's principal and its roles in code (adapters/principal.py, domain/roles.py).
app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)


# host.json sets routePrefix "" so the SPA can own "/"; API routes spell out api/.
@app.route(route="api/health", methods=["GET"])
async def health(req: func.HttpRequest) -> func.HttpResponse:
    """Liveness and the deployed version."""
    return await health_endpoint(req)


# In Azure with built-in auth off, the principal header could be forged: every staff
# route answers 401 AUTH_DISABLED, and this is logged once, at start-up (AD-14).
if not settings.platform_auth_trusted:
    log_event(
        logging.getLogger("invoicing.auth"),
        "auth.disabled",
        level=logging.ERROR,
        code=ErrorCode.AUTH_DISABLED,
    )

me_api = me_endpoint(platform_auth_trusted=settings.platform_auth_trusted)


@app.route(route="api/me", methods=["GET"])
async def me(req: func.HttpRequest) -> func.HttpResponse:
    """The signed-in user's display name and app roles: `{name, roles}`, or 401."""
    return await me_api(req)


# Story 2.8: staff-api's own login, signing in with an Entra token (AD-11). Creating
# the engine opens no connection; migrations never run here (AD-17). A small pool: the
# staff app's requests are few, and Dev and Prod share the B1ms server (AD-12).
STAFF_POOL_SIZE = 4
engine = postgres_engine(
    host=settings.postgres_host,
    database=settings.postgres_database,
    user=settings.postgres_user,
    password=entra_token_provider(str(settings.azure_client_id)),
    pool_size=STAFF_POOL_SIZE,
)

queue_api = queue_endpoint(
    PostgresAdminQueueReader(engine),
    page_cap=settings.di_monthly_page_cap,
    currency=settings.invoice_currency,
    platform_auth_trusted=settings.platform_auth_trusted,
)


@app.route(route="api/admin/queue", methods=["GET"])
async def admin_queue(req: func.HttpRequest) -> func.HttpResponse:
    """The admin queue, oldest first, 50 a page (admins only): 200, 400, 401 or 403."""
    return await queue_api(req)


# Story 2.9: the admin item. The image comes from `images` as staff-api's identity,
# streamed same-origin (no SAS). pgp-private-key is read from the private-key vault on
# the first bank value an admin opens, then kept in this process only (AD-11).
_identity = str(settings.azure_client_id)
item_api, item_image_api, bank_reveal_api = item_endpoints(
    PostgresAdminItemReader(
        engine,
        PrivateKeyLoader(
            settings.pgp_private_key_vault_uri,
            lambda: ManagedIdentityCredential(client_id=_identity),
        ),
    ),
    BlobImageStore.with_managed_identity(settings.storage_account_name, _identity),
    platform_auth_trusted=settings.platform_auth_trusted,
)


@app.route(route="api/admin/items/{invoice_id}", methods=["GET"])
async def admin_item(req: func.HttpRequest) -> func.HttpResponse:
    """One queued invoice for an admin: 200, 401, 404 or 503."""
    return await item_api(req)


@app.route(route="api/admin/items/{invoice_id}/image", methods=["GET"])
async def admin_item_image(req: func.HttpRequest) -> func.HttpResponse:
    """The queued invoice's image or PDF, no-store: 200, 401 or 404 (IMAGE_DELETED)."""
    return await item_image_api(req)


@app.route(route="api/admin/items/{invoice_id}/bank/reveal", methods=["POST"])
async def admin_bank_reveal(req: func.HttpRequest) -> func.HttpResponse:
    """One changed bank value in full, audited: 200, 400, 401, 403, 404 or 503."""
    return await bank_reveal_api(req)


# Story 2.10: the admin actions. Each commits first; the stage queue message (as
# staff-api's identity, Queue Data Message Sender) and the corrections blob follow.
_account = settings.storage_account_name
queue_sender = StorageQueueSender.with_managed_identity(_account, _identity)
corrections = BlobCorrectionsStore.with_managed_identity(_account, _identity)
correct_api, reextract_api, retry_intake_api, reject_api = action_endpoints(
    PostgresAdminActions(engine, currency=settings.invoice_currency),
    lambda: queue_sender,
    lambda: corrections,
    platform_auth_trusted=settings.platform_auth_trusted,
)


@app.route(route="api/admin/items/{invoice_id}/correct", methods=["POST"])
async def admin_correct(req: func.HttpRequest) -> func.HttpResponse:
    """Save an admin's corrections and re-check: 200, 400, 401, 403, 404, 409 or 503."""
    return await correct_api(req)


@app.route(route="api/admin/items/{invoice_id}/reextract", methods=["POST"])
async def admin_reextract(req: func.HttpRequest) -> func.HttpResponse:
    """Extract the invoice again: 200, 400, 401, 403, 404, 409 or 503."""
    return await reextract_api(req)


@app.route(route="api/admin/items/{invoice_id}/retry-intake", methods=["POST"])
async def admin_retry_intake(req: func.HttpRequest) -> func.HttpResponse:
    """Send the upload through the quality check again: 200, 400, 401, 403, 404, 409
    or 503."""
    return await retry_intake_api(req)


@app.route(route="api/admin/items/{invoice_id}/reject", methods=["POST"])
async def admin_reject(req: func.HttpRequest) -> func.HttpResponse:
    """Reject the invoice with a reason: 200, 400, 401, 403, 404, 409 or 503."""
    return await reject_api(req)


# The built web/staff (AD-14), packaged as static/ next to this file by
# ci/code-deploy.sh. Route precedence, not registration order, sends /api/* to the
# literal api/ routes: a catch-all always ranks below them. It stays last by convention
# (tests/apps guard it). The host reserves admin/* and runtime/* before any function,
# so client routes never start with them (adapters/static.py).
spa = spa_endpoint(Path(__file__).resolve().parent / "static")


@app.route(route="{*path}", methods=["GET"])
async def web_app(req: func.HttpRequest) -> func.HttpResponse:
    """The single-page app: its files, or index.html for a client-side path."""
    return await spa(req)
