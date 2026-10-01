"""Story 5.3: price-rise alerts from the analytics refresh job and staff-api's Price
comparison (CAP-14, AD-13, AD-20). Purchasing is the seeded simulation read through
its adapter, `intake` and `analytics` a real PostgreSQL 18; the job writes as the
pipeline login and staff-api reads as its own (so the test also proves the grants).
The clock is injected, never waited on (coding-style.md rule 23). Synthetic data only
(security.md rule 1).

One merged test (the 200-case cap, coding-style.md rule 20 exception): each plan
matrix row is a block of assertions, in order."""

import asyncio
import json
import logging
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from types import ModuleType
from typing import Any
from uuid import UUID

import azure.functions as func
import pytest
from sqlalchemy import Engine, create_engine, text

from apps._pipeline_fakes import FakeReminders
from apps.test_staff_me import header
from apps.test_story_4_2_overdue import NAMES, SUPPLIER_BETA
from apps.test_story_5_1_summaries import _Broken, _invoice
from conftest import PostgresServer, login_engine
from contracts.purchasing_contract import CEMENT, REBAR, SUPPLIER_ALPHA
from invoicing.adapters.postgres.analytics import PostgresAnalyticsStore
from invoicing.adapters.postgres.dashboards import PostgresDashboardReader
from invoicing.adapters.postgres.schema import analytics_metadata
from invoicing.adapters.postgres.suppliers import PostgresSupplierDirectory
from invoicing.adapters.principal import PRINCIPAL_HEADER
from invoicing.adapters.purchasing_factory import purchasing_port
from invoicing.apps.pipeline.analytics_refresh import AnalyticsRefresh
from invoicing.apps.staff_api.price_comparison import price_comparison_endpoints

# Not in the master and with no goods receipts: no name and no on-time rate.
SUPPLIER_NEW = UUID("0192f0c1-7a2b-7c3d-8e4f-0000000053e1")
SUPPLIER_OLD = UUID("0192f0c1-7a2b-7c3d-8e4f-0000000053e2")
# Not in purchasing: named by a placeholder.
UNKNOWN_MATERIAL = UUID("0192f0c1-7a2b-7c3d-8e4f-0000000053f1")
CEMENT_NAME = "Portland cement, 50 kg bag"
REBAR_NAME = "Steel rebar, 12 mm x 12 m"


def _at(month: int, day: int) -> datetime:
    """01:30 UTC (09:30 in Singapore): an AD-13 run."""
    return datetime(2026, month, day, 1, 30, tzinfo=UTC)


@pytest.fixture
def owner(postgres_server: PostgresServer, purchasing_seeded: str) -> Iterator[Engine]:
    """The deployer, which owns the schemas: seeds `intake` and empties `analytics`."""
    engine = create_engine(
        postgres_server.url(postgres_server.deployer, purchasing_seeded)
    )
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {', '.join(analytics_metadata.tables)}"))
        for supplier_id, supplier_name in NAMES.items():
            connection.execute(
                text(
                    "INSERT INTO master.supplier (id, name) VALUES (:id, :name)"
                    " ON CONFLICT (id) DO UPDATE SET name = :name"
                ),
                {"id": supplier_id, "name": supplier_name},
            )
    yield engine
    engine.dispose()


