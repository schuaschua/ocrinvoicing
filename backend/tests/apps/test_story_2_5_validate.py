"""Story 2.5: the `validate` stage end to end, against a real PostgreSQL 18 signed in
as the pipeline login, with the purchasing simulation's synthetic seed (PO-45012 of
Synthetic Alpha) and a fake queue.

One merged test (the 200-case cap, coding-style.md rule 20 exception): each plan
matrix row is a block of assertions, in order."""

import asyncio
import logging
from collections.abc import Callable
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine, create_engine, func, select, text

from apps._pipeline_fakes import FakeQueue, FakeReminders
from apps._validation_seed import Seeder, header, message, one, seed_master
from conftest import PostgresServer
from contracts.purchasing_contract import (
    CEMENT,
    DELIVERY_12_1,
    DELIVERY_12_2,
    LINE_12_1,
    LINE_12_2,
    REBAR,
)
from invoicing.adapters.postgres.invoices import PostgresInvoiceRepository
from invoicing.adapters.postgres.schema import admin_item, invoice, invoice_line
from invoicing.adapters.postgres.suppliers import PostgresSupplierReader
from invoicing.adapters.postgres.validation import PostgresValidationRepository
from invoicing.adapters.purchasing_factory import purchasing_port
from invoicing.apps.pipeline.quality import StageFailed
from invoicing.apps.pipeline.validate import (
    ValidateAction,
    ValidateDependencies,
    validate_handler,
)
from invoicing.ports.queue import QueueName
from invoicing.ports.validation import ComputeResult


def _lines(engine: Engine, for_invoice: UUID) -> list[tuple[Any, ...]]:
    with engine.connect() as connection:
        return [
            tuple(row)
            for row in connection.execute(
                select(
                    invoice_line.c.line_no,
                    invoice_line.c.po_line_id,
                    invoice_line.c.material_id,
                )
                .where(invoice_line.c.invoice_id == for_invoice)
                .order_by(invoice_line.c.line_no)
            )
        ]


