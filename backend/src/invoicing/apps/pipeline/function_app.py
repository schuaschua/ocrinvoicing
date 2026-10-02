"""pipeline entry point. Deployed as the package root's `function_app.py`
(ci/code-deploy.sh), so imports are absolute.

Queue and timer triggers only, never HTTP routes (AD-1). Story 2.1 adds the `quality`
stage on `q-quality`; Story 2.2 the poison triggers, the AD-7 database wait and the
sweeper timer; Story 2.3 the `extract` stage on `q-extract`; Story 2.5 the `validate`
stage on `q-validate`, and Story 2.6 its duplicate, date and bank checks; Story 3.2 the
`post` stage on `q-post`; Story 4.2 the AD-13 analytics refresh timer, and Story 4.3
its weekly supplier reminders.
"""

import azure.functions as func
from azure.identity import ManagedIdentityCredential
from azure.identity.aio import (
    ManagedIdentityCredential as AsyncManagedIdentityCredential,
)

from invoicing.adapters.accounts_xml.client import AccountsXmlClient
from invoicing.adapters.blob_images import BlobImageStore
from invoicing.adapters.document_intelligence import DocumentIntelligenceAnalyzer
from invoicing.adapters.documents import load_quality_thresholds
from invoicing.adapters.key_vault import BankKeysLoader
from invoicing.adapters.metrics import OpenTelemetryMetrics
from invoicing.adapters.postgres.analytics import PostgresAnalyticsStore
from invoicing.adapters.postgres.engine import entra_token_provider, postgres_engine
from invoicing.adapters.postgres.extraction import PostgresExtractionRepository
from invoicing.adapters.postgres.invoices import PostgresInvoiceRepository
from invoicing.adapters.postgres.posting import PostgresPostingRepository
from invoicing.adapters.postgres.suppliers import PostgresSupplierReader
from invoicing.adapters.postgres.validation import PostgresValidationRepository
from invoicing.adapters.purchasing_factory import purchasing_port
from invoicing.adapters.queue import StorageQueueSender
from invoicing.adapters.table_reminders import TableReminderStore
from invoicing.adapters.table_upload_keys import TableUploadKeyStore
from invoicing.apps.common import load_settings, start_telemetry
from invoicing.apps.pipeline.analytics_refresh import REFRESH_SCHEDULE, AnalyticsRefresh
from invoicing.apps.pipeline.dbwait import wait_for_database
from invoicing.apps.pipeline.extract import ExtractDependencies, extract_handler
from invoicing.apps.pipeline.poison import poison_handler
from invoicing.apps.pipeline.post import PostDependencies, post_handler
from invoicing.apps.pipeline.quality import quality_handler
from invoicing.apps.pipeline.settings import PipelineSettings
from invoicing.apps.pipeline.sweeper import SWEEP_SCHEDULE, Sweeper
from invoicing.apps.pipeline.validate import ValidateDependencies, validate_handler
from invoicing.domain.status import Stage
from invoicing.ports.extraction import DefaultModelSelector
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
reminders = TableReminderStore.with_managed_identity(_account, _identity)
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
# Story 2.3: the bank keys are read from Key Vault once, when a run first holds a
# bank value (AD-11); DI is called through its one adapter only (AD-8).
extractions = PostgresExtractionRepository(
    engine,
    invoices,
    BankKeysLoader(
        settings.key_vault_uri, lambda: ManagedIdentityCredential(client_id=_identity)
    ),
)
analyzer = DocumentIntelligenceAnalyzer(
    endpoint=settings.di_endpoint,
    credential=AsyncManagedIdentityCredential(client_id=_identity),
    engine=engine,
    page_cap=settings.di_monthly_page_cap,
    currency=settings.invoice_currency,
)
extract_stage = wait_for_database(
    QueueName.EXTRACT,
    queue,
    extract_handler(
        ExtractDependencies(
            images=images,
            invoices=invoices,
            extractions=extractions,
            analyzer=analyzer,
            models=DefaultModelSelector(),
            queue=queue,
            metrics=metrics,
        )
    ),
)
# Story 2.5: purchasing is read before the finishing transaction (AD-10); the PO
# match, the duplicate check (Story 2.6) and the writes run under the per-supplier
# lock (AD-9, AD-19). A matched PO's reminder row is deleted after the commit (AD-6).
validations = PostgresValidationRepository(engine, invoices)
validate_stage = wait_for_database(
    QueueName.VALIDATE,
    queue,
    validate_handler(
        ValidateDependencies(
            invoices=invoices,
            validations=validations,
            purchasing=purchasing,
            suppliers=PostgresSupplierReader(engine),
            queue=queue,
            reminders=reminders,
        )
    ),
)
# Story 3.2: the AD-18 current values go to the accounts system through its one
# adapter (AD-10), with a managed-identity token for accounts-sim's registration.
post_stage = wait_for_database(
    QueueName.POST,
    queue,
    post_handler(
        PostDependencies(
            invoices=invoices,
            postings=PostgresPostingRepository(engine, invoices),
            validations=validations,
            accounts=AccountsXmlClient(
                base_url=settings.accounts_base_url,
                audience=settings.accounts_audience,
                credential=AsyncManagedIdentityCredential(client_id=_identity),
            ),
            queue=queue,
            currency=settings.invoice_currency,
        )
    ),
)
poison_stages = {
    stage: wait_for_database(
        POISON_QUEUES[stage], queue, poison_handler(stage, images, invoices, metrics)
    )
    for stage in Stage
}
sweeper_job = Sweeper(invoices, upload_keys, images, queue, metrics)
# Story 4.2: the AD-13 job, the only writer of `analytics`; purchasing through its
# adapter only (AD-10). Story 4.3: it also writes the weekly supplier reminders;
# Story 5.1 the daily summary tables (AD-20).
analytics_job = AnalyticsRefresh(purchasing, PostgresAnalyticsStore(engine), reminders)


