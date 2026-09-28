"""Story 1.7: the `supplierlinks` Table adapter (AD-6). Fakes stand in for Azure: a fake
client for the mapping, and the real SDK pipeline over a fake transport for what the
SDK itself logs and traces. Nothing goes over the network."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Iterator, Mapping
from datetime import UTC, datetime
from typing import Any, Self
from uuid import UUID

import pytest
from azure.core.credentials import AzureNamedKeyCredential
from azure.core.exceptions import (
    ClientAuthenticationError,
    HttpResponseError,
    ResourceNotFoundError,
    ServiceRequestError,
)
from azure.core.pipeline.transport import AsyncHttpResponse, AsyncHttpTransport
from azure.core.settings import settings as azure_settings
from azure.data.tables.aio import TableClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from invoicing.adapters import table_links
from invoicing.adapters.logging import event_fields
from invoicing.adapters.table_links import TableSupplierLinkRegistry
from invoicing.domain.errors import ErrorCode, ServiceUnavailableError
from invoicing.ports.links import SupplierLink, SupplierLinkRegistry, partition_key

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
    """A `TableClient` stand-in: records queries, returns `entities` or raises `error`."""

    def __init__(
        self,
        entities: list[Mapping[str, Any]] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.entities = entities or []
        self.error = error
        self.queries: list[tuple[str, dict[str, Any]]] = []
        self.closed = False

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


def test_story_1_7_partition_key_is_the_first_two_hex_characters() -> None:
    assert partition_key(TOKEN_HASH) == "3f"


def test_story_1_7_a_revoked_link_resolves_as_revoked() -> None:
    revoked = {**ENTITY, "revoked_at": datetime(2026, 9, 20, tzinfo=UTC)}
    link = _resolve(FakeTable([revoked]))
    assert link is not None and not link.is_active


@pytest.mark.parametrize("empty", [None, ""])
def test_story_1_7_an_empty_revoked_at_means_active(empty: object) -> None:
    link = _resolve(FakeTable([{**ENTITY, "revoked_at": empty, "issued_at": None}]))
    assert link is not None and link.is_active and link.issued_at is None


def test_story_1_7_an_unknown_hash_resolves_to_none() -> None:
    assert _resolve(FakeTable([])) is None


def _codes(caplog: pytest.LogCaptureFixture, event: str) -> list[object]:
    return [
        event_fields(r).get("code")
        for r in caplog.records
        if r.getMessage().startswith(event + " ")
    ]


@pytest.mark.parametrize(
    ("error", "code", "level"),
    [
        (ServiceRequestError("connection reset"), "TRANSIENT", logging.WARNING),
        (
            HttpResponseError(message=f"503 for supplierlinks RowKey='{TOKEN_HASH}'"),
            "TRANSIENT",
            logging.WARNING,
        ),
        (ClientAuthenticationError("no role"), "AUTH_FAILED", logging.ERROR),
        (ResourceNotFoundError("TableNotFound"), "TABLE_NOT_FOUND", logging.ERROR),
    ],
)
def test_story_1_7_a_table_failure_is_service_unavailable_with_a_distinct_code(
    error: Exception, code: str, level: int, caplog: pytest.LogCaptureFixture
) -> None:
    with (
        caplog.at_level(logging.DEBUG, logger="invoicing"),
        pytest.raises(ServiceUnavailableError) as raised,
    ):
        _resolve(FakeTable(error=error))
    assert raised.value.code is ErrorCode.SERVICE_UNAVAILABLE
    assert raised.value.__cause__ is None and raised.value.__suppress_context__
    assert TOKEN_HASH not in str(raised.value)
    assert _codes(caplog, "supplierlinks.unavailable") == [code]
    assert [r.levelno for r in caplog.records if r.name.startswith("invoicing")] == [
        level
    ]
    assert not [r for r in caplog.records if TOKEN_HASH in str(vars(r))]


@pytest.mark.parametrize(
    ("broken", "code"),
    [
        ({"supplier_name": ""}, "MISSING_SUPPLIER_NAME"),
        ({"supplier_name": "   "}, "MISSING_SUPPLIER_NAME"),
        ({"supplier_name": None}, "MISSING_SUPPLIER_NAME"),
        ({"supplier_id": None}, "MISSING_SUPPLIER_ID"),
        ({"supplier_id": ""}, "MISSING_SUPPLIER_ID"),
        ({"supplier_id": "not-a-uuid"}, "BAD_SUPPLIER_ID"),
        ({"revoked_at": "20th September"}, "BAD_DATE"),
        ({"issued_at": 1727740800}, "BAD_DATE"),
    ],
)
def test_story_1_7_a_corrupt_row_is_logged_by_code_and_answers_503(
    broken: dict[str, Any], code: str, caplog: pytest.LogCaptureFixture
) -> None:
    with (
        caplog.at_level(logging.DEBUG, logger="invoicing"),
        pytest.raises(ServiceUnavailableError) as raised,
    ):
        _resolve(FakeTable([{**ENTITY, **broken}]))
    assert raised.value.__cause__ is None
    assert _codes(caplog, "supplierlinks.corrupt_row") == [code]
    assert not [r for r in caplog.records if TOKEN_HASH in str(vars(r))]


def test_story_1_7_iso_8601_date_strings_are_read_as_utc_datetimes() -> None:
    link = _resolve(
        FakeTable(
            [
                {
                    **ENTITY,
                    "issued_at": "2026-09-01T00:00:00Z",
                    "revoked_at": "2026-09-20T08:30:00",
                }
            ]
        )
    )
    assert link is not None
    assert link.issued_at == datetime(2026, 9, 1, tzinfo=UTC)
    assert link.revoked_at == datetime(2026, 9, 20, 8, 30, tzinfo=UTC)
    assert not link.is_active


def test_story_1_7_the_supplier_name_is_trimmed() -> None:
    link = _resolve(FakeTable([{**ENTITY, "supplier_name": "  Lim Leather Trading "}]))
    assert link is not None and link.supplier_name == "Lim Leather Trading"


def test_story_1_7_close_releases_the_client_and_the_credential() -> None:
    class FakeCredential:
        closed = False

        async def close(self) -> None:
            self.closed = True

    table, credential = FakeTable(), FakeCredential()
    asyncio.run(TableSupplierLinkRegistry(table, credential).close())
    assert table.closed and credential.closed


def test_story_1_7_managed_identity_registry_targets_the_accounts_table_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_ids: list[str] = []

    class FakeManagedIdentity:
        def __init__(self, *, client_id: str) -> None:
            client_ids.append(client_id)

        async def get_token(self, *scopes: str, **kwargs: Any) -> Any:
            raise AssertionError("no token is requested in this test")

        async def close(self) -> None:
            return None

    monkeypatch.setattr(table_links, "ManagedIdentityCredential", FakeManagedIdentity)

    async def build() -> None:
        registry = TableSupplierLinkRegistry.with_managed_identity(
            "babaloosealngst01", "00000000-0000-0000-0000-00000000c1d0"
        )
        table = registry._table
        assert isinstance(table, TableClient)
        assert table.table_name == "supplierlinks"
        assert table.url.startswith("https://babaloosealngst01.table.core.windows.net")
        await registry.close()

    asyncio.run(build())
    assert client_ids == ["00000000-0000-0000-0000-00000000c1d0"]


# --- The real SDK pipeline: what it logs and traces never holds the hash (AD-14) ------


class _Response(AsyncHttpResponse):
    def __init__(self, request: Any, status: int, body: bytes) -> None:
        super().__init__(request, None)
        self.status_code = status
        self.reason = "OK" if status == 200 else "Service Unavailable"
        self.headers = {"Content-Type": "application/json;odata=minimalmetadata"}
        self.content_type = self.headers["Content-Type"]
        self._body = body

    def body(self) -> bytes:
        return self._body

    async def load_body(self) -> None:
        return None

    def stream_download(self, pipeline: Any, **kwargs: Any) -> Any:
        raise NotImplementedError


class _Transport(AsyncHttpTransport):
    def __init__(self, status: int, body: bytes) -> None:
        self.status, self.body = status, body
        self.urls: list[str] = []

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def send(self, request: Any, **kwargs: Any) -> _Response:
        self.urls.append(request.url)
        return _Response(request, self.status, self.body)


@pytest.fixture
def sdk_tracing() -> Iterator[None]:
    """The Azure SDK's OpenTelemetry spans on, as the Azure Monitor distro turns them on."""
    previous = azure_settings.tracing_implementation()
    azure_settings.tracing_implementation = "opentelemetry"
    yield
    azure_settings.tracing_implementation = previous


