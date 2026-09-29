"""The `validate` stage (Stories 2.5 and 2.6, AD-3, AD-4, AD-6, AD-9, AD-10, AD-18,
AD-19), fed by `q-validate`.

1. Claim `awaiting_validation -> validating` with a 10-minute lease (or reclaim an
   expired one). Zero rows: the invoice moved on; re-enqueue `q-post` when it is
   already `ready_to_post` (AD-2), otherwise only acknowledge.
2. Read the invoice's facts and its AD-18 current values through the one domain
   function. No extraction run: raised with a code (host retry, then poison).
3. Read the delivery, PO and receipts from purchasing (AD-10) and the supplier's
   master row, before any transaction: they are other systems' data.
4. Run the confidence, printed-supplier, photo-date and bank checks, then, in one
   transaction under the per-supplier advisory lock (AD-9), read the other invoices'
   current quantities and the earlier invoices' duplicate facts, run the PO match
   and the duplicate check, save the line matches and `po_number`, and either route
   every failing reason at once (AD-4) or move to `ready_to_post`.
5. After the commit, delete the supplier's reminder row for a matched PO (AD-6, best
   effort: a failure is logged with a code and never fails the invoice), and the
   handler enqueues `q-post`.

- Zero rows changed by the finish: the result is discarded, nothing is written and
  the message is acknowledged (AD-2).
- Any failure ends the lease and is raised with a code, so the host retries the
  message and, after 5 tries, the poison trigger routes `PROCESSING_FAILED`.
- A stopped database is waited out (dbwait.py, AD-7).

Supplier identity is always `intake.invoice.supplier_id`, never OCR's (P-5). Logs hold
ids, codes and timings only, never a field value (security.md rule 31).
"""

import logging
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from opentelemetry.trace import SpanKind
from pydantic import ValidationError
from rapidfuzz import fuzz

from invoicing.adapters.logging import MAX_VALUE_LENGTH, log_event
from invoicing.adapters.telemetry import correlation_span
from invoicing.apps.pipeline.quality import StageFailed, failure_code
from invoicing.domain.current_values import CurrentValues
from invoicing.domain.errors import DatabaseOfflineError
from invoicing.domain.reasons import ReasonCode
from invoicing.domain.status import (
    CLAIM_STATUS,
    InvoiceStatus,
    Stage,
    requeue_after_redelivery,
)
from invoicing.domain.transitions import (
    AdminReason,
    AdminRouting,
    Transition,
    plan_claim,
    plan_transition,
    route_to_admin,
)
from invoicing.domain.validation import (
    DuplicateFacts,
    PoLineRef,
    PoRef,
    Similarity,
    check_bank,
    check_confidence,
    check_duplicate,
    check_photo_date,
    check_po,
    check_printed_supplier,
    duplicate_facts,
    printed_po_number,
)
from invoicing.ports.intake import IntakeSource
from invoicing.ports.invoices import InvoiceRepository
from invoicing.ports.messages import QueueMessage
from invoicing.ports.purchasing import PurchaseOrder, PurchasingPort
from invoicing.ports.queue import STAGE_QUEUES, QueueName, QueueSender
from invoicing.ports.reminders import ReminderStore
from invoicing.ports.suppliers import SupplierReader
from invoicing.ports.validation import (
    InvoiceFacts,
    ValidationRepository,
    ValidationResult,
)

ACTOR = "pipeline:validate"
# Raised (host retry, then poison) when the invoice has no extraction run to validate.
NO_EXTRACTION_RUN = "NO_EXTRACTION_RUN"
INVOICE_NOT_FOUND = "INVOICE_NOT_FOUND"
# Logged when a matched PO's reminder row could not be deleted (the invoice goes on).
REMINDER_DELETE_FAILED = "REMINDER_DELETE_FAILED"

_logger = logging.getLogger("invoicing.pipeline.validate")


def token_set_ratio(first: str, second: str) -> float:
    """AD-19's name similarity (0-100): rapidfuzz's token-set ratio."""
    return float(fuzz.token_set_ratio(first, second))


class ValidateAction(StrEnum):
    """What the stage did with a message."""

    ADVANCE = "advance"
    ROUTE = "route"
    ACK = "ack"


@dataclass(frozen=True)
class ValidateOutcome:
    """The stage's result: what it did, the queue to send the next message to after
    the commit (if any), and the reasons of a routing."""

    action: ValidateAction
    enqueue: QueueName | None = None
    reasons: tuple[ReasonCode, ...] = ()


@dataclass(frozen=True)
class ValidateDependencies:
    """What the stage reaches outside itself; tests pass fakes for the queue."""

    invoices: InvoiceRepository
    validations: ValidationRepository
    purchasing: PurchasingPort
    suppliers: SupplierReader
    queue: QueueSender
    reminders: ReminderStore
    similarity: Similarity = token_set_ratio


