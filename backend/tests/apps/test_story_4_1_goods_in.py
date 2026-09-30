"""Story 4.1: goods-in scan on staff-api (AD-5, AD-6, AD-10, AD-14): the delivery list
and search, and the upload against a delivery. Purchasing and the supplier master are a
real PostgreSQL 18 read as the staff-api login (so the test also proves its grants);
fakes stand in for `uploadkeys`, `images` and `q-quality` (coding-style.md rule 23).
Synthetic data only (security.md rule 1).

One merged test (the 200-case cap, coding-style.md rule 20 exception): each plan
matrix row is a block of assertions, in order."""

import asyncio
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from types import ModuleType
from typing import Any
from uuid import UUID

import azure.functions as func
import pytest
from sqlalchemy import create_engine, text

from apps._pipeline_fakes import stopped_database
from apps.test_staff_me import header
from apps.test_supplier_upload import Storage
from conftest import PostgresServer, login_engine
from contracts.purchasing_contract import (
    DELIVERY_12_1,
    DELIVERY_12_2,
    DELIVERY_13_1,
    DELIVERY_16_1,
    DELIVERY_17_1,
    SUPPLIER_ALPHA,
)
from invoicing.adapters.postgres.suppliers import PostgresSupplierDirectory
from invoicing.adapters.principal import CSRF_HEADER, CSRF_VALUE, PRINCIPAL_HEADER
from invoicing.adapters.purchasing_factory import purchasing_port
from invoicing.apps.staff_api.goods_in import goods_in_endpoints
from invoicing.ports.intake import IntakeSource
from invoicing.ports.queue import QueueName

pytestmark = pytest.mark.app("staff_api")

SUPPLIER_BETA = UUID("01a0c450-6fe8-7cb7-9e60-74d841e2024a")
SUPPLIER_GAMMA = UUID("01a0c450-73d0-7ee3-94ca-ef9fef9d793d")
NAMES = {
    SUPPLIER_ALPHA: "Synthetic Alpha Building Supplies",
    SUPPLIER_BETA: "Synthetic Beta Hardware Trading",
    SUPPLIER_GAMMA: "Synthetic Gamma Construction Materials",
}
# 1am on 29 September in Singapore, still the 28th in UTC: "today" is Singapore's.
NOW = datetime(2026, 9, 28, 17, 0, tzinfo=UTC)
KEY = "5b0f3c2e-8a41-4d7e-9c55-3e2f1a0b9c7d"
# The paper invoice claims another supplier; the delivery decides (AD-5).
PDF = b"%PDF-1.7\n% Invoice from Synthetic Gamma Construction Materials\n" + b"\0" * 64
MB = 1024 * 1024


