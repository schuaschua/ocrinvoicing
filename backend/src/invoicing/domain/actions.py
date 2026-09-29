"""The admin actions of Story 2.10 (AD-3, AD-4, AD-18, UX-DR12): which actions an
invoice's open reasons allow, and how a Correct request becomes admin rows.

Pure. The item read lists `allowed_actions` and every action endpoint re-checks it
inside its transaction, so the screen and the server apply one guard.

EXPERIENCE.md "Allowed actions by reason" and its multi-reason rule: Correct if any
open reason allows it; Re-extract only if every one does; Retry intake in place of
Re-extract for `PROCESSING_FAILED` before the quality stage completed; Reject always,
unless the invoice has an `accounts_ref`. Approve is Story 3.3, so an invoice with an
`accounts_ref` has no action here.
"""

import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from types import MappingProxyType
from uuid import UUID

from invoicing.domain.current_values import CurrentValues, FieldValue, LineValue
from invoicing.domain.errors import ValidationFailedError
from invoicing.domain.extraction import (
    CHECKED_HEADER_FIELDS,
    CHECKED_IF_RETURNED_FIELD,
    UPLOAD_CHECKED_FIELD,
    is_bank_field_id,
)
from invoicing.domain.reasons import ReasonCode
from invoicing.domain.status import InvoiceStatus


class AdminAction(StrEnum):
    """An admin action of Story 2.10, by its API name."""

    CORRECT = "correct"
    REEXTRACT = "reextract"
    RETRY_INTAKE = "retry_intake"
    REJECT = "reject"


_R = ReasonCode
_A = AdminAction

# EXPERIENCE.md "Allowed actions by reason", without Approve (Story 3.3).
REASON_ACTIONS: Mapping[ReasonCode, frozenset[AdminAction]] = MappingProxyType(
    {
        _R.UNREADABLE: frozenset({_A.REJECT}),
        _R.UNSUPPORTED_DOCUMENT: frozenset({_A.REJECT}),
        _R.EXTRACTION_QUOTA: frozenset({_A.REEXTRACT, _A.REJECT}),
        _R.PROCESSING_FAILED: frozenset({_A.REEXTRACT, _A.REJECT}),
        _R.LOW_CONFIDENCE: frozenset({_A.CORRECT, _A.REJECT}),
        _R.PO_MISMATCH: frozenset({_A.CORRECT, _A.REJECT}),
        _R.DATE_MISMATCH: frozenset({_A.CORRECT, _A.REJECT}),
        _R.NO_PHOTO_DATE: frozenset({_A.CORRECT, _A.REJECT}),
        _R.SUPPLIER_ID_MISMATCH: frozenset({_A.CORRECT, _A.REJECT}),
        _R.DUPLICATE: frozenset({_A.REJECT}),
        _R.BANK_CHANGED: frozenset({_A.REJECT}),
        _R.ACCOUNTS_API_ERROR: frozenset({_A.REJECT}),
    }
)

# Where each action moves the invoice from `in_admin_queue` (AD-3).
TARGET_STATUS: Mapping[AdminAction, InvoiceStatus] = MappingProxyType(
    {
        _A.CORRECT: InvoiceStatus.AWAITING_VALIDATION,
        _A.REEXTRACT: InvoiceStatus.AWAITING_EXTRACTION,
        _A.RETRY_INTAKE: InvoiceStatus.RECEIVED,
        _A.REJECT: InvoiceStatus.REJECTED,
    }
)

# The `audit.event` action each one writes.
AUDIT_ACTION: Mapping[AdminAction, str] = MappingProxyType(
    {
        _A.CORRECT: "invoice.corrected",
        _A.REEXTRACT: "invoice.reextracted",
        _A.RETRY_INTAKE: "invoice.intake_retried",
        _A.REJECT: "invoice.rejected",
    }
)

_ORDER = (_A.CORRECT, _A.REEXTRACT, _A.RETRY_INTAKE, _A.REJECT)


def allowed_actions(
    reasons: Collection[str], *, accounts_ref: bool, quality_done: bool
) -> tuple[AdminAction, ...]:
    """The actions the open reasons allow, in button order. `reasons` are the codes of
    the latest routing (AD-4); a code this build doesn't know allows only Reject."""
    if accounts_ref:
        # AD-3: once in the accounts system only Approve (re-post) is safe (3.3).
        return ()
    per_reason = [_actions_for(reason) for reason in reasons]
    allowed = {_A.REJECT}
    if any(_A.CORRECT in actions for actions in per_reason):
        allowed.add(_A.CORRECT)
    if per_reason and all(_A.REEXTRACT in actions for actions in per_reason):
        failed_before_quality = (
            _R.PROCESSING_FAILED.value in reasons and not quality_done
        )
        # AD-3: with no quality decision there is nothing to extract from yet; the
        # upload goes through the quality stage again instead.
        allowed.add(_A.RETRY_INTAKE if failed_before_quality else _A.REEXTRACT)
    return tuple(action for action in _ORDER if action in allowed)


