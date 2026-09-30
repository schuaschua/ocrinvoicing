"""The analytics refresh job (AD-13): a `pipeline` timer on weekdays at 01:30, 04:30
and 08:30 UTC, the only writer of the `analytics` schema. Story 4.2 gives it the
overdue list (CAP-12); Stories 4.3 and 5.x add their work to the same run.

Each run takes today's Singapore date from the clock. At the first run of that date
that finds the database up, it reads `PurchasingPort.list_overdue_pos(today)` (the
purchasing adapter is the only reader of purchasing data, AD-10) and rebuilds
`analytics.overdue_po` from it in one transaction, dropping every PO a non-`rejected`
invoice has as its `po_number`, and records the day's run. A later run of the same
date changes nothing. No watermark is needed: each run recomputes from purchasing as
of today, so a missed day or a weekend is covered by the next run.

A stopped database (AD-7) is logged as `analytics_refresh.skipped code=DB_OFFLINE`,
and the next run catches up. A run that fails otherwise leaves the previous list and
its date, and raises, so the host logs it; the next run retries.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from invoicing.adapters.logging import log_event
from invoicing.domain.dates import singapore_date
from invoicing.domain.errors import DatabaseOfflineError
from invoicing.ports.analytics import AnalyticsStore
from invoicing.ports.purchasing import PurchasingPort

# NCRONTAB (seconds first), UTC: 01:30, 04:30 and 08:30, Monday to Friday (AD-13).
REFRESH_SCHEDULE = "0 30 1,4,8 * * 1-5"

# What a run did: made the day's list, found it already made, or found no database.
REFRESHED = "refreshed"
ALREADY_RAN = "already_ran"
DB_OFFLINE = "DB_OFFLINE"

_logger = logging.getLogger("invoicing.pipeline.analytics_refresh")


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class AnalyticsRefresh:
    """The job and its dependencies; `run` is the timer's body. `clock` is the
    current UTC time, injected so tests move it instead of waiting."""

    purchasing: PurchasingPort
    store: AnalyticsStore
    clock: Callable[[], datetime] = field(default=_now)

    async def run(self) -> str:
        """One run: `refreshed`, `already_ran` or `DB_OFFLINE`."""
        today = singapore_date(self.clock())
        try:
            # Read before the writing transaction; the adapter opens its own
            # connection (AD-10).
            pos = await self.purchasing.list_overdue_pos(today)
            made = await self.store.refresh_overdue(today, pos, self.clock())
        except DatabaseOfflineError:
            log_event(
                _logger,
                "analytics_refresh.skipped",
                level=logging.WARNING,
                code=DB_OFFLINE,
            )
            return DB_OFFLINE
        code = REFRESHED if made else ALREADY_RAN
        log_event(_logger, "analytics_refresh.done", code=code)
        return code
