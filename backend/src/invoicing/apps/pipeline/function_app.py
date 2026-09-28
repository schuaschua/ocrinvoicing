"""pipeline entry point. Deployed as the package root's `function_app.py`
(ci/code-deploy.sh), so imports are absolute.

Queue and timer triggers only, never HTTP routes (AD-1). Story 2.1 adds the `quality`
stage on `q-quality`; the other stages and the sweeper arrive with their stories.
"""

import azure.functions as func

from invoicing.adapters.blob_images import BlobImageStore
from invoicing.adapters.documents import load_quality_thresholds
from invoicing.adapters.postgres.engine import entra_token_provider, postgres_engine
from invoicing.adapters.postgres.invoices import PostgresInvoiceRepository
from invoicing.adapters.queue import StorageQueueSender
from invoicing.apps.common import load_settings, start_telemetry
from invoicing.apps.pipeline.quality import quality_handler
from invoicing.apps.pipeline.settings import PipelineSettings
from invoicing.ports.queue import QueueName

# Fails at start-up, naming any missing setting.
settings = load_settings(PipelineSettings)
# Once per app, before any function runs (AD-17); off, with one warning, when unset.
start_telemetry(settings, "pipeline")

app = func.FunctionApp()

# Creating the clients and the engine opens no connection. Migrations never run here
# (AD-17: the pipeline runs them before the app).
_account, _identity = settings.storage_account_name, str(settings.azure_client_id)
images = BlobImageStore.with_managed_identity(_account, _identity)
queue = StorageQueueSender.with_managed_identity(_account, _identity)
engine = postgres_engine(
    host=settings.postgres_host,
    database=settings.postgres_database,
    user=settings.postgres_user,
    password=entra_token_provider(_identity),
)
invoices = PostgresInvoiceRepository(engine)
# The thresholds the page uses too, packaged as shared/quality-thresholds.json (AD-6).
thresholds = load_quality_thresholds()

quality_stage = quality_handler(images, invoices, queue, thresholds)


# The queue trigger reads through the host storage connection (AzureWebJobsStorage,
# identity-based), which is the environment's storage account.
@app.queue_trigger(
    arg_name="msg", queue_name=QueueName.QUALITY.value, connection="AzureWebJobsStorage"
)
async def quality(msg: func.QueueMessage) -> None:
    """The quality stage: create the invoice row and check readability (Story 2.1)."""
    await quality_stage(msg.get_body())
