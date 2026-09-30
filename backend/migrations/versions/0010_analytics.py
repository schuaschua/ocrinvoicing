"""The `analytics` schema and the overdue list (Story 4.2, AD-11, AD-13).

Revision ID: 0010_analytics
Revises: 0009_sim_accounts
Create Date: 2026-09-30

Backward-compatible only (coding-style.md rule 29): a new schema, nothing changed.

- `overdue_po`: the overdue list (CAP-12), one row per PO, replaced as a whole by
  each day's run of the analytics refresh job.
- `job_run`: one row per job and Singapore date that ran, written in the same
  transaction as the job's rows. Its `finished_at` is the date the list was made, and
  its presence is the once-a-day guard.

AD-13: the analytics refresh job (the pipeline login) is the only writer, with only
what it uses: SELECT, INSERT and DELETE on `overdue_po` (a rebuild replaces the rows),
SELECT and INSERT on `job_run` (a recorded run is never changed or erased, so the
once-a-day guard can't be undone). staff-api reads the dashboards and gets SELECT
only. No other login gets anything on the schema.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0010_analytics"
down_revision: str | Sequence[str] | None = "0009_sim_accounts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "analytics"
TABLES = ("overdue_po", "job_run")
PIPELINE_GRANTS = {"overdue_po": "SELECT, INSERT, DELETE", "job_run": "SELECT, INSERT"}
STAFF_API_GRANTS = dict.fromkeys(TABLES, "SELECT")


def _roles() -> tuple[str, str]:
    """(pipeline, staff-api) logins, quoted as identifiers (env.py checked them)."""
    roles: dict[str, str] = context.config.attributes["roles"]
    quote = op.get_bind().dialect.identifier_preparer.quote_identifier
    return quote(roles["pipeline_role"]), quote(roles["staff_api_role"])


def _grants() -> tuple[tuple[str, dict[str, str]], ...]:
    pipeline, staff_api = _roles()
    return ((pipeline, PIPELINE_GRANTS), (staff_api, STAFF_API_GRANTS))


def upgrade() -> None:
    op.execute(sa.schema.CreateSchema(SCHEMA))
    op.create_table(
        "overdue_po",
        sa.Column("po_number", sa.Text, primary_key=True),
        sa.Column("supplier_id", sa.Uuid, nullable=False),
        sa.Column("expected_date", sa.Date, nullable=False),
        schema=SCHEMA,
    )
    op.create_table(
        "job_run",
        sa.Column("job", sa.Text, primary_key=True),
        sa.Column("run_date", sa.Date, primary_key=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    for role, grants in _grants():
        op.execute(f"GRANT USAGE ON SCHEMA {SCHEMA} TO {role}")
        for table, privileges in grants.items():
            op.execute(f"GRANT {privileges} ON {SCHEMA}.{table} TO {role}")


def downgrade() -> None:
    """Revokes the grants and drops the schema. Needs the same `-x` role arguments as
    the upgrade (env.py requires them)."""
    for role, grants in _grants():
        for table, privileges in grants.items():
            op.execute(f"REVOKE {privileges} ON {SCHEMA}.{table} FROM {role}")
        op.execute(f"REVOKE USAGE ON SCHEMA {SCHEMA} FROM {role}")
    op.drop_table("job_run", schema=SCHEMA)
    op.drop_table("overdue_po", schema=SCHEMA)
    op.execute(sa.schema.DropSchema(SCHEMA))