@dataclass(frozen=True)
class _PurchasingFacts:
    po_number: str | None
    po: PoRef | None
    received: Mapping[UUID, Decimal] | None
    # The latest received date of those receipts (AD-19's photo date check).
    latest_receipt: date | None = None


def _redelivered(status: InvoiceStatus | None) -> ValidateOutcome:
    """AD-2: the stage already ran. Its final target re-enqueues the next stage."""
    following = requeue_after_redelivery(Stage.VALIDATE, status)
    return ValidateOutcome(
        ValidateAction.ACK, None if following is None else STAGE_QUEUES[following]
    )


def _po_ref(po: PurchaseOrder) -> PoRef:
    return PoRef(
        po_number=po.po_number,
        supplier_id=po.supplier_id,
        lines=tuple(
            PoLineRef(
                po_line_id=line.po_line_id,
                material_id=line.material_id,
                supplier_product_code=line.supplier_product_code,
                unit_price=line.unit_price,
            )
            for line in po.lines
        ),
    )


async def _purchasing(
    facts: InvoiceFacts, values: CurrentValues, purchasing: PurchasingPort
) -> _PurchasingFacts:
    """AD-19: the PO is the printed one for an upload, the delivery's for a goods-in
    scan; received is every receipt of the PO for an upload, only the delivery's
    receipt for a scan (None when there is no receipt)."""
    goods_in = facts.source is IntakeSource.GOODS_IN
    if goods_in:
        delivery = (
            None
            if facts.delivery_id is None
            else await purchasing.get_delivery(facts.delivery_id)
        )
        po_number = None if delivery is None else delivery.po_number
    else:
        po_number = printed_po_number(values)
    order = None if po_number is None else await purchasing.get_po(po_number)
    if order is None or order.supplier_id != facts.supplier_id:
        # check_po routes these without needing receipts.
        return _PurchasingFacts(
            po_number, None if order is None else _po_ref(order), None
        )
    receipts = await purchasing.get_receipts(order.po_number)
    if goods_in:
        receipts = tuple(r for r in receipts if r.delivery_id == facts.delivery_id)
    if not receipts:
        return _PurchasingFacts(po_number, _po_ref(order), None)
    received: dict[UUID, Decimal] = {}
    for receipt in receipts:
        for po_line_id, quantity in receipt.lines.items():
            received[po_line_id] = received.get(po_line_id, Decimal(0)) + quantity
    latest = max(receipt.received_date for receipt in receipts)
    return _PurchasingFacts(po_number, _po_ref(order), received, latest)


async def _delete_reminder(
    reminders: ReminderStore, invoice_id: UUID, supplier_id: UUID, po_number: str
) -> None:
    """AD-6: the invoice for this PO has arrived, so the supplier's weekly reminder for
    it stops. Best effort, after the commit: a failure is logged with a code and never
    fails or retries the invoice (the worst case is one more weekly reminder)."""
    try:
        await reminders.delete(supplier_id, po_number)
    except Exception:  # noqa: BLE001  # best effort: logged by a code, never raised
        log_event(
            _logger,
            "validate.reminder_delete_failed",
            level=logging.WARNING,
            invoice_id=invoice_id,
            code=REMINDER_DELETE_FAILED,
        )


