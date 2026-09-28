"""Story 2.2: the poison triggers (AD-2, AD-4, AD-17), one test per poison row of the
I/O matrix, against a real PostgreSQL 18 signed in as the pipeline login, with fake
blob storage and metrics."""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any
from uuid import UUID

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
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy import Engine, select, text, update

import invoicing
from invoicing.adapters.logging import ALLOWED_KEYS, DROPPED_FIELDS_KEY, event_fields
from invoicing.adapters.postgres.invoices import PostgresInvoiceRepository
from invoicing.adapters.postgres.schema import admin_item, invoice, status_history
from invoicing.apps.pipeline.poison import (
    MAX_DEQUEUE_COUNT,
    PoisonAction,
    PoisonFailed,
    PoisonOutcome,
    poison_handler,
)
from invoicing.domain.errors import ServiceUnavailableError
from invoicing.domain.status import InvoiceStatus, Stage
from invoicing.ports.intake import IntakeSource
from invoicing.ports.invoices import NewInvoice
from invoicing.ports.messages import QueueMessage

S = InvoiceStatus
APPS_DIR = Path(invoicing.__file__).parent / "apps"
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


def test_story_2_2_poison_for_an_invoice_that_moved_on_is_only_acknowledged(
    quality: Poison,
) -> None:
    quality.seed(S.AWAITING_EXTRACTION)
    assert quality.run() == PoisonOutcome(PoisonAction.ACK, "MOVED_ON")
    assert quality.status() == "awaiting_extraction"
    assert quality.rows(admin_item) == []
    assert quality.counted("q-quality-poison")


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


def test_story_2_2_poison_with_no_row_and_no_blob_logs_a_code_and_acknowledges(
    quality: Poison, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG, logger="invoicing"):
        outcome = quality.run()
    assert outcome == PoisonOutcome(PoisonAction.ACK, "IMAGE_NOT_FOUND")
    assert quality.rows(invoice) == []
    assert quality.counted("q-quality-poison")
    (done,) = [r for r in caplog.records if r.getMessage().startswith("poison.done ")]
    assert event_fields(done) == {
        "queue": "q-quality-poison",
        "invoice_id": str(INVOICE_ID),
        "correlation_id": str(CORRELATION_ID),
        "attempt": 5,
        "code": "IMAGE_NOT_FOUND",
    }


@pytest.mark.parametrize(
    ("source", "delivery_id", "code"),
    [
        (IntakeSource.GOODS_IN, None, "SOURCE_DELIVERY_MISMATCH"),
        (
            IntakeSource.LINK,
            UUID("0192f0c1-0000-7000-8000-00000000de11"),
            "SOURCE_DELIVERY_MISMATCH",
        ),
    ],
)
def test_story_2_2_metadata_a_row_cant_be_made_from_is_acknowledged_by_code(
    quality: Poison, source: IntakeSource, delivery_id: UUID | None, code: str
) -> None:
    quality.images.put(metadata(INVOICE_ID, source=source, delivery_id=delivery_id))
    assert quality.run() == PoisonOutcome(PoisonAction.ACK, code)
    assert quality.rows(invoice) == []


def test_story_2_2_metadata_for_another_invoice_is_acknowledged_by_code(
    quality: Poison,
) -> None:
    quality.images.put(metadata(invoice_id(2)))
    quality.images.blobs[INVOICE_ID] = quality.images.blobs.pop(invoice_id(2))
    assert quality.run() == PoisonOutcome(PoisonAction.ACK, "METADATA_INVOICE_MISMATCH")


