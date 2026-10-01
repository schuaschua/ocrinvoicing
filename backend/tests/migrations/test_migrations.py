"""Story 2.1: the Alembic migrations (AD-11, AD-17 step 6) against PostgreSQL 18, run
through the CLI exactly as ci/migrate.sh does: PG* variables and `-x` role names."""

from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError, ProgrammingError

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
    # Story 2.3: extraction runs, fields and lines are append-only (AD-18).
    "UPDATE intake.extraction_run SET pages = 0",
    "UPDATE intake.invoice_field SET confidence = 1",
    "UPDATE intake.invoice_line SET confidence = 1",
    "DELETE FROM intake.invoice_field",
    # Story 2.9: page sizes are append-only like their run.
    "UPDATE intake.extraction_page SET width = 1",
    "DELETE FROM intake.extraction_page",
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
    # Story 2.9: only the pipeline saves page sizes; staff-api only reads them.
    staff = _engine(postgres_server, postgres_server.staff_api, intake_database)
    try:
        with (
            staff.connect() as connection,
            pytest.raises(ProgrammingError, match="permission denied"),
        ):
            connection.execute(
                text(
                    "INSERT INTO intake.extraction_page (run_id, page, width, height,"
                    " unit) VALUES (gen_random_uuid(), 1, 1, 1, 'pixel')"
                )
            )
    finally:
        staff.dispose()
    # Story 4.2 (AD-11, AD-13): staff-api reads `analytics` and never writes it; the
    # pipeline login (the refresh job) writes it, which the Story 4.2 tests prove.
    staff = _engine(postgres_server, postgres_server.staff_api, intake_database)
    try:
        with staff.connect() as connection:
            connection.execute(text("SELECT count(*) FROM analytics.overdue_po"))
            connection.execute(text("SELECT count(*) FROM analytics.job_run"))
        for statement in (
            (
                "INSERT INTO analytics.overdue_po (po_number, supplier_id,"
                " expected_date) VALUES ('PO-1', gen_random_uuid(), '2026-09-01')"
            ),
            "UPDATE analytics.overdue_po SET po_number = 'x'",
            "DELETE FROM analytics.overdue_po",
            (
                "INSERT INTO analytics.job_run (job, run_date, finished_at)"
                " VALUES ('overdue_po', '2026-09-01', now())"
            ),
            "UPDATE analytics.job_run SET job = 'x'",
            "DELETE FROM analytics.job_run",
        ):
            with (
                staff.connect() as connection,
                pytest.raises(ProgrammingError, match="permission denied"),
            ):
                connection.execute(text(statement))
    finally:
        staff.dispose()
    # The pipeline rebuilds `overdue_po` but never rewrites a row, and can't erase or
    # change a recorded run (the once-a-day guard).
    pipeline = _engine(postgres_server, postgres_server.pipeline, intake_database)
    try:
        for statement in (
            "UPDATE analytics.overdue_po SET po_number = 'x'",
            "UPDATE analytics.job_run SET job = 'x'",
            "DELETE FROM analytics.job_run",
        ):
            with (
                pipeline.connect() as connection,
                pytest.raises(ProgrammingError, match="permission denied"),
            ):
                connection.execute(text(statement))
    finally:
        pipeline.dispose()
    # Other logins have no grant on the schema at all.
    outsider = _engine(postgres_server, postgres_server.accounts_sim, intake_database)
    try:
        with (
            outsider.connect() as connection,
            pytest.raises(
                ProgrammingError, match="permission denied for schema intake"
            ),
        ):
            connection.execute(text("SELECT count(*) FROM intake.invoice"))
        with (
            outsider.connect() as connection,
            pytest.raises(
                ProgrammingError, match="permission denied for schema analytics"
            ),
        ):
            connection.execute(text("SELECT count(*) FROM analytics.overdue_po"))
    finally:
        outsider.dispose()

    # Story 2.3 (AD-11): a bank field never holds a plaintext value, and only a bank
    # field holds ciphertext. Written as the owner, inside a rolled-back transaction.
    owner = _engine(postgres_server, postgres_server.deployer, intake_database)
    field = (
        "INSERT INTO intake.invoice_field (id, invoice_id, run_id, field_id, source, {})"
        " VALUES (gen_random_uuid(), :invoice, :run, '{}', 'di', {})"
    )
    try:
        with owner.connect() as connection, connection.begin():
            ids = {"invoice": uuid4(), "run": uuid4()}
            connection.execute(
                text(
                    "INSERT INTO intake.invoice (id, correlation_id, source, supplier_id,"
                    " content_type, device_check, status) VALUES (:invoice,"
                    " gen_random_uuid(), 'link', gen_random_uuid(), 'image/jpeg',"
                    " 'passed', 'extracting')"
                ),
                ids,
            )
            connection.execute(
                text(
                    "INSERT INTO intake.extraction_run (run_id, invoice_id, model_id,"
                    " api_version, pages) VALUES (:run, :invoice, 'm', 'v', 1)"
                ),
                ids,
            )
            for columns, field_id, values in (
                ("value_text", "payment[0].iban", "'SG12ABCD'"),
                (
                    "bank_ciphertext, bank_fingerprint",
                    "vendor_name",
                    f"'\\x00'::bytea, '{'0' * 64}'",
                ),
            ):
                # The savepoint rolls back the refused insert only.
                with (
                    pytest.raises(IntegrityError, match="ck_invoice_field_bank"),
                    connection.begin_nested(),
                ):
                    connection.execute(
                        text(field.format(columns, field_id, values)), ids
                    )
            connection.rollback()
    finally:
        owner.dispose()
