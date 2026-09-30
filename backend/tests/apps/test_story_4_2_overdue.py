"""Story 4.2: the overdue PO list (CAP-12, AD-13): the analytics refresh job and
staff-api's read. Purchasing is the seeded simulation read through its adapter as the
pipeline login (AD-10), `intake` and `analytics` a real PostgreSQL 18, and staff-api
reads as its own login (so the tests also prove the grants). The clock is injected,
never waited on (coding-style.md rule 23). Synthetic data only (security.md rule 1).

Seeded POs by earliest expected date: PO-45012 1 Sep and PO-45017 25 Sep (Alpha),
PO-45013 5 Sep and PO-45015 15 Sep (Beta), PO-45016 28 Sep and PO-45014 20 Oct
(Gamma).

Two merged tests (the 200-case cap, coding-style.md rule 20 exception): each plan
matrix row is a block of assertions, in order."""

import asyncio
import json
import logging
from collections.abc import Callable
from datetime import UTC, date, datetime
from types import ModuleType
from typing import Any
from uuid import UUID, uuid4

import azure.functions as func
import pytest
from sqlalchemy import Engine, create_engine, text

from apps._pipeline_fakes import stopped_database
from apps.test_staff_me import header
from conftest import PostgresServer, login_engine
from contracts.purchasing_contract import SUPPLIER_ALPHA
from invoicing.adapters.postgres.analytics import (
    PostgresAnalyticsStore,
    PostgresOverdueReader,
)
from invoicing.adapters.postgres.suppliers import PostgresSupplierDirectory
from invoicing.adapters.principal import PRINCIPAL_HEADER
from invoicing.adapters.purchasing_factory import purchasing_port
from invoicing.apps.pipeline.analytics_refresh import AnalyticsRefresh
from invoicing.apps.staff_api.overdue import overdue_endpoint
from invoicing.ports.purchasing import OverduePo

SUPPLIER_BETA = UUID("01a0c450-6fe8-7cb7-9e60-74d841e2024a")
NAMES = {
    SUPPLIER_ALPHA: "Synthetic Alpha Building Supplies",
    SUPPLIER_BETA: "Synthetic Beta Hardware Trading",
}


def _at(day: int) -> datetime:
    """01:30 UTC (09:30 in Singapore) on `day` September 2026: an AD-13 run."""
    return datetime(2026, 9, day, 1, 30, tzinfo=UTC)


def _owner(server: PostgresServer, database: str) -> Engine:
    return create_engine(server.url(server.deployer, database))


def _reset_analytics(server: PostgresServer, database: str) -> None:
    owner = _owner(server, database)
    try:
        with owner.begin() as connection:
            connection.execute(text("TRUNCATE analytics.overdue_po, analytics.job_run"))
    finally:
        owner.dispose()


def _invoice(engine: Engine, po_number: str, status: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO intake.invoice (id, correlation_id, source, supplier_id,"
                " content_type, device_check, po_number, status) VALUES (:id,"
                " gen_random_uuid(), 'link', gen_random_uuid(), 'image/jpeg',"
                " 'passed', :po, :status)"
            ),
            {"id": uuid4(), "po": po_number, "status": status},
        )


