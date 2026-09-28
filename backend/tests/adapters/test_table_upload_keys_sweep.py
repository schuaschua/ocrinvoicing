"""Story 2.2: the sweeper's side of the `uploadkeys` adapter (AD-6): list keys older
than a cutoff (capped, with their ETags), mark an orphan recovered and delete a key,
each conditional on the listed ETag, never putting a key in a URL or a log."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from _sdk_transport import FakeTransport
from azure.core import MatchConditions
from azure.core.credentials import AzureNamedKeyCredential
from azure.core.exceptions import (
    HttpResponseError,
    ResourceNotFoundError,
    ServiceRequestError,
)
from azure.core.pipeline.transport._base_async import (
    AsyncHttpClientTransportResponse,
)
from azure.data.tables import TableEntity, UpdateMode
from azure.data.tables.aio import TableClient

from invoicing.adapters.logging import event_fields
from invoicing.adapters.table_upload_keys import TableUploadKeyStore
from invoicing.domain.errors import ServiceUnavailableError
from invoicing.domain.upload import DeviceCheck, UploadContentType
from invoicing.ports.upload_keys import AgedUploadKey, AgedUploadKeys, UploadKey

KEY = UUID("3fa85f64-5717-4562-b3fc-2c963f66afa6")
OTHER = UUID("3fa85f64-5717-4562-b3fc-000000000002")
CUTOFF = datetime(2026, 9, 29, 1, 0, tzinfo=UTC)
AT = datetime(2026, 9, 29, 2, 0, tzinfo=UTC)
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


def _entity(
    key: UUID | str,
    *,
    etag: str | None = ETAG,
    recovered_at: datetime | None = None,
    **changes: Any,
) -> TableEntity:
    """A listed row as the SDK returns it: a TableEntity with its ETag in metadata."""
    entity = TableEntity(
        {
            "PartitionKey": str(key)[:2],
            "RowKey": str(key),
            "invoice_id": str(ENTRY.invoice_id),
            "supplier_id": str(ENTRY.supplier_id),
            "correlation_id": str(ENTRY.correlation_id),
            "created_at": ENTRY.created_at,
            "content_sha256": ENTRY.content_sha256,
            "content_type": ENTRY.content_type.value,
            "device_check": ENTRY.device_check.value,
            **({} if recovered_at is None else {"recovered_at": recovered_at}),
            **changes,
        }
    )
    entity._metadata = {"etag": etag, "timestamp": None}
    return entity


class FakeTable:
    def __init__(
        self,
        rows: list[Mapping[str, Any]] | None = None,
        query_error: Exception | None = None,
        batch_error: Exception | None = None,
        batch_result: list[Mapping[str, Any]] | None = None,
    ) -> None:
        self.rows = rows or []
        self.query_error = query_error
        self.batch_error = batch_error
        self.batch_result = (
            [{"etag": NEW_ETAG}] if batch_result is None else batch_result
        )
        self.queries: list[tuple[str, dict[str, Any]]] = []
        self.transactions: list[list[Any]] = []
        self.yielded = 0

    def query_entities(
        self, query_filter: str, **kwargs: Any
    ) -> AsyncIterator[Mapping[str, Any]]:
        self.queries.append((query_filter, kwargs))
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[Mapping[str, Any]]:
        for row in self.rows:
            self.yielded += 1
            yield row
        if self.query_error is not None:
            raise self.query_error

    async def submit_transaction(self, operations: Any, **kwargs: Any) -> Any:
        self.transactions.append(list(operations))
        if self.batch_error is not None:
            raise self.batch_error
        return self.batch_result

    async def create_entity(self, entity: Mapping[str, Any], **kwargs: Any) -> Any:
        raise NotImplementedError

    async def close(self) -> None:
        return None


def _store(table: FakeTable) -> AgedUploadKeys:
    return TableUploadKeyStore(table)  # type: ignore[arg-type]  # a structural fake


def _batch_error(code: str, status: int) -> HttpResponseError:
    error = HttpResponseError(code)
    error.status_code = status
    error.error_code = code  # type: ignore[attr-defined]  # set by the SDK
    return error


# --- Listing ------------------------------------------------------------------------------


def test_story_2_2_older_than_lists_keys_with_their_etag_and_recovery() -> None:
    table = FakeTable([_entity(KEY), _entity(OTHER, recovered_at=AT)])
    aged = asyncio.run(_store(table).older_than(CUTOFF, 500))
    assert aged == [ITEM, AgedUploadKey(OTHER, ENTRY, ETAG, AT)]
    ((query, kwargs),) = table.queries
    assert query == "created_at lt @cutoff"
    assert kwargs["parameters"] == {"cutoff": CUTOFF}
    assert {"PartitionKey", "RowKey", "recovered_at", "created_at"} <= set(
        kwargs["select"]
    )


def test_story_2_2_older_than_stops_at_its_limit() -> None:
    table = FakeTable([_entity(UUID(int=n)) for n in range(1, 10)])
    aged = asyncio.run(_store(table).older_than(CUTOFF, 3))
    assert [a.key for a in aged] == [UUID(int=1), UUID(int=2), UUID(int=3)]
    # The listing is not read past the limit.
    assert table.yielded == 3
    assert table.queries[0][1]["results_per_page"] == 3


def test_story_2_2_a_row_that_cant_be_read_is_skipped_by_code(
    caplog: pytest.LogCaptureFixture,
) -> None:
    table = FakeTable(
        [
            _entity("not-a-key"),
            _entity(OTHER, invoice_id="not-a-uuid"),
            _entity(OTHER, etag=None),
            _entity(KEY),
        ]
    )
    with caplog.at_level(logging.DEBUG, logger="invoicing"):
        aged = asyncio.run(_store(table).older_than(CUTOFF, 500))
    assert aged == [ITEM]
    codes = [
        event_fields(r)["code"]
        for r in caplog.records
        if r.getMessage().startswith("uploadkeys.corrupt_row")
    ]
    assert codes == ["BAD_ROW_KEY", "BAD_INVOICE_ID", "MISSING_ETAG"]
    for record in caplog.records:
        assert str(OTHER) not in record.getMessage()


@pytest.mark.parametrize(
    "error",
    [ServiceRequestError("reset"), HttpResponseError("boom")],
)
def test_story_2_2_a_listing_that_fails_is_a_503(error: Exception) -> None:
    table = FakeTable([_entity(KEY)], query_error=error)
    with pytest.raises(ServiceUnavailableError):
        asyncio.run(_store(table).older_than(CUTOFF, 500))


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


def test_story_2_2_mark_recovered_merges_one_property_on_the_listed_etag() -> None:
    table = FakeTable()
    marked = asyncio.run(_store(table).mark_recovered(ITEM, AT))
    assert marked == AgedUploadKey(KEY, ENTRY, NEW_ETAG, AT)
    assert table.transactions == [
        [
            (
                "update",
                {"PartitionKey": "3f", "RowKey": str(KEY), "recovered_at": AT},
                {
                    "mode": UpdateMode.MERGE,
                    "etag": ETAG,
                    "match_condition": MatchConditions.IfNotModified,
                },
            )
        ]
    ]


def test_story_2_2_a_row_changed_since_listing_is_left_alone() -> None:
    changed = _batch_error("UpdateConditionNotSatisfied", 412)
    assert asyncio.run(_store(FakeTable(batch_error=changed)).delete(ITEM)) is False
    assert (
        asyncio.run(_store(FakeTable(batch_error=changed)).mark_recovered(ITEM, AT))
        is None
    )


def test_story_2_2_a_row_already_gone_is_deleted_but_not_marked() -> None:
    gone = _batch_error("ResourceNotFound", 404)
    assert asyncio.run(_store(FakeTable(batch_error=gone)).delete(ITEM)) is True
    assert (
        asyncio.run(_store(FakeTable(batch_error=gone)).mark_recovered(ITEM, AT))
        is None
    )


def test_story_2_2_a_mark_with_no_new_etag_is_a_503() -> None:
    with pytest.raises(ServiceUnavailableError):
        asyncio.run(_store(FakeTable(batch_result=[{}])).mark_recovered(ITEM, AT))


def _not_found(code: str) -> ResourceNotFoundError:
    error = ResourceNotFoundError(code)
    error.status_code = 404
    error.error_code = code  # type: ignore[attr-defined]  # set by the SDK
    return error


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (_not_found("TableNotFound"), "RESOURCE_NOT_FOUND"),
        (ServiceRequestError("reset"), "TRANSIENT"),
    ],
)
def test_story_2_2_a_failed_write_is_a_503_logged_by_code(
    error: Exception, code: str, caplog: pytest.LogCaptureFixture
) -> None:
    with (
        caplog.at_level(logging.DEBUG, logger="invoicing"),
        pytest.raises(ServiceUnavailableError),
    ):
        asyncio.run(_store(FakeTable(batch_error=error)).delete(ITEM))
    (record,) = [
        r for r in caplog.records if r.getMessage().startswith("uploadkeys.unavailable")
    ]
    assert event_fields(record)["code"] == code


# --- On the wire, through the real SDK pipeline -------------------------------------------


def _sdk_table(transport: FakeTransport) -> TableClient:
    return TableClient(
        endpoint="https://babaloosealngst01.table.core.windows.net",
        table_name="uploadkeys",
        credential=AzureNamedKeyCredential("babaloosealngst01", "a2V5"),
        transport=transport,
        retry_total=0,
    )


@pytest.fixture
def batch_parts(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fake transport's responses are the legacy kind, whose batch parts lack the
    `read()` the SDK awaits (the aiohttp transport's parts have it). Give them one, so
    the SDK parses a real multipart batch response."""

    async def read(self: AsyncHttpClientTransportResponse) -> bytes:
        return self.body()

    monkeypatch.setattr(AsyncHttpClientTransportResponse, "read", read, raising=False)


