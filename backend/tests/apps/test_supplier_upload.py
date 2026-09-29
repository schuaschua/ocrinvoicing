"""Story 1.8: `POST /api/upload` on supplier-api, every row of the I/O matrix. Fakes
stand in for `supplierlinks`, `uploadkeys`, `images` and `q-quality` (coding-style.md
rule 23); nothing reaches Azure."""

import asyncio
import base64
import hashlib
import json
import logging
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
def handler(module: ModuleType) -> Callable[[func.HttpRequest], Any]:
    """The `upload` function's handler (the host allows reading its functions once)."""
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
    return upload.get_user_function()


@pytest.fixture
def call(handler: Callable[[func.HttpRequest], Any]) -> Call:
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


def _reset(storage: Storage, clock: Clock) -> None:
    """Empty storage and rewind the clock between the blocks of one merged test, so
    each block starts as a fresh test would (the handler holds these same fakes)."""
    storage.keys.clear()
    storage.blobs.clear()
    storage.messages.clear()
    storage.writes.clear()
    storage.fail = set()
    storage.yield_on_claim = False
    clock.now = NOW


# --- Happy path and replays ----------------------------------------------------------


def test_story_1_8_upload_writes_key_blob_message_once_across_retries_and_races(
    call: Call,
    handler: Callable[[func.HttpRequest], Any],
    storage: Storage,
    clock: Clock,
) -> None:
    # --- The happy path writes the key, then the blob, then the message.
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

    # --- A retry after success returns the same invoice and enqueues again.
    _reset(storage, clock)
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

    # --- A crash after the blob: the retry skips it and enqueues.
    _reset(storage, clock)
    storage.fail = {"queue"}
    _error(call(), 503, "SERVICE_UNAVAILABLE")
    assert storage.writes == ["key", "blob"]
    storage.fail = set()
    invoice_id, _ = _ok(call())
    assert storage.writes == ["key", "blob", "queue"]
    assert storage.messages[0][1].invoice_id == invoice_id

    # --- Concurrent requests with one key make one invoice.
    _reset(storage, clock)
    storage.yield_on_claim = True

    def request() -> func.HttpRequest:
        return func.HttpRequest(
            method="POST",
            url="/api/upload",
            headers={"X-Upload-Token": TOKEN_A, "Idempotency-Key": KEY},
            body=JPEG,
        )

    async def race() -> list[func.HttpResponse]:
        return list(await asyncio.gather(handler(request()), handler(request())))

    racer_one, racer_two = asyncio.run(race())
    assert _ok(racer_one) == _ok(racer_two)
    assert len(storage.keys) == 1 and len(storage.blobs) == 1


# --- Refusals: nothing is written ----------------------------------------------------


def test_story_1_8_refused_uploads_get_their_error_and_write_nothing(
    call: Call, storage: Storage, clock: Clock
) -> None:
    # --- A key held by another supplier is a 409 and writes nothing.
    theirs = _ok(call(token=TOKEN_B))
    before = (dict(storage.keys), dict(storage.blobs), list(storage.messages))
    message = _error(call(token=TOKEN_A), 409, "IDEMPOTENCY_KEY_CONFLICT")
    # Nothing about the other supplier's upload leaks.
    assert theirs[1] not in message and str(theirs[0]) not in message
    assert (dict(storage.keys), dict(storage.blobs), list(storage.messages)) == before

    # --- A malformed idempotency key is a 400.
    _reset(storage, clock)
    message = _error(call(key="not-a-uuid"), 400, "VALIDATION_FAILED")
    assert "key" in message.lower()
    _nothing_written(storage)

    # --- A file that is not JPEG, PNG or PDF is a 415.
    _reset(storage, clock)
    gif = b"GIF89a" + b"\x00" * 100
    message = _error(
        call(gif, content_type="image/jpeg"), 415, "UNSUPPORTED_MEDIA_TYPE"
    )
    assert "JPEG" in message and "PDF" in message
    _nothing_written(storage)

    # --- An invalid (revoked) link gets the identical 401 and writes nothing.
    _reset(storage, clock)
    response = call(token=REVOKED)
    assert _error(response, 401, "LINK_NOT_VALID") == LINK_NOT_WORKING
    assert response.headers["WWW-Authenticate"] == "UploadToken"
    _nothing_written(storage)


# --- Never PostgreSQL, never a secret in logs ----------------------------------------


def test_story_1_8_no_log_or_span_holds_the_token_the_key_or_the_file(
    call: Call,
    storage: Storage,
    spans: InMemorySpanExporter,
    caplog: pytest.LogCaptureFixture,
) -> None:
    storage.fail = {"blob"}
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


# --- Story 1.9: the device check ------------------------------------------------------


def test_story_1_9_the_device_check_is_stored_and_any_other_value_is_a_400(
    call: Call, storage: Storage, clock: Clock
) -> None:
    # --- "skipped" is stored in the blob metadata and the key.
    invoice_id, _ = _ok(call(headers={"X-Device-Check": "skipped"}))
    assert storage.blobs[invoice_id][1].to_blob_metadata()["device_check"] == "skipped"
    assert storage.keys[UUID(KEY)].device_check == "skipped"

    # --- Any other value ("failed") is a 400 and writes nothing.
    _reset(storage, clock)
    message = _error(
        call(headers={"X-Device-Check": "failed"}), 400, "VALIDATION_FAILED"
    )
    assert "check" in message.lower()
    _nothing_written(storage)