def test_story_4_1_goods_in_scan(
    postgres_server: PostgresServer,
    purchasing_seeded: str,
    app_settings: dict[str, str],
    load_app: Callable[[str], ModuleType],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """GET api/goods-in/deliveries and POST .../{delivery_id}/upload. Covers: both
    routes wired before the SPA catch-all; today's deliveries (Singapore date) with
    PO, supplier and delivery number; search by PO prefix or supplier name (any
    case, last 60 days, newest first), 400 under 2 characters; a send takes the
    supplier from the delivery even when the invoice or the request claims another,
    in key, blob, q-quality order with source goods_in and the delivery; a retry is
    the same invoice; key reuse for another delivery or bytes is 409; an unknown
    delivery is 404 DELIVERY_NOT_FOUND; a stopped database is 503 DB_OFFLINE; all
    with nothing written; other roles 403, signed out 401, no CSRF header 403; file
    limits 413, 415 and 400; no search text or name in the logs."""
    # --- Wiring: both routes, their methods, and the SPA catch-all stays last.
    module = load_app("staff_api")
    functions = list(module.app.get_functions())
    names = [fn.get_function_name() for fn in functions]
    assert names[-1] == "web_app"
    for name, route, method in (
        ("goods_in_deliveries", "api/goods-in/deliveries", "GET"),
        ("goods_in_upload", "api/goods-in/deliveries/{delivery_id}/upload", "POST"),
    ):
        (trigger,) = [
            b.get_dict_repr()
            for b in functions[names.index(name)].get_bindings()
            if b.get_dict_repr()["type"] == "httpTrigger"
        ]
        assert trigger["route"] == route
        assert [getattr(m, "value", m) for m in trigger["methods"]] == [method]  # type: ignore[attr-defined]  # a list here

    owner = create_engine(
        postgres_server.url(postgres_server.deployer, purchasing_seeded)
    )
    with owner.begin() as connection:
        for supplier_id, supplier_name in NAMES.items():
            connection.execute(
                text(
                    "INSERT INTO master.supplier (id, name) VALUES (:id, :name)"
                    " ON CONFLICT (id) DO UPDATE SET name = :name"
                ),
                {"id": supplier_id, "name": supplier_name},
            )
    owner.dispose()
    staff = login_engine(postgres_server, postgres_server.staff_api, purchasing_seeded)
    storage = Storage()

    def endpoints(engine: Any, now: datetime = NOW) -> tuple[Any, Any]:
        return goods_in_endpoints(
            purchasing_port("sim", engine),
            PostgresSupplierDirectory(engine),
            lambda: storage,
            lambda: storage,
            lambda: storage,
            platform_auth_trusted=True,
            clock=lambda: now,
        )

    deliveries, upload = endpoints(staff)

    def listing(
        params: dict[str, str], *roles: str, endpoint: Any = None
    ) -> tuple[int, Any]:
        headers = {PRINCIPAL_HEADER: header(*roles)} if roles else {}
        request = func.HttpRequest(
            method="GET",
            url="/api/goods-in/deliveries",
            headers=headers,
            params=params,
            body=b"",
        )
        response = asyncio.run((endpoint or deliveries)(request))
        return response.status_code, json.loads(response.get_body())

    def found(q: str, endpoint: Any = None) -> list[str]:
        status, body = listing({"q": q}, "goods_in", endpoint=endpoint)
        assert status == 200, body
        return [item["delivery_id"] for item in body["items"]]

    def send(
        delivery_id: str,
        body: bytes = PDF,
        *,
        roles: tuple[str, ...] = ("goods_in",),
        key: str = KEY,
        csrf: bool = True,
        endpoint: Any = None,
    ) -> tuple[int, Any]:
        headers = {"Idempotency-Key": key, "Content-Length": str(len(body))}
        if roles:
            headers[PRINCIPAL_HEADER] = header(*roles)
        if csrf:
            headers[CSRF_HEADER] = CSRF_VALUE
        # A supplier in the request is never read.
        headers["X-Supplier-Id"] = str(SUPPLIER_GAMMA)
        request = func.HttpRequest(
            method="POST",
            url=f"/api/goods-in/deliveries/{delivery_id}/upload",
            headers=headers,
            params={"supplier_id": str(SUPPLIER_GAMMA)},
            route_params={"delivery_id": delivery_id},
            body=body,
        )
        response = asyncio.run((endpoint or upload)(request))
        return response.status_code, json.loads(response.get_body())

    try:
        with caplog.at_level(logging.DEBUG):
            # --- Open: today's deliveries, by Singapore date.
            status, body = listing({}, "goods_in")
            assert status == 200
            assert body == {
                "today": "2026-09-29",
                "items": [
                    {
                        "delivery_id": str(DELIVERY_16_1),
                        "po_number": "PO-45016",
                        "delivery_no": 1,
                        "delivery_date": "2026-09-29",
                        "supplier_name": NAMES[SUPPLIER_GAMMA],
                    }
                ],
            }

            # --- Search: PO prefix or supplier name, any case, newest first.
            assert found(" po-4501 ") == [
                str(DELIVERY_16_1),
                str(DELIVERY_17_1),
                str(DELIVERY_12_2),
                str(DELIVERY_13_1),
                str(DELIVERY_12_1),
            ]
            # 40 days on, the window starts 8 September: PO-45012's first delivery
            # (2 September) and PO-45013's (7 September) are out of it.
            later, _ = endpoints(staff, NOW + timedelta(days=40))
            assert found("po-4501", later) == [
                str(DELIVERY_16_1),
                str(DELIVERY_17_1),
                str(DELIVERY_12_2),
            ]
            assert found("gAmMa") == [str(DELIVERY_16_1)]
            assert found("beta hardware") == [str(DELIVERY_13_1)]
            assert found("%%") == []
            for short in ("x", "  y  ", "z" * 65):
                status, body = listing({"q": short}, "goods_in")
                assert (status, body["code"]) == (400, "VALIDATION_FAILED")

            # --- Send: the delivery's supplier, key then blob then q-quality.
            status, body = send(str(DELIVERY_12_2))
            assert status == 200, body
            invoice_id = UUID(body["invoice_id"])
            assert body == {
                "invoice_id": str(invoice_id),
                "po_number": "PO-45012",
                "supplier_name": NAMES[SUPPLIER_ALPHA],
            }
            assert storage.writes == ["key", "blob", "queue"]
            stored = storage.keys[UUID(KEY)]
            assert (stored.supplier_id, stored.source, stored.delivery_id) == (
                SUPPLIER_ALPHA,
                IntakeSource.GOODS_IN,
                DELIVERY_12_2,
            )
            data, metadata = storage.blobs[invoice_id]
            assert data == PDF
            assert metadata.to_blob_metadata() == {
                "invoice_id": str(invoice_id),
                "source": "goods_in",
                "supplier_id": str(SUPPLIER_ALPHA),
                "delivery_id": str(DELIVERY_12_2),
                "content_type": "application/pdf",
                "uploaded_at": "2026-09-28T17:00:00.000000Z",
                "device_check": "passed",
            }
            ((queue, message),) = storage.messages
            assert (queue, message.invoice_id) == (QueueName.QUALITY, invoice_id)

            # --- Retry: the same invoice, no second key or blob.
            status, again = send(str(DELIVERY_12_2))
            assert (status, again["invoice_id"]) == (200, str(invoice_id))
            assert storage.writes == ["key", "blob", "queue", "queue"]

            # --- Key reuse for another delivery or other bytes: 409, nothing written.
            writes = list(storage.writes)
            for other in (
                send(str(DELIVERY_13_1)),
                send(str(DELIVERY_12_2), PDF + b"more"),
            ):
                assert (other[0], other[1]["code"]) == (409, "IDEMPOTENCY_KEY_CONFLICT")
            assert storage.writes == writes

            # --- Unknown or malformed delivery: 404, nothing written.
            fresh = "0c1d2e3f-4a5b-4c6d-8e7f-000000000001"
            for unknown in ("0192f0c1-7a2b-7c3d-8e4f-0000000000dd", "nope"):
                status, body = send(unknown, key=fresh)
                assert (status, body["code"]) == (404, "DELIVERY_NOT_FOUND")
            # The delivery is looked up before the file is checked.
            status, body = send("nope", b"GIF89a", key=fresh)
            assert (status, body["code"]) == (404, "DELIVERY_NOT_FOUND")
            # --- Wrong role, signed out, or no CSRF header: refused before any read.
            for roles in (("admin",), ("finance", "procurement")):
                assert listing({}, *roles)[0] == 403
                status, body = send(str(DELIVERY_12_2), roles=roles, key=fresh)
                assert (status, body["code"]) == (403, "FORBIDDEN")
            assert listing({})[1]["code"] == "UNAUTHENTICATED"
            assert send(str(DELIVERY_12_2), roles=(), key=fresh)[0] == 401
            assert send(str(DELIVERY_12_2), csrf=False, key=fresh)[0] == 403
            # --- Bad files: 413, 415, 400.
            for bad, expected in (
                (b"\xff\xd8\xff" + b"\0" * (4 * MB), 413),
                (b"GIF89a" + b"\0" * 64, 415),
                (b"", 400),
            ):
                assert send(str(DELIVERY_12_2), bad, key=fresh)[0] == expected
            assert storage.writes == writes

            # --- Database stopped, on open and on send: 503 DB_OFFLINE, nothing written.
            with stopped_database() as stopped:
                offline_list, offline_send = endpoints(stopped)
                status, body = listing({}, "goods_in", endpoint=offline_list)
                assert (status, body["code"]) == (503, "DB_OFFLINE")
                status, body = send(
                    str(DELIVERY_12_2), key=fresh, endpoint=offline_send
                )
                assert (status, body["code"]) == (503, "DB_OFFLINE")
            assert storage.writes == writes

        # --- Never a search text, a name or the key in the logs.
        logged = " ".join(
            f"{record.getMessage()} {vars(record)}"
            for record in caplog.records
            if record.name.startswith("invoicing")
        )
        assert "upload.accepted" in logged
        assert f"delivery_id={DELIVERY_12_2}" in logged
        for secret in ("gAmMa", "beta hardware", "Synthetic", KEY, "PO-45012"):
            assert secret not in logged
    finally:
        staff.dispose()
