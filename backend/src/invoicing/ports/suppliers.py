"""The supplier master, read by the pipeline (Story 2.5, AD-11, AD-19): the facts the
printed-supplier check compares against. The supplier is always the invoice's
`supplier_id`, never one read from OCR (P-5).

Every method raises `DatabaseOfflineError` (domain/errors.py) when the database can't
be reached at all (AD-7); a failing query raises as it is."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class SupplierFacts:
    """A supplier's master name and tax id (None when none is on file)."""

    name: str
    tax_id: str | None


class SupplierReader(Protocol):
    """Read-only access to `master.supplier`."""

    async def get(self, supplier_id: UUID) -> SupplierFacts | None:
        """The supplier's facts, or None when the master has no such supplier."""
        ...


class SupplierDirectory(Protocol):
    """Supplier names from `master.supplier`, for staff screens that show or search
    them (Story 4.1: goods-in's delivery list)."""

    async def names(self, supplier_ids: Iterable[UUID]) -> dict[UUID, str]:
        """The name of each supplier in `supplier_ids` the master has."""
        ...

    async def matching(self, text: str) -> dict[UUID, str]:
        """Every supplier whose name contains `text` in any case, with its name."""
        ...
