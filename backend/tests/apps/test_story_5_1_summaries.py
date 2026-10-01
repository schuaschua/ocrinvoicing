"""Story 5.1: the analytics refresh job's daily summary tables (AD-13, AD-20) and
staff-api's read-only dashboard repository. Purchasing is the seeded simulation read
through its adapter, `intake` and `analytics` a real PostgreSQL 18; the job writes as
the pipeline login and the dashboards read as staff-api's (so the tests also prove
the grants). The clock is injected, never waited on (coding-style.md rule 23).
Synthetic data only (security.md rule 1).

Two merged tests (the 200-case cap, coding-style.md rule 20 exception): each plan
matrix row is a block of assertions, in order."""

import asyncio
import logging
from collections.abc import Iterator, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, Table, create_engine, insert, text

import invoicing.adapters.postgres.dashboards as dashboards_module
from apps._pipeline_fakes import FakeReminders
from apps.test_story_4_2_overdue import SUPPLIER_BETA
from conftest import PostgresServer, login_engine
from contracts.purchasing_contract import CEMENT, REBAR, SUPPLIER_ALPHA
from invoicing.adapters.postgres.analytics import PostgresAnalyticsStore
from invoicing.adapters.postgres.dashboards import PostgresDashboardReader
from invoicing.adapters.postgres.schema import (
    admin_item,
    analytics_metadata,
    extraction_run,
    invoice,
    invoice_field,
    invoice_line,
    status_history,
)
from invoicing.adapters.purchasing_factory import purchasing_port
from invoicing.apps.pipeline.analytics_refresh import AnalyticsRefresh
from invoicing.domain.analytics import MonthSummary, SupplierOnTime
from invoicing.ports.dashboards import SupplierMonthRow
from invoicing.ports.purchasing import PurchasingPort

SUPPLIER_GAMMA = UUID("01a0c450-73d0-7ee3-94ca-ef9fef9d793d")
# Story 5.1's own synthetic purchasing rows (removed again after the test).
SUPPLIER_LATE = UUID("0192f0c1-7a2b-7c3d-8e4f-0000000005a1")
SUPPLIER_OLD = UUID("0192f0c1-7a2b-7c3d-8e4f-0000000005a2")


def _at(month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=UTC)


@pytest.fixture
def owner(postgres_server: PostgresServer, purchasing_seeded: str) -> Iterator[Engine]:
    """The deployer, which owns the schemas: seeds `intake` and empties `analytics`."""
    engine = create_engine(
        postgres_server.url(postgres_server.deployer, purchasing_seeded)
    )
    names = ", ".join(analytics_metadata.tables)
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {names}"))
    yield engine
    engine.dispose()


@pytest.fixture
def staff(postgres_server: PostgresServer, purchasing_seeded: str) -> Iterator[Engine]:
    engine = login_engine(postgres_server, postgres_server.staff_api, purchasing_seeded)
    yield engine
    engine.dispose()


def _invoice(
    owner: Engine,
    supplier_id: UUID,
    *,
    created_at: datetime,
    posted_at: datetime | None = None,
    status: str = "posted",
    invoice_date: tuple[str, Any] | None = None,
    total: str | None = None,
    lines: Sequence[tuple[UUID | None, str]] = (),
    admin_reasons: Sequence[str] = (),
) -> tuple[UUID, UUID]:
    """An invoice with one extraction run, as the stages leave it; `lines` are
    (material_id, unit_price). Routed through the admin queue when it has reasons.
    Returns (invoice id, run id)."""
    invoice_id, run_id = uuid4(), uuid4()
    with owner.begin() as connection:
        connection.execute(
            insert(invoice).values(
                id=invoice_id,
                correlation_id=uuid4(),
                source="link",
                supplier_id=supplier_id,
                content_type="image/jpeg",
                device_check="passed",
                status=status,
                status_changed_at=created_at,
                post_failures=0,
                posted_at=posted_at,
                created_at=created_at,
            )
        )
        path = ["received", "awaiting_validation"]
        path += ["in_admin_queue", "ready_to_post"] if admin_reasons else []
        path += ["posting", "posted"] if posted_at else []
        for before, after in zip([None, *path], path, strict=False):
            connection.execute(
                insert(status_history).values(
                    id=uuid4(),
                    invoice_id=invoice_id,
                    from_status=before,
                    to_status=after,
                    actor="test",
                    at=created_at,
                )
            )
        for reason in admin_reasons:
            connection.execute(
                insert(admin_item).values(
                    id=uuid4(),
                    invoice_id=invoice_id,
                    routing_id=invoice_id,
                    reason=reason,
                    field_ids=[],
                    detail={},
                    created_at=created_at,
                )
            )
        connection.execute(
            insert(extraction_run).values(
                run_id=run_id,
                invoice_id=invoice_id,
                model_id="prebuilt-invoice",
                api_version="2024-11-30",
                pages=1,
                created_at=created_at,
            )
        )
        fields: list[dict[str, Any]] = []
        if invoice_date is not None:
            fields.append(
                {"field_id": "invoice_date", invoice_date[0]: invoice_date[1]}
            )
        if total is not None:
            fields.append({"field_id": "invoice_total", "value_number": Decimal(total)})
        for field in fields:
            connection.execute(
                insert(invoice_field).values(
                    id=uuid4(),
                    invoice_id=invoice_id,
                    run_id=run_id,
                    source="di",
                    confidence=0.99,
                    created_at=created_at,
                    **field,
                )
            )
    for line_no, (material_id, price) in enumerate(lines, start=1):
        _line(owner, invoice_id, run_id, line_no, material_id, price, created_at)
    return invoice_id, run_id


