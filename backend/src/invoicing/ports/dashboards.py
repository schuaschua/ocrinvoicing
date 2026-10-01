"""Staff-api's dashboard data (Story 5.1, AD-13, AD-20, P-10): read-only, from the
`analytics` schema the refresh job writes, never from the invoice tables. Stories 5.3
to 5.6 add the methods their dashboards need; nothing here is served over HTTP yet.

Every method raises `DatabaseOfflineError` (domain/errors.py) when the database can't
be reached at all (AD-7); a failing query raises as it is."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from invoicing.domain.analytics import MonthSummary, PricePoint, SupplierOnTime


@dataclass(frozen=True)
class SupplierMonthRow:
    """A supplier's month: spend and posted invoices by posted month, flagged and
    duplicate invoices by received month (AD-20); zero where the month has none."""

    supplier_id: UUID
    month: date
    spend: Decimal
    posted_count: int
    flagged_count: int
    duplicate_count: int


@dataclass(frozen=True)
class Alert:
    """One `analytics.alert` (CAP-14, CAP-15); `emailed_at` is None until emailed."""

    alert_id: UUID
    kind: str
    dedupe_key: str
    supplier_id: UUID
    material_id: UUID | None
    detail: dict[str, Any]
    created_at: datetime
    emailed_at: datetime | None


class DashboardReader(Protocol):
    """The dashboards' reads of `analytics` (staff-api, SELECT only)."""

    async def price_points(self, since: date) -> tuple[PricePoint, ...]:
        """Price points with an `invoice_date` of `since` or later, by material,
        supplier, invoice date and invoice id."""
        ...

    async def on_time_rates(self) -> tuple[SupplierOnTime, ...]:
        """Each supplier's on-time rate over the last 365 days, by supplier id."""
        ...

    async def supplier_months(self, since: date) -> tuple[SupplierMonthRow, ...]:
        """Supplier months from `since`'s month on, by month then supplier id."""
        ...

    async def month_summaries(self, since: date) -> tuple[MonthSummary, ...]:
        """Straight-through shares from `since`'s month on, by month."""
        ...

    async def alerts(self, since: datetime) -> tuple[Alert, ...]:
        """Alerts created at `since` or later, newest first."""
        ...
