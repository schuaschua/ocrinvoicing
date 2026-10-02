"""Story 5.4: the watchlist the analytics refresh job keeps and staff-api's Watchlist
(CAP-15, CAP-16, AD-13, AD-20). Purchasing is the seeded simulation read through its
adapter (its goods receipts replaced by the test's own), `intake` and `analytics` a
real PostgreSQL 18; the job writes as the pipeline login and staff-api reads as its
own (so the test also proves the grants). The clock is injected, never waited on
(coding-style.md rule 23). Synthetic data only (security.md rule 1).

One merged test (the 200-case cap, coding-style.md rule 20 exception): each plan
matrix row is a block of assertions, in order."""

import asyncio
import json
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from types import ModuleType
from typing import Any
from uuid import UUID, uuid4

import azure.functions as func
import pytest
from sqlalchemy import Engine, create_engine, text

from apps._pipeline_fakes import FakeReminders
from apps.test_staff_me import header
from apps.test_story_4_2_overdue import NAMES, SUPPLIER_BETA
from apps.test_story_5_1_summaries import _invoice
from conftest import PostgresServer, login_engine
from contracts.purchasing_contract import CEMENT, REBAR, SUPPLIER_ALPHA
from invoicing.adapters.postgres.analytics import PostgresAnalyticsStore
from invoicing.adapters.postgres.dashboards import PostgresDashboardReader
from invoicing.adapters.postgres.schema import analytics_metadata
from invoicing.adapters.postgres.suppliers import PostgresSupplierDirectory
from invoicing.adapters.principal import PRINCIPAL_HEADER
from invoicing.adapters.purchasing_factory import purchasing_port
from invoicing.apps.pipeline.analytics_refresh import AnalyticsRefresh
from invoicing.apps.staff_api.watchlist import watchlist_endpoint
from invoicing.ports.purchasing import PurchasingPort, ReceiptLine

# Not in the master and with no goods receipts: no name and no on-time rate.
SUPPLIER_NEW = UUID("0192f0c1-7a2b-7c3d-8e4f-0000000054e1")
CEMENT_NAME = "Portland cement, 50 kg bag"


def _at(month: int, day: int) -> datetime:
    """01:30 UTC (09:30 in Singapore): an AD-13 run."""
    return datetime(2026, month, day, 1, 30, tzinfo=UTC)