# The queue trigger reads through the host storage connection (AzureWebJobsStorage,
# identity-based), which is the environment's storage account.
@app.queue_trigger(
    arg_name="msg", queue_name=QueueName.QUALITY.value, connection="AzureWebJobsStorage"
)
async def quality(msg: func.QueueMessage) -> None:
    """The quality stage: create the invoice row and check readability (Story 2.1)."""
    await quality_stage(msg.get_body())


@app.queue_trigger(
    arg_name="msg", queue_name=QueueName.EXTRACT.value, connection="AzureWebJobsStorage"
)
async def extract(msg: func.QueueMessage) -> None:
    """The extract stage: read the invoice's fields with Document Intelligence
    (Story 2.3)."""
    await extract_stage(msg.get_body())


@app.queue_trigger(
    arg_name="msg",
    queue_name=QueueName.VALIDATE.value,
    connection="AzureWebJobsStorage",
)
async def validate(msg: func.QueueMessage) -> None:
    """The validate stage: confidence, PO match and printed supplier (Story 2.5);
    duplicates, photo date and bank details (Story 2.6)."""
    await validate_stage(msg.get_body())


@app.queue_trigger(
    arg_name="msg", queue_name=QueueName.POST.value, connection="AzureWebJobsStorage"
)
async def post(msg: func.QueueMessage) -> None:
    """The post stage: send a clean invoice to the accounts system (Story 3.2)."""
    await post_stage(msg.get_body())


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


# AD-13: weekdays at 01:30, 04:30 and 08:30 UTC; the first run that finds the database
# up does the day's work. No run at start-up: a cold start is not a schedule.
@app.timer_trigger(
    arg_name="timer",
    schedule=REFRESH_SCHEDULE,
    run_on_startup=False,
    use_monitor=True,
)
async def analytics_refresh(timer: func.TimerRequest) -> None:
    """The analytics refresh job: rebuild the overdue list once a weekday (Story
    4.2), the supplier reminders once a week (Story 4.3) and the summary tables once
    a day (Story 5.1)."""
    await analytics_job.run()
