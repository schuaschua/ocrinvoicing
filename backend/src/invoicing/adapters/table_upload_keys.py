"""`UploadKeyStore` over the Azure Table `uploadkeys` (AD-6), signed in with the app's
user-assigned managed identity. Key scheme: `ports/upload_keys.py`."""

import logging
import re
from collections.abc import AsyncIterator, Awaitable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, Protocol, Self
from uuid import UUID

from azure.core import MatchConditions
from azure.core.exceptions import AzureError, HttpResponseError, ResourceExistsError
from azure.data.tables import UpdateMode
from azure.data.tables.aio import TableClient
from azure.identity.aio import ManagedIdentityCredential

from invoicing.adapters.logging import log_event
from invoicing.adapters.storage_errors import raise_unavailable
from invoicing.domain.errors import ServiceUnavailableError
from invoicing.domain.upload import DeviceCheck, UploadContentType
from invoicing.ports.intake import IntakeSource
from invoicing.ports.upload_keys import (
    UPLOAD_KEYS_TABLE,
    AgedUploadKey,
    UploadKey,
    partition_key,
    row_key,
)

# A query, not a point read, as in table_links.py: the key travels in `$filter`, which
# the SDK's logging and tracing redact, instead of the URL path, which they record.
_FILTER = "PartitionKey eq @pk and RowKey eq @rk"
_SELECT = [
    "invoice_id",
    "supplier_id",
    "correlation_id",
    "created_at",
    "content_sha256",
    "content_type",
    "device_check",
    "source",
    "delivery_id",
]
# The sweeper's listing (Story 2.2): a table scan on `created_at`, which is small (keys
# live 24 hours). The keys come back as properties, never in a URL.
_OLDER_THAN = "created_at lt @cutoff"
_AGED_SELECT = ["PartitionKey", "RowKey", "recovered_at", *_SELECT]
# The service returns at most 1,000 entities a page.
_MAX_PAGE = 1000
# An insert refused because the key exists, then a read that finds nothing, means the
# sweeper deleted the row in between: insert again, once.
_ATTEMPTS = 2
_SHA256 = re.compile(r"[0-9a-f]{64}")

_logger = logging.getLogger("invoicing.uploadkeys")


