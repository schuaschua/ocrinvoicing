"""The `analytics` schema (AD-13): written by the analytics refresh job only, read by
staff-api's dashboards. Story 4.2 adds the overdue list (CAP-12).

Every method raises `DatabaseOfflineError` (domain/errors.py) when the database can't
be reached at all (AD-7); a failing query raises as it is."""

from collections.abc import Sequence
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


class OverdueReader(Protocol):
    """The overdue list, read-only (staff-api)."""

    async def overdue_list(self) -> OverdueList:
        """Every listed PO and the latest run's `finished_at`."""
        ...
