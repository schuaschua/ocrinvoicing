"""Story 2.10: the admin actions on staff-api (AD-3, AD-4, AD-11, AD-18), against a real
PostgreSQL 18 written as the staff-api login (so the test also proves its grants), a
fake queue and a fake `corrections` container under the real blob adapter. Synthetic
data only (security.md rule 1).

One merged test (the 200-case cap, coding-style.md rule 20 exception): each plan
matrix row is a block of assertions, in order."""

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import ModuleType
from typing import Any
from uuid import UUID, uuid4

import azure.functions as func
import pytest
from azure.core.exceptions import ServiceRequestError
from sqlalchemy import Engine, create_engine, insert, select, text
from sqlalchemy import func as sql

from _pgp import make_test_key_pair
from apps._pipeline_fakes import FakeQueue
from apps.test_staff_me import OID, header
from conftest import PostgresServer, login_engine, truncate_intake
from invoicing.adapters.blob_corrections import BlobCorrectionsStore
from invoicing.adapters.postgres.admin_actions import PostgresAdminActions
from invoicing.adapters.postgres.admin_item import PostgresAdminItemReader
from invoicing.adapters.postgres.admin_queue import PostgresAdminQueueReader
from invoicing.adapters.postgres.schema import (
    admin_item,
    extraction_run,
    invoice,
    invoice_field,
    invoice_line,
    status_history,
)
from invoicing.adapters.principal import PRINCIPAL_HEADER
from invoicing.apps.staff_api.actions import action_endpoints
from invoicing.apps.staff_api.item import item_endpoints
from invoicing.apps.staff_api.queue import queue_endpoint
from invoicing.domain.errors import ServiceUnavailableError
from invoicing.ports.admin_actions import ActionResult
from invoicing.ports.messages import QueueMessage
from invoicing.ports.queue import QueueName

pytestmark = pytest.mark.app("staff_api")

T0 = datetime(2026, 9, 1, 1, 0, tzinfo=UTC)
NOW = datetime(2026, 9, 30, 2, 0, tzinfo=UTC)
SUPPLIER = UUID("01a0c450-6c00-7b7b-8aa9-4ccade9f5c31")
PHONE = "+65 6000 0110"
IBAN = "SG12ABCD00009930"
PO_LINE, MATERIAL = UUID(int=501), UUID(int=502)
CSRF = {"X-Requested-With": "XMLHttpRequest"}
REASON = "Could not verify bank change"
# The routing each seeded invoice is queued under (one per invoice).
ROUTING = {
    key: UUID(f"0192f0c3-{n:04x}-7000-8000-000000000000")
    for n, key in enumerate(
        (
            "correct",
            "reextract",
            "retry",
            "unreadable",
            "accounts",
            "unsupported",
            "old_run",
            "line_only",
        ),
        start=1,
    )
}


def _id(n: int) -> UUID:
    return UUID(f"0192f0c1-7a2b-7c3d-8e4f-{n:012x}")


def _routing(n: int) -> UUID:
    return UUID(f"0192f0c3-{n:04x}-7000-8000-000000000000")


class _Container:
    """The `corrections` container: records uploads, or fails them all."""

    def __init__(self) -> None:
        self.blobs: dict[str, tuple[bytes, dict[str, Any]]] = {}
        self.fail = False

    async def upload_blob(self, name: str, data: bytes, **kwargs: Any) -> None:
        if self.fail:
            raise ServiceRequestError("synthetic outage")
        self.blobs[name] = (data, kwargs)

    async def close(self) -> None:
        return None


class _Spy:
    """The real actions, counting calls (a refused call must reach nothing)."""

    def __init__(self, actions: PostgresAdminActions) -> None:
        self.actions = actions
        self.calls = 0

    async def correct(self, *args: Any) -> ActionResult:
        self.calls += 1
        return await self.actions.correct(*args)

    async def reextract(self, *args: Any) -> ActionResult:
        self.calls += 1
        return await self.actions.reextract(*args)

    async def retry_intake(self, *args: Any) -> ActionResult:
        self.calls += 1
        return await self.actions.retry_intake(*args)

    async def reject(self, *args: Any) -> ActionResult:
        self.calls += 1
        return await self.actions.reject(*args)

    async def approve(self, *args: Any) -> ActionResult:
        self.calls += 1
        return await self.actions.approve(*args)


