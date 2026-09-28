"""Stage queues (AD-2) and the port every producer sends through."""

from collections.abc import Mapping
from enum import StrEnum
from typing import Protocol

from invoicing.domain.status import Stage
from invoicing.ports.messages import QueueMessage


class QueueName(StrEnum):
    """One queue per stage input (AD-2), and the poison queue the Functions host moves
    a message to after `maxDequeueCount` failures (`<queue>-poison`)."""

    QUALITY = "q-quality"
    EXTRACT = "q-extract"
    VALIDATE = "q-validate"
    POST = "q-post"
    QUALITY_POISON = "q-quality-poison"
    EXTRACT_POISON = "q-extract-poison"
    VALIDATE_POISON = "q-validate-poison"
    POST_POISON = "q-post-poison"


# The queue that feeds each stage (AD-2).
STAGE_QUEUES: Mapping[Stage, QueueName] = {
    Stage.QUALITY: QueueName.QUALITY,
    Stage.EXTRACT: QueueName.EXTRACT,
    Stage.VALIDATE: QueueName.VALIDATE,
    Stage.POST: QueueName.POST,
}

# Each stage's poison queue, watched by a poison trigger (AD-2).
POISON_QUEUES: Mapping[Stage, QueueName] = {
    Stage.QUALITY: QueueName.QUALITY_POISON,
    Stage.EXTRACT: QueueName.EXTRACT_POISON,
    Stage.VALIDATE: QueueName.VALIDATE_POISON,
    Stage.POST: QueueName.POST_POISON,
}


class QueueSender(Protocol):
    """Sends a `QueueMessage` to a stage queue."""

    async def send(
        self, queue: QueueName, message: QueueMessage, *, delay_seconds: int = 0
    ) -> None:
        """Enqueue `message`, invisible for `delay_seconds` (AD-3 backoff, AD-7 waits)."""
        ...
