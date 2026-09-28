"""Stage queues (AD-2) and the port every producer sends through."""

from enum import StrEnum
from typing import Protocol

from invoicing.ports.messages import QueueMessage


class QueueName(StrEnum):
    """One queue per stage input (AD-2)."""

    QUALITY = "q-quality"
    EXTRACT = "q-extract"
    VALIDATE = "q-validate"
    POST = "q-post"


class QueueSender(Protocol):
    """Sends a `QueueMessage` to a stage queue."""

    async def send(
        self, queue: QueueName, message: QueueMessage, *, delay_seconds: int = 0
    ) -> None:
        """Enqueue `message`, invisible for `delay_seconds` (AD-3 backoff, AD-7 waits)."""
        ...
