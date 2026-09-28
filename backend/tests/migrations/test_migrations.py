"""Story 2.1: the Alembic migrations (AD-11, AD-17 step 6) against PostgreSQL 18, run
through the CLI exactly as ci/migrate.sh does: PG* variables and `-x` role names."""

import subprocess
import sys
from collections.abc import Iterator
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import ProgrammingError

from conftest import BACKEND_DIR, PostgresServer
from invoicing.adapters.postgres.schema import metadata as intake_metadata
from invoicing.domain.reasons import ReasonCode


def _sql_type(sql_type: Any) -> str:
    """A column type as PostgreSQL DDL, so a declared and a reflected type compare."""
    return str(sql_type.compile(dialect=postgresql.dialect()))


INTAKE_TABLES = {"invoice", "status_history", "admin_item", "image_hash"}


def _engine(server: PostgresServer, user: str, database: str) -> Engine:
    return create_engine(server.url(user, database))


def test_story_2_1_upgrade_downgrade_upgrade(postgres_server: PostgresServer) -> None:
    database = "invoicing_migrations"
    postgres_server.create_database(database)
    for args in (["upgrade", "head"], ["downgrade", "base"], ["upgrade", "head"]):
        result = postgres_server.alembic(database, *args)
        assert result.returncode == 0, result.stdout + result.stderr
        if args[0] == "downgrade":
            engine = _engine(postgres_server, postgres_server.deployer, database)
            with engine.connect() as connection:
                assert "intake" not in inspect(connection).get_schema_names()
                # Downgrade revoked the default privileges it set, too.
                leftover = connection.execute(
                    text("SELECT count(*) FROM pg_default_acl")
                ).scalar()
                assert leftover == 0
            engine.dispose()
    current = postgres_server.alembic(database, "current")
    assert "0001_intake (head)" in current.stdout


def _alembic_without_fixture_roles(
    server: PostgresServer, database: str, *x_args: str
) -> subprocess.CompletedProcess[str]:
    x = [part for arg in x_args for part in ("-x", arg)]
    return subprocess.run(  # noqa: S603  # our own interpreter and alembic
        [sys.executable, "-m", "alembic", *x, "upgrade", "head"],
        cwd=BACKEND_DIR,
        env={"PATH": "", **server.libpq_env(server.deployer, database)},
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def test_story_2_1_role_names_are_required_and_checked(
    postgres_server: PostgresServer,
) -> None:
    database = "invoicing_no_roles"
    postgres_server.create_database(database)
    missing = _alembic_without_fixture_roles(
        postgres_server, database, "pipeline_role=x"
    )
    assert missing.returncode != 0
    assert "-x staff_api_role=<login>" in missing.stderr
    bad = _alembic_without_fixture_roles(
        postgres_server, database, "pipeline_role=x; DROP TABLE y", "staff_api_role=s"
    )
    assert bad.returncode != 0
    assert "-x pipeline_role is not a valid login name" in bad.stderr
    # Nothing was created by either attempt.
    engine = _engine(postgres_server, postgres_server.deployer, database)
    with engine.connect() as connection:
        assert "intake" not in inspect(connection).get_schema_names()
    engine.dispose()


@pytest.fixture
def owner(postgres_server: PostgresServer, intake_database: str) -> Iterator[Engine]:
    engine = _engine(postgres_server, postgres_server.deployer, intake_database)
    yield engine
    engine.dispose()


def test_story_2_1_the_schema_matches_the_adapters_tables(owner: Engine) -> None:
    with owner.connect() as connection:
        inspector = inspect(connection)
        assert set(inspector.get_table_names(schema="intake")) == INTAKE_TABLES
        for table in intake_metadata.sorted_tables:
            columns = {
                c["name"]: c for c in inspector.get_columns(table.name, "intake")
            }
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
                for fk in inspector.get_foreign_keys(table.name, "intake")
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
            primary_key = inspector.get_pk_constraint(table.name, "intake")
            assert primary_key["constrained_columns"] == [
                c.name for c in table.primary_key.columns
            ], table.name
        # AD-3: exactly the invoice columns the spine lists.
        assert [c["name"] for c in inspector.get_columns("invoice", "intake")] == [
            "id", "correlation_id", "source", "supplier_id", "delivery_id",
            "content_type", "device_check", "photo_taken_at", "po_number", "status",
            "status_changed_at", "claimed_until", "next_attempt_at", "post_failures",
            "accounts_ref", "posted_at", "created_at",
        ]  # fmt: skip


@pytest.mark.parametrize(
    ("statement", "constraint"),
    [
        ("status = 'lost'", "ck_invoice_status"),
        ("source = 'email'", "ck_invoice_source"),
        ("content_type = 'image/gif'", "ck_invoice_content_type"),
        ("device_check = 'maybe'", "ck_invoice_device_check"),
    ],
)
def test_story_2_1_checks_refuse_values_outside_the_catalogues(
    owner: Engine, statement: str, constraint: str
) -> None:
    invoice_id = UUID("0192f0c1-7a2b-7c3d-8e4f-00000000c0de")
    with owner.connect() as connection:
        connection.execute(
            text(
                "INSERT INTO intake.invoice (id, correlation_id, source, supplier_id,"
                " content_type, device_check, status) VALUES (:id, :id, 'link', :id,"
                " 'image/jpeg', 'passed', 'received')"
            ),
            {"id": invoice_id},
        )
        with pytest.raises(Exception, match=constraint):
            connection.execute(
                text(f"UPDATE intake.invoice SET {statement} WHERE id = :id"),  # noqa: S608  # fixed test literals
                {"id": invoice_id},
            )
        connection.rollback()


def test_story_2_1_admin_item_reasons_are_the_catalogue(owner: Engine) -> None:
    with owner.connect() as connection:
        (check,) = connection.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint"
                " WHERE conname = 'ck_admin_item_reason'"
            )
        ).one()
    for code in ReasonCode:
        assert f"'{code.value}'" in check


