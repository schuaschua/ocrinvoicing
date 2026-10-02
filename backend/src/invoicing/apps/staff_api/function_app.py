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
from invoicing.adapters.postgres.analytics import PostgresOverdueReader
from invoicing.adapters.postgres.dashboards import PostgresDashboardReader
from invoicing.adapters.postgres.engine import entra_token_provider, postgres_engine
from invoicing.adapters.postgres.invoice_search import PostgresInvoiceSearchReader
from invoicing.adapters.postgres.suppliers import PostgresSupplierDirectory
from invoicing.adapters.purchasing_factory import purchasing_port
from invoicing.adapters.queue import StorageQueueSender
from invoicing.adapters.static import spa_endpoint
from invoicing.adapters.table_upload_keys import TableUploadKeyStore
from invoicing.apps.common import health_endpoint, load_settings, start_telemetry
from invoicing.apps.staff_api.actions import action_endpoints
from invoicing.apps.staff_api.finance_month import finance_month_endpoint
from invoicing.apps.staff_api.goods_in import goods_in_endpoints
from invoicing.apps.staff_api.invoices import invoices_endpoints
from invoicing.apps.staff_api.item import item_endpoints
from invoicing.apps.staff_api.me import me_endpoint
from invoicing.apps.staff_api.overdue import overdue_endpoint
from invoicing.apps.staff_api.price_comparison import price_comparison_endpoints
from invoicing.apps.staff_api.queue import queue_endpoint
from invoicing.apps.staff_api.settings import StaffApiSettings
from invoicing.apps.staff_api.suppliers import suppliers_endpoints
from invoicing.apps.staff_api.watchlist import watchlist_endpoint
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
_account = settings.storage_account_name
# Reads the admin item's image; writes goods-in scans (Story 4.1).
images = BlobImageStore.with_managed_identity(_account, _identity)
item_api, item_image_api, bank_reveal_api, duplicate_image_api = item_endpoints(
    PostgresAdminItemReader(
        engine,
        PrivateKeyLoader(
            settings.pgp_private_key_vault_uri,
            lambda: ManagedIdentityCredential(client_id=_identity),
        ),
    ),
    images,
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


@app.route(route="api/admin/items/{invoice_id}/duplicate/image", methods=["GET"])
async def admin_duplicate_image(req: func.HttpRequest) -> func.HttpResponse:
    """The image of the invoice an open DUPLICATE names (Story 3.3), no-store: 200,
    401 or 404 (IMAGE_DELETED)."""
    return await duplicate_image_api(req)


@app.route(route="api/admin/items/{invoice_id}/bank/reveal", methods=["POST"])
async def admin_bank_reveal(req: func.HttpRequest) -> func.HttpResponse:
    """One changed bank value in full, audited: 200, 400, 401, 403, 404 or 503."""
    return await bank_reveal_api(req)


# Story 2.10: the admin actions. Each commits first; the stage queue message (as
# staff-api's identity, Queue Data Message Sender) and the corrections blob follow.
queue_sender = StorageQueueSender.with_managed_identity(_account, _identity)
corrections = BlobCorrectionsStore.with_managed_identity(_account, _identity)
correct_api, reextract_api, retry_intake_api, reject_api, approve_api = (
    action_endpoints(
        PostgresAdminActions(engine, currency=settings.invoice_currency),
        lambda: queue_sender,
        lambda: corrections,
        platform_auth_trusted=settings.platform_auth_trusted,
    )
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


# Story 3.3: Approve moves the invoice to ready_to_post, then q-post.
@app.route(route="api/admin/items/{invoice_id}/approve", methods=["POST"])
async def admin_approve(req: func.HttpRequest) -> func.HttpResponse:
    """Approve the invoice with a reason (and, for a bank change, both call-back
    checks): 200, 400, 401, 403, 404, 409 or 503."""
    return await approve_api(req)


# Story 3.4: invoice search and detail for admin and finance. Read-only; bank fields
# only as "on file" (AD-11), and no image route on this surface.
invoice_search_api, invoice_detail_api = invoices_endpoints(
    PostgresInvoiceSearchReader(engine),
    currency=settings.invoice_currency,
    platform_auth_trusted=settings.platform_auth_trusted,
)


@app.route(route="api/invoices", methods=["GET"])
async def invoice_search(req: func.HttpRequest) -> func.HttpResponse:
    """Every invoice, newest first, 50 a page, filtered (admin and finance): 200, 400,
    401, 403 or 503."""
    return await invoice_search_api(req)


@app.route(route="api/invoices/{invoice_id}", methods=["GET"])
async def invoice_detail(req: func.HttpRequest) -> func.HttpResponse:
    """One invoice's current fields, lines, history and accounts reference (admin and
    finance): 200, 401, 404 or 503."""
    return await invoice_detail_api(req)


# Story 4.1: goods-in scan. The supplier comes from the delivery (AD-10 purchasing
# port, chosen by PURCHASING_ADAPTER), and the upload follows the AD-6 key, blob,
# q-quality order through the same intake as supplier uploads.
upload_keys = TableUploadKeyStore.with_managed_identity(_account, _identity)
goods_in_deliveries_api, goods_in_upload_api = goods_in_endpoints(
    purchasing_port(settings.purchasing_adapter, engine),
    PostgresSupplierDirectory(engine),
    lambda: upload_keys,
    lambda: images,
    lambda: queue_sender,
    platform_auth_trusted=settings.platform_auth_trusted,
)


@app.route(route="api/goods-in/deliveries", methods=["GET"])
async def goods_in_deliveries(req: func.HttpRequest) -> func.HttpResponse:
    """Today's deliveries, or those matching `q` by PO or supplier (goods_in only):
    200, 400, 401, 403 or 503."""
    return await goods_in_deliveries_api(req)


@app.route(route="api/goods-in/deliveries/{delivery_id}/upload", methods=["POST"])
async def goods_in_upload(req: func.HttpRequest) -> func.HttpResponse:
    """A paper invoice scanned against a delivery (goods_in only): 200, 400, 401, 403,
    404, 409, 413, 415 or 503."""
    return await goods_in_upload_api(req)


# Story 4.2: the overdue list the AD-13 job made, read from `analytics` only (SELECT).
overdue_api = overdue_endpoint(
    PostgresOverdueReader(engine),
    PostgresSupplierDirectory(engine),
    platform_auth_trusted=settings.platform_auth_trusted,
)


@app.route(route="api/overdue-pos", methods=["GET"])
async def overdue_pos(req: func.HttpRequest) -> func.HttpResponse:
    """POs past their expected date with no invoice, by supplier, with the date the
    list was made (admin, procurement and finance): 200, 401, 403 or 503."""
    return await overdue_api(req)


# Story 5.3: Price comparison, read from `analytics` only (SELECT); supplier names from
# the master.
materials_api, price_comparison_api = price_comparison_endpoints(
    PostgresDashboardReader(engine),
    PostgresSupplierDirectory(engine),
    platform_auth_trusted=settings.platform_auth_trusted,
)


# Story 4.4: the suppliers list and one supplier's page shell, id and name only (AD-11).
# Story 4.5: its Deliveries tab, from the purchasing port (AD-10). Story 5.5: its
# Scorecard tab, from `analytics` only (SELECT).
(
    supplier_list_api,
    supplier_detail_api,
    supplier_deliveries_api,
    supplier_scorecard_api,
) = suppliers_endpoints(
    PostgresSupplierDirectory(engine),
    purchasing_port(settings.purchasing_adapter, engine),
    PostgresDashboardReader(engine),
    platform_auth_trusted=settings.platform_auth_trusted,
)


@app.route(route="api/materials", methods=["GET"])
async def materials(req: func.HttpRequest) -> func.HttpResponse:
    """The materials with posted prices, by name (procurement and finance): 200, 401,
    403 or 503."""
    return await materials_api(req)


@app.route(route="api/price-comparison", methods=["GET"])
async def price_comparison(req: func.HttpRequest) -> func.HttpResponse:
    """One material's suppliers, price history and price-rise alerts (procurement and
    finance): 200, 401, 403, 404 or 503."""
    return await price_comparison_api(req)


# Story 5.4: the Watchlist, read from `analytics` only (SELECT); supplier names from the
# master.
watchlist_api = watchlist_endpoint(
    PostgresDashboardReader(engine),
    PostgresSupplierDirectory(engine),
    platform_auth_trusted=settings.platform_auth_trusted,
)


@app.route(route="api/watchlist", methods=["GET"])
async def watchlist(req: func.HttpRequest) -> func.HttpResponse:
    """The watchlisted suppliers with their evidence and ranked alternatives
    (procurement and management): 200, 401, 403 or 503."""
    return await watchlist_api(req)


@app.route(route="api/suppliers", methods=["GET"])
async def supplier_list(req: func.HttpRequest) -> func.HttpResponse:
    """Suppliers by name, 50 a page, searched by name (procurement, finance and
    management): 200, 400, 401, 403 or 503."""
    return await supplier_list_api(req)


@app.route(route="api/suppliers/{supplier_id}", methods=["GET"])
async def supplier_detail(req: func.HttpRequest) -> func.HttpResponse:
    """One supplier's id and name (procurement, finance and management): 200, 401,
    404 or 503."""
    return await supplier_detail_api(req)


@app.route(route="api/suppliers/{supplier_id}/deliveries", methods=["GET"])
async def supplier_deliveries(req: func.HttpRequest) -> func.HttpResponse:
    """One supplier's deliveries of the last 365 days with promised, delivered and
    received dates and the gaps in days (procurement, finance and management): 200,
    401, 404 or 503."""
    return await supplier_deliveries_api(req)


@app.route(route="api/suppliers/{supplier_id}/scorecard", methods=["GET"])
async def supplier_scorecard(req: func.HttpRequest) -> func.HttpResponse:
    """One supplier's on-time rate and price trend per material over the last 365
    days (procurement, finance and management): 200, 401, 404 or 503."""
    return await supplier_scorecard_api(req)


# Story 5.6: Finance month, read from `analytics` only (SELECT); supplier names from
# the master.
finance_month_api = finance_month_endpoint(
    PostgresDashboardReader(engine),
    PostgresSupplierDirectory(engine),
    platform_auth_trusted=settings.platform_auth_trusted,
)


@app.route(route="api/finance-month", methods=["GET"])
async def finance_month(req: func.HttpRequest) -> func.HttpResponse:
    """One month's spend, price rises, flagged and duplicate invoices per supplier,
    with the straight-through share against the 90% target (finance and management):
    200, 400, 401, 403 or 503."""
    return await finance_month_api(req)


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
