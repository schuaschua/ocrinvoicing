"""Story 2.1: the PostgreSQL invoice repository (AD-3, AD-4, AD-5, AD-9) against a
real PostgreSQL 18, signed in as the pipeline login, and the engine's token sign-in."""

import asyncio
import dataclasses
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine, select, text

from invoicing.adapters.postgres import engine as engine_module
from invoicing.adapters.postgres.engine import (
    ENTRA_SCOPE,
    entra_token_provider,
    postgres_engine,
)
from invoicing.adapters.postgres.invoices import (
    PostgresInvoiceRepository,
    signed_phash,
    unsigned_phash,
)
from invoicing.adapters.postgres.schema import (
    admin_item,
    image_hash,
    invoice,
    status_history,
)
from invoicing.domain.reasons import ReasonCode
from invoicing.domain.status import InvoiceStatus
from invoicing.domain.transitions import AdminReason, plan_transition, route_to_admin
from invoicing.domain.upload import UploadContentType
from invoicing.ports.intake import DeviceCheck, IntakeBlobMetadata, IntakeSource
from invoicing.ports.invoices import InvoiceRepository, NewInvoice, QualityFacts

S = InvoiceStatus
INVOICE_ID = UUID("0192f0c1-7a2b-7c3d-8e4f-0123456789ab")
CORRELATION_ID = UUID("0192f0c1-7a2b-7c3d-8e4f-0000000000c0")
SUPPLIER_ID = UUID("0192f0c1-0000-7000-8000-000000000001")
METADATA = IntakeBlobMetadata(
    invoice_id=INVOICE_ID,
    source=IntakeSource.LINK,
    supplier_id=SUPPLIER_ID,
    content_type=UploadContentType.JPEG,
    uploaded_at=datetime(2026, 9, 29, 1, 30, tzinfo=UTC),
    device_check=DeviceCheck.OVERRIDDEN,
)
NEW = NewInvoice(METADATA, CORRELATION_ID, "pipeline:quality")
TAKEN = datetime(2026, 9, 20, 6, 30, 5, tzinfo=UTC)


def _repo(engine: Engine) -> InvoiceRepository:
    return PostgresInvoiceRepository(engine)


def _rows(engine: Engine, table: Any) -> list[Any]:
    with engine.connect() as connection:
        return list(connection.execute(select(table)).mappings())


def _history(engine: Engine) -> list[tuple[str | None, str, str]]:
    with engine.connect() as connection:
        rows = connection.execute(
            select(
                status_history.c.from_status,
                status_history.c.to_status,
                status_history.c.actor,
            ).order_by(status_history.c.id)
        )
        return [tuple(row) for row in rows]


@pytest.mark.parametrize(
    ("phash", "stored"),
    [
        (0, 0),
        (1, 1),
        ((1 << 63) - 1, (1 << 63) - 1),
        (1 << 63, -(1 << 63)),
        ((1 << 64) - 1, -1),
    ],
)
def test_story_2_1_phash_is_stored_as_a_signed_bigint_with_the_same_bits(
    phash: int, stored: int
) -> None:
    assert signed_phash(phash) == stored
    assert unsigned_phash(stored) == phash


@pytest.mark.parametrize("phash", [-1, 1 << 64])
def test_story_2_1_phash_must_be_64_bits(phash: int) -> None:
    with pytest.raises(ValueError):
        signed_phash(phash)


def test_story_2_1_insert_if_absent_creates_the_row_once_from_the_metadata(
    pipeline_engine: Engine,
) -> None:
    repo = _repo(pipeline_engine)
    assert asyncio.run(repo.status(INVOICE_ID)) is None
    assert asyncio.run(repo.insert_if_absent(NEW)) is True
    assert asyncio.run(repo.insert_if_absent(NEW)) is False
    (row,) = _rows(pipeline_engine, invoice)
    assert row["id"] == INVOICE_ID
    assert row["correlation_id"] == CORRELATION_ID
    assert (row["source"], row["supplier_id"], row["delivery_id"]) == (
        "link",
        SUPPLIER_ID,
        None,
    )
    assert (row["content_type"], row["device_check"]) == ("image/jpeg", "overridden")
    assert row["status"] == "received" and row["post_failures"] == 0
    assert row["status_changed_at"] == row["created_at"]
    assert row["photo_taken_at"] is None and row["po_number"] is None
    assert asyncio.run(repo.status(INVOICE_ID)) is S.RECEIVED
    assert _history(pipeline_engine) == [(None, "received", "pipeline:quality")]


