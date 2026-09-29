"""Story 2.1: the PostgreSQL invoice repository (AD-3, AD-4, AD-5, AD-9) against a
real PostgreSQL 18, signed in as the pipeline login, and the engine's token sign-in."""

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, select

from invoicing.adapters.postgres.invoices import (
    PostgresInvoiceRepository,
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
