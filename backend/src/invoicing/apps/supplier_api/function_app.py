"""supplier-api entry point. Deployed as the package root's `function_app.py`
(ci/code-deploy.sh), so imports are absolute."""

from pathlib import Path

import azure.functions as func

from invoicing.adapters.blob_images import BlobImageStore
from invoicing.adapters.queue import StorageQueueSender
from invoicing.adapters.static import spa_endpoint
from invoicing.adapters.table_links import TableSupplierLinkRegistry
from invoicing.adapters.table_reminders import TableReminderStore
from invoicing.adapters.table_upload_keys import TableUploadKeyStore
from invoicing.apps.common import (
    anonymous_health_endpoint,
    load_settings,
    start_telemetry,
)
from invoicing.apps.supplier_api.link import link_endpoint
from invoicing.apps.supplier_api.reminders import reminders_endpoint
from invoicing.apps.supplier_api.settings import SupplierApiSettings
from invoicing.apps.supplier_api.upload import upload_endpoint

# Fails at start-up, naming any missing setting.
settings = load_settings(SupplierApiSettings)
# Once per app, before any function runs (AD-17); off, with one warning, when unset.
start_telemetry(settings, "supplier-api")

# Anonymous at the platform; the upload token is checked in code (AD-1, AD-14).
app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

# The upload path and the reminders (AD-6): Table Storage, blob storage and q-quality
# only, never PostgreSQL. Creating the clients opens no connection.
_account, _identity = settings.storage_account_name, str(settings.azure_client_id)
links = TableSupplierLinkRegistry.with_managed_identity(_account, _identity)
upload_keys = TableUploadKeyStore.with_managed_identity(_account, _identity)
images = BlobImageStore.with_managed_identity(_account, _identity)
queue = StorageQueueSender.with_managed_identity(_account, _identity)
# Story 4.3: the weekly job's reminder rows, read for the link's supplier only.
reminders = TableReminderStore.with_managed_identity(_account, _identity)


# host.json sets routePrefix "" so the SPA can own "/"; API routes spell out api/.
@app.route(route="api/health", methods=["GET"])
async def health(req: func.HttpRequest) -> func.HttpResponse:
    """Liveness and the deployed version."""
    return await anonymous_health_endpoint(req)


link_api = link_endpoint(lambda: links)


@app.route(route="api/link", methods=["GET"])
async def link(req: func.HttpRequest) -> func.HttpResponse:
    """The supplier name for the X-Upload-Token link, or 401 LINK_NOT_VALID."""
    return await link_api(req)


upload_api = upload_endpoint(
    lambda: links, lambda: upload_keys, lambda: images, lambda: queue
)


@app.route(route="api/upload", methods=["POST"])
async def upload(req: func.HttpRequest) -> func.HttpResponse:
    """One invoice file as the raw body, with Idempotency-Key: `{invoice_id,
    reference}` (AD-6)."""
    return await upload_api(req)


reminders_api = reminders_endpoint(lambda: links, lambda: reminders)


@app.route(route="api/reminders", methods=["GET"])
async def supplier_reminders(req: func.HttpRequest) -> func.HttpResponse:
    """The link's supplier's overdue PO numbers, sorted (Story 4.3), or 401
    LINK_NOT_VALID."""
    return await reminders_api(req)


# The built web/supplier (AD-14), packaged as static/ next to this file by
# ci/code-deploy.sh. Route precedence, not registration order, sends /api/* to the
# literal api/ routes: a catch-all always ranks below them. It stays last by convention
# (tests/apps guard it). The host reserves admin/* and runtime/* before any function,
# so client routes never start with them (adapters/static.py).
# Anonymous: the caller's X-Correlation-Id is ignored (it would choose the trace id).
spa = spa_endpoint(
    Path(__file__).resolve().parent / "static", trust_caller_correlation_id=False
)


@app.route(route="{*path}", methods=["GET"])
async def web_app(req: func.HttpRequest) -> func.HttpResponse:
    """The single-page app: its files, or index.html for a client-side path."""
    return await spa(req)
