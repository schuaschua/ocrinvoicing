"""accounts-sim entry point. Deployed as the package root's `function_app.py`
(ci/code-deploy.sh), so imports are absolute.

The XML endpoint (AD-10) arrives with its story; the host starts with no functions.
"""

import azure.functions as func

from invoicing.apps.accounts_sim.settings import AccountsSimSettings
from invoicing.apps.common import load_settings, start_telemetry

# Fails at start-up, naming any missing setting.
settings = load_settings(AccountsSimSettings)
# Once per app, before any function runs (AD-17); off, with one warning, when unset.
start_telemetry(settings, "accounts-sim")

# Sign-in is enforced by built-in auth at the platform (AD-10, Story 2.7).
app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)
