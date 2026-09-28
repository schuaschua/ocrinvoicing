"""Story 2.2: the repository's recovery reads and writes against a real PostgreSQL 18,
signed in as the pipeline login. The AD-3 claim and lease reclaim, the poison guard's
lease check, the sweeper's stale scan with its `pg_postmaster_start_time()` guard,
and "database unreachable" detection (AD-7)."""

import asyncio
import logging
import socket
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from azure.core.exceptions import ClientAuthenticationError
from sqlalchemy import Engine, select, text, update
from sqlalchemy.exc import ProgrammingError

from invoicing.adapters.logging import event_fields
from invoicing.adapters.postgres.engine import (
    POOL_SIZE,
    DatabaseBusyError,
    open_connection,
    postgres_engine,
)
from invoicing.adapters.postgres.invoices import (
    EXISTING_CHUNK,
    PostgresInvoiceRepository,
)
from invoicing.adapters.postgres.schema import invoice, status_history
from invoicing.domain.errors import DatabaseOfflineError
from invoicing.domain.reasons import ReasonCode
from invoicing.domain.status import InvoiceStatus, Stage
from invoicing.domain.sweep import CONSUMED_QUEUES, STALE_AFTER, SWEEP_LIMIT
from invoicing.domain.transitions import CLAIM_LEASE, plan_claim, route_to_admin
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


# --- AD-3 claim and lease reclaim (matrix "Lease reclaim") ---------------------------------


def test_story_2_2_a_claim_moves_the_input_to_its_claim_state_with_a_lease(
    pipeline_engine: Engine,
) -> None:
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


def test_story_2_2_an_expired_lease_is_reclaimed_with_a_new_lease(
    pipeline_engine: Engine,
) -> None:
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


def test_story_2_2_a_live_lease_is_never_taken(pipeline_engine: Engine) -> None:
    _seed(pipeline_engine, INVOICE_ID, S.VALIDATING, lease="5 minutes")
    lease = _row(pipeline_engine)["claimed_until"]
    repo = PostgresInvoiceRepository(pipeline_engine)
    assert not asyncio.run(repo.claim(plan_claim(INVOICE_ID, Stage.VALIDATE, "t")))
    assert _row(pipeline_engine)["claimed_until"] == lease


@pytest.mark.parametrize(
    ("status", "next_attempt", "claimed"),
    [
        (S.READY_TO_POST, None, True),
        (S.READY_TO_POST, "-1 minute", True),
        (S.READY_TO_POST, "5 minutes", False),
        (S.POSTED, None, False),
    ],
)
def test_story_2_2_the_post_claim_waits_for_next_attempt_at(
    pipeline_engine: Engine, status: S, next_attempt: str | None, claimed: bool
) -> None:
    _seed(pipeline_engine, INVOICE_ID, status, next_attempt=next_attempt)
    repo = PostgresInvoiceRepository(pipeline_engine)
    assert asyncio.run(repo.claim(plan_claim(INVOICE_ID, Stage.POST, "t"))) is claimed
    assert _row(pipeline_engine)["status"] == ("posting" if claimed else status.value)


def test_story_2_2_a_claim_on_a_missing_invoice_changes_nothing(
    pipeline_engine: Engine,
) -> None:
    repo = PostgresInvoiceRepository(pipeline_engine)
    assert not asyncio.run(repo.claim(plan_claim(INVOICE_ID, Stage.EXTRACT, "t")))
    assert _history(pipeline_engine) == []


# --- The poison guard's reads and lease check ---------------------------------------------


def test_story_2_2_state_reads_status_and_lease_on_the_databases_clock(
    pipeline_engine: Engine,
) -> None:
    repo = PostgresInvoiceRepository(pipeline_engine)
    assert asyncio.run(repo.state(INVOICE_ID)) is None
    _seed(pipeline_engine, INVOICE_ID, S.POSTING, lease="3 minutes")
    state = asyncio.run(repo.state(INVOICE_ID))
    assert state is not None and state.status is S.POSTING
    assert state.claimed_until == _row(pipeline_engine)["claimed_until"]
    assert state.now < state.claimed_until <= state.now + timedelta(minutes=3)
    assert state.next_attempt_at is None
    _seed(pipeline_engine, _invoice_id(2), S.READY_TO_POST, next_attempt="5 minutes")
    waiting = asyncio.run(repo.state(_invoice_id(2)))
    assert waiting is not None and waiting.next_attempt_at is not None
    assert waiting.next_attempt_at > waiting.now


