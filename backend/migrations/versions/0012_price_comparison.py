"""`analytics.material`: material names for Price comparison (Story 5.3, AD-10, AD-13).

Revision ID: 0012_price_comparison
Revises: 0011_analytics_summaries
Create Date: 2026-10-01

Backward-compatible only (coding-style.md rule 29): a new table, nothing changed.

- `material`: the name of each material that has a price point, read from purchasing
  through `PurchasingPort.material_names` (AD-10) and replaced as a whole by the
  analytics refresh job, so staff-api's dashboards never read purchasing.

AD-13: the pipeline login is the only writer, with SELECT, INSERT and DELETE (a
refresh replaces the rows); staff-api gets SELECT only.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0012_price_comparison"
down_revision: str | Sequence[str] | None = "0011_analytics_summaries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "analytics"
PIPELINE_GRANTS = {"material": "SELECT, INSERT, DELETE"}
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
        "material",
        sa.Column("material_id", sa.Uuid, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
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
    op.drop_table("material", schema=SCHEMA)