def _batch_response(status_line: str, headers: str, body: str = "") -> bytes:
    return (
        "--batchresponse_1\r\n"
        "Content-Type: multipart/mixed; boundary=changesetresponse_2\r\n\r\n"
        "--changesetresponse_2\r\n"
        "Content-Type: application/http\r\nContent-Transfer-Encoding: binary\r\n\r\n"
        f"HTTP/1.1 {status_line}\r\n{headers}\r\n{body}\r\n"
        "--changesetresponse_2--\r\n--batchresponse_1--\r\n"
    ).encode()


BATCH_HEADERS = {"Content-Type": "multipart/mixed; boundary=batchresponse_1"}
ERROR_HEADERS = (
    "DataServiceVersion: 3.0;\r\n"
    "Content-Type: application/json;odata=minimalmetadata;streaming=true;charset=utf-8\r\n"
)


def _odata_error(code: str) -> str:
    return json.dumps(
        {"odata.error": {"code": code, "message": {"lang": "en-US", "value": "0:x"}}}
    )


def test_story_2_2_the_wire_listing_reads_etags_and_filters_on_created_at() -> None:
    json_headers = {"Content-Type": "application/json;odata=minimalmetadata"}
    row = {
        **{k: v for k, v in _entity(KEY).items() if k != "created_at"},
        "odata.etag": ETAG,
        "created_at": "2026-09-28T01:30:00Z",
        "created_at@odata.type": "Edm.DateTime",
    }
    transport = FakeTransport(
        [(200, json.dumps({"value": [row]}).encode(), json_headers)]
    )
    table = _sdk_table(transport)

    async def listing() -> list[AgedUploadKey]:
        async with table:
            return await TableUploadKeyStore(table).older_than(CUTOFF, 500)

    (aged,) = asyncio.run(listing())
    assert (aged.key, aged.etag, aged.value.created_at) == (KEY, ETAG, ENTRY.created_at)
    (request,) = transport.requests
    assert "$filter=created_at%20lt%20datetime%272026-09-29T01%3A00%3A00" in request.url


