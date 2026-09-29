"""Story 1.9: migration 0003_device_check_skipped against PostgreSQL 18: the invoice
check accepts `skipped` (AD-5), still refuses anything else, and a downgrade narrows
it back after rewriting `skipped` rows as `passed`."""

from uuid import UUID

import pytest
from sqlalchemy import Connection, create_engine, text

from conftest import PostgresServer
from invoicing.domain.upload import DeviceCheck

INVOICE_ID = UUID("0192f0c1-7a2b-7c3d-8e4f-00000001c0de")


def _insert(connection: Connection, device_check: str) -> None:
    connection.execute(
        text(
            "INSERT INTO intake.invoice (id, correlation_id, source, supplier_id,"
            " content_type, device_check, status) VALUES (:id, :id, 'link', :id,"
            " 'image/jpeg', :device_check, 'received')"
        ),
        {"id": INVOICE_ID, "device_check": device_check},
    )


def _device_check(connection: Connection) -> str:
    return str(
        connection.execute(
            text("SELECT device_check FROM intake.invoice WHERE id = :id"),
            {"id": INVOICE_ID},
        ).scalar_one()
    )


def test_story_1_9_every_device_check_value_is_accepted_at_head(
    postgres_server: PostgresServer, intake_database: str
) -> None:
    engine = create_engine(
        postgres_server.url(postgres_server.deployer, intake_database)
    )
    try:
        for value in DeviceCheck:
            with engine.connect() as connection:
                _insert(connection, value.value)
                assert _device_check(connection) == value.value
                connection.rollback()
        with engine.connect() as connection:
            with pytest.raises(Exception, match="ck_invoice_device_check"):
                _insert(connection, "maybe")
            connection.rollback()
    finally:
        engine.dispose()


def test_story_1_9_downgrade_rewrites_skipped_and_narrows_the_check(
    postgres_server: PostgresServer,
) -> None:
    database = "invoicing_device_check_skipped"
    postgres_server.create_database(database)
    engine = create_engine(postgres_server.url(postgres_server.deployer, database))
    try:
        result = postgres_server.alembic(database, "upgrade", "head")
        assert result.returncode == 0, result.stdout + result.stderr
        with engine.begin() as connection:
            _insert(connection, "skipped")

        result = postgres_server.alembic(database, "downgrade", "0002_sim_purchasing")
        assert result.returncode == 0, result.stdout + result.stderr
        with engine.connect() as connection:
            assert _device_check(connection) == "passed"
            with pytest.raises(Exception, match="ck_invoice_device_check"):
                connection.execute(
                    text(
                        "UPDATE intake.invoice SET device_check = 'skipped'"
                        " WHERE id = :id"
                    ),
                    {"id": INVOICE_ID},
                )
            connection.rollback()

        result = postgres_server.alembic(database, "upgrade", "head")
        assert result.returncode == 0, result.stdout + result.stderr
        current = postgres_server.alembic(database, "current")
        assert "0003_device_check_skipped (head)" in current.stdout
    finally:
        engine.dispose()
