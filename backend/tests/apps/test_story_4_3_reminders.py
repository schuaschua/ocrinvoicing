"""Story 4.3: suppliers' weekly reminders (CAP-13, FR13, AD-6, AD-13): the analytics
refresh job's weekly step and supplier-api's `GET /api/reminders`. The table adapter
runs over an in-memory `supplierreminders` (coding-style.md rule 23); purchasing,
`intake` and `analytics` are a real PostgreSQL 18 signed in as the pipeline login. The
clock is injected, never waited on. Synthetic data only (security.md rule 1).

Seeded POs by earliest expected date: PO-45012 1 Sep and PO-45017 25 Sep (Alpha),
PO-45013 5 Sep and PO-45015 15 Sep (Beta).

Two merged tests (the 200-case cap, coding-style.md rule 20 exception): each plan
matrix row is a block of assertions, in order."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable, Sequence
from datetime import UTC, date, datetime
from types import ModuleType
from typing import Any
from uuid import UUID

import azure.functions as func
import pytest
from azure.core.exceptions import HttpResponseError
from sqlalchemy import Engine, text
from sqlalchemy.engine import base as sqlalchemy_base

from apps._pipeline_fakes import stopped_database
from apps.test_story_4_2_overdue import SUPPLIER_BETA, _invoice, _reset_analytics
from apps.test_supplier_link import SUPPLIER_ID, UNKNOWN, VALID, FakeRegistry
from conftest import PostgresServer
from contracts.purchasing_contract import SUPPLIER_ALPHA
from invoicing.adapters.postgres.analytics import PostgresAnalyticsStore
from invoicing.adapters.purchasing_factory import purchasing_port
from invoicing.adapters.table_links import TableSupplierLinkRegistry
from invoicing.adapters.table_reminders import TableReminderStore
from invoicing.apps.pipeline.analytics_refresh import AnalyticsRefresh

SUPPLIER_DELTA = UUID("0192f0c1-7a2b-7c3d-8e4f-0000000000dd")


class FakeTable:
    """`supplierreminders` in memory, with the service's transaction rules: one
    partition and at most 100 operations, all or nothing, and a delete of a missing
    row failing the whole transaction."""

    def __init__(self, rows: set[tuple[str, str]] | None = None) -> None:
        self.rows: set[tuple[str, str]] = set(rows or ())
        self.transactions: list[list[Any]] = []
        self.queries: list[dict[str, Any]] = []
        self.failing = False
        # Raised by the next listings, while set.
        self.listing_error: Exception | None = None
        # Runs once, just before the next transaction applies (a concurrent writer).
        self.before_submit: Callable[[], None] | None = None
        # Runs once, just after the next listing (an invoice arriving mid-run).
        self.after_listing: Callable[[], None] | None = None

    def partition(self, supplier_id: UUID) -> set[str]:
        return {rk for pk, rk in self.rows if pk == str(supplier_id)}

    async def list_entities(
        self, *, select: list[str] | None = None, **kwargs: Any
    ) -> AsyncIterator[dict[str, str]]:
        if self.listing_error is not None:
            raise self.listing_error
        for pk, rk in sorted(self.rows):
            yield {"PartitionKey": pk, "RowKey": rk}
        if self.after_listing is not None:
            hook, self.after_listing = self.after_listing, None
            hook()

    async def query_entities(
        self,
        query_filter: str,
        *,
        parameters: dict[str, Any] | None = None,
        select: list[str] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[dict[str, str]]:
        # The key travels as a $filter parameter, never in a URL path.
        assert query_filter == "PartitionKey eq @pk"
        self.queries.append(dict(parameters or {}))
        if self.failing:
            raise HttpResponseError("busy")
        for pk, rk in sorted(self.rows):
            if pk == (parameters or {})["pk"]:
                yield {"RowKey": rk}

    async def submit_transaction(self, operations: Any, **kwargs: Any) -> Any:
        if self.before_submit is not None:
            hook, self.before_submit = self.before_submit, None
            hook()
        ops = list(operations)
        self.transactions.append(ops)
        assert 0 < len(ops) <= 100
        assert len({entity["PartitionKey"] for _, entity in ops}) == 1
        if self.failing:
            raise HttpResponseError("busy")
        rows = set(self.rows)
        for kind, entity in ops:
            key = (entity["PartitionKey"], entity["RowKey"])
            if kind == "delete":
                if key not in rows:
                    error = HttpResponseError("gone")
                    error.error_code = "ResourceNotFound"  # set by the SDK
                    raise error
                rows.discard(key)
            else:
                assert kind == "upsert"
                rows.add(key)
        self.rows = rows
        return [{} for _ in ops]

    async def close(self) -> None:
        return None


def _at(day: int, hour: int = 1) -> datetime:
    """`hour`:30 UTC on `day` September 2026: an AD-13 run."""
    return datetime(2026, 9, day, hour, 30, tzinfo=UTC)


def _weeks_recorded(engine: Engine) -> list[date]:
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(
                    "SELECT run_date FROM analytics.job_run"
                    " WHERE job = 'supplier_reminders' ORDER BY run_date"
                )
            ).scalars()
        )


def test_story_4_3_weekly_reminders(
    postgres_server: PostgresServer,
    purchasing_seeded: str,
    pipeline_engine: Engine,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The weekly step: written at the first run of the ISO week that gets through
    (a stopped Monday caught up on Tuesday), once a week; each partition replaced
    exactly, stale rows and partitions deleted; a PO invoiced after the Table was
    listed left out, one with only a rejected invoice kept; a failed write, a failed
    listing or any other error leaves the week unrecorded without changing the
    run's result, and the next run, even one whose overdue list was already made,
    writes it."""
    _reset_analytics(postgres_server, purchasing_seeded)
    alpha, beta, delta = str(SUPPLIER_ALPHA), str(SUPPLIER_BETA), str(SUPPLIER_DELTA)
    # Last week's rows: Alpha's PO-45001 is no longer overdue, and Delta has none.
    table = FakeTable({(alpha, "PO-45001"), (delta, "PO-9")})
    reminders = TableReminderStore(table)  # type: ignore[arg-type]  # a structural fake
    store = PostgresAnalyticsStore(pipeline_engine)
    clock = [_at(21)]
    job = AnalyticsRefresh(
        purchasing_port("sim", pipeline_engine),
        store,
        reminders,
        clock=lambda: clock[0],
    )

    with caplog.at_level(logging.INFO):
        # --- Missed Monday 21 Sep: the database is stopped, nothing is written.
        with stopped_database() as stopped:
            offline = AnalyticsRefresh(
                purchasing_port("sim", stopped),
                PostgresAnalyticsStore(stopped),
                reminders,
                clock=lambda: _at(21),
            )
            assert asyncio.run(offline.run()) == "DB_OFFLINE"
        assert table.transactions == []

        # --- Tuesday 22 Sep, first up: the week is written. PO-45013 is invoiced
        # after the Table was listed, just before the partitions' writes, so it is
        # left out; PO-45012's only invoice is rejected, so it stays; stale rows
        # are deleted.
        clock[0] = _at(22)
        _invoice(pipeline_engine, "PO-45012", "rejected")
        table.after_listing = lambda: _invoice(pipeline_engine, "PO-45013", "received")
        assert asyncio.run(job.run()) == "refreshed"
        assert table.rows == {(alpha, "PO-45012"), (beta, "PO-45015")}
        assert _weeks_recorded(pipeline_engine) == [date(2026, 9, 21)]

        # --- Wednesday, same week: no Table writes.
        written = len(table.transactions)
        clock[0] = _at(23)
        assert asyncio.run(job.run()) == "refreshed"
        assert len(table.transactions) == written

        # --- Monday 28 Sep, the write fails: the week is not recorded.
        _invoice(pipeline_engine, "PO-45015", "posted")
        table.failing = True
        clock[0] = _at(28)
        assert asyncio.run(job.run()) == "refreshed"
        assert table.rows == {(alpha, "PO-45012"), (beta, "PO-45015")}
        assert _weeks_recorded(pipeline_engine) == [date(2026, 9, 21)]

        # --- The listing fails, then an unexpected error: the day's result stands,
        # the week is not recorded.
        table.failing = False
        for hour, error in ((2, HttpResponseError("busy")), (3, RuntimeError("x"))):
            table.listing_error = error
            clock[0] = _at(28, hour)
            assert asyncio.run(job.run()) == "already_ran"
            assert _weeks_recorded(pipeline_engine) == [date(2026, 9, 21)]
        table.listing_error = None

        # --- 04:30 the same day: the list was already made, the week still runs.
        # Beta has nothing overdue now, so its partition goes.
        table.failing = False
        clock[0] = _at(28, 4)
        assert asyncio.run(job.run()) == "already_ran"
        assert table.rows == {(alpha, "PO-45012"), (alpha, "PO-45017")}
        assert _weeks_recorded(pipeline_engine) == [
            date(2026, 9, 21),
            date(2026, 9, 28),
        ]

    messages = [r.getMessage() for r in caplog.records]
    failed = [m for m in messages if m.startswith("analytics_refresh.reminders_failed")]
    assert failed == [
        "analytics_refresh.reminders_failed code=SERVICE_UNAVAILABLE",
        "analytics_refresh.reminders_failed code=SERVICE_UNAVAILABLE",
        "analytics_refresh.reminders_failed code=RuntimeError",
    ]
    assert "analytics_refresh.skipped code=DB_OFFLINE" in messages

    # --- The adapter: a key the Table can't hold is skipped, logged by code only;
    # at most 100 operations a transaction; a row the validate stage deletes between
    # the listing and the write is read again, not a failed week.
    async def owed(po_numbers: Sequence[str]) -> set[str]:
        return set(po_numbers)

    caplog.clear()
    many = [f"PO-{n:05d}" for n in range(150)]
    table.transactions.clear()
    with caplog.at_level(logging.INFO):
        assert (
            asyncio.run(reminders.replace_all({SUPPLIER_ALPHA: [*many, "PO/1"]}, owed))
            == 150
        )
    assert table.partition(SUPPLIER_ALPHA) == set(many)
    assert [len(t) for t in table.transactions] == [100, 52]
    assert "code=UNSTORABLE_PO_NUMBER" in caplog.text and "PO/1" not in caplog.text
    table.before_submit = lambda: table.rows.discard((alpha, "PO-00000"))
    assert asyncio.run(reminders.replace_all({SUPPLIER_ALPHA: ["PO-00001"]}, owed)) == 1
    assert table.rows == {(alpha, "PO-00001")}


