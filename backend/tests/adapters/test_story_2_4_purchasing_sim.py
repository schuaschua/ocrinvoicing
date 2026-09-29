"""Story 2.4: the purchasing simulation against PostgreSQL 18, through the reusable
`PurchasingPort` contract (tests/contracts), signed in as each app login that reads
it (AD-11), plus what only the simulation shows."""

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine

from conftest import PostgresServer, login_engine
from contracts.purchasing_contract import PurchasingContract
from invoicing.adapters.purchasing_sim.adapter import PurchasingSimAdapter
from invoicing.ports.purchasing import PurchasingPort


@pytest.fixture(scope="module", params=["pipeline"])
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
