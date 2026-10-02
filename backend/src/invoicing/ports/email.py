"""Outgoing email (AD-16, Story 5.2): staff alert emails only, never to suppliers
(AD-6). `adapters/email.py` is the only implementation and the only code that sends
mail.

Delivery is at least once: an alert is marked emailed only after its send succeeded,
so a failure to mark it (or a crash in between) sends it again on the next run."""

from collections.abc import Sequence
from typing import Protocol


class EmailThrottledError(RuntimeError):
    """The send limit is reached for now (Story 5.2): nothing was sent.
    `retry_after` is the seconds until a send may go (the minute's window), or None
    when the caller should stop until its next run (the hour's cap, or ACS's 429)."""

    def __init__(self, retry_after: float | None = None) -> None:
        super().__init__("send limit reached")
        self.retry_after = retry_after


class EmailPort(Protocol):
    """Sends one email."""

    async def send(self, to: Sequence[str], subject: str, text: str, html: str) -> None:
        """Send one email to `to`. The adapter puts the recipients in bcc and
        addresses the message to its own sender address, so no recipient sees the
        others. Raises `EmailThrottledError` when the send limit is reached (nothing
        sent); any other error means it was not confirmed as sent."""
        ...
