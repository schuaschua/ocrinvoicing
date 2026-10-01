"""Supplier reminders (AD-6, AD-13): the rows the weekly job (Story 4.3) writes for
each overdue PO, which the validate stage deletes once an invoice for the PO is
matched (Story 2.6).

Storage contract, shared with Story 4.3:

- Azure Table `supplierreminders`, one entity per overdue PO of a supplier.
- `PartitionKey` = the supplier id, a UUID in canonical lowercase form.
- `RowKey` = the PO number, as `invoice.po_number` holds it.
- No other property: a row's presence is the reminder.
"""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Protocol
from uuid import UUID

SUPPLIER_REMINDERS_TABLE = "supplierreminders"


def partition_key(supplier_id: UUID) -> str:
    """The `PartitionKey` of a supplier's reminders."""
    return str(supplier_id)


def row_key(po_number: str) -> str:
    """The `RowKey` of a PO's reminder."""
    return po_number


# Characters the Table service never allows in a key.
_FORBIDDEN_KEY_CHARACTERS = frozenset("/\\#?")
# The service's limit on a key, in UTF-16 code units (1 KiB).
_MAX_KEY_UNITS = 512


def storable(key: str) -> bool:
    """Whether the Table service can hold `key` as a `RowKey`. A PO number it can't
    hold has no reminder row."""
    return (
        bool(key)
        and len(key.encode("utf-16-le")) // 2 <= _MAX_KEY_UNITS
        and not any(c in _FORBIDDEN_KEY_CHARACTERS or not c.isprintable() for c in key)
    )


class ReminderStore(Protocol):
    """The validate stage's side of `supplierreminders`."""

    async def delete(self, supplier_id: UUID, po_number: str) -> None:
        """Delete the supplier's reminder row for `po_number`; a missing row is
        fine. Raises `ServiceUnavailableError` when the store can't answer."""
        ...


# Of the PO numbers given, those still owed an invoice right now (Story 4.3).
type StillOwed = Callable[[Sequence[str]], Awaitable[set[str]]]


class ReminderWriter(Protocol):
    """The weekly job's side of `supplierreminders` (Story 4.3)."""

    async def replace_all(
        self, rows_by_supplier: Mapping[UUID, Sequence[str]], still_owed: StillOwed
    ) -> int:
        """Make the table hold exactly `rows_by_supplier`: each supplier's partition
        its PO numbers, every other row and partition deleted. Just before writing a
        partition (and again before a retry of it), `still_owed` filters its PO
        numbers, so one invoiced meanwhile is not written. A PO number the table
        can't hold is skipped. Returns how many rows were written (upserted).
        Raises `ServiceUnavailableError` when any Table call fails (others may have
        landed), and whatever `still_owed` raises."""
        ...


class ReminderReader(Protocol):
    """supplier-api's side of `supplierreminders` (Story 4.3)."""

    async def list_for(self, supplier_id: UUID) -> list[str]:
        """The supplier's reminded PO numbers, sorted. Raises
        `ServiceUnavailableError` when the store can't answer."""
        ...
