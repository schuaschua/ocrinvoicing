"""AD-19 validation checks (Story 2.5): confidence, PO match and printed supplier.

Pure: each check reads an invoice's AD-18 current values plus the facts the stage
fetched, and returns the `AdminReason` it fails with (or None), so the stage can route
every failing reason together (AD-4). Money is `Decimal` (coding-style.md rule 4).

The domain uses the standard library only, so the name similarity (rapidfuzz's
`token_set_ratio`, named by AD-19) is passed in by the caller.
"""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from types import MappingProxyType
from uuid import UUID

from invoicing.domain.current_values import (
    ADMIN_SOURCE,
    CurrentValues,
    FieldValue,
    LineValue,
)
from invoicing.domain.extraction import (
    CHECKED_HEADER_FIELDS,
    CHECKED_IF_RETURNED_FIELD,
    CHECKED_LINE_FIELDS,
    UPLOAD_CHECKED_FIELD,
    line_field_id,
)
from invoicing.domain.reasons import ReasonCode
from invoicing.domain.transitions import AdminReason

# P-9 / AD-18: a checked field below this confidence goes to an admin.
CONFIDENCE_THRESHOLD = 0.98
# AD-19: the least token-set similarity (0-100) of the printed and master names.
NAME_SIMILARITY_MIN = 85
# AD-19: sub_total within the larger of 1 % of the expected amount and 1.00.
TOLERANCE_RATE = Decimal("0.01")
TOLERANCE_FLOOR = Decimal("1.00")
CENTS = Decimal("0.01")

SUB_TOTAL = "sub_total"
VENDOR_NAME = "vendor_name"
VENDOR_TAX_ID = "vendor_tax_id"
PURCHASE_ORDER = UPLOAD_CHECKED_FIELD

# Legal-form suffixes dropped from the end of a supplier name, longest first.
LEGAL_SUFFIXES: tuple[tuple[str, ...], ...] = (
    ("private", "limited"),
    ("pte", "ltd"),
    ("sdn", "bhd"),
    ("limited",),
    ("ltd",),
    ("pte",),
    ("inc",),
    ("llc",),
    ("corp",),
    ("co",),
)

type Similarity = Callable[[str, str], float]

_NOT_ALPHANUMERIC = re.compile(r"[\W_]+")
_TAX_ID_NOISE = re.compile(r"[^0-9A-Z]")


class PoProblem:
    """The `detail.problems` codes of a `PO_MISMATCH` item."""

    PO_MISSING = "PO_MISSING"
    PO_UNKNOWN = "PO_UNKNOWN"
    PO_OTHER_SUPPLIER = "PO_OTHER_SUPPLIER"
    NO_LINES = "NO_LINES"
    LINE_UNMATCHED = "LINE_UNMATCHED"
    AMBIGUOUS_PRODUCT_CODE = "AMBIGUOUS_PRODUCT_CODE"
    NO_RECEIPT = "NO_RECEIPT"
    SUB_TOTAL_MISSING = "SUB_TOTAL_MISSING"
    AMOUNT_OUTSIDE_TOLERANCE = "AMOUNT_OUTSIDE_TOLERANCE"


@dataclass(frozen=True)
class PoLineRef:
    """What validation needs of one PO line (AD-10)."""

    po_line_id: UUID
    material_id: UUID
    supplier_product_code: str
    unit_price: Decimal


@dataclass(frozen=True)
class PoRef:
    """What validation needs of one PO: its number, supplier and lines."""

    po_number: str
    supplier_id: UUID
    lines: tuple[PoLineRef, ...]


@dataclass(frozen=True)
class LineMatch:
    """The PO line an invoice line matched (`invoice_line.po_line_id/material_id`)."""

    po_line_id: UUID
    material_id: UUID


def _no_matches() -> Mapping[UUID, LineMatch]:
    return MappingProxyType({})


@dataclass(frozen=True)
class PoCheck:
    """The PO match: the PO to save as `invoice.po_number` (None unless it exists and
    is the supplier's), the matches by invoice line row id, and the reason if any."""

    po_number: str | None
    matches: Mapping[UUID, LineMatch] = field(default_factory=_no_matches)
    reason: AdminReason | None = None


def money(amount: Decimal) -> Decimal:
    """An amount to 2 decimals, half up (AD-19 compares amounts at this precision)."""
    return amount.quantize(CENTS, rounding=ROUND_HALF_UP)


def tolerance(expected: Decimal) -> Decimal:
    """The larger of 1 % of `expected` and 1.00 (AD-19)."""
    return max(money(abs(expected) * TOLERANCE_RATE), TOLERANCE_FLOOR)


