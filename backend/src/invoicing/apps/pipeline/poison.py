"""The poison triggers (AD-2, AD-4): one per stage queue's `<queue>-poison`, where the
Functions host moves a message after `maxDequeueCount` (5) failures.

For each poison message:

1. Read the invoice's status and lease.
2. Route `PROCESSING_FAILED` only while the invoice is still in that queue's input
   status, or in its claim status with an expired lease (`domain.status.
   poison_route_from`); the conditional transition re-checks the lease, so a live
   claim is never taken. Anything else has moved on: acknowledge only.
3. `q-quality` with no invoice row: create it from the blob's `IntakeBlobMetadata`
   (read from its properties; the bytes are never downloaded) inside
   `route_to_admin` (AD-4). With no blob either, or metadata a row can't be made
   from, log a code and acknowledge.
4. Emit `poison_message{queue}` (AD-17) once, on the message's final outcome; it
   alerts when above 0 in an hour.

A failure is raised for a host retry, except on the poison message's last delivery
(`MAX_DEQUEUE_COUNT`): the host would move it to an unwatched `<queue>-poison-poison`,
so it is logged as `POISON_ABANDONED`, counted and acknowledged instead. A stopped
database is waited out like any consumer (dbwait.py, AD-7): no metric then, because
the message is handled when it comes back.
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from opentelemetry.trace import SpanKind
from pydantic import ValidationError

from invoicing.adapters.logging import log_event, log_unsampled_event
from invoicing.adapters.telemetry import correlation_span
from invoicing.apps.pipeline.quality import StageFailed, check_metadata
from invoicing.domain.errors import DatabaseOfflineError
from invoicing.domain.reasons import ReasonCode
from invoicing.domain.status import CLAIM_STATUS, Stage, poison_route_from
from invoicing.domain.transitions import AdminReason, route_to_admin
from invoicing.ports.blobs import ImageNotFoundError, ImageReader
from invoicing.ports.invoices import InvoiceRepository, NewInvoice
from invoicing.ports.messages import QueueMessage
from invoicing.ports.metrics import MetricName, MetricsPort
from invoicing.ports.queue import POISON_QUEUES, STAGE_QUEUES

ACTOR = "pipeline:poison"
# host.json `maxDequeueCount`: the delivery after which the host gives up on a message.
MAX_DEQUEUE_COUNT = 5

_logger = logging.getLogger("invoicing.pipeline.poison")


class PoisonAction(StrEnum):
    """What the trigger did with a poison message."""

    ROUTE = "route"
    ACK = "ack"


@dataclass(frozen=True)
class PoisonOutcome:
    """The result and a code: `ROUTED`, or why it was only acknowledged."""

    action: PoisonAction
    code: str


def _ack(code: str) -> PoisonOutcome:
    return PoisonOutcome(PoisonAction.ACK, code)


class PoisonFailed(Exception):
    """Handling failed; the host retries the poison message. Raised `from None` with
    a code only, like `StageFailed`, so no value reaches the host's log."""

    def __init__(self, code: str) -> None:
        super().__init__(f"poison handling failed: {code}")
        self.code = code


async def handle_poison(
    stage: Stage,
    message: QueueMessage,
    images: ImageReader,
    invoices: InvoiceRepository,
    clock: Callable[[], datetime],
) -> PoisonOutcome:
    """Steps 1-3 for one parsed poison message of `stage`."""
    invoice_id = message.invoice_id
    state = await invoices.state(invoice_id)
    if state is None:
        from_status = poison_route_from(stage, None, None, clock())
    else:
        from_status = poison_route_from(
            stage, state.status, state.claimed_until, state.now, state.next_attempt_at
        )
    if from_status is None:
        return _ack("ROW_MISSING" if state is None else "MOVED_ON")

    metadata: NewInvoice | None = None
    if state is None:
        # AD-4: route_to_admin creates the missing row from the blob's metadata.
        try:
            blob_metadata = await images.metadata(invoice_id)
            check_metadata(blob_metadata, invoice_id)
        except ImageNotFoundError:
            return _ack("IMAGE_NOT_FOUND")
        except ValueError:
            return _ack("BAD_METADATA")
        except StageFailed as error:
            return _ack(error.code)
        metadata = NewInvoice(blob_metadata, message.correlation_id, ACTOR)

    routing = route_to_admin(
        invoice_id,
        [
            AdminReason(
                ReasonCode.PROCESSING_FAILED,
                detail={"queue": STAGE_QUEUES[stage].value},
            )
        ],
        from_status,
        actor=ACTOR,
        # From a claim state the trigger does not hold: only an expired lease (AD-2).
        require_expired_lease=from_status is CLAIM_STATUS.get(stage),
    )
    if await invoices.route_to_admin(routing, metadata=metadata):
        return PoisonOutcome(PoisonAction.ROUTE, "ROUTED")
    # The invoice moved (or was claimed) between the read and the transition.
    return _ack("MOVED_ON")


type PoisonHandler = Callable[[str | bytes, int], Awaitable[PoisonOutcome]]


def _now() -> datetime:
    return datetime.now(UTC)


def poison_handler(
    stage: Stage,
    images: ImageReader,
    invoices: InvoiceRepository,
    metrics: MetricsPort,
    clock: Callable[[], datetime] | None = None,
) -> PoisonHandler:
    """The `<queue>-poison` message handler for `stage`, given the body and the
    host's dequeue count. Raises `DatabaseOfflineError` for the AD-7 wait and
    `PoisonFailed` for anything unexpected (retried), until the last delivery."""
    queue = POISON_QUEUES[stage]

    def _emit() -> None:
        metrics.emit_metric(MetricName.POISON_MESSAGE, 1, {"queue": queue.value})

    async def handle(body: str | bytes, dequeue_count: int = 1) -> PoisonOutcome:
        try:
            message = QueueMessage.from_json(body)
        except ValidationError:
            # Nothing can be routed without an invoice id; it is still counted.
            _emit()
            log_unsampled_event(
                _logger,
                "poison.done",
                level=logging.ERROR,
                queue=queue,
                code="MALFORMED_MESSAGE",
            )
            return _ack("MALFORMED_MESSAGE")

        with correlation_span(
            "pipeline.poison",
            message.correlation_id,
            kind=SpanKind.CONSUMER,
            invoice_id=message.invoice_id,
            stage=stage,
            queue=queue,
            attempt=message.attempt,
        ):
            try:
                outcome = await handle_poison(
                    stage, message, images, invoices, clock or _now
                )
            except DatabaseOfflineError:
                raise
            except Exception as error:  # noqa: BLE001  # re-raised as PoisonFailed
                code = type(error).__name__
                if dequeue_count >= MAX_DEQUEUE_COUNT:
                    # The final outcome: nothing watches `<queue>-poison-poison`.
                    _emit()
                    log_unsampled_event(
                        _logger,
                        "poison.done",
                        level=logging.ERROR,
                        queue=queue,
                        invoice_id=message.invoice_id,
                        attempt=message.attempt,
                        code="POISON_ABANDONED",
                        reason=code,
                    )
                    return _ack("POISON_ABANDONED")
                log_event(
                    _logger,
                    "poison.failed",
                    level=logging.ERROR,
                    queue=queue,
                    invoice_id=message.invoice_id,
                    code=code,
                )
                raise PoisonFailed(code) from None
            _emit()
            log_unsampled_event(
                _logger,
                "poison.done",
                level=logging.WARNING,
                queue=queue,
                invoice_id=message.invoice_id,
                attempt=message.attempt,
                code=outcome.code,
            )
        return outcome

    return handle