def test_story_4_2_refresh_job(
    postgres_server: PostgresServer,
    purchasing_seeded: str,
    pipeline_engine: Engine,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """FR12 on the seeded simulation: a PO past its earliest expected date (Singapore)
    with no invoice is listed, dated by the run; an invoice in any status but
    rejected (in_admin_queue included) drops it; one due today or later is not
    listed; a missed day or a weekend is caught up by the next run; a second run the
    same day changes nothing, and two at once write once; a failed run leaves the
    previous list; a stopped database is skipped with DB_OFFLINE."""
    _reset_analytics(postgres_server, purchasing_seeded)
    staff = login_engine(postgres_server, postgres_server.staff_api, purchasing_seeded)
    reader = PostgresOverdueReader(staff)
    clock = [_at(25)]
    store = PostgresAnalyticsStore(pipeline_engine)
    job = AnalyticsRefresh(
        purchasing_port("sim", pipeline_engine), store, clock=lambda: clock[0]
    )

    def listed() -> tuple[datetime | None, list[str]]:
        found = asyncio.run(reader.overdue_list())
        return found.made_at, [po.po_number for po in found.pos]

    try:
        with caplog.at_level(logging.INFO):
            # --- FR12, Friday 25 Sep: PO-45017 is due today, so not yet listed.
            assert asyncio.run(job.run()) == "refreshed"
            assert listed() == (_at(25), ["PO-45012", "PO-45013", "PO-45015"])

            # --- Second run the same day: nothing changes, even with a new invoice.
            _invoice(pipeline_engine, "PO-45012", "posted")
            clock[0] = datetime(2026, 9, 25, 8, 30, tzinfo=UTC)
            assert asyncio.run(job.run()) == "already_ran"
            assert listed() == (_at(25), ["PO-45012", "PO-45013", "PO-45015"])

            # --- Monday 28 Sep, after the weekend: invoiced POs drop out (posted, and
            # in_admin_queue counts as invoiced); a PO whose only invoice is
            # rejected stays; PO-45017, due Friday, is listed; PO-45016 is due today.
            _invoice(pipeline_engine, "PO-45013", "in_admin_queue")
            _invoice(pipeline_engine, "PO-45015", "rejected")
            clock[0] = _at(28)
            assert asyncio.run(job.run()) == "refreshed"
            assert listed() == (_at(28), ["PO-45015", "PO-45017"])

            # --- Catch-up: no run on Tuesday; Wednesday's lists PO-45016 (28 Sep).
            clock[0] = _at(30)
            assert asyncio.run(job.run()) == "refreshed"
            assert listed() == (_at(30), ["PO-45015", "PO-45017", "PO-45016"])

            # --- A failed run rolls back whole: the previous list and date stay, and
            # the day is not recorded, so the next run retries.
            broken = OverduePo("PO-1", None, date(2026, 9, 1))  # type: ignore[arg-type]  # NOT NULL breaks mid-rebuild
            with pytest.raises(Exception, match="supplier_id"):
                asyncio.run(store.refresh_overdue(date(2026, 10, 1), [broken], _at(30)))
            assert listed() == (_at(30), ["PO-45015", "PO-45017", "PO-45016"])

            # --- Two runs at once on a new day: exactly one writes.
            async def both() -> list[bool]:
                pos = [OverduePo("PO-45015", SUPPLIER_BETA, date(2026, 9, 15))]
                day, at = date(2026, 10, 1), datetime(2026, 10, 1, 1, 30, tzinfo=UTC)
                return list(
                    await asyncio.gather(
                        store.refresh_overdue(day, pos, at),
                        store.refresh_overdue(day, pos, at),
                    )
                )

            assert sorted(asyncio.run(both())) == [False, True]
            assert listed()[1] == ["PO-45015"]

            # --- Database stopped: skipped with DB_OFFLINE, nothing written.
            with stopped_database() as stopped:
                offline = AnalyticsRefresh(
                    purchasing_port("sim", stopped),
                    PostgresAnalyticsStore(stopped),
                    clock=lambda: datetime(2026, 10, 2, 1, 30, tzinfo=UTC),
                )
                assert asyncio.run(offline.run()) == "DB_OFFLINE"
            assert listed()[1] == ["PO-45015"]
        skipped = [
            r.getMessage()
            for r in caplog.records
            if r.getMessage().startswith("analytics_refresh.skipped")
        ]
        assert skipped == ["analytics_refresh.skipped code=DB_OFFLINE"]
    finally:
        staff.dispose()


@pytest.mark.app("staff_api")
def test_story_4_2_overdue_api(
    postgres_server: PostgresServer,
    purchasing_seeded: str,
    pipeline_engine: Engine,
    app_settings: dict[str, str],
    load_app: Callable[[str], ModuleType],
) -> None:
    """GET api/overdue-pos: wired before the SPA catch-all; made_at null before any
    run; an empty list after a run with nothing overdue; POs grouped by supplier
    (by name, an unknown supplier last), by expected date then number; 401 signed
    out, 403 for goods_in and management; 503 DB_OFFLINE when stopped."""
    module = load_app("staff_api")
    functions = list(module.app.get_functions())
    names = [fn.get_function_name() for fn in functions]
    assert names[-1] == "web_app"
    (trigger,) = [
        b.get_dict_repr()
        for b in functions[names.index("overdue_pos")].get_bindings()
        if b.get_dict_repr()["type"] == "httpTrigger"
    ]
    assert trigger["route"] == "api/overdue-pos"

    _reset_analytics(postgres_server, purchasing_seeded)
    owner = _owner(postgres_server, purchasing_seeded)
    with owner.begin() as connection:
        for supplier_id, supplier_name in NAMES.items():
            connection.execute(
                text(
                    "INSERT INTO master.supplier (id, name) VALUES (:id, :name)"
                    " ON CONFLICT (id) DO UPDATE SET name = :name"
                ),
                {"id": supplier_id, "name": supplier_name},
            )
    staff = login_engine(postgres_server, postgres_server.staff_api, purchasing_seeded)

    def endpoint(engine: Engine) -> Any:
        return overdue_endpoint(
            PostgresOverdueReader(engine),
            PostgresSupplierDirectory(engine),
            platform_auth_trusted=True,
        )

    api = endpoint(staff)

    def get(*roles: str, using: Any = None) -> tuple[int, Any]:
        headers = {PRINCIPAL_HEADER: header(*roles)} if roles else {}
        request = func.HttpRequest(
            method="GET", url="/api/overdue-pos", headers=headers, body=b""
        )
        response = asyncio.run((using or api)(request))
        return response.status_code, json.loads(response.get_body())

    def run(at: datetime) -> None:
        job = AnalyticsRefresh(
            purchasing_port("sim", pipeline_engine),
            PostgresAnalyticsStore(pipeline_engine),
            clock=lambda: at,
        )
        assert asyncio.run(job.run()) == "refreshed"

    try:
        # --- Never made.
        assert get("procurement") == (200, {"made_at": None, "suppliers": []})

        # --- None overdue on 1 Sep: an empty list, with its date.
        run(_at(1))
        assert get("finance") == (
            200,
            {"made_at": "2026-09-01T01:30:00+00:00", "suppliers": []},
        )

        # --- Grouped by supplier name, then by expected date and PO number; a
        # supplier the master lacks comes last with no name.
        run(_at(28))
        unknown = UUID("0192f0c1-7a2b-7c3d-8e4f-0000000000ee")
        with owner.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO analytics.overdue_po (po_number, supplier_id,"
                    " expected_date) VALUES ('PO-9', :s, '2026-09-02')"
                ),
                {"s": unknown},
            )
        status, body = get("admin")
        assert status == 200
        assert body == {
            "made_at": "2026-09-28T01:30:00+00:00",
            "suppliers": [
                {
                    "supplier_id": str(SUPPLIER_ALPHA),
                    "supplier_name": NAMES[SUPPLIER_ALPHA],
                    "pos": [
                        {"po_number": "PO-45012", "expected_date": "2026-09-01"},
                        {"po_number": "PO-45017", "expected_date": "2026-09-25"},
                    ],
                },
                {
                    "supplier_id": str(SUPPLIER_BETA),
                    "supplier_name": NAMES[SUPPLIER_BETA],
                    "pos": [
                        {"po_number": "PO-45013", "expected_date": "2026-09-05"},
                        {"po_number": "PO-45015", "expected_date": "2026-09-15"},
                    ],
                },
                {
                    "supplier_id": str(unknown),
                    "supplier_name": None,
                    "pos": [{"po_number": "PO-9", "expected_date": "2026-09-02"}],
                },
            ],
        }

        # --- Wrong role 403, signed out 401, before anything is read.
        for roles in (("goods_in",), ("management",)):
            status, body = get(*roles)
            assert (status, body["code"]) == (403, "FORBIDDEN")
        status, body = get()
        assert (status, body["code"]) == (401, "UNAUTHENTICATED")

        # --- Database stopped: 503 DB_OFFLINE.
        with stopped_database() as stopped:
            status, body = get("procurement", using=endpoint(stopped))
        assert (status, body["code"]) == (503, "DB_OFFLINE")
    finally:
        staff.dispose()
        owner.dispose()
