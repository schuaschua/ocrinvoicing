"""`ReminderStore`, `ReminderWriter` and `ReminderReader` over the Azure Table
`supplierreminders` (AD-6), signed in with the app's user-assigned managed identity.
Key scheme: `ports/reminders.py`.

Keys never travel in a URL path, which SDK logging and tracing record: writes are
transactions (keys in the request body), a supplier's read is a query (the key in
`$filter`, which they redact) and the weekly job's listing is a plain table scan."""

import logging
from collections import defaultdict
from collections.abc import AsyncIterator, Awaitable, Mapping, Sequence
from typing import Any, Protocol, Self
from uuid import UUID

from azure.core.exceptions import AzureError, HttpResponseError
from azure.data.tables.aio import TableClient
from azure.identity.aio import ManagedIdentityCredential

from invoicing.adapters.logging import log_event
from invoicing.adapters.storage_errors import raise_unavailable
from invoicing.ports.reminders import (
    SUPPLIER_REMINDERS_TABLE,
    StillOwed,
    partition_key,
    row_key,
    storable,
)

# The Table service's limit on one transaction.
MAX_TRANSACTION_OPERATIONS = 100
_PARTITION = "PartitionKey eq @pk"
_KEYS = ["PartitionKey", "RowKey"]

_logger = logging.getLogger("invoicing.reminders")


class _TableClient(Protocol):
    # Not `async def`: the SDK's tracing decorator types it as returning an Awaitable.
    def submit_transaction(
        self, operations: Any, **kwargs: Any
    ) -> Awaitable[list[Mapping[str, Any]]]: ...

    def list_entities(
        self, *, select: list[str] | None = None, **kwargs: Any
    ) -> AsyncIterator[Mapping[str, Any]]: ...

    def query_entities(
        self,
        query_filter: str,
        *,
        parameters: dict[str, Any] | None = None,
        select: list[str] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[Mapping[str, Any]]: ...

    async def close(self) -> None: ...


class _Closeable(Protocol):
    async def close(self) -> None: ...


class TableReminderStore:
    """Deletes one row for the validate stage (`ReminderStore`), replaces the whole
    table for the weekly job (`ReminderWriter`) and lists a supplier's rows for
    supplier-api (`ReminderReader`)."""

    def __init__(
        self, table: _TableClient, credential: _Closeable | None = None
    ) -> None:
        self._table = table
        self._credential = credential

    @classmethod
    def with_managed_identity(cls, account_name: str, client_id: str) -> Self:
        """A store on `account_name`, authenticated as the user-assigned identity."""
        credential = ManagedIdentityCredential(client_id=client_id)
        table = TableClient(
            endpoint=f"https://{account_name}.table.core.windows.net",
            table_name=SUPPLIER_REMINDERS_TABLE,
            credential=credential,
        )
        return cls(table, credential)

    async def delete(self, supplier_id: UUID, po_number: str) -> None:
        key = row_key(po_number)
        # A PO number the table can't hold has no row, so there is nothing to delete.
        if not storable(key):
            return
        entity = {"PartitionKey": partition_key(supplier_id), "RowKey": key}
        try:
            # A one-operation transaction, as in table_upload_keys.py.
            await self._table.submit_transaction([("delete", entity)])
        except HttpResponseError as error:
            if getattr(error, "error_code", None) == "ResourceNotFound":
                return
            raise_unavailable(_logger, "reminders.unavailable", error)
        except AzureError as error:
            raise_unavailable(_logger, "reminders.unavailable", error)

    async def replace_all(
        self, rows_by_supplier: Mapping[UUID, Sequence[str]], still_owed: StillOwed
    ) -> int:
        wanted: dict[str, set[str]] = {}
        skipped = 0
        for supplier_id, po_numbers in rows_by_supplier.items():
            keys = {row_key(po) for po in po_numbers}
            good = {key for key in keys if storable(key)}
            skipped += len(keys) - len(good)
            if good:
                wanted[partition_key(supplier_id)] = good
        if skipped:
            # By code and count only, never the PO number.
            log_event(
                _logger,
                "reminders.key_skipped",
                level=logging.WARNING,
                code="UNSTORABLE_PO_NUMBER",
                count=skipped,
            )
        stored = await self._existing()
        written = 0
        for partition in sorted(stored.keys() | wanted.keys()):
            written += await self._replace_partition(
                partition,
                wanted.get(partition, set()),
                stored.get(partition, set()),
                still_owed,
            )
        return written

    async def _existing(self) -> dict[str, set[str]]:
        """Every row, by partition: a scan with no key in the URL."""
        stored: dict[str, set[str]] = defaultdict(set)
        try:
            async for entity in self._table.list_entities(select=_KEYS):
                stored[str(entity["PartitionKey"])].add(str(entity["RowKey"]))
        except AzureError as error:
            raise_unavailable(_logger, "reminders.unavailable", error)
        return stored

    async def _partition(self, partition: str) -> set[str]:
        try:
            return {
                str(entity["RowKey"])
                async for entity in self._table.query_entities(
                    _PARTITION, parameters={"pk": partition}, select=["RowKey"]
                )
            }
        except AzureError as error:
            raise_unavailable(_logger, "reminders.unavailable", error)

    async def _replace_partition(
        self,
        partition: str,
        wanted: set[str],
        stored: set[str],
        still_owed: StillOwed,
        *,
        retry: bool = True,
    ) -> int:
        """Upsert the partition's wanted rows that are still owed, then delete its
        stale ones, in transactions of at most 100 operations (one partition each).
        Upserts first, so a reader or a failure part-way never sees too few rows.
        Returns how many rows were upserted."""
        # AD-13: re-checked just before this partition's write (a validate delete,
        # Story 2.6, is never undone).
        owed = (await still_owed(sorted(wanted))) & wanted if wanted else set()
        operations: list[tuple[str, dict[str, str]]] = [
            ("upsert", {"PartitionKey": partition, "RowKey": key})
            for key in sorted(owed)
        ] + [
            ("delete", {"PartitionKey": partition, "RowKey": key})
            for key in sorted(stored - owed)
        ]
        for start in range(0, len(operations), MAX_TRANSACTION_OPERATIONS):
            chunk = operations[start : start + MAX_TRANSACTION_OPERATIONS]
            try:
                await self._table.submit_transaction(chunk)
            except HttpResponseError as error:
                # A stale row deleted since the listing (the validate stage, Story
                # 2.6) fails the whole transaction: read the partition again, once.
                if retry and getattr(error, "error_code", None) == "ResourceNotFound":
                    current = await self._partition(partition)
                    return await self._replace_partition(
                        partition, wanted, current, still_owed, retry=False
                    )
                raise_unavailable(_logger, "reminders.unavailable", error)
            except AzureError as error:
                raise_unavailable(_logger, "reminders.unavailable", error)
        return len(owed)

    async def list_for(self, supplier_id: UUID) -> list[str]:
        return sorted(await self._partition(partition_key(supplier_id)))

    async def close(self) -> None:
        """Release the HTTP session and the credential."""
        await self._table.close()
        if self._credential is not None:
            await self._credential.close()
