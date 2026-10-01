"""The `analytics` schema (AD-13): written by the analytics refresh job only, read by
staff-api's dashboards. Story 4.2 adds the overdue list (CAP-12); Story 4.3 the
weekly supplier reminders' reads and guard (CAP-13); Story 5.1 the daily summary
tables (AD-20), which staff-api reads through `ports/dashboards.py`; Story 5.3 the
material names; Story 5.2 the alerts still to email and their `emailed_at`.

Every method raises `DatabaseOfflineError` (domain/errors.py) when the database can't
be reached at all (AD-7); a failing query raises as it is."""

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol
from uuid import UUID

from invoicing.domain.alert_email import PendingAlert
from invoicing.ports.purchasing import OverduePo, ReceiptLine


@dataclass(frozen=True)
class OverdueList:
    """The overdue list as last made: its POs, and when the run that made it
    finished (None when no run has made it yet)."""

    made_at: datetime | None
    pos: tuple[OverduePo, ...]


class AnalyticsStore(Protocol):
    """The analytics refresh job's writes (the pipeline login)."""

    async def refresh_overdue(
        self, run_date: date, pos: Sequence[OverduePo], finished_at: datetime
    ) -> bool:
        """In one transaction, under one lock: replace the overdue list with `pos`
        minus every PO a non-`rejected` invoice has as its `po_number`, and record
        `run_date`'s run. False, with nothing written, when `run_date` already ran."""
        ...

    async def overdue_pos(self) -> list[OverduePo]:
        """The overdue list as last made (Story 4.3 reads it, never purchasing)."""
        ...

    async def invoiced(self, po_numbers: Iterable[str]) -> set[str]:
        """Those of `po_numbers` a non-`rejected` invoice has as its `po_number` now
        (the overdue rebuild's rule, AD-13)."""
        ...

    async def reminders_done(self, week: date) -> bool:
        """Whether the supplier reminders of the ISO week starting Monday `week` were
        written."""
        ...

    async def record_reminders(self, week: date, finished_at: datetime) -> None:
        """Record the week's reminders as written; recording it twice is fine."""
        ...

    async def summaries_done(self, run_date: date) -> bool:
        """Whether `run_date`'s summaries were written (Story 5.1)."""
        ...

    async def refresh_summaries(
        self, run_date: date, receipts: Sequence[ReceiptLine], finished_at: datetime
    ) -> bool:
        """In one transaction, under one lock (Story 5.1, AD-20): rewrite the price
        points and facts of every invoice posted after the watermark minus 1 hour,
        move the watermark on, recompute the other summary tables in full (lateness
        from `receipts`), and record `run_date`'s run. False, with nothing written,
        when `run_date` already ran."""
        ...

    async def priced_materials(self) -> set[UUID]:
        """Every material with a price point (Story 5.3)."""
        ...

    async def replace_materials(self, names: Mapping[UUID, str]) -> None:
        """Replace `analytics.material` with `names` in one transaction (Story 5.3)."""
        ...

    async def pending_alerts(
        self, kinds: Collection[str], limit: int
    ) -> list[PendingAlert]:
        """Story 5.2: up to `limit` alerts of `kinds` with no `emailed_at` and not
        backfilled, oldest first, with the supplier's name from master and the names
        of the materials in `analytics.material`. A row whose detail isn't a JSON
        object reads as an empty detail (the email step then skips it)."""
        ...

    async def mark_emailed(self, alert_id: UUID, at: datetime) -> None:
        """Story 5.2: set the alert's `emailed_at` (the only column the pipeline
        login may update), unless it is set already. Called only after the send
        succeeded, so delivery is at least once."""
        ...

    async def mark_stale(self, created_before: datetime, at: datetime) -> int:
        """Story 5.2: set `emailed_at` on every alert not yet emailed that was
        created before `created_before`, without sending it; the number marked."""
        ...


class OverdueReader(Protocol):
    """The overdue list, read-only (staff-api)."""

    async def overdue_list(self) -> OverdueList:
        """Every listed PO and the latest run's `finished_at`."""
        ...