async def validate(
    message: QueueMessage, deps: ValidateDependencies
) -> ValidateOutcome:
    """Steps 1-5 for one parsed message. Raises storage and purchasing errors, and
    `StageFailed` for an invoice with no run, for a host retry, with the lease
    ended."""
    invoice_id = message.invoice_id
    claim = plan_claim(invoice_id, Stage.VALIDATE, ACTOR)
    if not await deps.invoices.claim(claim):
        return _redelivered(await deps.invoices.status(invoice_id))
    claimed = CLAIM_STATUS[Stage.VALIDATE]
    try:
        loaded = await deps.validations.load(invoice_id)
        if loaded is None:
            raise StageFailed(INVOICE_NOT_FOUND, Stage.VALIDATE)
        facts, values = loaded.facts, loaded.values
        if values is None:
            raise StageFailed(NO_EXTRACTION_RUN, Stage.VALIDATE)
        supplier_upload = facts.source is IntakeSource.LINK
        bought = await _purchasing(facts, values, deps.purchasing)
        master = await deps.suppliers.get(facts.supplier_id)
        confidence = check_confidence(values, supplier_upload=supplier_upload)
        printed = check_printed_supplier(
            values,
            master_name=None if master is None else master.name,
            master_tax_id=None if master is None else master.tax_id,
            similarity=deps.similarity,
        )
        photo_date = check_photo_date(
            facts.photo_taken_at, bought.latest_receipt, run_id=values.run_id
        )
        bank = check_bank(values, loaded.master_bank)
        own = duplicate_facts(invoice_id, values, phash=facts.phash)
        routed: list[AdminReason] = []
        saved_po: list[str | None] = [None]

        def compute(
            invoiced_elsewhere: Mapping[UUID, Decimal],
            earlier: Sequence[DuplicateFacts],
        ) -> ValidationResult:
            po = check_po(
                values,
                po_number=bought.po_number,
                po=bought.po,
                supplier_id=facts.supplier_id,
                received=bought.received,
                invoiced_elsewhere=invoiced_elsewhere,
                supplier_upload=supplier_upload,
            )
            # AD-9: decided here, under the supplier lock, against earlier ids only.
            duplicate = check_duplicate(own, earlier)
            reasons = [
                r
                for r in (confidence, po.reason, printed, duplicate, photo_date, bank)
                if r is not None
            ]
            routed[:] = reasons
            saved_po[0] = po.po_number
            finish: Transition | AdminRouting = (
                route_to_admin(invoice_id, reasons, claimed, actor=ACTOR)
                if reasons
                else plan_transition(
                    invoice_id, claimed, InvoiceStatus.READY_TO_POST, ACTOR
                )
            )
            return ValidationResult(
                po_number=po.po_number,
                matches={line.id: po.matches.get(line.id) for line in values.lines},
                finish=finish,
            )

        if not await deps.validations.finish_locked(
            invoice_id, facts.supplier_id, compute
        ):
            return _redelivered(await deps.invoices.status(invoice_id))
        if saved_po[0] is not None:
            await _delete_reminder(
                deps.reminders, invoice_id, facts.supplier_id, saved_po[0]
            )
        if routed:
            return ValidateOutcome(
                ValidateAction.ROUTE, reasons=tuple(r.reason for r in routed)
            )
        return ValidateOutcome(ValidateAction.ADVANCE, QueueName.POST)
    except DatabaseOfflineError:
        raise
    except Exception:
        # The host retries this message now: let that retry reclaim (AD-3).
        await deps.invoices.release_claim(claim)
        raise


def _now() -> datetime:
    return datetime.now(UTC)


type ValidateHandler = Callable[[str | bytes], Awaitable[ValidateOutcome]]


def validate_handler(
    deps: ValidateDependencies, clock: Callable[[], datetime] | None = None
) -> ValidateHandler:
    """The `q-validate` message handler: parse, validate, then enqueue after the
    commit. A failure is raised as `StageFailed` with a code, so the host retries the
    message (`maxDequeueCount` 5). `DatabaseOfflineError` is raised as it is, for the
    AD-7 wait (dbwait.py)."""

    async def handle(body: str | bytes) -> ValidateOutcome:
        try:
            message = QueueMessage.from_json(body)
        except ValidationError:
            log_event(
                _logger,
                "validate.malformed_message",
                level=logging.ERROR,
                code="MALFORMED_MESSAGE",
            )
            raise StageFailed("MALFORMED_MESSAGE", Stage.VALIDATE) from None

        with correlation_span(
            "pipeline.validate",
            message.correlation_id,
            kind=SpanKind.CONSUMER,
            invoice_id=message.invoice_id,
            stage=Stage.VALIDATE,
            attempt=message.attempt,
        ):
            started = time.perf_counter()
            try:
                outcome = await validate(message, deps)
                if outcome.enqueue is not None:
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
                code = failure_code(error)
                log_event(
                    _logger,
                    "validate.failed",
                    level=logging.ERROR,
                    invoice_id=message.invoice_id,
                    code=code,
                    attempt=message.attempt,
                )
                raise StageFailed(code, Stage.VALIDATE) from None
            done: dict[str, object] = {
                "invoice_id": message.invoice_id,
                "code": outcome.action,
                "duration_ms": round((time.perf_counter() - started) * 1000),
            }
            if outcome.reasons:
                # Codes only. Up to six can fail together, longer than one log value
                # may be (logging.py MAX_VALUE_LENGTH): then one event per reason.
                joined = ",".join(outcome.reasons)
                if len(joined) <= MAX_VALUE_LENGTH:
                    done["reason"] = joined
                else:
                    done["count"] = len(outcome.reasons)
                    for reason in outcome.reasons:
                        log_event(
                            _logger,
                            "validate.reason",
                            level=logging.INFO,
                            invoice_id=message.invoice_id,
                            reason=reason,
                        )
            if outcome.enqueue is not None:
                done["queue"] = outcome.enqueue
            log_event(_logger, "validate.done", level=logging.INFO, **done)
        return outcome

    return handle
