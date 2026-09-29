"""Story 2.1: the `quality` stage, every I/O matrix row (grouped into two tests to
keep within the repo's test-case cap; each block starts on an empty schema), against a real
PostgreSQL 18 (signed in as the pipeline login), with fake blob and queue clients."""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, select

from _documents import blurred, darkened, exif, jpeg, page
from invoicing.adapters.documents import load_quality_thresholds, read_image
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


def test_story_2_1_and_1_9_quality_advances_readable_and_routes_unreadable_photos(
    pipeline_engine: Engine, reset_intake: Callable[[], None]
) -> None:
    # --- Story 2.1: a readable photo advances and queues extraction once.
    stage = Stage(pipeline_engine)
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

    # --- Story 2.1: an unreadable (dark) photo goes to the admin queue.
    reset_intake()
    stage = Stage(pipeline_engine)
    stage.images.put(jpeg(darkened(page()), exif(taken="2026:09:20 14:30:05")))
    _assert_routed(stage, stage.run(), "UNREADABLE")
    # The stage finished reading the photo: its hash and time are kept with the
    # routing (AD-9 duplicates, AD-19 photo date, AD-3 Retry intake guard).
    assert stage.invoice()["photo_taken_at"] == datetime(
        2026, 9, 20, 6, 30, 5, tzinfo=UTC
    )
    (hashed,) = stage.rows(image_hash)
    dark = read_image(jpeg(darkened(page()), exif(taken="2026:09:20 14:30:05")), 1024)
    assert unsigned_phash(hashed["phash"]) == dark.phash

    # --- Story 1.9: a skipped device check is still checked by the server.
    reset_intake()
    stage = Stage(pipeline_engine)
    stage.images.put(jpeg(blurred(page())), device_check=DeviceCheck.SKIPPED)
    _assert_routed(stage, stage.run(), "UNREADABLE")


def test_story_2_1_redeliveries_and_concurrent_deliveries_never_double_process(
    pipeline_engine: Engine, reset_intake: Callable[[], None]
) -> None:
    # --- A redelivery after success re-queues extraction only.
    stage = Stage(pipeline_engine)
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

    # --- A redelivery after routing only acknowledges.
    reset_intake()
    stage = Stage(pipeline_engine)
    stage.images.put(jpeg(darkened(page())))
    stage.run()
    outcome = stage.run(_message(attempt=2))
    assert outcome == QualityOutcome(Action.ACK)
    assert stage.queue.sent == []
    assert len(stage.rows(admin_item)) == 1
    assert len(stage.history()) == 2

    # --- A row left in `received` is finished by the redelivery.
    reset_intake()
    stage = Stage(pipeline_engine)
    # A crash after the insert, before the transition: the retry completes it.
    stage.images.put(SHARP_JPEG)
    first = stage.images.blobs[INVOICE_ID]
    asyncio.run(
        stage.invoices.insert_if_absent(
            NewInvoice(first.metadata, CORRELATION_ID, "pipeline:quality")
        )
    )
    _assert_advanced(stage, stage.run(_message(attempt=2)))

    # --- Concurrent deliveries make one row and one transition.
    reset_intake()
    stage = Stage(pipeline_engine)
    stage.images.put(SHARP_JPEG)
    racing = stage

    async def both() -> list[QualityOutcome]:
        racing.images.gate = asyncio.Event()
        racing.images.waiting = 2
        return list(
            await asyncio.gather(racing.handle(_message()), racing.handle(_message(2)))
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
