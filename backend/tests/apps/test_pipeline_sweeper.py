"""Story 2.2: the sweeper timer (AD-2, AD-6, AD-17), every sweeper row of the
I/O matrix, against a real PostgreSQL 18 signed in as the pipeline login, with fake
queue, blob, table and metrics clients. The database's start time comes through the
repository's seam, except in "Just restarted", which uses the container's own. Every
age is measured on the database's clock, as the sweeper does."""

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from _pipeline_fakes import (
    CORRELATION_ID,
    FakeImages,
    FakeMetrics,
    FakeQueue,
    FakeUploadKeys,
    invoice_id,
    metadata,
)
from sqlalchemy import Engine, select, text, update

from invoicing.adapters.logging import event_fields
from invoicing.adapters.postgres.invoices import PostgresInvoiceRepository
from invoicing.adapters.postgres.schema import invoice
from invoicing.apps.pipeline import sweeper as sweeper_module
from invoicing.apps.pipeline.sweeper import Sweeper, SweepResult
from invoicing.domain.status import InvoiceStatus, Stage
from invoicing.ports.invoices import NewInvoice
from invoicing.ports.messages import QueueMessage
from invoicing.ports.queue import QueueName

S = InvoiceStatus
LONG_AGO = datetime(2026, 1, 1).astimezone()
ORPHAN_CORRELATION = UUID("0192f0c1-7a2b-7c3d-8e4f-0000000000c9")


def _key(n: int) -> UUID:
    return UUID(f"3fa85f64-5717-4562-b3fc-{n:012x}")


class Sweep:
    def __init__(self, engine: Engine, started_at: datetime | None = LONG_AGO) -> None:
        self.engine = engine
        self.queue = FakeQueue()
        self.images = FakeImages()
        self.keys = FakeUploadKeys()
        self.metrics = FakeMetrics()
        self.invoices = PostgresInvoiceRepository(
            engine, database_started_at=started_at
        )

    def run(self) -> SweepResult:
        return asyncio.run(
            Sweeper(
                self.invoices, self.keys, self.images, self.queue, self.metrics
            ).run()
        )

    def db_now(self) -> datetime:
        with self.engine.connect() as connection:
            value: datetime = connection.execute(text("SELECT now()")).scalar_one()
            return value

    def seed(
        self,
        n: int,
        status: S,
        *,
        changed: str = "2 hours",
        lease: str | None = None,
        next_attempt: str | None = None,
    ) -> UUID:
        target = invoice_id(n)
        asyncio.run(
            self.invoices.insert_if_absent(
                NewInvoice(metadata(target), CORRELATION_ID, "pipeline:quality")
            )
        )

        def relative(value: str | None) -> Any:
            if value is None:
                return None
            return text("now() + CAST(:v AS interval)").bindparams(v=value)

        with self.engine.begin() as connection:
            connection.execute(
                update(invoice)
                .where(invoice.c.id == target)
                .values(
                    status=status.value,
                    status_changed_at=text(
                        "now() - CAST(:changed AS interval)"
                    ).bindparams(changed=changed),
                    claimed_until=relative(lease),
                    next_attempt_at=relative(next_attempt),
                )
            )
        return target

    def created_at(self, target: UUID) -> datetime:
        with self.engine.connect() as connection:
            value: datetime = connection.execute(
                select(invoice.c.created_at).where(invoice.c.id == target)
            ).scalar_one()
            return value

    def key(
        self,
        n: int,
        target: UUID,
        age: timedelta,
        correlation_id: UUID = CORRELATION_ID,
    ) -> datetime:
        created = self.db_now() - age
        self.keys.add(_key(n), target, created, correlation_id=correlation_id)
        return created

    def sent(self) -> dict[UUID, QueueName]:
        return {message.invoice_id: queue for queue, message, _ in self.queue.sent}

    def stuck(self) -> list[float]:
        return [v for name, v, _ in self.metrics.emitted if name == "stuck_invoices"]


@pytest.fixture
def sweep(pipeline_engine: Engine) -> Sweep:
    return Sweep(pipeline_engine)


def _done(caplog: pytest.LogCaptureFixture) -> dict[str, Any]:
    (done,) = [r for r in caplog.records if r.getMessage().startswith("sweeper.done")]
    return dict(event_fields(done))


# --- Matrix rows ------------------------------------------------------------------------


