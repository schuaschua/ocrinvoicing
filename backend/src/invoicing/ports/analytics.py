"""The `analytics` schema (AD-13): written by the analytics refresh job only, read by
staff-api's dashboards. Story 4.2 adds the overdue list (CAP-12); Story 4.3 the
weekly supplier reminders' reads and guard (CAP-13).

Every method raises `DatabaseOfflineError` (domain/errors.py) when the database can't
be reached at all (AD-7); a failing query raises as it is."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from invoicing.ports.purchasing import OverduePo


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


class OverdueReader(Protocol):
    """The overdue list, read-only (staff-api)."""

    async def overdue_list(self) -> OverdueList:
        """Every listed PO and the latest run's `finished_at`."""
        ...
