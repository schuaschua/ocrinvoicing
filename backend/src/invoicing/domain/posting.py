"""The posting backoff (AD-3, AD-10): how long the `post` stage waits after each
accounts failure, and when it stops retrying and routes `ACCOUNTS_API_ERROR`.

The count is `intake.invoice.post_failures`, never `QueueMessage.attempt` (which is
informational). It resets when the invoice enters `ready_to_post` from `validating` or
`in_admin_queue`, so a corrected or approved invoice starts the ladder again.
"""

from dataclasses import dataclass
from datetime import timedelta

from invoicing.domain.status import InvoiceStatus
from invoicing.domain.transitions import Transition

# AD-3: the waits after failures 1-4; the 5th failure routes to the admin queue.
POST_BACKOFF: tuple[timedelta, ...] = (
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=15),
    timedelta(minutes=60),
)
MAX_POST_FAILURES = len(POST_BACKOFF) + 1

_S = InvoiceStatus

# AD-3: the ways into `ready_to_post` that start the posting count again.
RESETS_POST_FAILURES: frozenset[tuple[InvoiceStatus, InvoiceStatus]] = frozenset(
    {(_S.VALIDATING, _S.READY_TO_POST), (_S.IN_ADMIN_QUEUE, _S.READY_TO_POST)}
)


def post_backoff(failures: int) -> timedelta | None:
    """The wait before the next try after `failures` failures in a row (this one
    included), or None when this failure is the 5th and the invoice is routed."""
    if failures < 1:
        raise ValueError("failures counts this failure, so it is at least 1")
    if failures >= MAX_POST_FAILURES:
        return None
    return POST_BACKOFF[failures - 1]


def resets_post_failures(from_status: InvoiceStatus, to_status: InvoiceStatus) -> bool:
    """Whether `from_status -> to_status` sets `post_failures` back to 0 (AD-3)."""
    return (from_status, to_status) in RESETS_POST_FAILURES


@dataclass(frozen=True)
class PostRetry:
    """A failed post that tries again: `posting -> ready_to_post`, due after `delay`
    (`next_attempt_at`), in one transaction with the count and the lease release."""

    transition: Transition
    delay: timedelta