@pytest.mark.parametrize(
    ("lease", "routed"), [("-1 minute", True), ("5 minutes", False)]
)
def test_story_2_2_routing_from_a_claim_needs_an_expired_lease(
    pipeline_engine: Engine, lease: str, routed: bool
) -> None:
    _seed(pipeline_engine, INVOICE_ID, S.EXTRACTING, lease=lease)
    routing = route_to_admin(
        INVOICE_ID,
        [ReasonCode.PROCESSING_FAILED],
        S.EXTRACTING,
        actor="pipeline:poison",
        require_expired_lease=True,
    )
    repo = PostgresInvoiceRepository(pipeline_engine)
    assert asyncio.run(repo.route_to_admin(routing)) is routed
    assert _row(pipeline_engine)["status"] == (
        "in_admin_queue" if routed else "extracting"
    )


def test_story_2_2_existing_names_the_invoices_that_have_a_row(
    pipeline_engine: Engine,
) -> None:
    _seed(pipeline_engine, _invoice_id(1), S.RECEIVED)
    repo = PostgresInvoiceRepository(pipeline_engine)
    assert asyncio.run(repo.existing([_invoice_id(1), _invoice_id(2)])) == {
        _invoice_id(1)
    }
    assert asyncio.run(repo.existing([])) == frozenset()


# --- The sweeper's scan (AD-2) --------------------------------------------------------------


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


def test_story_2_2_the_stale_scan_applies_the_domain_map_in_sql(
    pipeline_engine: Engine,
) -> None:
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


def test_story_2_2_the_stale_scan_reads_only_consumed_stages(
    pipeline_engine: Engine,
) -> None:
    _seed(pipeline_engine, _invoice_id(1), S.RECEIVED, changed="2 hours")
    _seed(pipeline_engine, _invoice_id(2), S.AWAITING_EXTRACTION, changed="2 hours")
    _seed(pipeline_engine, _invoice_id(3), S.READY_TO_POST, changed="2 hours")
    scan = _stale(_long_running(pipeline_engine))
    assert [(i.invoice_id, i.status) for i in scan.invoices] == [
        (_invoice_id(1), S.RECEIVED)
    ]


def test_story_2_2_the_stale_scan_is_capped_oldest_first(
    pipeline_engine: Engine,
) -> None:
    for n, age in [(1, "2 hours"), (2, "5 hours"), (3, "3 hours")]:
        _seed(pipeline_engine, _invoice_id(n), S.RECEIVED, changed=age)
    scan = _stale(_long_running(pipeline_engine), limit=2)
    assert [i.invoice_id for i in scan.invoices] == [_invoice_id(2), _invoice_id(3)]


def test_story_2_2_a_database_started_within_the_hour_sweeps_nothing(
    pipeline_engine: Engine,
) -> None:
    # The test container started minutes ago: pg_postmaster_start_time() itself.
    _seed(pipeline_engine, INVOICE_ID, S.RECEIVED, changed="5 hours")
    scan = _stale(PostgresInvoiceRepository(pipeline_engine))
    assert (scan.settled, scan.invoices) == (False, ())
    # The same through the seam, just inside the hour.
    recent = _db_now(pipeline_engine) - timedelta(minutes=59)
    scan = _stale(
        PostgresInvoiceRepository(pipeline_engine, database_started_at=recent)
    )
    assert (scan.settled, scan.invoices) == (False, ())


def test_story_2_2_existing_is_chunked_for_long_id_lists(
    pipeline_engine: Engine,
) -> None:
    _seed(pipeline_engine, _invoice_id(1), S.RECEIVED)
    _seed(pipeline_engine, _invoice_id(1200), S.RECEIVED)
    ids = [_invoice_id(n) for n in range(1, EXISTING_CHUNK * 2 + 300)]
    repo = PostgresInvoiceRepository(pipeline_engine)
    assert asyncio.run(repo.existing(ids)) == {_invoice_id(1), _invoice_id(1200)}


# --- Database unreachable (AD-7, Design Notes) ---------------------------------------------


def _closed_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
    return port


@pytest.fixture
def stopped_engine() -> Iterator[Engine]:
    """An engine for a server that is not running (nothing listens on the port)."""
    engine = postgres_engine(
        host="127.0.0.1",
        port=_closed_port(),
        database="invoicing_test",
        user="pipeline-login",
        password=lambda: "unused",
        sslmode="disable",
    )
    yield engine
    engine.dispose()


