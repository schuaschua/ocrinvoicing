"""`SupplierLinkRegistry` over the Azure Table `supplierlinks` (AD-6). supplier-api
signs in with its user-assigned managed identity and only resolves; the supplier load
script (Story 1.6) signs in as the operator and issues, lists and revokes. Key
scheme: `ports/links.py`."""

import logging
from collections.abc import AsyncIterator, Awaitable, Mapping
from datetime import UTC, datetime
from typing import Any, NoReturn, Protocol, Self
from uuid import UUID

from azure.core.credentials_async import AsyncTokenCredential
from azure.core.exceptions import (
    AzureError,
    ClientAuthenticationError,
    ResourceNotFoundError,
)
from azure.data.tables import UpdateMode
from azure.data.tables.aio import TableClient
from azure.identity.aio import ManagedIdentityCredential

from invoicing.adapters.logging import log_event
from invoicing.adapters.storage_errors import raise_unavailable
from invoicing.domain.errors import ServiceUnavailableError
from invoicing.ports.links import (
    SUPPLIER_LINKS_TABLE,
    RegisteredLink,
    SupplierLink,
    partition_key,
)

# A query, not a point read: the keys then travel in `$filter`, which the Azure SDK's
# logging and tracing policies redact, instead of the URL path, which they record
# (AD-14: the hash never reaches logs or telemetry). An exact PartitionKey and RowKey
# filter is still a single-entity lookup for the service.
_FILTER = "PartitionKey eq @pk and RowKey eq @rk"
_SELECT = ["supplier_id", "supplier_name", "issued_at", "revoked_at"]
# The load script's listing (Story 1.6): a scan on `supplier_id`, which is small (one
# row per link ever issued). The keys come back as properties, never in a URL.
_BY_SUPPLIER = "supplier_id eq @sid"
_BY_SUPPLIER_SELECT = ["PartitionKey", "RowKey", *_SELECT]


class _TableClient(Protocol):
    # Not `async def`: the SDK's tracing decorator types it as returning an Awaitable.
    def create_entity(
        self, entity: Mapping[str, Any], **kwargs: Any
    ) -> Awaitable[Mapping[str, Any]]: ...

    def submit_transaction(
        self, operations: Any, **kwargs: Any
    ) -> Awaitable[list[Mapping[str, Any]]]: ...

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
    """Reads `supplierlinks` for supplier-api; issues, lists and revokes links for the
    supplier load script (Story 1.6), the only writer."""

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

    @classmethod
    def with_credential(
        cls, account_name: str, credential: AsyncTokenCredential
    ) -> Self:
        """A registry on `account_name` signed in with `credential` (the load script
        passes the operator's Azure CLI sign-in); closing the registry closes it."""
        table = TableClient(
            endpoint=f"https://{account_name}.table.core.windows.net",
            table_name=SUPPLIER_LINKS_TABLE,
            credential=credential,
        )
        return cls(table, credential)

    async def issue(self, token_hash: str, link: SupplierLink) -> None:
        # An insert, never an upsert: an existing row (a hash collision) is refused.
        # The keys travel in the request body, not the URL path the SDK logs.
        entity: dict[str, Any] = {
            "PartitionKey": partition_key(token_hash),
            "RowKey": token_hash,
            "supplier_id": str(link.supplier_id),
            "supplier_name": link.supplier_name,
            "issued_at": (link.issued_at or datetime.now(UTC)).astimezone(UTC),
        }
        if link.revoked_at is not None:
            entity["revoked_at"] = link.revoked_at.astimezone(UTC)
        try:
            await self._table.create_entity(entity)
        except AzureError as error:
            raise_unavailable(_logger, "supplierlinks.unavailable", error)

    async def find_by_supplier(self, supplier_id: UUID) -> list[RegisteredLink]:
        entities = self._table.query_entities(
            _BY_SUPPLIER,
            parameters={"sid": str(supplier_id)},
            select=_BY_SUPPLIER_SELECT,
        )
        found: list[RegisteredLink] = []
        try:
            async for entity in entities:
                row_key = entity.get("RowKey")
                if not isinstance(row_key, str) or not row_key:
                    raise _CorruptRowError("MISSING_ROW_KEY")
                found.append(RegisteredLink(token_hash=row_key, link=_link(entity)))
        except _CorruptRowError as error:
            log_event(
                _logger,
                "supplierlinks.corrupt_row",
                level=logging.ERROR,
                code=error.code,
            )
            raise ServiceUnavailableError() from None
        except AzureError as error:
            raise_unavailable(_logger, "supplierlinks.unavailable", error)
        return found

    async def revoke(self, token_hash: str, at: datetime) -> None:
        # Merge one property into the existing row (a merge fails when the row is
        # missing, so it never creates one); rows are never deleted (AD-6). A
        # one-operation transaction keeps the keys out of the URL path, as above.
        entity = {
            "PartitionKey": partition_key(token_hash),
            "RowKey": token_hash,
            "revoked_at": at.astimezone(UTC),
        }
        try:
            await self._table.submit_transaction(
                [("update", entity, {"mode": UpdateMode.MERGE})]
            )
        except AzureError as error:
            raise_unavailable(_logger, "supplierlinks.unavailable", error)

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
