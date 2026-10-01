"""Story 4.5: `GET /api/suppliers/{supplier_id}/deliveries` on staff-api (CAP-19,
AD-10, AD-14), against a real PostgreSQL 18 with the purchasing simulation's seed,
read as the staff-api login (so the test also proves its grants). Synthetic data only
(security.md rule 1).

This test's own supplier, PO and deliveries carry a marker, and are removed
afterwards. One merged test (the 200-case cap, coding-style.md rule 20 exception):
each plan matrix row is a block of assertions, in order."""

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from types import ModuleType
from typing import Any
from uuid import UUID

import azure.functions as func
import pytest
from sqlalchemy import Engine, create_engine, text

from apps.test_staff_me import header
from conftest import PostgresServer, login_engine
from contracts.purchasing_contract import CEMENT, SUPPLIER_ALPHA
from invoicing.adapters.postgres.dashboards import PostgresDashboardReader
from invoicing.adapters.postgres.suppliers import PostgresSupplierDirectory
from invoicing.adapters.principal import PRINCIPAL_HEADER
from invoicing.adapters.purchasing_factory import purchasing_port
from invoicing.apps.staff_api.suppliers import suppliers_endpoints

pytestmark = pytest.mark.app("staff_api")

# 1am on 1 October in Singapore, still 30 September in UTC: "today" is Singapore's.
NOW = datetime(2026, 9, 30, 17, 0, tzinfo=UTC)
CAPPED = UUID("0192f0c1-7a2b-7c3d-8e4f-450000000001")
EMPTY = UUID("0192f0c1-7a2b-7c3d-8e4f-450000000002")
CAP_PO = "PO-Zq45-CAP"
# An Alpha PO of this test's own, for the window's Singapore-date edge.
WINDOW_PO = "PO-Zq45-WIN"
CAP_DELIVERIES = 205


def _cap_delivery(n: int) -> UUID:
    return UUID(f"0192f0c1-7a2b-7c3d-8e4f-45{n + 0x100:010x}")


class _Counting:
    """A port or directory, counting the reads made through it."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.reads = 0

    def __getattr__(self, name: str) -> Any:
        method = getattr(self.inner, name)

        async def counted(*args: Any) -> Any:
            self.reads += 1
            return await method(*args)

        return counted


def _remove(owner: Engine) -> None:
    """Delete this test's purchasing rows and suppliers, as the deployer."""
    with owner.begin() as connection:
        for statement in (
            "DELETE FROM sim_purchasing.delivery WHERE po_number = ANY(:pos)",
            "DELETE FROM sim_purchasing.po_line WHERE po_number = ANY(:pos)",
            "DELETE FROM sim_purchasing.purchase_order WHERE po_number = ANY(:pos)",
        ):
            connection.execute(text(statement), {"pos": [CAP_PO, WINDOW_PO]})
        connection.execute(
            text("DELETE FROM master.supplier WHERE id = ANY(:ids)"),
            {"ids": [CAPPED, EMPTY]},
        )


