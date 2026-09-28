"""Story 2.2: consumers wait out a stopped database (AD-7). Matrix rows "DB down,
consumer" and "DB down, poison", with a real engine pointed at a server that is not
running."""

import asyncio
import logging
from datetime import datetime, timedelta

import pytest
from _pipeline_fakes import (
    CORRELATION_ID,
    UPLOADED_AT,
    FakeImages,
    FakeMetrics,
    FakeQueue,
    invoice_id,
    stopped_database,
)

from invoicing.adapters.documents import load_quality_thresholds
from invoicing.adapters.logging import ALLOWED_KEYS, event_fields
from invoicing.adapters.postgres.invoices import PostgresInvoiceRepository
from invoicing.apps.pipeline.dbwait import (
    DB_WAIT_LIMIT,
    DB_WAIT_SECONDS,
    wait_for_database,
)
from invoicing.apps.pipeline.poison import poison_handler
from invoicing.apps.pipeline.quality import StageFailed, quality_handler
from invoicing.domain.errors import DatabaseOfflineError, ServiceUnavailableError
from invoicing.domain.status import Stage
from invoicing.ports.messages import QueueMessage
from invoicing.ports.queue import QueueName

INVOICE_ID = invoice_id(1)


def _soon() -> datetime:
    """A clock an hour after the message was first enqueued."""
    return UPLOADED_AT + timedelta(hours=1)


# A redelivered message: every field must survive the wait unchanged.
MESSAGE = QueueMessage(
    invoice_id=INVOICE_ID,
    correlation_id=CORRELATION_ID,
    first_enqueued_at=UPLOADED_AT,
    attempt=3,
)


def test_story_2_2_db_down_quality_message_is_re_enqueued_with_a_15_minute_delay(
    caplog: pytest.LogCaptureFixture,
) -> None:
    assert DB_WAIT_SECONDS == 15 * 60
    queue = FakeQueue()
    with stopped_database() as engine:
        stage = quality_handler(
            FakeImages(),
            PostgresInvoiceRepository(engine),
            queue,
            load_quality_thresholds(),
        )
        handle = wait_for_database(QueueName.QUALITY, queue, stage, clock=_soon)
        with caplog.at_level(logging.DEBUG, logger="invoicing"):
            # Returns normally: the host completes the original, keeping its count.
            assert asyncio.run(handle(MESSAGE.to_json())) is None
    assert queue.sent == [(QueueName.QUALITY, MESSAGE, DB_WAIT_SECONDS)]
    (waited,) = [
        r for r in caplog.records if r.getMessage().startswith("pipeline.db_wait")
    ]
    assert event_fields(waited) == {
        "code": "DB_OFFLINE",
        "queue": "q-quality",
        "invoice_id": str(INVOICE_ID),
        "correlation_id": str(CORRELATION_ID),
        "attempt": 3,
    }
    for record in caplog.records:
        if record.name.startswith("invoicing"):
            assert set(event_fields(record)) <= ALLOWED_KEYS


def test_story_2_2_db_down_poison_message_goes_back_to_its_poison_queue() -> None:
    queue = FakeQueue()
    metrics = FakeMetrics()
    with stopped_database() as engine:
        poison = poison_handler(
            Stage.EXTRACT, FakeImages(), PostgresInvoiceRepository(engine), metrics
        )
        handle = wait_for_database(QueueName.EXTRACT_POISON, queue, poison, clock=_soon)
        assert asyncio.run(handle(MESSAGE.to_json())) is None
    assert queue.sent == [(QueueName.EXTRACT_POISON, MESSAGE, DB_WAIT_SECONDS)]
    # Handled when it comes back, so it is counted then (no double count).
    assert metrics.emitted == []


def test_story_2_2_a_failed_re_enqueue_is_raised_for_a_host_retry() -> None:
    queue = FakeQueue(fail_for=frozenset({INVOICE_ID}))

    async def offline(body: str | bytes) -> None:
        raise DatabaseOfflineError()

    handle = wait_for_database(QueueName.QUALITY, queue, offline, clock=_soon)
    with pytest.raises(ServiceUnavailableError):
        asyncio.run(handle(MESSAGE.to_json()))
    assert queue.sent == []


def test_story_2_2_other_failures_pass_through_unchanged() -> None:
    queue = FakeQueue()

    async def failing(body: str | bytes) -> None:
        raise StageFailed("IMAGE_NOT_FOUND")

    handle = wait_for_database(QueueName.QUALITY, queue, failing, clock=_soon)
    with pytest.raises(StageFailed, match="IMAGE_NOT_FOUND"):
        asyncio.run(handle(MESSAGE.to_json()))
    assert queue.sent == []


def test_story_2_2_a_handler_result_is_returned_as_it_is() -> None:
    async def done(body: str | bytes) -> str:
        return "advance"

    handle = wait_for_database(QueueName.QUALITY, FakeQueue(), done)
    assert asyncio.run(handle(MESSAGE.to_json())) == "advance"


def test_story_2_2_an_offline_error_on_an_unparsable_body_is_raised() -> None:
    queue = FakeQueue()

    async def offline(body: str | bytes) -> None:
        raise DatabaseOfflineError()

    handle = wait_for_database(QueueName.QUALITY, queue, offline, clock=_soon)
    with pytest.raises(DatabaseOfflineError):
        asyncio.run(handle("not json"))
    assert queue.sent == []


def test_story_2_2_a_wait_past_eight_days_stops_and_raises_for_the_host(
    caplog: pytest.LogCaptureFixture,
) -> None:
    assert DB_WAIT_LIMIT == timedelta(days=8)
    queue = FakeQueue()

    async def offline(body: str | bytes) -> None:
        raise DatabaseOfflineError()

    def late() -> datetime:
        return UPLOADED_AT + DB_WAIT_LIMIT + timedelta(seconds=1)

    handle = wait_for_database(QueueName.QUALITY, queue, offline, clock=late)
    with (
        caplog.at_level(logging.DEBUG, logger="invoicing"),
        pytest.raises(DatabaseOfflineError),
    ):
        asyncio.run(handle(MESSAGE.to_json()))
    # Not waited out again: the host retries, then poisons it.
    assert queue.sent == []
    (record,) = [
        r for r in caplog.records if r.getMessage().startswith("pipeline.db_wait")
    ]
    assert record.levelno == logging.ERROR
    assert event_fields(record)["code"] == "DB_WAIT_EXPIRED"

    # Just inside the limit it still waits.
    def inside() -> datetime:
        return UPLOADED_AT + DB_WAIT_LIMIT

    asyncio.run(
        wait_for_database(QueueName.QUALITY, queue, offline, clock=inside)(
            MESSAGE.to_json()
        )
    )
    assert queue.sent == [(QueueName.QUALITY, MESSAGE, DB_WAIT_SECONDS)]


def test_story_2_2_further_arguments_reach_the_handler() -> None:
    seen: list[int] = []

    async def poison(body: str | bytes, dequeue_count: int) -> str:
        seen.append(dequeue_count)
        return "ack"

    handle = wait_for_database(
        QueueName.QUALITY_POISON, FakeQueue(), poison, clock=_soon
    )
    assert asyncio.run(handle(MESSAGE.to_json(), 4)) == "ack"
    assert seen == [4]
