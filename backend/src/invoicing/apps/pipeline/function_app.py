"""pipeline entry point. Deployed as the package root's `function_app.py`
(ci/code-deploy.sh), so imports are absolute.

Queue and timer triggers only, never HTTP routes (AD-1). Story 2.1 adds the `quality`
stage on `q-quality`; Story 2.2 the poison triggers, the AD-7 database wait and the
sweeper timer. The other stages arrive with their stories.
"""

import azure.functions as func

from invoicing.adapters.blob_images import BlobImageStore
from invoicing.adapters.documents import load_quality_thresholds
from invoicing.adapters.metrics import OpenTelemetryMetrics
from invoicing.adapters.postgres.engine import entra_token_provider, postgres_engine
from invoicing.adapters.postgres.invoices import PostgresInvoiceRepository
from invoicing.adapters.purchasing_factory import purchasing_port
from invoicing.adapters.queue import StorageQueueSender
from invoicing.adapters.table_upload_keys import TableUploadKeyStore
from invoicing.apps.common import load_settings, start_telemetry
from invoicing.apps.pipeline.dbwait import wait_for_database
from invoicing.apps.pipeline.poison import poison_handler
from invoicing.apps.pipeline.quality import quality_handler
from invoicing.apps.pipeline.settings import PipelineSettings
from invoicing.apps.pipeline.sweeper import SWEEP_SCHEDULE, Sweeper
from invoicing.domain.status import Stage
from invoicing.ports.queue import POISON_QUEUES, QueueName

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
upload_keys = TableUploadKeyStore.with_managed_identity(_account, _identity)
engine = postgres_engine(
    host=settings.postgres_host,
    database=settings.postgres_database,
    user=settings.postgres_user,
    password=entra_token_provider(_identity),
)
invoices = PostgresInvoiceRepository(engine)
# PO and goods-received data (AD-10), for validate (Story 2.5) and the overdue job; the
# adapter is the one PURCHASING_ADAPTER names.
purchasing = purchasing_port(settings.purchasing_adapter, engine)
# After start_telemetry, so the metrics go to the configured meter (AD-17).
metrics = OpenTelemetryMetrics()
# The thresholds the page uses too, packaged as shared/quality-thresholds.json (AD-6).
thresholds = load_quality_thresholds()

# AD-7: every consumer, poison triggers included, waits out a stopped database.
quality_stage = wait_for_database(
    QueueName.QUALITY, queue, quality_handler(images, invoices, queue, thresholds)
)
poison_stages = {
    stage: wait_for_database(
        POISON_QUEUES[stage], queue, poison_handler(stage, images, invoices, metrics)
    )
    for stage in Stage
}
sweeper_job = Sweeper(invoices, upload_keys, images, queue, metrics)


# The queue trigger reads through the host storage connection (AzureWebJobsStorage,
# identity-based), which is the environment's storage account.
@app.queue_trigger(
    arg_name="msg", queue_name=QueueName.QUALITY.value, connection="AzureWebJobsStorage"
)
async def quality(msg: func.QueueMessage) -> None:
    """The quality stage: create the invoice row and check readability (Story 2.1)."""
    await quality_stage(msg.get_body())


# AD-2: one trigger per poison queue; each routes PROCESSING_FAILED under the guard.
@app.queue_trigger(
    arg_name="msg",
    queue_name=QueueName.QUALITY_POISON.value,
    connection="AzureWebJobsStorage",
)
async def quality_poison(msg: func.QueueMessage) -> None:
    """`q-quality-poison`: route a quality message that failed 5 times (Story 2.2)."""
    await poison_stages[Stage.QUALITY](msg.get_body(), msg.dequeue_count or 1)


@app.queue_trigger(
    arg_name="msg",
    queue_name=QueueName.EXTRACT_POISON.value,
    connection="AzureWebJobsStorage",
)
async def extract_poison(msg: func.QueueMessage) -> None:
    """`q-extract-poison`: route an extract message that failed 5 times (Story 2.2)."""
    await poison_stages[Stage.EXTRACT](msg.get_body(), msg.dequeue_count or 1)


@app.queue_trigger(
    arg_name="msg",
    queue_name=QueueName.VALIDATE_POISON.value,
    connection="AzureWebJobsStorage",
)
async def validate_poison(msg: func.QueueMessage) -> None:
    """`q-validate-poison`: route a validate message that failed 5 times (Story 2.2)."""
    await poison_stages[Stage.VALIDATE](msg.get_body(), msg.dequeue_count or 1)


@app.queue_trigger(
    arg_name="msg",
    queue_name=QueueName.POST_POISON.value,
    connection="AzureWebJobsStorage",
)
async def post_poison(msg: func.QueueMessage) -> None:
    """`q-post-poison`: route a post message that failed 5 times (Story 2.2)."""
    await poison_stages[Stage.POST](msg.get_body(), msg.dequeue_count or 1)


# AD-2: every 15 minutes, UTC. No run at start-up: a cold start is not a schedule.
@app.timer_trigger(
    arg_name="timer", schedule=SWEEP_SCHEDULE, run_on_startup=False, use_monitor=True
)
async def sweeper(timer: func.TimerRequest) -> None:
    """The sweeper: re-enqueue stuck invoices and orphaned uploads, expire upload keys
    (Story 2.2)."""
    await sweeper_job.run()
