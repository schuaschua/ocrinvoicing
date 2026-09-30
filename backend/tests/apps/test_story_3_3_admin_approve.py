"""Story 3.3: Approve on staff-api (AD-3, AD-4, AD-9, AD-11), against a real
PostgreSQL 18 written as the staff-api login (so the test also proves its grants), a
fake queue and a fake `images` container. Synthetic data only (security.md rule 1).

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
from sqlalchemy import Engine, create_engine, insert, select, text
from sqlalchemy import func as sql

from apps._pipeline_fakes import FakeQueue
from apps.test_staff_me import OID, header
from conftest import PostgresServer, login_engine, truncate_intake
from invoicing.adapters.postgres.admin_actions import PostgresAdminActions
from invoicing.adapters.postgres.admin_item import PostgresAdminItemReader
from invoicing.adapters.postgres.schema import (
    admin_item,
    extraction_run,
    invoice,
    invoice_field,
)
from invoicing.adapters.principal import PRINCIPAL_HEADER
from invoicing.apps.staff_api.actions import action_endpoints
from invoicing.apps.staff_api.item import item_endpoints
from invoicing.ports.blobs import ImageNotFoundError, StoredImage
from invoicing.ports.messages import QueueMessage
from invoicing.ports.queue import QueueName

pytestmark = pytest.mark.app("staff_api")

T0 = datetime(2026, 9, 1, 1, 0, tzinfo=UTC)
NOW = datetime(2026, 9, 30, 2, 0, tzinfo=UTC)
SUPPLIER = UUID("01a0c450-6c00-7b7b-8aa9-4ccade9f5c33")
CSRF = {"X-Requested-With": "XMLHttpRequest"}
REASON = "Confirmed new account by phone with Ms Chan"
BOTH = {"called_number_on_file": True, "supplier_confirmed": True}
JPEG = b"\xff\xd8\xff synthetic original"
KEYS = ("low", "bank", "dup", "accounts_err", "mixed", "posted_ref", "original")


def _id(n: int) -> UUID:
    return UUID(f"0192f0c1-7a2b-7c3d-8e4f-33{n:010x}")


def _routing(n: int) -> UUID:
    return UUID(f"0192f0c3-{n:04x}-7000-8000-000000000033")


IDS = {key: _id(n) for n, key in enumerate(KEYS, start=1)}
ROUTING = {key: _routing(n) for n, key in enumerate(KEYS, start=1)}


class _Images:
    """The `images` container: present blobs only (the others were deleted)."""

    def __init__(self, blobs: dict[UUID, bytes]) -> None:
        self.blobs = blobs

    async def get(self, invoice_id: UUID) -> StoredImage:
        if invoice_id not in self.blobs:
            raise ImageNotFoundError("gone")
        return StoredImage(self.blobs[invoice_id], None)  # type: ignore[arg-type]  # bytes only

    async def exists(self, invoice_id: UUID) -> bool:
        return invoice_id in self.blobs

    async def metadata(self, invoice_id: UUID) -> Any:
        raise NotImplementedError


def _seed(owner: Engine) -> None:
    """One queued invoice per Approve path, and the earlier invoice `dup` matches."""
    reasons: dict[str, list[tuple[str, dict[str, object]]]] = {
        "low": [("LOW_CONFIDENCE", {})],
        "bank": [("BANK_CHANGED", {}), ("PO_MISMATCH", {})],
        "dup": [
            (
                "DUPLICATE",
                {"invoice_id": str(IDS["original"]), "basis": "fingerprint"},
            )
        ],
        "accounts_err": [
            ("ACCOUNTS_API_ERROR", {"status": 503, "code": "SIMULATED_FAILURE"})
        ],
        "mixed": [("LOW_CONFIDENCE", {}), ("UNREADABLE", {})],
        "posted_ref": [("ACCOUNTS_API_ERROR", {"status": None, "code": "TIMEOUT"})],
    }
    run = UUID(int=3301)
    with owner.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO master.supplier (id, name) VALUES (:id, :name)"
                " ON CONFLICT (id) DO NOTHING"
            ),
            {"id": SUPPLIER, "name": "Synthetic Jurong Soles"},
        )
        for n, (key, invoice_id) in enumerate(IDS.items()):
            connection.execute(
                insert(invoice).values(
                    id=invoice_id,
                    correlation_id=UUID(int=3300 + n),
                    source="link",
                    supplier_id=SUPPLIER,
                    content_type="image/jpeg",
                    device_check="passed",
                    status="posted" if key == "original" else "in_admin_queue",
                    status_changed_at=T0,
                    # Story 3.2: failures and a backoff left from earlier tries.
                    post_failures=5 if key == "accounts_err" else 0,
                    next_attempt_at=T0 if key == "accounts_err" else None,
                    accounts_ref="SIM-000123" if key == "posted_ref" else None,
                    created_at=T0 + timedelta(minutes=n),
                )
            )
        connection.execute(
            insert(extraction_run).values(
                run_id=run,
                invoice_id=IDS["original"],
                model_id="prebuilt-invoice",
                api_version="2024-11-30",
                pages=1,
                created_at=T0,
            )
        )
        connection.execute(
            insert(invoice_field).values(
                id=uuid4(),
                invoice_id=IDS["original"],
                run_id=run,
                field_id="invoice_total",
                value_number=Decimal("109.00"),
                currency="SGD",
                confidence=0.99,
                source="di",
                created_at=T0,
            )
        )
        k = 0
        for key, rows in reasons.items():
            for reason, detail in rows:
                k += 1
                connection.execute(
                    insert(admin_item).values(
                        id=UUID(int=3300 + k),
                        invoice_id=IDS[key],
                        routing_id=ROUTING[key],
                        run_id=None,
                        reason=reason,
                        field_ids=[],
                        detail=detail,
                        created_at=sql.now(),
                    )
                )


def test_story_3_3_admin_approves_exceptions(
    postgres_server: PostgresServer,
    intake_database: str,
    app_settings: dict[str, str],
    load_app: Callable[[str], ModuleType],
) -> None:
    """Approve. Covers: the approve and duplicate-image routes are wired; the item
    offers Approve when every reason allows it (alone with an accounts_ref) and
    carries the matching invoice of a DUPLICATE and the accounts error's status and
    code; a missing or too-long reason is 400 with nothing written; BANK_CHANGED needs
    both checks (400 CHECKS_REQUIRED) and records them; Approve moves to
    ready_to_post, resets the posting count and backoff, audits the reason and
    enqueues q-post after the commit; a disallowed mix is 409 ACTION_NOT_ALLOWED; a
    stale routing and a second admin get 409 CONFLICT; an accounts_ref keeps its ref;
    the duplicate image is served only while the DUPLICATE is open, to admins."""
    # --- Wiring: the approve and duplicate-image routes, the SPA catch-all last.
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
    assert routes["admin_approve"] == ("api/admin/items/{invoice_id}/approve", ["POST"])
    assert routes["admin_duplicate_image"] == (
        "api/admin/items/{invoice_id}/duplicate/image",
        ["GET"],
    )

    truncate_intake(postgres_server, intake_database)
    owner = create_engine(
        postgres_server.url(postgres_server.deployer, intake_database)
    )
    staff = login_engine(postgres_server, postgres_server.staff_api, intake_database)
    _seed(owner)
    queue = FakeQueue()
    images = _Images({IDS["original"]: JPEG})
    *_, reject_api, approve_api = action_endpoints(
        PostgresAdminActions(staff, currency="SGD"),
        lambda: queue,
        lambda: None,  # type: ignore[arg-type,return-value]  # Approve writes no blob
        platform_auth_trusted=True,
        clock=lambda: NOW,
    )
    item_api, _, _, duplicate_image_api = item_endpoints(
        PostgresAdminItemReader(staff, lambda: "no key needed"),
        images,
        platform_auth_trusted=True,
    )

    def request(
        endpoint: Any,
        invoice_id: object,
        body: object = None,
        roles: tuple[str, ...] = ("admin",),
    ) -> func.HttpResponse:
        if isinstance(body, dict) and "routing_id" not in body:
            routing = ROUTING.get(
                next((k for k, v in IDS.items() if v == invoice_id), "")
            )
            body = {**body, "routing_id": None if routing is None else str(routing)}
        return asyncio.run(
            endpoint(
                func.HttpRequest(
                    method="GET" if body is None else "POST",
                    url=f"/api/admin/items/{invoice_id}",
                    headers={PRINCIPAL_HEADER: header(*roles), **CSRF},
                    route_params={"invoice_id": str(invoice_id)},
                    params={},
                    body=b"" if body is None else json.dumps(body).encode(),
                )
            )
        )

    def call(
        endpoint: Any, key: str, body: object = None, **kwargs: Any
    ) -> tuple[int, dict[str, Any]]:
        response = request(endpoint, IDS[key], body, **kwargs)
        return response.status_code, json.loads(response.get_body())

    def row(key: str) -> Any:
        with owner.connect() as connection:
            return connection.execute(
                select(
                    invoice.c.status,
                    invoice.c.post_failures,
                    invoice.c.next_attempt_at,
                    invoice.c.accounts_ref,
                ).where(invoice.c.id == IDS[key])
            ).one()

    def audit(key: str) -> list[tuple[str, Any]]:
        with owner.connect() as connection:
            return [
                (r.action, r.detail)
                for r in connection.execute(
                    text(
                        "SELECT action, detail FROM audit.event"
                        " WHERE entity = 'invoice' AND entity_id = :id ORDER BY id"
                    ),
                    {"id": str(IDS[key])},
                )
            ]

    try:
        # --- Guard: Approve when every reason allows it; alone with an accounts_ref.
        expected = {
            "low": ["correct", "approve", "reject"],
            "bank": ["correct", "approve", "reject"],
            "dup": ["approve", "reject"],
            "accounts_err": ["approve", "reject"],
            "mixed": ["correct", "reject"],
            "posted_ref": ["approve"],
        }
        for key, actions in expected.items():
            status, body = call(item_api, key)
            assert (status, body["allowed_actions"]) == (200, actions), key
        # The accounts error's stored status and code (Story 3.2) reach the screen.
        body = call(item_api, "accounts_err")[1]
        assert body["reasons"][0]["detail"] == {
            "status": 503,
            "code": "SIMULATED_FAILURE",
        }
        assert body["duplicate_of"] is None

        # --- Duplicate: the matching invoice side by side, and its image.
        body = call(item_api, "dup")[1]
        assert body["duplicate_of"] == {
            "invoice_id": str(IDS["original"]),
            "received_at": (T0 + timedelta(minutes=6)).isoformat(),
            "content_type": "image/jpeg",
            "supplier_name": "Synthetic Jurong Soles",
            "invoice_total": "109.00",
            "currency": "SGD",
            "image_available": True,
        }
        response = request(duplicate_image_api, IDS["dup"])
        assert (response.status_code, response.get_body()) == (200, JPEG)
        assert response.headers["Content-Type"] == "image/jpeg"
        assert response.headers["Cache-Control"] == "no-store"
        # Only through an open DUPLICATE, to admins: the posted original's own item,
        # another queued invoice and other roles get 404.
        for invoice_id, roles in (
            (IDS["original"], ("admin",)),
            (IDS["low"], ("admin",)),
            (IDS["dup"], ("finance",)),
        ):
            response = request(duplicate_image_api, invoice_id, roles=roles)
            assert response.status_code == 404, (invoice_id, roles)
            assert JPEG not in response.get_body()
        # The matching image deleted after 30 days: a placeholder on the screen.
        images.blobs.clear()
        assert call(item_api, "dup")[1]["duplicate_of"]["image_available"] is False
        status, answer = call(duplicate_image_api, "dup")
        assert (status, answer["code"]) == (404, "IMAGE_DELETED")
        images.blobs[IDS["original"]] = JPEG

        # --- A reason is required, 500 characters at most: 400, nothing written.
        for body in (
            {},
            {"reason": "   "},
            {"reason": "x" * 501},
            {"reason": REASON, "checks": ["yes"]},
            {"reason": REASON, "checks": {"called_number_on_file": "yes"}},
            # A misspelled check is refused, never ignored.
            {"reason": REASON, "checks": {"called_number_on_fil": True}},
        ):
            status, answer = call(approve_api, "low", body)
            assert (status, answer["code"]) == (400, "VALIDATION_FAILED"), body
        assert row("low").status == "in_admin_queue"
        assert audit("low") == []

        # --- Bank change: both checks, on the server too; recorded in the audit.
        # No checks key, `checks: null` (no checks) and one check only.
        for body in (
            {"reason": REASON},
            {"reason": REASON, "checks": None},
            {"reason": REASON, "checks": {"called_number_on_file": True}},
        ):
            status, answer = call(approve_api, "bank", body)
            assert (status, answer["code"], answer["message"]) == (
                400,
                "CHECKS_REQUIRED",
                "Tick both checks to approve.",
            )
        assert (row("bank").status, audit("bank")) == ("in_admin_queue", [])

        # --- Approve: ready_to_post, then q-post after the commit, audited.
        seen: list[str] = []
        sent = queue.send

        async def send_after_commit(
            name: QueueName, message: QueueMessage, *, delay_seconds: int = 0
        ) -> None:
            seen.append(
                row(next(k for k, v in IDS.items() if v == message.invoice_id)).status
            )
            await sent(name, message, delay_seconds=delay_seconds)

        queue.send = send_after_commit  # type: ignore[method-assign]  # a spy
        status, answer = call(
            approve_api, "bank", {"reason": f"  {REASON}  ", "checks": BOTH}
        )
        assert (status, answer) == (
            200,
            {"invoice_id": str(IDS["bank"]), "status": "ready_to_post"},
        )
        assert seen == ["ready_to_post"]
        assert [(q, m.invoice_id, m.correlation_id, d) for q, m, d in queue.sent] == [
            (QueueName.POST, IDS["bank"], UUID(int=3301), 0)
        ]
        assert audit("bank") == [
            ("invoice.approved", {"reason": REASON, "checks": BOTH, "admin_oid": OID})
        ]
        queue.send = sent  # type: ignore[method-assign]  # restore

        # Not a duplicate; a plain exception (checks recorded as not needed).
        # `checks: null` counts as no checks: fine where no bank change is open.
        for key, body in (
            ("dup", {"reason": REASON}),
            ("low", {"reason": REASON, "checks": None}),
        ):
            status, answer = call(approve_api, key, body)
            assert (status, answer["status"]) == (200, "ready_to_post"), key
        assert audit("low")[0][1]["checks"] == {
            "called_number_on_file": False,
            "supplier_confirmed": False,
        }
        # Approved: the matching image is no longer served for it.
        assert request(duplicate_image_api, IDS["dup"]).status_code == 404

        # --- Accounts error: a stale page is refused; then Approve retries posting
        # with the count and backoff reset (AD-3).
        status, answer = call(
            approve_api,
            "accounts_err",
            {"reason": REASON, "routing_id": str(_routing(99))},
        )
        assert (status, answer["code"], answer["message"]) == (
            409,
            "CONFLICT",
            "Already handled by another admin.",
        )
        assert call(approve_api, "accounts_err", {"reason": REASON})[0] == 200
        assert tuple(row("accounts_err")) == ("ready_to_post", 0, None, None)

        # --- Mixed reasons: 409 ACTION_NOT_ALLOWED, nothing written.
        status, answer = call(approve_api, "mixed", {"reason": REASON})
        assert (status, answer["code"]) == (409, "ACTION_NOT_ALLOWED")
        assert (row("mixed").status, audit("mixed")) == ("in_admin_queue", [])

        # --- Already in the accounts system: only Approve; the ref is kept, so the
        # post stage re-uses it (Story 3.2) and the re-post returns the same ref.
        assert call(reject_api, "posted_ref", {"reason": REASON})[0] == 409
        assert call(approve_api, "posted_ref", {"reason": REASON})[0] == 200
        assert tuple(row("posted_ref")) == ("ready_to_post", 0, None, "SIM-000123")

        # --- Race: another admin approved first: 409 CONFLICT, nothing more.
        before = len(queue.sent)
        status, answer = call(approve_api, "low", {"reason": REASON})
        assert (status, answer["code"]) == (409, "CONFLICT")
        assert len(queue.sent) == before
        assert len(audit("low")) == 1
        # Every approval went to q-post; the reason is never in a queue message.
        assert {q for q, _, _ in queue.sent} == {QueueName.POST}
        assert len(queue.sent) == 5

        # --- Non-admin: 404, nothing reached.
        status, answer = call(
            approve_api, "mixed", {"reason": REASON}, roles=("finance",)
        )
        assert (status, answer["code"]) == (404, "NOT_FOUND")
    finally:
        staff.dispose()
        owner.dispose()
