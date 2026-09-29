"""Story 1.6: migration 0004_master_audit against PostgreSQL 18: the `master` and
`audit` schemas, their AD-11 grants (column-level for the pipeline), and a downgrade
that returns them exactly."""

from collections.abc import Iterator
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.exc import ProgrammingError

from conftest import PostgresServer
from invoicing.adapters.postgres.suppliers import metadata as supplier_metadata

SUPPLIER_ID = UUID("01a0c450-6c00-7b7b-8aa9-4ccade9f5526")
FINGERPRINT = "ab" * 32


def _acl_snapshot(server: PostgresServer, database: str) -> list[Any]:
    """Every ACL on the two schemas, their tables and columns (as the superuser)."""
    engine = create_engine(server.url(server.superuser, database))
    try:
        with engine.connect() as connection:
            return list(
                connection.execute(
                    text(
                        "SELECT n.nspname, n.nspacl::text, c.relname, c.relacl::text,"
                        " a.attname, a.attacl::text"
                        " FROM pg_namespace n"
                        " LEFT JOIN pg_class c ON c.relnamespace = n.oid"
                        " LEFT JOIN pg_attribute a ON a.attrelid = c.oid"
                        "  AND a.attnum > 0 AND a.attacl IS NOT NULL"
                        " WHERE n.nspname IN ('master', 'audit')"
                        " ORDER BY 1, 3, 5"
                    )
                )
            )
    finally:
        engine.dispose()


def test_story_1_6_downgrade_and_upgrade_return_schemas_and_grants_exactly(
    postgres_server: PostgresServer,
) -> None:
    database = "invoicing_master_audit"
    postgres_server.create_database(database)
    result = postgres_server.alembic(database, "upgrade", "head")
    assert result.returncode == 0, result.stdout + result.stderr
    first = _acl_snapshot(postgres_server, database)
    assert first, "the schemas carry grants"

    # The append-only audit log is never dropped by a downgrade while it holds rows.
    admin = create_engine(postgres_server.url(postgres_server.superuser, database))
    with admin.begin() as connection:
        connection.execute(
            text("INSERT INTO audit.event (id, action, entity, entity_id)"
                 " VALUES (gen_random_uuid(), 'test.action', 'supplier', 'x')")
        )  # fmt: skip
    result = postgres_server.alembic(database, "downgrade", "0003_device_check_skipped")
    assert result.returncode != 0
    assert "refusing to downgrade 0004_master_audit" in result.stderr
    assert _acl_snapshot(postgres_server, database) == first
    with admin.begin() as connection:
        connection.execute(text("DELETE FROM audit.event"))
    admin.dispose()

    result = postgres_server.alembic(database, "downgrade", "0003_device_check_skipped")
    assert result.returncode == 0, result.stdout + result.stderr
    assert _acl_snapshot(postgres_server, database) == []
    engine = create_engine(postgres_server.url(postgres_server.deployer, database))
    try:
        with engine.connect() as connection:
            schemas = inspect(connection).get_schema_names()
            assert "master" not in schemas and "audit" not in schemas
            assert "intake" in schemas
            # Neither schema set default privileges, so none are left behind.
            assert connection.execute(
                text("SELECT count(*) FROM pg_default_acl d JOIN pg_namespace n"
                     " ON n.oid = d.defaclnamespace"
                     " WHERE n.nspname IN ('master', 'audit')")
            ).scalar() == 0  # fmt: skip
    finally:
        engine.dispose()

    result = postgres_server.alembic(database, "upgrade", "head")
    assert result.returncode == 0, result.stdout + result.stderr
    assert _acl_snapshot(postgres_server, database) == first
    _check_tables(postgres_server, database)


@pytest.fixture
def superuser(
    postgres_server: PostgresServer, intake_database: str
) -> Iterator[Engine]:
    engine = create_engine(
        postgres_server.url(postgres_server.superuser, intake_database)
    )
    yield engine
    engine.dispose()


