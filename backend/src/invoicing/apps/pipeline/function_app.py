"""pipeline entry point. Deployed as the package root's `function_app.py`
(ci/code-deploy.sh), so imports are absolute.

Queue and timer triggers only, never HTTP routes (AD-1). The stages and the sweeper
arrive with their stories; the host starts with no functions.
"""

import azure.functions as func

from invoicing.apps.common import load_settings
from invoicing.apps.pipeline.settings import PipelineSettings

# Fails at start-up, naming any missing setting.
settings = load_settings(PipelineSettings)

app = func.FunctionApp()
