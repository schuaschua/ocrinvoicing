"""Supplier reminders (AD-6, AD-13): the rows the weekly job (Story 4.3) writes for
each overdue PO, which the validate stage deletes once an invoice for the PO is
matched (Story 2.6).

Storage contract, shared with Story 4.3:

- Azure Table `supplierreminders`, one entity per overdue PO of a supplier.
- `PartitionKey` = the supplier id, a UUID in canonical lowercase form.
- `RowKey` = the PO number, as `invoice.po_number` holds it.
"""

from typing import Protocol
from uuid import UUID

SUPPLIER_REMINDERS_TABLE = "supplierreminders"


def partition_key(supplier_id: UUID) -> str:
    """The `PartitionKey` of a supplier's reminders."""
    return str(supplier_id)


def row_key(po_number: str) -> str:
    """The `RowKey` of a PO's reminder."""
    return po_number


class ReminderStore(Protocol):
    """The validate stage's side of `supplierreminders`."""

    async def delete(self, supplier_id: UUID, po_number: str) -> None:
        """Delete the supplier's reminder row for `po_number`; a missing row is
        fine. Raises `ServiceUnavailableError` when the store can't answer."""
        ...
