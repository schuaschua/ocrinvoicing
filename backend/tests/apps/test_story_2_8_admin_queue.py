"""Story 2.8: `GET /api/admin/queue` on staff-api (AD-4, AD-8, AD-14, AD-18), against a
real PostgreSQL 18 read as the staff-api login (so the test also proves its grants,
0007_staff_queue included). Synthetic data only (security.md rule 1).

One merged test (the 200-case cap, coding-style.md rule 20 exception): each plan
matrix row is a block of assertions, in order."""

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import ModuleType
from typing import Any
from uuid import UUID

import azure.functions as func
import pytest
from sqlalchemy import Engine, create_engine, insert, text
from sqlalchemy import func as sql

from apps.test_staff_me import header
from conftest import PostgresServer, login_engine, truncate_intake
from contracts.purchasing_contract import SUPPLIER_ALPHA
from invoicing.adapters.postgres.admin_queue import PostgresAdminQueueReader
from invoicing.adapters.postgres.engine import postgres_engine
from invoicing.adapters.postgres.schema import (
    admin_item,
    extraction_run,
    invoice,
    invoice_field,
)
from invoicing.adapters.principal import PRINCIPAL_HEADER
from invoicing.apps.staff_api.queue import queue_endpoint
from invoicing.ports.admin_queue import QueueListing, QueueQuery

pytestmark = pytest.mark.app("staff_api")

SUPPLIER_BETA = UUID("01a0c450-6c00-7b7b-8aa9-4ccade9f55b0")
ALPHA_NAME = "Synthetic Alpha Building Supplies"
BETA_NAME = "Synthetic Beta Traders"
T0 = datetime(2026, 9, 1, 1, 0, tzinfo=UTC)
CAP = 400


def _id(n: int) -> UUID:
    return UUID(f"0192f0c1-7a2b-7c3d-8e4f-{n:012x}")


def _routing(n: int) -> UUID:
    # UUIDv7-shaped: a later routing sorts after an earlier one.
    return UUID(f"0192f0c2-{n:04x}-7000-8000-000000000000")


class _Spy:
    """The real reader, counting reads (a refused call must read nothing)."""

    def __init__(self, reader: PostgresAdminQueueReader) -> None:
        self.reader = reader
        self.reads = 0

    async def read(self, query: QueueQuery) -> QueueListing:
        self.reads += 1
        return await self.reader.read(query)


class _Seed:
    def __init__(self, owner: Engine) -> None:
        self.owner = owner

    def invoice(
        self,
        n: int,
        *,
        status: str = "in_admin_queue",
        supplier_id: UUID = SUPPLIER_ALPHA,
    ) -> UUID:
        created = _id(n)
        at = T0 + timedelta(minutes=n)
        with self.owner.begin() as connection:
            connection.execute(
                insert(invoice).values(
                    id=created,
                    correlation_id=created,
                    source="link",
                    supplier_id=supplier_id,
                    content_type="image/jpeg",
                    device_check="passed",
                    status=status,
                    status_changed_at=at,
                    post_failures=0,
                    created_at=at,
                )
            )
        return created

    def reasons(self, invoice_id: UUID, routing: int, *reasons: str) -> None:
        with self.owner.begin() as connection:
            for k, reason in enumerate(reasons):
                connection.execute(
                    insert(admin_item).values(
                        id=UUID(int=routing * 100 + k),
                        invoice_id=invoice_id,
                        routing_id=_routing(routing),
                        reason=reason,
                        field_ids=[],
                        detail={},
                        created_at=sql.now(),
                    )
                )

    def total(self, invoice_id: UUID, n: int, *values: tuple[str, str]) -> None:
        """One run holding `invoice_total` rows as (value, source), oldest first."""
        run_id = UUID(int=n)
        with self.owner.begin() as connection:
            connection.execute(
                insert(extraction_run).values(
                    run_id=run_id,
                    invoice_id=invoice_id,
                    model_id="prebuilt-invoice",
                    api_version="2024-11-30",
                    pages=1,
                    created_at=T0,
                )
            )
            for k, (value, source) in enumerate(values):
                connection.execute(
                    insert(invoice_field).values(
                        id=UUID(int=n * 1000 + k),
                        invoice_id=invoice_id,
                        run_id=run_id,
                        field_id="invoice_total",
                        value_number=Decimal(value),
                        confidence=0.99,
                        source=source,
                        created_at=T0 + timedelta(seconds=k),
                    )
                )

    def pages(self, used: int) -> None:
        with self.owner.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO intake.di_usage (month, pages) VALUES"
                    " (date_trunc('month', timezone('UTC', now()))::date, :p)"
                    " ON CONFLICT (month) DO UPDATE SET pages = :p"
                ),
                {"p": used},
            )


