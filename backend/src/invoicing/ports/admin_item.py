"""One admin item, read by staff-api (Story 2.9, AD-4, AD-11, AD-18). One adapter, over
PostgreSQL (`adapters/postgres/admin_item.py`).

Only an invoice in `in_admin_queue` is an item: any other id reads as None, so the
endpoint answers 404 and never reveals whether it exists. Bank values leave the
adapter only as masks (their last 4 characters), except through `reveal`, which
returns one full value after writing its audit entry in the same transaction.

Every method raises `DatabaseOfflineError` when the database can't be reached (AD-7)
and `ServiceUnavailableError` when the private key can't be read or doesn't decrypt."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from invoicing.domain.extraction import PageSize


class RevealWhich(StrEnum):
    """Which value of a changed bank field to reveal: the one on the invoice, or the
    supplier master's."""

    NEW = "new"
    ON_FILE = "on_file"


@dataclass(frozen=True)
class ItemReason:
    """One open reason (an `admin_item` row of the latest `routing_id`, AD-4)."""

    code: str
    field_ids: tuple[str, ...]
    detail: Mapping[str, object]


@dataclass(frozen=True)
class ItemField:
    """One current field (AD-18). `value` is None for a bank field (its mask is in
    `BankChange`) and for a field found without a value. `confidence` is 1.0 for an
    admin correction (AD-18)."""

    field_id: str
    value: str | None
    currency: str | None
    confidence: float | None
    page: int | None
    polygon: tuple[float, ...] | None
    flagged: bool
    bank: bool = False


@dataclass(frozen=True)
class ItemLine:
    """One current line (AD-18)."""

    line_no: int
    confidence: float
    product_code: str | None = None
    description: str | None = None
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    amount: Decimal | None = None


@dataclass(frozen=True)
class BankChange:
    """One changed bank field (`payment[<n>].<id>`) of `BANK_CHANGED`: the last 4
    characters of the master's value (None when it has none) and of the invoice's
    (None when not read). A value of 4 characters or fewer masks to '' (no digits)."""

    field_id: str
    on_file: str | None = field(repr=False)
    new: str | None = field(repr=False)


@dataclass(frozen=True)
class DuplicateOf:
    """The earlier invoice an open `DUPLICATE` names (its detail `invoice_id`, AD-9),
    for the side-by-side comparison (Story 3.3): when it was received, its supplier,
    its current total (AD-18) and its content type. Any status: it need not be queued."""

    invoice_id: UUID
    received_at: datetime
    content_type: str
    supplier_name: str | None
    invoice_total: str | None
    currency: str | None


@dataclass(frozen=True)
class AdminItem:
    """What the admin item screen shows. `supplier_phone` is set only when
    `BANK_CHANGED`, `UNREADABLE` or `UNSUPPORTED_DOCUMENT` is open, and `bank_changes`
    only for `BANK_CHANGED`; `pages` are empty for a run saved before page
    sizes were kept."""

    invoice_id: UUID
    received_at: datetime
    content_type: str
    supplier_id: UUID
    supplier_name: str | None
    supplier_phone: str | None
    reasons: tuple[ItemReason, ...]
    fields: tuple[ItemField, ...]
    lines: tuple[ItemLine, ...]
    pages: tuple[PageSize, ...]
    bank_changes: tuple[BankChange, ...] = ()
    # Story 2.10: the admin actions the open reasons allow (`domain/actions.py`).
    allowed_actions: tuple[str, ...] = ()
    # The routing the admin sees: every action sends it back, so an invoice routed
    # again meanwhile is refused as already handled (Story 2.10).
    routing_id: UUID | None = None
    # The missing checked header fields Correct may add (`domain/actions.py`).
    addable_fields: tuple[str, ...] = ()
    # Story 3.3: the matching invoice of an open `DUPLICATE`; None without one.
    duplicate_of: DuplicateOf | None = None


class AdminItemReader(Protocol):
    """Admin items: queued invoices only."""

    async def read(self, invoice_id: UUID) -> AdminItem | None:
        """The item, from one snapshot; None unless the invoice is queued."""
        ...

    async def content_type(self, invoice_id: UUID) -> str | None:
        """The queued invoice's content type (for its image); None unless queued."""
        ...

    async def duplicate_content_type(self, invoice_id: UUID) -> tuple[UUID, str] | None:
        """The matching invoice an open `DUPLICATE` of the queued invoice names, and
        its content type (for its image, Story 3.3); None unless the invoice is queued
        with such a reason and the matching invoice exists."""
        ...

    async def reveal(
        self,
        invoice_id: UUID,
        field_id: str,
        which: RevealWhich,
        admin_oid: str,
    ) -> str | None:
        """The full value of one changed bank field of the queued invoice, after
        writing its `bank.reveal` audit entry in the same transaction; None when the
        invoice is not queued, `field_id` is not one of its `BANK_CHANGED` fields, or
        there is no such value. Nothing is returned if the audit entry fails."""
        ...
