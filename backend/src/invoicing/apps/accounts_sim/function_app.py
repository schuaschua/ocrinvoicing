"""accounts-sim entry point. Deployed as the package root's `function_app.py`
(ci/code-deploy.sh), so imports are absolute.

The simulated accounts XML API (AD-10, Story 3.1): `POST /api/invoices` (host.json
keeps the default `api/` route prefix). No health route: the deploy loop checks only
supplier-api and staff-api.
"""

import logging

import azure.functions as func

from invoicing.adapters.logging import log_event
from invoicing.adapters.postgres.engine import entra_token_provider, postgres_engine
from invoicing.adapters.postgres.sim_accounts import PostgresSimAccounts
from invoicing.apps.accounts_sim.invoices import invoices_endpoint
from invoicing.apps.accounts_sim.settings import AccountsSimSettings
from invoicing.apps.common import load_settings, start_telemetry
from invoicing.domain.errors import ErrorCode

# Fails at start-up, naming any missing setting.
settings = load_settings(AccountsSimSettings)
# Once per app, before any function runs (AD-17); off, with one warning, when unset.
start_telemetry(settings, "accounts-sim")

# Sign-in is enforced by built-in auth at the platform, which admits only this
# environment's pipeline identity (AD-10); the route checks that principal again.
app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

# In Azure with built-in auth off, the principal header could be forged: the route
# answers 401 AUTH_DISABLED, and this is logged once, at start-up.
if not settings.platform_auth_trusted:
    log_event(
        logging.getLogger("invoicing.auth"),
        "auth.disabled",
        level=logging.ERROR,
        code=ErrorCode.AUTH_DISABLED,
    )

# accounts-sim's own login, signing in with an Entra token (AD-11). Creating the engine
# opens no connection; migrations never run here (AD-17). One pipeline instance posts
# one invoice at a time (AD-2), so a small pool is plenty on the shared B1ms (AD-12).
SIM_POOL_SIZE = 2
engine = postgres_engine(
    host=settings.postgres_host,
    database=settings.postgres_database,
    user=settings.postgres_user,
    password=entra_token_provider(str(settings.azure_client_id)),
    pool_size=SIM_POOL_SIZE,
)

invoices_api = invoices_endpoint(
    PostgresSimAccounts(engine),
    pipeline_principal_id=settings.pipeline_principal_id,
    platform_auth_trusted=settings.platform_auth_trusted,
)


@app.route(route="invoices", methods=["POST"])
async def invoices(req: func.HttpRequest) -> func.HttpResponse:
    """Store one invoice XML document: 201 or 200 with its accounts_ref, 400, 401, 403,
    413, or the failure mode's status."""
    return await invoices_api(req)
