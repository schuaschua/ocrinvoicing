"""The `extract` stage (Story 2.3, AD-3, AD-8, AD-18, CAP-4), fed by `q-extract`.

1. Claim `awaiting_extraction -> extracting` with a 10-minute lease (or reclaim an
   expired one). Zero rows: the invoice moved on; re-enqueue `q-validate` when it is
   already `awaiting_validation` (AD-2), otherwise only acknowledge.
2. A run saved since the invoice last entered `awaiting_extraction` is reused: DI is
   not called and no pages are counted (AD-3 save-before-finish).
3. Otherwise analyse through the one DI adapter: resume the saved `Operation-Location`
   if there is one, else send the original (pages reserved first, AD-8).
4. Save the run, its fields (bank values encrypted, AD-11) and lines with
   `extracting -> awaiting_validation`, in one transaction; after the commit, enqueue
   `q-validate` and emit `di_pages_used_pct`.

- The page cap, or a DI quota error: `route_to_admin(EXTRACTION_QUOTA)`.
- DI 429: the same message goes back to `q-extract` after `Retry-After` and the
  original is completed, so no dequeue is used (AD-7). The lease is ended so that
  retry can reclaim at once; the invoice stays `extracting`.
- Any other failure ends the lease and is raised with a code, so the host retries
  the message and, after 5 tries, the poison trigger routes `PROCESSING_FAILED`.
- A stopped database is waited out (dbwait.py, AD-7).
"""

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from opentelemetry.trace import SpanKind
from pydantic import ValidationError

from invoicing.adapters.logging import log_event
from invoicing.adapters.telemetry import correlation_span
from invoicing.apps.pipeline.quality import StageFailed, failure_code
from invoicing.domain.errors import DatabaseOfflineError
from invoicing.domain.ids import new_uuid7
from invoicing.domain.reasons import ReasonCode
from invoicing.domain.status import (
    CLAIM_STATUS,
    InvoiceStatus,
    Stage,
    requeue_after_redelivery,
)
from invoicing.domain.transitions import plan_claim, plan_transition, route_to_admin
from invoicing.ports.blobs import ImageReader
from invoicing.ports.extraction import (
    DEAD_OPERATION_CODES,
    AnalyzeRequest,
    DiAnalysisFailed,
    DiQuotaExceeded,
    DiThrottled,
    DocumentAnalyzer,
    ExtractionError,
    ExtractionRepository,
    ModelSelector,
    NewRun,
)
from invoicing.ports.invoices import InvoiceRepository
from invoicing.ports.messages import QueueMessage
from invoicing.ports.metrics import MetricName, MetricsPort
from invoicing.ports.queue import STAGE_QUEUES, QueueName, QueueSender

ACTOR = "pipeline:extract"

_logger = logging.getLogger("invoicing.pipeline.extract")


class ExtractAction(StrEnum):
    """What the stage did with a message."""

    ADVANCE = "advance"
    REUSE = "reuse"
    ROUTE = "route"
    RETRY = "retry"
    ACK = "ack"


@dataclass(frozen=True)
class ExtractOutcome:
    """The stage's result: what it did, the queue to send the next message to after
    the commit (if any), the reason of a routing, and the delay of a 429 retry."""

    action: ExtractAction
    enqueue: QueueName | None = None
    reason: ReasonCode | None = None
    delay_seconds: int = 0


@dataclass(frozen=True)
class ExtractDependencies:
    """What the stage reaches outside itself; tests pass fakes for DI and queues."""

    images: ImageReader
    invoices: InvoiceRepository
    extractions: ExtractionRepository
    analyzer: DocumentAnalyzer
    models: ModelSelector
    queue: QueueSender
    metrics: MetricsPort


def _redelivered(status: InvoiceStatus | None) -> ExtractOutcome:
    """AD-2: the stage already ran. Its final target re-enqueues the next stage."""
    following = requeue_after_redelivery(Stage.EXTRACT, status)
    return ExtractOutcome(
        ExtractAction.ACK, None if following is None else STAGE_QUEUES[following]
    )


async def _emit_usage(deps: ExtractDependencies) -> None:
    deps.metrics.emit_metric(
        MetricName.DI_PAGES_USED_PCT, await deps.analyzer.pages_used_pct()
    )


