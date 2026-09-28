"""Story 1.8: the `uploadkeys` Table adapter (AD-6): insert-if-absent, the concurrent
loser reading the winner, error mapping, and no key in logs or spans."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Iterator, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from _sdk_transport import FakeTransport
from azure.core.credentials import AzureNamedKeyCredential
from azure.core.exceptions import (
    ClientAuthenticationError,
    HttpResponseError,
    ResourceExistsError,
    ResourceNotFoundError,
    ServiceRequestError,
)
from azure.core.settings import settings as azure_settings
from azure.data.tables.aio import TableClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from invoicing.adapters import table_upload_keys
from invoicing.adapters.logging import event_fields
from invoicing.adapters.table_upload_keys import TableUploadKeyStore
from invoicing.domain.errors import ServiceUnavailableError
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
        self,
        rows: dict[tuple[str, str], Mapping[str, Any]] | None = None,
        create_error: Exception | None = None,
        query_error: Exception | None = None,
        vanish: bool = False,
        refuse_first: bool = False,
    ) -> None:
        self.rows = dict(rows or {})
        self.create_error = create_error
        self.query_error = query_error
        # The row is there for the insert, then gone for the read (the sweeper).
        self.vanish = vanish
        # The first insert is refused and the row is already gone (swept) by the read.
        self.refuse_first = refuse_first
        self.inserts = 0
        self.created: list[Mapping[str, Any]] = []
        self.queries: list[tuple[str, dict[str, Any]]] = []
        self.closed = False

    async def create_entity(self, entity: Mapping[str, Any], **kwargs: Any) -> Any:
        self.inserts += 1
        if self.create_error is not None:
            raise self.create_error
        pk_rk = (entity["PartitionKey"], entity["RowKey"])
        if (
            pk_rk in self.rows
            or self.vanish
            or (self.refuse_first and self.inserts == 1)
        ):
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
        if self.query_error is not None:
            raise self.query_error
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


def test_story_1_8_a_refused_insert_with_no_row_to_read_is_retried_once() -> None:
    table = FakeTable(refuse_first=True)
    assert _claim(table) == (MINE, True)
    assert table.inserts == 2 and len(table.queries) == 1


def test_story_1_8_a_row_swept_between_insert_and_read_is_retried_then_503(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with (
        caplog.at_level(logging.DEBUG, logger="invoicing"),
        pytest.raises(ServiceUnavailableError),
    ):
        _claim(table := FakeTable(vanish=True))
    assert table.inserts == 2 and len(table.queries) == 2
    assert [
        event_fields(r).get("code")
        for r in caplog.records
        if r.getMessage().startswith("uploadkeys.unavailable ")
    ] == ["VANISHED"]


@pytest.mark.parametrize("stage", ["create", "query"])
@pytest.mark.parametrize(
    ("error", "code"),
    [
        (ServiceRequestError("connection reset"), "TRANSIENT"),
        (HttpResponseError(message=f"503 for RowKey='{KEY}'"), "TRANSIENT"),
        (ClientAuthenticationError("no role"), "AUTH_FAILED"),
        (ResourceNotFoundError("TableNotFound"), "RESOURCE_NOT_FOUND"),
    ],
)
def test_story_1_8_a_table_failure_is_a_503_logged_by_code_without_the_key(
    stage: str, error: Exception, code: str, caplog: pytest.LogCaptureFixture
) -> None:
    table = (
        FakeTable(create_error=error)
        if stage == "create"
        else FakeTable({("3f", str(KEY)): _row(THEIRS)}, query_error=error)
    )
    with (
        caplog.at_level(logging.DEBUG, logger="invoicing"),
        pytest.raises(ServiceUnavailableError) as raised,
    ):
        _claim(table)
    assert raised.value.__cause__ is None and raised.value.__suppress_context__
    assert str(KEY) not in str(raised.value)
    assert [
        event_fields(r).get("code")
        for r in caplog.records
        if r.getMessage().startswith("uploadkeys.unavailable ")
    ] == [code]
    assert not [r for r in caplog.records if str(KEY) in str(vars(r))]


@pytest.mark.parametrize(
    ("broken", "code"),
    [
        ({"invoice_id": None}, "MISSING_INVOICE_ID"),
        ({"invoice_id": "nope"}, "BAD_INVOICE_ID"),
        ({"invoice_id": "12345678-1234-4234-8234-123456789abc"}, "BAD_INVOICE_ID"),
        ({"supplier_id": ""}, "MISSING_SUPPLIER_ID"),
        ({"correlation_id": "x"}, "BAD_CORRELATION_ID"),
        ({"created_at": None}, "BAD_CREATED_AT"),
        ({"created_at": "yesterday"}, "BAD_CREATED_AT"),
        ({"content_sha256": None}, "BAD_CONTENT_SHA256"),
        ({"content_sha256": "AB" * 32}, "BAD_CONTENT_SHA256"),
        ({"content_type": "image/gif"}, "BAD_CONTENT_TYPE"),
        ({"content_type": None}, "BAD_CONTENT_TYPE"),
    ],
)
def test_story_1_8_a_corrupt_row_is_logged_by_code_and_answers_503(
    broken: dict[str, Any], code: str, caplog: pytest.LogCaptureFixture
) -> None:
    table = FakeTable({("3f", str(KEY)): {**_row(THEIRS), **broken}})
    with (
        caplog.at_level(logging.DEBUG, logger="invoicing"),
        pytest.raises(ServiceUnavailableError),
    ):
        _claim(table)
    assert [
        event_fields(r).get("code")
        for r in caplog.records
        if r.getMessage().startswith("uploadkeys.corrupt_row ")
    ] == [code]


def test_story_1_9_the_device_check_is_stored_and_read_back() -> None:
    overridden = replace(MINE, device_check=DeviceCheck.OVERRIDDEN)
    table = FakeTable()
    _claim(table, overridden)
    assert table.created[0]["device_check"] == "overridden"
    # The next claim on the key reads the stored value, whatever it offers.
    assert _claim(table, MINE) == (overridden, False)


def test_story_1_9_the_device_check_is_read_through_the_selected_columns() -> None:
    table = FakeTable({("3f", str(KEY)): _row(THEIRS)})
    stored, _ = _claim(table)
    assert stored.device_check is DeviceCheck.OVERRIDDEN
    ((_, kwargs),) = table.queries
    assert "device_check" in kwargs["select"]


@pytest.mark.parametrize("legacy", ["missing", "", None])
def test_story_1_9_a_row_from_before_the_device_check_reads_as_passed(
    legacy: str | None,
) -> None:
    row = {k: v for k, v in _row(THEIRS).items() if k != "device_check"}
    if legacy != "missing":
        row["device_check"] = legacy
    stored, _ = _claim(FakeTable({("3f", str(KEY)): row}))
    assert stored.device_check is DeviceCheck.PASSED


def test_story_1_9_an_unknown_device_check_is_a_corrupt_row(
    caplog: pytest.LogCaptureFixture,
) -> None:
    table = FakeTable({("3f", str(KEY)): {**_row(THEIRS), "device_check": "maybe"}})
    with (
        caplog.at_level(logging.DEBUG, logger="invoicing"),
        pytest.raises(ServiceUnavailableError),
    ):
        _claim(table)
    assert [
        event_fields(r).get("code")
        for r in caplog.records
        if r.getMessage().startswith("uploadkeys.corrupt_row ")
    ] == ["BAD_DEVICE_CHECK"]


def test_story_1_8_an_iso_string_created_at_is_read_as_utc() -> None:
    row = {**_row(THEIRS), "created_at": "2026-09-29T01:30:00"}
    assert _claim(FakeTable({("3f", str(KEY)): row}))[0].created_at == CREATED


def test_story_1_8_close_releases_the_client_and_the_credential() -> None:
    class FakeCredential:
        closed = False

        async def close(self) -> None:
            self.closed = True

    table, credential = FakeTable(), FakeCredential()
    asyncio.run(TableUploadKeyStore(table, credential).close())
    assert table.closed and credential.closed


def test_story_1_8_managed_identity_store_targets_the_uploadkeys_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeManagedIdentity:
        def __init__(self, *, client_id: str) -> None:
            self.client_id = client_id

        async def get_token(self, *scopes: str, **kwargs: Any) -> Any:
            raise AssertionError("no token is requested in this test")

        async def close(self) -> None:
            return None

    monkeypatch.setattr(
        table_upload_keys, "ManagedIdentityCredential", FakeManagedIdentity
    )

    async def build() -> None:
        store = TableUploadKeyStore.with_managed_identity(
            "babaloosealngst01", "00000000-0000-0000-0000-00000000c1d0"
        )
        table = store._table
        assert isinstance(table, TableClient)
        assert table.table_name == "uploadkeys"
        assert table.url.startswith("https://babaloosealngst01.table.core.windows.net")
        await store.close()

    asyncio.run(build())


# --- The real SDK pipeline: what it logs and traces never holds the key ---------------


@pytest.fixture
def sdk_tracing() -> Iterator[None]:
    previous = azure_settings.tracing_implementation()
    azure_settings.tracing_implementation = "opentelemetry"
    yield
    azure_settings.tracing_implementation = previous


def test_story_1_8_the_sdks_own_logs_and_spans_never_hold_the_key(
    sdk_tracing: None,
    spans: InMemorySpanExporter,
    caplog: pytest.LogCaptureFixture,
) -> None:
    json_headers = {"Content-Type": "application/json;odata=minimalmetadata"}
    stored = {
        **_row(THEIRS),
        "created_at@odata.type": "Edm.DateTime",
        "created_at": "2026-09-29T01:30:00Z",
    }
    conflict = json.dumps(
        {"odata.error": {"code": "EntityAlreadyExists", "message": {"value": "x"}}}
    ).encode()
    transport = FakeTransport(
        [
            (409, conflict, {**json_headers, "x-ms-error-code": "EntityAlreadyExists"}),
            (200, json.dumps({"value": [stored]}).encode(), json_headers),
        ]
    )
    table = TableClient(
        endpoint="https://babaloosealngst01.table.core.windows.net",
        table_name="uploadkeys",
        credential=AzureNamedKeyCredential("babaloosealngst01", "a2V5"),
        transport=transport,
        retry_total=0,
    )

    async def claim() -> tuple[UploadKey, bool]:
        async with table:
            return await TableUploadKeyStore(table).claim(KEY, MINE)

    with caplog.at_level(logging.DEBUG, logger="azure"):
        assert asyncio.run(claim()) == (THEIRS, False)

    insert, read = transport.requests
    # The insert carries the key in its body only; the read in $filter only.
    assert insert.method == "POST" and str(KEY) not in insert.url
    assert str(KEY) in json.loads(insert.body)["RowKey"]
    assert str(KEY) in read.url and "$filter=" in read.url
    logged = [record.getMessage() for record in caplog.records]
    assert logged, "the SDK's HTTP logging policy ran"
    assert not [text for text in logged if str(KEY) in text]
    finished = spans.get_finished_spans()
    assert finished, "the SDK's tracing policy ran"
    for span in finished:
        for value in (span.attributes or {}).values():
            assert str(KEY) not in str(value)
        for event in span.events:
            assert str(KEY) not in str(event.attributes)
