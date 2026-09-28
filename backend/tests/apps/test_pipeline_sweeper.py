"""Story 2.2: the sweeper timer (AD-2, AD-6, AD-17), one test per sweeper row of the
I/O matrix, against a real PostgreSQL 18 signed in as the pipeline login, with fake
queue, blob, table and metrics clients. The database's start time comes through the
repository's seam, except in "Just restarted", which uses the container's own. Every
age is measured on the database's clock, as the sweeper does."""

import asyncio
import logging
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
    stopped_database,
)
from sqlalchemy import Engine, select, text, update

from invoicing.adapters.logging import ALLOWED_KEYS, DROPPED_FIELDS_KEY, event_fields
from invoicing.adapters.postgres.invoices import PostgresInvoiceRepository
from invoicing.adapters.postgres.schema import invoice
from invoicing.apps.pipeline import sweeper as sweeper_module
from invoicing.apps.pipeline.sweeper import SWEEP_SCHEDULE, Sweeper, SweepResult
from invoicing.domain.errors import DatabaseOfflineError, ServiceUnavailableError
from invoicing.domain.status import InvoiceStatus, Stage
from invoicing.domain.sweep import SWEEP_LIMIT
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


def test_story_2_2_the_sweeper_runs_every_15_minutes_utc() -> None:
    # NCRONTAB, seconds first; the host runs timers in UTC (AD-1).
    assert SWEEP_SCHEDULE == "0 */15 * * * *"


# --- Matrix rows ------------------------------------------------------------------------


