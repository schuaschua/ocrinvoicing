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

Story 4.3 (CAP-13, FR13) adds a weekly step after it, whether the day's list was just
made or already made: at the first run of each ISO week (Singapore date) that gets
through, it replaces the `supplierreminders` table with one row per listed PO,
re-checking just before the write that no non-`rejected` invoice now has the PO, and
then records the week under its Monday in `analytics.job_run`. A failed Table write
leaves the week unrecorded, logged as `analytics_refresh.reminders_failed`, and the
next run retries all of it. No supplier is ever emailed or sent anything.

Story 5.1 (AD-20) adds a daily summary step after those, again whether the day's list
was just made or already made: at the first run of each Singapore date that gets
through, it reads the last 365 days of goods-receipt lines through
`PurchasingPort.receipt_lines` (never SQL on purchasing, AD-10) and, in one
transaction, rewrites the price points and facts of the invoices posted since its
watermark (minus 1 hour), recomputes the other summary tables, and records the day
under job `summaries`. A failure is logged as `analytics_refresh.summaries_failed`
and leaves the day unrecorded, so the next run retries it; the run's result stays the
overdue step's.

A stopped database (AD-7) is logged as `analytics_refresh.skipped code=DB_OFFLINE`,
and the next run catches up. A run whose overdue step fails otherwise logs
`analytics_refresh.overdue_failed`, leaves the previous list and its date, still
runs the weekly and summary steps, and then raises, so the host logs it; the next
run retries.
"""

import logging
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from invoicing.adapters.logging import log_event
from invoicing.domain.dates import singapore_date
from invoicing.domain.errors import DatabaseOfflineError, ServiceUnavailableError
from invoicing.ports.analytics import AnalyticsStore
from invoicing.ports.purchasing import PurchasingPort
from invoicing.ports.reminders import ReminderWriter

# NCRONTAB (seconds first), UTC: 01:30, 04:30 and 08:30, Monday to Friday (AD-13).
REFRESH_SCHEDULE = "0 30 1,4,8 * * 1-5"

# AD-20: lateness and on-time rates cover the last 365 days, today included, so the
# earliest received date counted is today minus 364.
LATENESS_WINDOW = timedelta(days=364)

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
    reminders: ReminderWriter
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
        except Exception as error:
            # A failed overdue list never stops the other steps; the host still
            # records the failure. Only the type is logged, never the text.
            log_event(
                _logger,
                "analytics_refresh.overdue_failed",
                level=logging.ERROR,
                code=type(error).__name__,
            )
            await self._weekly_reminders(today)
            await self._daily_summaries(today)
            raise
        code = REFRESHED if made else ALREADY_RAN
        log_event(_logger, "analytics_refresh.done", code=code)
        # On its own: a failed week never changes the day's result.
        await self._weekly_reminders(today)
        # Likewise: a failed summary never changes the day's result.
        await self._daily_summaries(today)
        return code

    async def _weekly_reminders(self, today: date) -> None:
        """Story 4.3: the week's supplier reminders, once per ISO week. Any failure
        is logged as `analytics_refresh.reminders_failed` and leaves the week
        unrecorded, so the next run retries it."""
        week = today - timedelta(days=today.weekday())
        try:
            written = await self._write_week(week)
        except DatabaseOfflineError:
            code: str = DB_OFFLINE
        except ServiceUnavailableError as error:
            code = error.code
        except Exception as error:  # noqa: BLE001  # a failed week never fails the run
            # Only the type is logged, never the text.
            code = type(error).__name__
        else:
            if written is not None:
                log_event(_logger, "analytics_refresh.reminders_done", count=written)
            return
        log_event(
            _logger,
            "analytics_refresh.reminders_failed",
            level=logging.ERROR,
            code=code,
        )

    async def _daily_summaries(self, today: date) -> None:
        """Story 5.1: the summary tables, once per Singapore date. Any failure is
        logged as `analytics_refresh.summaries_failed` and leaves the day
        unrecorded, so the next run retries it."""
        try:
            written = await self._write_summaries(today)
        except DatabaseOfflineError:
            code: str = DB_OFFLINE
        except ServiceUnavailableError as error:
            code = error.code
        except Exception as error:  # noqa: BLE001  # a failed summary never fails the run
            # Only the type is logged, never the text.
            code = type(error).__name__
        else:
            if written:
                log_event(_logger, "analytics_refresh.summaries_done")
            return
        log_event(
            _logger,
            "analytics_refresh.summaries_failed",
            level=logging.ERROR,
            code=code,
        )

    async def _write_summaries(self, today: date) -> bool:
        """Write and record the day's summaries; False when they were already."""
        if await self.store.summaries_done(today):
            return False
        # Read before the writing transaction, like the overdue list (AD-10).
        receipts = await self.purchasing.receipt_lines(today - LATENESS_WINDOW)
        return await self.store.refresh_summaries(today, receipts, self.clock())

    async def _write_week(self, week: date) -> int | None:
        """Write and record the week; None when it was already written."""
        if await self.store.reminders_done(week):
            return None
        # The list this run (or an earlier one today) made, so the reminders and the
        # Overdue POs page agree; never purchasing again.
        rows: dict[UUID, list[str]] = defaultdict(list)
        for po in await self.store.overdue_pos():
            rows[po.supplier_id].append(po.po_number)

        async def still_owed(po_numbers: Sequence[str]) -> set[str]:
            # AD-13: called by the Table writer just before each supplier's write.
            return set(po_numbers) - await self.store.invoiced(po_numbers)

        written = await self.reminders.replace_all(rows, still_owed)
        # Only after every write succeeded, so a failed week retries at the next run.
        await self.store.record_reminders(week, self.clock())
        return written
