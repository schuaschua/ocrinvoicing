"""Storage Queue sender (AD-2): plain JSON text through `azure-storage-queue`, signed
in with the app's user-assigned managed identity."""

import logging
from collections.abc import Awaitable
from typing import Any, Protocol, Self

from azure.core.exceptions import AzureError
from azure.identity.aio import ManagedIdentityCredential
from azure.storage.queue.aio import QueueServiceClient

from invoicing.adapters.storage_errors import raise_unavailable
from invoicing.ports.messages import QueueMessage
from invoicing.ports.queue import QueueName

# Azure Storage Queues reject a visibility timeout above 7 days.
MAX_DELAY_SECONDS = 7 * 24 * 60 * 60

_logger = logging.getLogger("invoicing.queue")


class _QueueClient(Protocol):
    # Not `async def`: the SDK's tracing decorator types it as returning an Awaitable.
    def send_message(
        self, content: Any, *, visibility_timeout: int | None = None, **kwargs: Any
    ) -> Awaitable[Any]: ...


class _Closeable(Protocol):
    async def close(self) -> None: ...


class _QueueServiceClient(Protocol):
    def get_queue_client(self, queue: str, **kwargs: Any) -> _QueueClient: ...

    async def close(self) -> None: ...


class StorageQueueSender:
    """`QueueSender` over Azure Storage Queues."""

    def __init__(
        self, service: _QueueServiceClient, credential: _Closeable | None = None
    ) -> None:
        self._service = service
        self._credential = credential

    @classmethod
    def with_managed_identity(cls, account_name: str, client_id: str) -> Self:
        """A sender for `account_name`, authenticated as the user-assigned identity `client_id`."""
        credential = ManagedIdentityCredential(client_id=client_id)
        # No message_encode_policy: the client sends the text unchanged, matching the
        # consumers' host.json `messageEncoding: none` (AD-2).
        service = QueueServiceClient(
            account_url=f"https://{account_name}.queue.core.windows.net",
            credential=credential,
        )
        return cls(service, credential)

    async def send(
        self, queue: QueueName, message: QueueMessage, *, delay_seconds: int = 0
    ) -> None:
        if delay_seconds < 0:
            raise ValueError("delay_seconds must not be negative")
        if delay_seconds > MAX_DELAY_SECONDS:
            raise ValueError("delay_seconds must be at most 7 days")
        client = self._service.get_queue_client(queue.value)
        try:
            await client.send_message(
                message.to_json(), visibility_timeout=delay_seconds or None
            )
        # A failed send is a retryable 503 (AD-6); the log names the queue and a code.
        except AzureError as error:
            raise_unavailable(_logger, "queue.unavailable", error, queue=queue)

    async def close(self) -> None:
        """Release the underlying HTTP session and the credential."""
        await self._service.close()
        if self._credential is not None:
            await self._credential.close()