def test_story_2_2_sweeper_map_re_enqueues_stale_received_to_quality(
    sweep: Sweep, caplog: pytest.LogCaptureFixture
) -> None:
    stale = sweep.seed(1, S.RECEIVED)
    with caplog.at_level(logging.DEBUG, logger="invoicing"):
        result = sweep.run()
    # The invoice's own trace, first enqueued when it was created.
    assert sweep.queue.sent == [
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
    assert result == SweepResult("swept", requeued=1)
    assert sweep.stuck() == [1]
    assert _done(caplog) == {
        "code": "swept",
        "requeued": 1,
        "orphans": 0,
        "deleted": 0,
        "failures": 0,
    }


def test_story_2_2_sweeper_map_sends_each_state_to_its_queue_once_consumed(
    sweep: Sweep, monkeypatch: pytest.MonkeyPatch
) -> None:
    # As it will run once every stage story has added its consumer.
    monkeypatch.setattr(sweeper_module, "CONSUMED_QUEUES", frozenset(Stage))
    expected = {
        sweep.seed(1, S.RECEIVED): QueueName.QUALITY,
        sweep.seed(2, S.AWAITING_EXTRACTION): QueueName.EXTRACT,
        sweep.seed(3, S.EXTRACTING, lease="-1 minute"): QueueName.EXTRACT,
        sweep.seed(4, S.AWAITING_VALIDATION): QueueName.VALIDATE,
        sweep.seed(5, S.VALIDATING, lease="-1 minute"): QueueName.VALIDATE,
        sweep.seed(6, S.READY_TO_POST): QueueName.POST,
        sweep.seed(7, S.READY_TO_POST, next_attempt="-1 minute"): QueueName.POST,
        sweep.seed(8, S.POSTING, lease="-1 minute"): QueueName.POST,
    }
    assert sweep.run() == SweepResult("swept", requeued=8)
    assert sweep.sent() == expected
    assert sweep.stuck() == [8]


def test_story_2_2_stages_without_a_consumer_are_never_swept(sweep: Sweep) -> None:
    # Their queues have no reader yet: messages would pile up (and the alert stay on).
    for n, status in enumerate(
        [S.AWAITING_EXTRACTION, S.AWAITING_VALIDATION, S.READY_TO_POST], start=1
    ):
        sweep.seed(n, status)
    assert sweep.run() == SweepResult("swept")
    assert sweep.queue.sent == []
    assert sweep.stuck() == [0]


def test_story_2_2_sweeper_leaves_admin_final_fresh_backoff_and_leased_rows_alone(
    sweep: Sweep, monkeypatch: pytest.MonkeyPatch
) -> None:
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


def test_story_2_2_just_restarted_database_sweeps_nothing(
    pipeline_engine: Engine,
) -> None:
    # The test container started minutes ago: its real pg_postmaster_start_time().
    sweep = Sweep(pipeline_engine, started_at=None)
    sweep.seed(1, S.RECEIVED, changed="5 hours")
    orphan = invoice_id(9)
    sweep.images.put(metadata(orphan))
    sweep.key(1, orphan, timedelta(hours=30))
    assert sweep.run() == SweepResult("swept")
    assert sweep.queue.sent == []
    assert sweep.stuck() == [0]
    # The orphaned upload is kept for a later sweep.
    assert sweep.keys.deleted == [] and sweep.keys.recovered == {}


def test_story_2_2_db_down_sweeper_exits_with_a_code_and_enqueues_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with stopped_database() as engine:
        sweep = Sweep(engine)
        sweep.keys.add(_key(1), invoice_id(1), LONG_AGO)
        with caplog.at_level(logging.DEBUG, logger="invoicing"):
            assert sweep.run() == SweepResult("DB_OFFLINE")
    assert sweep.queue.sent == []
    assert sweep.metrics.emitted == []
    # Keys are kept too: whether they are orphans needs the database.
    assert sweep.keys.deleted == []
    (skipped,) = [
        r for r in caplog.records if r.getMessage().startswith("sweeper.skipped")
    ]
    assert event_fields(skipped) == {"code": "DB_OFFLINE"}


def test_story_2_2_an_orphaned_upload_is_re_enqueued_once_with_its_own_ids(
    sweep: Sweep,
) -> None:
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


def test_story_2_2_an_orphan_whose_row_changed_is_enqueued_but_left_unmarked(
    sweep: Sweep,
) -> None:
    orphan = invoice_id(9)
    sweep.images.put(metadata(orphan))
    sweep.key(1, orphan, timedelta(hours=30))
    sweep.keys.changed.add(_key(1))
    assert sweep.run() == SweepResult("swept", orphans=1)
    # The ETag no longer matches: neither marked nor deleted this sweep.
    assert sweep.keys.recovered == {} and sweep.keys.deleted == []


def test_story_2_2_key_ages_use_the_databases_clock_and_listings_are_capped(
    sweep: Sweep,
) -> None:
    sweep.run()
    ((cutoff,), (limit,)) = (sweep.keys.cutoffs, sweep.keys.limits)
    assert limit == SWEEP_LIMIT
    assert abs(cutoff - (sweep.db_now() - timedelta(hours=1))) < timedelta(minutes=1)


def test_story_2_2_uploads_younger_than_an_hour_or_with_a_row_are_not_orphans(
    sweep: Sweep,
) -> None:
    young = invoice_id(8)
    processed = sweep.seed(1, S.AWAITING_EXTRACTION, changed="1 minute")
    for target in (young, processed):
        sweep.images.put(metadata(target))
    sweep.key(1, young, timedelta(minutes=59))
    sweep.key(2, processed, timedelta(hours=2))
    assert sweep.run() == SweepResult("swept")
    assert sweep.queue.sent == []


def test_story_2_2_an_upload_whose_blob_never_arrived_is_logged_not_enqueued(
    sweep: Sweep, caplog: pytest.LogCaptureFixture
) -> None:
    lost = invoice_id(9)
    sweep.key(1, lost, timedelta(hours=2))
    with caplog.at_level(logging.DEBUG, logger="invoicing"):
        assert sweep.run() == SweepResult("swept")
    assert sweep.queue.sent == []
    assert sweep.keys.deleted == []
    (record,) = [
        r
        for r in caplog.records
        if r.getMessage().startswith("sweeper.upload_without_blob")
    ]
    assert event_fields(record) == {"invoice_id": str(lost), "code": "IMAGE_NOT_FOUND"}


def test_story_2_2_old_keys_are_deleted(sweep: Sweep) -> None:
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


def test_story_2_2_a_key_changed_since_listing_is_not_deleted(sweep: Sweep) -> None:
    done = sweep.seed(1, S.POSTED)
    sweep.key(1, done, timedelta(days=2))
    sweep.keys.changed.add(_key(1))
    assert sweep.run() == SweepResult("swept")
    assert list(sweep.keys.rows) == [_key(1)]


def test_story_2_2_a_failed_delete_is_logged_and_the_sweep_goes_on(
    sweep: Sweep, caplog: pytest.LogCaptureFixture
) -> None:
    first, second = sweep.seed(1, S.POSTED), sweep.seed(2, S.POSTED)
    sweep.key(1, first, timedelta(days=2))
    sweep.key(2, second, timedelta(days=2))
    sweep.keys.fail_delete.add(_key(1))
    with caplog.at_level(logging.DEBUG, logger="invoicing"):
        result = sweep.run()
    assert sweep.keys.deleted == [_key(2)]
    assert (result.deleted, result.failures) == (1, 1)
    (failed,) = [
        r for r in caplog.records if r.getMessage().startswith("sweeper.delete_failed")
    ]
    assert event_fields(failed) == {"invoice_id": str(first), "code": "DELETE_FAILED"}
    assert _done(caplog)["failures"] == 1
    # The key itself is never logged (AD-6).
    for record in caplog.records:
        assert str(_key(1)) not in record.getMessage()


# --- Partial failures: each step, invoice and key on its own -----------------------------


def test_story_2_2_one_failed_enqueue_never_stops_the_sweep(
    sweep: Sweep, caplog: pytest.LogCaptureFixture
) -> None:
    failing, fine = sweep.seed(1, S.RECEIVED), sweep.seed(2, S.RECEIVED)
    sweep.queue.fail_for = frozenset({failing})
    with caplog.at_level(logging.DEBUG, logger="invoicing"):
        result = sweep.run()
    assert sweep.sent() == {fine: QueueName.QUALITY}
    assert (result.requeued, result.failures) == (1, 1)
    assert sweep.stuck() == [1]
    (failed,) = [
        r for r in caplog.records if r.getMessage().startswith("sweeper.enqueue_failed")
    ]
    assert event_fields(failed)["invoice_id"] == str(failing)


def test_story_2_2_an_orphan_whose_enqueue_failed_keeps_its_key_unmarked(
    sweep: Sweep,
) -> None:
    orphan = invoice_id(9)
    sweep.images.put(metadata(orphan))
    sweep.key(1, orphan, timedelta(days=2))
    sweep.queue.fail_for = frozenset({orphan})
    assert sweep.run() == SweepResult("swept", failures=1)
    assert sweep.keys.deleted == [] and sweep.keys.recovered == {}


def test_story_2_2_a_failed_mark_keeps_the_key_for_the_next_sweep(sweep: Sweep) -> None:
    orphan = invoice_id(9)
    sweep.images.put(metadata(orphan))
    sweep.key(1, orphan, timedelta(days=2))
    sweep.keys.fail_mark.add(_key(1))
    assert sweep.run() == SweepResult("swept", orphans=1, failures=1)
    assert sweep.keys.deleted == []


def test_story_2_2_a_failed_key_listing_is_logged_and_the_metric_still_sent(
    sweep: Sweep, caplog: pytest.LogCaptureFixture
) -> None:
    stale = sweep.seed(1, S.RECEIVED)
    sweep.keys.list_error = ServiceUnavailableError()
    with caplog.at_level(logging.DEBUG, logger="invoicing"):
        assert sweep.run() == SweepResult("swept", requeued=1, failures=1)
    assert sweep.sent() == {stale: QueueName.QUALITY}
    assert sweep.stuck() == [1]
    (failed,) = [
        r
        for r in caplog.records
        if r.getMessage().startswith("sweeper.upload_keys_failed")
    ]
    assert event_fields(failed) == {"code": "ServiceUnavailableError"}


def test_story_2_2_a_failed_invoice_scan_still_sends_the_metric(
    sweep: Sweep, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("syntax error at or near")

    monkeypatch.setattr(sweep.invoices, "stale", broken)
    with caplog.at_level(logging.DEBUG, logger="invoicing"):
        assert sweep.run() == SweepResult("swept", failures=1)
    assert sweep.stuck() == [0]
    (failed,) = [
        r for r in caplog.records if r.getMessage().startswith("sweeper.stale_failed")
    ]
    assert event_fields(failed) == {"code": "RuntimeError"}
    assert _done(caplog)["failures"] == 1


def test_story_2_2_a_blob_check_that_fails_keeps_the_orphan_for_later(
    sweep: Sweep,
) -> None:
    sweep.key(1, invoice_id(9), timedelta(days=2))
    sweep.images.error = ServiceUnavailableError()
    assert sweep.run() == SweepResult("swept", failures=1)
    assert sweep.keys.deleted == []


def test_story_2_2_a_database_lost_mid_sweep_leaves_the_keys_alone(
    sweep: Sweep, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def offline(ids: Any) -> Any:
        raise DatabaseOfflineError()

    monkeypatch.setattr(sweep.invoices, "existing", offline)
    stale = sweep.seed(1, S.RECEIVED)
    sweep.key(1, invoice_id(9), timedelta(days=2))
    with caplog.at_level(logging.DEBUG, logger="invoicing"):
        assert sweep.run() == SweepResult("swept", requeued=1, failures=1)
    assert sweep.sent() == {stale: QueueName.QUALITY}
    assert sweep.keys.deleted == []
    assert sweep.stuck() == [1]
    (failed,) = [
        r
        for r in caplog.records
        if r.getMessage().startswith("sweeper.upload_keys_failed")
    ]
    assert event_fields(failed) == {"code": "DB_OFFLINE"}


def test_story_2_2_the_sweeper_logs_ids_and_codes_only(
    sweep: Sweep, caplog: pytest.LogCaptureFixture
) -> None:
    sweep.seed(1, S.RECEIVED)
    orphan = invoice_id(9)
    sweep.images.put(metadata(orphan))
    sweep.key(1, orphan, timedelta(days=2))
    with caplog.at_level(logging.DEBUG, logger="invoicing"):
        sweep.run()
    requeued = [
        event_fields(r)
        for r in caplog.records
        if r.getMessage().startswith("sweeper.requeued")
    ]
    assert {f.get("status", f.get("code")) for f in requeued} == {
        "received",
        "ORPHANED_UPLOAD",
    }
    assert _done(caplog) == {
        "code": "swept",
        "requeued": 1,
        "orphans": 1,
        "deleted": 1,
        "failures": 0,
    }
    for record in caplog.records:
        if record.name.startswith("invoicing"):
            assert DROPPED_FIELDS_KEY not in event_fields(record)
            assert set(event_fields(record)) <= ALLOWED_KEYS
            assert str(_key(1)) not in record.getMessage()
