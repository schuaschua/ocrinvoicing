"""The `quality` stage (AD-5, AD-6, AD-9, CAP-3): the first pipeline step, fed by
`q-quality`.

1. An invoice already past `received` is a redelivery: re-enqueue `q-extract` when it
   is `awaiting_extraction` (the enqueue after the commit may have been lost, AD-2),
   otherwise only acknowledge.
2. Read `images/<invoice_id>` and create the invoice row from its metadata, unless it
   exists (`INSERT ... ON CONFLICT DO NOTHING`); the supplier comes from the metadata
   only.
3. Check readability again with the page's measures and thresholds, EXIF orientation
   applied; count a PDF's pages; read `photo_taken_at` and the phash.
4. Move `received -> awaiting_extraction`, or `route_to_admin(UNREADABLE |
   UNSUPPORTED_DOCUMENT)`, saving `photo_taken_at` and the phash in the same
   transaction. Zero rows changed: read the status and apply step 1's rule.
5. After the commit, enqueue `q-extract` when the invoice advanced.

The stage returns an outcome (`advance`, `route` or `ack`) and enqueues only after the
transaction, so a crash in between is recovered by redelivery (and the 2.2 sweeper).
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from opentelemetry.trace import SpanKind
from pydantic import ValidationError

from invoicing.adapters.documents import PdfFacts, read_document
from invoicing.adapters.logging import log_event
from invoicing.adapters.telemetry import correlation_span
from invoicing.domain.errors import ServiceUnavailableError
from invoicing.domain.quality import QualityThresholds, image_reason, pdf_reason
from invoicing.domain.reasons import ReasonCode
from invoicing.domain.status import InvoiceStatus, Stage, requeue_after_redelivery
from invoicing.domain.transitions import plan_transition, route_to_admin
from invoicing.ports.blobs import ImageNotFoundError, ImageReader
from invoicing.ports.intake import IntakeBlobMetadata, IntakeSource
from invoicing.ports.invoices import InvoiceRepository, NewInvoice, QualityFacts
from invoicing.ports.messages import QueueMessage
from invoicing.ports.queue import QueueName, QueueSender

ACTOR = "pipeline:quality"

# The queue that feeds each stage (AD-2).
STAGE_QUEUES: Mapping[Stage, QueueName] = {
    Stage.QUALITY: QueueName.QUALITY,
    Stage.EXTRACT: QueueName.EXTRACT,
    Stage.VALIDATE: QueueName.VALIDATE,
    Stage.POST: QueueName.POST,
}

_logger = logging.getLogger("invoicing.pipeline.quality")


class StageFailed(Exception):
    """The stage failed and the message is retried (poison handling is Story 2.2).
    Raised `from None` with a fixed text and a code only, so the host never logs the
    original exception's text, which may hold values (security.md rule 31)."""

    def __init__(self, code: str) -> None:
        super().__init__(f"quality stage failed: {code}")
        self.code = code


# Codes for the failures the stage expects; any other is named by its class.
_FAILURE_CODES: Mapping[type[Exception], str] = {
    ImageNotFoundError: "IMAGE_NOT_FOUND",
    ServiceUnavailableError: "STORAGE_UNAVAILABLE",
}


def _failure_code(error: Exception) -> str:
    if isinstance(error, StageFailed):
        return error.code
    for kind, code in _FAILURE_CODES.items():
        if isinstance(error, kind):
            return code
    return type(error).__name__


def _check_metadata(metadata: IntakeBlobMetadata, invoice_id: UUID) -> None:
    """Refuse metadata the invoice row can't be created from, with a code, before
    anything is written (a check constraint would otherwise fail on every retry)."""
    if metadata.invoice_id != invoice_id:
        raise StageFailed("METADATA_INVOICE_MISMATCH")
    # AD-5: a goods-in scan names its delivery; a supplier upload has none.
    if (metadata.source is IntakeSource.GOODS_IN) != (metadata.delivery_id is not None):
        raise StageFailed("SOURCE_DELIVERY_MISMATCH")


class Action(StrEnum):
    """What the stage did with a message."""

    ADVANCE = "advance"
    ROUTE = "route"
    ACK = "ack"


@dataclass(frozen=True)
class QualityOutcome:
    """The stage's result: what it did, the queue to send the next message to after
    the commit (if any) and, for a routing, the reason."""

    action: Action
    enqueue: QueueName | None = None
    reason: ReasonCode | None = None


def _redelivered(status: InvoiceStatus | None) -> QualityOutcome:
    """AD-2: the stage already ran. Its final target re-enqueues the next stage."""
    following = requeue_after_redelivery(Stage.QUALITY, status)
    return QualityOutcome(
        Action.ACK, None if following is None else STAGE_QUEUES[following]
    )


