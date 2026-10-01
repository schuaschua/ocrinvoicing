"""Story 5.6: `GET /api/finance-month` on staff-api (CAP-18, FR18, NFR19, AD-13,
AD-20), against a real PostgreSQL 18, read as the staff-api login (so the test also
proves its grants). The `analytics` rows the refresh job would write (Stories 5.1 and
5.3) are inserted directly; the clock is injected (coding-style.md rule 23).
Synthetic data only (security.md rule 1).

One merged test (the 200-case cap, coding-style.md rule 20 exception): each plan
matrix row is a block of assertions, in order."""

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime
from types import ModuleType
from typing import Any
from uuid import UUID

import azure.functions as func
import pytest
from sqlalchemy import create_engine, text

from apps.test_staff_me import header
from apps.test_story_4_2_overdue import NAMES, SUPPLIER_BETA
from apps.test_story_4_5_deliveries_api import _Counting
from conftest import PostgresServer, login_engine
from contracts.purchasing_contract import CEMENT, SUPPLIER_ALPHA
from invoicing.adapters.postgres.dashboards import PostgresDashboardReader
from invoicing.adapters.postgres.schema import analytics_metadata
from invoicing.adapters.postgres.suppliers import PostgresSupplierDirectory
from invoicing.adapters.principal import PRINCIPAL_HEADER
from invoicing.apps.staff_api.finance_month import finance_month_endpoint

pytestmark = pytest.mark.app("staff_api")

# 1am on 1 October in Singapore, still 30 September in UTC: the current month is
# October 2026.
NOW = datetime(2026, 9, 30, 17, 0, tzinfo=UTC)
# Not in the master: flagged only, no name.
SUPPLIER_C = UUID("0192f0c1-7a2b-7c3d-8e4f-560000000003")
# Not in the master: only a price rise, in a month with nothing else.
SUPPLIER_D = UUID("0192f0c1-7a2b-7c3d-8e4f-560000000004")
# Equal spend in July: name order differs from id order.
SUPPLIER_ZEBRA = UUID("0192f0c1-7a2b-7c3d-8e4f-560000000005")
SUPPLIER_AARDVARK = UUID("0192f0c1-7a2b-7c3d-8e4f-560000000006")
EXTRA_NAMES = {SUPPLIER_ZEBRA: "Zq56 Zebra", SUPPLIER_AARDVARK: "Zq56 Aardvark"}


def _rise(n: int, supplier: UUID, invoice_date: str) -> dict[str, Any]:
    return {
        "id": UUID(f"0192f0c1-7a2b-7c3d-8e4f-56{n:010x}"),
        "key": f"price_rise:story-5-6:{n}",
        "s": supplier,
        "m": CEMENT,
        "detail": json.dumps(
            {
                "pct": "2.50",
                "previous": {"invoice_date": "2026-07-01", "unit_price": "4.00"},
                "current": {"invoice_date": invoice_date, "unit_price": "4.10"},
            }
        ),
    }


