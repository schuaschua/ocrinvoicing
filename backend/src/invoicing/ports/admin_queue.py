"""The admin queue list, read by staff-api (Story 2.8, AD-4, AD-18). One adapter, over
PostgreSQL (`adapters/postgres/admin_queue.py`). Read-only: nothing here writes.

Every method raises `DatabaseOfflineError` (domain/errors.py) when the database can't
be reached at all (AD-7); a failing query raises as it is."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from invoicing.domain.reasons import ReasonCode

# UX-DR9: the queue is paginated at 50 rows.
PAGE_SIZE = 50


@dataclass(frozen=True)
class QueueQuery:
    """Which page of the queue, and its filters: an open reason and a supplier."""

    page: int = 1
    reason: ReasonCode | None = None
    supplier_id: UUID | None = None

    @property
    def offset(self) -> int:
        return (self.page - 1) * PAGE_SIZE


@dataclass(frozen=True)
class QueueRow:
    """One queued invoice. `received_at` is `invoice.created_at`; `supplier_name` is
    None when the master has no such supplier; `invoice_total` is the AD-18 current
    value, None without an extraction run (or without the field). `reasons` are the
    open reasons: the `admin_item` rows of the invoice's latest `routing_id` (AD-4)."""

    invoice_id: UUID
    received_at: datetime
    supplier_id: UUID
    supplier_name: str | None
    invoice_total: Decimal | None
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class QueueSupplier:
    """A supplier with an invoice in the queue; `name` is None when the master has
    no such supplier."""

    supplier_id: UUID
    name: str | None


@dataclass(frozen=True)
class QueueListing:
    """One page of queued invoices, oldest first, the number matching the filters,
    this UTC month's Document Intelligence pages (AD-8), and every supplier with a
    queued invoice, whatever the filters, by name (the supplier filter's options)."""

    rows: tuple[QueueRow, ...]
    total: int
    pages_used: int
    suppliers: tuple[QueueSupplier, ...] = ()


class AdminQueueReader(Protocol):
    """Read-only access to the invoices in `in_admin_queue`."""

    async def read(self, query: QueueQuery) -> QueueListing:
        """The page `query` asks for, sorted by `created_at` then id."""
        ...