@pytest.mark.parametrize("status", [200, 503])
def test_story_1_7_the_sdks_own_logs_and_spans_never_hold_the_hash(
    status: int,
    sdk_tracing: None,
    spans: InMemorySpanExporter,
    caplog: pytest.LogCaptureFixture,
) -> None:
    entity = {
        **ENTITY,
        "issued_at@odata.type": "Edm.DateTime",
        "issued_at": "2026-09-01T00:00:00Z",
    }
    body = json.dumps({"value": [entity]} if status == 200 else {}).encode()
    transport = _Transport(status, body)
    table = TableClient(
        endpoint="https://babaloosealngst01.table.core.windows.net",
        table_name="supplierlinks",
        credential=AzureNamedKeyCredential("babaloosealngst01", "a2V5"),
        transport=transport,
        retry_total=0,
    )

    async def resolve() -> SupplierLink | None:
        async with table:
            return await TableSupplierLinkRegistry(table).resolve(TOKEN_HASH)

    with caplog.at_level(logging.DEBUG, logger="azure"):
        if status == 200:
            link = asyncio.run(resolve())
            assert link is not None and link.supplier_name == "Lim Leather Trading"
        else:
            with pytest.raises(ServiceUnavailableError):
                asyncio.run(resolve())

    # The hash did go to the service, inside $filter ...
    assert any(TOKEN_HASH in url and "$filter=" in url for url in transport.urls)
    # ... and nothing recorded about the call carries it.
    logged = [record.getMessage() for record in caplog.records]
    assert logged, "the SDK's HTTP logging policy ran"
    assert not [text for text in logged if TOKEN_HASH in text]
    finished = spans.get_finished_spans()
    assert finished, "the SDK's tracing policy ran"
    for span in finished:
        for value in (span.attributes or {}).values():
            assert TOKEN_HASH not in str(value)
        for event in span.events:
            assert TOKEN_HASH not in str(event.attributes)
