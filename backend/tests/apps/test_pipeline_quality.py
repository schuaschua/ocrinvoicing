"""Story 2.1: the `quality` stage, one test per I/O matrix row, against a real
PostgreSQL 18 (signed in as the pipeline login), with fake blob and queue clients."""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from PIL import Image
from sqlalchemy import Engine, select

from _documents import blurred, darkened, exif, hamming, jpeg, page, pdf, png
from invoicing.adapters.documents import load_quality_thresholds, read_image
from invoicing.adapters.logging import ALLOWED_KEYS, DROPPED_FIELDS_KEY, event_fields
from invoicing.adapters.postgres.invoices import (
    PostgresInvoiceRepository,
    unsigned_phash,
)
from invoicing.adapters.postgres.schema import (
    admin_item,
    image_hash,
    invoice,
    status_history,
)
from invoicing.apps.pipeline.quality import (
    Action,
    QualityOutcome,
    StageFailed,
    quality_handler,
)
from invoicing.domain.upload import UploadContentType
from invoicing.ports.blobs import ImageNotFoundError, StoredImage
from invoicing.ports.intake import DeviceCheck, IntakeBlobMetadata, IntakeSource
from invoicing.ports.invoices import NewInvoice
from invoicing.ports.messages import QueueMessage
from invoicing.ports.queue import QueueName

INVOICE_ID = UUID("0192f0c1-7a2b-7c3d-8e4f-0123456789ab")
CORRELATION_ID = UUID("0192f0c1-7a2b-7c3d-8e4f-0000000000c0")
SUPPLIER_ID = UUID("0192f0c1-0000-7000-8000-000000000001")
UPLOADED_AT = datetime(2026, 9, 29, 1, 30, tzinfo=UTC)
NOW = datetime(2026, 9, 29, 1, 31, tzinfo=UTC)
THRESHOLDS = load_quality_thresholds()
SHARP_JPEG = jpeg(page())


class FakeImages:
    """`ImageReader` over a dict; `gate` holds every read until `waiting` reads arrived."""

    def __init__(self) -> None:
        self.blobs: dict[UUID, StoredImage] = {}
        self.reads: list[UUID] = []
        self.gate: asyncio.Event | None = None
        self.waiting = 0

    def put(
        self,
        data: bytes,
        content_type: UploadContentType = UploadContentType.JPEG,
        device_check: DeviceCheck = DeviceCheck.PASSED,
        invoice_id: UUID = INVOICE_ID,
        source: IntakeSource = IntakeSource.LINK,
        delivery_id: UUID | None = None,
    ) -> None:
        self.blobs[invoice_id] = StoredImage(
            data,
            IntakeBlobMetadata(
                invoice_id=invoice_id,
                source=source,
                supplier_id=SUPPLIER_ID,
                delivery_id=delivery_id,
                content_type=content_type,
                uploaded_at=UPLOADED_AT,
                device_check=device_check,
            ),
        )

    async def get(self, invoice_id: UUID) -> StoredImage:
        self.reads.append(invoice_id)
        if self.gate is not None:
            if len(self.reads) >= self.waiting:
                self.gate.set()
            await self.gate.wait()
        if invoice_id not in self.blobs:
            raise ImageNotFoundError("the upload original does not exist")
        return self.blobs[invoice_id]


class FakeQueue:
    def __init__(self) -> None:
        self.sent: list[tuple[QueueName, QueueMessage, int]] = []

    async def send(
        self, queue: QueueName, message: QueueMessage, *, delay_seconds: int = 0
    ) -> None:
        self.sent.append((queue, message, delay_seconds))


class Stage:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.images = FakeImages()
        self.queue = FakeQueue()
        self.invoices = PostgresInvoiceRepository(engine)
        self.handle = quality_handler(
            self.images, self.invoices, self.queue, THRESHOLDS, clock=lambda: NOW
        )

    def run(self, message: str | None = None) -> QualityOutcome:
        return asyncio.run(self.handle(message or _message()))

    def rows(self, table: Any) -> list[Any]:
        with self.engine.connect() as connection:
            return list(connection.execute(select(table)).mappings())

    def invoice(self) -> Any:
        (row,) = self.rows(invoice)
        return row

    def history(self) -> list[tuple[str | None, str]]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(
                    status_history.c.from_status, status_history.c.to_status
                ).order_by(status_history.c.id)
            )
            return [tuple(row) for row in rows]