def within_tolerance(actual: Decimal, expected: Decimal) -> bool:
    """Whether `actual` is within `tolerance(expected)` of `expected`, both to 0.01."""
    return abs(money(actual) - money(expected)) <= tolerance(money(expected))


def normalise_tax_id(value: str) -> str:
    """A tax id compared as uppercase letters and digits only (AD-19)."""
    return _TAX_ID_NOISE.sub("", value.upper())


def normalise_name(value: str) -> str:
    """A supplier name casefolded, punctuation removed and legal-form suffixes such as
    "Pte Ltd" dropped from its end (AD-19)."""
    tokens = _NOT_ALPHANUMERIC.sub(" ", value.casefold()).split()
    stripped = True
    while stripped:
        stripped = False
        for suffix in LEGAL_SUFFIXES:
            size = len(suffix)
            if len(tokens) > size and tuple(tokens[-size:]) == suffix:
                del tokens[-size:]
                stripped = True
                break
    return " ".join(tokens)


def _field_confidence(row: FieldValue | None) -> float:
    # AD-18: a missing field (no row, or no value read) counts as 0; an admin
    # correction counts as 1.0.
    if row is None or not row.has_value:
        return 0.0
    if row.source == ADMIN_SOURCE:
        return 1.0
    return row.confidence or 0.0


def _low_line_fields(line: LineValue) -> list[str]:
    if line.source == ADMIN_SOURCE:
        return []
    missing = [name for name in CHECKED_LINE_FIELDS if getattr(line, name) is None]
    if missing:
        return [line_field_id(line.line_no, name) for name in missing]
    if line.confidence < CONFIDENCE_THRESHOLD:
        # The line row keeps only its lowest checked confidence (AD-18), so every
        # checked field of the line is named.
        return [line_field_id(line.line_no, name) for name in CHECKED_LINE_FIELDS]
    return []


def check_confidence(
    values: CurrentValues, *, supplier_upload: bool
) -> AdminReason | None:
    """`LOW_CONFIDENCE` naming each checked field below 0.98 (AD-18): the header
    fields, `purchase_order` for supplier uploads, `vendor_tax_id` when DI returned it,
    and every line's checked fields. Bank and other fields are never checked."""
    checked = list(CHECKED_HEADER_FIELDS)
    if supplier_upload:
        checked.append(UPLOAD_CHECKED_FIELD)
    if CHECKED_IF_RETURNED_FIELD in values.fields:
        checked.append(CHECKED_IF_RETURNED_FIELD)
    low = [
        field_id
        for field_id in checked
        if _field_confidence(values.fields.get(field_id)) < CONFIDENCE_THRESHOLD
    ]
    for line in values.lines:
        low.extend(_low_line_fields(line))
    if not low:
        return None
    return AdminReason(
        ReasonCode.LOW_CONFIDENCE, field_ids=tuple(low), run_id=values.run_id
    )


def _text(values: CurrentValues, field_id: str) -> str | None:
    row = values.fields.get(field_id)
    if row is None or row.value_text is None or not row.value_text.strip():
        return None
    return row.value_text


def normalise_po_number(value: str) -> str:
    """A PO number as looked up and saved: trimmed, uppercase."""
    return value.strip().upper()


def normalise_product_code(value: str) -> str:
    """A product code as matched: trimmed, inner whitespace collapsed, uppercase, so
    OCR spacing and case never decide a match."""
    return " ".join(value.split()).upper()


def printed_po_number(values: CurrentValues) -> str | None:
    """The extracted `purchase_order`, normalised; None when it was not read."""
    text = _text(values, PURCHASE_ORDER)
    return None if text is None else normalise_po_number(text)


def check_printed_supplier(
    values: CurrentValues,
    *,
    master_name: str | None,
    master_tax_id: str | None,
    similarity: Similarity,
) -> AdminReason | None:
    """`SUPPLIER_ID_MISMATCH` when the printed supplier is not the invoice's (AD-19):
    by tax id when both are present (the name is then not consulted), otherwise by
    the normalised name's token-set similarity (at least 85). The supplier is always
    `intake.invoice.supplier_id`'s master row, never read from OCR (P-5)."""
    printed_tax = _text(values, VENDOR_TAX_ID)
    tax = None if printed_tax is None else normalise_tax_id(printed_tax)
    master_tax = None if master_tax_id is None else normalise_tax_id(master_tax_id)
    if tax and master_tax:
        if tax == master_tax:
            return None
        return AdminReason(
            ReasonCode.SUPPLIER_ID_MISMATCH,
            field_ids=(VENDOR_TAX_ID,),
            detail={"basis": "tax_id"},
            run_id=values.run_id,
        )
    printed_name = _text(values, VENDOR_NAME)
    name = "" if printed_name is None else normalise_name(printed_name)
    master = "" if master_name is None else normalise_name(master_name)
    score = int(similarity(name, master)) if name and master else 0
    if score >= NAME_SIMILARITY_MIN:
        return None
    return AdminReason(
        ReasonCode.SUPPLIER_ID_MISMATCH,
        field_ids=(VENDOR_NAME,),
        detail={"basis": "name", "score": score},
        run_id=values.run_id,
    )