def _seed(owner: Engine, public_key: str) -> dict[str, UUID]:
    """One queued invoice per action path (plus a posted-to-accounts one)."""
    ids = {
        "correct": _id(1),
        "reextract": _id(2),
        "retry": _id(3),
        "unreadable": _id(4),
        "accounts": _id(5),
        "unsupported": _id(6),
        # Queue flags only: admin rows on an older run; a line-only correction.
        "old_run": _id(7),
        "line_only": _id(8),
    }
    run = UUID(int=40)
    with owner.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO master.supplier (id, name, phone) VALUES (:id, :name, :p)"
                " ON CONFLICT (id) DO UPDATE SET phone = :p"
            ),
            {"id": SUPPLIER, "name": "Synthetic Tampines Soles", "p": PHONE},
        )
        for n, (key, invoice_id) in enumerate(ids.items()):
            connection.execute(
                insert(invoice).values(
                    id=invoice_id,
                    correlation_id=UUID(int=900 + n),
                    source="link",
                    supplier_id=SUPPLIER,
                    content_type="image/jpeg",
                    device_check="passed",
                    status="in_admin_queue",
                    status_changed_at=T0,
                    post_failures=0,
                    accounts_ref="ACC-1" if key == "accounts" else None,
                    created_at=T0 + timedelta(minutes=n),
                )
            )
            if key != "retry":
                # The quality stage completed for all but the Retry intake one.
                connection.execute(
                    insert(status_history).values(
                        id=uuid4(),
                        invoice_id=invoice_id,
                        from_status="received",
                        to_status="awaiting_extraction",
                        actor="pipeline:quality",
                        at=T0,
                    )
                )
        connection.execute(
            insert(extraction_run).values(
                run_id=run,
                invoice_id=ids["correct"],
                model_id="prebuilt-invoice",
                api_version="2024-11-30",
                pages=1,
                created_at=T0,
            )
        )
        for run_id, owner_key, minutes in (
            (UUID(int=41), "old_run", 0),
            (UUID(int=42), "old_run", 60),
            (UUID(int=43), "line_only", 0),
        ):
            connection.execute(
                insert(extraction_run).values(
                    run_id=run_id,
                    invoice_id=ids[owner_key],
                    model_id="prebuilt-invoice",
                    api_version="2024-11-30",
                    pages=1,
                    created_at=T0 + timedelta(minutes=minutes),
                )
            )
        for run_id, owner_key, source in (
            (UUID(int=41), "old_run", "admin"),  # an older run: not current
            (UUID(int=42), "old_run", "di"),
        ):
            connection.execute(
                insert(invoice_field).values(
                    id=uuid4(),
                    invoice_id=ids[owner_key],
                    run_id=run_id,
                    field_id="invoice_total",
                    value_number=Decimal(1),
                    confidence=1.0,
                    source=source,
                    created_at=T0,
                )
            )
        for source in ("di", "admin"):
            connection.execute(
                insert(invoice_line).values(
                    id=uuid4(),
                    invoice_id=ids["line_only"],
                    run_id=UUID(int=43),
                    line_no=1,
                    confidence=1.0,
                    source=source,
                    created_at=T0,
                )
            )
        base = {"invoice_id": ids["correct"], "run_id": run, "source": "di"}
        for values in (
            {
                "field_id": "invoice_total",
                "value_number": Decimal("190.00"),
                "currency": "SGD",
                "confidence": 0.9,
                "page": 1,
                "polygon": [1, 2, 3, 2, 3, 4, 1, 4],
            },
            {
                "field_id": "vendor_name",
                "value_text": "Synth Tampines",
                "confidence": 0.99,
            },
            {
                "field_id": "payment[0].iban",
                "bank_ciphertext": sql.pgp_pub_encrypt(IBAN, sql.dearmor(public_key)),
                "bank_fingerprint": "0" * 64,
                "confidence": 0.99,
            },
        ):
            connection.execute(
                insert(invoice_field).values(
                    id=uuid4(), created_at=T0, **base, **values
                )
            )
        connection.execute(
            insert(invoice_line).values(
                id=uuid4(),
                line_no=1,
                product_code="EVA-0l",
                description="EVA soles",
                quantity=Decimal(10),
                unit="pair",
                unit_price=Decimal("10.90"),
                amount=Decimal("109.00"),
                tax=Decimal("8.72"),
                confidence=0.4,
                po_line_id=PO_LINE,
                material_id=MATERIAL,
                created_at=T0,
                **base,
            )
        )
        for k, (key, reason) in enumerate(
            (
                ("correct", "LOW_CONFIDENCE"),
                ("correct", "BANK_CHANGED"),
                ("reextract", "EXTRACTION_QUOTA"),
                ("retry", "PROCESSING_FAILED"),
                ("unreadable", "UNREADABLE"),
                ("accounts", "ACCOUNTS_API_ERROR"),
                ("unsupported", "UNSUPPORTED_DOCUMENT"),
                ("old_run", "PO_MISMATCH"),
                ("line_only", "PO_MISMATCH"),
            )
        ):
            connection.execute(
                insert(admin_item).values(
                    id=UUID(int=200 + k),
                    invoice_id=ids[key],
                    routing_id=ROUTING[key],
                    run_id=run if key == "correct" else None,
                    reason=reason,
                    field_ids=(
                        ["payment[0].iban"]
                        if reason == "BANK_CHANGED"
                        else ["invoice_total", "line[1].product_code"]
                        if key == "correct"
                        else []
                    ),
                    detail={},
                    created_at=sql.now(),
                )
            )
    return ids


