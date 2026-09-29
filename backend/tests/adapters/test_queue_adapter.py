"""Story 1.3: the Storage Queue sender, matrix row "Queue send"; Story 1.8: a failed
send is a retryable 503. A fake client stands in for Azure; nothing is sent over the
network."""

import asyncio
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from invoicing.adapters.queue import StorageQueueSender
from invoicing.ports.messages import QueueMessage
from invoicing.ports.queue import QueueName, QueueSender

MESSAGE = QueueMessage.first(
    UUID("0192f0c1-7a2b-7c3d-8e4f-0123456789ab"),
    UUID("0192f0c1-7a2b-7c3d-9e4f-0123456789ac"),
    datetime(2026, 9, 29, 1, 30, tzinfo=UTC),
)


class FakeQueueClient:
    def __init__(self, name: str, sent: list[tuple[str, str, int | None]]) -> None:
        self.name = name
        self.sent = sent

    async def send_message(
        self, content: str, *, visibility_timeout: int | None = None
    ) -> Any:
        self.sent.append((self.name, content, visibility_timeout))


class FakeQueueService:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, int | None]] = []
        self.closed = False

    def get_queue_client(self, queue: str, **kwargs: Any) -> FakeQueueClient:
        return FakeQueueClient(queue, self.sent)

    async def close(self) -> None:
        self.closed = True


def test_story_1_3_producer_sends_plain_json_with_exactly_the_four_fields() -> None:
    service = FakeQueueService()
    sender: QueueSender = StorageQueueSender(service)
    asyncio.run(sender.send(QueueName.QUALITY, MESSAGE))
    ((queue, content, delay),) = service.sent
    assert queue == "q-quality" and delay is None
    assert json.loads(content) == {
        "invoice_id": "0192f0c1-7a2b-7c3d-8e4f-0123456789ab",
        "correlation_id": "0192f0c1-7a2b-7c3d-9e4f-0123456789ac",
        "first_enqueued_at": "2026-09-29T01:30:00.000000Z",
        "attempt": 1,
    }