def _every_method(repo: PostgresInvoiceRepository) -> list[Any]:
    routing = route_to_admin(
        INVOICE_ID, [ReasonCode.PROCESSING_FAILED], S.RECEIVED, actor="t"
    )
    return [
        repo.status(INVOICE_ID),
        repo.state(INVOICE_ID),
        repo.insert_if_absent(_new(INVOICE_ID)),
        repo.route_to_admin(routing),
        repo.claim(plan_claim(INVOICE_ID, Stage.EXTRACT, "t")),
        repo.stale(STALE_AFTER, stages=CONSUMED_QUEUES, limit=SWEEP_LIMIT),
        repo.existing([INVOICE_ID]),
    ]


def test_story_2_2_a_stopped_server_is_database_offline_and_logged_by_code(
    stopped_engine: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    repo = PostgresInvoiceRepository(stopped_engine)
    with caplog.at_level(logging.DEBUG, logger="invoicing"):
        for call in _every_method(repo):
            with pytest.raises(DatabaseOfflineError) as raised:
                asyncio.run(call)
            assert raised.value.__cause__ is None and raised.value.__suppress_context__
    records = [
        r for r in caplog.records if r.getMessage().startswith("postgres.unreachable")
    ]
    assert len(records) == 7
    assert {event_fields(r)["code"] for r in records} == {"CONNECT_FAILED"}
    for record in caplog.records:
        assert "127.0.0.1" not in record.getMessage()


def test_story_2_2_a_failed_entra_token_is_database_offline(
    postgres_server: Any, intake_database: str, caplog: pytest.LogCaptureFixture
) -> None:
    def no_token() -> str:
        raise ClientAuthenticationError("identity endpoint unavailable")

    engine = postgres_engine(
        host=postgres_server.host,
        port=postgres_server.port,
        database=intake_database,
        user=postgres_server.pipeline,
        password=no_token,
        sslmode="disable",
    )
    try:
        with (
            caplog.at_level(logging.DEBUG, logger="invoicing"),
            pytest.raises(DatabaseOfflineError),
        ):
            asyncio.run(PostgresInvoiceRepository(engine).status(INVOICE_ID))
    finally:
        engine.dispose()
    (record,) = [
        r for r in caplog.records if r.getMessage().startswith("postgres.unreachable")
    ]
    assert event_fields(record)["code"] == "TOKEN_FAILED"


def test_story_2_2_a_failing_query_is_not_database_offline(
    postgres_server: Any, intake_database: str
) -> None:
    # Connected, but the login has no grant on `intake`: a query error, retried by
    # the host like any failure, not an AD-7 wait.
    engine = postgres_engine(
        host=postgres_server.host,
        port=postgres_server.port,
        database=intake_database,
        user=postgres_server.outsider,
        password=lambda: str(postgres_server.password),
        sslmode="disable",
    )
    try:
        with pytest.raises(ProgrammingError):
            asyncio.run(PostgresInvoiceRepository(engine).status(INVOICE_ID))
    finally:
        engine.dispose()


# --- The connection pool (one connection per pipeline function) ---------------------------


def test_story_2_2_the_pool_has_a_connection_per_pipeline_function() -> None:
    assert POOL_SIZE == 6
    engine = postgres_engine(
        host="babaloo-sea-lng-psql-21.postgres.database.azure.com",
        database="invoicing_dev",
        user="babaloo-sea-lng-id-03",
        password=lambda: "unused",
    )
    assert engine.pool.size() == POOL_SIZE  # type: ignore[attr-defined]  # QueuePool


def test_story_2_2_a_saturated_pool_is_busy_not_offline(
    postgres_server: Any, intake_database: str, caplog: pytest.LogCaptureFixture
) -> None:
    engine = postgres_engine(
        host=postgres_server.host,
        port=postgres_server.port,
        database=intake_database,
        user=postgres_server.pipeline,
        password=lambda: str(postgres_server.password),
        sslmode="disable",
        pool_size=1,
        pool_timeout=0.1,
    )
    try:
        with (
            open_connection(engine),
            caplog.at_level(logging.DEBUG, logger="invoicing"),
        ):
            # The only connection is in use: retried by the host, never waited out.
            with pytest.raises(DatabaseBusyError) as raised:
                asyncio.run(PostgresInvoiceRepository(engine).status(INVOICE_ID))
            assert not isinstance(raised.value, DatabaseOfflineError)
            assert raised.value.__cause__ is None and raised.value.__suppress_context__
    finally:
        engine.dispose()
    (record,) = [
        r for r in caplog.records if r.getMessage().startswith("postgres.pool_timeout")
    ]
    assert event_fields(record) == {"code": "POOL_TIMEOUT"}
