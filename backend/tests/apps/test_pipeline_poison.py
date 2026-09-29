"""Story 2.2: the poison triggers (AD-2, AD-4, AD-17), one test per poison row of the
I/O matrix, against a real PostgreSQL 18 signed in as the pipeline login, with fake
blob storage and metrics."""

import asyncio
from typing import Any

import pytest
from _pipeline_fakes import (
    CORRELATION_ID,
    SUPPLIER_ID,
    UPLOADED_AT,
    FakeImages,
    FakeMetrics,
    invoice_id,
    metadata,
)
from sqlalchemy import Engine, select, text, update

from invoicing.adapters.postgres.invoices import PostgresInvoiceRepository
from invoicing.adapters.postgres.schema import admin_item, invoice, status_history
from invoicing.apps.pipeline.poison import (
    PoisonAction,
    PoisonOutcome,
    poison_handler,
)
from invoicing.domain.status import InvoiceStatus, Stage
from invoicing.ports.invoices import NewInvoice
from invoicing.ports.messages import QueueMessage

S = InvoiceStatus
INVOICE_ID = invoice_id(1)
ROUTED = PoisonOutcome(PoisonAction.ROUTE, "ROUTED")


def _message(attempt: int = 5) -> str:
    return QueueMessage(
        invoice_id=INVOICE_ID,
        correlation_id=CORRELATION_ID,
        first_enqueued_at=UPLOADED_AT,
        attempt=attempt,
    ).to_json()


class Poison:
    def __init__(self, engine: Engine, stage: Stage) -> None:
        self.engine = engine
        self.images = FakeImages()
        self.metrics = FakeMetrics()
        self.invoices = PostgresInvoiceRepository(engine)
        self.handle = poison_handler(stage, self.images, self.invoices, self.metrics)

    def run(
        self, body: str | bytes | None = None, dequeue_count: int = 1
    ) -> PoisonOutcome:
        return asyncio.run(self.handle(body or _message(), dequeue_count))

    def seed(
        self, status: S, lease: str | None = None, next_attempt: str | None = None
    ) -> None:
        asyncio.run(
            self.invoices.insert_if_absent(
                NewInvoice(metadata(INVOICE_ID), CORRELATION_ID, "pipeline:quality")
            )
        )
        with self.engine.begin() as connection:
            connection.execute(
                update(invoice)
                .where(invoice.c.id == INVOICE_ID)
                .values(
                    status=status.value,
                    claimed_until=None
                    if lease is None
                    else text("now() + CAST(:lease AS interval)").bindparams(
                        lease=lease
                    ),
                    next_attempt_at=None
                    if next_attempt is None
                    else text("now() + CAST(:next AS interval)").bindparams(
                        next=next_attempt
                    ),
                )
            )

    def rows(self, table: Any) -> list[Any]:
        with self.engine.connect() as connection:
            return list(connection.execute(select(table)).mappings())

    def status(self) -> str | None:
        rows = self.rows(invoice)
        return rows[0]["status"] if rows else None

    def counted(self, queue: str) -> bool:
        return self.metrics.emitted == [("poison_message", 1, {"queue": queue})]


@pytest.fixture
def quality(pipeline_engine: Engine) -> Poison:
    return Poison(pipeline_engine, Stage.QUALITY)


def _assert_routed(poison: Poison, outcome: PoisonOutcome, queue: str) -> None:
    assert outcome == ROUTED
    assert poison.status() == "in_admin_queue"
    (item,) = poison.rows(admin_item)
    assert item["reason"] == "PROCESSING_FAILED"
    # Which stage gave up, as a code (AD-4 detail holds ids and codes only).
    assert item["detail"] == {"queue": queue}
    assert item["routing_id"].version == 7


# --- Matrix rows ------------------------------------------------------------------------


def test_story_2_2_poison_in_the_input_state_is_routed_and_counted(
    quality: Poison,
) -> None:
    quality.seed(S.RECEIVED)
    _assert_routed(quality, quality.run(), "q-quality")
    with quality.engine.connect() as connection:
        last = connection.execute(
            select(
                status_history.c.from_status,
                status_history.c.to_status,
                status_history.c.actor,
            )
            .order_by(status_history.c.id.desc())
            .limit(1)
        ).one()
    assert tuple(last) == ("received", "in_admin_queue", "pipeline:poison")
    assert quality.counted("q-quality-poison")
    # The blob was never needed: the row exists.
    assert quality.images.reads == []


def test_story_2_2_poison_with_no_row_creates_it_from_the_blob_metadata(
    quality: Poison,
) -> None:
    quality.images.put(metadata(INVOICE_ID))
    _assert_routed(quality, quality.run(), "q-quality")
    # The metadata came from the blob's properties: its bytes were never downloaded.
    assert quality.images.reads == []
    (row,) = quality.rows(invoice)
    # AD-5: the supplier comes from the metadata; the trace id from the message.
    assert (row["supplier_id"], row["source"], row["correlation_id"]) == (
        SUPPLIER_ID,
        "link",
        CORRELATION_ID,
    )
    with quality.engine.connect() as connection:
        history = connection.execute(
            select(status_history.c.from_status, status_history.c.to_status).order_by(
                status_history.c.id
            )
        ).all()
    assert [tuple(h) for h in history] == [
        (None, "received"),
        ("received", "in_admin_queue"),
    ]
    assert quality.counted("q-quality-poison")


@pytest.mark.parametrize(
    ("stage", "claim_state", "queue"),
    [(Stage.EXTRACT, S.EXTRACTING, "q-extract")],
)
def test_story_2_2_poison_with_an_expired_claim_is_routed(
    pipeline_engine: Engine, stage: Stage, claim_state: S, queue: str
) -> None:
    poison = Poison(pipeline_engine, stage)
    poison.seed(claim_state, lease="-1 minute")
    _assert_routed(poison, poison.run(), queue)
    assert poison.rows(invoice)[0]["claimed_until"] is None
    assert poison.counted(f"{queue}-poison")


@pytest.mark.parametrize(
    ("stage", "claim_state"),
    [(Stage.EXTRACT, S.EXTRACTING)],
)
def test_story_2_2_poison_never_takes_a_live_claim(
    pipeline_engine: Engine, stage: Stage, claim_state: S
) -> None:
    poison = Poison(pipeline_engine, stage)
    poison.seed(claim_state, lease="5 minutes")
    assert poison.run() == PoisonOutcome(PoisonAction.ACK, "MOVED_ON")
    assert poison.status() == claim_state.value
    assert poison.rows(admin_item) == []
