"""Staff-api's dashboard data (Story 5.1, AD-13, AD-20, P-10): read-only, from the
`analytics` schema the refresh job writes, never from the invoice tables. Stories 5.3
to 5.6 add the methods their dashboards need; Story 5.3 serves Price comparison and
Story 5.4 the Watchlist.

Every method raises `DatabaseOfflineError` (domain/errors.py) when the database can't
be reached at all (AD-7); a failing query raises as it is."""

from collections.abc import Mapping
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


@dataclass(frozen=True)
class Material:
    """A material with price points, named from purchasing (`analytics.material`)."""

    material_id: UUID
    name: str


@dataclass(frozen=True)
class PriceComparison:
    """Everything Price comparison shows for one material (Story 5.3, CAP-14): its
    price points (by supplier, invoice date, invoice id and line), the on-time rate of
    each of its suppliers that has one, and its price-rise alerts, newest first."""

    material: Material
    points: tuple[PricePoint, ...]
    on_time_rates: Mapping[UUID, Decimal]
    alerts: tuple[Alert, ...]


@dataclass(frozen=True)
class WatchlistRow:
    """One `analytics.watchlist` row: a supplier listed under an AD-20 rule."""

    supplier_id: UUID
    rule: str
    first_added_on: date
    evidence: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class Watchlist:
    """Everything the Watchlist shows (Story 5.4, CAP-15, CAP-16), in one snapshot:
    the rows, the price points of the last 90 days the alternatives are ranked from,
    the materials of each supplier's late receipt lines of the last 365 days (by
    material id), every supplier's on-time rate and average days late, the material
    names, and whether any price point exists at all."""

    rows: tuple[WatchlistRow, ...]
    points: tuple[PricePoint, ...]
    late_materials: Mapping[UUID, tuple[UUID, ...]]
    on_time: Mapping[UUID, SupplierOnTime]
    material_names: Mapping[UUID, str]
    has_price_points: bool


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

    async def materials(self) -> tuple[Material, ...]:
        """Every material with price points, by name (Story 5.3)."""
        ...

    async def price_comparison(self, material_id: UUID) -> PriceComparison | None:
        """`material_id`'s price comparison in one snapshot, or None when it is not a
        material with price points (Story 5.3)."""
        ...

    async def watchlist(self, today: date) -> Watchlist:
        """The watchlist on the Singapore date `today` (Story 5.4)."""
        ...