class _Receipts:
    """Purchasing with the test's goods-receipt lines in place of the seeded ones."""

    def __init__(self, real: PurchasingPort, lines: list[ReceiptLine]) -> None:
        self._real, self.lines = real, lines

    async def receipt_lines(self, since: date) -> list[ReceiptLine]:
        return list(self.lines)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


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
def test_story_5_4_watchlist(
    owner: Engine,
    postgres_server: PostgresServer,
    purchasing_seeded: str,
    pipeline_engine: Engine,
    app_settings: dict[str, str],
    load_app: Callable[[str], ModuleType],
) -> None:
    """The job lists suppliers by the AD-20 rules with their evidence and one
    watchlist alert per new listing (none on a rerun, a new one when re-listed);
    GET api/watchlist: entries by most recent listing, the ranked alternatives, no
    invoice ids for its roles; 403 for other roles, 401 signed out; both empty
    states."""
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
    assert routes["watchlist"] == "api/watchlist"

    staff = login_engine(postgres_server, postgres_server.staff_api, purchasing_seeded)
    clock = [_at(10, 1)]
    api = watchlist_endpoint(
        PostgresDashboardReader(staff),
        PostgresSupplierDirectory(staff),
        platform_auth_trusted=True,
        clock=lambda: clock[0],
    )
    purchasing = _Receipts(purchasing_port("sim", pipeline_engine), [])

    def get(*roles: str) -> tuple[int, Any]:
        headers = {PRINCIPAL_HEADER: header(*roles)} if roles else {}
        request = func.HttpRequest(
            method="GET", url="/api/watchlist", headers=headers, body=b""
        )
        response = asyncio.run(api(request))
        return response.status_code, json.loads(response.get_body())

    def run() -> None:
        job = AnalyticsRefresh(
            purchasing,
            PostgresAnalyticsStore(pipeline_engine),
            FakeReminders(),
            clock=lambda: clock[0],
        )
        asyncio.run(job.run())

    def rows(sql: str) -> list[Any]:
        with owner.connect() as connection:
            return list(connection.execute(text(sql)))

    def listed() -> dict[tuple[UUID, str], date]:
        return {
            (row.supplier_id, row.rule): row.first_added_on
            for row in rows("SELECT * FROM analytics.watchlist")
        }

    def alerts() -> dict[str, Any]:
        return {
            row.dedupe_key: row.detail
            for row in rows(
                "SELECT dedupe_key, detail FROM analytics.alert"
                " WHERE kind = 'watchlist'"
            )
        }

    def emailed() -> dict[str, Any]:
        return {
            row.dedupe_key: row.emailed_at
            for row in rows(
                "SELECT dedupe_key, emailed_at FROM analytics.alert"
                " WHERE kind = 'watchlist'"
            )
        }

    def receipt(late_by: int, day: int, material: UUID = CEMENT) -> ReceiptLine:
        return ReceiptLine(
            receipt_id=uuid4(),
            po_line_id=uuid4(),
            supplier_id=SUPPLIER_BETA,
            material_id=material,
            expected_date=date(2026, 9, day),
            received_date=date(2026, 9, day + late_by),
        )

    def posted(supplier: UUID, day: date, price: str) -> UUID:
        invoice_id, _ = _invoice(
            owner,
            supplier,
            created_at=datetime(day.year, day.month, day.day, 2, tzinfo=UTC),
            posted_at=datetime(day.year, day.month, day.day, 3, tzinfo=UTC),
            invoice_date=("value_date", day),
            lines=[(CEMENT, price)],
        )
        return invoice_id

    def key(supplier: UUID, rule: str, day: str) -> str:
        return f"watchlist:{supplier}:{rule}:{day}"

    try:
        # --- Wrong role 403, signed out 401, before anything is read.
        for role in ("finance", "admin"):
            status, body = get(role)
            assert (status, body["code"]) == (403, "FORBIDDEN")
        status, body = get()
        assert (status, body["code"]) == (401, "UNAUTHENTICATED")

        # --- Empty: no price points at all.
        assert get("management") == (200, {"has_price_points": False, "entries": []})

        # --- 3 rises and a price gap: Alpha's cement 4.00, 4.10, 4.20, 4.30 (each
        # more than 2%), 7.5% above Beta's 4.00; the new supplier's 4.10 is only
        # 2.5% above. Late: Beta's receipts 7 days late on average (7.00).
        rise_0 = posted(SUPPLIER_ALPHA, date(2026, 9, 1), "4.00")
        rise_1 = posted(SUPPLIER_ALPHA, date(2026, 9, 10), "4.10")
        posted(SUPPLIER_ALPHA, date(2026, 9, 15), "4.20")
        latest = posted(SUPPLIER_ALPHA, date(2026, 9, 20), "4.30")
        posted(SUPPLIER_BETA, date(2026, 9, 12), "4.00")
        posted(SUPPLIER_NEW, date(2026, 9, 14), "4.10")
        purchasing.lines = [receipt(7, 20), receipt(7, 21)]
        run()
        first_day = {
            (SUPPLIER_ALPHA, "price_rises"): date(2026, 10, 1),
            (SUPPLIER_ALPHA, "price_gap"): date(2026, 10, 1),
            (SUPPLIER_BETA, "late"): date(2026, 10, 1),
        }
        assert listed() == first_day
        first_alerts = alerts()
        assert set(first_alerts) == {
            key(SUPPLIER_ALPHA, "price_rises", "2026-10-01"),
            key(SUPPLIER_ALPHA, "price_gap", "2026-10-01"),
            key(SUPPLIER_BETA, "late", "2026-10-01"),
        }
        gap = first_alerts[key(SUPPLIER_ALPHA, "price_gap", "2026-10-01")]
        assert gap == {
            "supplier_id": str(SUPPLIER_ALPHA),
            "rule": "price_gap",
            "evidence": [
                {
                    "material_id": str(CEMENT),
                    "invoice_id": str(latest),
                    "invoice_date": "2026-09-20",
                    "unit_price": "4.30",
                    "lowest_unit_price": "4.00",
                    "cheapest_supplier_id": str(SUPPLIER_BETA),
                    "pct": "7.50",
                }
            ],
            "backfilled": True,
        }
        # A first run's listings are history: already marked emailed (as 5.3's rises).
        assert set(emailed().values()) == {_at(10, 1)}

        # --- Rerun the next day, same state: no new alert, the dates kept.
        clock[0] = _at(10, 2)
        run()
        assert listed() == first_day
        assert alerts() == first_alerts

        # --- Beta on time: dropped off; late again later: listed anew, alerted anew
        # (left for the email). Now 20 late cement lines and an older late rebar one,
        # beyond the 20 kept as evidence.
        clock[0] = _at(10, 5)
        purchasing.lines = [receipt(0, 20), receipt(0, 21)]
        run()
        assert (SUPPLIER_BETA, "late") not in listed()
        clock[0] = _at(10, 6)
        purchasing.lines = [receipt(7, day) for day in range(2, 22)]
        purchasing.lines.append(receipt(7, 1, REBAR))
        run()
        assert listed()[SUPPLIER_BETA, "late"] == date(2026, 10, 6)
        relisted = key(SUPPLIER_BETA, "late", "2026-10-06")
        assert set(alerts()) == set(first_alerts) | {relisted}
        assert emailed()[relisted] is None
        assert "backfilled" not in alerts()[relisted]

        # --- The API: Beta (listed 6 Oct) before Alpha (1 Oct); alternatives by
        # price, then on-time rate; no invoice ids for procurement or management.
        status, body = get("procurement")
        assert status == 200
        assert body["has_price_points"] is True
        assert [entry["supplier_id"] for entry in body["entries"]] == [
            str(SUPPLIER_BETA),
            str(SUPPLIER_ALPHA),
        ]
        beta, alpha = body["entries"]
        assert beta == {
            "supplier_id": str(SUPPLIER_BETA),
            "supplier_name": NAMES[SUPPLIER_BETA],
            "rules": [
                {
                    "rule": "late",
                    "first_added_on": "2026-10-06",
                    "avg_days_late": "7.00",
                    "evidence": [
                        {
                            "material_id": str(CEMENT),
                            "material_name": CEMENT_NAME,
                            "received_date": received,
                            "days_late": 7,
                        }
                        for received in (
                            date(2026, 9, day).isoformat() for day in range(28, 8, -1)
                        )
                    ],
                }
            ],
            "alternatives": [
                {
                    "material_id": str(CEMENT),
                    "material_name": CEMENT_NAME,
                    "suppliers": [
                        {
                            "supplier_id": str(SUPPLIER_NEW),
                            "supplier_name": None,
                            "latest_unit_price": "4.10",
                            "on_time_rate": None,
                            "watchlisted": False,
                        },
                        {
                            "supplier_id": str(SUPPLIER_ALPHA),
                            "supplier_name": NAMES[SUPPLIER_ALPHA],
                            "latest_unit_price": "4.30",
                            "on_time_rate": None,
                            "watchlisted": True,
                        },
                    ],
                },
                # From the late line beyond the evidence; nobody priced it lately.
                {"material_id": str(REBAR), "material_name": None, "suppliers": []},
            ],
        }
        assert [rule["rule"] for rule in alpha["rules"]] == [
            "price_rises",
            "price_gap",
        ]
        rises = alpha["rules"][0]["evidence"]
        assert [(e["invoice_date"], e["unit_price"]) for e in rises] == [
            ("2026-09-20", "4.30"),
            ("2026-09-15", "4.20"),
            ("2026-09-10", "4.10"),
        ]
        assert rises[2] == {
            "material_id": str(CEMENT),
            "material_name": CEMENT_NAME,
            "invoice_id": None,
            "invoice_date": "2026-09-10",
            "unit_price": "4.10",
            "previous_invoice_id": None,
            "previous_invoice_date": "2026-09-01",
            "previous_unit_price": "4.00",
            "pct": "2.50",
        }
        assert str(rise_1) not in json.dumps(body)
        assert (
            alpha["rules"][1]["evidence"][0]["cheapest_supplier_name"]
            == (NAMES[SUPPLIER_BETA])
        )
        assert alpha["rules"][1]["evidence"][0]["invoice_id"] is None
        assert alpha["alternatives"][0]["suppliers"] == [
            {
                "supplier_id": str(SUPPLIER_BETA),
                "supplier_name": NAMES[SUPPLIER_BETA],
                "latest_unit_price": "4.00",
                "on_time_rate": "0.0000",
                "watchlisted": True,
            },
            {
                "supplier_id": str(SUPPLIER_NEW),
                "supplier_name": None,
                "latest_unit_price": "4.10",
                "on_time_rate": None,
                "watchlisted": False,
            },
        ]
        assert get("management") == (200, body)

        # --- A management user who is also finance can open invoices: real ids.
        status, linked = get("management", "finance")
        assert status == 200
        shown = linked["entries"][1]["rules"]
        assert (
            shown[0]["evidence"][2]["invoice_id"],
            shown[0]["evidence"][2]["previous_invoice_id"],
        ) == (str(rise_1), str(rise_0))
        assert shown[1]["evidence"][0]["invoice_id"] == str(latest)

        # --- Price points but nobody listed.
        with owner.begin() as connection:
            connection.execute(text("DELETE FROM analytics.watchlist"))
        assert get("management") == (200, {"has_price_points": True, "entries": []})
    finally:
        staff.dispose()