class _TableClient(Protocol):
    # Not `async def`: the SDK's tracing decorator types it as returning an Awaitable.
    def create_entity(
        self, entity: Mapping[str, Any], **kwargs: Any
    ) -> Awaitable[Mapping[str, Any]]: ...

    def query_entities(
        self,
        query_filter: str,
        *,
        parameters: dict[str, Any] | None = None,
        select: list[str] | None = None,
        results_per_page: int | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[Mapping[str, Any]]: ...

    def submit_transaction(
        self, operations: Any, **kwargs: Any
    ) -> Awaitable[list[Mapping[str, Any]]]: ...

    async def close(self) -> None: ...


class _Closeable(Protocol):
    async def close(self) -> None: ...


class _CorruptRowError(Exception):
    """A stored key row that can't be read; `code` names the fault, never a value."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class TableUploadKeyStore:
    """Inserts and reads `uploadkeys` (`UploadKeyStore`); lists and deletes old rows
    for the sweeper (`AgedUploadKeys`, Story 2.2)."""

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
            table_name=UPLOAD_KEYS_TABLE,
            credential=credential,
        )
        return cls(table, credential)

    async def claim(self, key: UUID, candidate: UploadKey) -> tuple[UploadKey, bool]:
        for _ in range(_ATTEMPTS):
            try:
                await self._table.create_entity(_entity(key, candidate))
                return candidate, True
            except ResourceExistsError:
                pass
            except AzureError as error:
                raise_unavailable(_logger, "uploadkeys.unavailable", error)
            stored = await self._read(key)
            if stored is not None:
                return stored, False
        log_event(
            _logger, "uploadkeys.unavailable", level=logging.ERROR, code="VANISHED"
        )
        raise ServiceUnavailableError()

    async def _read(self, key: UUID) -> UploadKey | None:
        entities = self._table.query_entities(
            _FILTER,
            parameters={"pk": partition_key(key), "rk": row_key(key)},
            select=_SELECT,
            results_per_page=1,
        )
        try:
            async for entity in entities:
                return _upload_key(entity)
        except _CorruptRowError as error:
            log_event(
                _logger,
                "uploadkeys.corrupt_row",
                level=logging.ERROR,
                code=error.code,
            )
            raise ServiceUnavailableError() from None
        except AzureError as error:
            raise_unavailable(_logger, "uploadkeys.unavailable", error)
        return None

    async def older_than(self, cutoff: datetime, limit: int) -> list[AgedUploadKey]:
        entities = self._table.query_entities(
            _OLDER_THAN,
            parameters={"cutoff": cutoff.astimezone(UTC)},
            select=_AGED_SELECT,
            results_per_page=min(limit, _MAX_PAGE),
        )
        aged: list[AgedUploadKey] = []
        try:
            async for entity in entities:
                try:
                    aged.append(_aged(entity))
                except _CorruptRowError as error:
                    # One bad row never stops the sweep; the code names the fault.
                    log_event(
                        _logger,
                        "uploadkeys.corrupt_row",
                        level=logging.ERROR,
                        code=error.code,
                    )
                if len(aged) >= limit:
                    break
        except AzureError as error:
            raise_unavailable(_logger, "uploadkeys.unavailable", error)
        return aged

    async def mark_recovered(
        self, item: AgedUploadKey, at: datetime
    ) -> AgedUploadKey | None:
        entity = {
            "PartitionKey": partition_key(item.key),
            "RowKey": row_key(item.key),
            "recovered_at": at.astimezone(UTC),
        }
        # Merge one property, only if the row is unchanged since it was listed.
        options = {
            "mode": UpdateMode.MERGE,
            "etag": item.etag,
            "match_condition": MatchConditions.IfNotModified,
        }
        results = await self._transact(("update", entity, options))
        if results is None:
            return None
        etag = results[0].get("etag") if results else None
        if not etag:
            log_event(
                _logger, "uploadkeys.unavailable", level=logging.ERROR, code="NO_ETAG"
            )
            raise ServiceUnavailableError()
        return replace(item, etag=str(etag), recovered_at=at)

    async def delete(self, item: AgedUploadKey) -> bool:
        entity = {"PartitionKey": partition_key(item.key), "RowKey": row_key(item.key)}
        options = {"etag": item.etag, "match_condition": MatchConditions.IfNotModified}
        return (
            await self._transact(("delete", entity, options), gone_ok=True) is not None
        )

    async def _transact(
        self,
        operation: tuple[str, Mapping[str, Any], Mapping[str, Any]],
        *,
        gone_ok: bool = False,
    ) -> list[Mapping[str, Any]] | None:
        """One-operation transaction: the key travels in the request body, never in
        the URL path that SDK logging and tracing record (as for reads above). None
        when the row changed since it was listed (or, unless `gone_ok`, is gone)."""
        try:
            return list(await self._table.submit_transaction([operation]))
        except HttpResponseError as error:
            code = getattr(error, "error_code", None)
            if code == "ResourceNotFound":
                # Already gone (a concurrent sweep).
                return [] if gone_ok else None
            if code == "UpdateConditionNotSatisfied":
                log_event(
                    _logger,
                    "uploadkeys.changed",
                    level=logging.INFO,
                    code="ETAG_MISMATCH",
                )
                return None
            raise_unavailable(_logger, "uploadkeys.unavailable", error)
        except AzureError as error:
            raise_unavailable(_logger, "uploadkeys.unavailable", error)

    async def close(self) -> None:
        """Release the HTTP session and the credential."""
        await self._table.close()
        if self._credential is not None:
            await self._credential.close()


def _entity(key: UUID, value: UploadKey) -> dict[str, Any]:
    entity: dict[str, Any] = {
        "PartitionKey": partition_key(key),
        "RowKey": row_key(key),
        "invoice_id": str(value.invoice_id),
        "supplier_id": str(value.supplier_id),
        "correlation_id": str(value.correlation_id),
        "created_at": value.created_at.astimezone(UTC),
        "content_sha256": value.content_sha256,
        "content_type": value.content_type.value,
        "device_check": value.device_check.value,
        "source": value.source.value,
    }
    # Only a goods-in scan has a delivery; the property is absent otherwise.
    if value.delivery_id is not None:
        entity["delivery_id"] = str(value.delivery_id)
    return entity


def _uuid(entity: Mapping[str, Any], name: str) -> UUID:
    raw = entity.get(name)
    if raw in (None, ""):
        raise _CorruptRowError(f"MISSING_{name.upper()}")
    try:
        return UUID(str(raw))
    except ValueError:
        raise _CorruptRowError(f"BAD_{name.upper()}") from None


def _aged(entity: Mapping[str, Any]) -> AgedUploadKey:
    metadata = getattr(entity, "metadata", None) or {}
    etag = metadata.get("etag")
    if not etag:
        raise _CorruptRowError("MISSING_ETAG")
    recovered = entity.get("recovered_at")
    return AgedUploadKey(
        key=_row_key(entity.get("RowKey")),
        value=_upload_key(entity),
        etag=str(etag),
        recovered_at=None if recovered in (None, "") else _created_at(recovered),
    )


def _row_key(value: object) -> UUID:
    try:
        return UUID(str(value))
    except ValueError:
        raise _CorruptRowError("BAD_ROW_KEY") from None


def _created_at(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            raise _CorruptRowError("BAD_CREATED_AT") from None
    else:
        raise _CorruptRowError("BAD_CREATED_AT")
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _upload_key(entity: Mapping[str, Any]) -> UploadKey:
    invoice_id = _uuid(entity, "invoice_id")
    # Every invoice id is a UUIDv7 (the reference is derived from its random part).
    if invoice_id.version != 7:
        raise _CorruptRowError("BAD_INVOICE_ID")
    return UploadKey(
        invoice_id=invoice_id,
        supplier_id=_uuid(entity, "supplier_id"),
        correlation_id=_uuid(entity, "correlation_id"),
        created_at=_created_at(entity.get("created_at")),
        content_sha256=_sha256(entity.get("content_sha256")),
        content_type=_content_type(entity.get("content_type")),
        device_check=_device_check(entity.get("device_check")),
        source=_source(entity.get("source")),
        delivery_id=(
            None
            if entity.get("delivery_id") in (None, "")
            else _uuid(entity, "delivery_id")
        ),
    )


def _source(value: object) -> IntakeSource:
    # A row written before Story 4.1 has none: all were supplier-link uploads.
    if value is None or value == "":
        return IntakeSource.LINK
    try:
        return IntakeSource(str(value))
    except ValueError:
        raise _CorruptRowError("BAD_SOURCE") from None


def _sha256(value: object) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise _CorruptRowError("BAD_CONTENT_SHA256")
    return value


def _content_type(value: object) -> UploadContentType:
    try:
        return UploadContentType(str(value))
    except ValueError:
        raise _CorruptRowError("BAD_CONTENT_TYPE") from None


def _device_check(value: object) -> DeviceCheck:
    # A row written before Story 1.9 has none (or an empty one): all were `passed`.
    if value is None or value == "":
        return DeviceCheck.PASSED
    try:
        return DeviceCheck(str(value))
    except ValueError:
        raise _CorruptRowError("BAD_DEVICE_CHECK") from None
