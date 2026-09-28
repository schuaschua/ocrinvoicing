"""Story 1.3: the Storage Queue sender, matrix row "Queue send"; Story 1.8: a failed
send is a retryable 503. A fake client stands in for Azure; nothing is sent over the
network."""

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from azure.core.exceptions import (
    ClientAuthenticationError,
    HttpResponseError,
    ResourceNotFoundError,
    ServiceRequestError,
)
from azure.identity.aio import ManagedIdentityCredential

from invoicing.adapters.logging import event_fields
from invoicing.adapters.queue import StorageQueueSender
from invoicing.domain.errors import ServiceUnavailableError
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


def test_story_1_3_delayed_send_sets_the_visibility_timeout() -> None:
    service = FakeQueueService()
    asyncio.run(
        StorageQueueSender(service).send(QueueName.POST, MESSAGE, delay_seconds=900)
    )
    assert service.sent[0][0] == "q-post" and service.sent[0][2] == 900


def test_story_1_3_negative_delay_is_refused() -> None:
    with pytest.raises(ValueError, match="negative"):
        asyncio.run(
            StorageQueueSender(FakeQueueService()).send(
                QueueName.POST, MESSAGE, delay_seconds=-1
            )
        )


def test_story_1_3_close_releases_the_client_and_the_credential() -> None:
    class FakeCredential:
        closed = False

        async def close(self) -> None:
            self.closed = True

    service, credential = FakeQueueService(), FakeCredential()
    asyncio.run(StorageQueueSender(service, credential).close())
    assert service.closed and credential.closed


def test_story_1_3_delay_above_seven_days_is_refused() -> None:
    service = FakeQueueService()
    sender = StorageQueueSender(service)
    asyncio.run(sender.send(QueueName.POST, MESSAGE, delay_seconds=604_800))
    with pytest.raises(ValueError, match="7 days"):
        asyncio.run(sender.send(QueueName.POST, MESSAGE, delay_seconds=604_801))
    assert [sent[2] for sent in service.sent] == [604_800]


def test_story_1_3_real_client_uses_managed_identity_and_no_message_encoding() -> None:
    sender = StorageQueueSender.with_managed_identity(
        "babaloosealngst01", "00000000-0000-0000-0000-00000000c1d0"
    )
    service: Any = sender._service
    client: Any = service.get_queue_client("q-quality")
    assert client.url == "https://babaloosealngst01.queue.core.windows.net/q-quality"
    assert isinstance(service.credential, ManagedIdentityCredential)
    assert sender._credential is service.credential
    # AD-2: plain text on the wire, matching host.json messageEncoding "none".
    assert type(client._message_encode_policy).__name__ == "NoEncodePolicy"
    asyncio.run(sender.close())


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (ServiceRequestError("connection reset"), "TRANSIENT"),
        (HttpResponseError(message="500 on q-quality"), "TRANSIENT"),
        (ClientAuthenticationError("no role"), "AUTH_FAILED"),
        (ResourceNotFoundError("QueueNotFound"), "RESOURCE_NOT_FOUND"),
    ],
)
def test_story_1_8_a_failed_send_is_a_retryable_503_logged_by_queue_and_code(
    error: Exception, code: str, caplog: pytest.LogCaptureFixture
) -> None:
    class FailingClient:
        async def send_message(self, content: str, **kwargs: Any) -> Any:
            raise error

    class FailingService(FakeQueueService):
        def get_queue_client(self, queue: str, **kwargs: Any) -> Any:
            return FailingClient()

    with (
        caplog.at_level(logging.DEBUG, logger="invoicing"),
        pytest.raises(ServiceUnavailableError) as raised,
    ):
        asyncio.run(
            StorageQueueSender(FailingService()).send(QueueName.QUALITY, MESSAGE)
        )
    assert raised.value.__cause__ is None and raised.value.__suppress_context__
    ((fields,),) = [
        [event_fields(r)]
        for r in caplog.records
        if r.getMessage().startswith("queue.unavailable ")
    ]
    assert fields["code"] == code and fields["queue"] == "q-quality"