def _message(attempt: int = 1, invoice_id: UUID = INVOICE_ID) -> str:
    return QueueMessage(
        invoice_id=invoice_id,
        correlation_id=CORRELATION_ID,
        first_enqueued_at=UPLOADED_AT,
        attempt=attempt,
    ).to_json()


@pytest.fixture
def stage(pipeline_engine: Engine) -> Stage:
    return Stage(pipeline_engine)


def _assert_advanced(stage: Stage, outcome: QualityOutcome) -> None:
    assert outcome == QualityOutcome(Action.ADVANCE, QueueName.EXTRACT)
    assert stage.invoice()["status"] == "awaiting_extraction"
    assert stage.history() == [(None, "received"), ("received", "awaiting_extraction")]
    ((queue, message, delay),) = stage.queue.sent
    assert (queue, delay) == (QueueName.EXTRACT, 0)
    assert message == QueueMessage.first(INVOICE_ID, CORRELATION_ID, NOW)
    assert stage.rows(admin_item) == []


def _assert_routed(stage: Stage, outcome: QualityOutcome, reason: str) -> None:
    """Matrix: `in_admin_queue`, one admin item with a routing id, a history row and
    nothing enqueued."""
    assert outcome.action is Action.ROUTE and outcome.enqueue is None
    assert outcome.reason == reason
    assert stage.invoice()["status"] == "in_admin_queue"
    (item,) = stage.rows(admin_item)
    assert item["reason"] == reason and item["invoice_id"] == INVOICE_ID
    assert item["routing_id"].version == 7
    assert stage.history() == [(None, "received"), ("received", "in_admin_queue")]
    assert stage.queue.sent == []


# --- Matrix rows ---------------------------------------------------------------------


def test_story_2_1_readable_photo_advances_and_queues_extraction_once(
    stage: Stage,
) -> None:
    stage.images.put(jpeg(page(), exif(taken="2026:09:20 14:30:05")))
    _assert_advanced(stage, stage.run())
    row = stage.invoice()
    # The row comes from the blob metadata (AD-5) and the message's correlation id.
    assert (row["supplier_id"], row["source"], row["correlation_id"]) == (
        SUPPLIER_ID,
        "link",
        CORRELATION_ID,
    )
    assert (row["content_type"], row["device_check"]) == ("image/jpeg", "passed")
    assert row["photo_taken_at"] == datetime(2026, 9, 20, 6, 30, 5, tzinfo=UTC)
    (hashed,) = stage.rows(image_hash)
    expected = read_image(jpeg(page(), exif(taken="2026:09:20 14:30:05")), 1024).phash
    assert unsigned_phash(hashed["phash"]) == expected


@pytest.mark.parametrize("pages", [1, 2])
def test_story_2_1_readable_pdf_advances_without_phash_or_photo_time(
    stage: Stage, pages: int
) -> None:
    stage.images.put(pdf(pages), UploadContentType.PDF)
    _assert_advanced(stage, stage.run())
    assert stage.invoice()["photo_taken_at"] is None
    assert stage.invoice()["content_type"] == "application/pdf"
    assert stage.rows(image_hash) == []


@pytest.mark.parametrize("spoil", [darkened, blurred], ids=["dark", "blurry"])
def test_story_2_1_unreadable_photo_goes_to_the_admin_queue(
    stage: Stage, spoil: Any
) -> None:
    stage.images.put(jpeg(spoil(page()), exif(taken="2026:09:20 14:30:05")))
    _assert_routed(stage, stage.run(), "UNREADABLE")
    # The stage finished reading the photo: its hash and time are kept with the
    # routing (AD-9 duplicates, AD-19 photo date, AD-3 Retry intake guard).
    assert stage.invoice()["photo_taken_at"] == datetime(
        2026, 9, 20, 6, 30, 5, tzinfo=UTC
    )
    (hashed,) = stage.rows(image_hash)
    expected = read_image(jpeg(spoil(page()), exif(taken="2026:09:20 14:30:05")), 1024)
    assert unsigned_phash(hashed["phash"]) == expected.phash


def test_story_2_1_overridden_upload_that_passes_is_processed_normally(
    stage: Stage,
) -> None:
    stage.images.put(png(page(800, 600)), UploadContentType.PNG, DeviceCheck.OVERRIDDEN)
    _assert_advanced(stage, stage.run())
    assert stage.invoice()["device_check"] == "overridden"


