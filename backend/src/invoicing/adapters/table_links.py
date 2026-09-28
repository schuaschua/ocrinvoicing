"""`SupplierLinkRegistry` over the Azure Table `supplierlinks` (AD-6), signed in with
the app's user-assigned managed identity. Key scheme: `ports/links.py`."""

import logging
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from typing import Any, NoReturn, Protocol, Self
from uuid import UUID

from azure.core.exceptions import (
    AzureError,
    ClientAuthenticationError,
    ResourceNotFoundError,
)
from azure.data.tables.aio import TableClient
from azure.identity.aio import ManagedIdentityCredential

from invoicing.adapters.logging import log_event
from invoicing.domain.errors import ServiceUnavailableError
from invoicing.ports.links import SUPPLIER_LINKS_TABLE, SupplierLink, partition_key

# A query, not a point read: the keys then travel in `$filter`, which the Azure SDK's
# logging and tracing policies redact, instead of the URL path, which they record
# (AD-14: the hash never reaches logs or telemetry). An exact PartitionKey and RowKey
# filter is still a single-entity lookup for the service.
_FILTER = "PartitionKey eq @pk and RowKey eq @rk"
_SELECT = ["supplier_id", "supplier_name", "issued_at", "revoked_at"]


class _TableClient(Protocol):
    def query_entities(
        self,
        query_filter: str,
        *,
        parameters: dict[str, Any] | None = None,
        select: list[str] | None = None,
        results_per_page: int | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[Mapping[str, Any]]: ...

    async def close(self) -> None: ...


class _Closeable(Protocol):
    async def close(self) -> None: ...


_logger = logging.getLogger("invoicing.supplierlinks")


class _CorruptRowError(Exception):
    """A stored link row that can't be read; `code` names the fault, never a value."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _datetime(value: object) -> datetime | None:
    # Edm.DateTime comes back as a datetime; a row written with an ISO-8601 string
    # property is read too. Empty or null means "not set".
    if isinstance(value, datetime):
        parsed = value
    elif value in (None, ""):
        return None
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            raise _CorruptRowError("BAD_DATE") from None
    else:
        raise _CorruptRowError("BAD_DATE")
    # Timestamps are UTC by convention; a naive one is read as UTC.
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class TableSupplierLinkRegistry:
    """Reads `supplierlinks`; never writes it (only the load script does, Story 1.6)."""

    def __init__(
        self, table: _TableClient, credential: _Closeable | None = None
    ) -> None:
        self._table = table
        self._credential = credential

    @classmethod
    def with_managed_identity(cls, account_name: str, client_id: str) -> Self:
        """A registry on `account_name`, authenticated as the user-assigned identity."""
        credential = ManagedIdentityCredential(client_id=client_id)
        table = TableClient(
            endpoint=f"https://{account_name}.table.core.windows.net",
            table_name=SUPPLIER_LINKS_TABLE,
            credential=credential,
        )
        return cls(table, credential)

    async def resolve(self, token_hash: str) -> SupplierLink | None:
        entities = self._table.query_entities(
            _FILTER,
            parameters={"pk": partition_key(token_hash), "rk": token_hash},
            select=_SELECT,
            results_per_page=1,
        )
        # Every failure is a 503 with a plain message: the exception text may carry the
        # request URL, and a log holds a code only, never the hash (AD-14).
        try:
            async for entity in entities:
                return _link(entity)
        except _CorruptRowError as error:
            log_event(
                _logger,
                "supplierlinks.corrupt_row",
                level=logging.ERROR,
                code=error.code,
            )
            raise ServiceUnavailableError() from None
        # Permanent (identity, role or missing table), not transient: a distinct code
        # so an alert can tell them apart; the caller still sees 503.
        except ClientAuthenticationError:
            _unavailable("AUTH_FAILED", logging.ERROR)
        except ResourceNotFoundError:
            _unavailable("TABLE_NOT_FOUND", logging.ERROR)
        except AzureError:
            _unavailable("TRANSIENT", logging.WARNING)
        return None

    async def close(self) -> None:
        """Release the HTTP session and the credential."""
        await self._table.close()
        if self._credential is not None:
            await self._credential.close()


def _unavailable(code: str, level: int) -> NoReturn:
    log_event(_logger, "supplierlinks.unavailable", level=level, code=code)
    raise ServiceUnavailableError() from None


def _link(entity: Mapping[str, Any]) -> SupplierLink:
    raw_id = entity.get("supplier_id")
    if raw_id in (None, ""):
        raise _CorruptRowError("MISSING_SUPPLIER_ID")
    try:
        supplier_id = UUID(str(raw_id))
    except ValueError:
        raise _CorruptRowError("BAD_SUPPLIER_ID") from None
    name = entity.get("supplier_name")
    if not isinstance(name, str) or not name.strip():
        raise _CorruptRowError("MISSING_SUPPLIER_NAME")
    return SupplierLink(
        supplier_id=supplier_id,
        supplier_name=name.strip(),
        issued_at=_datetime(entity.get("issued_at")),
        revoked_at=_datetime(entity.get("revoked_at")),
    )