def test_story_2_1_a_goods_in_scan_keeps_its_delivery(pipeline_engine: Engine) -> None:
    delivery = UUID("0192f0c1-0000-7000-8000-00000000de11")
    goods_in = METADATA.model_copy(
        update={"source": IntakeSource.GOODS_IN, "delivery_id": delivery}
    )
    asyncio.run(
        _repo(pipeline_engine).insert_if_absent(
            NewInvoice(goods_in, CORRELATION_ID, "t")
        )
    )
    (row,) = _rows(pipeline_engine, invoice)
    assert (row["source"], row["delivery_id"]) == ("goods_in", delivery)


def test_story_2_1_a_transition_is_conditional_and_writes_history_and_facts(
    pipeline_engine: Engine,
) -> None:
    repo = _repo(pipeline_engine)
    asyncio.run(repo.insert_if_absent(NEW))
    plan = plan_transition(
        INVOICE_ID, S.RECEIVED, S.AWAITING_EXTRACTION, "pipeline:quality"
    )
    facts = QualityFacts(photo_taken_at=TAKEN, phash=(1 << 64) - 2)
    assert asyncio.run(repo.transition(plan, quality=facts)) is True
    # The same plan again changes nothing and writes nothing (AD-2).
    assert asyncio.run(repo.transition(plan, quality=facts)) is False
    (row,) = _rows(pipeline_engine, invoice)
    assert row["status"] == "awaiting_extraction"
    assert row["photo_taken_at"] == TAKEN
    assert row["status_changed_at"] >= row["created_at"]
    (hashed,) = _rows(pipeline_engine, image_hash)
    assert unsigned_phash(hashed["phash"]) == (1 << 64) - 2
    assert _history(pipeline_engine) == [
        (None, "received", "pipeline:quality"),
        ("received", "awaiting_extraction", "pipeline:quality"),
    ]


def test_story_2_1_a_transition_without_facts_leaves_them_alone(
    pipeline_engine: Engine,
) -> None:
    repo = _repo(pipeline_engine)
    asyncio.run(repo.insert_if_absent(NEW))
    asyncio.run(
        repo.transition(
            plan_transition(INVOICE_ID, S.RECEIVED, S.AWAITING_EXTRACTION, "t"),
            quality=QualityFacts(photo_taken_at=TAKEN, phash=None),
        )
    )
    asyncio.run(
        repo.transition(
            plan_transition(INVOICE_ID, S.AWAITING_EXTRACTION, S.EXTRACTING, "t")
        )
    )
    (row,) = _rows(pipeline_engine, invoice)
    assert row["photo_taken_at"] == TAKEN and row["status"] == "extracting"
    assert _rows(pipeline_engine, image_hash) == []


def test_story_2_1_a_transition_of_a_missing_invoice_changes_nothing(
    pipeline_engine: Engine,
) -> None:
    plan = plan_transition(INVOICE_ID, S.RECEIVED, S.AWAITING_EXTRACTION, "t")
    assert asyncio.run(_repo(pipeline_engine).transition(plan)) is False
    assert _history(pipeline_engine) == []


def test_story_2_1_route_to_admin_writes_items_history_and_facts_in_one_go(
    pipeline_engine: Engine,
) -> None:
    repo = _repo(pipeline_engine)
    asyncio.run(repo.insert_if_absent(NEW))
    with pipeline_engine.begin() as connection:
        connection.execute(
            invoice.update().values(claimed_until=datetime(2030, 1, 1, tzinfo=UTC))
        )
    routing = route_to_admin(
        INVOICE_ID,
        [
            ReasonCode.UNREADABLE,
            AdminReason(ReasonCode.LOW_CONFIDENCE, ("invoice_total",), {"min": "0.5"}),
        ],
        S.RECEIVED,
        actor="pipeline:quality",
    )
    facts = QualityFacts(photo_taken_at=None, phash=5)
    assert asyncio.run(repo.route_to_admin(routing, quality=facts)) is True
    assert asyncio.run(repo.route_to_admin(routing, quality=facts)) is False
    (row,) = _rows(pipeline_engine, invoice)
    assert row["status"] == "in_admin_queue" and row["claimed_until"] is None
    items = sorted(_rows(pipeline_engine, admin_item), key=lambda r: r["reason"])
    assert [
        (i["reason"], i["routing_id"], i["field_ids"], i["detail"], i["run_id"])
        for i in items
    ] == [
        ("LOW_CONFIDENCE", routing.routing_id, ["invoice_total"], {"min": "0.5"}, None),
        ("UNREADABLE", routing.routing_id, [], {}, None),
    ]
    assert {i["id"] for i in items} == {i.id for i in routing.items}
    assert _history(pipeline_engine)[-1] == (
        "received",
        "in_admin_queue",
        "pipeline:quality",
    )
    assert len(_history(pipeline_engine)) == 2
    assert [r["phash"] for r in _rows(pipeline_engine, image_hash)] == [5]


