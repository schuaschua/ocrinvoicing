"""Story 2.4: the operator seed command loads the synthetic purchasing data through
the PG* variables, is idempotent, and refuses an inconsistent file."""

import secrets
from typing import Any

import pytest
from sqlalchemy import create_engine, text

from conftest import PostgresServer
from invoicing.adapters.purchasing_sim.seed import DEFAULT_SEED_FILE
from invoicing.tools.seed_purchasing import main

TABLES = (
    "material",
    "purchase_order",
    "po_line",
    "delivery",
    "goods_receipt",
    "goods_receipt_line",
)


def _counts(server: PostgresServer, database: str) -> dict[str, int]:
    engine = create_engine(server.url(server.deployer, database))
    try:
        with engine.connect() as connection:
            return {
                table: connection.execute(
                    text(f"SELECT count(*) FROM sim_purchasing.{table}")  # noqa: S608  # fixed names
                ).scalar_one()
                for table in TABLES
            }
    finally:
        engine.dispose()


def _snapshot(server: PostgresServer, database: str) -> list[Any]:
    engine = create_engine(server.url(server.deployer, database))
    try:
        with engine.connect() as connection:
            return [
                sorted(
                    tuple(row)
                    for row in connection.execute(
                        text(f"SELECT * FROM sim_purchasing.{table}")  # noqa: S608  # fixed names
                    )
                )
                for table in TABLES
            ]
    finally:
        engine.dispose()


@pytest.fixture
def seed_database(postgres_server: PostgresServer) -> str:
    """A fresh, migrated, empty database, so the counts are the seed's alone."""
    database = f"invoicing_seed_{secrets.token_hex(4)}"
    postgres_server.create_database(database)
    result = postgres_server.alembic(database, "upgrade", "head")
    assert result.returncode == 0, result.stdout + result.stderr
    return database


def test_story_2_4_seed_twice_gives_the_same_rows(
    postgres_server: PostgresServer,
    seed_database: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The command connects through the PG* variables only, as ci/migrate.sh does.
    for name, value in postgres_server.libpq_env(
        postgres_server.deployer, seed_database
    ).items():
        monkeypatch.setenv(name, value)
    assert main([]) == 0
    first = _counts(postgres_server, seed_database)
    assert first == {
        "material": 3,
        "purchase_order": 6,
        "po_line": 8,
        "delivery": 5,
        "goods_receipt": 4,
        "goods_receipt_line": 4,
    }
    output = capsys.readouterr()
    assert "po_line: 8 row(s) upserted" in output.out
    assert "warning" not in output.err
    before = _snapshot(postgres_server, seed_database)
    assert main(["--file", str(DEFAULT_SEED_FILE)]) == 0
    assert _counts(postgres_server, seed_database) == first
    assert _snapshot(postgres_server, seed_database) == before
