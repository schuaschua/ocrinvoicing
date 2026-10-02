"""The only email sender (Story 5.2, AD-16): Azure Communication Services Email, from
the verified custom domain's sender address, signed in with the app's managed
identity (no connection string or key exists).

- `AcsEmail` sends one message per 49 recipients (ACS takes 50 per message): the
  recipients in bcc and the sender itself as the only `to`, so staff never see each
  other's addresses. It waits at most 60 s for ACS to accept each and raises unless
  the status is `Succeeded`; ACS's 429 becomes `EmailThrottledError` (stop for now).
  ACS's text is never logged (the caller logs the error's type only).
- `SendThrottle` keeps the environment under ACS's custom-domain limits (30 a
  minute, 100 an hour, per subscription, shared by Dev and Prod): Dev at most 5 a
  minute and 20 an hour, Prod 25 and 80; `local` runs use Dev's. It counts
  successful sends only, in-process, with no shared state (no table, no blob): the
  pipeline runs one instance (AD-17). When the minute is full it says how long to
  wait; when the hour is, the dispatch stops until its next run.
- `ThrottledEmail` puts the two together as one `EmailPort`.

Time comes from an injected clock, so tests move it instead of sleeping. Delivery is
at least once (`ports/email.py`).
"""

import asyncio
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from azure.communication.email.aio import EmailClient
from azure.core.credentials_async import AsyncTokenCredential
from azure.core.exceptions import HttpResponseError

from invoicing.ports.email import EmailPort, EmailThrottledError

MINUTE = timedelta(minutes=1)
HOUR = timedelta(hours=1)


@dataclass(frozen=True)
class SendLimits:
    """At most `per_minute` sends in any minute and `per_hour` in any hour."""

    per_minute: int
    per_hour: int


# Story 5.2: Dev and Prod together stay under ACS's 30 a minute and 100 an hour.
DEV_LIMITS = SendLimits(per_minute=5, per_hour=20)
PROD_LIMITS = SendLimits(per_minute=25, per_hour=80)


def limits_for(app_environment: str) -> SendLimits:
    """The environment's limits: Prod's in `prod`, Dev's otherwise (`dev`, `local`)."""
    return PROD_LIMITS if app_environment == "prod" else DEV_LIMITS


def _now() -> datetime:
    return datetime.now(UTC)


class SendThrottle:
    """Sliding one-minute and one-hour windows over this process's successful
    sends."""

    def __init__(
        self, limits: SendLimits, clock: Callable[[], datetime] = _now
    ) -> None:
        self.limits = limits
        self._clock = clock
        self._sent: deque[datetime] = deque()

    def acquire(self) -> datetime:
        """Count one send now and return its slot; `EmailThrottledError` (nothing
        counted) when the minute's limit is reached, with the seconds until the
        minute's window has room, or when the hour's is, with no retry time."""
        now = self._clock()
        while self._sent and now - self._sent[0] >= HOUR:
            self._sent.popleft()
        if len(self._sent) >= self.limits.per_hour:
            raise EmailThrottledError(retry_after=None)
        last_minute = [at for at in self._sent if now - at < MINUTE]
        if len(last_minute) >= self.limits.per_minute:
            wait = last_minute[-self.limits.per_minute] + MINUTE - now
            raise EmailThrottledError(retry_after=max(wait.total_seconds(), 0.0))
        self._sent.append(now)
        return now

    def try_acquire(self) -> bool:
        """`acquire` as a yes or no."""
        try:
            self.acquire()
        except EmailThrottledError:
            return False
        return True

    def release(self, slot: datetime) -> None:
        """Give back a slot whose send failed: only successful sends count."""
        try:
            self._sent.remove(slot)
        except ValueError:
            return


# ACS takes at most 50 recipients per message: the sender (the only `to`) plus 49.
MAX_BCC = 49
# How long to wait for ACS to accept one message.
SEND_TIMEOUT_SECONDS = 60


class EmailSendError(RuntimeError):
    """ACS didn't confirm a message as sent (its status, never its text)."""


def acs_message(
    sender: str, bcc: Sequence[str], subject: str, text: str, html: str
) -> dict[str, Any]:
    """The ACS message: the sender as the only `to`, the recipients in bcc, so no
    recipient sees the others."""
    return {
        "senderAddress": sender,
        "recipients": {
            "to": [{"address": sender}],
            "bcc": [{"address": address} for address in bcc],
        },
        "content": {"subject": subject, "plainText": text, "html": html},
    }


class AcsEmail:
    """`EmailPort` over ACS Email (AD-16): the only code that sends mail. One
    client for the process, made at the first send."""

    def __init__(
        self, endpoint: str, sender_address: str, credential: AsyncTokenCredential
    ) -> None:
        self._endpoint = endpoint
        self._sender = sender_address
        self._credential = credential
        self._client: EmailClient | None = None

    async def send(self, to: Sequence[str], subject: str, text: str, html: str) -> None:
        if self._client is None:
            self._client = EmailClient(self._endpoint, self._credential)
        for start in range(0, len(to), MAX_BCC):
            message = acs_message(
                self._sender, to[start : start + MAX_BCC], subject, text, html
            )
            try:
                poller = await self._client.begin_send(message)
                result = await asyncio.wait_for(poller.result(), SEND_TIMEOUT_SECONDS)
            except HttpResponseError as error:
                if error.status_code == 429:
                    # ACS's own limit: stop until the next run.
                    raise EmailThrottledError(retry_after=None) from None
                raise
            status = (result or {}).get("status")
            if status != "Succeeded":
                raise EmailSendError(f"status {status}")


class ThrottledEmail:
    """An `EmailPort` that takes a `throttle` slot before each send of `inner`,
    and gives it back when the send fails."""

    def __init__(self, inner: EmailPort, throttle: SendThrottle) -> None:
        self._inner = inner
        self.throttle = throttle

    async def send(self, to: Sequence[str], subject: str, text: str, html: str) -> None:
        slot = self.throttle.acquire()
        try:
            await self._inner.send(to, subject, text, html)
        except BaseException:
            self.throttle.release(slot)
            raise