@pytest.mark.parametrize("login", ["pipeline", "staff_api"])
def test_story_2_1_app_logins_read_and_write_intake(
    postgres_server: PostgresServer, intake_database: str, login: str
) -> None:
    engine = _engine(postgres_server, getattr(postgres_server, login), intake_database)
    invoice_id = UUID("0192f0c1-7a2b-7c3d-8e4f-0000000a11ce")
    try:
        with engine.connect() as connection:
            for table in INTAKE_TABLES:
                connection.execute(text(f"SELECT count(*) FROM intake.{table}"))  # noqa: S608  # fixed names
            connection.execute(
                text(
                    "INSERT INTO intake.invoice (id, correlation_id, source, supplier_id,"
                    " content_type, device_check, status) VALUES (:id, :id, 'link',"
                    " :id, 'image/jpeg', 'passed', 'received')"
                ),
                {"id": invoice_id},
            )
            connection.execute(
                text("UPDATE intake.invoice SET po_number = 'PO-1' WHERE id = :id"),
                {"id": invoice_id},
            )
            connection.execute(
                text(
                    "INSERT INTO intake.status_history (id, invoice_id, to_status, actor)"
                    " VALUES (:id, :id, 'received', 't')"
                ),
                {"id": invoice_id},
            )
            connection.execute(
                text(
                    "INSERT INTO intake.image_hash (invoice_id, phash) VALUES (:id, 1)"
                ),
                {"id": invoice_id},
            )
            connection.execute(
                text(
                    "INSERT INTO intake.admin_item (id, invoice_id, routing_id, reason)"
                    " VALUES (:id, :id, :id, 'UNREADABLE')"
                ),
                {"id": invoice_id},
            )
            connection.rollback()
    finally:
        engine.dispose()


# Least privilege (AD-11, security.md rule 32): nobody deletes, and history, admin
# items and hashes are never rewritten. Each statement in its own transaction.
REFUSED = [
    "DELETE FROM intake.invoice",
    "DELETE FROM intake.status_history",
    "DELETE FROM intake.admin_item",
    "DELETE FROM intake.image_hash",
    "UPDATE intake.status_history SET actor = 'x'",
    "UPDATE intake.admin_item SET reason = 'DUPLICATE'",
    "UPDATE intake.image_hash SET phash = 0",
    "TRUNCATE intake.invoice CASCADE",
    # Never DDL on the schema the deployer owns.
    "CREATE TABLE intake.sneaky (id int)",
]


@pytest.mark.parametrize("statement", REFUSED)
@pytest.mark.parametrize("login", ["pipeline", "staff_api"])
def test_story_2_1_app_logins_cannot_delete_or_rewrite_history(
    postgres_server: PostgresServer, intake_database: str, login: str, statement: str
) -> None:
    engine = _engine(postgres_server, getattr(postgres_server, login), intake_database)
    try:
        with (
            engine.connect() as connection,
            pytest.raises(ProgrammingError, match="permission denied"),
        ):
            connection.execute(text(statement))
    finally:
        engine.dispose()


def test_story_2_1_a_table_added_later_is_granted_by_default(
    postgres_server: PostgresServer, intake_database: str, owner: Engine
) -> None:
    with owner.begin() as connection:
        connection.execute(text("CREATE TABLE intake.later_table (id int)"))
    engine = _engine(postgres_server, postgres_server.pipeline, intake_database)
    try:
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO intake.later_table VALUES (1)"))
            connection.execute(text("UPDATE intake.later_table SET id = 2"))
        with (
            engine.connect() as connection,
            pytest.raises(ProgrammingError, match="permission denied"),
        ):
            connection.execute(text("DELETE FROM intake.later_table"))
    finally:
        engine.dispose()
        with owner.begin() as connection:
            connection.execute(text("DROP TABLE intake.later_table"))


def test_story_2_1_other_logins_have_no_intake_grant(
    postgres_server: PostgresServer, intake_database: str
) -> None:
    engine = _engine(postgres_server, postgres_server.outsider, intake_database)
    try:
        with (
            engine.connect() as connection,
            pytest.raises(
                ProgrammingError, match="permission denied for schema intake"
            ),
        ):
            connection.execute(text("SELECT count(*) FROM intake.invoice"))
    finally:
        engine.dispose()
