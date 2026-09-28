"""Story 1.8: `POST /api/upload` on supplier-api, every row of the I/O matrix. Fakes
stand in for `supplierlinks`, `uploadkeys`, `images` and `q-quality` (coding-style.md
rule 23); nothing reaches Azure."""

import asyncio
import base64
import hashlib
import json
import logging
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import ModuleType
from typing import Any
from uuid import UUID

import azure.functions as func
import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from invoicing.adapters.blob_images import BlobImageStore
from invoicing.adapters.http import CORRELATION_HEADER, SECURITY_HEADERS
from invoicing.adapters.logging import event_fields
from invoicing.adapters.queue import StorageQueueSender
from invoicing.adapters.table_links import TableSupplierLinkRegistry
from invoicing.adapters.table_upload_keys import TableUploadKeyStore
from invoicing.apps.supplier_api import upload as upload_module
from invoicing.domain.errors import ServiceUnavailableError
from invoicing.domain.links import token_hash
from invoicing.domain.reference import supplier_reference
from invoicing.ports.intake import IntakeBlobMetadata
from invoicing.ports.links import SupplierLink
from invoicing.ports.messages import QueueMessage
from invoicing.ports.queue import QueueName
from invoicing.ports.upload_keys import UploadKey

# Synthetic tokens, never real links.
TOKEN_A = base64.urlsafe_b64encode(b"\x11" * 32).rstrip(b"=").decode()
TOKEN_B = base64.urlsafe_b64encode(b"\x44" * 32).rstrip(b"=").decode()
REVOKED = base64.urlsafe_b64encode(b"\x22" * 32).rstrip(b"=").decode()
UNKNOWN = base64.urlsafe_b64encode(b"\x33" * 32).rstrip(b"=").decode()
SUPPLIER_A = UUID("0192f0c1-7a2b-7c3d-8e4f-0123456789ab")
SUPPLIER_B = UUID("0192f0c1-7a2b-7c3d-8e4f-0000000000bb")
KEY = "3fa85f64-5717-4562-b3fc-2c963f66afa6"
NOW = datetime(2026, 9, 29, 1, 30, tzinfo=UTC)
MB = 1024 * 1024
JPEG = b"\xff\xd8\xff\xe1\x00\x18Exif\x00\x00" + b"\x5a" * (MB - 12)
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
PDF = b"%PDF-1.7\n" + b"\x00" * 100
LINK_NOT_WORKING = "This link isn't working. Please contact your buyer at Babaloo."
POSTGRES_DRIVERS = ("psycopg", "psycopg2", "psycopg_pool", "asyncpg", "sqlalchemy")


class FakeRegistry:
    def __init__(self) -> None:
        issued = datetime(2026, 9, 1, tzinfo=UTC)
        self.links = {
            token_hash(TOKEN_A): SupplierLink(SUPPLIER_A, "Lim Leather", issued, None),
            token_hash(TOKEN_B): SupplierLink(
                SUPPLIER_B, "Kowloon Soles", issued, None
            ),
            token_hash(REVOKED): SupplierLink(SUPPLIER_A, "Lim Leather", issued, NOW),
        }

    async def resolve(self, token_hash: str) -> SupplierLink | None:
        return self.links.get(token_hash)