def _actions_for(reason: str) -> frozenset[AdminAction]:
    try:
        return REASON_ACTIONS[ReasonCode(reason)]
    except (ValueError, KeyError):
        return frozenset({_A.REJECT})


# --- Correct --------------------------------------------------------------------------

# Reject's reason is the only free text an action takes (UX-DR12).
MAX_REJECT_REASON = 500
# A corrected value: longer than any invoice field.
MAX_VALUE_LENGTH = 200
# The editable line columns; unit, tax, po_line_id and material_id are copied.
LINE_TEXT_COLUMNS = ("product_code", "description")
LINE_NUMBER_COLUMNS = ("quantity", "unit_price", "amount")
LINE_COLUMNS = LINE_TEXT_COLUMNS + LINE_NUMBER_COLUMNS
# A missing field the admin may add: the AD-18 checked header fields.
ADDABLE_FIELDS = (
    *CHECKED_HEADER_FIELDS,
    UPLOAD_CHECKED_FIELD,
    CHECKED_IF_RETURNED_FIELD,
)

_DATE_FIELDS = frozenset({"invoice_date", "due_date"})
_NUMBER_FIELDS = frozenset({"sub_total", "invoice_total", "total_tax", "amount_due"})
_NUMBER = re.compile(r"-?[0-9]{1,15}(\.[0-9]{1,6})?")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


class FieldKind(StrEnum):
    """Which `invoice_field` value column a field is stored in."""

    TEXT = "text"
    NUMBER = "number"
    DATE = "date"


@dataclass(frozen=True)
class FieldCorrection:
    """One corrected header field: exactly one value set, as its column stores it.
    `currency`, `page` and `polygon` are the current row's, so the box still shows."""

    field_id: str
    value_text: str | None = None
    value_number: Decimal | None = None
    value_date: date | None = None
    currency: str | None = None
    page: int | None = None
    polygon: tuple[float, ...] | None = None

    @property
    def wire_value(self) -> str:
        """The value as the admin typed it back (for the corrections blob)."""
        if self.value_number is not None:
            return str(self.value_number)
        if self.value_date is not None:
            return self.value_date.isoformat()
        return self.value_text or ""


@dataclass(frozen=True)
class LineCorrection:
    """One corrected line as a complete row (AD-18): the edited columns, and every
    other column copied from the current row."""

    line_no: int
    product_code: str | None
    description: str | None
    quantity: Decimal | None
    unit: str | None
    unit_price: Decimal | None
    amount: Decimal | None
    tax: Decimal | None
    po_line_id: UUID | None
    material_id: UUID | None


@dataclass(frozen=True)
class Correction:
    """What one Save and re-check writes, on the latest run."""

    run_id: UUID
    fields: tuple[FieldCorrection, ...]
    lines: tuple[LineCorrection, ...]


type LineEdits = Mapping[int, Mapping[str, str | None]]


def field_kind(field_id: str, current: FieldValue | None) -> FieldKind:
    """The column a value of `field_id` goes in: the current row's, else the field's
    DI type."""
    if current is not None:
        if current.value_number is not None:
            return FieldKind.NUMBER
        if current.value_date is not None:
            return FieldKind.DATE
        if current.value_text is not None:
            return FieldKind.TEXT
    if field_id in _DATE_FIELDS:
        return FieldKind.DATE
    if field_id in _NUMBER_FIELDS:
        return FieldKind.NUMBER
    return FieldKind.TEXT


def _number(value: str, name: str) -> Decimal:
    text = value.strip()
    if _NUMBER.fullmatch(text) is None:
        raise ValidationFailedError(f"{name} must be a number, like 1250.50.")
    try:
        return Decimal(text)
    except InvalidOperation:
        raise ValidationFailedError(f"{name} must be a number.") from None


def _date(value: str, name: str) -> date:
    text = value.strip()
    try:
        if _DATE.fullmatch(text) is None:
            raise ValueError
        return date.fromisoformat(text)
    except ValueError:
        raise ValidationFailedError(
            f"{name} must be a date, like 2026-09-30."
        ) from None


