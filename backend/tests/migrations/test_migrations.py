"""Story 2.1: the Alembic migrations (AD-11, AD-17 step 6) against PostgreSQL 18, run
through the CLI exactly as ci/migrate.sh does: PG* variables and `-x` role names."""

import pytest
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.exc import ProgrammingError

from conftest import PostgresServer


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
    # Story 2.4 moved head on; this test is about the chain, not the latest revision.
    assert "(head)" in current.stdout


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


def test_story_2_1_app_logins_cannot_delete_or_rewrite_history(
    postgres_server: PostgresServer, intake_database: str
) -> None:
    for login in ("pipeline", "staff_api"):
        engine = _engine(
            postgres_server, getattr(postgres_server, login), intake_database
        )
        try:
            for statement in REFUSED:
                with (
                    engine.connect() as connection,
                    pytest.raises(ProgrammingError, match="permission denied"),
                ):
                    connection.execute(text(statement))
        finally:
            engine.dispose()
    # Other logins have no grant on the schema at all.
    outsider = _engine(postgres_server, postgres_server.outsider, intake_database)
    try:
        with (
            outsider.connect() as connection,
            pytest.raises(
                ProgrammingError, match="permission denied for schema intake"
            ),
        ):
            connection.execute(text("SELECT count(*) FROM intake.invoice"))
    finally:
        outsider.dispose()