@dataclass
class Storage:
    """`uploadkeys`, `images` and `q-quality` in memory, with one shared log of
    writes in the order they happened, and failures to inject per step."""

    keys: dict[UUID, UploadKey] = field(default_factory=dict)
    blobs: dict[UUID, tuple[bytes, IntakeBlobMetadata]] = field(default_factory=dict)
    messages: list[tuple[QueueName, QueueMessage]] = field(default_factory=list)
    writes: list[str] = field(default_factory=list)
    fail: set[str] = field(default_factory=set)
    # Let concurrent requests interleave at the key insert.
    yield_on_claim: bool = False

    async def claim(self, key: UUID, candidate: UploadKey) -> tuple[UploadKey, bool]:
        if "key" in self.fail:
            raise ServiceUnavailableError()
        if self.yield_on_claim:
            await asyncio.sleep(0)
        if key in self.keys:
            return self.keys[key], False
        self.keys[key] = candidate
        self.writes.append("key")
        return candidate, True

    async def put_if_absent(self, data: bytes, metadata: IntakeBlobMetadata) -> bool:
        if "blob" in self.fail:
            raise ServiceUnavailableError()
        if metadata.invoice_id in self.blobs:
            return False
        self.blobs[metadata.invoice_id] = (data, metadata)
        self.writes.append("blob")
        return True

    async def send(
        self, queue: QueueName, message: QueueMessage, *, delay_seconds: int = 0
    ) -> None:
        if "queue" in self.fail:
            raise ServiceUnavailableError()
        self.messages.append((queue, message))
        self.writes.append("queue")


type Call = Callable[..., func.HttpResponse]


@pytest.fixture
def storage() -> Storage:
    return Storage()


class Clock:
    """The upload handler's clock, fixed and movable (a retry comes later)."""

    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    fixed = Clock()
    monkeypatch.setattr(upload_module, "_now", fixed)
    return fixed


