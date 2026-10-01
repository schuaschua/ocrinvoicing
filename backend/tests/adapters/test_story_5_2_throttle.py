"""Story 5.2: the email send throttle (AD-16). Pure: the clock is injected and moved,
never waited on (coding-style.md rule 23). One merged test (the 200-case cap,
coding-style.md rule 20 exception)."""

from datetime import UTC, datetime, timedelta

import pytest

from invoicing.adapters.email import (
    DEV_LIMITS,
    MAX_BCC,
    PROD_LIMITS,
    SendLimits,
    SendThrottle,
    acs_message,
    limits_for,
)
from invoicing.ports.email import EmailThrottledError


def test_story_5_2_throttle() -> None:
    """Dev 5 a minute and 20 an hour, Prod 25 and 80, local as Dev; a refused send
    counts nothing and says how long to wait (the minute) or to stop (the hour); a
    released (failed) send counts nothing; both windows slide with the clock. The
    ACS message: the sender the only `to`, the recipients in bcc, at most 49."""
    assert DEV_LIMITS == SendLimits(per_minute=5, per_hour=20)
    assert PROD_LIMITS == SendLimits(per_minute=25, per_hour=80)
    assert limits_for("dev") == limits_for("local") == DEV_LIMITS
    assert limits_for("prod") == PROD_LIMITS

    now = [datetime(2026, 10, 1, 1, 30, tzinfo=UTC)]
    throttle = SendThrottle(DEV_LIMITS, clock=lambda: now[0])

    def burst() -> int:
        sent = 0
        while throttle.try_acquire():
            sent += 1
        return sent

    # Throttled: 7 pending in one minute, 5 go and the rest wait.
    assert burst() == 5
    with pytest.raises(EmailThrottledError) as minute:
        throttle.acquire()
    assert minute.value.retry_after == 60
    now[0] += timedelta(seconds=59)
    assert burst() == 0
    # The next minute takes 5 more, up to 20 in the hour.
    for _ in range(3):
        now[0] += timedelta(minutes=1)
        assert burst() == 5
    # Hourly cap: 20 sent this hour, none more until the hour rolls.
    now[0] += timedelta(minutes=10)
    assert burst() == 0
    with pytest.raises(EmailThrottledError) as hour:
        throttle.acquire()
    assert hour.value.retry_after is None
    # An hour after the first 5 they no longer count.
    now[0] = datetime(2026, 10, 1, 2, 30, tzinfo=UTC)
    assert burst() == 5

    # Prod: 25 a minute, 80 an hour.
    prod = SendThrottle(PROD_LIMITS, clock=lambda: now[0])
    sent = 0
    for minute in range(5):
        now[0] += timedelta(minutes=1)
        while prod.try_acquire():
            sent += 1
        assert sent == min(25 * (minute + 1), 80)

    # A failed send gives its slot back: only successful sends count.
    fresh = SendThrottle(DEV_LIMITS, clock=lambda: now[0])
    fresh.release(fresh.acquire())
    assert sum(fresh.try_acquire() for _ in range(6)) == 5

    # The message ACS gets.
    assert acs_message(
        "alerts@alerts.example.test",
        ["a@example.test", "b@example.test"],
        "S",
        "T",
        "<p>H</p>",
    ) == {
        "senderAddress": "alerts@alerts.example.test",
        "recipients": {
            "to": [{"address": "alerts@alerts.example.test"}],
            "bcc": [{"address": "a@example.test"}, {"address": "b@example.test"}],
        },
        "content": {"subject": "S", "plainText": "T", "html": "<p>H</p>"},
    }
    assert MAX_BCC == 49
