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
    FakeQueue,
    invoice_id,
    stopped_database,
)

from invoicing.adapters.documents import load_quality_thresholds
from invoicing.adapters.logging import ALLOWED_KEYS, event_fields
from invoicing.adapters.postgres.invoices import PostgresInvoiceRepository
from invoicing.apps.pipeline.dbwait import (
    DB_WAIT_SECONDS,
    wait_for_database,
)
from invoicing.apps.pipeline.quality import quality_handler
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