def test_story_2_8_admin_queue(
    postgres_server: PostgresServer,
    intake_database: str,
    app_settings: dict[str, str],
    load_app: Callable[[str], ModuleType],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /api/admin/queue. Covers: the route is wired before the SPA catch-all; only
    queued invoices, oldest first, with supplier name, current amount and the latest
    routing's reasons; no run gives a null amount; 50 a page with the total; reason and
    supplier filters; page usage from 80 % of the cap; 400 for a bad query; 403 for a
    non-admin with nothing read; 401 signed out; 401 AUTH_DISABLED through the
    registered handler when built-in auth is off; 503 DB_OFFLINE when unreachable; the
    supplier filter's options are every queued invoice's supplier, by name."""
    # --- Wiring: the route exists, GET only, and the SPA catch-all stays last.
    module = load_app("staff_api")
    functions = list(module.app.get_functions())
    names = [fn.get_function_name() for fn in functions]
    assert names[-1] == "web_app" and "admin_queue" in names
    (trigger,) = [
        b.get_dict_repr()
        for b in functions[names.index("admin_queue")].get_bindings()
        if b.get_dict_repr()["type"] == "httpTrigger"
    ]
    assert trigger["route"] == "api/admin/queue"
    assert [getattr(m, "value", m) for m in trigger["methods"]] == ["GET"]  # type: ignore[attr-defined]  # a list here

    # --- In Azure with built-in auth off, the registered handler fails closed (AD-14).
    with monkeypatch.context() as env:
        env.setenv("WEBSITE_SITE_NAME", "babaloo-sea-lng-func-02")
        env.delenv("WEBSITE_AUTH_ENABLED", raising=False)
        untrusted = {
            fn.get_function_name(): fn
            for fn in load_app("staff_api").app.get_functions()
        }
        handler = untrusted["admin_queue"].get_user_function()
        response = asyncio.run(
            handler(
                func.HttpRequest(
                    method="GET",
                    url="/api/admin/queue",
                    headers={PRINCIPAL_HEADER: header("admin")},
                    body=b"",
                )
            )
        )
        assert response.status_code == 401
        assert json.loads(response.get_body())["code"] == "AUTH_DISABLED"

    truncate_intake(postgres_server, intake_database)
    owner = create_engine(
        postgres_server.url(postgres_server.deployer, intake_database)
    )
    staff = login_engine(postgres_server, postgres_server.staff_api, intake_database)
    seed = _Seed(owner)
    with owner.begin() as connection:
        for supplier_id, name in (
            (SUPPLIER_ALPHA, ALPHA_NAME),
            (SUPPLIER_BETA, BETA_NAME),
        ):
            connection.execute(
                text(
                    "INSERT INTO master.supplier (id, name) VALUES (:id, :name)"
                    " ON CONFLICT (id) DO UPDATE SET name = :name"
                ),
                {"id": supplier_id, "name": name},
            )
    spy = _Spy(PostgresAdminQueueReader(staff))
    endpoint = queue_endpoint(
        spy, page_cap=CAP, currency="SGD", platform_auth_trusted=True
    )

    def call(params: dict[str, str], *roles: str) -> tuple[int, Any]:
        headers = {PRINCIPAL_HEADER: header(*roles)} if roles else {}
        request = func.HttpRequest(
            method="GET",
            url="/api/admin/queue",
            headers=headers,
            params=params,
            body=b"",
        )
        response = asyncio.run(endpoint(request))
        return response.status_code, json.loads(response.get_body())

    try:
        # --- List, open reasons, no amount.
        seed.invoice(1, status="ready_to_post")  # the oldest, but not queued
        seed.reasons(_id(1), 1, "LOW_CONFIDENCE")
        first = seed.invoice(2)
        seed.reasons(first, 2, "LOW_CONFIDENCE", "BANK_CHANGED")
        seed.reasons(first, 3, "PO_MISMATCH")  # routed again: only this one is open
        # The admin's correction on the latest run wins (AD-18).
        seed.total(first, 2, ("1090.004", "di"), ("1100.5", "admin"))
        second = seed.invoice(3, supplier_id=SUPPLIER_BETA)  # no extraction run
        seed.reasons(second, 4, "BANK_CHANGED", "DUPLICATE")
        seed.pages(319)

        status, body = call({}, "admin")
        assert status == 200
        assert body == {
            "items": [
                {
                    "invoice_id": str(first),
                    "received_at": (T0 + timedelta(minutes=2)).isoformat(),
                    "supplier_id": str(SUPPLIER_ALPHA),
                    "supplier_name": ALPHA_NAME,
                    "amount": "1100.50",
                    "currency": "SGD",
                    "reasons": ["PO_MISMATCH"],
                },
                {
                    "invoice_id": str(second),
                    "received_at": (T0 + timedelta(minutes=3)).isoformat(),
                    "supplier_id": str(SUPPLIER_BETA),
                    "supplier_name": BETA_NAME,
                    "amount": None,
                    "currency": None,
                    "reasons": ["BANK_CHANGED", "DUPLICATE"],
                },
            ],
            "page": 1,
            "page_size": 50,
            "total": 2,
            # 319 of 400 is below 80 %.
            "page_usage": None,
            # Every queued invoice's supplier, by name (the ready_to_post one's is
            # Alpha too, so it adds nothing).
            "suppliers": [
                {"supplier_id": str(SUPPLIER_ALPHA), "supplier_name": ALPHA_NAME},
                {"supplier_id": str(SUPPLIER_BETA), "supplier_name": BETA_NAME},
            ],
        }

        # --- Filters: a reason among the open reasons only; a supplier.
        def ids(params: dict[str, str]) -> list[str]:
            status, body = call(params, "admin")
            assert status == 200, body
            return [item["invoice_id"] for item in body["items"]]

        assert ids({"reason": "BANK_CHANGED"}) == [str(second)]
        assert ids({"reason": "LOW_CONFIDENCE"}) == []
        assert ids({"reason": "PO_MISMATCH"}) == [str(first)]
        assert ids({"supplier_id": str(SUPPLIER_BETA)}) == [str(second)]
        assert ids({"supplier_id": str(SUPPLIER_BETA), "reason": "PO_MISMATCH"}) == []
        # The supplier options ignore the filters.
        _, filtered = call(
            {"supplier_id": str(SUPPLIER_BETA), "reason": "PO_MISMATCH"}, "admin"
        )
        assert [s["supplier_id"] for s in filtered["suppliers"]] == [
            str(SUPPLIER_ALPHA),
            str(SUPPLIER_BETA),
        ]

        # --- Page usage: from 80 % of the cap, the boundary included.
        seed.pages(320)
        assert call({}, "admin")[1]["page_usage"] == {
            "pages_used": 320,
            "page_cap": CAP,
        }
        seed.pages(322)
        assert call({}, "admin")[1]["page_usage"] == {
            "pages_used": 322,
            "page_cap": CAP,
        }

        # --- Paging: 51 queued, 50 a page, oldest first.
        for n in range(4, 53):
            seed.invoice(n)
        status, page_one = call({"page": "1"}, "admin")
        assert (status, page_one["total"], len(page_one["items"])) == (200, 51, 50)
        assert page_one["items"][0]["invoice_id"] == str(first)
        received = [item["received_at"] for item in page_one["items"]]
        assert received == sorted(received)
        status, page_two = call({"page": "2"}, "admin")
        assert (page_two["total"], page_two["page"]) == (51, 2)
        assert [item["invoice_id"] for item in page_two["items"]] == [str(_id(52))]

        # --- A bad query is 400, naming no value.
        for params in (
            {"page": "0"},
            {"page": "abc"},
            {"page": "1.5"},
            {"reason": "NOT_A_REASON"},
            {"supplier_id": "not-a-uuid"},
        ):
            status, body = call(params, "admin")
            assert (status, body["code"]) == (400, "VALIDATION_FAILED"), params
            assert next(iter(params.values())) not in body["message"]

        # --- Non-admin: 403, and nothing is read. Signed out: 401.
        reads = spy.reads
        for roles in (("finance",), ("goods_in", "management")):
            status, body = call({}, *roles)
            assert (status, body["code"]) == (403, "FORBIDDEN")
        status, body = call({})
        assert (status, body["code"]) == (401, "UNAUTHENTICATED")
        assert spy.reads == reads
    finally:
        staff.dispose()
        owner.dispose()

    # --- DB down: the existing 503 DB_OFFLINE mapping.
    unreachable = postgres_engine(
        host="127.0.0.1",
        port=1,
        database=intake_database,
        user=postgres_server.staff_api,
        password=lambda: "unused",
        sslmode="disable",
        pool_size=1,
    )
    try:
        offline = queue_endpoint(
            PostgresAdminQueueReader(unreachable),
            page_cap=CAP,
            currency="SGD",
            platform_auth_trusted=True,
        )
        request = func.HttpRequest(
            method="GET",
            url="/api/admin/queue",
            headers={PRINCIPAL_HEADER: header("admin")},
            body=b"",
        )
        response = asyncio.run(offline(request))
        assert response.status_code == 503
        assert json.loads(response.get_body())["code"] == "DB_OFFLINE"
    finally:
        unreachable.dispose()