def test_story_2_2_sweeper_re_enqueues_stale_rows_and_orphans_and_deletes_old_keys(
    sweep: Sweep,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    pipeline_engine: Engine,
    reset_intake: Callable[[], None],
) -> None:
    # --- Story 2.2: sweeper map re enqueues stale received to quality
    stale = sweep.seed(1, S.RECEIVED)
    # Story 2.3: extract is a consumed queue now, so it is swept too.
    waiting = sweep.seed(2, S.AWAITING_EXTRACTION)
    # Story 2.5: and validate.
    validating = sweep.seed(3, S.AWAITING_VALIDATION)
    with caplog.at_level(logging.DEBUG, logger="invoicing"):
        result = sweep.run()
    assert sweep.sent()[waiting] is QueueName.EXTRACT
    assert sweep.sent()[validating] is QueueName.VALIDATE
    # The invoice's own trace, first enqueued when it was created.
    assert [sent for sent in sweep.queue.sent if sent[1].invoice_id == stale] == [
        (
            QueueName.QUALITY,
            QueueMessage(
                invoice_id=stale,
                correlation_id=CORRELATION_ID,
                first_enqueued_at=sweep.created_at(stale),
                attempt=1,
            ),
            0,
        )
    ]
    assert result == SweepResult("swept", requeued=3)
    assert sweep.stuck() == [3]
    assert _done(caplog) == {
        "code": "swept",
        "requeued": 3,
        "orphans": 0,
        "deleted": 0,
        "failures": 0,
    }

    # --- Story 2.2: an orphaned upload is re enqueued once with its own ids
    reset_intake()
    sweep = Sweep(pipeline_engine)
    orphan = invoice_id(9)
    sweep.images.put(metadata(orphan))
    created = sweep.key(
        1, orphan, timedelta(hours=2), correlation_id=ORPHAN_CORRELATION
    )
    result = sweep.run()
    assert sweep.queue.sent == [
        (
            QueueName.QUALITY,
            QueueMessage(
                invoice_id=orphan,
                correlation_id=ORPHAN_CORRELATION,
                first_enqueued_at=created,
                attempt=1,
            ),
            0,
        )
    ]
    assert result == SweepResult("swept", orphans=1)
    assert sweep.stuck() == [1]
    # Marked recovered, on the database's clock; kept for a supplier retry (AD-6).
    assert abs(sweep.keys.recovered[_key(1)] - sweep.db_now()) < timedelta(minutes=1)
    assert sweep.keys.deleted == []
    # The next sweep sees the mark: never recovered twice, even if it fails again.
    assert sweep.run() == SweepResult("swept")
    assert len(sweep.queue.sent) == 1
    assert sweep.stuck() == [1, 0]

    # --- Story 2.2: old keys are deleted
    reset_intake()
    sweep = Sweep(pipeline_engine)
    done = sweep.seed(1, S.POSTED, changed="1 day")
    orphan, lost, recovered = invoice_id(8), invoice_id(9), invoice_id(10)
    sweep.images.put(metadata(orphan))
    sweep.key(1, done, timedelta(hours=25))
    sweep.key(2, orphan, timedelta(hours=30))
    sweep.key(3, lost, timedelta(days=3))
    sweep.key(4, done, timedelta(hours=23))
    sweep.key(5, recovered, timedelta(hours=26))
    sweep.keys.recovered[_key(5)] = LONG_AGO
    result = sweep.run()
    # Every key older than 24 hours goes; an orphan is enqueued (and marked) first,
    # and deleted with the ETag of its mark.
    assert sorted(sweep.keys.deleted) == [_key(1), _key(2), _key(3), _key(5)]
    assert list(sweep.keys.rows) == [_key(4)]
    assert sweep.sent() == {orphan: QueueName.QUALITY}
    assert result == SweepResult("swept", orphans=1, deleted=4)

    # --- Story 2.2: a key changed since listing is not deleted
    reset_intake()
    sweep = Sweep(pipeline_engine)
    done = sweep.seed(1, S.POSTED)
    sweep.key(1, done, timedelta(days=2))
    sweep.keys.changed.add(_key(1))
    assert sweep.run() == SweepResult("swept")
    assert list(sweep.keys.rows) == [_key(1)]

    # --- Story 2.2: sweeper leaves admin final fresh backoff and leased rows alone
    # (Last: it widens CONSUMED_QUEUES for the rest of the test.)
    reset_intake()
    sweep = Sweep(pipeline_engine)
    monkeypatch.setattr(sweeper_module, "CONSUMED_QUEUES", frozenset(Stage))
    sweep.seed(1, S.IN_ADMIN_QUEUE, changed="3 days")
    sweep.seed(2, S.POSTED, changed="3 days")
    sweep.seed(3, S.REJECTED, changed="3 days")
    sweep.seed(4, S.RECEIVED, changed="59 minutes")
    sweep.seed(5, S.READY_TO_POST, next_attempt="10 minutes")
    sweep.seed(6, S.EXTRACTING, lease="5 minutes")
    sweep.seed(7, S.VALIDATING, lease="5 minutes")
    sweep.seed(8, S.POSTING, lease="5 minutes")
    assert sweep.run() == SweepResult("swept")
    assert sweep.queue.sent == []
    # Emitted as 0, so the stuck_invoices alert resolves.
    assert sweep.stuck() == [0]