@pytest.fixture
def module(
    clock: Clock,
    app_settings: dict[str, str],
    load_app: Callable[[str], ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    storage: Storage,
) -> ModuleType:
    """supplier-api as the host loads it, with fakes behind every storage adapter."""
    built: list[tuple[str, str, str]] = []

    def factory(name: str, fake: object) -> Any:
        def build(cls: object, account: str, client_id: str) -> object:
            built.append((name, account, client_id))
            return fake

        return classmethod(build)

    registry = FakeRegistry()
    monkeypatch.setattr(
        TableSupplierLinkRegistry, "with_managed_identity", factory("links", registry)
    )
    for name, cls in [
        ("keys", TableUploadKeyStore),
        ("images", BlobImageStore),
        ("queue", StorageQueueSender),
    ]:
        monkeypatch.setattr(cls, "with_managed_identity", factory(name, storage))
    loaded = load_app("supplier_api")
    # Each on the environment's storage account, as the app's own identity.
    account, identity = (
        app_settings["STORAGE_ACCOUNT_NAME"],
        app_settings["AZURE_CLIENT_ID"],
    )
    assert sorted(built) == sorted(
        (name, account, identity) for name in ["links", "keys", "images", "queue"]
    )
    return loaded


@pytest.fixture
def call(module: ModuleType) -> Call:
    functions = {fn.get_function_name(): fn for fn in module.app.get_functions()}
    upload = functions["upload"]
    (trigger,) = [
        b.get_dict_repr()
        for b in upload.get_bindings()
        if b.get_dict_repr()["type"] == "httpTrigger"
    ]
    assert trigger["route"] == "api/upload"
    assert [getattr(m, "value", m) for m in trigger["methods"]] == ["POST"]  # type: ignore[attr-defined]  # a list here
    assert getattr(trigger["authLevel"], "value", None) == "anonymous"
    handler = upload.get_user_function()

    def send(
        body: bytes = JPEG,
        *,
        token: str | None = TOKEN_A,
        key: str | None = KEY,
        content_type: str = "image/jpeg",
        headers: dict[str, str] | None = None,
        request: func.HttpRequest | None = None,
    ) -> func.HttpResponse:
        sent = {"Content-Type": content_type, "Content-Length": str(len(body))}
        if token is not None:
            sent["X-Upload-Token"] = token
        if key is not None:
            sent["Idempotency-Key"] = key
        sent.update(headers or {})
        req = request or func.HttpRequest(
            method="POST", url="/api/upload", headers=sent, body=body
        )
        return asyncio.run(handler(req))

    return send


def _body(response: func.HttpResponse) -> dict[str, Any]:
    body = json.loads(response.get_body())
    assert isinstance(body, dict)
    return body


def _ok(response: func.HttpResponse) -> tuple[UUID, str]:
    assert response.status_code == 200, response.get_body()
    body = _body(response)
    assert set(body) == {"invoice_id", "reference"}
    invoice_id = UUID(body["invoice_id"])
    assert invoice_id.version == 7
    assert body["reference"] == supplier_reference(invoice_id)
    for name, value in SECURITY_HEADERS.items():
        assert response.headers[name] == value
    return invoice_id, body["reference"]


def _error(response: func.HttpResponse, status: int, code: str) -> str:
    assert response.status_code == status
    body = _body(response)
    assert body["code"] == code
    assert body["correlation_id"] == response.headers[CORRELATION_HEADER]
    message = body["message"]
    assert isinstance(message, str) and message
    return message


def _nothing_written(storage: Storage) -> None:
    assert storage.writes == [] and not storage.keys
    assert not storage.blobs and not storage.messages


# --- Happy path and replays ----------------------------------------------------------


def test_story_1_8_happy_path_writes_key_then_blob_then_message(
    call: Call, storage: Storage
) -> None:
    response = call(JPEG, content_type="image/jpeg")
    invoice_id, reference = _ok(response)
    assert reference.startswith("R-") and len(reference) == 10
    assert storage.writes == ["key", "blob", "queue"]

    stored = storage.keys[UUID(KEY)]
    assert stored.invoice_id == invoice_id and stored.supplier_id == SUPPLIER_A
    correlation_id = UUID(response.headers[CORRELATION_HEADER])
    assert stored.correlation_id == correlation_id

    data, metadata = storage.blobs[invoice_id]
    assert data == JPEG  # the original bytes, byte for byte
    assert metadata.to_blob_metadata() == {
        "invoice_id": str(invoice_id),
        "source": "link",
        "supplier_id": str(SUPPLIER_A),
        "content_type": "image/jpeg",
        "uploaded_at": "2026-09-29T01:30:00.000000Z",
        "device_check": "passed",
    }
    assert metadata.delivery_id is None
    assert metadata.uploaded_at == stored.created_at == NOW
    assert stored.content_type == "image/jpeg"
    assert stored.content_sha256 == hashlib.sha256(JPEG).hexdigest()

    ((queue, message),) = storage.messages
    assert queue is QueueName.QUALITY
    assert message.invoice_id == invoice_id
    assert message.correlation_id == correlation_id
    assert message.attempt == 1
    assert message.first_enqueued_at == NOW
    # Plain JSON with the four fields only (AD-2).
    assert set(json.loads(message.to_json())) == {
        "invoice_id",
        "correlation_id",
        "first_enqueued_at",
        "attempt",
    }


@pytest.mark.parametrize(
    ("body", "declared", "stored_as"),
    [
        (PNG, "image/png", "image/png"),
        (PDF, "application/pdf", "application/pdf"),
        # The bytes decide, not the label.
        (PDF, "image/jpeg", "application/pdf"),
        (JPEG, "application/octet-stream", "image/jpeg"),
    ],
)
def test_story_1_8_the_stored_type_comes_from_the_bytes(
    body: bytes, declared: str, stored_as: str, call: Call, storage: Storage
) -> None:
    invoice_id, _ = _ok(call(body, content_type=declared))
    assert storage.blobs[invoice_id][1].content_type == stored_as


def test_story_1_8_a_retry_after_success_returns_the_same_invoice_and_enqueues_again(
    call: Call, storage: Storage, clock: Clock
) -> None:
    first = call()
    clock.now = NOW + timedelta(minutes=7)
    again = call()
    assert _ok(first) == _ok(again)
    # One invoice: one key, one blob; the message again (harmless, AD-2).
    assert storage.writes == ["key", "blob", "queue", "queue"]
    first_message, second_message = (m for _, m in storage.messages)
    assert first_message.invoice_id == second_message.invoice_id
    # The replay stays in the first attempt's trace (one correlation id per upload).
    assert second_message.correlation_id == UUID(first.headers[CORRELATION_HEADER])
    # And the first attempt's time, not the retry's.
    assert first_message.first_enqueued_at == NOW
    assert second_message.first_enqueued_at == NOW
    assert storage.blobs[first_message.invoice_id][1].uploaded_at == NOW


def test_story_1_8_crash_after_the_key_is_completed_by_the_retry(
    call: Call, storage: Storage, clock: Clock
) -> None:
    storage.fail = {"blob"}
    _error(call(), 503, "SERVICE_UNAVAILABLE")
    assert storage.writes == ["key"]
    storage.fail = set()
    clock.now = NOW + timedelta(minutes=3)
    invoice_id, _ = _ok(call())
    # The blob written by the retry carries the first attempt's time.
    assert storage.blobs[invoice_id][1].uploaded_at == NOW
    assert storage.messages[0][1].first_enqueued_at == NOW
    assert invoice_id == storage.keys[UUID(KEY)].invoice_id
    assert storage.writes == ["key", "blob", "queue"]


def test_story_1_8_crash_after_the_blob_skips_it_and_enqueues(
    call: Call, storage: Storage
) -> None:
    storage.fail = {"queue"}
    _error(call(), 503, "SERVICE_UNAVAILABLE")
    assert storage.writes == ["key", "blob"]
    storage.fail = set()
    invoice_id, _ = _ok(call())
    assert storage.writes == ["key", "blob", "queue"]
    assert storage.messages[0][1].invoice_id == invoice_id


def test_story_1_8_a_lost_response_is_answered_again_with_the_same_reference(
    call: Call, storage: Storage
) -> None:
    lost = _ok(call())
    assert _ok(call()) == lost
    assert len(storage.blobs) == 1 and len(storage.messages) == 2


def test_story_1_8_concurrent_requests_with_one_key_make_one_invoice(
    module: ModuleType, storage: Storage
) -> None:
    storage.yield_on_claim = True
    handler = next(
        fn for fn in module.app.get_functions() if fn.get_function_name() == "upload"
    ).get_user_function()

    def request() -> func.HttpRequest:
        return func.HttpRequest(
            method="POST",
            url="/api/upload",
            headers={"X-Upload-Token": TOKEN_A, "Idempotency-Key": KEY},
            body=JPEG,
        )

    async def race() -> list[func.HttpResponse]:
        return list(await asyncio.gather(handler(request()), handler(request())))

    first, second = asyncio.run(race())
    assert _ok(first) == _ok(second)
    assert len(storage.keys) == 1 and len(storage.blobs) == 1


# --- Refusals: nothing is written ----------------------------------------------------


def test_story_1_8_a_key_held_by_another_supplier_is_a_409_and_writes_nothing(
    call: Call, storage: Storage
) -> None:
    theirs = _ok(call(token=TOKEN_B))
    before = (dict(storage.keys), dict(storage.blobs), list(storage.messages))
    message = _error(call(token=TOKEN_A), 409, "IDEMPOTENCY_KEY_CONFLICT")
    # Nothing about the other supplier's upload leaks.
    assert theirs[1] not in message and str(theirs[0]) not in message
    assert (dict(storage.keys), dict(storage.blobs), list(storage.messages)) == before


@pytest.mark.parametrize(
    ("body", "content_type"),
    [
        (JPEG[:-1] + b"\x00", "image/jpeg"),  # other bytes, same type
        (PDF, "application/pdf"),  # another type
    ],
)
def test_story_1_8_same_key_same_supplier_different_bytes_is_a_409(
    body: bytes, content_type: str, call: Call, storage: Storage
) -> None:
    first = _ok(call())
    before = (dict(storage.keys), dict(storage.blobs), list(storage.messages))
    message = _error(
        call(body, content_type=content_type), 409, "IDEMPOTENCY_KEY_CONFLICT"
    )
    assert first[1] not in message
    assert (dict(storage.keys), dict(storage.blobs), list(storage.messages)) == before


def test_story_1_8_the_callers_correlation_id_is_ignored(
    call: Call, storage: Storage
) -> None:
    chosen = "0192f0c1-0000-7000-8000-00000000dead"
    response = call(headers={CORRELATION_HEADER: chosen})
    _ok(response)
    assert response.headers[CORRELATION_HEADER] != chosen
    assert str(storage.keys[UUID(KEY)].correlation_id) != chosen
    assert str(storage.messages[0][1].correlation_id) != chosen
    assert UUID(response.headers[CORRELATION_HEADER]).version == 7


@pytest.mark.parametrize(
    "key",
    [
        None,
        "",
        "not-a-uuid",
        "00000000-0000-0000-0000-000000000000",
        KEY + "0",
        "{" + KEY + "}",
    ],
)
def test_story_1_8_a_missing_or_malformed_key_is_a_400(
    key: str | None, call: Call, storage: Storage
) -> None:
    message = _error(call(key=key), 400, "VALIDATION_FAILED")
    assert "key" in message.lower()
    _nothing_written(storage)


def test_story_1_8_the_key_is_accepted_in_any_case(
    call: Call, storage: Storage
) -> None:
    _ok(call(key=KEY.upper()))
    assert list(storage.keys) == [UUID(KEY)]


class UnreadBody(func.HttpRequest):
    """A request whose body must not be read."""

    def get_body(self) -> bytes:
        raise AssertionError("the body was read")


def test_story_1_8_a_declared_length_over_4_mb_is_refused_before_reading(
    call: Call, storage: Storage
) -> None:
    request = UnreadBody(
        method="POST",
        url="/api/upload",
        headers={
            "X-Upload-Token": TOKEN_A,
            "Idempotency-Key": KEY,
            "Content-Length": str(4 * MB + 1),
        },
        body=b"",
    )
    message = _error(call(request=request), 413, "PAYLOAD_TOO_LARGE")
    assert "4 MB" in message
    _nothing_written(storage)


@pytest.mark.parametrize("declared", [None, "10"])
def test_story_1_8_an_actual_length_over_4_mb_is_refused(
    declared: str | None, call: Call, storage: Storage
) -> None:
    body = JPEG + b"\x00" * (3 * MB + 1)
    assert len(body) == 4 * MB + 1
    headers = {"X-Upload-Token": TOKEN_A, "Idempotency-Key": KEY}
    if declared is not None:
        headers["Content-Length"] = declared
    request = func.HttpRequest(
        method="POST", url="/api/upload", headers=headers, body=body
    )
    _error(call(request=request), 413, "PAYLOAD_TOO_LARGE")
    _nothing_written(storage)


def test_story_1_8_exactly_4_mb_is_accepted(call: Call) -> None:
    _ok(call(JPEG + b"\x00" * (3 * MB)))


@pytest.mark.parametrize(
    ("body", "declared"),
    [
        (b"GIF89a" + b"\x00" * 100, "image/gif"),
        (b"\x00\x00\x00\x18ftypheic" + b"\x00" * 100, "image/heic"),
        # A label is not a type: these bytes are neither JPEG, PNG nor PDF.
        (b"GIF89a" + b"\x00" * 100, "image/jpeg"),
        (b"<script>alert(1)</script>", "application/pdf"),
    ],
)
def test_story_1_8_a_file_that_is_not_jpeg_png_or_pdf_is_a_415(
    body: bytes, declared: str, call: Call, storage: Storage
) -> None:
    message = _error(call(body, content_type=declared), 415, "UNSUPPORTED_MEDIA_TYPE")
    assert "JPEG" in message and "PDF" in message
    _nothing_written(storage)


def test_story_1_8_an_empty_body_is_a_400(call: Call, storage: Storage) -> None:
    _error(call(b""), 400, "VALIDATION_FAILED")
    _nothing_written(storage)


@pytest.mark.parametrize("token", [None, REVOKED, UNKNOWN, "not a token"])
def test_story_1_8_an_invalid_link_gets_the_identical_401_and_writes_nothing(
    token: str | None, call: Call, storage: Storage
) -> None:
    response = call(token=token)
    assert _error(response, 401, "LINK_NOT_VALID") == LINK_NOT_WORKING
    assert response.headers["WWW-Authenticate"] == "UploadToken"
    _nothing_written(storage)


def test_story_1_8_the_link_is_checked_before_the_key_and_the_file(
    call: Call, storage: Storage
) -> None:
    # A bad token with a bad key and a bad file: still the link answer, nothing else.
    _error(call(b"GIF89a", token=UNKNOWN, key=None), 401, "LINK_NOT_VALID")
    _nothing_written(storage)


@pytest.mark.parametrize("step", ["key", "blob", "queue"])
def test_story_1_8_a_storage_outage_is_a_retryable_503(
    step: str, call: Call, storage: Storage
) -> None:
    storage.fail = {step}
    response = call()
    _error(response, 503, "SERVICE_UNAVAILABLE")
    assert response.headers["Retry-After"] == "5"


# --- Never PostgreSQL, never a secret in logs ----------------------------------------


def test_story_1_8_upload_works_with_no_database_settings(
    call: Call, app_settings: dict[str, str]
) -> None:
    # supplier-api has no database setting to point anywhere: nothing to be down.
    assert not [name for name in app_settings if "DATABASE" in name or "PG" in name]
    # Not even the pipeline's settings are in its environment (Story 2.1).
    assert not [name for name in os.environ if name.startswith("POSTGRES_")]
    _ok(call())


def test_story_1_8_the_upload_path_imports_no_postgres_driver(
    app_settings: dict[str, str],
) -> None:
    # A fresh interpreter: other tests' imports can't hide or fake a dependency.
    script = (
        "import sys\n"
        "import invoicing.apps.supplier_api.function_app\n"
        "print('\\n'.join(sorted(sys.modules)))\n"
    )
    env = {**os.environ, **app_settings}
    for name in (
        "APPLICATIONINSIGHTS_CONNECTION_STRING",
        "APPLICATIONINSIGHTS_AUTHENTICATION_STRING",
    ):
        env.pop(name, None)
    result = subprocess.run(  # noqa: S603  # our own interpreter, a fixed script
        [sys.executable, "-c", script],
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    modules = set(result.stdout.split())
    assert {
        "invoicing.apps.supplier_api.upload",
        "invoicing.adapters.table_upload_keys",
        "invoicing.adapters.blob_images",
        "invoicing.adapters.queue",
    } <= modules
    assert not [m for m in modules if m.split(".")[0] in POSTGRES_DRIVERS]


@pytest.mark.parametrize("fail", [set(), {"blob"}])
def test_story_1_8_no_log_or_span_holds_the_token_the_key_or_the_file(
    fail: set[str],
    call: Call,
    storage: Storage,
    spans: InMemorySpanExporter,
    caplog: pytest.LogCaptureFixture,
) -> None:
    storage.fail = fail
    spans.clear()
    with caplog.at_level(logging.DEBUG):
        call(PNG, headers={"Content-Disposition": 'inline; filename="inv-4521.png"'})
        call(token=UNKNOWN)
        call(key="not-a-uuid")
    secrets = [
        TOKEN_A,
        token_hash(TOKEN_A),
        UNKNOWN,
        KEY,
        "inv-4521",
        "X-Upload-Token",
        "Idempotency-Key",
        "PNG",
    ]
    records = [
        f"{record.getMessage()} {vars(record)}"
        for record in caplog.records
        if record.name.startswith("invoicing")
    ]
    assert any("upload." in text or "http.domain_error" in text for text in records)
    finished = spans.get_finished_spans()
    assert finished, "the request spans were recorded"
    recorded = records + [
        f"{span.name} {dict(span.attributes or {})} {[e.attributes for e in span.events]}"
        for span in finished
    ]
    for text in recorded:
        for secret in secrets:
            assert secret not in text


def test_story_1_8_the_accepted_log_names_the_outcome_type_and_size(
    call: Call, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="invoicing"):
        call(PNG, content_type="image/png")
        call(PNG, content_type="image/png")
    accepted = [
        event_fields(r)
        for r in caplog.records
        if r.getMessage().startswith("upload.accepted ")
    ]
    assert [
        (f["status"], f["blob_written"], f["content_type"], f["size_bytes"])
        for f in accepted
    ] == [
        ("new", True, "image/png", len(PNG)),
        ("existing", False, "image/png", len(PNG)),
    ]


# --- Story 1.9: the device check ------------------------------------------------------


@pytest.mark.parametrize(
    ("header", "stored"),
    [(None, "passed"), ("passed", "passed"), ("overridden", "overridden")],
)
def test_story_1_9_the_device_check_is_stored_in_the_blob_metadata(
    header: str | None, stored: str, call: Call, storage: Storage
) -> None:
    headers = {} if header is None else {"X-Device-Check": header}
    invoice_id, _ = _ok(call(headers=headers))
    assert storage.blobs[invoice_id][1].to_blob_metadata()["device_check"] == stored
    assert storage.keys[UUID(KEY)].device_check == stored


@pytest.mark.parametrize("header", ["", "failed", "OVERRIDE"])
def test_story_1_9_any_other_device_check_is_a_400_and_writes_nothing(
    header: str, call: Call, storage: Storage
) -> None:
    message = _error(call(headers={"X-Device-Check": header}), 400, "VALIDATION_FAILED")
    assert "check" in message.lower()
    _nothing_written(storage)


def test_story_1_9_a_replay_with_another_device_check_keeps_the_stored_one(
    call: Call, storage: Storage
) -> None:
    first = _ok(call(headers={"X-Device-Check": "overridden"}))
    again = _ok(call(headers={"X-Device-Check": "passed"}))
    assert first == again
    invoice_id, _ = first
    assert storage.writes == ["key", "blob", "queue", "queue"]
    assert storage.blobs[invoice_id][1].device_check == "overridden"


def test_story_1_9_a_retry_completing_a_crashed_upload_writes_the_first_device_check(
    call: Call, storage: Storage
) -> None:
    storage.fail = {"blob"}
    _error(call(headers={"X-Device-Check": "overridden"}), 503, "SERVICE_UNAVAILABLE")
    storage.fail = set()
    # The retry says passed; the key holds the first attempt's overridden.
    invoice_id, _ = _ok(call())
    assert storage.blobs[invoice_id][1].device_check == "overridden"


def test_story_1_9_the_accepted_log_names_the_device_check(
    call: Call, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="invoicing"):
        call(headers={"X-Device-Check": "overridden"})
    (accepted,) = [
        event_fields(r)
        for r in caplog.records
        if r.getMessage().startswith("upload.accepted ")
    ]
    assert accepted["device_check"] == "overridden"


def test_story_1_9_a_replay_with_another_device_check_is_logged_by_code(
    call: Call, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="invoicing"):
        first, _ = _ok(call(headers={"X-Device-Check": "overridden"}))
        _ok(call(headers={"X-Device-Check": "overridden"}))
        _ok(call(headers={"X-Device-Check": "passed"}))
    mismatches = [
        event_fields(r)
        for r in caplog.records
        if r.getMessage().startswith("upload.device_check_mismatch ")
    ]
    # Once, for the retry that differed; the stored value, ids and codes only.
    assert mismatches == [
        {
            "invoice_id": str(first),
            "code": "DEVICE_CHECK_MISMATCH",
            "device_check": "overridden",
            **{k: v for k, v in mismatches[0].items() if k == "correlation_id"},
        }
    ]
