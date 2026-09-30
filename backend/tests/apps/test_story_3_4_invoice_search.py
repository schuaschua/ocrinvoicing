"""Story 3.4: `GET /api/invoices` and `GET /api/invoices/{invoice_id}` on staff-api
(AD-3, AD-11, AD-14, AD-18), against a real PostgreSQL 18 read as the staff-api login
(so the test also proves its grants). Synthetic data only (security.md rule 1).

One merged test (the 200-case cap, coding-style.md rule 20 exception): each plan
matrix row is a block of assertions, in order."""

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import ModuleType
from typing import Any
from uuid import UUID

import azure.functions as func
import pytest
from sqlalchemy import Engine, create_engine, insert, text

from apps.test_staff_me import OID, header
from conftest import PostgresServer, login_engine, truncate_intake
from contracts.purchasing_contract import SUPPLIER_ALPHA
from invoicing.adapters.postgres.invoice_search import PostgresInvoiceSearchReader
from invoicing.adapters.postgres.schema import (
    extraction_run,
    invoice,
    invoice_field,
    invoice_line,
    status_history,
)
from invoicing.adapters.principal import PRINCIPAL_HEADER
from invoicing.apps.staff_api.invoices import invoices_endpoints
from invoicing.domain.reference import supplier_reference
from invoicing.ports.invoice_search import InvoiceDetail, SearchListing, SearchQuery

pytestmark = pytest.mark.app("staff_api")

SUPPLIER_BETA = UUID("01a0c450-6c00-7b7b-8aa9-4ccade9f55b0")
ALPHA_NAME = "Synthetic Alpha Building Supplies"
BETA_NAME = "Synthetic Beta Traders"
T0 = datetime(2026, 9, 1, 1, 0, tzinfo=UTC)
FINGERPRINT = "ab" * 32


def _id(n: int, high: int = 0) -> UUID:
    # UUIDv7-shaped; `high` changes a byte above the reference's low 40 bits.
    return UUID(f"0192f0c1-7a2b-7c3d-8e4f-{high:02x}{n:010x}")


class _Spy:
    """The real reader, counting reads (a refused call must read nothing)."""

    def __init__(self, reader: PostgresInvoiceSearchReader) -> None:
        self.reader = reader
        self.reads = 0

    async def search(self, query: SearchQuery) -> SearchListing:
        self.reads += 1
        return await self.reader.search(query)

    async def detail(self, invoice_id: UUID) -> InvoiceDetail | None:
        self.reads += 1
        return await self.reader.detail(invoice_id)


class _Seed:
    def __init__(self, owner: Engine) -> None:
        self.owner = owner

    def invoice(
        self,
        invoice_id: UUID,
        minute: int,
        status: str,
        supplier_id: UUID = SUPPLIER_ALPHA,
        **extra: object,
    ) -> UUID:
        at = T0 + timedelta(minutes=minute)
        with self.owner.begin() as connection:
            connection.execute(
                insert(invoice).values(
                    id=invoice_id,
                    correlation_id=invoice_id,
                    source="link",
                    supplier_id=supplier_id,
                    content_type="image/jpeg",
                    device_check="passed",
                    status=status,
                    status_changed_at=at,
                    post_failures=0,
                    created_at=at,
                    **extra,
                )
            )
        return invoice_id

    def run(self, invoice_id: UUID, n: int, *fields: dict[str, Any]) -> None:
        """One run holding `fields` (field_id, source and one value each), in order."""
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
            for k, values in enumerate(fields):
                connection.execute(
                    insert(invoice_field).values(
                        id=UUID(int=n * 1000 + k),
                        invoice_id=invoice_id,
                        run_id=run_id,
                        confidence=0.99,
                        created_at=T0 + timedelta(seconds=k),
                        **{"source": "di", **values},
                    )
                )

    def line(self, invoice_id: UUID, n: int) -> None:
        with self.owner.begin() as connection:
            connection.execute(
                insert(invoice_line).values(
                    id=UUID(int=n * 1000 + 999),
                    invoice_id=invoice_id,
                    run_id=UUID(int=n),
                    line_no=1,
                    product_code="EVA-01",
                    description="EVA soles",
                    quantity=Decimal(10),
                    unit_price=Decimal("124.85"),
                    amount=Decimal("1248.50"),
                    confidence=0.99,
                    source="di",
                    created_at=T0,
                )
            )

    def history(self, invoice_id: UUID, *steps: tuple[str | None, str, str]) -> None:
        with self.owner.begin() as connection:
            for k, (from_status, to_status, actor) in enumerate(steps):
                connection.execute(
                    insert(status_history).values(
                        id=UUID(int=7000 + k),
                        invoice_id=invoice_id,
                        from_status=from_status,
                        to_status=to_status,
                        actor=actor,
                        at=T0 + timedelta(minutes=k),
                    )
                )


