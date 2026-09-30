"""Story 2.9: the admin item endpoints on staff-api (AD-4, AD-11, AD-14, AD-18), against a
real PostgreSQL 18 read as the staff-api login (so the test also proves its grants,
0008_extraction_pages included) and a fake `images` container. Synthetic data only
(security.md rule 1). Page sizes saved by the extract stage are asserted in
test_story_2_3_extract.

One merged test (the 200-case cap, coding-style.md rule 20 exception): each plan
matrix row is a block of assertions, in order."""

import asyncio
import base64
import json
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import ModuleType
from typing import Any
from uuid import UUID, uuid4

import azure.functions as func
import pytest
from sqlalchemy import Engine, create_engine, insert, text
from sqlalchemy import func as sql

from _pgp import make_test_key_pair
from apps.test_staff_me import OID, header
from conftest import PostgresServer, login_engine, truncate_intake
from invoicing.adapters.key_vault import SecretReadError
from invoicing.adapters.postgres.admin_item import PostgresAdminItemReader
from invoicing.adapters.postgres.schema import (
    admin_item,
    extraction_page,
    extraction_run,
    invoice,
    invoice_field,
    invoice_line,
)
from invoicing.adapters.principal import PRINCIPAL_HEADER
from invoicing.apps.staff_api.item import item_endpoints
from invoicing.ports.admin_item import AdminItem, RevealWhich
from invoicing.ports.blobs import ImageNotFoundError, StoredImage

pytestmark = pytest.mark.app("staff_api")

T0 = datetime(2026, 9, 1, 1, 0, tzinfo=UTC)
SUPPLIER = UUID("01a0c450-6c00-7b7b-8aa9-4ccade9f5c29")
PHONE = "+65 6123 4567"
NEW_IBAN = "SG12ABCD00009930"
ON_FILE_IBAN = "SG99ZZZZ00004821"
# 4 characters or fewer: masked with no digits, or the mask would be the value.
NEW_SWIFT = "QZXW"
ON_FILE_SWIFT = "WXV"
FINGERPRINT = "0" * 64
BOX = [100.0, 200.0, 400.0, 200.0, 400.0, 260.0, 100.0, 260.0]
JPEG = b"\xff\xd8\xff\xe0synthetic-jpeg"
CSRF = {"X-Requested-With": "XMLHttpRequest"}


def _id(n: int) -> UUID:
    return UUID(f"0192f0c1-7a2b-7c3d-8e4f-{n:012x}")


def _routing(n: int) -> UUID:
    return UUID(f"0192f0c2-{n:04x}-7000-8000-000000000000")


class _Spy:
    """The real reader, counting calls (a refused call must read nothing)."""

    def __init__(self, reader: PostgresAdminItemReader) -> None:
        self.reader = reader
        self.calls = 0

    async def read(self, invoice_id: UUID) -> AdminItem | None:
        self.calls += 1
        return await self.reader.read(invoice_id)

    async def content_type(self, invoice_id: UUID) -> str | None:
        self.calls += 1
        return await self.reader.content_type(invoice_id)

    async def reveal(
        self, invoice_id: UUID, field_id: str, which: RevealWhich, oid: str | None
    ) -> str | None:
        self.calls += 1
        return await self.reader.reveal(invoice_id, field_id, which, oid)


class _Key:
    """The private key provider, counting reads (nothing decrypts for a refusal)."""

    def __init__(self, key: str | None) -> None:
        self.key = key
        self.reads = 0

    def __call__(self) -> str:
        self.reads += 1
        if self.key is None:
            raise SecretReadError("pgp-private-key", "FORBIDDEN")
        return self.key


class _Images:
    """The `images` container: present blobs only (the others were deleted)."""

    def __init__(self, blobs: dict[UUID, bytes]) -> None:
        self.blobs = blobs

    async def get(self, invoice_id: UUID) -> StoredImage:
        if invoice_id not in self.blobs:
            raise ImageNotFoundError("gone")
        # The endpoint streams the bytes only; the metadata is never read.
        return StoredImage(self.blobs[invoice_id], None)  # type: ignore[arg-type]

    async def exists(self, invoice_id: UUID) -> bool:
        return invoice_id in self.blobs

    async def metadata(self, invoice_id: UUID) -> Any:
        raise NotImplementedError


