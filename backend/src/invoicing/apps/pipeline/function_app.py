"""pipeline entry point. Deployed as the package root's `function_app.py`
(ci/code-deploy.sh), so imports are absolute.

Queue and timer triggers only, never HTTP routes (AD-1). The stages and the sweeper
arrive with their stories; the host starts with no functions.
"""

import azure.functions as func

from invoicing.apps.common import load_settings, start_telemetry
from invoicing.apps.pipeline.settings import PipelineSettings

# Fails at start-up, naming any missing setting.
settings = load_settings(PipelineSettings)
# Once per app, before any function runs (AD-17); off, with one warning, when unset.
start_telemetry(settings, "pipeline")

app = func.FunctionApp()
