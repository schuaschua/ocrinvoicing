"""Story 2.4: migration 0002_sim_purchasing against PostgreSQL 18: its tables match
the simulation adapter's, it goes up and down on its own, and the app logins may only
read it (AD-11)."""

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import (
    CheckConstraint,
    Engine,
    UniqueConstraint,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import ProgrammingError

from conftest import PostgresServer
from invoicing.adapters.purchasing_sim.schema import SCHEMA
from invoicing.adapters.purchasing_sim.schema import metadata as sim_metadata

TABLES = {
    "material",
    "purchase_order",
    "po_line",
    "delivery",
    "goods_receipt",
    "goods_receipt_line",
}


def _sql_type(sql_type: Any) -> str:
    return str(sql_type.compile(dialect=postgresql.dialect()))


@pytest.fixture
def owner(postgres_server: PostgresServer, intake_database: str) -> Iterator[Engine]:
    engine = create_engine(
        postgres_server.url(postgres_server.deployer, intake_database)
    )
    yield engine
    engine.dispose()


def test_story_2_4_up_and_down_one_revision(postgres_server: PostgresServer) -> None:
    database = "invoicing_sim_purchasing"
    postgres_server.create_database(database)
    engine = create_engine(postgres_server.url(postgres_server.deployer, database))
    try:
        for args, present in (
            (["upgrade", "head"], True),
            (["downgrade", "0001_intake"], False),
            (["upgrade", "head"], True),
        ):
            result = postgres_server.alembic(database, *args)
            assert result.returncode == 0, result.stdout + result.stderr
            with engine.connect() as connection:
                schemas = inspect(connection).get_schema_names()
                assert (SCHEMA in schemas) is present
                # Downgrading 0002 leaves 0001's intake schema alone.
                assert "intake" in schemas
                acl = connection.execute(
                    text(
                        "SELECT count(*) FROM pg_default_acl d"
                        " JOIN pg_namespace n ON n.oid = d.defaclnamespace"
                        " WHERE n.nspname = :schema"
                    ),
                    {"schema": SCHEMA},
                ).scalar()
                # One default-ACL row for the schema (both logins in it), gone after downgrade.
                assert acl == (1 if present else 0)
        current = postgres_server.alembic(database, "current")
        assert "0002_sim_purchasing (head)" in current.stdout
    finally:
        engine.dispose()


def test_story_2_4_the_schema_matches_the_adapters_tables(owner: Engine) -> None:
    with owner.connect() as connection:
        inspector = inspect(connection)
        assert set(inspector.get_table_names(schema=SCHEMA)) == TABLES
        for table in sim_metadata.sorted_tables:
            columns = {c["name"]: c for c in inspector.get_columns(table.name, SCHEMA)}
            assert set(columns) == {c.name for c in table.columns}, table.name
            for column in table.columns:
                where = f"{table.name}.{column.name}"
                assert columns[column.name]["nullable"] == column.nullable, where
                assert _sql_type(columns[column.name]["type"]) == _sql_type(
                    column.type
                ), where
            reflected_keys = {
                (
                    tuple(fk["constrained_columns"]),
                    fk["referred_schema"],
                    fk["referred_table"],
                    tuple(fk["referred_columns"]),
                )
                for fk in inspector.get_foreign_keys(table.name, SCHEMA)
            }
            declared_keys = {
                (
                    (fk.parent.name,),
                    fk.column.table.schema,
                    fk.column.table.name,
                    (fk.column.name,),
                )
                for fk in table.foreign_keys
            }
            assert reflected_keys == declared_keys, table.name
            # The seed's upserts rely on the unique keys (ON CONFLICT), so they and
            # the checks must be declared alike in schema.py and the migration.
            declared_unique = {
                (c.name, tuple(col.name for col in c.columns))
                for c in table.constraints
                if isinstance(c, UniqueConstraint)
            }
            reflected_unique = {
                (u["name"], tuple(u["column_names"]))
                for u in inspector.get_unique_constraints(table.name, SCHEMA)
            }
            assert reflected_unique == declared_unique, table.name
            declared_checks = {
                c.name for c in table.constraints if isinstance(c, CheckConstraint)
            }
            reflected_checks = {
                c["name"] for c in inspector.get_check_constraints(table.name, SCHEMA)
            }
            assert reflected_checks == declared_checks, table.name
            assert inspector.get_pk_constraint(table.name, SCHEMA)[
                "constrained_columns"
            ] == [c.name for c in table.primary_key.columns], table.name
        # AD-10 money and quantity types; no key into `master`.
        po_line = {c["name"]: c for c in inspector.get_columns("po_line", SCHEMA)}
        assert _sql_type(po_line["unit_price"]["type"]) == "NUMERIC(18, 2)"
        assert _sql_type(po_line["quantity"]["type"]) == "NUMERIC(18, 3)"
        assert _sql_type(po_line["expected_date"]["type"]) == "DATE"
        for table in TABLES:
            for fk in inspector.get_foreign_keys(table, SCHEMA):
                assert fk["referred_schema"] == SCHEMA


@pytest.mark.parametrize("login", ["pipeline", "staff_api"])
def test_story_2_4_app_logins_can_read_every_table(
    postgres_server: PostgresServer, intake_database: str, login: str
) -> None:
    engine = create_engine(
        postgres_server.url(getattr(postgres_server, login), intake_database)
    )
    try:
        with engine.connect() as connection:
            for table in TABLES:
                connection.execute(text(f"SELECT count(*) FROM {SCHEMA}.{table}"))  # noqa: S608  # fixed names
    finally:
        engine.dispose()


REFUSED = [
    (
        "INSERT INTO sim_purchasing.purchase_order VALUES"
        " ('PO-X', '01a0c450-6c00-7b7b-8aa9-4ccade9f5526', '2026-09-01')"
    ),
    (
        "INSERT INTO sim_purchasing.material VALUES"
        " ('01a0c450-0000-7000-8000-000000000001', 'X', 'x')"
    ),
    "UPDATE sim_purchasing.po_line SET unit_price = 0",
    "UPDATE sim_purchasing.goods_receipt SET received_date = '2026-01-01'",
    "DELETE FROM sim_purchasing.goods_receipt_line",
    "DELETE FROM sim_purchasing.delivery",
    "TRUNCATE sim_purchasing.material CASCADE",
    "CREATE TABLE sim_purchasing.sneaky (id int)",
]


@pytest.mark.parametrize("statement", REFUSED)
@pytest.mark.parametrize("login", ["pipeline", "staff_api"])
def test_story_2_4_app_logins_cannot_write(
    postgres_server: PostgresServer, intake_database: str, login: str, statement: str
) -> None:
    engine = create_engine(
        postgres_server.url(getattr(postgres_server, login), intake_database)
    )
    try:
        with (
            engine.connect() as connection,
            pytest.raises(ProgrammingError, match="permission denied"),
        ):
            connection.execute(text(statement))
    finally:
        engine.dispose()


def test_story_2_4_a_table_added_later_is_readable_only(
    postgres_server: PostgresServer, intake_database: str, owner: Engine
) -> None:
    with owner.begin() as connection:
        connection.execute(text(f"CREATE TABLE {SCHEMA}.later_table (id int)"))
    engine = create_engine(
        postgres_server.url(postgres_server.pipeline, intake_database)
    )
    try:
        with engine.connect() as connection:
            connection.execute(text(f"SELECT * FROM {SCHEMA}.later_table"))  # noqa: S608  # fixed name
        with (
            engine.connect() as connection,
            pytest.raises(ProgrammingError, match="permission denied"),
        ):
            connection.execute(text(f"INSERT INTO {SCHEMA}.later_table VALUES (1)"))  # noqa: S608  # fixed name
    finally:
        engine.dispose()
        with owner.begin() as connection:
            connection.execute(text(f"DROP TABLE {SCHEMA}.later_table"))


def test_story_2_4_other_logins_cannot_read_it(
    postgres_server: PostgresServer, intake_database: str
) -> None:
    engine = create_engine(
        postgres_server.url(postgres_server.outsider, intake_database)
    )
    try:
        with (
            engine.connect() as connection,
            pytest.raises(ProgrammingError, match="permission denied for schema"),
        ):
            connection.execute(text(f"SELECT count(*) FROM {SCHEMA}.purchase_order"))  # noqa: S608  # fixed name
    finally:
        engine.dispose()