def _line(
    owner: Engine,
    invoice_id: UUID,
    run_id: UUID,
    line_no: int,
    material_id: UUID | None,
    price: str,
    at: datetime,
    source: str = "di",
) -> None:
    with owner.begin() as connection:
        connection.execute(
            insert(invoice_line).values(
                id=uuid4(),
                invoice_id=invoice_id,
                run_id=run_id,
                line_no=line_no,
                quantity=Decimal(1),
                unit_price=Decimal(price),
                amount=Decimal(price),
                confidence=0.99,
                material_id=material_id,
                source=source,
                created_at=at,
            )
        )


class _Broken:
    """Purchasing whose `failing` read raises: a failing step."""

    def __init__(self, real: PurchasingPort, failing: str) -> None:
        self._real, self._failing = real, failing

    def __getattr__(self, name: str) -> Any:
        if name == self._failing:

            async def fail(*args: Any) -> Any:
                raise RuntimeError("purchasing went away")

            return fail
        return getattr(self._real, name)


def _job(
    engine: Engine, at: list[datetime], purchasing: Any = None
) -> AnalyticsRefresh:
    return AnalyticsRefresh(
        purchasing or purchasing_port("sim", engine),
        PostgresAnalyticsStore(engine),
        FakeReminders(),
        clock=lambda: at[0],
    )


def _scalars(owner: Engine, sql: str) -> list[Any]:
    with owner.connect() as connection:
        return list(connection.execute(text(sql)).scalars())


