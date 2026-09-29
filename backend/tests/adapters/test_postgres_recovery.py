"""Story 2.2: the repository's recovery reads and writes against a real PostgreSQL 18,
signed in as the pipeline login. The AD-3 claim and lease reclaim, the poison guard's
lease check, the sweeper's stale scan with its `pg_postmaster_start_time()` guard,
and "database unreachable" detection (AD-7)."""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, select, text, update

from invoicing.adapters.postgres.invoices import (
    PostgresInvoiceRepository,
)
from invoicing.adapters.postgres.schema import invoice, status_history
from invoicing.domain.status import InvoiceStatus, Stage
from invoicing.domain.sweep import CONSUMED_QUEUES, STALE_AFTER, SWEEP_LIMIT
from invoicing.domain.transitions import CLAIM_LEASE, plan_claim
from invoicing.domain.upload import UploadContentType
from invoicing.ports.intake import DeviceCheck, IntakeBlobMetadata, IntakeSource
from invoicing.ports.invoices import NewInvoice

S = InvoiceStatus
SUPPLIER_ID = UUID("0192f0c1-0000-7000-8000-000000000001")
CORRELATION_ID = UUID("0192f0c1-7a2b-7c3d-8e4f-0000000000c0")
INVOICE_ID = UUID("0192f0c1-7a2b-7c3d-8e4f-000000000001")


def _invoice_id(n: int) -> UUID:
    return UUID(f"0192f0c1-7a2b-7c3d-8e4f-{n:012x}")


def _new(invoice_id: UUID) -> NewInvoice:
    metadata = IntakeBlobMetadata(
        invoice_id=invoice_id,
        source=IntakeSource.LINK,
        supplier_id=SUPPLIER_ID,
        content_type=UploadContentType.JPEG,
        uploaded_at=datetime(2026, 9, 29, 1, 30, tzinfo=UTC),
        device_check=DeviceCheck.PASSED,
    )
    return NewInvoice(metadata, CORRELATION_ID, "pipeline:quality")


def _seed(
    engine: Engine,
    invoice_id: UUID,
    status: S,
    *,
    changed: str = "0 minutes",
    lease: str | None = None,
    next_attempt: str | None = None,
) -> None:
    """An invoice in `status`, its status changed `changed` ago, with a lease and a
    next attempt relative to the database's now() (interval text, e.g. `-5 minutes`)."""
    asyncio.run(PostgresInvoiceRepository(engine).insert_if_absent(_new(invoice_id)))
    with engine.begin() as connection:
        connection.execute(
            update(invoice)
            .where(invoice.c.id == invoice_id)
            .values(
                status=status.value,
                status_changed_at=text("now() - CAST(:changed AS interval)").bindparams(
                    changed=changed
                ),
                claimed_until=None
                if lease is None
                else text("now() + CAST(:lease AS interval)").bindparams(lease=lease),
                next_attempt_at=None
                if next_attempt is None
                else text("now() + CAST(:next AS interval)").bindparams(
                    next=next_attempt
                ),
            )
        )


def _row(engine: Engine, invoice_id: UUID = INVOICE_ID) -> Any:
    with engine.connect() as connection:
        return (
            connection.execute(select(invoice).where(invoice.c.id == invoice_id))
            .mappings()
            .one()
        )


def _history(engine: Engine) -> list[tuple[str | None, str, str]]:
    with engine.connect() as connection:
        rows = connection.execute(
            select(
                status_history.c.from_status,
                status_history.c.to_status,
                status_history.c.actor,
            ).order_by(status_history.c.id)
        )
        return [tuple(r) for r in rows]


def _db_now(engine: Engine) -> datetime:
    with engine.connect() as connection:
        value: datetime = connection.execute(text("SELECT now()")).scalar_one()
        return value


# --- Helpers for the sweeper's scan (AD-2) ----------------------------------------------


ALL_STAGES = frozenset(Stage)


def _stale(
    repo: PostgresInvoiceRepository,
    stages: frozenset[Stage] = CONSUMED_QUEUES,
    limit: int = SWEEP_LIMIT,
) -> Any:
    return asyncio.run(repo.stale(STALE_AFTER, stages=stages, limit=limit))


def _long_running(engine: Engine) -> PostgresInvoiceRepository:
    started = _db_now(engine) - timedelta(hours=2)
    return PostgresInvoiceRepository(engine, database_started_at=started)


# --- AD-3 claim and lease reclaim (matrix "Lease reclaim"), then the sweeper's scan ---