def _seed(owner: Engine, public_key: str) -> tuple[UUID, UUID, UUID]:
    """(the bank-change item, a queued PDF with no run, a posted invoice)."""
    banked, pdf, posted = _id(1), _id(2), _id(3)
    run, earlier = UUID(int=20), UUID(int=10)

    def encrypt(value: str) -> Any:
        return sql.pgp_pub_encrypt(value, sql.dearmor(public_key))

    with owner.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO master.supplier (id, name, phone) VALUES (:id, :name, :phone)"
                " ON CONFLICT (id) DO UPDATE SET phone = :phone"
            ),
            {"id": SUPPLIER, "name": "Synthetic Kowloon Soles", "phone": PHONE},
        )
        connection.execute(
            text(
                "INSERT INTO master.supplier_bank (supplier_id, field_id, ciphertext,"
                " fingerprint) VALUES (:id, 'iban',"
                " pgp_pub_encrypt(:value, dearmor(:key)), :fp)"
                " ON CONFLICT (supplier_id, field_id) DO UPDATE"
                " SET ciphertext = excluded.ciphertext"
            ),
            {"id": SUPPLIER, "value": ON_FILE_IBAN, "key": public_key, "fp": "1" * 64},
        )
        connection.execute(
            text(
                "INSERT INTO master.supplier_bank (supplier_id, field_id, ciphertext,"
                " fingerprint) VALUES (:id, 'swift',"
                " pgp_pub_encrypt(:value, dearmor(:key)), :fp)"
                " ON CONFLICT (supplier_id, field_id) DO UPDATE"
                " SET ciphertext = excluded.ciphertext"
            ),
            {"id": SUPPLIER, "value": ON_FILE_SWIFT, "key": public_key, "fp": "2" * 64},
        )
        for n, (invoice_id, status, content_type) in enumerate(
            (
                (banked, "in_admin_queue", "image/jpeg"),
                (pdf, "in_admin_queue", "application/pdf"),
                (posted, "posted", "image/jpeg"),
            )
        ):
            connection.execute(
                insert(invoice).values(
                    id=invoice_id,
                    correlation_id=invoice_id,
                    source="link",
                    supplier_id=SUPPLIER,
                    content_type=content_type,
                    device_check="passed",
                    status=status,
                    status_changed_at=T0,
                    post_failures=0,
                    created_at=T0 + timedelta(minutes=n),
                )
            )
        for run_id, at in ((earlier, T0), (run, T0 + timedelta(hours=1))):
            connection.execute(
                insert(extraction_run).values(
                    run_id=run_id,
                    invoice_id=banked,
                    model_id="prebuilt-invoice",
                    api_version="2024-11-30",
                    pages=1,
                    created_at=at,
                )
            )
        connection.execute(
            insert(extraction_page).values(
                run_id=run, page=1, width=1000.0, height=1400.0, unit="pixel"
            )
        )
        field = {"invoice_id": banked, "source": "di", "created_at": T0}
        for values in (
            # An earlier run's value is never current (AD-18).
            {"run_id": earlier, "field_id": "vendor_name", "value_text": "Old"},
            {
                "run_id": run,
                "field_id": "vendor_name",
                "value_text": "Synthetic Kowloon Soles",
                "confidence": 0.995,
                "page": 1,
                "polygon": BOX,
            },
            {
                "run_id": run,
                "field_id": "invoice_total",
                "value_number": Decimal("109.00"),
                "currency": "SGD",
                "confidence": 0.91,
                "page": 1,
                "polygon": BOX,
            },
            {
                "run_id": run,
                "field_id": "invoice_date",
                "value_date": date(2026, 9, 28),
                "confidence": 0.5,
            },
            # The admin's correction wins and counts as 1.0 (AD-18).
            {
                "run_id": run,
                "field_id": "invoice_date",
                "value_date": date(2026, 9, 29),
                "source": "admin",
                "created_at": T0 + timedelta(minutes=5),
            },
            {
                "run_id": run,
                "field_id": "payment[0].iban",
                "bank_ciphertext": encrypt(NEW_IBAN),
                "bank_fingerprint": FINGERPRINT,
                "confidence": 0.99,
                "page": 1,
                "polygon": BOX,
            },
            {
                "run_id": run,
                "field_id": "payment[0].swift",
                "bank_ciphertext": encrypt(NEW_SWIFT),
                "bank_fingerprint": FINGERPRINT,
                "confidence": 0.99,
            },
        ):
            connection.execute(
                insert(invoice_field).values(id=uuid4(), **{**field, **values})
            )
        connection.execute(
            insert(invoice_line).values(
                id=uuid4(),
                invoice_id=banked,
                run_id=run,
                line_no=1,
                product_code="EVA-01",
                description="EVA soles",
                quantity=Decimal(10),
                unit_price=Decimal("10.90"),
                amount=Decimal("109.00"),
                confidence=0.99,
                source="di",
                created_at=T0,
            )
        )
        for k, (routing, reason, field_ids) in enumerate(
            (
                (1, "PO_MISMATCH", ["sub_total"]),  # an earlier routing: not open
                (2, "LOW_CONFIDENCE", ["invoice_total"]),
                (2, "BANK_CHANGED", ["payment[0].iban", "payment[0].swift"]),
            )
        ):
            connection.execute(
                insert(admin_item).values(
                    id=UUID(int=100 + k),
                    invoice_id=banked,
                    routing_id=_routing(routing),
                    run_id=run,
                    reason=reason,
                    field_ids=field_ids,
                    detail={},
                    created_at=sql.now(),
                )
            )
    return banked, pdf, posted