def test_story_2_1_overridden_upload_that_fails_is_unreadable(stage: Stage) -> None:
    stage.images.put(jpeg(blurred(page())), device_check=DeviceCheck.OVERRIDDEN)
    _assert_routed(stage, stage.run(), "UNREADABLE")


def test_story_2_1_pdf_over_two_pages_is_unsupported(stage: Stage) -> None:
    stage.images.put(pdf(3), UploadContentType.PDF)
    _assert_routed(stage, stage.run(), "UNSUPPORTED_DOCUMENT")


@pytest.mark.parametrize(
    ("data", "content_type"),
    [
        (b"\xff\xd8\xff\xe0 not a jpeg at all", UploadContentType.JPEG),
        (SHARP_JPEG[: len(SHARP_JPEG) // 4], UploadContentType.JPEG),
        (b"\x89PNG\r\n\x1a\n" + b"\0" * 64, UploadContentType.PNG),
        (b"%PDF-1.7\n this is not a pdf", UploadContentType.PDF),
    ],
    ids=["jpeg", "truncated-jpeg", "png", "pdf"],
)
def test_story_2_1_corrupt_file_is_unreadable(
    stage: Stage, data: bytes, content_type: UploadContentType
) -> None:
    stage.images.put(data, content_type)
    _assert_routed(stage, stage.run(), "UNREADABLE")
    assert stage.rows(image_hash) == []
    assert stage.invoice()["photo_taken_at"] is None


def test_story_2_1_exif_orientation_is_applied_before_measuring_and_hashing(
    stage: Stage,
) -> None:
    turned = page().transpose(Image.Transpose.ROTATE_90)
    stage.images.put(jpeg(turned, exif(orientation=6)))
    _assert_advanced(stage, stage.run())
    (hashed,) = stage.rows(image_hash)
    upright = read_image(SHARP_JPEG, 1024).phash
    unoriented = read_image(jpeg(turned), 1024).phash
    assert upright is not None and unoriented is not None
    assert hamming(unsigned_phash(hashed["phash"]), upright) <= 8
    assert hamming(unsigned_phash(hashed["phash"]), unoriented) > 8


@pytest.mark.parametrize(
    ("taken", "offset", "expected"),
    [
        ("2026:09:20 14:30:05", None, datetime(2026, 9, 20, 6, 30, 5, tzinfo=UTC)),
        ("2026:09:20 14:30:05", "+02:00", datetime(2026, 9, 20, 12, 30, 5, tzinfo=UTC)),
        ("2026:13:45 99:99:99", None, None),
        ("2026:09:20 14:30:05", "garbage", datetime(2026, 9, 20, 6, 30, 5, tzinfo=UTC)),
    ],
    ids=["singapore", "offset", "malformed", "malformed-offset"],
)
def test_story_2_1_exif_time_is_stored_as_utc(
    stage: Stage, taken: str, offset: str | None, expected: datetime | None
) -> None:
    stage.images.put(jpeg(page(), exif(taken=taken, offset=offset)))
    stage.run()
    assert stage.invoice()["photo_taken_at"] == expected


def test_story_2_1_redelivery_after_success_requeues_extraction_only(
    stage: Stage,
) -> None:
    stage.images.put(SHARP_JPEG)
    stage.run()
    stage.queue.sent.clear()
    # The images may be gone by then (AD-15): a redelivery never needs the blob.
    stage.images.blobs.clear()
    outcome = stage.run(_message(attempt=2))
    assert outcome == QualityOutcome(Action.ACK, QueueName.EXTRACT)
    assert len(stage.rows(invoice)) == 1
    assert stage.history() == [(None, "received"), ("received", "awaiting_extraction")]
    assert len(stage.rows(image_hash)) == 1
    ((queue, message, _),) = stage.queue.sent
    assert queue is QueueName.EXTRACT and message.invoice_id == INVOICE_ID


def test_story_2_1_redelivery_after_routing_only_acknowledges(stage: Stage) -> None:
    stage.images.put(jpeg(darkened(page())))
    stage.run()
    outcome = stage.run(_message(attempt=2))
    assert outcome == QualityOutcome(Action.ACK)
    assert stage.queue.sent == []
    assert len(stage.rows(admin_item)) == 1
    assert len(stage.history()) == 2


def test_story_2_1_a_row_left_in_received_is_finished_by_the_redelivery(
    stage: Stage,
) -> None:
    # A crash after the insert, before the transition: the retry completes it.
    stage.images.put(SHARP_JPEG)
    first = stage.images.blobs[INVOICE_ID]
    asyncio.run(
        stage.invoices.insert_if_absent(
            NewInvoice(first.metadata, CORRELATION_ID, "pipeline:quality")
        )
    )
    _assert_advanced(stage, stage.run(_message(attempt=2)))


def test_story_2_1_a_lost_race_rereads_the_status(
    stage: Stage, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Another delivery moved the invoice between this one's check and its transition.
    stage.images.put(SHARP_JPEG)
    real = stage.invoices.transition

    async def racing(plan: Any, **kwargs: Any) -> bool:
        await real(plan, **kwargs)
        return await real(plan, **kwargs)

    monkeypatch.setattr(stage.invoices, "transition", racing)
    assert stage.run() == QualityOutcome(Action.ACK, QueueName.EXTRACT)


def test_story_2_1_concurrent_deliveries_make_one_row_and_one_transition(
    stage: Stage,
) -> None:
    stage.images.put(SHARP_JPEG)

    async def both() -> list[QualityOutcome]:
        stage.images.gate = asyncio.Event()
        stage.images.waiting = 2
        return list(
            await asyncio.gather(stage.handle(_message()), stage.handle(_message(2)))
        )

    outcomes = asyncio.run(both())
    # Both passed the status check before either inserted.
    assert stage.images.reads == [INVOICE_ID, INVOICE_ID]
    assert sorted(o.action for o in outcomes) == [Action.ACK, Action.ADVANCE]
    assert len(stage.rows(invoice)) == 1
    assert stage.history() == [(None, "received"), ("received", "awaiting_extraction")]
    assert len(stage.rows(image_hash)) == 1
    # The loser re-enqueues too (AD-2): a duplicate message is harmless.
    assert [q for q, _, _ in stage.queue.sent] == [QueueName.EXTRACT, QueueName.EXTRACT]


def test_story_2_1_missing_blob_raises_for_a_retry_and_logs_a_code(
    stage: Stage, caplog: pytest.LogCaptureFixture
) -> None:
    with (
        caplog.at_level(logging.INFO, logger="invoicing"),
        pytest.raises(StageFailed) as raised,
    ):
        stage.run()
    assert raised.value.code == "IMAGE_NOT_FOUND"
    assert raised.value.__cause__ is None and raised.value.__suppress_context__
    assert stage.rows(invoice) == []
    assert stage.queue.sent == []
    (failed,) = [
        r for r in caplog.records if r.getMessage().startswith("quality.failed ")
    ]
    assert event_fields(failed) == {
        "invoice_id": str(INVOICE_ID),
        "code": "IMAGE_NOT_FOUND",
        "attempt": 1,
        "correlation_id": str(CORRELATION_ID),
    }


# --- The handler around the stage ------------------------------------------------------


@pytest.mark.parametrize("body", ["not json", '{"invoice_id": "x"}', b"\xff\xfe"])
def test_story_2_1_a_malformed_message_is_raised_and_logged_by_code(
    stage: Stage, body: str | bytes, caplog: pytest.LogCaptureFixture
) -> None:
    with (
        caplog.at_level(logging.INFO, logger="invoicing"),
        pytest.raises(StageFailed, match="MALFORMED_MESSAGE") as raised,
    ):
        asyncio.run(stage.handle(body))
    assert raised.value.__cause__ is None and raised.value.__suppress_context__
    (record,) = [r for r in caplog.records if r.name.startswith("invoicing")]
    assert event_fields(record) == {"code": "MALFORMED_MESSAGE"}
    assert stage.images.reads == []


def test_story_2_1_blob_metadata_for_another_invoice_is_refused(stage: Stage) -> None:
    other = UUID("0192f0c1-7a2b-7c3d-8e4f-0000000000ff")
    stage.images.put(SHARP_JPEG, invoice_id=other)
    stage.images.blobs[INVOICE_ID] = stage.images.blobs[other]
    with pytest.raises(StageFailed, match="METADATA_INVOICE_MISMATCH"):
        stage.run()
    assert stage.rows(invoice) == []


@pytest.mark.parametrize(
    ("source", "delivery_id"),
    [
        (IntakeSource.LINK, UUID("0192f0c1-0000-7000-8000-00000000de11")),
        (IntakeSource.GOODS_IN, None),
    ],
    ids=["link-with-delivery", "goods-in-without-delivery"],
)
def test_story_2_1_source_and_delivery_that_disagree_fail_early_with_a_code(
    stage: Stage,
    source: IntakeSource,
    delivery_id: UUID | None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    stage.images.put(SHARP_JPEG, source=source, delivery_id=delivery_id)
    with (
        caplog.at_level(logging.INFO, logger="invoicing"),
        pytest.raises(StageFailed) as raised,
    ):
        stage.run()
    assert raised.value.code == "SOURCE_DELIVERY_MISMATCH"
    # Refused before any write, so no check constraint is hit on each retry.
    assert stage.rows(invoice) == []
    (failed,) = [
        r for r in caplog.records if r.getMessage().startswith("quality.failed ")
    ]
    assert event_fields(failed)["code"] == "SOURCE_DELIVERY_MISMATCH"


def test_story_2_1_a_goods_in_scan_with_its_delivery_is_processed(stage: Stage) -> None:
    delivery = UUID("0192f0c1-0000-7000-8000-00000000de11")
    stage.images.put(SHARP_JPEG, source=IntakeSource.GOODS_IN, delivery_id=delivery)
    _assert_advanced(stage, stage.run())
    assert stage.invoice()["delivery_id"] == delivery


def test_story_2_1_an_unexpected_failure_reaches_the_host_as_a_code_only(
    stage: Stage, caplog: pytest.LogCaptureFixture
) -> None:
    stage.images.put(SHARP_JPEG)

    async def leaky(invoice_id: UUID) -> Any:
        raise RuntimeError("password=hunter2 host=db.internal")

    stage.invoices.status = leaky  # type: ignore[method-assign]  # a failing fake
    with (
        caplog.at_level(logging.DEBUG, logger="invoicing"),
        pytest.raises(StageFailed) as raised,
    ):
        stage.run()
    assert raised.value.code == "RuntimeError"
    assert str(raised.value) == "quality stage failed: RuntimeError"
    assert raised.value.__cause__ is None and raised.value.__suppress_context__
    for record in caplog.records:
        assert "hunter2" not in record.getMessage()


def test_story_2_1_the_stage_runs_in_the_uploads_trace_and_logs_codes_only(
    stage: Stage, spans: InMemorySpanExporter, caplog: pytest.LogCaptureFixture
) -> None:
    stage.images.put(jpeg(page(), exif(taken="2026:09:20 14:30:05")))
    with caplog.at_level(logging.DEBUG, logger="invoicing"):
        stage.run()
    (span,) = [s for s in spans.get_finished_spans() if s.name == "pipeline.quality"]
    # One trace per correlation id (AD-17).
    assert span.context is not None and span.context.trace_id == CORRELATION_ID.int
    assert dict(span.attributes or {}) == {
        "correlation_id": str(CORRELATION_ID),
        "invoice_id": str(INVOICE_ID),
        "stage": "quality",
        "attempt": 1,
    }
    (done,) = [r for r in caplog.records if r.getMessage().startswith("quality.done ")]
    fields = event_fields(done)
    assert fields["code"] == "advance" and fields["queue"] == "q-extract"
    assert isinstance(fields["duration_ms"], int)
    for record in caplog.records:
        if record.name.startswith("invoicing"):
            assert DROPPED_FIELDS_KEY not in event_fields(record)
            assert set(event_fields(record)) <= ALLOWED_KEYS
            # Never the photo time or the hash.
            assert "2026-09-20" not in record.getMessage()


def test_story_2_1_an_enqueue_failure_is_raised_after_the_commit(stage: Stage) -> None:
    stage.images.put(SHARP_JPEG)

    async def failing(*args: Any, **kwargs: Any) -> None:
        raise ConnectionError("queue down")

    stage.queue.send = failing  # type: ignore[method-assign]  # a failing fake
    with pytest.raises(StageFailed, match="ConnectionError"):
        stage.run()
    # Committed first: the redelivery re-enqueues from the saved status (AD-2).
    assert stage.invoice()["status"] == "awaiting_extraction"
    stage.queue = FakeQueue()
    stage.handle = quality_handler(
        stage.images, stage.invoices, stage.queue, THRESHOLDS, clock=lambda: NOW
    )
    assert stage.run(_message(2)) == QualityOutcome(Action.ACK, QueueName.EXTRACT)
    assert [q for q, _, _ in stage.queue.sent] == [QueueName.EXTRACT]
