"""Invoice search and detail for admin and finance, read by staff-api (Story 3.4,
AD-3, AD-11, AD-18). One adapter, over PostgreSQL (`adapters/postgres/invoice_search.py`).
Read-only: nothing here writes.

No bank value, mask or ciphertext ever leaves the adapter: a detail says only whether
bank details are on file (AD-11). Every method raises `DatabaseOfflineError` when the
database can't be reached (AD-7); a failing query raises as it is."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from invoicing.domain.status import InvoiceStatus

# Story 3.4: 50 results a page, like the queue (UX-DR9).
PAGE_SIZE = 50


@dataclass(frozen=True)
class SearchQuery:
    """Which page, and the filters (all optional, combined with AND): a supplier, a
    set of statuses, an invoice number already normalised (`normalise_invoice_number`)
    and the 5 low bytes of a supplier reference (`parse_reference`)."""

    page: int = 1
    supplier_id: UUID | None = None
    statuses: frozenset[InvoiceStatus] = frozenset()
    invoice_number: str | None = None
    reference: bytes | None = None

    @property
    def offset(self) -> int:
        return (self.page - 1) * PAGE_SIZE


@dataclass(frozen=True)
class SearchRow:
    """One invoice. `received_at` is `invoice.created_at`; `supplier_name` is None
    when the master has no such supplier; `invoice_number` and `invoice_total` are the
    AD-18 current values, None before extraction (or when not read).
    `after_correction`: an admin corrected the current run (Story 2.10)."""

    invoice_id: UUID
    received_at: datetime
    supplier_id: UUID
    supplier_name: str | None
    invoice_number: str | None
    invoice_total: Decimal | None
    currency: str | None
    status: str
    after_correction: bool


@dataclass(frozen=True)
class SearchSupplier:
    """A supplier with at least one invoice; `name` is None when the master has none."""

    supplier_id: UUID
    name: str | None


@dataclass(frozen=True)
class SearchListing:
    """One page of matches, newest first, the number matching, and every supplier
    with an invoice, whatever the filters (the supplier filter's options)."""

    rows: tuple[SearchRow, ...]
    total: int
    suppliers: tuple[SearchSupplier, ...] = ()


@dataclass(frozen=True)
class DetailField:
    """One current header field (AD-18), never a bank field. `amount` is set for a
    numeric (money) field, so the endpoint can send it at 2 decimals."""

    field_id: str
    value: str | None
    currency: str | None
    amount: Decimal | None = None


@dataclass(frozen=True)
class DetailLine:
    """One current line (AD-18)."""

    line_no: int
    product_code: str | None
    description: str | None
    quantity: Decimal | None
    unit_price: Decimal | None
    amount: Decimal | None


@dataclass(frozen=True)
class HistoryEntry:
    """One `status_history` row. `actor` is the raw actor; the endpoint shows only its
    category."""

    from_status: str | None
    to_status: str
    at: datetime
    actor: str


@dataclass(frozen=True)
class InvoiceDetail:
    """One invoice as admin and finance see it. `bank_on_file`: the current run holds
    at least one bank field (shown as "Bank details on file", never a value)."""

    invoice_id: UUID
    received_at: datetime
    supplier_id: UUID
    supplier_name: str | None
    status: str
    after_correction: bool
    accounts_ref: str | None
    posted_at: datetime | None
    fields: tuple[DetailField, ...]
    lines: tuple[DetailLine, ...]
    bank_on_file: bool
    history: tuple[HistoryEntry, ...]


class InvoiceSearchReader(Protocol):
    """Read-only access to every invoice, whatever its status."""

    async def search(self, query: SearchQuery) -> SearchListing:
        """The page `query` asks for, newest first (`created_at`, then id)."""
        ...

    async def detail(self, invoice_id: UUID) -> InvoiceDetail | None:
        """The invoice, or None when there is no such invoice."""
        ...
