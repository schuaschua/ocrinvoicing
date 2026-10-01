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

from sqlalchemy import Connection, Engine, select

from invoicing.adapters.postgres.engine import open_connection
from invoicing.adapters.postgres.schema import (
    alert,
    month_summary,
    price_point,
    supplier_month,
    supplier_month_flags,
    supplier_on_time,
)
from invoicing.domain.analytics import (
    MonthSummary,
    PricePoint,
    SupplierOnTime,
    month_start,
)
from invoicing.ports.dashboards import Alert, SupplierMonthRow


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
    # Spend is by posted month and flags by received month (AD-20), so either side
    # may have a supplier month the other lacks.
    spend = {
        (row.supplier_id, row.month): (row.spend, row.posted_count)
        for row in connection.execute(
            select(
                supplier_month.c.supplier_id,
                supplier_month.c.month,
                supplier_month.c.spend,
                supplier_month.c.posted_count,
            ).where(supplier_month.c.month >= since)
        )
    }
    flags = {
        (row.supplier_id, row.month): (row.flagged_count, row.duplicate_count)
        for row in connection.execute(
            select(
                supplier_month_flags.c.supplier_id,
                supplier_month_flags.c.month,
                supplier_month_flags.c.flagged_count,
                supplier_month_flags.c.duplicate_count,
            ).where(supplier_month_flags.c.month >= since)
        )
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


def _alerts(connection: Connection, since: datetime) -> tuple[Alert, ...]:
    rows = connection.execute(
        select(
            alert.c.alert_id,
            alert.c.kind,
            alert.c.dedupe_key,
            alert.c.supplier_id,
            alert.c.material_id,
            alert.c.detail,
            alert.c.created_at,
            alert.c.emailed_at,
        )
        .where(alert.c.created_at >= since)
        .order_by(alert.c.created_at.desc(), alert.c.alert_id)
    ).all()
    return tuple(Alert(**row._asdict()) for row in rows)
