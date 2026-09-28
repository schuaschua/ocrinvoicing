"""staff-api entry point. Deployed as the package root's `function_app.py`
(ci/code-deploy.sh), so imports are absolute."""

import azure.functions as func

from invoicing.apps.common import health_endpoint, load_settings
from invoicing.apps.staff_api.settings import StaffApiSettings

# Fails at start-up, naming any missing setting.
settings = load_settings(StaffApiSettings)

# Sign-in is enforced by built-in auth at the platform (AD-14, Story 2.7), so the
# functions themselves need no keys.
app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)


@app.route(route="health", methods=["GET"])
async def health(req: func.HttpRequest) -> func.HttpResponse:
    """Liveness and the deployed version."""
    return await health_endpoint(req)
