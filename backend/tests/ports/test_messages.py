"""Story 1.3: the AD-2 queue message, matrix row "Queue send"."""

from datetime import UTC, datetime
from uuid import UUID

from invoicing.ports.messages import QueueMessage

INVOICE_ID = UUID("0192f0c1-7a2b-7c3d-8e4f-0123456789ab")
CORRELATION_ID = UUID("0192f0c1-7a2b-7c3d-9e4f-0123456789ac")


def test_story_1_3_message_round_trips() -> None:
    message = QueueMessage(
        invoice_id=INVOICE_ID,
        correlation_id=CORRELATION_ID,
        first_enqueued_at=datetime(2026, 1, 2, tzinfo=UTC),
        attempt=3,
    )
    assert QueueMessage.from_json(message.to_json()) == message
