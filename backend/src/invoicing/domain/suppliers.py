"""The supplier master's load rules (Story 1.6, AD-11): the CSV row model, and how bank
values are normalised and fingerprinted.

A bank value is compared only by its fingerprint, never decrypted (AD-11, AD-19): an
HMAC-SHA256, keyed with the environment's `hmac-key` secret, over the value with
spaces and hyphens stripped and converted to uppercase.

Errors name a row and a column, never a value: a CSV cell may hold a bank value or a
phone number (security.md rule 2).
"""

import _csv
import csv
import hashlib
import hmac
import io
import re
from dataclasses import dataclass, field
from uuid import UUID

# AD-18: the bank field ids (the part after `payment[<n>].`), one `supplier_bank` row each.
BANK_FIELD_IDS: tuple[str, ...] = ("bank_account_number", "iban", "swift")
# The CSV header, in this order or any other; every column is required.
CSV_COLUMNS: tuple[str, ...] = (
    "supplier_id",
    "name",
    "phone",
    "tax_id",
    *BANK_FIELD_IDS,
)

# Spaces (any whitespace) and hyphens are formatting, not part of the value (AD-11).
_FORMATTING = re.compile(r"[\s-]")


class SupplierCsvError(ValueError):
    """A CSV the load refuses. `row` is the 1-based line number (the header is row 1)."""

    def __init__(self, row: int, column: str | None, problem: str) -> None:
        where = f"row {row}" + (f", column {column}" if column else "")
        super().__init__(f"{where}: {problem}")
        self.row = row
        self.column = column
        self.problem = problem


@dataclass(frozen=True)
class SupplierRow:
    """One supplier from the CSV. `bank` holds only the non-empty bank fields, and a
    blank `phone` or `tax_id` is None: a blank cell leaves a stored value unchanged
    (Dj, 2026-09-29)."""

    supplier_id: UUID
    name: str
    phone: str | None
    tax_id: str | None
    bank: dict[str, str] = field(default_factory=dict)


def normalise_bank_value(value: str) -> str:
    """The value a fingerprint is taken over: spaces and hyphens stripped, uppercase."""
    return _FORMATTING.sub("", value).upper()


def bank_fingerprint(key: str, value: str) -> str:
    """HMAC-SHA256 (lowercase hex) of the normalised `value`, keyed with the `hmac-key`
    secret text."""
    return hmac.new(
        key.encode(), normalise_bank_value(value).encode(), hashlib.sha256
    ).hexdigest()


def _optional(value: str) -> str | None:
    stripped = value.strip()
    return stripped or None


def parse_supplier_csv(text: str) -> tuple[SupplierRow, ...]:
    """Every row of a supplier CSV, or `SupplierCsvError` for the first problem."""
    # newline="": a quoted cell may hold a line break (the csv module's rule).
    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        return _parse(reader)
    except csv.Error:
        # E.g. an oversized cell. The csv module's message is not repeated: a row
        # number is enough, and nothing from the cell is shown.
        raise SupplierCsvError(max(reader.line_num, 1), None, "not valid CSV") from None


def _parse(reader: "_csv.Reader") -> tuple[SupplierRow, ...]:
    header = next(reader, None)
    if header is None:
        raise SupplierCsvError(1, None, "the file is empty")
    columns = [name.strip() for name in header]
    for name in columns:
        if name not in CSV_COLUMNS:
            raise SupplierCsvError(1, name or "(blank)", "unknown column")
    for name in CSV_COLUMNS:
        if name not in columns:
            raise SupplierCsvError(1, name, "missing column")
    if len(set(columns)) != len(columns):
        repeated = next(name for name in columns if columns.count(name) > 1)
        raise SupplierCsvError(1, repeated, "repeated column")

    rows: list[SupplierRow] = []
    seen: set[UUID] = set()
    # A record starts on the line after the previous one ended: a quoted cell may
    # span lines, and the error names the line the record starts on.
    ended = reader.line_num
    for cells in reader:
        row, ended = ended + 1, reader.line_num
        if not any(cell.strip() for cell in cells):
            continue
        if len(cells) != len(columns):
            raise SupplierCsvError(
                row, None, f"{len(cells)} cells, the header has {len(columns)}"
            )
        values = dict(zip(columns, cells, strict=True))
        try:
            supplier_id = UUID(values["supplier_id"].strip())
        except ValueError:
            raise SupplierCsvError(row, "supplier_id", "not a UUID") from None
        if supplier_id in seen:
            raise SupplierCsvError(row, "supplier_id", "repeats an earlier row")
        seen.add(supplier_id)
        name = values["name"].strip()
        if not name:
            raise SupplierCsvError(row, "name", "blank")
        if not name.isprintable():
            # It is printed next to the link: no line breaks or control characters.
            raise SupplierCsvError(
                row, "name", "holds a line break or control character"
            )
        bank: dict[str, str] = {}
        for field_id in BANK_FIELD_IDS:
            value = values[field_id].strip()
            if not value:
                continue
            if not normalise_bank_value(value):
                raise SupplierCsvError(row, field_id, "only spaces and hyphens")
            bank[field_id] = value
        rows.append(
            SupplierRow(
                supplier_id=supplier_id,
                name=name,
                phone=_optional(values["phone"]),
                tax_id=_optional(values["tax_id"]),
                bank=bank,
            )
        )
    if not rows:
        raise SupplierCsvError(1, None, "no supplier rows")
    return tuple(rows)
