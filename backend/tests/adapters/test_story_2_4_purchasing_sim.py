"""Story 2.4: the purchasing simulation against PostgreSQL 18, through the reusable
`PurchasingPort` contract (tests/contracts), signed in as each app login that reads
it (AD-11), plus what only the simulation shows."""

import asyncio
from collections.abc import Callable, Coroutine, Iterator
from datetime import date
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine

from conftest import PostgresServer, login_engine
from contracts.purchasing_contract import PurchasingContract
from invoicing.adapters.postgres.engine import postgres_engine
from invoicing.adapters.purchasing_sim.adapter import PurchasingSimAdapter
from invoicing.domain.errors import DatabaseOfflineError
from invoicing.ports.purchasing import PurchasingPort


@pytest.fixture(scope="module", params=["pipeline", "staff_api"])
def reader_engine(
    request: pytest.FixtureRequest,
    postgres_server: PostgresServer,
    purchasing_seeded: str,
) -> Iterator[Engine]:
    engine = login_engine(
        postgres_server, getattr(postgres_server, request.param), purchasing_seeded
    )
    yield engine
    engine.dispose()


class TestStory24PurchasingSimContract(PurchasingContract):
    """The contract, run against the simulation as the pipeline and staff-api logins."""

    @pytest.fixture
    def purchasing(self, reader_engine: Engine) -> PurchasingPort:
        return PurchasingSimAdapter(reader_engine)


@pytest.mark.parametrize(
    "call",
    [
        lambda p: p.get_po("PO-45012"),
        lambda p: p.get_receipts("PO-45012"),
        lambda p: p.get_delivery(UUID(int=1)),
        lambda p: p.list_overdue_pos(date(2026, 10, 1)),
        lambda p: p.get_delivery_dates("PO-45012"),
    ],
)
def test_story_2_4_an_unreachable_database_raises_database_offline(
    call: Callable[[PurchasingSimAdapter], Coroutine[Any, Any, object]],
) -> None:
    # Nothing listens on port 1: connecting fails like a stopped server (AD-7).
    engine = postgres_engine(
        host="127.0.0.1",
        port=1,
        database="invoicing_test",
        user="nobody",
        password=lambda: "unused",
        sslmode="disable",
    )
    try:
        with pytest.raises(DatabaseOfflineError):
            asyncio.run(call(PurchasingSimAdapter(engine)))
    finally:
        engine.dispose()