def _text(value: str, name: str) -> str:
    text = value.strip()
    if not text:
        raise ValidationFailedError(f"{name} needs a value.")
    if len(text) > MAX_VALUE_LENGTH:
        raise ValidationFailedError(f"{name} is too long.")
    return text


def shown(row: FieldValue) -> str | None:
    """A field's value as the admin screen shows it (and sends it back unchanged)."""
    if row.value_text is not None:
        return row.value_text
    if row.value_number is not None:
        return str(row.value_number)
    if row.value_date is not None:
        return row.value_date.isoformat()
    return None


def addable_fields(current: CurrentValues | None) -> tuple[str, ...]:
    """The missing checked header fields an admin may add; none without a run."""
    if current is None:
        return ()
    return tuple(f for f in ADDABLE_FIELDS if f not in current.fields)


def _field(
    field_id: str,
    raw: str,
    current: FieldValue | None,
    currency: str,
) -> FieldCorrection:
    if is_bank_field_id(field_id):
        # AD-11: a wrong bank reading is Approved after a call-back, or Rejected.
        raise ValidationFailedError("Bank fields can't be corrected.")
    if current is None and field_id not in ADDABLE_FIELDS:
        raise ValidationFailedError("That field can't be corrected.")
    page = None if current is None else current.page
    polygon = None if current is None else current.polygon
    if current is not None and current.has_value and raw.strip() == shown(current):
        # A flagged value the admin confirmed unchanged is kept exactly as read, even
        # where it would not pass as typed input (precision, exponent, length).
        return FieldCorrection(
            field_id,
            value_text=current.value_text,
            value_number=current.value_number,
            value_date=current.value_date,
            currency=current.currency,
            page=page,
            polygon=polygon,
        )
    text = _text(raw, "Each value")
    kind = field_kind(field_id, current)
    if kind is FieldKind.NUMBER:
        # An amount is in the invoice currency (AD-8).
        held = None if current is None else current.currency
        return FieldCorrection(
            field_id,
            value_number=_number(text, "An amount"),
            currency=held or currency,
            page=page,
            polygon=polygon,
        )
    if kind is FieldKind.DATE:
        return FieldCorrection(
            field_id, value_date=_date(text, "A date"), page=page, polygon=polygon
        )
    return FieldCorrection(field_id, value_text=text, page=page, polygon=polygon)


def _line_text(
    edits: Mapping[str, str | None], column: str, held: str | None
) -> str | None:
    if column not in edits:
        return held
    raw = edits[column]
    return None if raw is None or not raw.strip() else _text(raw, "A line value")


def _line_number(
    edits: Mapping[str, str | None], column: str, held: Decimal | None
) -> Decimal | None:
    if column not in edits:
        return held
    raw = edits[column]
    if raw is None or not raw.strip():
        return None
    return _number(raw, "A line amount or quantity")


def _line(line: LineValue, edits: Mapping[str, str | None]) -> LineCorrection:
    if set(edits) - set(LINE_COLUMNS):
        raise ValidationFailedError("That line column can't be corrected.")
    return LineCorrection(
        line_no=line.line_no,
        product_code=_line_text(edits, "product_code", line.product_code),
        description=_line_text(edits, "description", line.description),
        quantity=_line_number(edits, "quantity", line.quantity),
        unit=line.unit,
        unit_price=_line_number(edits, "unit_price", line.unit_price),
        amount=_line_number(edits, "amount", line.amount),
        tax=line.tax,
        po_line_id=line.po_line_id,
        material_id=line.material_id,
    )


def plan_correction(
    current: CurrentValues,
    fields: Mapping[str, str],
    lines: LineEdits,
    *,
    currency: str,
) -> Correction:
    """The admin rows of one Correct (AD-18), or `ValidationFailedError` naming no
    value. A field is any current non-bank field or a missing checked header field; a
    line is a current line, written whole."""
    if not fields and not lines:
        raise ValidationFailedError("Change at least one field or line.")
    corrected = tuple(
        _field(field_id, raw, current.fields.get(field_id), currency)
        for field_id, raw in sorted(fields.items())
    )
    by_no = {line.line_no: line for line in current.lines}
    rows: list[LineCorrection] = []
    for line_no in sorted(lines):
        line = by_no.get(line_no)
        if line is None:
            raise ValidationFailedError("That line isn't on this invoice.")
        rows.append(_line(line, lines[line_no]))
    return Correction(run_id=current.run_id, fields=corrected, lines=tuple(rows))