def test_story_2_5_validate_stage(
    pipeline_engine: Engine,
    postgres_server: PostgresServer,
    purchasing_seeded: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="invoicing")
    owner = create_engine(
        postgres_server.url(postgres_server.deployer, purchasing_seeded)
    )
    seed_master(owner)
    seed = Seeder(owner)
    queue = FakeQueue()
    invoices = PostgresInvoiceRepository(pipeline_engine)
    validations = PostgresValidationRepository(pipeline_engine, invoices)
    before_finish: list[Callable[[], None]] = []

    class Racing:
        """The real repository; a test hook runs just before the finish."""

        async def load(self, for_invoice: UUID) -> Any:
            return await validations.load(for_invoice)

        async def finish_locked(
            self, for_invoice: UUID, supplier_id: UUID, compute: ComputeResult
        ) -> bool:
            for hook in before_finish:
                hook()
            return await validations.finish_locked(for_invoice, supplier_id, compute)

    handle = validate_handler(
        ValidateDependencies(
            invoices=invoices,
            validations=Racing(),
            purchasing=purchasing_port("sim", pipeline_engine),
            suppliers=PostgresSupplierReader(pipeline_engine),
            queue=queue,
            reminders=FakeReminders(),
        )
    )

    def run(for_invoice: UUID) -> Any:
        return asyncio.run(handle(message(for_invoice)))

    def status(for_invoice: UUID) -> tuple[str, str | None]:
        row = one(
            pipeline_engine,
            select(invoice.c.status, invoice.c.po_number).where(
                invoice.c.id == for_invoice
            ),
        )
        return row[0], row[1]

    # --- Partial deliveries: earlier invoices already hold 30 of the 100 received -----
    # One matched earlier (in the admin queue, its line corrected by an admin from 20
    # to 30: the current value counts); one rejected (never counts).
    earlier = seed.invoice(
        10,
        fields=header("234.00"),
        lines=[("ALP-CEM-50", "20", "7.80")],
        status="in_admin_queue",
        matched={1: LINE_12_1},
    )
    seed.line(
        earlier,
        UUID(int=10),
        10,
        1,
        "ALP-CEM-50",
        "30",
        "7.80",
        {1: LINE_12_1},
        source="admin",
    )
    seed.invoice(
        11,
        fields=header("390.00"),
        lines=[("ALP-CEM-50", "50", "7.80")],
        status="rejected",
        matched={1: LINE_12_1},
    )

    # --- All pass: 70 x 7.80 = 546.00 still to invoice, tax ids equal ------------------
    first = seed.invoice(
        1,
        fields={**header("546.00"), "payment[0].iban": (None, 0.1)},
        lines=[("ALP-CEM-50", "70", "7.80")],
    )
    outcome = run(first)
    assert outcome.action is ValidateAction.ADVANCE
    assert status(first) == ("ready_to_post", "PO-45012")
    assert _lines(pipeline_engine, first) == [(1, LINE_12_1, CEMENT)]
    assert [(q, m.invoice_id) for q, m, _ in queue.sent] == [(QueueName.POST, first)]
    lease = one(
        pipeline_engine, select(invoice.c.claimed_until).where(invoice.c.id == first)
    )
    assert lease[0] is None
    # Redelivered: already ready_to_post, so q-post is queued again (AD-2).
    queue.sent.clear()
    assert run(first).action is ValidateAction.ACK
    assert [q for q, _, _ in queue.sent] == [QueueName.POST]
    # Re-validated (e.g. after an admin correction): its own 70 is not deducted.
    with owner.begin() as connection:
        connection.execute(
            text(
                "UPDATE intake.invoice SET status = 'awaiting_validation' WHERE id = :id"
            ),
            {"id": first},
        )
    assert run(first).action is ValidateAction.ADVANCE
    assert status(first) == ("ready_to_post", "PO-45012")

    # --- Goods-in scan: PO and received quantity from its own delivery ----------------
    # Delivery 2 received 50 rebar; the scan carries no purchase_order and no tax id.
    queue.sent.clear()
    scan = seed.invoice(
        2,
        fields=header("925.00", po=None, tax_id=None),
        lines=[("ALP-RB-12", "50", "18.50")],
        source="goods_in",
        delivery_id=DELIVERY_12_2,
    )
    assert run(scan).action is ValidateAction.ADVANCE
    assert status(scan) == ("ready_to_post", "PO-45012")
    assert _lines(pipeline_engine, scan) == [(1, LINE_12_2, REBAR)]
    # Only its own delivery's receipt counts: delivery 1 received no rebar.
    other_delivery = seed.invoice(
        6,
        fields=header("925.00", po=None, tax_id=None, number="INV-A-6"),
        lines=[("ALP-RB-12", "50", "18.50")],
        source="goods_in",
        delivery_id=DELIVERY_12_1,
    )
    outcome = run(other_delivery)
    assert (outcome.action, outcome.reasons) == (
        ValidateAction.ROUTE,
        ("PO_MISMATCH",),
    )
    with pipeline_engine.connect() as connection:
        detail = connection.execute(
            select(admin_item.c.detail).where(admin_item.c.invoice_id == other_delivery)
        ).scalar_one()
    assert detail == {
        "expected": "0.00",
        "actual": "925.00",
        "problems": ["AMOUNT_OUTSIDE_TOLERANCE"],
    }

    # --- Several reasons: one routing, three items, one routing_id, each run_id -------
    queue.sent.clear()
    several = seed.invoice(
        3,
        fields={
            **header("100.00", po="PO-45013", tax_id="T99999999Z"),
            "invoice_date": ("2026-09-20", 0.5),
        },
        lines=[("ALP-CEM-50", "10", "7.80"), ("ALP-RB-12", None, "18.50")],
    )
    outcome = run(several)
    assert outcome.action is ValidateAction.ROUTE
    assert queue.sent == []
    assert status(several) == ("in_admin_queue", None)
    with pipeline_engine.connect() as connection:
        items = {
            row.reason: row
            for row in connection.execute(
                select(admin_item).where(admin_item.c.invoice_id == several)
            )
        }
    assert set(items) == {"LOW_CONFIDENCE", "PO_MISMATCH", "SUPPLIER_ID_MISMATCH"}
    assert len({row.routing_id for row in items.values()}) == 1
    assert {row.run_id for row in items.values()} == {UUID(int=3)}
    assert items["LOW_CONFIDENCE"].field_ids == ["invoice_date", "line[2].quantity"]
    assert items["PO_MISMATCH"].detail == {
        "expected": None,
        "actual": "100.00",
        "problems": ["PO_OTHER_SUPPLIER"],
    }
    assert items["SUPPLIER_ID_MISMATCH"].detail == {"basis": "tax_id"}
    # Another supplier's PO matches nothing.
    assert _lines(pipeline_engine, several) == [(1, None, None), (2, None, None)]
    logged = " ".join(str(record.__dict__) for record in caplog.records)
    assert "LOW_CONFIDENCE,PO_MISMATCH,SUPPLIER_ID_MISMATCH" in logged
    # No field value reaches a log (security.md rule 31).
    for value in ("Synthetic Alpha", "T99999999Z", "PO-45013", "546.00"):
        assert value not in logged

    # --- Lost race: the finish changes 0 rows, so nothing is written, only acked ------
    # Both finishes: to ready_to_post (all pass) and a routing (an unknown PO).
    passing = seed.invoice(
        4, fields=header("0.00"), lines=[("ALP-CEM-50", "1", "7.80")]
    )
    failing = seed.invoice(
        7, fields=header("7.80", po="PO-99999"), lines=[("ALP-CEM-50", "1", "7.80")]
    )
    for lost in (passing, failing):

        def move_on(target: UUID = lost) -> None:
            with owner.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE intake.invoice SET status = 'rejected' WHERE id = :id"
                    ),
                    {"id": target},
                )

        before_finish.append(move_on)
        assert run(lost).action is ValidateAction.ACK
        before_finish.clear()
        assert status(lost) == ("rejected", None)
        assert _lines(pipeline_engine, lost) == [(1, None, None)]
        with pipeline_engine.connect() as connection:
            routed = connection.execute(
                select(func.count()).where(admin_item.c.invoice_id == lost)
            ).scalar_one()
        assert routed == 0

    # --- No run: raised with a code for a host retry, lease ended ---------------------
    no_run = seed.invoice(5, fields={}, lines=[], run=False)
    with pytest.raises(StageFailed, match="NO_EXTRACTION_RUN"):
        run(no_run)
    ended = one(
        pipeline_engine,
        select(
            invoice.c.status,
            invoice.c.claimed_until <= func.now(),
        ).where(invoice.c.id == no_run),
    )
    assert tuple(ended) == ("validating", True)
    assert "NO_EXTRACTION_RUN" in caplog.text
    owner.dispose()