@pytest.mark.app("staff_api")
def test_story_5_3_price_comparison(
    owner: Engine,
    postgres_server: PostgresServer,
    purchasing_seeded: str,
    pipeline_engine: Engine,
    app_settings: dict[str, str],
    load_app: Callable[[str], ModuleType],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The job stores each price rise once, with its evidence (a first run's as
    already emailed history), and names the priced materials (a placeholder for one
    purchasing can't name; a failure retried by the next run); GET api/materials and api/price-comparison: suppliers by latest price
    then on-time rate, 365 days of history, evidence invoice ids for finance only;
    404 for an unknown or malformed material, 403 for other roles, 401 signed out;
    empty before any price."""
    module = load_app("staff_api")
    functions = list(module.app.get_functions())
    names = [fn.get_function_name() for fn in functions]
    assert names[-1] == "web_app"
    routes = {
        name: binding.get_dict_repr()["route"]
        for name, fn in zip(names, functions, strict=True)
        for binding in fn.get_bindings()
        if binding.get_dict_repr()["type"] == "httpTrigger"
    }
    assert routes["materials"] == "api/materials"
    assert routes["price_comparison"] == "api/price-comparison"

    staff = login_engine(postgres_server, postgres_server.staff_api, purchasing_seeded)
    clock = [_at(10, 1)]
    materials_api, comparison_api = price_comparison_endpoints(
        PostgresDashboardReader(staff),
        PostgresSupplierDirectory(staff),
        platform_auth_trusted=True,
        clock=lambda: clock[0],
    )

    def get(api: Any, url: str, *roles: str) -> tuple[int, Any]:
        headers = {PRINCIPAL_HEADER: header(*roles)} if roles else {}
        path, _, query = url.partition("?")
        params = dict(item.split("=", 1) for item in query.split("&") if item)
        request = func.HttpRequest(
            method="GET", url=path, headers=headers, params=params, body=b""
        )
        response = asyncio.run(api(request))
        return response.status_code, json.loads(response.get_body())

    def compare(material: object, *roles: str) -> tuple[int, Any]:
        return get(
            comparison_api, f"/api/price-comparison?material_id={material}", *roles
        )

    def run(purchasing: Any = None) -> None:
        job = AnalyticsRefresh(
            purchasing or purchasing_port("sim", pipeline_engine),
            PostgresAnalyticsStore(pipeline_engine),
            FakeReminders(),
            clock=lambda: clock[0],
        )
        asyncio.run(job.run())

    def alert_rows() -> dict[str, tuple[Any, ...]]:
        """Each alert by dedupe key: (alert_id, kind, emailed_at, detail)."""
        with owner.connect() as connection:
            return {
                row.dedupe_key: (row.alert_id, row.kind, row.emailed_at, row.detail)
                for row in connection.execute(
                    text(
                        "SELECT dedupe_key, alert_id, kind, emailed_at, detail"
                        " FROM analytics.alert"
                    )
                )
            }

    def posted(supplier: UUID, day: date, *lines: tuple[UUID, str]) -> UUID:
        invoice_id, _ = _invoice(
            owner,
            supplier,
            created_at=datetime(day.year, day.month, day.day, 2, tzinfo=UTC),
            posted_at=datetime(day.year, day.month, day.day, 3, tzinfo=UTC),
            invoice_date=("value_date", day),
            lines=lines,
        )
        return invoice_id

    try:
        # --- Wrong role 403, signed out 401, before anything is read.
        for api, url in (
            (materials_api, "/api/materials"),
            (comparison_api, f"/api/price-comparison?material_id={CEMENT}"),
        ):
            status, body = get(api, url, "management")
            assert (status, body["code"]) == (403, "FORBIDDEN")
            status, body = get(api, url)
            assert (status, body["code"]) == (401, "UNAUTHENTICATED")

        # --- Empty: no price points, no materials; a material without them is 404.
        assert get(materials_api, "/api/materials", "procurement") == (
            200,
            {"items": []},
        )
        assert compare(CEMENT, "procurement")[0] == 404

        # --- Rise: Alpha's cement 4.00, then 4.10 (+2.5%), then 4.10 again; Beta's
        # 4.10. The new supplier falls from 4.30 (today-365, outside the history)
        # to 4.20 (today-364, inside) and 4.10; the old one priced only 13 months
        # ago. A material purchasing doesn't know.
        inv1 = posted(SUPPLIER_ALPHA, date(2026, 9, 1), (CEMENT, "4.00"))
        inv2 = posted(
            SUPPLIER_ALPHA, date(2026, 9, 10), (CEMENT, "4.10"), (REBAR, "18.00")
        )
        posted(SUPPLIER_ALPHA, date(2026, 9, 20), (CEMENT, "4.10"))
        posted(SUPPLIER_ALPHA, date(2026, 9, 5), (UNKNOWN_MATERIAL, "1.00"))
        posted(SUPPLIER_BETA, date(2026, 9, 12), (CEMENT, "4.10"))
        posted(SUPPLIER_NEW, date(2025, 10, 2), (CEMENT, "4.30"))
        posted(SUPPLIER_NEW, date(2025, 10, 3), (CEMENT, "4.20"))
        posted(SUPPLIER_NEW, date(2026, 9, 15), (CEMENT, "4.10"))
        posted(SUPPLIER_OLD, date(2025, 9, 1), (CEMENT, "3.00"))

        # --- Names fail: logged, nothing listed; the same day's next run names them,
        # a material purchasing doesn't know by a placeholder.
        with caplog.at_level(logging.INFO):
            run(_Broken(purchasing_port("sim", pipeline_engine), "material_names"))
            assert "analytics_refresh.materials_failed code=RuntimeError" in caplog.text
            assert get(materials_api, "/api/materials", "finance") == (
                200,
                {"items": []},
            )
            run()
            assert (
                "analytics_refresh.materials_unnamed code=MATERIAL_UNKNOWN count=1"
                in caplog.text
            )
        assert get(materials_api, "/api/materials", "finance") == (
            200,
            {
                "items": [
                    {
                        "material_id": str(UNKNOWN_MATERIAL),
                        "name": f"Material {str(UNKNOWN_MATERIAL)[:8]}",
                    },
                    {"material_id": str(CEMENT), "name": CEMENT_NAME},
                    {"material_id": str(REBAR), "name": REBAR_NAME},
                ]
            },
        )

        # --- A first run's rises are history: stored, but already marked emailed.
        first = alert_rows()
        alpha_key = f"price_rise:{inv2}:1"
        assert list(first) == [alpha_key]
        alert_id, kind, emailed_at, detail = first[alpha_key]
        assert (kind, emailed_at) == ("price_rise", _at(10, 1))
        assert detail == {
            "supplier_id": str(SUPPLIER_ALPHA),
            "material_id": str(CEMENT),
            "pct": "2.50",
            "previous": {
                "invoice_id": str(inv1),
                "invoice_date": "2026-09-01",
                "unit_price": "4.00",
            },
            "current": {
                "invoice_id": str(inv2),
                "invoice_date": "2026-09-10",
                "unit_price": "4.10",
            },
            "backfilled": True,
        }

        # --- Rerun the next day: no duplicate; Beta's new 4.30 (+4.88%), posted in
        # this run's window, is left for the email (emailed_at null).
        inv3 = posted(SUPPLIER_BETA, date(2026, 9, 25), (CEMENT, "4.30"))
        clock[0] = _at(10, 2)
        run()
        second = alert_rows()
        beta_key = f"price_rise:{inv3}:1"
        assert second.keys() == {alpha_key, beta_key}
        assert second[alpha_key] == first[alpha_key]
        assert second[beta_key][2] is None
        assert "backfilled" not in second[beta_key][3]
        assert second[beta_key][3]["pct"] == "4.88"

        # --- Comparison: Alpha and the new supplier at 4.10, the one with a rate
        # first; then Beta at 4.30 (rates set as given). The old supplier has no
        # price in the window and isn't listed.
        with owner.begin() as connection:
            connection.execute(
                text(
                    "UPDATE analytics.supplier_on_time SET on_time_rate = CASE"
                    " supplier_id WHEN :a THEN 0.8 ELSE 0.5 END"
                ),
                {"a": SUPPLIER_ALPHA},
            )
        status, body = compare(CEMENT, "finance")
        assert status == 200
        evidence = [
            {
                "invoice_id": str(inv1),
                "invoice_date": "2026-09-01",
                "unit_price": "4.00",
            },
            {
                "invoice_id": str(inv2),
                "invoice_date": "2026-09-10",
                "unit_price": "4.10",
            },
        ]

        def price(supplier: UUID, day: str, unit_price: str) -> dict[str, str]:
            return {
                "supplier_id": str(supplier),
                "invoice_date": day,
                "unit_price": unit_price,
            }

        assert {k: v for k, v in body.items() if k != "alerts"} == {
            "material_id": str(CEMENT),
            "name": CEMENT_NAME,
            "suppliers": [
                {
                    "supplier_id": str(SUPPLIER_ALPHA),
                    "supplier_name": NAMES[SUPPLIER_ALPHA],
                    "latest_unit_price": "4.10",
                    "latest_invoice_date": "2026-09-20",
                    "on_time_rate": "0.8000",
                },
                {
                    "supplier_id": str(SUPPLIER_NEW),
                    "supplier_name": None,
                    "latest_unit_price": "4.10",
                    "latest_invoice_date": "2026-09-15",
                    "on_time_rate": None,
                },
                {
                    "supplier_id": str(SUPPLIER_BETA),
                    "supplier_name": NAMES[SUPPLIER_BETA],
                    "latest_unit_price": "4.30",
                    "latest_invoice_date": "2026-09-25",
                    "on_time_rate": "0.5000",
                },
            ],
            # By supplier id, then date: today-364 in, today-365 out (2 Oct 2026).
            "history": sorted(
                [
                    price(SUPPLIER_ALPHA, "2026-09-01", "4.00"),
                    price(SUPPLIER_ALPHA, "2026-09-10", "4.10"),
                    price(SUPPLIER_ALPHA, "2026-09-20", "4.10"),
                    price(SUPPLIER_BETA, "2026-09-12", "4.10"),
                    price(SUPPLIER_BETA, "2026-09-25", "4.30"),
                    price(SUPPLIER_NEW, "2025-10-03", "4.20"),
                    price(SUPPLIER_NEW, "2026-09-15", "4.10"),
                ],
                key=lambda row: (row["supplier_id"], row["invoice_date"]),
            ),
        }
        shown = {item["supplier_id"]: item for item in body["alerts"]}
        assert [item["supplier_id"] for item in body["alerts"]] == [
            str(SUPPLIER_BETA),
            str(SUPPLIER_ALPHA),
        ]
        assert {
            k: v for k, v in shown[str(SUPPLIER_ALPHA)].items() if k != "created_at"
        } == {
            "alert_id": str(alert_id),
            "supplier_id": str(SUPPLIER_ALPHA),
            "supplier_name": NAMES[SUPPLIER_ALPHA],
            "pct": "2.50",
            "evidence": evidence,
        }

        # --- Evidence roles: no invoice id for procurement.
        status, body = compare(CEMENT, "procurement")
        assert status == 200
        assert body["alerts"][1]["evidence"] == [
            {**row, "invoice_id": None} for row in evidence
        ]

        # --- Bad material: unknown, malformed or missing is 404.
        for material in (UUID(int=1), "abc"):
            status, body = compare(material, "finance")
            assert (status, body["code"]) == (404, "NOT_FOUND")
        assert get(comparison_api, "/api/price-comparison", "finance")[0] == 404
    finally:
        staff.dispose()
