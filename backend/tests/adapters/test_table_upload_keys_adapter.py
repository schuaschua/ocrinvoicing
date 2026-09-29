"""Story 1.8: the `uploadkeys` Table adapter (AD-6): insert-if-absent, the concurrent
loser reading the winner, error mapping, and no key in logs or spans."""

import asyncio
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from azure.core.exceptions import (
    ResourceExistsError,
)

from invoicing.adapters.table_upload_keys import TableUploadKeyStore
from invoicing.domain.upload import DeviceCheck, UploadContentType
from invoicing.ports.upload_keys import UploadKey, UploadKeyStore

KEY = UUID("3fa85f64-5717-4562-b3fc-2c963f66afa6")
CREATED = datetime(2026, 9, 29, 1, 30, tzinfo=UTC)
MINE = UploadKey(
    invoice_id=UUID("0192f0c1-7a2b-7c3d-8e4f-0123456789ab"),
    supplier_id=UUID("0192f0c1-0000-7000-8000-000000000001"),
    correlation_id=UUID("0192f0c1-0000-7000-8000-0000000000c1"),
    created_at=CREATED,
    content_sha256="ab" * 32,
    content_type=UploadContentType.JPEG,
    device_check=DeviceCheck.PASSED,
)
THEIRS = UploadKey(
    invoice_id=UUID("0192f0c1-7a2b-7c3d-8e4f-0000000000ff"),
    supplier_id=UUID("0192f0c1-0000-7000-8000-000000000002"),
    correlation_id=UUID("0192f0c1-0000-7000-8000-0000000000c2"),
    created_at=CREATED,
    content_sha256="cd" * 32,
    content_type=UploadContentType.PDF,
    device_check=DeviceCheck.OVERRIDDEN,
)


def _row(value: UploadKey) -> dict[str, Any]:
    return {
        "invoice_id": str(value.invoice_id),
        "supplier_id": str(value.supplier_id),
        "correlation_id": str(value.correlation_id),
        "created_at": value.created_at,
        "content_sha256": value.content_sha256,
        "content_type": value.content_type.value,
        "device_check": value.device_check.value,
    }


class FakeTable:
    """A dict-backed `uploadkeys`: create_entity refuses an existing key."""

    def __init__(
        self, rows: dict[tuple[str, str], Mapping[str, Any]] | None = None
    ) -> None:
        self.rows = dict(rows or {})
        self.created: list[Mapping[str, Any]] = []
        self.queries: list[tuple[str, dict[str, Any]]] = []
        self.closed = False

    async def create_entity(self, entity: Mapping[str, Any], **kwargs: Any) -> Any:
        pk_rk = (entity["PartitionKey"], entity["RowKey"])
        if pk_rk in self.rows:
            raise ResourceExistsError("EntityAlreadyExists")
        self.rows[pk_rk] = entity
        self.created.append(entity)
        return {}

    def query_entities(
        self, query_filter: str, **kwargs: Any
    ) -> AsyncIterator[Mapping[str, Any]]:
        self.queries.append((query_filter, kwargs))
        return self._iterate(kwargs["parameters"], kwargs.get("select"))

    async def _iterate(
        self, parameters: dict[str, str], select: list[str] | None
    ) -> AsyncIterator[Mapping[str, Any]]:
        row = self.rows.get((parameters["pk"], parameters["rk"]))
        if row is not None:
            # Like the service: only the selected properties come back.
            yield row if select is None else {k: row[k] for k in select if k in row}

    async def close(self) -> None:
        self.closed = True


def _claim(table: FakeTable, candidate: UploadKey = MINE) -> tuple[UploadKey, bool]:
    store: UploadKeyStore = TableUploadKeyStore(table)
    return asyncio.run(store.claim(KEY, candidate))


def test_story_1_8_a_new_key_is_inserted_with_the_contract_fields() -> None:
    table = FakeTable()
    assert _claim(table) == (MINE, True)
    ((entity,),) = [table.created]
    assert entity == {
        "PartitionKey": "3f",
        "RowKey": str(KEY),
        **_row(MINE),
    }
    # No read when the insert wins.
    assert table.queries == []


def test_story_1_8_an_existing_key_returns_the_stored_upload_and_writes_nothing() -> (
    None
):
    table = FakeTable({("3f", str(KEY)): _row(THEIRS)})
    assert _claim(table) == (THEIRS, False)
    assert table.created == []
    ((query_filter, kwargs),) = table.queries
    # The key is a parameter, never pasted into the filter text.
    assert str(KEY) not in query_filter
    assert kwargs["parameters"] == {"pk": "3f", "rk": str(KEY)}


def test_story_1_8_two_racing_claims_get_the_same_upload() -> None:
    table = FakeTable()
    store = TableUploadKeyStore(table)
    other = UploadKey(
        invoice_id=UUID("0192f0c1-7a2b-7c3d-8e4f-0000000000aa"),
        supplier_id=MINE.supplier_id,
        correlation_id=UUID("0192f0c1-0000-7000-8000-0000000000c3"),
        created_at=CREATED,
        content_sha256=MINE.content_sha256,
        content_type=MINE.content_type,
        device_check=MINE.device_check,
    )

    async def race() -> list[tuple[UploadKey, bool]]:
        return list(
            await asyncio.gather(store.claim(KEY, MINE), store.claim(KEY, other))
        )

    (first, first_inserted), (second, second_inserted) = asyncio.run(race())
    assert first == second
    assert [first_inserted, second_inserted].count(True) == 1
    assert len(table.created) == 1