async def check_quality(
    message: QueueMessage,
    images: ImageReader,
    invoices: InvoiceRepository,
    thresholds: QualityThresholds,
) -> QualityOutcome:
    """Steps 1-4 for one message. Raises `ImageNotFoundError` when the upload
    original is missing and `StageFailed` for metadata the row can't be created from
    (retried; poison handling is Story 2.2)."""
    invoice_id = message.invoice_id
    status = await invoices.status(invoice_id)
    if status is not None and status is not InvoiceStatus.RECEIVED:
        return _redelivered(status)

    stored = await images.get(invoice_id)
    _check_metadata(stored.metadata, invoice_id)
    await invoices.insert_if_absent(
        NewInvoice(stored.metadata, message.correlation_id, ACTOR)
    )

    # Decoding and measuring are CPU-bound: off the event loop.
    facts = await asyncio.to_thread(
        read_document, stored.data, stored.metadata.content_type, thresholds
    )
    if isinstance(facts, PdfFacts):
        reason = pdf_reason(facts.page_count)
        # AD-9: PDFs get the fingerprint check only; they carry no photo time.
        quality = QualityFacts(photo_taken_at=None, phash=None)
    else:
        reason = image_reason(facts.measures, thresholds)
        quality = QualityFacts(photo_taken_at=facts.photo_taken_at, phash=facts.phash)

    if reason is None:
        changed = await invoices.transition(
            plan_transition(
                invoice_id,
                InvoiceStatus.RECEIVED,
                InvoiceStatus.AWAITING_EXTRACTION,
                ACTOR,
            ),
            quality=quality,
        )
        outcome = QualityOutcome(Action.ADVANCE, QueueName.EXTRACT)
    else:
        changed = await invoices.route_to_admin(
            route_to_admin(invoice_id, [reason], InvoiceStatus.RECEIVED, actor=ACTOR),
            quality=quality,
        )
        outcome = QualityOutcome(Action.ROUTE, reason=reason)
    if changed:
        return outcome
    # Another delivery got there first (AD-2).
    return _redelivered(await invoices.status(invoice_id))


def _now() -> datetime:
    return datetime.now(UTC)


type QualityHandler = Callable[[str | bytes], Awaitable[QualityOutcome]]


def quality_handler(
    images: ImageReader,
    invoices: InvoiceRepository,
    queue: QueueSender,
    thresholds: QualityThresholds,
    clock: Callable[[], datetime] | None = None,
) -> QualityHandler:
    """The `q-quality` message handler: parse, check, then enqueue after the commit.
    Any failure is raised, so the host retries the message (`maxDequeueCount` 5)."""

    async def handle(body: str | bytes) -> QualityOutcome:
        try:
            message = QueueMessage.from_json(body)
        except ValidationError:
            # The text may be anything a producer sent: log a code only.
            log_event(
                _logger,
                "quality.malformed_message",
                level=logging.ERROR,
                code="MALFORMED_MESSAGE",
            )
            raise StageFailed("MALFORMED_MESSAGE") from None

        with correlation_span(
            "pipeline.quality",
            message.correlation_id,
            kind=SpanKind.CONSUMER,
            invoice_id=message.invoice_id,
            stage=Stage.QUALITY,
            attempt=message.attempt,
        ):
            started = time.perf_counter()
            try:
                outcome = await check_quality(message, images, invoices, thresholds)
                if outcome.enqueue is not None:
                    await queue.send(
                        outcome.enqueue,
                        QueueMessage.first(
                            message.invoice_id,
                            message.correlation_id,
                            (clock or _now)(),
                        ),
                    )
            except Exception as error:  # noqa: BLE001  # re-raised as StageFailed
                # The exception text may hold values: log a code, raise only the code.
                code = _failure_code(error)
                log_event(
                    _logger,
                    "quality.failed",
                    level=logging.ERROR,
                    invoice_id=message.invoice_id,
                    code=code,
                    attempt=message.attempt,
                )
                raise StageFailed(code) from None
            done: dict[str, object] = {
                "invoice_id": message.invoice_id,
                "code": outcome.action,
                "duration_ms": round((time.perf_counter() - started) * 1000),
            }
            # Only what applies, so nothing is dropped as empty.
            if outcome.reason is not None:
                done["reason"] = outcome.reason
            if outcome.enqueue is not None:
                done["queue"] = outcome.enqueue
            log_event(_logger, "quality.done", level=logging.INFO, **done)
        return outcome

    return handle
