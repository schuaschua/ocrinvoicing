"""PO and goods-received data (AD-10): the purchasing system, reached only through
`PurchasingPort`. Today one adapter serves it, the simulation
(`adapters/purchasing_sim/`); the real system replaces it by one setting
(`PURCHASING_ADAPTER`), so no capability code knows which one it talks to.

Money is `Decimal` with 2 decimals, quantities `Decimal` with up to 3, dates `date`
(spine Consistency Conventions). Every method raises `DatabaseOfflineError`
(domain/errors.py) when the data can't be reached at all (AD-7); anything else
raises as it is.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class PoLine:
    """One PO line (AD-10). Purchasing owns materials: `material_id` and
    `material_name` come from here, never from `master`. An invoice line matches it
    by `product_code = supplier_product_code` (AD-19)."""

    po_line_id: UUID
    line_no: int
    material_id: UUID
    material_name: str
    supplier_product_code: str
    unit_price: Decimal
    quantity: Decimal
    expected_date: date


@dataclass(frozen=True)
class PurchaseOrder:
    """A PO: its supplier and its lines, in line order."""

    po_number: str
    supplier_id: UUID
    order_date: date
    lines: tuple[PoLine, ...]


@dataclass(frozen=True)
class GoodsReceipt:
    """One goods receipt: when it was received, the quantity per `po_line_id`, and the
    delivery it checked in (Story 2.5: a goods-in scan's expected amount is what its
    own delivery received, AD-19; None where the system does not say)."""

    receipt_id: UUID
    received_date: date
    lines: Mapping[UUID, Decimal]
    delivery_id: UUID | None = None


@dataclass(frozen=True)
class Delivery:
    """A delivery against a PO. Goods-in takes the invoice's supplier from it (AD-5)."""

    delivery_id: UUID
    supplier_id: UUID
    po_number: str
    delivery_no: int
    delivery_date: date


@dataclass(frozen=True)
class OverduePo:
    """A PO whose earliest line `expected_date` has passed. Receipts don't matter:
    a received PO is still overdue until it is invoiced, and whether it has been
    invoiced is decided by the AD-13 overdue job, not here."""

    po_number: str
    supplier_id: UUID
    expected_date: date


@dataclass(frozen=True)
class DeliveryDates:
    """The three dates of one delivery (CAP-19): promised is the earliest
    `expected_date` of the PO lines it received (of all the PO's lines while it has no
    receipt), delivered its `delivery_date`, received its goods receipt's
    `received_date` (None until the goods are checked in)."""

    delivery_id: UUID
    promised_date: date
    delivered_date: date
    received_date: date | None


class PurchasingPort(Protocol):
    """Read-only access to POs, deliveries and goods receipts (AD-10)."""

    async def get_po(self, po_number: str) -> PurchaseOrder | None:
        """The PO with its supplier and lines, or None when there is no such PO."""
        ...

    async def get_receipts(self, po_number: str) -> tuple[GoodsReceipt, ...]:
        """The PO's goods receipts, oldest first; empty when nothing was received
        (or there is no such PO)."""
        ...

    async def get_delivery(self, delivery_id: UUID) -> Delivery | None:
        """The delivery with its PO and supplier, or None when it is unknown."""
        ...

    async def list_deliveries(self, on: date) -> tuple[Delivery, ...]:
        """The deliveries dated `on`, by PO number then delivery number (Story 4.1:
        goods-in's list of today's deliveries)."""
        ...

    async def search_deliveries(self, text: str, since: date) -> tuple[Delivery, ...]:
        """The deliveries dated `since` or later whose PO number starts with `text`
        in any case, or does so with a leading "PO" and any spaces or hyphens
        removed from both ("45012" and "po 45012" find "PO-45012"); an empty
        `text` matches every PO. Newest first, then by PO
        number and delivery number (Story 4.1: goods-in's search for a late
        delivery). Purchasing holds no supplier names; goods-in matches those against
        the master itself."""
        ...

    async def list_overdue_pos(self, as_of: date) -> tuple[OverduePo, ...]:
        """Every PO whose earliest line `expected_date` is before `as_of`, by that
        date then PO number, whatever has been delivered or received: overdue means
        not yet invoiced (AD-13), so a fully received PO is listed too, and the AD-13
        job drops the ones already invoiced."""
        ...

    async def get_delivery_dates(self, po_number: str) -> tuple[DeliveryDates, ...]:
        """Promised, delivered and received dates per delivery of the PO, by delivery
        date; empty when it has none (or there is no such PO)."""
        ...
