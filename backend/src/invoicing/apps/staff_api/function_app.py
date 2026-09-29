"""staff-api entry point. Deployed as the package root's `function_app.py`
(ci/code-deploy.sh), so imports are absolute."""

import logging
from pathlib import Path

import azure.functions as func

from invoicing.adapters.logging import log_event
from invoicing.adapters.postgres.admin_queue import PostgresAdminQueueReader
from invoicing.adapters.postgres.engine import entra_token_provider, postgres_engine
from invoicing.adapters.static import spa_endpoint
from invoicing.apps.common import health_endpoint, load_settings, start_telemetry
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
