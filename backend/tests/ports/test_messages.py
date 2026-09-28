"""Story 1.3: the AD-2 queue message, matrix row "Queue send"."""

import json
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from invoicing.ports.messages import QueueMessage

INVOICE_ID = UUID("0192f0c1-7a2b-7c3d-8e4f-0123456789ab")
CORRELATION_ID = UUID("0192f0c1-7a2b-7c3d-9e4f-0123456789ac")


def test_story_1_3_message_json_has_exactly_the_four_fields_with_utc_time() -> None:
    singapore = timezone(timedelta(hours=8))
    message = QueueMessage.first(
        INVOICE_ID,
        CORRELATION_ID,
        datetime(2026, 9, 29, 9, 30, 0, 123456, tzinfo=singapore),
    )
    assert json.loads(message.to_json()) == {
        "invoice_id": str(INVOICE_ID),
        "correlation_id": str(CORRELATION_ID),
        "first_enqueued_at": "2026-09-29T01:30:00.123456Z",
        "attempt": 1,
    }


def test_story_1_3_message_round_trips() -> None:
    message = QueueMessage(
        invoice_id=INVOICE_ID,
        correlation_id=CORRELATION_ID,
        first_enqueued_at=datetime(2026, 1, 2, tzinfo=UTC),
        attempt=3,
    )
    assert QueueMessage.from_json(message.to_json()) == message


@pytest.mark.parametrize(
    "payload",
    [
        {
            "invoice_id": str(INVOICE_ID),
            "correlation_id": str(CORRELATION_ID),
            "first_enqueued_at": "2026-09-29T01:30:00",
            "attempt": 1,
        },
        {
            "invoice_id": str(INVOICE_ID),
            "correlation_id": str(CORRELATION_ID),
            "first_enqueued_at": "2026-09-29T01:30:00Z",
            "attempt": 0,
        },
        {
            "invoice_id": str(INVOICE_ID),
            "correlation_id": str(CORRELATION_ID),
            "first_enqueued_at": "2026-09-29T01:30:00Z",
        },
        {
            "invoice_id": str(INVOICE_ID),
            "correlation_id": str(CORRELATION_ID),
            "first_enqueued_at": "2026-09-29T01:30:00Z",
            "attempt": 1,
            "supplier_id": "extra data never travels on the queue",
        },
    ],
    ids=["naive-time", "attempt-zero", "missing-field", "extra-field"],
)
def test_story_1_3_malformed_messages_are_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        QueueMessage.from_json(json.dumps(payload))


def test_story_1_3_messages_are_immutable() -> None:
    message = QueueMessage.first(
        INVOICE_ID, CORRELATION_ID, datetime(2026, 1, 2, tzinfo=UTC)
    )
    with pytest.raises(ValidationError):
        message.attempt = 2  # type: ignore[misc]  # deliberately writing to a frozen model


@pytest.mark.parametrize("attempt", ["true", '"3"', "2.0"])
def test_story_1_3_attempt_must_be_a_json_integer(attempt: str) -> None:
    text = (
        f'{{"invoice_id": "{INVOICE_ID}", "correlation_id": "{CORRELATION_ID}", '
        f'"first_enqueued_at": "2026-09-29T01:30:00Z", "attempt": {attempt}}}'
    )
    with pytest.raises(ValidationError):
        QueueMessage.from_json(text)