def test_story_2_2_claims_leases_and_the_stale_scan_in_postgres(
    pipeline_engine: Engine, reset_intake: Callable[[], None]
) -> None:
    # --- Story 2.2: a claim moves the input to its claim state with a lease
    _seed(pipeline_engine, INVOICE_ID, S.AWAITING_EXTRACTION)
    repo = PostgresInvoiceRepository(pipeline_engine)
    before = _db_now(pipeline_engine)
    assert asyncio.run(
        repo.claim(plan_claim(INVOICE_ID, Stage.EXTRACT, "pipeline:extract"))
    )
    row = _row(pipeline_engine)
    assert row["status"] == "extracting"
    assert (
        before + CLAIM_LEASE
        <= row["claimed_until"]
        <= _db_now(pipeline_engine) + CLAIM_LEASE
    )
    assert _history(pipeline_engine)[-1] == (
        "awaiting_extraction",
        "extracting",
        "pipeline:extract",
    )
    # A duplicate message finds a live lease: zero rows, acknowledge (AD-3).
    assert not asyncio.run(repo.claim(plan_claim(INVOICE_ID, Stage.EXTRACT, "x")))
    assert _row(pipeline_engine)["claimed_until"] == row["claimed_until"]

    # --- Story 2.2: an expired lease is reclaimed with a new lease
    reset_intake()
    _seed(
        pipeline_engine,
        INVOICE_ID,
        S.EXTRACTING,
        changed="30 minutes",
        lease="-1 minute",
    )
    history_before = _history(pipeline_engine)
    changed_before = _row(pipeline_engine)["status_changed_at"]
    repo = PostgresInvoiceRepository(pipeline_engine)
    assert asyncio.run(
        repo.claim(plan_claim(INVOICE_ID, Stage.EXTRACT, "pipeline:extract"))
    )
    row = _row(pipeline_engine)
    assert row["status"] == "extracting"
    assert row["claimed_until"] > _db_now(pipeline_engine) + timedelta(minutes=9)
    # The status did not change: no history row, and its age is kept.
    assert _history(pipeline_engine) == history_before
    assert row["status_changed_at"] == changed_before

    # --- Story 2.2: a live lease is never taken
    reset_intake()
    _seed(pipeline_engine, INVOICE_ID, S.VALIDATING, lease="5 minutes")
    lease = _row(pipeline_engine)["claimed_until"]
    repo = PostgresInvoiceRepository(pipeline_engine)
    assert not asyncio.run(repo.claim(plan_claim(INVOICE_ID, Stage.VALIDATE, "t")))
    assert _row(pipeline_engine)["claimed_until"] == lease

    # --- Story 2.2: the stale scan applies the domain map in sql
    reset_intake()
    swept = {
        _invoice_id(1): S.RECEIVED,
        _invoice_id(2): S.AWAITING_EXTRACTION,
        _invoice_id(3): S.EXTRACTING,
        _invoice_id(4): S.READY_TO_POST,
        _invoice_id(5): S.POSTING,
    }
    _seed(pipeline_engine, _invoice_id(1), S.RECEIVED, changed="61 minutes")
    _seed(pipeline_engine, _invoice_id(2), S.AWAITING_EXTRACTION, changed="2 hours")
    _seed(
        pipeline_engine,
        _invoice_id(3),
        S.EXTRACTING,
        changed="2 hours",
        lease="-1 minute",
    )
    _seed(
        pipeline_engine,
        _invoice_id(4),
        S.READY_TO_POST,
        changed="2 hours",
        next_attempt="-1 minute",
    )
    _seed(pipeline_engine, _invoice_id(5), S.POSTING, changed="2 hours")
    # Left in the database: live leases, a backoff still running, admin and final
    # statuses, and a status changed within the hour.
    _seed(
        pipeline_engine,
        _invoice_id(6),
        S.VALIDATING,
        changed="2 hours",
        lease="5 minutes",
    )
    _seed(
        pipeline_engine,
        _invoice_id(7),
        S.READY_TO_POST,
        changed="2 hours",
        next_attempt="5 minutes",
    )
    for n, status in enumerate([S.IN_ADMIN_QUEUE, S.POSTED, S.REJECTED], start=10):
        _seed(pipeline_engine, _invoice_id(n), status, changed="3 hours")
    _seed(pipeline_engine, _invoice_id(20), S.RECEIVED, changed="59 minutes")
    scan = _stale(_long_running(pipeline_engine), ALL_STAGES)
    assert scan.settled
    assert {(i.invoice_id, i.status) for i in scan.invoices} == set(swept.items())
    assert all(i.correlation_id == CORRELATION_ID for i in scan.invoices)
    # created_at comes back: the re-enqueued message's first_enqueued_at.
    (received,) = [i for i in scan.invoices if i.status is S.RECEIVED]
    assert received.created_at == _row(pipeline_engine, _invoice_id(1))["created_at"]
