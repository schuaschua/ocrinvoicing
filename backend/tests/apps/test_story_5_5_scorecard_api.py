"""Story 5.5: `GET /api/suppliers/{supplier_id}/scorecard` on staff-api (CAP-17,
AD-13, AD-20), against a real PostgreSQL 18, read as the staff-api login (so the test
also proves its grants). The `analytics` rows the refresh job would write (Stories 5.1
and 5.3) are inserted directly; the clock is injected (coding-style.md rule 23).
Synthetic data only (security.md rule 1).

This test's own suppliers, materials and analytics rows carry a marker, and are
removed afterwards. One merged test (the 200-case cap, coding-style.md rule 20
exception): each plan matrix row is a block of assertions, in order."""

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from types import ModuleType
from typing import Any
from uuid import UUID

import azure.functions as func
import pytest
from sqlalchemy import Engine, create_engine, text

from apps.test_staff_me import header
from apps.test_story_4_5_deliveries_api import _Counting
from conftest import PostgresServer, login_engine
from invoicing.adapters.postgres.dashboards import PostgresDashboardReader
from invoicing.adapters.postgres.suppliers import PostgresSupplierDirectory
from invoicing.adapters.principal import PRINCIPAL_HEADER
from invoicing.adapters.purchasing_factory import purchasing_port
from invoicing.apps.staff_api.suppliers import suppliers_endpoints

pytestmark = pytest.mark.app("staff_api")

# 1am on 1 October in Singapore, still 30 September in UTC: the window starts on
# 2 October 2025.
NOW = datetime(2026, 9, 30, 17, 0, tzinfo=UTC)
FULL = UUID("0192f0c1-7a2b-7c3d-8e4f-550000000001")
SPARSE = UUID("0192f0c1-7a2b-7c3d-8e4f-550000000002")
EMPTY = UUID("0192f0c1-7a2b-7c3d-8e4f-550000000003")
MORTAR = UUID("0192f0c1-7a2b-7c3d-8e4f-55000000000a")
ADHESIVE = UUID("0192f0c1-7a2b-7c3d-8e4f-55000000000b")
OLD = UUID("0192f0c1-7a2b-7c3d-8e4f-55000000000c")
# Priced, but with no `analytics.material` row yet: left out.
UNNAMED = UUID("0192f0c1-7a2b-7c3d-8e4f-55000000000d")
SUPPLIERS = [FULL, SPARSE, EMPTY]
MATERIALS = [MORTAR, ADHESIVE, OLD]


def _remove(owner: Engine) -> None:
    """Delete this test's analytics rows and suppliers, as the deployer."""
    with owner.begin() as connection:
        for statement in (
            "DELETE FROM analytics.price_point WHERE supplier_id = ANY(:s)",
            "DELETE FROM analytics.supplier_on_time WHERE supplier_id = ANY(:s)",
            "DELETE FROM master.supplier WHERE id = ANY(:s)",
        ):
            connection.execute(text(statement), {"s": SUPPLIERS})
        connection.execute(
            text("DELETE FROM analytics.material WHERE material_id = ANY(:m)"),
            {"m": MATERIALS},
        )


