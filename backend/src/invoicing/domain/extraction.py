"""AD-18: how a Document Intelligence `prebuilt-invoice` result becomes typed field and
line rows (Story 2.3). Pure: the adapter passes the document's `fields` object and
keeps nothing else, so the raw result is never stored (AD-8).

- Field ids are DI names in snake_case (`VendorName` -> `vendor_name`), except
  `InvoiceId`, which is `invoice_number`.
- `Items` become lines: `line[<n>].<field>` ids, `n` = `line_no`, counted from 1 like
  PO lines. A line's confidence is the lowest of its checked fields (a missing one
  counts as 0).
- `PaymentDetails` is a list, so bank fields are `payment[<n>].bank_account_number`,
  `.iban` and `.swift`, `n` counted from 0 as DI lists it. Their value is held only
  as `bank_value`, which the adapter encrypts and fingerprints (AD-11); it is never
  put in `value_text` and never printed.
- Any other list is flattened the same way (`<name>[<n>].<field>`).
- Amounts are `Decimal` (coding-style.md rule 4); the currency is configuration
  (`INVOICE_CURRENCY`), never DI's (AD-8).
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from invoicing.domain.suppliers import BANK_FIELD_IDS
from invoicing.domain.upload import UploadContentType

# AD-18: the one DI name that is not simply snake_cased.
_RENAMED = {"InvoiceId": "invoice_number"}
# DI lists that are not plain fields.
ITEMS = "Items"
PAYMENT_DETAILS = "PaymentDetails"
PAYMENT_PREFIX = "payment"
LINE_PREFIX = "line"

# AD-18: the invoice_line columns, by DI item field name.
LINE_COLUMNS: Mapping[str, str] = {
    "ProductCode": "product_code",
    "Description": "description",
    "Quantity": "quantity",
    "Unit": "unit",
    "UnitPrice": "unit_price",
    "Amount": "amount",
    "Tax": "tax",
}
NUMERIC_LINE_COLUMNS = frozenset({"quantity", "unit_price", "amount", "tax"})
# AD-18 checked line fields: a line's confidence is the lowest of these.
CHECKED_LINE_FIELDS: tuple[str, ...] = (
    "product_code",
    "quantity",
    "unit_price",
    "amount",
)

# AD-18 checked header fields: always these; `purchase_order` for supplier uploads only
# (goods-in scans take the PO from the delivery); `vendor_tax_id` when DI returned it.
CHECKED_HEADER_FIELDS: tuple[str, ...] = (
    "vendor_name",
    "invoice_number",
    "invoice_date",
    "sub_total",
    "invoice_total",
)
UPLOAD_CHECKED_FIELD = "purchase_order"
CHECKED_IF_RETURNED_FIELD = "vendor_tax_id"

_WORD_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_TEXT_KEYS = (
    "valueString",
    "valuePhoneNumber",
    "valueCountryRegion",
    "valueTime",
    "valueSelectionMark",
)


# AD-8 page caps: F0 analyses at most a document's first 2 pages, so an analyze call
# reserves 2 pages for a PDF and 1 for a photo; the run reconciles to the real count.
F0_MAX_PAGES = 2


def pages_to_reserve(content_type: UploadContentType) -> int:
    """The pages one analyze call of this document can use on F0 (AD-8)."""
    return F0_MAX_PAGES if content_type is UploadContentType.PDF else 1


def field_id_for(di_name: str) -> str:
    """The AD-18 field id of a DI field name."""
    return _RENAMED.get(di_name) or _WORD_BOUNDARY.sub("_", di_name).lower()


def line_field_id(line_no: int, column: str) -> str:
    """`line[<n>].<field>`, the field id of one line column (AD-18)."""
    return f"{LINE_PREFIX}[{line_no}].{column}"


def is_bank_field_id(field_id: str) -> bool:
    """Whether `field_id` is `payment[<n>].<bank field id>` (AD-11, AD-18)."""
    prefix, _, bank_field = field_id.partition("].")
    return (
        prefix.startswith(f"{PAYMENT_PREFIX}[")
        and prefix[len(PAYMENT_PREFIX) + 1 :].isdigit()
        and bank_field in BANK_FIELD_IDS
    )


@dataclass(frozen=True)
class FieldRow:
    """One `intake.invoice_field` row from DI (`source=di`). Exactly one of the value
    columns is set, or none when DI found the field but read no value; a bank field
    sets only `bank_value`."""

    field_id: str
    confidence: float | None
    page: int | None = None
    polygon: tuple[float, ...] | None = None
    value_text: str | None = None
    value_number: Decimal | None = None
    value_date: date | None = None
    currency: str | None = None
    # AD-11: plaintext only in memory, on its way to pgp_pub_encrypt; never printed.
    bank_value: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class LineRow:
    """One `intake.invoice_line` row from DI. `confidence` is the lowest of the
    checked fields (AD-18)."""

    line_no: int
    confidence: float
    product_code: str | None = None
    description: str | None = None
    quantity: Decimal | None = None
    unit: str | None = None
    unit_price: Decimal | None = None
    amount: Decimal | None = None
    tax: Decimal | None = None


@dataclass(frozen=True)
class ExtractedInvoice:
    """What one extraction run saves: its header fields and its lines (AD-18)."""

    fields: tuple[FieldRow, ...]
    lines: tuple[LineRow, ...]


def _mapping(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None


def _decimal(value: object) -> Decimal | None:
    # bool is an int: never an amount.
    if isinstance(value, bool) or not isinstance(value, int | float | Decimal | str):
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _confidence(di_field: Mapping[str, object]) -> float | None:
    value = _decimal(di_field.get("confidence"))
    return None if value is None else min(max(float(value), 0.0), 1.0)


def _region(
    di_field: Mapping[str, object],
) -> tuple[int | None, tuple[float, ...] | None]:
    """The page and polygon of the field's first bounding region (the admin crop)."""
    regions = di_field.get("boundingRegions")
    if not isinstance(regions, Sequence) or isinstance(regions, str) or not regions:
        return None, None
    first = _mapping(regions[0])
    if first is None:
        return None, None
    page = first.get("pageNumber")
    polygon = first.get("polygon")
    points: tuple[float, ...] | None = None
    if isinstance(polygon, Sequence) and not isinstance(polygon, str):
        numbers = [_decimal(point) for point in polygon]
        if all(number is not None for number in numbers):
            points = tuple(float(number) for number in numbers if number is not None)
    page_number = (
        page
        if isinstance(page, int) and not isinstance(page, bool) and page > 0
        else None
    )
    return page_number, points