def test_story_2_1_route_to_admin_creates_a_missing_row_from_the_metadata(
    pipeline_engine: Engine,
) -> None:
    routing = route_to_admin(
        INVOICE_ID, [ReasonCode.PROCESSING_FAILED], S.RECEIVED, actor="t"
    )
    assert (
        asyncio.run(_repo(pipeline_engine).route_to_admin(routing, metadata=NEW))
        is True
    )
    (row,) = _rows(pipeline_engine, invoice)
    assert row["supplier_id"] == SUPPLIER_ID and row["status"] == "in_admin_queue"
    assert [h[:2] for h in _history(pipeline_engine)] == [
        (None, "received"),
        ("received", "in_admin_queue"),
    ]


def test_story_2_1_route_to_admin_that_loses_the_race_writes_nothing(
    pipeline_engine: Engine,
) -> None:
    repo = _repo(pipeline_engine)
    asyncio.run(repo.insert_if_absent(NEW))
    asyncio.run(
        repo.transition(
            plan_transition(INVOICE_ID, S.RECEIVED, S.AWAITING_EXTRACTION, "t")
        )
    )
    routing = route_to_admin(INVOICE_ID, [ReasonCode.UNREADABLE], S.RECEIVED, actor="t")
    assert (
        asyncio.run(repo.route_to_admin(routing, quality=QualityFacts(None, 9)))
        is False
    )
    assert _rows(pipeline_engine, admin_item) == []
    assert _rows(pipeline_engine, image_hash) == []
    assert len(_history(pipeline_engine)) == 2


def test_story_2_1_route_to_admin_refuses_another_invoices_metadata(
    pipeline_engine: Engine,
) -> None:
    other = UUID("0192f0c1-7a2b-7c3d-8e4f-0000000000ff")
    routing = route_to_admin(other, [ReasonCode.UNREADABLE], S.RECEIVED, actor="t")
    with pytest.raises(ValueError, match="another invoice"):
        asyncio.run(_repo(pipeline_engine).route_to_admin(routing, metadata=NEW))
    assert _rows(pipeline_engine, invoice) == []


# --- The engine: Entra token sign-in (AD-11) --------------------------------------------


def test_story_2_1_the_engine_asks_for_a_password_per_new_connection(
    postgres_server: Any, intake_database: str
) -> None:
    calls: list[int] = []

    def token() -> str:
        calls.append(1)
        return str(postgres_server.password)

    engine = postgres_engine(
        host=postgres_server.host,
        port=postgres_server.port,
        database=intake_database,
        user=postgres_server.pipeline,
        password=token,
        sslmode="disable",
    )
    assert engine.url.password is None
    assert calls == []  # creating it opened nothing
    with engine.connect() as connection:
        assert (
            connection.execute(text("SELECT current_user")).scalar()
            == postgres_server.pipeline
        )
    with engine.connect():
        pass  # pooled: no new sign-in
    assert calls == [1]
    engine.dispose()
    with engine.connect():
        pass
    assert calls == [1, 1]
    engine.dispose()


def test_story_2_1_the_engine_requires_tls_by_default() -> None:
    engine = postgres_engine(
        host="babaloo-sea-lng-psql-21.postgres.database.azure.com",
        database="invoicing_dev",
        user="babaloo-sea-lng-id-03",
        password=lambda: "unused",
    )
    assert engine.url.query["sslmode"] == "require"
    assert engine.url.port == 5432
    assert engine.pool.size() == 2  # type: ignore[attr-defined]  # QueuePool