def test_story_5_5_scorecard_api(
    postgres_server: PostgresServer,
    purchasing_seeded: str,
    app_settings: dict[str, str],
    load_app: Callable[[str], ModuleType],
) -> None:
    """Wired GET before the SPA catch-all; the on-time rate and each material's
    prices of the last 365 days (Singapore date) with the change first to latest,
    materials by name; one price has no change; older prices aren't listed; no
    receipts is a null on_time; nothing is empty; unknown or malformed supplier 404
    before analytics is read; admin 404 with nothing read; 401 signed out."""
    # --- Wiring.
    module = load_app("staff_api")
    functions = list(module.app.get_functions())
    names = [fn.get_function_name() for fn in functions]
    assert names[-1] == "web_app"
    (trigger,) = [
        b.get_dict_repr()
        for b in functions[names.index("supplier_scorecard")].get_bindings()
        if b.get_dict_repr()["type"] == "httpTrigger"
    ]
    assert trigger["route"] == "api/suppliers/{supplier_id}/scorecard"

    owner = create_engine(
        postgres_server.url(postgres_server.deployer, purchasing_seeded)
    )
    staff = login_engine(postgres_server, postgres_server.staff_api, purchasing_seeded)
    directory = _Counting(PostgresSupplierDirectory(staff))
    dashboards = _Counting(PostgresDashboardReader(staff))
    *_, endpoint = suppliers_endpoints(
        directory,
        purchasing_port("sim", staff),
        dashboards,
        platform_auth_trusted=True,
        clock=lambda: NOW,
    )

    def scorecard(supplier_id: str, *roles: str) -> Any:
        request = func.HttpRequest(
            method="GET",
            url=f"/api/suppliers/{supplier_id}/scorecard",
            headers={PRINCIPAL_HEADER: header(*roles)} if roles else {},
            params={},
            route_params={"supplier_id": supplier_id},
            body=b"",
        )
        response = asyncio.run(endpoint(request))
        return response.status_code, json.loads(response.get_body())

    def point(
        n: int, supplier: UUID, material: UUID, day: date, price: str, hour: int = 3
    ) -> Any:
        return {
            "id": UUID(f"0192f0c1-7a2b-7c3d-8e4f-55{n:010x}"),
            "s": supplier,
            "m": material,
            "d": day,
            "p": price,
            "at": datetime(day.year, day.month, day.day, hour, tzinfo=UTC),
        }

    try:
        _remove(owner)
        with owner.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO master.supplier (id, name) VALUES"
                    " (:f, 'Zq55 Full'), (:s, 'Zq55 Sparse'), (:e, 'Zq55 Empty')"
                ),
                {"f": FULL, "s": SPARSE, "e": EMPTY},
            )
            connection.execute(
                text(
                    "INSERT INTO analytics.material (material_id, name) VALUES"
                    " (:m, 'Zq55 mortar'), (:a, 'Zq55 Adhesive'), (:o, 'Zq55 Old')"
                ),
                {"m": MORTAR, "a": ADHESIVE, "o": OLD},
            )
            # 4 of 5 receipt lines on time, 1.2 days late on average.
            connection.execute(
                text(
                    "INSERT INTO analytics.supplier_on_time (supplier_id, receipts,"
                    " on_time, on_time_rate, avg_days_late) VALUES (:f, 5, 4, 0.8,"
                    " 1.2)"
                ),
                {"f": FULL},
            )
            connection.execute(
                text(
                    "INSERT INTO analytics.price_point (invoice_id, line_no,"
                    " supplier_id, material_id, invoice_date, unit_price, posted_at)"
                    " VALUES (:id, 1, :s, :m, :d, :p, :at)"
                ),
                [
                    # Mortar: 1 Oct 2025 is outside, 2 Oct 2025 the window's first day.
                    point(1, FULL, MORTAR, date(2025, 10, 1), "3.00"),
                    point(2, FULL, MORTAR, date(2025, 10, 2), "4.00"),
                    point(3, FULL, MORTAR, date(2026, 5, 1), "4.10"),
                    point(4, FULL, MORTAR, date(2026, 10, 1), "4.24"),
                    # Same day, posted earlier (with a later-sorting invoice id): not
                    # the latest.
                    point(8, FULL, MORTAR, date(2026, 10, 1), "4.50", hour=1),
                    # After today (Singapore): not listed.
                    point(9, FULL, MORTAR, date(2026, 10, 2), "9.99"),
                    # No material name yet: not listed.
                    point(10, FULL, UNNAMED, date(2026, 6, 1), "1.00"),
                    # Old prices only: not listed.
                    point(5, FULL, OLD, date(2025, 9, 1), "9.00"),
                    # One price, from a supplier with no receipts.
                    point(6, SPARSE, ADHESIVE, date(2026, 9, 1), "4.00"),
                    # Another supplier's price for the same material is not this one's.
                    point(7, SPARSE, MORTAR, date(2026, 9, 2), "5.00"),
                ],
            )

        # --- Full: rate 0.8000; Mortar 4.00 -> 4.24 (the later posted of 1 Oct) is
        # +6.00%; old, future and unnamed prices omitted.
        status, body = scorecard(str(FULL), "procurement")
        assert status == 200, body
        assert body == {
            "on_time": {
                "rate": "0.8000",
                "receipts": 5,
                "on_time": 4,
                "avg_days_late": "1.20",
            },
            "materials": [
                {
                    "material_id": str(MORTAR),
                    "name": "Zq55 mortar",
                    "change_pct": "6.00",
                    "latest_unit_price": "4.24",
                    "points": [
                        {"invoice_date": "2025-10-02", "unit_price": "4.00"},
                        {"invoice_date": "2026-05-01", "unit_price": "4.10"},
                        {"invoice_date": "2026-10-01", "unit_price": "4.50"},
                        {"invoice_date": "2026-10-01", "unit_price": "4.24"},
                    ],
                }
            ],
        }

        # --- One price and no receipts: change null, on_time null; by name in any
        # case (Adhesive before mortar).
        status, body = scorecard(str(SPARSE), "finance")
        assert status == 200, body
        assert body["on_time"] is None
        assert [(m["name"], m["change_pct"]) for m in body["materials"]] == [
            ("Zq55 Adhesive", None),
            ("Zq55 mortar", None),
        ]
        assert body["materials"][0]["latest_unit_price"] == "4.00"

        # --- Empty.
        assert scorecard(str(EMPTY), "management") == (
            200,
            {"on_time": None, "materials": []},
        )

        # --- Unknown or malformed supplier: 404 before analytics is read.
        reads = dashboards.reads
        for missing in ("0192f0c1-7a2b-7c3d-8e4f-55ffffffffff", "not-a-uuid"):
            status, body = scorecard(missing, "procurement")
            assert (status, body["code"]) == (404, "NOT_FOUND")
        assert dashboards.reads == reads

        # --- Wrong role 404, signed out 401: nothing read.
        reads = dashboards.reads + directory.reads
        status, body = scorecard(str(FULL), "admin")
        assert (status, body["code"]) == (404, "NOT_FOUND")
        status, body = scorecard(str(FULL))
        assert (status, body["code"]) == (401, "UNAUTHENTICATED")
        assert dashboards.reads + directory.reads == reads
    finally:
        try:
            _remove(owner)
        finally:
            staff.dispose()
            owner.dispose()
