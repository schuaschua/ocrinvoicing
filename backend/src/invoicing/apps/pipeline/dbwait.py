"""AD-7: every `pipeline` queue consumer waits out a stopped database instead of
failing.

A consumer that can't connect to PostgreSQL sends the same message (same
`invoice_id`, `correlation_id`, `first_enqueued_at` and `attempt`) back to its own
queue, invisible for 15 minutes, and then completes the original normally, so the
host's dequeue count (`maxDequeueCount` 5) is not used up while Dj has the server
stopped (AD-12). The wait is bounded: a stopped server restarts itself after 7 days,
so a message first enqueued more than 8 days ago is not waiting for a stop but for a
permanent fault (a revoked login, a wrong host). It stops waiting, logs
`DB_WAIT_EXPIRED` and raises, so the host retries it and then poisons it. Poison
triggers follow the same rule, so no message is dropped.
"""

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Concatenate

from pydantic import ValidationError

from invoicing.adapters.logging import log_event
from invoicing.domain.errors import DatabaseOfflineError
from invoicing.ports.messages import QueueMessage
from invoicing.ports.queue import QueueName, QueueSender

# AD-7: how long a message waits before it tries the database again.
DB_WAIT_SECONDS = 15 * 60
# Longer than the 7 days after which a stopped server restarts itself (AD-7).
DB_WAIT_LIMIT = timedelta(days=8)

_logger = logging.getLogger("invoicing.pipeline.dbwait")


def _now() -> datetime:
    return datetime.now(UTC)


def wait_for_database[**P, T](
    queue: QueueName,
    sender: QueueSender,
    handler: Callable[Concatenate[str | bytes, P], Awaitable[T]],
    clock: Callable[[], datetime] = _now,
) -> Callable[Concatenate[str | bytes, P], Awaitable[T | None]]:
    """`handler` for messages from `queue` (any further arguments, such as the dequeue
    count, are passed through); when it raises `DatabaseOfflineError`, the message
    goes back to `queue` with a 15-minute delay and None is returned, so the host
    completes the original. A failed re-enqueue, or a wait past `DB_WAIT_LIMIT`, is
    raised, so the host retries the original instead of losing it."""

    async def handle(body: str | bytes, *args: P.args, **kwargs: P.kwargs) -> T | None:
        try:
            return await handler(body, *args, **kwargs)
        except DatabaseOfflineError:
            try:
                message = QueueMessage.from_json(body)
            except ValidationError:
                # Only a parsed message reaches the database, so this is a handler
                # bug: raise the original error for a retry.
                raise DatabaseOfflineError() from None
            if clock() - message.first_enqueued_at > DB_WAIT_LIMIT:
                log_event(
                    _logger,
                    "pipeline.db_wait",
                    level=logging.ERROR,
                    code="DB_WAIT_EXPIRED",
                    queue=queue,
                    invoice_id=message.invoice_id,
                    correlation_id=message.correlation_id,
                    attempt=message.attempt,
                )
                raise
            # The same message: its ids, first enqueue time and attempt are kept.
            await sender.send(queue, message, delay_seconds=DB_WAIT_SECONDS)
            log_event(
                _logger,
                "pipeline.db_wait",
                level=logging.WARNING,
                code="DB_OFFLINE",
                queue=queue,
                invoice_id=message.invoice_id,
                correlation_id=message.correlation_id,
                attempt=message.attempt,
            )
            return None

    return handle
