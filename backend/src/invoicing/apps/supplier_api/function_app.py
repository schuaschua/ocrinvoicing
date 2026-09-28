"""supplier-api entry point. Deployed as the package root's `function_app.py`
(ci/code-deploy.sh), so imports are absolute."""

import azure.functions as func

from invoicing.apps.common import health_endpoint, load_settings
from invoicing.apps.supplier_api.settings import SupplierApiSettings

# Fails at start-up, naming any missing setting.
settings = load_settings(SupplierApiSettings)

# Anonymous at the platform; the upload token is checked in code (AD-1, AD-14).
app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)


@app.route(route="health", methods=["GET"])
async def health(req: func.HttpRequest) -> func.HttpResponse:
    """Liveness and the deployed version."""
    return await health_endpoint(req)