def test_story_2_2_unreadable_blob_metadata_is_acknowledged_by_code(
    quality: Poison, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def bad(invoice_id: UUID) -> Any:
        raise ValueError("the blob metadata is not IntakeBlobMetadata")

    monkeypatch.setattr(quality.images, "metadata", bad)
    assert quality.run() == PoisonOutcome(PoisonAction.ACK, "BAD_METADATA")


@pytest.mark.parametrize(
    ("stage", "claim_state", "queue"),
    [
        (Stage.EXTRACT, S.EXTRACTING, "q-extract"),
        (Stage.VALIDATE, S.VALIDATING, "q-validate"),
        (Stage.POST, S.POSTING, "q-post"),
    ],
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
    [
        (Stage.EXTRACT, S.EXTRACTING),
        (Stage.VALIDATE, S.VALIDATING),
        (Stage.POST, S.POSTING),
    ],
)
def test_story_2_2_poison_never_takes_a_live_claim(
    pipeline_engine: Engine, stage: Stage, claim_state: S
) -> None:
    poison = Poison(pipeline_engine, stage)
    poison.seed(claim_state, lease="5 minutes")
    assert poison.run() == PoisonOutcome(PoisonAction.ACK, "MOVED_ON")
    assert poison.status() == claim_state.value
    assert poison.rows(admin_item) == []


@pytest.mark.parametrize(
    ("stage", "input_state", "queue"),
    [
        (Stage.EXTRACT, S.AWAITING_EXTRACTION, "q-extract"),
        (Stage.VALIDATE, S.AWAITING_VALIDATION, "q-validate"),
        (Stage.POST, S.READY_TO_POST, "q-post"),
    ],
)
def test_story_2_2_poison_in_each_queues_input_state_is_routed(
    pipeline_engine: Engine, stage: Stage, input_state: S, queue: str
) -> None:
    poison = Poison(pipeline_engine, stage)
    poison.seed(input_state)
    _assert_routed(poison, poison.run(), queue)


def test_story_2_2_a_missing_row_on_a_later_queue_is_only_acknowledged(
    pipeline_engine: Engine,
) -> None:
    poison = Poison(pipeline_engine, Stage.VALIDATE)
    poison.images.put(metadata(INVOICE_ID))
    assert poison.run() == PoisonOutcome(PoisonAction.ACK, "ROW_MISSING")
    assert poison.rows(invoice) == []
    assert poison.counted("q-validate-poison")


def test_story_2_2_a_routing_that_loses_the_race_is_only_acknowledged(
    quality: Poison, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The invoice advances between the guard's read and the routing.
    quality.seed(S.RECEIVED)
    real = quality.invoices.route_to_admin

    async def racing(routing: Any, **kwargs: Any) -> bool:
        with quality.engine.begin() as connection:
            connection.execute(update(invoice).values(status="awaiting_extraction"))
        return await real(routing, **kwargs)

    monkeypatch.setattr(quality.invoices, "route_to_admin", racing)
    assert quality.run() == PoisonOutcome(PoisonAction.ACK, "MOVED_ON")
    assert quality.rows(admin_item) == []


# --- The handler around it -------------------------------------------------------------


@pytest.mark.parametrize("body", ["not json", '{"invoice_id": "x"}', b"\xff\xfe"])
def test_story_2_2_a_malformed_poison_message_is_counted_and_acknowledged(
    quality: Poison, body: str | bytes, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG, logger="invoicing"):
        assert quality.run(body) == PoisonOutcome(PoisonAction.ACK, "MALFORMED_MESSAGE")
    assert quality.counted("q-quality-poison")
    (record,) = [r for r in caplog.records if r.name.startswith("invoicing")]
    assert event_fields(record) == {
        "queue": "q-quality-poison",
        "code": "MALFORMED_MESSAGE",
    }


def test_story_2_2_a_failure_before_the_last_delivery_is_raised_uncounted(
    quality: Poison, caplog: pytest.LogCaptureFixture
) -> None:
    quality.images.error = ServiceUnavailableError()
    with (
        caplog.at_level(logging.DEBUG, logger="invoicing"),
        pytest.raises(PoisonFailed) as raised,
    ):
        quality.run(dequeue_count=MAX_DEQUEUE_COUNT - 1)
    assert raised.value.code == "ServiceUnavailableError"
    assert raised.value.__cause__ is None and raised.value.__suppress_context__
    # Retried by the host: counted only on its final outcome.
    assert quality.metrics.emitted == []
    (failed,) = [
        r for r in caplog.records if r.getMessage().startswith("poison.failed ")
    ]
    assert event_fields(failed)["code"] == "ServiceUnavailableError"


def test_story_2_2_a_poison_message_is_counted_once_across_its_retries(
    quality: Poison,
) -> None:
    quality.images.put(metadata(INVOICE_ID))
    quality.images.error = ServiceUnavailableError()
    for dequeue_count in range(1, MAX_DEQUEUE_COUNT):
        with pytest.raises(PoisonFailed):
            quality.run(dequeue_count=dequeue_count)
    quality.images.error = None
    _assert_routed(quality, quality.run(dequeue_count=MAX_DEQUEUE_COUNT), "q-quality")
    assert quality.counted("q-quality-poison")


def test_story_2_2_a_failure_on_the_last_delivery_is_abandoned_counted_and_acked(
    quality: Poison, caplog: pytest.LogCaptureFixture
) -> None:
    assert MAX_DEQUEUE_COUNT == 5
    quality.images.error = ServiceUnavailableError()
    with caplog.at_level(logging.DEBUG, logger="invoicing"):
        outcome = quality.run(dequeue_count=MAX_DEQUEUE_COUNT)
    # Acknowledged: nothing watches `q-quality-poison-poison`.
    assert outcome == PoisonOutcome(PoisonAction.ACK, "POISON_ABANDONED")
    assert quality.counted("q-quality-poison")
    (done,) = [r for r in caplog.records if r.getMessage().startswith("poison.done ")]
    assert done.levelno == logging.ERROR
    assert event_fields(done)["code"] == "POISON_ABANDONED"
    assert event_fields(done)["reason"] == "ServiceUnavailableError"


def test_story_2_2_max_dequeue_count_matches_host_json() -> None:
    host = json.loads((APPS_DIR / "pipeline" / "host.json").read_text())
    assert host["extensions"]["queues"]["maxDequeueCount"] == MAX_DEQUEUE_COUNT


@pytest.mark.parametrize(
    ("stage", "claim_state"),
    [
        (Stage.EXTRACT, S.EXTRACTING),
        (Stage.VALIDATE, S.VALIDATING),
        (Stage.POST, S.POSTING),
    ],
)
def test_story_2_2_a_lease_renewed_after_the_read_is_never_taken(
    pipeline_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    stage: Stage,
    claim_state: S,
) -> None:
    # The guard reads an expired lease; a worker reclaims it before the routing runs.
    poison = Poison(pipeline_engine, stage)
    poison.seed(claim_state, lease="-1 minute")
    real = poison.invoices.route_to_admin

    async def reclaimed_first(routing: Any, **kwargs: Any) -> bool:
        with poison.engine.begin() as connection:
            connection.execute(
                update(invoice).values(
                    claimed_until=text("now() + interval '10 minutes'")
                )
            )
        return await real(routing, **kwargs)

    monkeypatch.setattr(poison.invoices, "route_to_admin", reclaimed_first)
    assert poison.run() == PoisonOutcome(PoisonAction.ACK, "MOVED_ON")
    assert poison.status() == claim_state.value
    assert poison.rows(admin_item) == []


def test_story_2_2_a_post_poison_leaves_an_invoice_waiting_on_its_backoff(
    pipeline_engine: Engine,
) -> None:
    poison = Poison(pipeline_engine, Stage.POST)
    poison.seed(S.READY_TO_POST, next_attempt="5 minutes")
    assert poison.run() == PoisonOutcome(PoisonAction.ACK, "MOVED_ON")
    assert poison.status() == "ready_to_post"
    assert poison.rows(admin_item) == []


def test_story_2_2_the_poison_trigger_runs_in_the_invoices_trace_and_logs_codes_only(
    quality: Poison, spans: InMemorySpanExporter, caplog: pytest.LogCaptureFixture
) -> None:
    quality.seed(S.RECEIVED)
    with caplog.at_level(logging.DEBUG, logger="invoicing"):
        quality.run()
    (span,) = [s for s in spans.get_finished_spans() if s.name == "pipeline.poison"]
    assert span.context is not None and span.context.trace_id == CORRELATION_ID.int
    assert dict(span.attributes or {}) == {
        "correlation_id": str(CORRELATION_ID),
        "invoice_id": str(INVOICE_ID),
        "stage": "quality",
        "queue": "q-quality-poison",
        "attempt": 5,
    }
    for record in caplog.records:
        if record.name.startswith("invoicing"):
            assert DROPPED_FIELDS_KEY not in event_fields(record)
            assert set(event_fields(record)) <= ALLOWED_KEYS
