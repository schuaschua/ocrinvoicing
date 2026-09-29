"""Story 1.7: the `supplierlinks` Table adapter (AD-6). Fakes stand in for Azure: a fake
client for the mapping, and the real SDK pipeline over a fake transport for what the
SDK itself logs and traces. Nothing goes over the network."""

import asyncio
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from invoicing.adapters.table_links import TableSupplierLinkRegistry
from invoicing.ports.links import SupplierLink, SupplierLinkRegistry

TOKEN_HASH = "3f" + "a1" * 31
SUPPLIER_ID = "0192f0c1-7a2b-7c3d-8e4f-0123456789ab"
ENTITY = {
    "PartitionKey": "3f",
    "RowKey": TOKEN_HASH,
    "supplier_id": SUPPLIER_ID,
    "supplier_name": "Lim Leather Trading",
    "issued_at": datetime(2026, 9, 1, tzinfo=UTC),
}


class FakeTable:
    """A `TableClient` stand-in: records queries and returns `entities`."""

    def __init__(self, entities: list[Mapping[str, Any]] | None = None) -> None:
        self.entities = entities or []
        self.queries: list[tuple[str, dict[str, Any]]] = []
        self.closed = False

    def query_entities(
        self, query_filter: str, **kwargs: Any
    ) -> AsyncIterator[Mapping[str, Any]]:
        self.queries.append((query_filter, kwargs))
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[Mapping[str, Any]]:
        for entity in self.entities:
            yield entity

    async def close(self) -> None:
        self.closed = True


def _resolve(table: FakeTable) -> SupplierLink | None:
    registry: SupplierLinkRegistry = TableSupplierLinkRegistry(table)
    return asyncio.run(registry.resolve(TOKEN_HASH))


def test_story_1_7_a_stored_link_resolves_to_its_supplier() -> None:
    table = FakeTable([ENTITY])
    link = _resolve(table)
    assert link == SupplierLink(
        supplier_id=UUID(SUPPLIER_ID),
        supplier_name="Lim Leather Trading",
        issued_at=datetime(2026, 9, 1, tzinfo=UTC),
        revoked_at=None,
    )
    assert link.is_active
    ((query_filter, kwargs),) = table.queries
    # Keys are parameters, never pasted into the filter text; PartitionKey is the first
    # 2 hex characters of the hash (the scheme Story 1.6 writes).
    assert TOKEN_HASH not in query_filter
    assert kwargs["parameters"] == {"pk": "3f", "rk": TOKEN_HASH}
    assert kwargs["results_per_page"] == 1
    assert set(kwargs["select"]) == {
        "supplier_id",
        "supplier_name",
        "issued_at",
        "revoked_at",
    }


def test_story_1_7_a_revoked_link_resolves_as_revoked() -> None:
    revoked = {**ENTITY, "revoked_at": datetime(2026, 9, 20, tzinfo=UTC)}
    link = _resolve(FakeTable([revoked]))
    assert link is not None and not link.is_active


def test_story_1_7_an_unknown_hash_resolves_to_none() -> None:
    assert _resolve(FakeTable([])) is None