def _text(di_field: Mapping[str, object]) -> str | None:
    for key in _TEXT_KEYS:
        value = di_field.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    # Addresses and anything else typed: what DI read, as printed.
    content = di_field.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    return None


def _typed_confidence(confidence: float | None, value: object) -> float | None:
    """AD-18: a typed value that did not parse is missing, so its confidence is 0."""
    return 0.0 if value is None else confidence


def _field_row(
    field_id: str, di_field: Mapping[str, object], currency: str
) -> FieldRow:
    page, polygon = _region(di_field)
    confidence = _confidence(di_field)
    if is_bank_field_id(field_id):
        return FieldRow(field_id, confidence, page, polygon, bank_value=_text(di_field))
    kind = di_field.get("type")
    if kind == "currency":
        amount = _mapping(di_field.get("valueCurrency"))
        number = None if amount is None else _decimal(amount.get("amount"))
        return FieldRow(
            field_id,
            _typed_confidence(confidence, number),
            page,
            polygon,
            value_number=number,
            currency=currency,
        )
    if kind in ("number", "integer"):
        number = _decimal(di_field.get("valueNumber", di_field.get("valueInteger")))
        return FieldRow(
            field_id,
            _typed_confidence(confidence, number),
            page,
            polygon,
            value_number=number,
        )
    if kind == "date":
        day = _date(di_field.get("valueDate"))
        return FieldRow(
            field_id,
            _typed_confidence(confidence, day),
            page,
            polygon,
            value_date=day,
        )
    return FieldRow(field_id, confidence, page, polygon, value_text=_text(di_field))


def _elements(di_field: Mapping[str, object]) -> list[Mapping[str, object]]:
    values = di_field.get("valueArray")
    if not isinstance(values, Sequence) or isinstance(values, str):
        return []
    return [element for element in map(_mapping, values) if element is not None]


def _object_fields(element: Mapping[str, object]) -> Mapping[str, object]:
    return _mapping(element.get("valueObject")) or {}


def _line(line_no: int, item: Mapping[str, object], currency: str) -> LineRow:
    texts: dict[str, str | None] = {}
    numbers: dict[str, Decimal | None] = {}
    confidences: dict[str, float] = {}
    for di_name, raw in _object_fields(item).items():
        column = LINE_COLUMNS.get(di_name)
        di_field = _mapping(raw)
        if column is None or di_field is None:
            continue
        row = _field_row(column, di_field, currency)
        if column in NUMERIC_LINE_COLUMNS:
            numbers[column] = row.value_number
        else:
            texts[column] = row.value_text
        confidences[column] = row.confidence or 0.0
    # AD-18: a checked field that is missing counts as confidence 0.
    confidence = min(confidences.get(name, 0.0) for name in CHECKED_LINE_FIELDS)
    return LineRow(
        line_no=line_no,
        confidence=confidence,
        product_code=texts.get("product_code"),
        description=texts.get("description"),
        quantity=numbers.get("quantity"),
        unit=texts.get("unit"),
        unit_price=numbers.get("unit_price"),
        amount=numbers.get("amount"),
        tax=numbers.get("tax"),
    )


def map_invoice(fields: Mapping[str, object], currency: str) -> ExtractedInvoice:
    """The AD-18 rows of one analysed invoice: `fields` is DI's
    `analyzeResult.documents[0].fields`, `currency` the configured invoice currency."""
    rows: list[FieldRow] = []
    lines: list[LineRow] = []
    for di_name, raw in sorted(fields.items()):
        di_field = _mapping(raw)
        if di_field is None:
            continue
        if di_name == ITEMS:
            lines.extend(
                _line(index, item, currency)
                for index, item in enumerate(_elements(di_field), start=1)
            )
            continue
        if di_field.get("type") != "array":
            # AD-11: payment details (bank values) are stored only through the
            # `payment[<n>].*` element path, never as one plaintext field.
            if di_name != PAYMENT_DETAILS:
                rows.append(_field_row(field_id_for(di_name), di_field, currency))
            continue
        prefix = PAYMENT_PREFIX if di_name == PAYMENT_DETAILS else field_id_for(di_name)
        for index, element in enumerate(_elements(di_field)):
            for sub_name, sub_raw in sorted(_object_fields(element).items()):
                sub_field = _mapping(sub_raw)
                if sub_field is not None:
                    field_id = f"{prefix}[{index}].{field_id_for(sub_name)}"
                    rows.append(_field_row(field_id, sub_field, currency))
    return ExtractedInvoice(fields=tuple(rows), lines=tuple(lines))
