"""`ReminderStore` over the Azure Table `supplierreminders` (AD-6), signed in with the
app's user-assigned managed identity. Key scheme: `ports/reminders.py`."""

import logging
from collections.abc import Awaitable, Mapping
from typing import Any, Protocol, Self
from uuid import UUID

from azure.core.exceptions import AzureError, HttpResponseError
from azure.data.tables.aio import TableClient
from azure.identity.aio import ManagedIdentityCredential

from invoicing.adapters.storage_errors import raise_unavailable
from invoicing.ports.reminders import (
    SUPPLIER_REMINDERS_TABLE,
    partition_key,
    row_key,
)

# Characters the Table service never allows in a key: a PO number holding one can have
# no reminder row, so there is nothing to delete.
_FORBIDDEN_KEY_CHARACTERS = frozenset("/\\#?")

_logger = logging.getLogger("invoicing.reminders")


class _TableClient(Protocol):
    # Not `async def`: the SDK's tracing decorator types it as returning an Awaitable.
    def submit_transaction(
        self, operations: Any, **kwargs: Any
    ) -> Awaitable[list[Mapping[str, Any]]]: ...

    async def close(self) -> None: ...


class _Closeable(Protocol):
    async def close(self) -> None: ...


class TableReminderStore:
    """Deletes `supplierreminders` rows (`ReminderStore`)."""

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
        if not key or any(
            c in _FORBIDDEN_KEY_CHARACTERS or not c.isprintable() for c in key
        ):
            return
        entity = {"PartitionKey": partition_key(supplier_id), "RowKey": key}
        try:
            # A one-operation transaction, as in table_upload_keys.py: the keys travel
            # in the request body, never in the URL path that SDK logging records.
            await self._table.submit_transaction([("delete", entity)])
        except HttpResponseError as error:
            if getattr(error, "error_code", None) == "ResourceNotFound":
                return
            raise_unavailable(_logger, "reminders.unavailable", error)
        except AzureError as error:
            raise_unavailable(_logger, "reminders.unavailable", error)

    async def close(self) -> None:
        """Release the HTTP session and the credential."""
        await self._table.close()
        if self._credential is not None:
            await self._credential.close()