def _check_tables(server: PostgresServer, database: str) -> None:
    """The tables match the adapter's and the spine's columns; pgcrypto is there."""
    engine = create_engine(server.url(server.superuser, database))
    with engine.connect() as connection:
        inspector = inspect(connection)
        for table in supplier_metadata.sorted_tables:
            columns = [
                c["name"] for c in inspector.get_columns(table.name, table.schema)
            ]
            assert columns == [c.name for c in table.columns], table.name
        # AD-11: exactly the columns the spine lists.
        assert [c["name"] for c in inspector.get_columns("supplier", "master")] == [
            "id", "name", "tax_id", "phone",
        ]  # fmt: skip
        assert [
            c["name"] for c in inspector.get_columns("supplier_bank", "master")
        ] == ["supplier_id", "field_id", "ciphertext", "fingerprint"]
        assert [c["name"] for c in inspector.get_columns("event", "audit")] == [
            "id", "at", "actor", "action", "entity", "entity_id", "detail",
        ]  # fmt: skip
        assert connection.execute(
            text("SELECT count(*) FROM pg_extension WHERE extname = 'pgcrypto'")
        ).scalar() == 1  # fmt: skip
    engine.dispose()


# (login, schema.table[.column], privilege) -> allowed, per AD-11 (the grant matrix).
GRANTS = (
    [
        ("dj", "master.supplier", "SELECT", True),
        ("dj", "master.supplier", "INSERT", True),
        ("dj", "master.supplier", "UPDATE", True),
        ("dj", "master.supplier", "DELETE", False),
        ("dj", "master.supplier", "TRUNCATE", False),
        ("dj", "master.supplier_bank", "SELECT", True),
        ("dj", "master.supplier_bank", "INSERT", True),
        ("dj", "master.supplier_bank", "UPDATE", True),
        ("dj", "master.supplier_bank", "DELETE", False),
        ("dj", "master.supplier_bank", "TRUNCATE", False),
        ("dj", "audit.event", "SELECT", False),
        ("dj", "intake.invoice", "SELECT", False),
        ("staff_api", "master.supplier", "SELECT", True),
        ("staff_api", "master.supplier", "UPDATE", False),
        ("staff_api", "master.supplier_bank.ciphertext", "SELECT", True),
        ("staff_api", "master.supplier_bank", "INSERT", False),
        ("staff_api", "audit.event", "SELECT", True),
        ("pipeline", "master.supplier", "SELECT", True),
        ("pipeline", "master.supplier", "INSERT", False),
        ("pipeline", "master.supplier_bank.fingerprint", "SELECT", True),
        ("pipeline", "master.supplier_bank.field_id", "SELECT", True),
        ("pipeline", "master.supplier_bank.supplier_id", "SELECT", True),
        ("pipeline", "master.supplier_bank", "INSERT", False),
        ("pipeline", "master.supplier_bank", "UPDATE", False),
        ("pipeline", "master.supplier_bank.ciphertext", "SELECT", False),
        ("pipeline", "audit.event", "SELECT", False),
        ("outsider", "master.supplier", "SELECT", False),
        ("outsider", "audit.event.action", "INSERT", False),
    ]
    + [
        (login, "audit.event", privilege, False)
        for login in ("dj", "staff_api", "pipeline")
        for privilege in ("UPDATE", "DELETE", "TRUNCATE")
    ]
    + [
        # INSERT on every column but `at` and `actor`, whose defaults always apply.
        (login, f"audit.event.{column}", "INSERT", column not in ("at", "actor"))
        for login in ("dj", "staff_api", "pipeline")
        for column in ("id", "action", "entity", "entity_id", "detail", "at", "actor")
    ]
)


