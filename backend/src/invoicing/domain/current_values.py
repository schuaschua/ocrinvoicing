"""AD-18 current values: the one rule every reader (validation, the admin screen,
analytics) uses to turn an invoice's stored rows into its current fields and lines.

The current values are the rows of the invoice's latest `extraction_run`, overlaid by
the `source=admin` rows that carry that `run_id`; for each field or line, the newest
row wins. Rows of earlier runs are never current, so a Re-extract drops earlier
corrections. Pure: the adapter passes the rows in.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

ADMIN_SOURCE = "admin"


@dataclass(frozen=True)
class RunRow:
    """One `intake.extraction_run` row."""

    run_id: UUID
    created_at: datetime


@dataclass(frozen=True)
class FieldValue:
    """One `intake.invoice_field` row, without the bank ciphertext: nothing that reads
    current values for validation ever needs a bank value (AD-11). A bank field
    carries only its `bank_fingerprint`, which the validate stage compares with the
    master's (AD-19, Story 2.6)."""

    id: UUID
    field_id: str
    run_id: UUID
    source: str
    created_at: datetime
    confidence: float | None
    value_text: str | None = None
    value_number: Decimal | None = None
    value_date: date | None = None
    bank_fingerprint: str | None = field(default=None, repr=False)

    @property
    def has_value(self) -> bool:
        """Whether a value was read (a field found with no value is missing)."""
        return (
            self.value_text is not None
            or self.value_number is not None
            or self.value_date is not None
        )


@dataclass(frozen=True)
class LineValue:
    """One `intake.invoice_line` row. `id` is the row that the validate stage fills
    `po_line_id` and `material_id` on."""

    id: UUID
    line_no: int
    run_id: UUID
    source: str
    created_at: datetime
    confidence: float
    product_code: str | None = None
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    amount: Decimal | None = None
    po_line_id: UUID | None = None


@dataclass(frozen=True)
class CurrentValues:
    """An invoice's current fields by field id and lines by line number (AD-18)."""

    run_id: UUID
    fields: Mapping[str, FieldValue]
    lines: tuple[LineValue, ...]


def _newest(row: FieldValue | LineValue) -> tuple[datetime, UUID]:
    # Rows written in one transaction share `created_at`: the later UUIDv7 row id
    # wins, so the result never depends on the order SQL returned the rows in.
    return row.created_at, row.id


def current_values(
    runs: Iterable[RunRow],
    fields: Iterable[FieldValue],
    lines: Iterable[LineValue],
) -> CurrentValues | None:
    """The AD-18 current values of one invoice from all its rows, or None when it has
    no extraction run."""
    ordered: Sequence[RunRow] = sorted(runs, key=lambda r: (r.created_at, r.run_id))
    if not ordered:
        return None
    latest = ordered[-1].run_id
    current_fields: dict[str, FieldValue] = {}
    for row in fields:
        if row.run_id != latest:
            continue
        held = current_fields.get(row.field_id)
        if held is None or _newest(row) > _newest(held):
            current_fields[row.field_id] = row
    current_lines: dict[int, LineValue] = {}
    for line in lines:
        if line.run_id != latest:
            continue
        held_line = current_lines.get(line.line_no)
        if held_line is None or _newest(line) > _newest(held_line):
            current_lines[line.line_no] = line
    return CurrentValues(
        run_id=latest,
        fields=current_fields,
        lines=tuple(current_lines[n] for n in sorted(current_lines)),
    )