def test_story_2_2_the_wire_delete_of_a_key_already_gone_returns_normally(
    batch_parts: None,
) -> None:
    # The service's real answer: 202 for the batch, 404 ResourceNotFound inside it.
    transport = FakeTransport(
        [
            (
                202,
                _batch_response(
                    "404 Not Found", ERROR_HEADERS, _odata_error("ResourceNotFound")
                ),
                BATCH_HEADERS,
            )
        ]
    )
    table = _sdk_table(transport)

    async def delete() -> bool:
        async with table:
            return await TableUploadKeyStore(table).delete(ITEM)

    assert asyncio.run(delete()) is True
    (request,) = transport.requests
    assert request.method == "POST" and request.url.endswith("/$batch")
    assert str(KEY) not in request.url
    body = (
        request.body.decode() if isinstance(request.body, bytes) else str(request.body)
    )
    assert f"RowKey='{KEY}'" in body and "DELETE " in body
    assert f"If-Match: {ETAG}" in body


def test_story_2_2_the_wire_mark_of_a_changed_row_returns_none(
    batch_parts: None,
) -> None:
    transport = FakeTransport(
        [
            (
                202,
                _batch_response(
                    "412 Precondition Failed",
                    ERROR_HEADERS,
                    _odata_error("UpdateConditionNotSatisfied"),
                ),
                BATCH_HEADERS,
            ),
            (
                202,
                _batch_response(
                    "204 No Content",
                    f"ETag: {NEW_ETAG}\r\nDataServiceVersion: 1.0;\r\n",
                ),
                BATCH_HEADERS,
            ),
        ]
    )
    table = _sdk_table(transport)

    async def mark_twice() -> tuple[AgedUploadKey | None, AgedUploadKey | None]:
        async with table:
            store = TableUploadKeyStore(table)
            return await store.mark_recovered(ITEM, AT), await store.mark_recovered(
                ITEM, AT
            )

    changed, marked = asyncio.run(mark_twice())
    assert changed is None
    assert marked == AgedUploadKey(KEY, ENTRY, NEW_ETAG, AT)
    body = transport.requests[1].body
    text = body.decode() if isinstance(body, bytes) else str(body)
    assert "PATCH " in text and f"If-Match: {ETAG}" in text and '"recovered_at"' in text
    assert str(KEY) not in transport.requests[1].url