async def extract(message: QueueMessage, deps: ExtractDependencies) -> ExtractOutcome:
    """Steps 1-4 for one parsed message. Raises `ExtractionError` (other than a 429
    or a quota) and storage errors for a host retry, with the lease ended."""
    invoice_id = message.invoice_id
    claim = plan_claim(invoice_id, Stage.EXTRACT, ACTOR)
    if not await deps.invoices.claim(claim):
        return _redelivered(await deps.invoices.status(invoice_id))
    finish = plan_transition(
        invoice_id,
        CLAIM_STATUS[Stage.EXTRACT],
        InvoiceStatus.AWAITING_VALIDATION,
        ACTOR,
    )
    try:
        if await deps.extractions.latest_run_since_entry(invoice_id) is not None:
            # AD-3: the run was saved but the transition not made; finish only.
            if await deps.invoices.transition(finish):
                return ExtractOutcome(ExtractAction.REUSE, QueueName.VALIDATE)
            return _redelivered(await deps.invoices.status(invoice_id))

        resume = await deps.extractions.saved_operation(invoice_id)
        if resume is not None:
            metadata, document = await deps.images.metadata(invoice_id), None
        else:
            stored = await deps.images.get(invoice_id)
            metadata, document = stored.metadata, stored.data
        request = AnalyzeRequest(
            invoice_id=invoice_id,
            model_id=deps.models.model_for(metadata.supplier_id),
            content_type=metadata.content_type,
            document=document,
            resume=resume,
        )
        try:
            analysis = await deps.analyzer.analyze(
                request, deps.extractions.save_operation
            )
        except DiAnalysisFailed as failed:
            if resume is not None and failed.code in DEAD_OPERATION_CODES:
                # DI expired or failed the saved operation: analyse afresh next time.
                await deps.extractions.forget_operation(invoice_id)
            raise
        except DiThrottled as throttled:
            await deps.invoices.release_claim(claim)
            return ExtractOutcome(
                ExtractAction.RETRY, delay_seconds=throttled.retry_after
            )
        except DiQuotaExceeded:
            await _emit_usage(deps)
            routed = await deps.invoices.route_to_admin(
                route_to_admin(
                    invoice_id,
                    [ReasonCode.EXTRACTION_QUOTA],
                    claim.claim_status,
                    actor=ACTOR,
                )
            )
            if routed:
                return ExtractOutcome(
                    ExtractAction.ROUTE, reason=ReasonCode.EXTRACTION_QUOTA
                )
            return _redelivered(await deps.invoices.status(invoice_id))

        saved = await deps.extractions.save_run(
            NewRun(run_id=new_uuid7(), invoice_id=invoice_id, analysis=analysis),
            finish,
        )
        await _emit_usage(deps)
        if saved:
            return ExtractOutcome(ExtractAction.ADVANCE, QueueName.VALIDATE)
        return _redelivered(await deps.invoices.status(invoice_id))
    except DatabaseOfflineError:
        raise
    except Exception:
        # The host retries this message now: let that retry reclaim (AD-3).
        await deps.invoices.release_claim(claim)
        raise


def _now() -> datetime:
    return datetime.now(UTC)


type ExtractHandler = Callable[[str | bytes], Awaitable[ExtractOutcome]]


def extract_handler(
    deps: ExtractDependencies, clock: Callable[[], datetime] | None = None
) -> ExtractHandler:
    """The `q-extract` message handler: parse, extract, then enqueue after the
    commit. A failure is raised as `StageFailed` with a code, so the host retries
    the message (`maxDequeueCount` 5). `DatabaseOfflineError` is raised as it is, for
    the AD-7 wait (dbwait.py)."""

    async def handle(body: str | bytes) -> ExtractOutcome:
        try:
            message = QueueMessage.from_json(body)
        except ValidationError:
            log_event(
                _logger,
                "extract.malformed_message",
                level=logging.ERROR,
                code="MALFORMED_MESSAGE",
            )
            raise StageFailed("MALFORMED_MESSAGE", Stage.EXTRACT) from None

        with correlation_span(
            "pipeline.extract",
            message.correlation_id,
            kind=SpanKind.CONSUMER,
            invoice_id=message.invoice_id,
            stage=Stage.EXTRACT,
            attempt=message.attempt,
        ):
            started = time.perf_counter()
            try:
                outcome = await extract(message, deps)
                if outcome.action is ExtractAction.RETRY:
                    # AD-7: the same message (ids, first enqueue time, attempt) after
                    # Retry-After; the host then completes the original.
                    await deps.queue.send(
                        QueueName.EXTRACT, message, delay_seconds=outcome.delay_seconds
                    )
                elif outcome.enqueue is not None:
                    await deps.queue.send(
                        outcome.enqueue,
                        QueueMessage.first(
                            message.invoice_id,
                            message.correlation_id,
                            (clock or _now)(),
                        ),
                    )
            except DatabaseOfflineError:
                raise
            except Exception as error:  # noqa: BLE001  # re-raised as StageFailed
                code = (
                    error.code
                    if isinstance(error, ExtractionError)
                    else failure_code(error)
                )
                log_event(
                    _logger,
                    "extract.failed",
                    level=logging.ERROR,
                    invoice_id=message.invoice_id,
                    code=code,
                    attempt=message.attempt,
                )
                raise StageFailed(code, Stage.EXTRACT) from None
            done: dict[str, object] = {
                "invoice_id": message.invoice_id,
                "code": outcome.action,
                "duration_ms": round((time.perf_counter() - started) * 1000),
            }
            if outcome.reason is not None:
                done["reason"] = outcome.reason
            if outcome.action is ExtractAction.RETRY:
                done["queue"] = QueueName.EXTRACT
            elif outcome.enqueue is not None:
                done["queue"] = outcome.enqueue
            log_event(_logger, "extract.done", level=logging.INFO, **done)
        return outcome

    return handle
