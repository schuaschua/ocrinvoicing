"""Story 5.2 (AD-16, CAP-14, CAP-15): the analytics refresh job's alert email step.

Each run first marks every alert created over 14 days ago and not yet emailed as
emailed without sending it (`email.stale count=n`): switching emails on never mails
a backlog, as the 5.3/5.4 backfill doesn't. Then it picks the alerts not yet emailed
of the kinds that have recipients configured, oldest first, and sends one email per
alert through `EmailPort` to the union of its kind's recipient roles
(`domain/alert_email.py`), and only then sets its `emailed_at`. Nothing is ever sent
to a supplier (AD-6). Delivery is at least once: an alert whose `emailed_at` can't
be set after its send is sent again by a later run.

- Feature off (no ACS endpoint, sender or staff app URL): `email.disabled`, once per
  run, and nothing is sent or marked.
- No recipients configured for a kind: `email.no_recipients kind=…`, once per kind
  and run; its alerts wait (they aren't even read).
- An alert that can't make a correct email: `email.invalid alert_id=…`; it stays
  unsent and the others go on.
- A failed send: `email.failed code=<type>`; the alert waits for the next run. Three
  failures in a row stop the run (`email.stopped`).
- The minute's limit reached: wait for the next window (the injected sleeper), up
  to 10 minutes in all per run; the hour's limit, ACS's 429, or that wait used up:
  `email.throttled`, and the rest wait for the next run.
- `emailed_at` not set after a send: `email.mark_failed alert_id=…`, and the run
  stops.

The values (addresses, names, subjects) are never logged, only ids, kinds and codes.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from invoicing.adapters.logging import log_event
from invoicing.domain.alert_email import (
    ALERT_RECIPIENT_ROLES,
    InvalidAlertError,
    alert_email,
    alert_recipients,
)
from invoicing.domain.roles import Role
from invoicing.ports.analytics import AnalyticsStore
from invoicing.ports.email import EmailPort, EmailThrottledError

# At most this many alerts are read per run: above either environment's hourly limit.
BATCH = 100
# Alerts older than this when emails can go are history, marked without a send.
STALE_AFTER = timedelta(days=14)
# The most a run waits, in all, for the minute's send window to open.
MAX_WAIT_SECONDS = 600.0
# Failed sends in a row that stop the run (ACS is down, or the role is missing).
MAX_CONSECUTIVE_FAILURES = 3

_logger = logging.getLogger("invoicing.pipeline.alert_emails")


@dataclass(frozen=True)
class AlertMailConfig:
    """Where alert emails go: the recipients per role and the staff app's URL for
    the deep links. `email` is None while the feature is off. `sleep` waits for the
    throttle's next window; tests inject one that moves their clock."""

    email: EmailPort | None
    recipients: Mapping[Role, Sequence[str]]
    staff_app_base_url: str | None
    sleep: Callable[[float], Awaitable[None]] = field(default=asyncio.sleep)


async def send_alert_emails(
    store: AnalyticsStore, config: AlertMailConfig, clock: Callable[[], datetime]
) -> int:
    """Email the pending alerts; the number sent. Errors reading alerts or marking
    stale ones raise (the job's step logs them); everything else is logged here."""
    if config.email is None or not config.staff_app_base_url:
        log_event(_logger, "email.disabled")
        return 0
    stale = await store.mark_stale(clock() - STALE_AFTER, clock())
    if stale:
        log_event(_logger, "email.stale", level=logging.WARNING, count=stale)
    kinds = []
    for kind in ALERT_RECIPIENT_ROLES:
        if alert_recipients(kind, config.recipients):
            kinds.append(kind)
        else:
            log_event(_logger, "email.no_recipients", level=logging.WARNING, kind=kind)
    sent = failures = 0
    waited = 0.0
    for pending in await store.pending_alerts(kinds, BATCH):
        try:
            message = alert_email(pending, config.staff_app_base_url)
        except InvalidAlertError:
            log_event(
                _logger,
                "email.invalid",
                level=logging.ERROR,
                kind=pending.kind,
                alert_id=pending.alert_id,
            )
            continue
        to = alert_recipients(pending.kind, config.recipients)
        while True:
            try:
                await config.email.send(to, message.subject, message.text, message.html)
            except EmailThrottledError as throttled:
                wait = throttled.retry_after
                if wait is not None and waited + wait <= MAX_WAIT_SECONDS:
                    await config.sleep(wait)
                    waited += wait
                    continue
                log_event(_logger, "email.throttled", level=logging.WARNING, count=sent)
                return sent
            except Exception as error:  # noqa: BLE001  # one failed send never stops the rest
                # Only the type is logged, never ACS's text.
                log_event(
                    _logger,
                    "email.failed",
                    level=logging.ERROR,
                    code=type(error).__name__,
                    alert_id=pending.alert_id,
                )
                failures += 1
                if failures >= MAX_CONSECUTIVE_FAILURES:
                    log_event(
                        _logger, "email.stopped", level=logging.ERROR, count=failures
                    )
                    return sent
                break
            failures = 0
            try:
                await store.mark_emailed(pending.alert_id, clock())
            except Exception as error:  # noqa: BLE001  # stop; at-least-once resends it
                log_event(
                    _logger,
                    "email.mark_failed",
                    level=logging.ERROR,
                    code=type(error).__name__,
                    alert_id=pending.alert_id,
                )
                return sent
            sent += 1
            log_event(
                _logger, "email.sent", kind=pending.kind, alert_id=pending.alert_id
            )
            break
    return sent