def test_story_5_6_finance_month_api(
    postgres_server: PostgresServer,
    purchasing_seeded: str,
    app_settings: dict[str, str],
    load_app: Callable[[str], ModuleType],
) -> None:
    """Wired GET before the SPA catch-all; 403 for other roles and 401 signed out
    before anything is read; nothing at all is the current month, empty; September
    by spend then name with rises by invoice date, a flags-only supplier at 0.00 and
    the share against the target; the latest month by default; an empty month;
    a malformed month 400, never echoed."""
    module = load_app("staff_api")
    functions = list(module.app.get_functions())
    names = [fn.get_function_name() for fn in functions]
    assert names[-1] == "web_app"
    (trigger,) = [
        b.get_dict_repr()
        for b in functions[names.index("finance_month")].get_bindings()
        if b.get_dict_repr()["type"] == "httpTrigger"
    ]
    assert trigger["route"] == "api/finance-month"

    owner = create_engine(
        postgres_server.url(postgres_server.deployer, purchasing_seeded)
    )
    staff = login_engine(postgres_server, postgres_server.staff_api, purchasing_seeded)
    dashboards = _Counting(PostgresDashboardReader(staff))
    endpoint = finance_month_endpoint(
        dashboards,
        PostgresSupplierDirectory(staff),
        platform_auth_trusted=True,
        clock=lambda: NOW,
    )

    def get(month: str | None, *roles: str) -> tuple[int, Any]:
        request = func.HttpRequest(
            method="GET",
            url="/api/finance-month",
            headers={PRINCIPAL_HEADER: header(*roles)} if roles else {},
            params={} if month is None else {"month": month},
            body=b"",
        )
        response = asyncio.run(endpoint(request))
        return response.status_code, json.loads(response.get_body())

    try:
        with owner.begin() as connection:
            connection.execute(text(f"TRUNCATE {', '.join(analytics_metadata.tables)}"))
            for supplier_id, supplier_name in {**NAMES, **EXTRA_NAMES}.items():
                connection.execute(
                    text(
                        "INSERT INTO master.supplier (id, name) VALUES (:id, :name)"
                        " ON CONFLICT (id) DO UPDATE SET name = :name"
                    ),
                    {"id": supplier_id, "name": supplier_name},
                )

        # --- Wrong role 403, signed out 401, before anything is read.
        status, body = get("2026-09", "procurement")
        assert (status, body["code"]) == (403, "FORBIDDEN")
        status, body = get("2026-09")
        assert (status, body["code"]) == (401, "UNAUTHENTICATED")
        assert dashboards.reads == 0

        # --- No data at all: the current Singapore month, empty.
        empty_share = {
            "share": None,
            "posted_count": 0,
            "straight_through_count": 0,
            "target": "0.9000",
        }
        assert get(None, "finance") == (
            200,
            {
                "month": "2026-10",
                "months": [],
                "straight_through": empty_share,
                "history": [],
                "suppliers": [],
            },
        )

        # --- September: A 120.00 from 2 posted, a rise (an August one counts in
        # August) and 1 flagged; B 40.00, 1 duplicate; C only flagged; 2 of 3
        # straight through. August: A 10.00, all straight through. July: two
        # suppliers at 50.00. June: only D's rise. Rises with a malformed date or a
        # mistyped future one are left out.
        with owner.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO analytics.supplier_month"
                    " (supplier_id, month, spend, posted_count) VALUES"
                    " (:a, '2026-09-01', 120.00, 2), (:b, '2026-09-01', 40.00, 1),"
                    " (:a, '2026-08-01', 10.00, 1),"
                    " (:z, '2026-07-01', 50.00, 1), (:y, '2026-07-01', 50.00, 1)"
                ),
                {
                    "a": SUPPLIER_ALPHA,
                    "b": SUPPLIER_BETA,
                    "z": SUPPLIER_ZEBRA,
                    "y": SUPPLIER_AARDVARK,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO analytics.supplier_month_flags"
                    " (supplier_id, month, flagged_count, duplicate_count) VALUES"
                    " (:a, '2026-09-01', 1, 0), (:b, '2026-09-01', 0, 1),"
                    " (:c, '2026-09-01', 1, 0)"
                ),
                {"a": SUPPLIER_ALPHA, "b": SUPPLIER_BETA, "c": SUPPLIER_C},
            )
            connection.execute(
                text(
                    "INSERT INTO analytics.month_summary (month, posted_count,"
                    " straight_through_count, straight_through_share) VALUES"
                    " ('2026-09-01', 3, 2, 0.6667), ('2026-08-01', 1, 1, 1)"
                )
            )
            for row in (
                _rise(1, SUPPLIER_ALPHA, "2026-09-10"),
                _rise(2, SUPPLIER_ALPHA, "2026-08-31"),
                _rise(3, SUPPLIER_D, "2026-06-15"),
                _rise(4, SUPPLIER_BETA, "next week"),
                _rise(5, SUPPLIER_BETA, "2026-13-01"),
                _rise(6, SUPPLIER_BETA, "2027-03-01"),
            ):
                connection.execute(
                    text(
                        "INSERT INTO analytics.alert (alert_id, kind, dedupe_key,"
                        " supplier_id, material_id, detail) VALUES"
                        " (:id, 'price_rise', :key, :s, :m, CAST(:detail AS jsonb))"
                    ),
                    row,
                )

        def supplier(
            supplier_id: UUID, spend: str, posted: int, rises: int, *flags: int
        ) -> dict[str, Any]:
            return {
                "supplier_id": str(supplier_id),
                "supplier_name": {**NAMES, **EXTRA_NAMES}.get(supplier_id),
                "spend": spend,
                "posted_count": posted,
                "price_rises": rises,
                "flagged_count": flags[0],
                "duplicate_count": flags[1],
            }

        history = [
            {"month": "2026-08", "share": "1.0000"},
            {"month": "2026-09", "share": "0.6667"},
        ]
        september = {
            "month": "2026-09",
            "months": ["2026-09", "2026-08", "2026-07", "2026-06"],
            "straight_through": {
                "share": "0.6667",
                "posted_count": 3,
                "straight_through_count": 2,
                "target": "0.9000",
            },
            "history": history,
            "suppliers": [
                supplier(SUPPLIER_ALPHA, "120.00", 2, 1, 1, 0),
                supplier(SUPPLIER_BETA, "40.00", 1, 0, 0, 1),
                supplier(SUPPLIER_C, "0.00", 0, 0, 1, 0),
            ],
        }
        assert get("2026-09", "finance") == (200, september)

        # --- Default month: the latest with data; management may read it too.
        assert get(None, "management") == (200, september)

        # --- August: the August rise counts there.
        status, body = get("2026-08", "finance")
        assert status == 200
        assert body["suppliers"] == [supplier(SUPPLIER_ALPHA, "10.00", 1, 1, 0, 0)]
        assert body["straight_through"]["share"] == "1.0000"

        # --- July: equal spend by name, not id.
        status, body = get("2026-07", "finance")
        assert status == 200
        assert body["suppliers"] == [
            supplier(SUPPLIER_AARDVARK, "50.00", 1, 0, 0, 0),
            supplier(SUPPLIER_ZEBRA, "50.00", 1, 0, 0, 0),
        ]

        # --- June: listed for its rise alone, at 0.00; history ends at June.
        status, body = get("2026-06", "finance")
        assert status == 200
        assert body["suppliers"] == [supplier(SUPPLIER_D, "0.00", 0, 1, 0, 0)]
        assert body["history"] == []

        # --- Empty month: no suppliers, no share.
        assert get("2026-05", "finance") == (
            200,
            {
                "month": "2026-05",
                "months": ["2026-09", "2026-08", "2026-07", "2026-06"],
                "straight_through": empty_share,
                "history": [],
                "suppliers": [],
            },
        )

        # --- Bad month: 400, the value never echoed.
        for bad in ("2026-13", "x", "2026-9", "0000-01", "2026-09-01", "9999-12"):
            status, body = get(bad, "finance")
            assert (status, body["code"]) == (400, "VALIDATION_FAILED")
            assert bad not in json.dumps(body)
    finally:
        with owner.begin() as connection:
            connection.execute(text(f"TRUNCATE {', '.join(analytics_metadata.tables)}"))
            connection.execute(
                text("DELETE FROM master.supplier WHERE id = ANY(:s)"),
                {"s": list(EXTRA_NAMES)},
            )
        staff.dispose()
        owner.dispose()