def _check_grants(server: PostgresServer, superuser: Engine) -> None:
    with superuser.connect() as connection:
        for login, target, privilege, allowed in GRANTS:
            parts = target.split(".")
            if len(parts) == 3:
                query = (
                    "SELECT has_column_privilege(:role, :table, :column, :privilege)"
                )
                params = {"table": ".".join(parts[:2]), "column": parts[2]}
            else:
                query = "SELECT has_table_privilege(:role, :table, :privilege)"
                params = {"table": target}
            held = connection.execute(
                text(query),
                {"role": getattr(server, login), "privilege": privilege, **params},
            ).scalar()
            assert held is allowed, (login, target, privilege)


def _as(server: PostgresServer, login: str, database: str) -> Engine:
    return create_engine(server.url(getattr(server, login), database))


def test_story_1_6_grants_follow_ad_11_and_the_pipeline_never_reads_ciphertext(
    postgres_server: PostgresServer, intake_database: str, superuser: Engine
) -> None:
    _check_grants(postgres_server, superuser)
    _check_audit_is_append_only(postgres_server, intake_database, superuser)
    with superuser.begin() as connection:
        connection.execute(text("TRUNCATE master.supplier_bank, master.supplier"))
        connection.execute(
            text("INSERT INTO master.supplier (id, name) VALUES (:id, 'Synthetic')"),
            {"id": SUPPLIER_ID},
        )
        connection.execute(
            text(
                "INSERT INTO master.supplier_bank VALUES"
                " (:id, 'iban', '\\x00'::bytea, :fingerprint)"
            ),
            {"id": SUPPLIER_ID, "fingerprint": FINGERPRINT},
        )
    pipeline = _as(postgres_server, "pipeline", intake_database)
    try:
        with pipeline.connect() as connection:
            # AD-19 compares fingerprints; that read is allowed.
            assert connection.execute(
                text("SELECT field_id, fingerprint FROM master.supplier_bank")
            ).all() == [("iban", FINGERPRINT)]
        with (
            pipeline.connect() as connection,
            pytest.raises(ProgrammingError, match="permission denied"),
        ):
            connection.execute(text("SELECT ciphertext FROM master.supplier_bank"))
        with (
            pipeline.connect() as connection,
            pytest.raises(ProgrammingError, match="permission denied"),
        ):
            connection.execute(text("SELECT * FROM master.supplier_bank"))
    finally:
        pipeline.dispose()
        with superuser.begin() as connection:
            connection.execute(text("TRUNCATE master.supplier_bank, master.supplier"))


def _check_audit_is_append_only(
    postgres_server: PostgresServer, intake_database: str, superuser: Engine
) -> None:
    event_id = UUID("01a0c450-0000-7000-8000-0000000a0d17")
    staff = _as(postgres_server, "staff_api", intake_database)
    try:
        with staff.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO audit.event (id, action, entity, entity_id)"
                    " VALUES (:id, 'test.action', 'supplier', 'x')"
                ),
                {"id": event_id},
            )
        with staff.connect() as connection:
            actor = connection.execute(
                text("SELECT actor FROM audit.event WHERE id = :id"), {"id": event_id}
            ).scalar()
            assert actor == postgres_server.staff_api
        for statement in (
            "UPDATE audit.event SET action = 'changed'",
            "DELETE FROM audit.event",
            # A writer can't forge who wrote a row, or when.
            (
                "INSERT INTO audit.event (id, actor, action, entity, entity_id) VALUES"
                " (gen_random_uuid(), 'someone-else', 'x', 'supplier', 'x')"
            ),
            (
                "INSERT INTO audit.event (id, at, action, entity, entity_id) VALUES"
                " (gen_random_uuid(), now() - interval '1 day', 'x', 'supplier', 'x')"
            ),
        ):
            with (
                staff.connect() as connection,
                pytest.raises(ProgrammingError, match="permission denied"),
            ):
                connection.execute(text(statement))
    finally:
        staff.dispose()
        with superuser.begin() as connection:
            connection.execute(
                text("DELETE FROM audit.event WHERE id = :id"), {"id": event_id}
            )