def test_story_5_1_incremental_summaries(
    owner: Engine,
    staff: Engine,
    pipeline_engine: Engine,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Posted invoices from the watermark (minus 1 hour) through AD-18 current values;
    spend, straight-through share and flags recomputed in full; once a day, a failed
    step retried by the next run; read back through the dashboard repository only."""
    # inv1: through the admin queue, line 2 corrected, line 3 without a material,
    # posted 01:00 on 1 Oct in Singapore.
    inv1, run1 = _invoice(
        owner,
        SUPPLIER_ALPHA,
        created_at=_at(9, 28, 2),
        posted_at=_at(9, 30, 17),
        invoice_date=("value_date", date(2026, 9, 27)),
        total="100.00",
        lines=[(CEMENT, "10.00"), (REBAR, "5.00"), (None, "3.00")],
        admin_reasons=["PO_MISMATCH"],
    )
    _line(owner, inv1, run1, 2, REBAR, "5.50", _at(9, 29, 2), source="admin")
    # inv2: no invoice date, so its Singapore posted date counts.
    inv2, _ = _invoice(
        owner,
        SUPPLIER_ALPHA,
        created_at=_at(9, 29, 2),
        posted_at=_at(9, 30, 18),
        total="50.00",
        lines=[(CEMENT, "11.00")],
    )
    # inv3: posted in September; the date was typed by an admin.
    inv3, _ = _invoice(
        owner,
        SUPPLIER_BETA,
        created_at=_at(9, 14, 2),
        posted_at=_at(9, 15, 3),
        invoice_date=("value_text", "2026-09-14"),
        total="20.00",
        lines=[(CEMENT, "9.00")],
    )
    # inv8: a typed date that can't be read and no total: the Singapore posted date
    # (16 Sep) counts, the invoice counts as posted and adds 0.00 to spend; a zero
    # or negative price (a discount or credit) is no price point.
    inv8, _ = _invoice(
        owner,
        SUPPLIER_BETA,
        created_at=_at(9, 15, 2),
        posted_at=_at(9, 15, 17),
        invoice_date=("value_text", "14/09/2026"),
        lines=[(CEMENT, "8.00"), (REBAR, "0.00"), (CEMENT, "-2.00")],
    )
    # Never posted: a flagged duplicate counts; prices don't.
    _invoice(
        owner,
        SUPPLIER_BETA,
        created_at=_at(9, 20, 3),
        status="in_admin_queue",
        lines=[(CEMENT, "1.00")],
        admin_reasons=["DUPLICATE", "LOW_CONFIDENCE"],
    )
    _invoice(
        owner,
        SUPPLIER_ALPHA,
        created_at=_at(9, 30, 3),
        status="awaiting_validation",
        lines=[(CEMENT, "99.00")],
    )
    reader = PostgresDashboardReader(staff)
    clock = [_at(10, 1, 1, 30)]

    def prices() -> dict[tuple[UUID, int], tuple[Any, ...]]:
        return {
            (p.invoice_id, p.line_no): (
                p.supplier_id,
                p.material_id,
                p.invoice_date,
                p.unit_price,
            )
            for p in asyncio.run(reader.price_points(date(2026, 1, 1)))
        }

    def summary_days() -> list[date]:
        return _scalars(
            owner,
            "SELECT run_date FROM analytics.job_run WHERE job = 'summaries'"
            " ORDER BY run_date",
        )

    with caplog.at_level(logging.INFO):
        # --- Step fails: logged, the day unrecorded, the overdue result returned.
        broken = _Broken(purchasing_port("sim", pipeline_engine), "receipt_lines")
        assert asyncio.run(_job(pipeline_engine, clock, broken).run()) == "refreshed"
        assert "analytics_refresh.summaries_failed code=RuntimeError" in caplog.text
        assert "went away" not in caplog.text
        assert summary_days() == [] and prices() == {}

        # --- First run (the retry, after an overdue step that already ran): no
        # watermark, everything posted; the corrected line once, as corrected; no
        # price point without a material.
        clock[0] = _at(10, 1, 4, 30)
        assert asyncio.run(_job(pipeline_engine, clock).run()) == "already_ran"
        first = {
            (inv1, 1): (SUPPLIER_ALPHA, CEMENT, date(2026, 9, 27), Decimal("10.00")),
            (inv1, 2): (SUPPLIER_ALPHA, REBAR, date(2026, 9, 27), Decimal("5.50")),
            (inv2, 1): (SUPPLIER_ALPHA, CEMENT, date(2026, 10, 1), Decimal("11.00")),
            (inv3, 1): (SUPPLIER_BETA, CEMENT, date(2026, 9, 14), Decimal("9.00")),
            (inv8, 1): (SUPPLIER_BETA, CEMENT, date(2026, 9, 16), Decimal("8.00")),
        }
        assert prices() == first
        assert _scalars(owner, "SELECT posted_at FROM analytics.watermark") == [
            _at(9, 30, 18)
        ]
        assert summary_days() == [date(2026, 10, 1)]
        with owner.connect() as connection:
            fact = connection.execute(
                text(
                    "SELECT invoice_date, posted_month, total"
                    " FROM analytics.invoice_fact WHERE invoice_id = :i"
                ),
                {"i": inv8},
            ).one()
        assert tuple(fact) == (date(2026, 9, 16), date(2026, 9, 1), None)
        sep, oct_ = date(2026, 9, 1), date(2026, 10, 1)
        # --- Straight-through: one via the admin queue, one not, in October.
        assert asyncio.run(reader.month_summaries(sep)) == (
            MonthSummary(sep, 2, 2, Decimal("1.0000")),
            MonthSummary(oct_, 2, 1, Decimal("0.5000")),
        )
        # --- Flags by received month, posted or not; spend by posted month.
        zero = Decimal("0.00")
        assert asyncio.run(reader.supplier_months(sep)) == (
            SupplierMonthRow(SUPPLIER_ALPHA, sep, zero, 0, 1, 0),
            SupplierMonthRow(SUPPLIER_BETA, sep, Decimal("20.00"), 2, 1, 1),
            SupplierMonthRow(SUPPLIER_ALPHA, oct_, Decimal("150.00"), 2, 0, 0),
        )

        # --- Same day again: no work, even with a newly posted invoice.
        inv6, _ = _invoice(
            owner,
            SUPPLIER_ALPHA,
            created_at=_at(10, 1, 4),
            posted_at=_at(10, 1, 5),
            total="30.00",
            lines=[(CEMENT, "12.00")],
        )
        clock[0] = _at(10, 1, 8, 30)
        assert asyncio.run(_job(pipeline_engine, clock).run()) == "already_ran"
        assert prices() == first

    # --- Missed day, incremental, late commit, rerun: Friday has no run; Monday's
    # takes inv6 and inv7 (posted 30 minutes before the watermark, committed late),
    # reprocesses inv2 (inside the hour) without duplicating it, and leaves inv3
    # (changed since, but long before the watermark) as it was.
    inv7, _ = _invoice(
        owner,
        SUPPLIER_ALPHA,
        created_at=_at(9, 30, 2),
        posted_at=_at(9, 30, 17, 30),
        invoice_date=("value_date", date(2026, 9, 30)),
        total="40.00",
        lines=[(CEMENT, "10.50")],
    )
    with owner.begin() as connection:
        connection.execute(
            text("UPDATE intake.invoice_line SET unit_price = 1 WHERE invoice_id = :i"),
            {"i": inv3},
        )
    # The overdue step fails too: logged, the summaries still written, then raised.
    clock[0] = _at(10, 5, 1, 30)
    no_overdue = _Broken(purchasing_port("sim", pipeline_engine), "list_overdue_pos")
    with (
        caplog.at_level(logging.INFO),
        pytest.raises(RuntimeError, match="went away"),
    ):
        asyncio.run(_job(pipeline_engine, clock, no_overdue).run())
    assert "analytics_refresh.overdue_failed code=RuntimeError" in caplog.text
    assert prices() == first | {
        (inv6, 1): (SUPPLIER_ALPHA, CEMENT, date(2026, 10, 1), Decimal("12.00")),
        (inv7, 1): (SUPPLIER_ALPHA, CEMENT, date(2026, 9, 30), Decimal("10.50")),
    }
    assert _scalars(owner, "SELECT posted_at FROM analytics.watermark") == [
        _at(10, 1, 5)
    ]
    assert summary_days() == [date(2026, 10, 1), date(2026, 10, 5)]
    # A mid-month `since` keeps its month.
    assert asyncio.run(reader.month_summaries(date(2026, 10, 15))) == (
        MonthSummary(date(2026, 10, 1), 4, 3, Decimal("0.7500")),
    )
    assert asyncio.run(reader.supplier_months(date(2026, 10, 1)))[0].spend == Decimal(
        "220.00"
    )

    # --- Staff-api reads dashboards through the repository, which knows only
    # `analytics` tables. 5.1's data produces only price_rise alerts (Story 5.3's
    # rule), so every alert read back is one.
    tables = [v for v in vars(dashboards_module).values() if isinstance(v, Table)]
    assert tables and {table.schema for table in tables} == {"analytics"}
    alerts = asyncio.run(reader.alerts(_at(1, 1, 0)))
    assert {item.kind for item in alerts} == {"price_rise"}


def test_story_5_1_lateness(
    owner: Engine, staff: Engine, pipeline_engine: Engine
) -> None:
    """Per receipt line, received minus expected; on time is 0 or less; rates and
    average days late per supplier over the last 365 days, recomputed each run."""
    po_lines = {name: uuid4() for name in ("late", "early", "old")}
    receipts = {name: uuid4() for name in po_lines}
    rows = [
        # (po, supplier, order date, po line, material, expected, received)
        ("PO-T5101", SUPPLIER_LATE, "2026-09-01", "late", CEMENT, "2026-09-10", "2026-09-13"),
        ("PO-T5101", SUPPLIER_LATE, "2026-09-01", "early", REBAR, "2026-09-20", "2026-09-19"),
        # 365 days before 1 Oct 2026: just outside the 365 days ending today.
        ("PO-T5102", SUPPLIER_OLD, "2025-09-01", "old", CEMENT, "2025-09-29", "2025-10-01"),
    ]  # fmt: skip
    with owner.begin() as connection:
        for no, (
            po,
            supplier,
            ordered,
            name,
            material,
            expected,
            received,
        ) in enumerate(rows, start=1):
            delivery = uuid4()
            connection.execute(
                text(
                    "INSERT INTO sim_purchasing.purchase_order (po_number, supplier_id,"
                    " order_date) VALUES (:po, :s, :o)"
                    " ON CONFLICT DO NOTHING"
                ),
                {"po": po, "s": supplier, "o": date.fromisoformat(ordered)},
            )
            connection.execute(
                text(
                    "INSERT INTO sim_purchasing.po_line (po_line_id, po_number,"
                    " line_no, material_id, supplier_product_code, unit_price,"
                    " quantity, expected_date) VALUES (:id, :po, :n, :m, 'T', 1, 1, :e)"
                ),
                {
                    "id": po_lines[name],
                    "po": po,
                    "n": no,
                    "m": material,
                    "e": date.fromisoformat(expected),
                },
            )
            connection.execute(
                text(
                    "INSERT INTO sim_purchasing.delivery (delivery_id, po_number,"
                    " delivery_no, delivery_date) VALUES (:d, :po, :n, :r)"
                ),
                {"d": delivery, "po": po, "n": no, "r": date.fromisoformat(received)},
            )
            connection.execute(
                text(
                    "INSERT INTO sim_purchasing.goods_receipt (receipt_id, delivery_id,"
                    " received_date) VALUES (:g, :d, :r)"
                ),
                {"g": receipts[name], "d": delivery, "r": date.fromisoformat(received)},
            )
            connection.execute(
                text(
                    "INSERT INTO sim_purchasing.goods_receipt_line (receipt_id, po_line_id,"
                    " quantity) VALUES (:g, :l, 1)"
                ),
                {"g": receipts[name], "l": po_lines[name]},
            )
    try:
        clock = [_at(10, 1, 1, 30)]
        assert asyncio.run(_job(pipeline_engine, clock).run()) == "refreshed"
        with owner.connect() as connection:
            lateness = {
                (row.receipt_id, row.po_line_id): row.days_late
                for row in connection.execute(
                    text(
                        "SELECT receipt_id, po_line_id, days_late"
                        " FROM analytics.receipt_lateness WHERE supplier_id = :s"
                    ),
                    {"s": SUPPLIER_LATE},
                )
            }
        assert lateness == {
            (receipts["late"], po_lines["late"]): 3,
            (receipts["early"], po_lines["early"]): -1,
        }
        rates = {
            r.supplier_id: r
            for r in asyncio.run(PostgresDashboardReader(staff).on_time_rates())
        }
        assert rates == {
            SUPPLIER_ALPHA: SupplierOnTime(
                SUPPLIER_ALPHA, 2, 0, Decimal("0.0000"), Decimal("2.00")
            ),
            SUPPLIER_BETA: SupplierOnTime(
                SUPPLIER_BETA, 1, 0, Decimal("0.0000"), Decimal("2.00")
            ),
            SUPPLIER_GAMMA: SupplierOnTime(
                SUPPLIER_GAMMA, 1, 0, Decimal("0.0000"), Decimal("1.00")
            ),
            # One 3 days late, one a day early; the supplier whose only receipt is
            # 365 days old has no row.
            SUPPLIER_LATE: SupplierOnTime(
                SUPPLIER_LATE, 2, 1, Decimal("0.5000"), Decimal("1.00")
            ),
        }
    finally:
        with owner.begin() as connection:
            for statement in (
                "DELETE FROM sim_purchasing.goods_receipt_line WHERE receipt_id = ANY(:g)",
                "DELETE FROM sim_purchasing.goods_receipt WHERE receipt_id = ANY(:g)",
                "DELETE FROM sim_purchasing.delivery WHERE po_number = ANY(:p)",
                "DELETE FROM sim_purchasing.po_line WHERE po_number = ANY(:p)",
                "DELETE FROM sim_purchasing.purchase_order WHERE po_number = ANY(:p)",
            ):
                connection.execute(
                    text(statement),
                    {"g": list(receipts.values()), "p": ["PO-T5101", "PO-T5102"]},
                )