def test_story_2_1_tokens_come_from_the_apps_identity_for_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested: list[tuple[str, tuple[str, ...]]] = []

    class FakeToken:
        token = "entra-access-token"  # noqa: S105  # a fake token, not a secret

    class FakeManagedIdentity:
        def __init__(self, *, client_id: str) -> None:
            self.client_id = client_id

        def get_token(self, *scopes: str) -> FakeToken:
            requested.append((self.client_id, scopes))
            return FakeToken()

    monkeypatch.setattr(engine_module, "ManagedIdentityCredential", FakeManagedIdentity)
    provider = entra_token_provider("00000000-0000-0000-0000-00000000c1d0")
    assert requested == []
    assert provider() == "entra-access-token"
    assert requested == [("00000000-0000-0000-0000-00000000c1d0", (ENTRA_SCOPE,))]
    assert ENTRA_SCOPE == "https://ossrdbms-aad.database.windows.net/.default"


# --- Review fixes -------------------------------------------------------------------------


def test_story_2_1_a_discarded_routing_rolls_back_the_row_it_created(
    pipeline_engine: Engine,
) -> None:
    # The metadata creates the row as `received`, but the routing's from_status is
    # another status: the transition changes nothing, so nothing at all is kept.
    routing = route_to_admin(
        INVOICE_ID, [ReasonCode.PROCESSING_FAILED], S.EXTRACTING, actor="t"
    )
    assert (
        asyncio.run(_repo(pipeline_engine).route_to_admin(routing, metadata=NEW))
        is False
    )
    assert _rows(pipeline_engine, invoice) == []
    assert _history(pipeline_engine) == []
    assert _rows(pipeline_engine, admin_item) == []


def test_story_2_1_a_routing_without_items_is_refused(pipeline_engine: Engine) -> None:
    repo = _repo(pipeline_engine)
    asyncio.run(repo.insert_if_absent(NEW))
    routing = route_to_admin(INVOICE_ID, [ReasonCode.UNREADABLE], S.RECEIVED, actor="t")
    empty = dataclasses.replace(routing, items=())
    with pytest.raises(ValueError, match="at least one admin item"):
        asyncio.run(repo.route_to_admin(empty))
    assert asyncio.run(repo.status(INVOICE_ID)) is S.RECEIVED


def test_story_2_1_detail_ids_amounts_and_times_are_stored_as_text(
    pipeline_engine: Engine,
) -> None:
    repo = _repo(pipeline_engine)
    asyncio.run(repo.insert_if_absent(NEW))
    detail = {
        "po_line_id": UUID("0192f0c1-0000-7000-8000-0000000000aa"),
        "expected": Decimal("1234.50"),
        "actual": Decimal("0.10"),
        "received_date": date(2026, 9, 1),
        "at": datetime(2026, 9, 1, 8, 0, tzinfo=UTC),
        "nested": {"ids": [UUID(int=1)]},
    }
    routing = route_to_admin(
        INVOICE_ID,
        [AdminReason(ReasonCode.PO_MISMATCH, detail=detail)],
        S.RECEIVED,
        actor="t",
    )
    assert asyncio.run(repo.route_to_admin(routing)) is True
    (item,) = _rows(pipeline_engine, admin_item)
    assert item["detail"] == {
        "po_line_id": "0192f0c1-0000-7000-8000-0000000000aa",
        "expected": "1234.50",
        "actual": "0.10",
        "received_date": "2026-09-01",
        "at": "2026-09-01T08:00:00+00:00",
        "nested": {"ids": ["00000000-0000-0000-0000-000000000001"]},
    }


def test_story_2_1_detail_that_is_not_json_is_refused_and_nothing_is_written(
    pipeline_engine: Engine,
) -> None:
    repo = _repo(pipeline_engine)
    asyncio.run(repo.insert_if_absent(NEW))
    routing = route_to_admin(
        INVOICE_ID,
        [AdminReason(ReasonCode.PO_MISMATCH, detail={"raw": b"bytes"})],
        S.RECEIVED,
        actor="t",
    )
    with pytest.raises(TypeError, match="bytes can't be stored"):
        asyncio.run(repo.route_to_admin(routing))
    assert asyncio.run(repo.status(INVOICE_ID)) is S.RECEIVED
    assert _rows(pipeline_engine, admin_item) == []
