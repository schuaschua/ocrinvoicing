"""Story 1.6: the `supplierlinks` adapter issues, lists and revokes links (AD-6). A fake
client checks the mapping; the real SDK pipeline over a fake transport checks that the
token hash never travels in a URL path or reaches the SDK's logs. No network."""

import asyncio
import logging
from collections.abc import AsyncIterator, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, Self
from uuid import UUID

import pytest
from azure.core.credentials import AzureNamedKeyCredential
from azure.core.exceptions import (
    ClientAuthenticationError,
    ResourceExistsError,
    ServiceRequestError,
)
from azure.core.pipeline.transport import AsyncHttpResponse, AsyncHttpTransport
from azure.data.tables import UpdateMode
from azure.data.tables.aio import TableClient

from invoicing.adapters.logging import event_fields
from invoicing.adapters.table_links import TableSupplierLinkRegistry
from invoicing.domain.errors import ServiceUnavailableError
from invoicing.ports.links import RegisteredLink, SupplierLink

TOKEN_HASH = "3f" + "a1" * 31
OTHER_HASH = "07" + "b2" * 31
SUPPLIER_ID = UUID("01a0c450-6c00-7b7b-8aa9-4ccade9f5526")
ISSUED = datetime(2026, 9, 29, 1, 2, 3, tzinfo=UTC)
LINK = SupplierLink(
    supplier_id=SUPPLIER_ID,
    supplier_name="Synthetic Alpha Building Supplies",
    issued_at=ISSUED,
    revoked_at=None,
)