def test_story_2_10_admin_actions(
    postgres_server: PostgresServer,
    intake_database: str,
    app_settings: dict[str, str],
    load_app: Callable[[str], ModuleType],
) -> None:
    """The admin actions. Covers: the four POST routes are wired before the SPA
    catch-all; the item lists the guard's actions and the phone for UNREADABLE;
    Correct writes admin rows (confidence 1.0, latest run, a complete line row, never
    an update) and moves to awaiting_validation in one transaction, then enqueues
    q-validate and writes the corrections blob with no bank data; a bank field is 400
    with nothing written; Re-extract and Retry intake move and enqueue; Reject audits
    its reason; accounts_ref and a disallowed action are 409 ACTION_NOT_ALLOWED; a
    second admin gets 409 CONFLICT; audit rows hold ids only; a failed blob write or
    enqueue never undoes the commit; the queue marks a returned correction (current
    run only, lines too); a stale or missing routing_id and nested JSON are refused;
    Reject enqueues nothing; non-admin, unknown and no-CSRF calls reach nothing."""
    # --- Wiring: four POST routes, and the SPA catch-all stays last.
    module = load_app("staff_api")
    functions = list(module.app.get_functions())
    assert functions[-1].get_function_name() == "web_app"
    routes = {}
    for fn in functions:
        (trigger,) = [
            b.get_dict_repr()
            for b in fn.get_bindings()
            if b.get_dict_repr()["type"] == "httpTrigger"
        ]
        methods = [getattr(m, "value", m) for m in trigger["methods"]]  # type: ignore[attr-defined]  # a list here
        routes[fn.get_function_name()] = (trigger["route"], methods)
    for name, suffix in (
        ("admin_correct", "correct"),
        ("admin_reextract", "reextract"),
        ("admin_retry_intake", "retry-intake"),
        ("admin_reject", "reject"),
    ):
        assert routes[name] == (f"api/admin/items/{{invoice_id}}/{suffix}", ["POST"])

    keys = make_test_key_pair()
    truncate_intake(postgres_server, intake_database)
    owner = create_engine(
        postgres_server.url(postgres_server.deployer, intake_database)
    )
    staff = login_engine(postgres_server, postgres_server.staff_api, intake_database)
    ids = _seed(owner, keys.public_key)
    queue = FakeQueue()
    container = _Container()
    spy = _Spy(PostgresAdminActions(staff, currency="SGD"))
    correct_api, reextract_api, retry_api, reject_api, _ = action_endpoints(
        spy,
        lambda: queue,
        lambda: BlobCorrectionsStore(container),
        platform_auth_trusted=True,
        clock=lambda: NOW,
    )
    item_api, _, _, _ = item_endpoints(
        PostgresAdminItemReader(staff, lambda: keys.private_key),
        _NoImages(),
        platform_auth_trusted=True,
    )
    queue_api = queue_endpoint(
        PostgresAdminQueueReader(staff),
        page_cap=100,
        currency="SGD",
        platform_auth_trusted=True,
    )

    routing_of = {str(ids[key]): routing for key, routing in ROUTING.items()}

    def call(
        endpoint: Any,
        invoice_id: object,
        body: object = None,
        roles: tuple[str, ...] = ("admin",),
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        if isinstance(body, dict) and "routing_id" not in body:
            # The routing the admin's page shows (Story 2.10 stale-page guard).
            seen = routing_of.get(str(invoice_id))
            body = {**body, "routing_id": None if seen is None else str(seen)}
        all_headers = {PRINCIPAL_HEADER: header(*roles), **CSRF}
        if headers is not None:
            all_headers = {PRINCIPAL_HEADER: header(*roles), **headers}
        response = asyncio.run(
            endpoint(
                func.HttpRequest(
                    method="GET" if body is None else "POST",
                    url=f"/api/admin/items/{invoice_id}",
                    headers=all_headers,
                    route_params={"invoice_id": str(invoice_id)},
                    params={},
                    body=b"" if body is None else json.dumps(body).encode(),
                )
            )
        )
        return response.status_code, json.loads(response.get_body())

    def status_of(invoice_id: UUID) -> str:
        with owner.connect() as connection:
            return str(
                connection.execute(
                    select(invoice.c.status).where(invoice.c.id == invoice_id)
                ).scalar_one()
            )

    def audit(invoice_id: UUID) -> list[Any]:
        with owner.connect() as connection:
            return list(
                connection.execute(
                    text(
                        "SELECT action, detail FROM audit.event"
                        " WHERE entity = 'invoice' AND entity_id = :id ORDER BY id"
                    ),
                    {"id": str(invoice_id)},
                )
            )

    def admin_rows(table: Any, invoice_id: UUID) -> list[Any]:
        with owner.connect() as connection:
            return list(
                connection.execute(
                    select(table).where(
                        table.c.invoice_id == invoice_id, table.c.source == "admin"
                    )
                )
            )

    try:
        # --- Guard: the item lists what the open reasons allow; phone for UNREADABLE.
        expected = {
            # Story 3.3: LOW_CONFIDENCE and BANK_CHANGED both allow Approve.
            "correct": ["correct", "approve", "reject"],
            "reextract": ["reextract", "reject"],
            "retry": ["retry_intake", "reject"],
            "unreadable": ["reject"],
            "accounts": ["approve"],
            "unsupported": ["reject"],
        }
        for key, actions in expected.items():
            status, body = call(item_api, ids[key])
            assert status == 200
            assert body["allowed_actions"] == actions, key
        assert call(item_api, ids["unreadable"])[1]["supplier_phone"] == PHONE
        assert call(item_api, ids["unsupported"])[1]["supplier_phone"] == PHONE
        # The routing the page acts on, and the missing checked fields it may add.
        body = call(item_api, ids["correct"])[1]
        assert (body["routing_id"], body["addable_fields"]) == (
            str(ROUTING["correct"]),
            [
                "invoice_number",
                "invoice_date",
                "sub_total",
                "purchase_order",
                "vendor_tax_id",
            ],
        )
        assert call(item_api, ids["reextract"])[1]["supplier_phone"] is None

        # --- Not allowed: 409 ACTION_NOT_ALLOWED, nothing written.
        for endpoint, key, body in (
            (reextract_api, "retry", {}),
            (retry_api, "reextract", {}),
            (correct_api, "unreadable", {"fields": {"vendor_name": "X"}}),
            (reject_api, "accounts", {"reason": REASON}),
        ):
            status, answer = call(endpoint, ids[key], body)
            assert (status, answer["code"]) == (409, "ACTION_NOT_ALLOWED"), key
            assert status_of(ids[key]) == "in_admin_queue"
            assert audit(ids[key]) == []

        # --- Correct: a bank field or a bad value is 400 with nothing written.
        calls = spy.calls
        status, answer = call(
            correct_api, ids["correct"], {"fields": {"payment[0].iban": IBAN}}
        )
        assert (status, answer["code"]) == (400, "VALIDATION_FAILED")
        assert IBAN not in json.dumps(answer)
        assert spy.calls == calls  # refused before anything was read
        status, _ = call(
            correct_api, ids["correct"], {"fields": {"invoice_total": "12,50"}}
        )
        assert status == 400
        # The routing the page saw is required; a stale one (routed again since) is
        # answered like another admin's action.
        status, answer = call(
            correct_api,
            ids["correct"],
            {"fields": {"vendor_name": "X"}, "routing_id": str(_routing(99))},
        )
        assert (status, answer["code"], answer["message"]) == (
            409,
            "CONFLICT",
            "Already handled by another admin.",
        )
        response = asyncio.run(
            correct_api(
                func.HttpRequest(
                    method="POST",
                    url="/",
                    headers={PRINCIPAL_HEADER: header("admin"), **CSRF},
                    route_params={"invoice_id": str(ids["correct"])},
                    body=json.dumps({"fields": {"vendor_name": "X"}}).encode(),
                )
            )
        )
        assert response.status_code == 400
        # Deeply nested JSON is a 400, not a crash.
        response = asyncio.run(
            correct_api(
                func.HttpRequest(
                    method="POST",
                    url="/",
                    headers={PRINCIPAL_HEADER: header("admin"), **CSRF},
                    route_params={"invoice_id": str(ids["correct"])},
                    body=b"[" * 30_000 + b"]" * 30_000,
                )
            )
        )
        assert response.status_code == 400
        assert status_of(ids["correct"]) == "in_admin_queue"
        assert admin_rows(invoice_field, ids["correct"]) == []

        # --- Correct: admin rows, the move, then the queue message and the blob.
        # The message is sent after the commit: the status is already visible.
        seen: list[str] = []
        sent = queue.send

        async def send_after_commit(
            name: QueueName, message: QueueMessage, *, delay_seconds: int = 0
        ) -> None:
            seen.append(status_of(message.invoice_id))
            await sent(name, message, delay_seconds=delay_seconds)

        queue.send = send_after_commit  # type: ignore[method-assign]  # a spy
        status, answer = call(
            correct_api,
            ids["correct"],
            {
                "fields": {"invoice_total": "109.00", "invoice_date": "2026-09-28"},
                "lines": [{"line_no": 1, "product_code": "EVA-01"}],
            },
        )
        assert (status, answer) == (
            200,
            {"invoice_id": str(ids["correct"]), "status": "awaiting_validation"},
        )
        assert seen == ["awaiting_validation"]
        assert [(q, m.invoice_id, m.correlation_id) for q, m, _ in queue.sent] == [
            (QueueName.VALIDATE, ids["correct"], UUID(int=900))
        ]
        fields = {r.field_id: r for r in admin_rows(invoice_field, ids["correct"])}
        assert sorted(fields) == ["invoice_date", "invoice_total"]
        assert {(r.run_id, r.confidence) for r in fields.values()} == {
            (UUID(int=40), 1.0)
        }
        assert (
            fields["invoice_total"].value_number,
            fields["invoice_total"].currency,
        ) == (
            Decimal("109.00"),
            "SGD",
        )
        assert str(fields["invoice_date"].value_date) == "2026-09-28"
        (line,) = admin_rows(invoice_line, ids["correct"])
        assert (line.product_code, line.description, line.quantity, line.unit) == (
            "EVA-01",
            "EVA soles",
            Decimal(10),
            "pair",
        )
        assert (line.tax, line.po_line_id, line.material_id, line.confidence) == (
            Decimal("8.72"),
            PO_LINE,
            MATERIAL,
            1.0,
        )
        # The DI rows are untouched (no update).
        with owner.connect() as connection:
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM intake.invoice_line WHERE source = 'di'"
                        " AND product_code = 'EVA-0l'"
                    )
                ).scalar_one()
                == 1
            )
        # The corrections blob: one per save, no bank data.
        ((name, (data, options)),) = container.blobs.items()
        assert name.startswith(f"{ids['correct']}/") and name.endswith(".json")
        assert options["overwrite"] is False
        blob = json.loads(data)
        assert (blob["invoice_id"], blob["run_id"], blob["admin_oid"]) == (
            str(ids["correct"]),
            str(UUID(int=40)),
            OID,
        )
        assert blob["fields"] == {
            "invoice_date": "2026-09-28",
            "invoice_total": "109.00",
        }
        assert blob["lines"][0]["product_code"] == "EVA-01"
        assert "payment" not in data.decode() and IBAN not in data.decode()
        # The audit row: ids and the admin, never a value.
        ((action, detail),) = audit(ids["correct"])
        assert action == "invoice.corrected"
        assert detail == {
            "run_id": str(UUID(int=40)),
            "field_ids": ["invoice_date", "invoice_total"],
            "line_nos": [1],
            "admin_oid": OID,
        }
        queue.send = sent  # type: ignore[method-assign]  # restore

        # --- Race: another admin already acted: 409 CONFLICT, nothing written.
        status, answer = call(
            correct_api, ids["correct"], {"fields": {"vendor_name": "Other"}}
        )
        assert (status, answer["code"], answer["message"]) == (
            409,
            "CONFLICT",
            "Already handled by another admin.",
        )
        assert len(admin_rows(invoice_field, ids["correct"])) == 2

        # --- Returned: the re-check routes it again; the queue marks it, open
        # reasons only.
        with owner.begin() as connection:
            connection.execute(
                text(
                    "UPDATE intake.invoice SET status = 'in_admin_queue' WHERE id = :id"
                ),
                {"id": ids["correct"]},
            )
            connection.execute(
                insert(admin_item).values(
                    id=UUID(int=300),
                    invoice_id=ids["correct"],
                    routing_id=_routing(9),
                    run_id=UUID(int=40),
                    reason="PO_MISMATCH",
                    field_ids=["sub_total"],
                    detail={},
                    created_at=sql.now(),
                )
            )
        rows = {
            item["invoice_id"]: item
            for item in call(queue_api, "", roles=("admin",))[1]["items"]
        }
        returned = rows[str(ids["correct"])]
        assert (returned["returned_after_correction"], returned["reasons"]) == (
            True,
            ["PO_MISMATCH"],
        )
        assert rows[str(ids["reextract"])]["returned_after_correction"] is False
        # Admin rows on an older run don't count; a line-only correction does.
        assert rows[str(ids["old_run"])]["returned_after_correction"] is False
        assert rows[str(ids["line_only"])]["returned_after_correction"] is True
        routing_of[str(ids["correct"])] = _routing(9)
        # Corrected again while the blob store is down: logged, the commit stands.
        container.fail = True
        status, answer = call(
            correct_api, ids["correct"], {"fields": {"sub_total": "100.00"}}
        )
        assert (status, answer["status"]) == (200, "awaiting_validation")
        assert status_of(ids["correct"]) == "awaiting_validation"
        assert len(container.blobs) == 1

        # --- Re-extract (the enqueue fails: logged, the commit stands) and Retry
        # intake (the blob store is never touched).
        queue.sent.clear()

        async def failing(*args: Any, **kwargs: Any) -> None:
            raise ServiceUnavailableError()

        queue.send = failing  # type: ignore[method-assign]  # a failing queue
        status, answer = call(reextract_api, ids["reextract"], {})
        assert (status, answer["status"]) == (200, "awaiting_extraction")
        assert status_of(ids["reextract"]) == "awaiting_extraction"
        queue.send = sent  # type: ignore[method-assign]  # restore
        status, answer = call(retry_api, ids["retry"], {})
        assert (status, answer["status"]) == (200, "received")
        assert [(q, m.invoice_id) for q, m, _ in queue.sent] == [
            (QueueName.QUALITY, ids["retry"])
        ]
        assert [a for a, _ in audit(ids["reextract"])] == ["invoice.reextracted"]
        assert audit(ids["retry"])[0].detail == {"admin_oid": OID}
        with owner.connect() as connection:
            actors = connection.execute(
                select(status_history.c.actor, status_history.c.to_status).where(
                    status_history.c.invoice_id == ids["retry"]
                )
            ).all()
        assert list(actors) == [(f"admin:{OID}", "received")]

        # --- Reject: a reason is required (500 at most); it is audited.
        for body in ({}, {"reason": "  "}, {"reason": "x" * 501}):
            assert call(reject_api, ids["unreadable"], body)[0] == 400
        before = list(queue.sent)
        status, answer = call(reject_api, ids["unreadable"], {"reason": REASON})
        assert (status, answer["status"]) == (200, "rejected")
        assert queue.sent == before  # Reject feeds no stage
        assert [tuple(r) for r in audit(ids["unreadable"])] == [
            ("invoice.rejected", {"reason": REASON, "admin_oid": OID})
        ]

        # --- Non-admin, unknown, malformed, no CSRF header: nothing reached.
        calls = spy.calls
        for roles in (("finance",), ("goods_in", "management")):
            status, answer = call(
                reject_api, ids["reextract"], {"reason": REASON}, roles
            )
            assert (status, answer["code"]) == (404, "NOT_FOUND")
        assert call(retry_api, "not-a-uuid", {})[0] == 404
        status, _ = call(reject_api, ids["reextract"], {"reason": REASON}, headers={})
        assert status == 403
        assert spy.calls == calls
        assert call(reject_api, _id(99), {"reason": REASON})[0] == 404
    finally:
        staff.dispose()
        owner.dispose()


class _NoImages:
    """The `images` container with nothing in it (the item's image is not the point)."""

    async def exists(self, invoice_id: UUID) -> bool:
        return False

    async def get(self, invoice_id: UUID) -> Any:
        raise NotImplementedError

    async def metadata(self, invoice_id: UUID) -> Any:
        raise NotImplementedError
