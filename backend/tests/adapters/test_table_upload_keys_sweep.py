"""Story 2.2: the sweeper's side of the `uploadkeys` adapter (AD-6): list keys older
than a cutoff (capped, with their ETags), mark an orphan recovered and delete a key,
each conditional on the listed ETag, never putting a key in a URL or a log. Story 2.6:
the `supplierreminders` adapter's delete, the same way."""

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from azure.core import MatchConditions
from azure.core.exceptions import HttpResponseError

from invoicing.adapters.table_reminders import TableReminderStore
from invoicing.adapters.table_upload_keys import TableUploadKeyStore
from invoicing.domain.errors import ServiceUnavailableError
from invoicing.domain.upload import DeviceCheck, UploadContentType
from invoicing.ports.reminders import ReminderStore
from invoicing.ports.upload_keys import AgedUploadKey, AgedUploadKeys, UploadKey

KEY = UUID("3fa85f64-5717-4562-b3fc-2c963f66afa6")
ETAG = "W/\"datetime'2026-09-28T01%3A30%3A00.1Z'\""
NEW_ETAG = "W/\"datetime'2026-09-29T02%3A00%3A00.1Z'\""
ENTRY = UploadKey(
    invoice_id=UUID("0192f0c1-7a2b-7c3d-8e4f-0123456789ab"),
    supplier_id=UUID("0192f0c1-0000-7000-8000-000000000001"),
    correlation_id=UUID("0192f0c1-0000-7000-8000-0000000000c1"),
    created_at=datetime(2026, 9, 28, 1, 30, tzinfo=UTC),
    content_sha256="ab" * 32,
    content_type=UploadContentType.JPEG,
    device_check=DeviceCheck.PASSED,
)
ITEM = AgedUploadKey(KEY, ENTRY, ETAG)


class FakeTable:
    def __init__(self, error_code: str | None = None) -> None:
        self.transactions: list[list[Any]] = []
        self.error_code = error_code

    async def submit_transaction(self, operations: Any, **kwargs: Any) -> Any:
        self.transactions.append(list(operations))
        if self.error_code is not None:
            error = HttpResponseError(self.error_code)
            error.error_code = self.error_code  # set by the SDK
            raise error
        return [{"etag": NEW_ETAG}]


def _store(table: FakeTable) -> AgedUploadKeys:
    return TableUploadKeyStore(table)  # type: ignore[arg-type]  # a structural fake


def _reminders(table: FakeTable) -> ReminderStore:
    return TableReminderStore(table)  # type: ignore[arg-type]  # a structural fake


# --- Conditional writes ---------------------------------------------------------------------


def test_story_2_2_delete_is_one_operation_conditional_on_the_listed_etag() -> None:
    table = FakeTable()
    assert asyncio.run(_store(table).delete(ITEM)) is True
    assert table.transactions == [
        [
            (
                "delete",
                {"PartitionKey": "3f", "RowKey": str(KEY)},
                {"etag": ETAG, "match_condition": MatchConditions.IfNotModified},
            )
        ]
    ]

    # --- Story 2.6: a matched PO's reminder row, keyed by supplier and PO number
    supplier_id = ENTRY.supplier_id
    table = FakeTable()
    asyncio.run(_reminders(table).delete(supplier_id, "PO-45012"))
    assert table.transactions == [
        [("delete", {"PartitionKey": str(supplier_id), "RowKey": "PO-45012"})]
    ]
    # A missing row is fine; a key the service can never store is not sent.
    asyncio.run(_reminders(FakeTable("ResourceNotFound")).delete(supplier_id, "PO-1"))
    table = FakeTable()
    asyncio.run(_reminders(table).delete(supplier_id, "PO/1"))
    assert table.transactions == []
    # Any other failure is the caller's to log (the validate stage never fails on it).
    with pytest.raises(ServiceUnavailableError):
        asyncio.run(
            _reminders(FakeTable("AuthorizationFailure")).delete(supplier_id, "PO-1")
        )
