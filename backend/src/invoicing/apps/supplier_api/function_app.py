"""supplier-api entry point. Deployed as the package root's `function_app.py`
(ci/code-deploy.sh), so imports are absolute."""

from pathlib import Path

import azure.functions as func

from invoicing.adapters.static import spa_endpoint
from invoicing.apps.common import (
    anonymous_health_endpoint,
    load_settings,
    start_telemetry,
)
from invoicing.apps.supplier_api.settings import SupplierApiSettings

# Fails at start-up, naming any missing setting.
settings = load_settings(SupplierApiSettings)
# Once per app, before any function runs (AD-17); off, with one warning, when unset.
start_telemetry(settings, "supplier-api")

# Anonymous at the platform; the upload token is checked in code (AD-1, AD-14).
app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)


# host.json sets routePrefix "" so the SPA can own "/"; API routes spell out api/.
@app.route(route="api/health", methods=["GET"])
async def health(req: func.HttpRequest) -> func.HttpResponse:
    """Liveness and the deployed version."""
    return await anonymous_health_endpoint(req)


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