def test_story_2_9_admin_item(
    postgres_server: PostgresServer,
    intake_database: str,
    app_settings: dict[str, str],
    load_app: Callable[[str], ModuleType],
) -> None:
    """The admin item. Covers: the three routes are wired before the SPA catch-all; the
    item body (open reasons, current fields with page, polygon, flag and confidence,
    lines, page sizes, phone, bank masks and no full value); a queued PDF with no run;
    the image stream (no-store) and a deleted image (404 IMAGE_DELETED); a reveal
    returns the value and writes its audit entry (ids only); a failed audit write
    returns nothing; a wrong or unreadable key is 503 with no value; the CSRF header
    and a bad body; 404 for a non-admin (nothing read or decrypted), a posted, unknown
    or malformed invoice; 401 signed out."""
    # --- Wiring: GET, GET and POST, and the SPA catch-all stays last.
    module = load_app("staff_api")
    functions = list(module.app.get_functions())
    names = [fn.get_function_name() for fn in functions]
    assert names[-1] == "web_app"
    routes = {}
    for fn in functions:
        (trigger,) = [
            b.get_dict_repr()
            for b in fn.get_bindings()
            if b.get_dict_repr()["type"] == "httpTrigger"
        ]
        methods = [getattr(m, "value", m) for m in trigger["methods"]]  # type: ignore[attr-defined]  # a list here
        routes[fn.get_function_name()] = (trigger["route"], methods)
    assert routes["admin_item"] == ("api/admin/items/{invoice_id}", ["GET"])
    assert routes["admin_item_image"] == ("api/admin/items/{invoice_id}/image", ["GET"])
    assert routes["admin_bank_reveal"] == (
        "api/admin/items/{invoice_id}/bank/reveal",
        ["POST"],
    )

    keys = make_test_key_pair()
    truncate_intake(postgres_server, intake_database)
    owner = create_engine(
        postgres_server.url(postgres_server.deployer, intake_database)
    )
    staff = login_engine(postgres_server, postgres_server.staff_api, intake_database)
    banked, pdf, posted = _seed(owner, keys.public_key)
    key = _Key(keys.private_key)
    spy = _Spy(PostgresAdminItemReader(staff, key))
    item_api, image_api, reveal_api, _ = item_endpoints(
        spy, _Images({banked: JPEG}), platform_auth_trusted=True
    )

    def request(
        endpoint: Any,
        invoice_id: object,
        *roles: str,
        suffix: str = "",
        body: object = None,
        headers: dict[str, str] | None = None,
    ) -> func.HttpResponse:
        all_headers = {PRINCIPAL_HEADER: header(*roles)} if roles else {}
        all_headers.update(headers or {})
        return asyncio.run(
            endpoint(
                func.HttpRequest(
                    method="GET" if body is None else "POST",
                    url=f"/api/admin/items/{invoice_id}{suffix}",
                    headers=all_headers,
                    route_params={"invoice_id": str(invoice_id)},
                    body=b"" if body is None else json.dumps(body).encode(),
                )
            )
        )

    def reveal(
        field_id: str, which: str, roles: tuple[str, ...] = ("admin",)
    ) -> func.HttpResponse:
        return request(
            reveal_api,
            banked,
            *roles,
            suffix="/bank/reveal",
            body={"field_id": field_id, "which": which},
            headers=CSRF,
        )

    def audit_rows() -> list[Any]:
        with owner.connect() as connection:
            return list(
                connection.execute(
                    text(
                        "SELECT action, entity, detail FROM audit.event"
                        " WHERE entity_id = :id ORDER BY at, id"
                    ),
                    {"id": str(banked)},
                )
            )

    try:
        # --- Open item: reasons, current fields, lines, page sizes, phone, masks.
        response = request(item_api, banked, "admin")
        assert response.status_code == 200
        body = json.loads(response.get_body())
        assert body == {
            "invoice_id": str(banked),
            "received_at": T0.isoformat(),
            "content_type": "image/jpeg",
            "image_available": True,
            "supplier_id": str(SUPPLIER),
            "supplier_name": "Synthetic Kowloon Soles",
            "supplier_phone": PHONE,
            "reasons": [
                {
                    "code": "LOW_CONFIDENCE",
                    "field_ids": ["invoice_total"],
                    "detail": {},
                },
                {
                    "code": "BANK_CHANGED",
                    "field_ids": ["payment[0].iban", "payment[0].swift"],
                    "detail": {},
                },
            ],
            "fields": [
                {
                    "field_id": "invoice_date",
                    "value": "2026-09-29",
                    "currency": None,
                    "confidence": 1.0,
                    "page": None,
                    "polygon": None,
                    "flagged": False,
                    "bank": False,
                },
                {
                    "field_id": "invoice_total",
                    "value": "109.00",
                    "currency": "SGD",
                    "confidence": 0.91,
                    "page": 1,
                    "polygon": BOX,
                    "flagged": True,
                    "bank": False,
                },
                {
                    "field_id": "payment[0].iban",
                    "value": None,
                    "currency": None,
                    "confidence": 0.99,
                    "page": 1,
                    "polygon": BOX,
                    "flagged": True,
                    "bank": True,
                },
                {
                    "field_id": "payment[0].swift",
                    "value": None,
                    "currency": None,
                    "confidence": 0.99,
                    "page": None,
                    "polygon": None,
                    "flagged": True,
                    "bank": True,
                },
                {
                    "field_id": "vendor_name",
                    "value": "Synthetic Kowloon Soles",
                    "currency": None,
                    "confidence": 0.995,
                    "page": 1,
                    "polygon": BOX,
                    "flagged": False,
                    "bank": False,
                },
            ],
            "lines": [
                {
                    "line_no": 1,
                    "product_code": "EVA-01",
                    "description": "EVA soles",
                    "quantity": "10",
                    "unit_price": "10.90",
                    "amount": "109.00",
                    "confidence": 0.99,
                }
            ],
            "pages": [{"page": 1, "width": 1000.0, "height": 1400.0, "unit": "pixel"}],
            "bank_changes": [
                {"field_id": "payment[0].iban", "on_file": "4821", "new": "9930"},
                # 4 characters or fewer: on file and read, but no digits.
                {"field_id": "payment[0].swift", "on_file": "", "new": ""},
            ],
            # Story 2.10: LOW_CONFIDENCE allows Correct; Story 3.3: both allow Approve.
            "allowed_actions": ["correct", "approve", "reject"],
            "routing_id": str(_routing(2)),
            "addable_fields": [
                "invoice_number",
                "sub_total",
                "purchase_order",
                "vendor_tax_id",
            ],
            "duplicate_of": None,
        }
        # Only masks leave the server by default (AD-11).
        for value in (NEW_IBAN, ON_FILE_IBAN, NEW_SWIFT, ON_FILE_SWIFT):
            assert value not in response.get_body().decode()

        # --- A queued PDF with no run: no fields, boxes, phone or bank panel.
        body = json.loads(request(item_api, pdf, "admin").get_body())
        assert (body["content_type"], body["image_available"]) == (
            "application/pdf",
            False,
        )
        assert (body["fields"], body["pages"], body["bank_changes"]) == ([], [], [])
        assert (body["reasons"], body["supplier_phone"]) == ([], None)

        # --- Image: streamed with no-store; deleted after 30 days: 404 IMAGE_DELETED.
        response = request(image_api, banked, "admin", suffix="/image")
        assert (response.status_code, response.get_body()) == (200, JPEG)
        assert response.headers["Content-Type"] == "image/jpeg"
        assert response.headers["Cache-Control"] == "no-store"
        response = request(image_api, pdf, "admin", suffix="/image")
        assert response.status_code == 404
        assert json.loads(response.get_body())["code"] == "IMAGE_DELETED"

        # --- Reveal: the full value, after its audit entry (ids only, no value).
        before = len(audit_rows())
        for which, value in (("new", NEW_IBAN), ("on_file", ON_FILE_IBAN)):
            response = reveal("payment[0].iban", which)
            assert response.status_code == 200
            assert json.loads(response.get_body()) == {
                "field_id": "payment[0].iban",
                "which": which,
                "value": value,
            }
        rows = audit_rows()[before:]
        assert [(r.action, r.entity) for r in rows] == [("bank.reveal", "invoice")] * 2
        assert [r.detail for r in rows] == [
            {"field_id": "payment[0].iban", "which": w, "admin_oid": OID}
            for w in ("new", "on_file")
        ]
        # A field that is not one of the changed ones, or a bad body: 404, 400.
        assert reveal("payment[1].iban", "new").status_code == 404
        for field_id, which in (("vendor_name", "new"), ("payment[0].iban", "old")):
            response = reveal(field_id, which)
            assert json.loads(response.get_body())["code"] == "VALIDATION_FAILED"
        # A principal without an object id: the audit entry could name nobody, so
        # 404, nothing decrypted and no audit entry.
        no_oid = base64.b64encode(
            json.dumps(
                {
                    "auth_typ": "aad",
                    "claims": [
                        {"typ": "name", "val": "Priya Tan"},
                        {"typ": "roles", "val": "admin"},
                    ],
                }
            ).encode()
        ).decode()
        count, reads = len(audit_rows()), key.reads
        response = request(
            reveal_api,
            banked,
            suffix="/bank/reveal",
            body={"field_id": "payment[0].iban", "which": "new"},
            headers={PRINCIPAL_HEADER: no_oid, **CSRF},
        )
        assert response.status_code == 404
        assert NEW_IBAN not in response.get_body().decode()
        assert (len(audit_rows()), key.reads) == (count, reads)
        # CSRF (security.md rule 24): a POST without the custom header is refused.
        response = request(
            reveal_api,
            banked,
            "admin",
            suffix="/bank/reveal",
            body={"field_id": "payment[0].iban", "which": "new"},
        )
        assert response.status_code == 403

        # --- An audit write that fails returns no value and writes nothing.
        grant = "INSERT (id, action, entity, entity_id, detail) ON audit.event"
        login = f'"{postgres_server.staff_api}"'
        with owner.begin() as connection:
            connection.execute(text(f"REVOKE {grant} FROM {login}"))
        try:
            count = len(audit_rows())
            response = reveal("payment[0].iban", "new")
            assert response.status_code == 500
            assert NEW_IBAN not in response.get_body().decode()
            assert len(audit_rows()) == count
        finally:
            with owner.begin() as connection:
                connection.execute(text(f"GRANT {grant} TO {login}"))

        # --- A wrong key or an unreadable one: 503, and no value.
        for other in (make_test_key_pair().private_key, None):
            wrong_item, _, wrong_reveal, _ = item_endpoints(
                PostgresAdminItemReader(staff, _Key(other)),
                _Images({}),
                platform_auth_trusted=True,
            )
            for response in (
                request(wrong_item, banked, "admin"),
                request(
                    wrong_reveal,
                    banked,
                    "admin",
                    suffix="/bank/reveal",
                    body={"field_id": "payment[0].iban", "which": "new"},
                    headers=CSRF,
                ),
            ):
                assert response.status_code == 503
                assert NEW_IBAN not in response.get_body().decode()
                assert "9930" not in response.get_body().decode()

        # --- Non-admin: 404 on every endpoint, with nothing read or decrypted.
        calls, reads = spy.calls, key.reads
        for roles in (("finance",), ("goods_in", "management")):
            for response in (
                request(item_api, banked, *roles),
                request(image_api, banked, *roles, suffix="/image"),
                reveal("payment[0].iban", "new", roles),
            ):
                assert response.status_code == 404
                assert json.loads(response.get_body())["code"] == "NOT_FOUND"
        assert (spy.calls, key.reads) == (calls, reads)
        # Posted, unknown or malformed: 404, and nothing decrypted.
        for invoice_id in (posted, _id(99), "not-a-uuid"):
            for response in (
                request(item_api, invoice_id, "admin"),
                request(image_api, invoice_id, "admin", suffix="/image"),
            ):
                assert response.status_code == 404
                assert json.loads(response.get_body())["code"] == "NOT_FOUND"
        assert key.reads == reads
        # Signed out: 401.
        response = request(item_api, banked)
        assert response.status_code == 401
    finally:
        staff.dispose()
        owner.dispose()