def test_story_4_5_deliveries_api(
    postgres_server: PostgresServer,
    purchasing_seeded: str,
    app_settings: dict[str, str],
    load_app: Callable[[str], ModuleType],
) -> None:
    """Wired GET before the SPA catch-all; a supplier's deliveries newest first with
    promised (partial receipt: the received line's), delivered and received dates and
    the gaps from the domain, nulls while not received; the last 365 days by the
    Singapore date; at most 200 with `truncated`; none is an empty list; unknown or
    malformed supplier 404 before purchasing is read; admin and goods_in 404 with
    nothing read; 401 signed out."""
    # --- Wiring.
    module = load_app("staff_api")
    functions = list(module.app.get_functions())
    names = [fn.get_function_name() for fn in functions]
    assert names[-1] == "web_app"
    (trigger,) = [
        b.get_dict_repr()
        for b in functions[names.index("supplier_deliveries")].get_bindings()
        if b.get_dict_repr()["type"] == "httpTrigger"
    ]
    assert trigger["route"] == "api/suppliers/{supplier_id}/deliveries"
    assert [getattr(m, "value", m) for m in trigger["methods"]] == ["GET"]  # type: ignore[attr-defined]  # a list here

    owner = create_engine(
        postgres_server.url(postgres_server.deployer, purchasing_seeded)
    )
    staff = login_engine(postgres_server, postgres_server.staff_api, purchasing_seeded)
    directory = _Counting(PostgresSupplierDirectory(staff))
    purchasing = _Counting(purchasing_port("sim", staff))

    def deliveries(supplier_id: str, *roles: str, now: datetime = NOW) -> Any:
        _, _, endpoint, _ = suppliers_endpoints(
            directory,
            purchasing,
            PostgresDashboardReader(staff),
            platform_auth_trusted=True,
            clock=lambda: now,
        )
        request = func.HttpRequest(
            method="GET",
            url=f"/api/suppliers/{supplier_id}/deliveries",
            headers={PRINCIPAL_HEADER: header(*roles)} if roles else {},
            params={},
            route_params={"supplier_id": supplier_id},
            body=b"",
        )
        response = asyncio.run(endpoint(request))
        return response.status_code, json.loads(response.get_body())

    try:
        _remove(owner)
        with owner.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO master.supplier (id, name) VALUES"
                    " (:alpha, 'Synthetic Alpha Building Supplies'),"
                    " (:capped, 'Zq45 Capped'), (:empty, 'Zq45 Empty')"
                    " ON CONFLICT (id) DO NOTHING"
                ),
                {"alpha": SUPPLIER_ALPHA, "capped": CAPPED, "empty": EMPTY},
            )
            connection.execute(
                text(
                    "INSERT INTO sim_purchasing.purchase_order (po_number,"
                    " supplier_id, order_date) VALUES (:po, :s, '2025-01-01')"
                ),
                {"po": CAP_PO, "s": CAPPED},
            )
            connection.execute(
                text(
                    "INSERT INTO sim_purchasing.po_line (po_line_id, po_number,"
                    " line_no, material_id, supplier_product_code, unit_price,"
                    " quantity, expected_date) VALUES (:id, :po, 1, :m, 'ZQ-45',"
                    " 1.00, 1, '2025-01-01')"
                ),
                {"id": _cap_delivery(999), "po": CAP_PO, "m": CEMENT},
            )
            # One a day back from today: number 1 is the newest.
            connection.execute(
                text(
                    "INSERT INTO sim_purchasing.delivery (delivery_id, po_number,"
                    " delivery_no, delivery_date) VALUES (:id, :po, :no, :on)"
                ),
                [
                    {
                        "id": _cap_delivery(n),
                        "po": CAP_PO,
                        "no": n,
                        "on": date(2026, 10, 1) - timedelta(days=n - 1),
                    }
                    for n in range(1, CAP_DELIVERIES + 1)
                ],
            )

        # --- Late and received, partial receipt, not received: newest first; PO-45012
        # delivery 2 received only line 2, so it was promised for line 2's 12 Sep.
        status, body = deliveries(str(SUPPLIER_ALPHA), "procurement")
        assert status == 200, body
        assert body == {
            "items": [
                {
                    "po_number": "PO-45017",
                    "delivery_no": 1,
                    "promised_date": "2026-09-25",
                    "delivered_date": "2026-09-26",
                    "received_date": None,
                    "days_late": 1,
                    "days_to_receive": None,
                    "days_overall": None,
                },
                {
                    "po_number": "PO-45012",
                    "delivery_no": 2,
                    "promised_date": "2026-09-12",
                    "delivered_date": "2026-09-14",
                    "received_date": "2026-09-15",
                    "days_late": 2,
                    "days_to_receive": 1,
                    "days_overall": 3,
                },
                {
                    "po_number": "PO-45012",
                    "delivery_no": 1,
                    "promised_date": "2026-09-01",
                    "delivered_date": "2026-09-02",
                    "received_date": "2026-09-02",
                    "days_late": 1,
                    "days_to_receive": 0,
                    "days_overall": 1,
                },
            ],
            "truncated": False,
        }

        # --- Window: the last 365 days, the Singapore date included. At 1am on 13
        # Sep 2027 in Singapore (still the 12th in UTC) it starts on 14 Sep 2026: the
        # 14th is listed, and the 13th (where a UTC "today" would start) is not.
        later = datetime(2027, 9, 12, 17, 0, tzinfo=UTC)
        with owner.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO sim_purchasing.purchase_order (po_number,"
                    " supplier_id, order_date) VALUES (:po, :s, '2026-09-01')"
                ),
                {"po": WINDOW_PO, "s": SUPPLIER_ALPHA},
            )
            connection.execute(
                text(
                    "INSERT INTO sim_purchasing.po_line (po_line_id, po_number,"
                    " line_no, material_id, supplier_product_code, unit_price,"
                    " quantity, expected_date) VALUES (:id, :po, 1, :m, 'ZQ-45W',"
                    " 1.00, 1, '2026-09-13')"
                ),
                {"id": _cap_delivery(998), "po": WINDOW_PO, "m": CEMENT},
            )
            connection.execute(
                text(
                    "INSERT INTO sim_purchasing.delivery (delivery_id, po_number,"
                    " delivery_no, delivery_date) VALUES (:id, :po, 1, '2026-09-13')"
                ),
                {"id": _cap_delivery(997), "po": WINDOW_PO},
            )
        status, body = deliveries(str(SUPPLIER_ALPHA), "finance", now=later)
        assert [(i["po_number"], i["delivery_no"]) for i in body["items"]] == [
            ("PO-45017", 1),
            ("PO-45012", 2),
        ]

        # --- Cap: the newest 200, and `truncated`.
        status, body = deliveries(str(CAPPED), "management")
        assert status == 200, body
        assert len(body["items"]) == 200
        assert body["truncated"] is True
        assert [i["delivery_no"] for i in body["items"][:2]] == [1, 2]
        assert body["items"][-1]["delivery_no"] == 200
        assert body["items"][0]["delivered_date"] == "2026-10-01"

        # --- No deliveries: an empty list.
        assert deliveries(str(EMPTY), "procurement") == (
            200,
            {"items": [], "truncated": False},
        )

        # --- Unknown or malformed supplier: 404 before purchasing is read.
        reads = purchasing.reads
        for missing in ("0192f0c1-7a2b-7c3d-8e4f-45ffffffffff", "not-a-uuid"):
            status, body = deliveries(missing, "procurement")
            assert (status, body["code"]) == (404, "NOT_FOUND")
        assert purchasing.reads == reads

        # --- Wrong role 404, signed out 401: nothing read.
        reads = purchasing.reads + directory.reads
        for role in ("admin", "goods_in"):
            status, body = deliveries(str(SUPPLIER_ALPHA), role)
            assert (status, body["code"]) == (404, "NOT_FOUND")
        status, body = deliveries(str(SUPPLIER_ALPHA))
        assert (status, body["code"]) == (401, "UNAUTHENTICATED")
        assert purchasing.reads + directory.reads == reads
    finally:
        try:
            _remove(owner)
        finally:
            staff.dispose()
            owner.dispose()
