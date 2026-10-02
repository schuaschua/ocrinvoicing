"""`DashboardReader` over PostgreSQL (Story 5.1, AD-11, AD-13, P-10): staff-api's
read-only access to the `analytics` schema, and to nothing else, so no dashboard
computes figures from the invoice tables. Each call is one read-only snapshot.
SQLAlchemy Core with bound parameters (security.md rule 21), on a worker thread
(coding-style.md rule 11).
"""

import asyncio
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Connection, Engine, func, select, union

from invoicing.adapters.postgres.engine import open_connection
from invoicing.adapters.postgres.schema import (
    alert,
    material,
    month_summary,
    price_point,
    receipt_lateness,
    supplier_month,
    supplier_month_flags,
    supplier_on_time,
    watchlist,
)
from invoicing.domain.analytics import (
    PRICE_GAP_WINDOW,
    PRICE_RISE,
    RISE_WINDOW,
    MonthSummary,
    PricePoint,
    SupplierOnTime,
    month_start,
)
from invoicing.ports.dashboards import (
    Alert,
    FinanceMonth,
    Material,
    PriceComparison,
    Scorecard,
    SupplierMonthRow,
    Watchlist,
    WatchlistRow,
)


class PostgresDashboardReader:
    """`DashboardReader`: staff-api's SELECT on `analytics`."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def _read[T, A](self, work: Callable[[Connection, A], T], argument: A) -> T:
        with open_connection(self._engine) as connection:
            connection.execution_options(
                isolation_level="REPEATABLE READ", postgresql_readonly=True
            )
            with connection.begin():
                return work(connection, argument)

    async def price_points(self, since: date) -> tuple[PricePoint, ...]:
        return await asyncio.to_thread(self._read, _price_points, since)

    async def on_time_rates(self) -> tuple[SupplierOnTime, ...]:
        return await asyncio.to_thread(self._read, _on_time_rates, None)

    async def supplier_months(self, since: date) -> tuple[SupplierMonthRow, ...]:
        # Months are stored as their first day: a mid-month `since` keeps its month.
        return await asyncio.to_thread(self._read, _supplier_months, month_start(since))

    async def month_summaries(self, since: date) -> tuple[MonthSummary, ...]:
        return await asyncio.to_thread(self._read, _month_summaries, month_start(since))

    async def alerts(self, since: datetime) -> tuple[Alert, ...]:
        return await asyncio.to_thread(self._read, _alerts, since)

    async def materials(self) -> tuple[Material, ...]:
        return await asyncio.to_thread(self._read, _materials, None)

    async def price_comparison(self, material_id: UUID) -> PriceComparison | None:
        return await asyncio.to_thread(self._read, _price_comparison, material_id)

    async def watchlist(self, today: date) -> Watchlist:
        return await asyncio.to_thread(self._read, _watchlist, today)

    async def scorecard(self, supplier_id: UUID, since: date) -> Scorecard:
        return await asyncio.to_thread(self._read, _scorecard, (supplier_id, since))

    async def finance_month(self, month: date | None, current: date) -> FinanceMonth:
        return await asyncio.to_thread(self._read, _finance_month, (month, current))


def _price_points(connection: Connection, since: date) -> tuple[PricePoint, ...]:
    rows = connection.execute(
        select(
            price_point.c.invoice_id,
            price_point.c.line_no,
            price_point.c.supplier_id,
            price_point.c.material_id,
            price_point.c.invoice_date,
            price_point.c.unit_price,
            price_point.c.posted_at,
        )
        .where(price_point.c.invoice_date >= since)
        .order_by(
            price_point.c.material_id,
            price_point.c.supplier_id,
            price_point.c.invoice_date,
            price_point.c.invoice_id,
            price_point.c.line_no,
        )
    ).all()
    return tuple(PricePoint(**row._asdict()) for row in rows)


def _on_time_rates(connection: Connection, _: None) -> tuple[SupplierOnTime, ...]:
    rows = connection.execute(
        select(
            supplier_on_time.c.supplier_id,
            supplier_on_time.c.receipts,
            supplier_on_time.c.on_time,
            supplier_on_time.c.on_time_rate,
            supplier_on_time.c.avg_days_late,
        ).order_by(supplier_on_time.c.supplier_id)
    ).all()
    return tuple(SupplierOnTime(**row._asdict()) for row in rows)


def _supplier_months(
    connection: Connection, since: date
) -> tuple[SupplierMonthRow, ...]:
    return _merged_months(connection, since, None)


def _merged_months(
    connection: Connection, since: date, until: date | None
) -> tuple[SupplierMonthRow, ...]:
    """Supplier months from `since` on, and before `until` when given."""
    # Spend is by posted month and flags by received month (AD-20), so either side
    # may have a supplier month the other lacks.
    spend_query = select(
        supplier_month.c.supplier_id,
        supplier_month.c.month,
        supplier_month.c.spend,
        supplier_month.c.posted_count,
    ).where(supplier_month.c.month >= since)
    flags_query = select(
        supplier_month_flags.c.supplier_id,
        supplier_month_flags.c.month,
        supplier_month_flags.c.flagged_count,
        supplier_month_flags.c.duplicate_count,
    ).where(supplier_month_flags.c.month >= since)
    if until is not None:
        spend_query = spend_query.where(supplier_month.c.month < until)
        flags_query = flags_query.where(supplier_month_flags.c.month < until)
    spend = {
        (row.supplier_id, row.month): (row.spend, row.posted_count)
        for row in connection.execute(spend_query)
    }
    flags = {
        (row.supplier_id, row.month): (row.flagged_count, row.duplicate_count)
        for row in connection.execute(flags_query)
    }
    return tuple(
        SupplierMonthRow(
            supplier_id,
            month,
            *spend.get((supplier_id, month), (Decimal("0.00"), 0)),
            *flags.get((supplier_id, month), (0, 0)),
        )
        for supplier_id, month in sorted(
            spend.keys() | flags.keys(), key=lambda key: (key[1], key[0])
        )
    )


def _month_summaries(connection: Connection, since: date) -> tuple[MonthSummary, ...]:
    rows = connection.execute(
        select(
            month_summary.c.month,
            month_summary.c.posted_count,
            month_summary.c.straight_through_count,
            month_summary.c.straight_through_share,
        )
        .where(month_summary.c.month >= since)
        .order_by(month_summary.c.month)
    ).all()
    return tuple(MonthSummary(**row._asdict()) for row in rows)


_ALERTS = select(
    alert.c.alert_id,
    alert.c.kind,
    alert.c.dedupe_key,
    alert.c.supplier_id,
    alert.c.material_id,
    alert.c.detail,
    alert.c.created_at,
    alert.c.emailed_at,
).order_by(alert.c.created_at.desc(), alert.c.alert_id)


def _alerts(connection: Connection, since: datetime) -> tuple[Alert, ...]:
    rows = connection.execute(_ALERTS.where(alert.c.created_at >= since)).all()
    return tuple(Alert(**row._asdict()) for row in rows)


def _materials(connection: Connection, _: None) -> tuple[Material, ...]:
    rows = connection.execute(
        select(material.c.material_id, material.c.name).order_by(
            material.c.name, material.c.material_id
        )
    ).all()
    return tuple(Material(**row._asdict()) for row in rows)


def _price_comparison(
    connection: Connection, material_id: UUID
) -> PriceComparison | None:
    name = connection.execute(
        select(material.c.name).where(material.c.material_id == material_id)
    ).scalar()
    if name is None:
        return None
    points = tuple(
        PricePoint(**row._asdict())
        for row in connection.execute(
            select(
                price_point.c.invoice_id,
                price_point.c.line_no,
                price_point.c.supplier_id,
                price_point.c.material_id,
                price_point.c.invoice_date,
                price_point.c.unit_price,
                price_point.c.posted_at,
            )
            .where(price_point.c.material_id == material_id)
            .order_by(
                price_point.c.supplier_id,
                price_point.c.invoice_date,
                price_point.c.invoice_id,
                price_point.c.line_no,
            )
        )
    )
    suppliers = sorted({point.supplier_id for point in points})
    rates = (
        {
            row.supplier_id: row.on_time_rate
            for row in connection.execute(
                select(
                    supplier_on_time.c.supplier_id, supplier_on_time.c.on_time_rate
                ).where(supplier_on_time.c.supplier_id.in_(suppliers))
            )
        }
        if suppliers
        else {}
    )
    alerts = tuple(
        Alert(**row._asdict())
        for row in connection.execute(
            _ALERTS.where(
                alert.c.material_id == material_id, alert.c.kind == PRICE_RISE
            )
        )
    )
    return PriceComparison(Material(material_id, name), points, rates, alerts)


def _watchlist(connection: Connection, today: date) -> Watchlist:
    rows = tuple(
        WatchlistRow(row.supplier_id, row.rule, row.first_added_on, tuple(row.evidence))
        for row in connection.execute(
            select(
                watchlist.c.supplier_id,
                watchlist.c.rule,
                watchlist.c.first_added_on,
                watchlist.c.evidence,
            ).order_by(watchlist.c.supplier_id, watchlist.c.rule)
        )
    )
    has_points = (
        connection.execute(select(price_point.c.invoice_id).limit(1)).first()
        is not None
    )
    names = {
        row.material_id: row.name
        for row in connection.execute(select(material.c.material_id, material.c.name))
    }
    # Every late line's material, not only the 20 kept as evidence (AD-20 window).
    late: dict[UUID, list[UUID]] = {}
    for row in connection.execute(
        select(receipt_lateness.c.supplier_id, receipt_lateness.c.material_id)
        .where(
            receipt_lateness.c.days_late > 0,
            receipt_lateness.c.received_date >= today - RISE_WINDOW,
        )
        .distinct()
        .order_by(receipt_lateness.c.supplier_id, receipt_lateness.c.material_id)
    ):
        late.setdefault(row.supplier_id, []).append(row.material_id)
    return Watchlist(
        rows=rows,
        points=_price_points(connection, today - PRICE_GAP_WINDOW),
        late_materials={key: tuple(value) for key, value in late.items()},
        on_time={item.supplier_id: item for item in _on_time_rates(connection, None)},
        material_names=names,
        has_price_points=has_points,
    )


def _scorecard(connection: Connection, key: tuple[UUID, date]) -> Scorecard:
    supplier_id, since = key
    on_time = connection.execute(
        select(
            supplier_on_time.c.supplier_id,
            supplier_on_time.c.receipts,
            supplier_on_time.c.on_time,
            supplier_on_time.c.on_time_rate,
            supplier_on_time.c.avg_days_late,
        ).where(supplier_on_time.c.supplier_id == supplier_id)
    ).first()
    points = tuple(
        PricePoint(**row._asdict())
        for row in connection.execute(
            select(
                price_point.c.invoice_id,
                price_point.c.line_no,
                price_point.c.supplier_id,
                price_point.c.material_id,
                price_point.c.invoice_date,
                price_point.c.unit_price,
                price_point.c.posted_at,
            )
            .where(
                price_point.c.supplier_id == supplier_id,
                price_point.c.invoice_date >= since,
            )
            # Same-day prices: the later posted is the latest (Story 5.5).
            .order_by(
                price_point.c.material_id,
                price_point.c.invoice_date,
                price_point.c.posted_at,
                price_point.c.invoice_id,
                price_point.c.line_no,
            )
        )
    )
    materials = sorted({point.material_id for point in points})
    names = (
        {
            row.material_id: row.name
            for row in connection.execute(
                select(material.c.material_id, material.c.name).where(
                    material.c.material_id.in_(materials)
                )
            )
        }
        if materials
        else {}
    )
    return Scorecard(
        on_time=None if on_time is None else SupplierOnTime(**on_time._asdict()),
        points=points,
        material_names=names,
    )


# A price rise counts in the month of its rising invoice's date (Story 5.6), held in
# the alert's evidence as YYYY-MM-DD text; a rise with any other text is skipped.
_RISE_DATE = alert.c.detail[("current", "invoice_date")].astext
_IS_RISE = (alert.c.kind == PRICE_RISE) & _RISE_DATE.regexp_match(
    r"^\d{4}-\d{2}-\d{2}$"
)
# Finance month's chart: the last 24 months, ending at the shown one.
HISTORY_MONTHS = 24


def _add_months(month: date, count: int) -> date:
    """The first day of the month `count` months after `month`'s (negative: before)."""
    index = month.year * 12 + month.month - 1 + count
    return date(index // 12, index % 12 + 1, 1)


def _finance_month(
    connection: Connection, key: tuple[date | None, date]
) -> FinanceMonth:
    requested, current = key
    # A mistyped future date never makes a month later than the current one.
    latest = month_start(current)
    stored = connection.execute(
        union(
            select(supplier_month.c.month),
            select(supplier_month_flags.c.month),
            select(month_summary.c.month),
        )
    )
    months: set[date] = {row.month for row in stored}
    for row in connection.execute(
        select(func.left(_RISE_DATE, 7).label("month")).where(_IS_RISE).distinct()
    ):
        try:
            months.add(date.fromisoformat(f"{row.month}-01"))
        except ValueError:
            continue  # e.g. month 13: not a month, so not listed
    ordered = sorted((held for held in months if held <= latest), reverse=True)
    if requested is not None:
        month = month_start(requested)
    elif ordered:
        month = ordered[0]
    else:
        month = latest
    following = _add_months(month, 1)
    rises = {
        row.supplier_id: row.rises
        for row in connection.execute(
            select(alert.c.supplier_id, func.count().label("rises"))
            .where(
                _IS_RISE,
                _RISE_DATE >= month.isoformat(),
                _RISE_DATE < following.isoformat(),
            )
            .group_by(alert.c.supplier_id)
        )
    }
    history = tuple(
        item
        for item in _month_summaries(connection, _add_months(month, 1 - HISTORY_MONTHS))
        if item.month <= month
    )
    return FinanceMonth(
        month=month,
        months=tuple(ordered),
        suppliers=_merged_months(connection, month, following),
        price_rises=rises,
        summary=next((item for item in history if item.month == month), None),
        history=history,
    )