class FakeWriteTable:
    """Records create_entity, query_entities and submit_transaction calls."""

    def __init__(
        self,
        entities: list[Mapping[str, Any]] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.entities = entities or []
        self.error = error
        self.created: list[Mapping[str, Any]] = []
        self.queries: list[tuple[str, dict[str, Any]]] = []
        self.transactions: list[Any] = []

    async def create_entity(self, entity: Mapping[str, Any], **kwargs: Any) -> Any:
        if self.error is not None:
            raise self.error
        self.created.append(entity)
        return {}

    def query_entities(
        self, query_filter: str, **kwargs: Any
    ) -> AsyncIterator[Mapping[str, Any]]:
        self.queries.append((query_filter, kwargs))
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[Mapping[str, Any]]:
        if self.error is not None:
            raise self.error
        for entity in self.entities:
            yield entity

    async def submit_transaction(self, operations: Any, **kwargs: Any) -> Any:
        if self.error is not None:
            raise self.error
        self.transactions.append(list(operations))
        return [{}]

    async def close(self) -> None:
        return None


def test_story_1_6_issue_list_and_revoke_map_to_the_reader_s_rows() -> None:
    table = FakeWriteTable()
    registry = TableSupplierLinkRegistry(table)
    asyncio.run(registry.issue(TOKEN_HASH, LINK))
    # The Story 1.7 reader's row shape: supplier_id as a UUID string, a non-blank
    # name, issued_at a UTC datetime and no revoked_at (active).
    assert table.created == [
        {
            "PartitionKey": "3f",
            "RowKey": TOKEN_HASH,
            "supplier_id": str(SUPPLIER_ID),
            "supplier_name": "Synthetic Alpha Building Supplies",
            "issued_at": ISSUED,
        }
    ]

    revoked = datetime(2026, 9, 30, 8, tzinfo=UTC)
    asyncio.run(registry.revoke(TOKEN_HASH, revoked))
    # A merge of revoked_at only: the row is kept (AD-6), never deleted or replaced.
    (((kind, entity, options),),) = table.transactions
    assert (kind, options) == ("update", {"mode": UpdateMode.MERGE})
    assert entity == {"PartitionKey": "3f", "RowKey": TOKEN_HASH, "revoked_at": revoked}

    table.entities = [
        {**table.created[0], "revoked_at": revoked},
        {**table.created[0], "PartitionKey": "07", "RowKey": OTHER_HASH},
    ]
    found = asyncio.run(registry.find_by_supplier(SUPPLIER_ID))
    assert found == [
        RegisteredLink(TOKEN_HASH, replace(LINK, revoked_at=revoked)),
        RegisteredLink(OTHER_HASH, LINK),
    ]
    ((query_filter, kwargs),) = table.queries
    assert str(SUPPLIER_ID) not in query_filter
    assert kwargs["parameters"] == {"sid": str(SUPPLIER_ID)}


def test_story_1_6_a_table_failure_is_unavailable_and_logs_a_code_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    exists = ResourceExistsError(f"row {TOKEN_HASH} exists")
    exists.status_code = 409
    for error, code in (
        (ServiceRequestError("reset"), "TRANSIENT"),
        (ClientAuthenticationError("no role"), "AUTH_FAILED"),
        (exists, "HTTP_409"),
    ):
        registry = TableSupplierLinkRegistry(FakeWriteTable(error=error))
        for call in (
            registry.issue(TOKEN_HASH, LINK),
            registry.find_by_supplier(SUPPLIER_ID),
            registry.revoke(TOKEN_HASH, ISSUED),
        ):
            caplog.clear()
            with (
                caplog.at_level(logging.DEBUG, logger="invoicing"),
                pytest.raises(ServiceUnavailableError) as raised,
            ):
                asyncio.run(call)
            assert raised.value.__cause__ is None
            assert [event_fields(r).get("code") for r in caplog.records] == [code]
            assert TOKEN_HASH not in caplog.text
    # A listed row the reader can't read is unavailable too.
    corrupt = FakeWriteTable([{"RowKey": TOKEN_HASH, "supplier_id": "nope"}])
    with pytest.raises(ServiceUnavailableError):
        asyncio.run(TableSupplierLinkRegistry(corrupt).find_by_supplier(SUPPLIER_ID))


def test_story_1_6_the_hash_travels_in_the_body_never_the_url_or_sdk_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    for call in ("issue", "revoke"):
        caplog.clear()
        _check_sdk_call(call, caplog)


class _Refusing(AsyncHttpResponse):
    def __init__(self, request: Any) -> None:
        super().__init__(request, None)
        self.status_code, self.reason = 503, "Service Unavailable"
        self.headers = {"Content-Type": "application/json"}
        self.content_type = self.headers["Content-Type"]

    def body(self) -> bytes:
        return b"{}"

    async def load_body(self) -> None:
        return None

    async def read(self) -> bytes:
        # The batch error path reads the body before raising.
        return b"{}"

    def stream_download(self, pipeline: Any, **kwargs: Any) -> Any:
        raise NotImplementedError


class FakeTransport(AsyncHttpTransport):
    """Records each request and answers 503: nothing goes over the network."""

    def __init__(self) -> None:
        self.requests: list[Any] = []

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def send(self, request: Any, **kwargs: Any) -> _Refusing:
        self.requests.append(request)
        return _Refusing(request)


def _check_sdk_call(call: str, caplog: pytest.LogCaptureFixture) -> None:
    # The service refuses (503), so the SDK's error path runs as well.
    transport = FakeTransport()
    table = TableClient(
        endpoint="https://babaloosealngst01.table.core.windows.net",
        table_name="supplierlinks",
        credential=AzureNamedKeyCredential("babaloosealngst01", "a2V5"),
        transport=transport,
        retry_total=0,
    )

    async def run() -> None:
        async with table:
            registry = TableSupplierLinkRegistry(table)
            if call == "issue":
                await registry.issue(TOKEN_HASH, LINK)
            else:
                await registry.revoke(TOKEN_HASH, ISSUED)

    with (
        caplog.at_level(logging.DEBUG, logger="azure"),
        pytest.raises(ServiceUnavailableError),
    ):
        asyncio.run(run())
    (request,) = transport.requests
    assert TOKEN_HASH not in request.url
    body = request.body or b""
    assert TOKEN_HASH.encode() in (body.encode() if isinstance(body, str) else body)
    logged = [record.getMessage() for record in caplog.records]
    assert logged, "the SDK's HTTP logging policy ran"
    assert not [text for text in logged if TOKEN_HASH in text]