def expected_amount(
    lines: Mapping[UUID, PoLineRef],
    received: Mapping[UUID, Decimal],
    invoiced_elsewhere: Mapping[UUID, Decimal],
) -> Decimal:
    """AD-19: over the matched PO lines (each once), the unit price times the
    quantity still to invoice: received less what other invoices already hold, never
    below 0. To 0.01, half up."""
    total = Decimal(0)
    for po_line_id, line in lines.items():
        still = received.get(po_line_id, Decimal(0)) - invoiced_elsewhere.get(
            po_line_id, Decimal(0)
        )
        total += line.unit_price * max(still, Decimal(0))
    return money(total)


def check_po(
    values: CurrentValues,
    *,
    po_number: str | None,
    po: PoRef | None,
    supplier_id: UUID,
    received: Mapping[UUID, Decimal] | None,
    invoiced_elsewhere: Mapping[UUID, Decimal],
    supplier_upload: bool,
) -> PoCheck:
    """The PO match (AD-19). `po_number` is the printed PO for an upload or the
    delivery's for a goods-in scan; `po` is that PO (None if unknown); `received` the
    quantity received per PO line (all receipts for an upload, the delivery's receipt
    for a scan; None when there is none); `invoiced_elsewhere` the current quantities
    of the supplier's other non-rejected invoices per PO line, deducted for uploads
    only. Every problem is one `PO_MISMATCH` item, with `expected` and `actual`."""
    run_id = values.run_id
    sub_total_row = values.fields.get(SUB_TOTAL)
    actual = None if sub_total_row is None else sub_total_row.value_number
    actual_text = None if actual is None else str(money(actual))
    po_field = (PURCHASE_ORDER,) if supplier_upload else ()

    def mismatch(
        problems: list[str], field_ids: tuple[str, ...], expected: Decimal | None
    ) -> AdminReason:
        return AdminReason(
            ReasonCode.PO_MISMATCH,
            field_ids=field_ids,
            detail={
                "expected": None if expected is None else str(expected),
                "actual": actual_text,
                "problems": problems,
            },
            run_id=run_id,
        )

    if po_number is None:
        return PoCheck(None, reason=mismatch([PoProblem.PO_MISSING], po_field, None))
    if po is None:
        return PoCheck(None, reason=mismatch([PoProblem.PO_UNKNOWN], po_field, None))
    if po.supplier_id != supplier_id:
        return PoCheck(
            None, reason=mismatch([PoProblem.PO_OTHER_SUPPLIER], po_field, None)
        )

    by_code: dict[str, PoLineRef] = {}
    ambiguous: set[str] = set()
    for po_line_ref in po.lines:
        key = normalise_product_code(po_line_ref.supplier_product_code)
        if key in by_code:
            # Two PO lines share the code: never guess which one was invoiced.
            ambiguous.add(key)
        by_code[key] = po_line_ref
    matches: dict[UUID, LineMatch] = {}
    matched: dict[UUID, PoLineRef] = {}
    problems: list[str] = []
    field_ids: list[str] = []
    if not values.lines:
        problems.append(PoProblem.NO_LINES)
    for line in values.lines:
        code = (
            None
            if line.product_code is None
            else normalise_product_code(line.product_code)
        )
        po_line = by_code.get(code) if code else None
        if code in ambiguous or po_line is None:
            problem = (
                PoProblem.AMBIGUOUS_PRODUCT_CODE
                if code in ambiguous
                else PoProblem.LINE_UNMATCHED
            )
            if problem not in problems:
                problems.append(problem)
            field_ids.append(line_field_id(line.line_no, "product_code"))
            continue
        matches[line.id] = LineMatch(po_line.po_line_id, po_line.material_id)
        matched[po_line.po_line_id] = po_line

    expected: Decimal | None = None
    if received is None:
        problems.append(PoProblem.NO_RECEIPT)
    else:
        expected = expected_amount(
            matched, received, invoiced_elsewhere if supplier_upload else {}
        )
        if actual is None:
            problems.append(PoProblem.SUB_TOTAL_MISSING)
            field_ids.append(SUB_TOTAL)
        elif not within_tolerance(actual, expected):
            problems.append(PoProblem.AMOUNT_OUTSIDE_TOLERANCE)
            field_ids.append(SUB_TOTAL)
    reason = mismatch(problems, tuple(field_ids), expected) if problems else None
    return PoCheck(po.po_number, matches, reason)
