"""`analytics.watchlist`: the supplier watchlist (Story 5.4, CAP-15, AD-13, AD-20).

Revision ID: 0013_watchlist
Revises: 0012_price_comparison
Create Date: 2026-10-01

Backward-compatible only (coding-style.md rule 29): a new table, nothing changed.

- `watchlist`: one row per supplier and AD-20 rule it is listed under, with the
  evidence and the date it was first listed. The analytics refresh job recomputes it
  in full each run and replaces the rows, keeping `first_added_on` while the pair
  stays listed.

AD-13: the pipeline login is the only writer, with SELECT, INSERT and DELETE (a
refresh replaces the rows); staff-api gets SELECT only.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0013_watchlist"
down_revision: str | Sequence[str] | None = "0012_price_comparison"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "analytics"
PIPELINE_GRANTS = {"watchlist": "SELECT, INSERT, DELETE"}
STAFF_API_GRANTS = dict.fromkeys(PIPELINE_GRANTS, "SELECT")


def _roles() -> tuple[str, str]:
    """(pipeline, staff-api) logins, quoted as identifiers (env.py checked them)."""
    roles: dict[str, str] = context.config.attributes["roles"]
    quote = op.get_bind().dialect.identifier_preparer.quote_identifier
    return quote(roles["pipeline_role"]), quote(roles["staff_api_role"])


def _grants() -> tuple[tuple[str, dict[str, str]], ...]:
    pipeline, staff_api = _roles()
    return ((pipeline, PIPELINE_GRANTS), (staff_api, STAFF_API_GRANTS))


def upgrade() -> None:
    op.create_table(
        "watchlist",
        sa.Column("supplier_id", sa.Uuid, primary_key=True),
        sa.Column("rule", sa.Text, primary_key=True),
        sa.Column("first_added_on", sa.Date, nullable=False),
        sa.Column(
            "evidence", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.CheckConstraint(
            "rule IN ('price_rises', 'late', 'price_gap')", name="ck_watchlist_rule"
        ),
        schema=SCHEMA,
    )
    for role, grants in _grants():
        for table, privileges in grants.items():
            op.execute(f"GRANT {privileges} ON {SCHEMA}.{table} TO {role}")


def downgrade() -> None:
    """Revokes the grants and drops the table. Needs the same `-x` role arguments as
    the upgrade (env.py requires them)."""
    for role, grants in _grants():
        for table, privileges in grants.items():
            op.execute(f"REVOKE {privileges} ON {SCHEMA}.{table} FROM {role}")
    op.drop_table("watchlist", schema=SCHEMA)