def test_story_3_4_invoice_search(
    postgres_server: PostgresServer,
    intake_database: str,
    app_settings: dict[str, str],
    load_app: Callable[[str], ModuleType],
) -> None:
    """GET /api/invoices and /api/invoices/{id}. Covers: both routes wired, GET only,
    before the SPA catch-all; newest first with received, supplier, number, total,
    status, reference and after-correction; supplier, status, invoice number (current
    value, normalised) and reference (any case, spaces, several matches) filters,
    combined; 50 a page with the total; 400 for a bad query naming no value; the
    detail's current fields, lines, history (actor categories only) and accounts
    reference; bank fields only as on file, never a value; 404 for an unknown id;
    finance allowed; other roles 403 on search and 404 on detail with nothing read;
    401 signed out."""
    # --- Wiring: both routes exist, GET only, and the SPA catch-all stays last.
    module = load_app("staff_api")
    functions = list(module.app.get_functions())
    names = [fn.get_function_name() for fn in functions]
    assert names[-1] == "web_app"
    for name, route in (
        ("invoice_search", "api/invoices"),
        ("invoice_detail", "api/invoices/{invoice_id}"),
    ):
        (trigger,) = [
            b.get_dict_repr()
            for b in functions[names.index(name)].get_bindings()
            if b.get_dict_repr()["type"] == "httpTrigger"
        ]
        assert trigger["route"] == route
        assert [getattr(m, "value", m) for m in trigger["methods"]] == ["GET"]  # type: ignore[attr-defined]  # a list here

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
    spy = _Spy(PostgresInvoiceSearchReader(staff))
    search, detail = invoices_endpoints(spy, currency="SGD", platform_auth_trusted=True)

    def call(
        endpoint: Any, url: str, params: dict[str, str], *roles: str, **route: str
    ) -> tuple[int, Any]:
        headers = {PRINCIPAL_HEADER: header(*roles)} if roles else {}
        request = func.HttpRequest(
            method="GET",
            url=url,
            headers=headers,
            params=params,
            route_params=route,
            body=b"",
        )
        response = asyncio.run(endpoint(request))
        return response.status_code, json.loads(response.get_body())

    def ids(params: dict[str, str], role: str = "finance") -> list[str]:
        status, body = call(search, "/api/invoices", params, role)
        assert status == 200, body
        return [item["invoice_id"] for item in body["items"]]

    def open_(invoice_id: str, *roles: str) -> tuple[int, Any]:
        return call(
            detail,
            f"/api/invoices/{invoice_id}",
            {},
            *roles,
            invoice_id=invoice_id,
        )

    try:
        posted_at = T0 + timedelta(hours=2)
        posted = seed.invoice(
            _id(1), 1, "posted", accounts_ref="ACC-000123", posted_at=posted_at
        )
        seed.run(
            posted,
            1,
            {"field_id": "invoice_number", "value_text": "INV 001"},
            {
                "field_id": "invoice_total",
                "value_number": Decimal("1248.5"),
                "currency": "SGD",
            },
            {"field_id": "invoice_date", "value_date": date(2026, 8, 30)},
            {
                "field_id": "payment[0].iban",
                "bank_ciphertext": b"\x01\x02",
                "bank_fingerprint": FINGERPRINT,
            },
        )
        seed.line(posted, 1)
        seed.history(
            posted,
            (None, "received", "pipeline:quality"),
            ("received", "awaiting_extraction", "pipeline:quality"),
            ("in_admin_queue", "ready_to_post", f"admin:{OID}"),
            ("posting", "posted", "pipeline:post"),
            ("posting", "ready_to_post", "sweeper"),
        )
        # Corrected by an admin: found by the new number only, and "Re-checking".
        rechecking = seed.invoice(_id(2), 2, "awaiting_validation", SUPPLIER_BETA)
        seed.run(
            rechecking,
            2,
            {"field_id": "invoice_number", "value_text": "INV-001"},
            {"field_id": "invoice_number", "value_text": "inv-002", "source": "admin"},
            # No currency stored: the configured one is sent.
            {"field_id": "invoice_total", "value_number": Decimal(90)},
        )
        queued = seed.invoice(_id(3), 3, "in_admin_queue")  # no run
        # Shares the posted invoice's reference (same low 40 bits).
        twin = seed.invoice(_id(1, high=1), 4, "rejected", SUPPLIER_BETA)

        # --- Search: newest first, every column.
        status, body = call(search, "/api/invoices", {}, "admin")
        assert status == 200
        assert [item["invoice_id"] for item in body["items"]] == [
            str(twin),
            str(queued),
            str(rechecking),
            str(posted),
        ]
        assert body["items"][3] == {
            "invoice_id": str(posted),
            "reference": supplier_reference(posted),
            "received_at": (T0 + timedelta(minutes=1)).isoformat(),
            "supplier_id": str(SUPPLIER_ALPHA),
            "supplier_name": ALPHA_NAME,
            "invoice_number": "INV 001",
            "amount": "1248.50",
            "currency": "SGD",
            "status": "posted",
            "after_correction": False,
        }
        assert body["items"][2]["invoice_number"] == "inv-002"
        assert body["items"][2]["after_correction"] is True
        assert (body["items"][2]["amount"], body["items"][2]["currency"]) == (
            "90.00",
            "SGD",
        )
        assert (body["items"][1]["invoice_number"], body["items"][1]["amount"]) == (
            None,
            None,
        )
        assert (body["page"], body["page_size"], body["total"]) == (1, 50, 4)
        assert body["suppliers"] == [
            {"supplier_id": str(SUPPLIER_ALPHA), "supplier_name": ALPHA_NAME},
            {"supplier_id": str(SUPPLIER_BETA), "supplier_name": BETA_NAME},
        ]
        assert supplier_reference(twin) == supplier_reference(posted)

        # --- Filters, alone and combined.
        assert ids({"supplier_id": str(SUPPLIER_ALPHA)}) == [str(queued), str(posted)]
        # The supplier options ignore the filters.
        _, filtered = call(
            search,
            "/api/invoices",
            {"supplier_id": str(SUPPLIER_BETA), "status": "posted"},
            "admin",
        )
        assert filtered["items"] == []
        assert [s["supplier_id"] for s in filtered["suppliers"]] == [
            str(SUPPLIER_ALPHA),
            str(SUPPLIER_BETA),
        ]
        # The configured currency fills a total stored without one; a stored one wins.
        other_search, _ = invoices_endpoints(
            spy, currency="SGX", platform_auth_trusted=True
        )
        _, other = call(other_search, "/api/invoices", {}, "finance")
        assert [item["currency"] for item in other["items"]] == [
            None,
            None,
            "SGX",
            "SGD",
        ]
        assert ids({"status": "posted"}) == [str(posted)]
        assert ids({"status": "awaiting_validation,validating"}) == [str(rechecking)]
        assert ids({"invoice_number": "inv-001"}) == [str(posted)]
        assert ids({"invoice_number": " INV002 "}) == [str(rechecking)]
        reference = supplier_reference(posted)
        assert ids({"reference": f"  {reference.lower()} "}) == [str(twin), str(posted)]
        assert ids({"reference": reference[2:]}) == [str(twin), str(posted)]
        assert ids({"reference": reference, "supplier_id": str(SUPPLIER_BETA)}) == [
            str(twin)
        ]
        assert ids({"reference": reference, "status": "in_admin_queue"}) == []

        # --- A bad query is 400, naming no value.
        for params in (
            {"page": "0"},
            {"page": "x"},
            {"status": "posted,nope"},
            {"supplier_id": "not-a-uuid"},
            {"reference": "R-1234"},
            {"reference": "R-ILOU1234"},
            {"invoice_number": "--"},
            {"invoice_number": "Z" * 65},
        ):
            status, body = call(search, "/api/invoices", params, "admin")
            assert (status, body["code"]) == (400, "VALIDATION_FAILED"), params
            assert next(iter(params.values())) not in body["message"]

        # --- Detail: current fields (no bank value), lines, history, accounts ref.
        status, body = open_(str(posted), "finance")
        assert status == 200
        assert body == {
            "invoice_id": str(posted),
            "reference": reference,
            "received_at": (T0 + timedelta(minutes=1)).isoformat(),
            "supplier_id": str(SUPPLIER_ALPHA),
            "supplier_name": ALPHA_NAME,
            "status": "posted",
            "after_correction": False,
            "accounts_ref": "ACC-000123",
            "posted_at": posted_at.isoformat(),
            "fields": [
                {"field_id": "invoice_date", "value": "2026-08-30", "currency": None},
                {"field_id": "invoice_number", "value": "INV 001", "currency": None},
                {"field_id": "invoice_total", "value": "1248.50", "currency": "SGD"},
            ],
            "bank_on_file": True,
            "lines": [
                {
                    "line_no": 1,
                    "product_code": "EVA-01",
                    "description": "EVA soles",
                    "quantity": "10",
                    "unit_price": "124.85",
                    "amount": "1248.50",
                }
            ],
            "history": [
                {
                    "from_status": None,
                    "to_status": "received",
                    "at": T0.isoformat(),
                    "actor": "quality",
                },
                {
                    "from_status": "received",
                    "to_status": "awaiting_extraction",
                    "at": (T0 + timedelta(minutes=1)).isoformat(),
                    "actor": "quality",
                },
                {
                    "from_status": "in_admin_queue",
                    "to_status": "ready_to_post",
                    "at": (T0 + timedelta(minutes=2)).isoformat(),
                    "actor": "admin",
                },
                {
                    "from_status": "posting",
                    "to_status": "posted",
                    "at": (T0 + timedelta(minutes=3)).isoformat(),
                    "actor": "post",
                },
                {
                    "from_status": "posting",
                    "to_status": "ready_to_post",
                    "at": (T0 + timedelta(minutes=4)).isoformat(),
                    "actor": "system",
                },
            ],
        }
        # Never a bank value or field id, nor the admin's identity (AD-11).
        raw = json.dumps(body)
        assert "iban" not in raw and FINGERPRINT not in raw and OID not in raw
        status, body = open_(str(rechecking), "admin")
        assert (status, body["after_correction"], body["bank_on_file"]) == (
            200,
            True,
            False,
        )
        assert body["fields"] == [
            {"field_id": "invoice_number", "value": "inv-002", "currency": None},
            {"field_id": "invoice_total", "value": "90.00", "currency": None},
        ]
        status, body = open_(str(queued), "admin")
        assert (status, body["fields"], body["lines"], body["history"]) == (
            200,
            [],
            [],
            [],
        )
        for unknown in (str(_id(99)), "not-a-uuid"):
            status, body = open_(unknown, "admin")
            assert (status, body["code"]) == (404, "NOT_FOUND")

        # --- Paging: 54 invoices, 50 a page, newest first.
        for n in range(10, 60):
            seed.invoice(_id(n), n, "received")
        status, page_one = call(search, "/api/invoices", {"page": "1"}, "admin")
        assert (page_one["total"], len(page_one["items"])) == (54, 50)
        received = [item["received_at"] for item in page_one["items"]]
        assert received == sorted(received, reverse=True)
        status, page_two = call(search, "/api/invoices", {"page": "2"}, "admin")
        assert [item["invoice_id"] for item in page_two["items"]] == [
            str(twin),
            str(queued),
            str(rechecking),
            str(posted),
        ]

        # --- Other roles: 403 on search, 404 on detail, nothing read. Signed out: 401.
        reads = spy.reads
        for roles in (("goods_in",), ("procurement", "management")):
            status, body = call(search, "/api/invoices", {}, *roles)
            assert (status, body["code"]) == (403, "FORBIDDEN")
            status, body = open_(str(posted), *roles)
            assert (status, body["code"]) == (404, "NOT_FOUND")
        for status, body in (
            call(search, "/api/invoices", {}),
            open_(str(posted)),
        ):
            assert (status, body["code"]) == (401, "UNAUTHENTICATED")
        assert spy.reads == reads
    finally:
        staff.dispose()
        owner.dispose()