@pytest.mark.app("supplier_api")
def test_story_4_3_reminders_api(
    app_settings: dict[str, str],
    load_app: Callable[[str], ModuleType],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET api/reminders: wired before the SPA catch-all; the link's supplier's PO
    numbers only, sorted, whatever the request asks; a row the validate stage
    deleted is gone; 401 LINK_NOT_VALID for a bad link, before the table is read;
    503 when the table fails; no PostgreSQL engine is ever made."""
    engines: list[object] = []

    def no_engine(self: object, *args: object, **kwargs: object) -> None:
        engines.append(self)
        raise AssertionError("supplier-api made a database engine")

    monkeypatch.setattr(sqlalchemy_base.Engine, "__init__", no_engine)
    other = str(SUPPLIER_BETA)
    table = FakeTable(
        {
            (str(SUPPLIER_ID), "PO-45019"),
            (str(SUPPLIER_ID), "PO-45012"),
            (other, "PO-45013"),
        }
    )
    store = TableReminderStore(table)  # type: ignore[arg-type]  # a structural fake
    registry = FakeRegistry()
    monkeypatch.setattr(
        TableSupplierLinkRegistry,
        "with_managed_identity",
        classmethod(lambda cls, account, client_id: registry),
    )
    monkeypatch.setattr(
        TableReminderStore,
        "with_managed_identity",
        classmethod(lambda cls, account, client_id: store),
    )
    module = load_app("supplier_api")
    functions = list(module.app.get_functions())
    names = [fn.get_function_name() for fn in functions]
    assert names[-1] == "web_app"
    endpoint = functions[names.index("supplier_reminders")]
    (trigger,) = [
        b.get_dict_repr()
        for b in endpoint.get_bindings()
        if b.get_dict_repr()["type"] == "httpTrigger"
    ]
    assert trigger["route"] == "api/reminders"
    assert [getattr(m, "value", m) for m in trigger["methods"]] == ["GET"]  # type: ignore[attr-defined]  # a list here
    assert getattr(trigger["authLevel"], "value", None) == "anonymous"

    def get(token: str | None) -> tuple[int, dict[str, Any]]:
        headers = {} if token is None else {"X-Upload-Token": token}
        # A supplier id in the URL is ignored: the link alone decides.
        request = func.HttpRequest(
            method="GET",
            url=f"/api/reminders?supplier_id={other}",
            headers=headers,
            body=b"",
            params={"supplier_id": other},
        )
        response = asyncio.run(endpoint.get_user_function()(request))
        return response.status_code, json.loads(response.get_body())

    # --- Banner rows: this supplier's only, sorted.
    assert get(VALID) == (200, {"po_numbers": ["PO-45012", "PO-45019"]})
    assert table.queries == [{"pk": str(SUPPLIER_ID)}]

    # --- Cleanup: validate deleted PO-45012's row (Story 2.6).
    asyncio.run(store.delete(SUPPLIER_ID, "PO-45012"))
    assert get(VALID) == (200, {"po_numbers": ["PO-45019"]})

    # --- Bad or missing link: the same 401 as /api/link, the table never read.
    table.queries.clear()
    for token in (UNKNOWN, None):
        status, body = get(token)
        assert (status, body["code"]) == (401, "LINK_NOT_VALID")
    assert table.queries == []

    # --- Table outage: 503.
    table.failing = True
    status, body = get(VALID)
    assert (status, body["code"]) == (503, "SERVICE_UNAVAILABLE")

    # --- Never PostgreSQL.
    assert engines == []
