"""Each extraction run's page sizes, for the admin item's field boxes (Story 2.9).

Revision ID: 0008_extraction_pages
Revises: 0007_staff_queue
Create Date: 2026-09-30

Backward-compatible only (coding-style.md rule 29): one new table, nothing changed.

`extraction_page(run_id, page, width, height, unit)`: DI's size of each analysed page
(`pixel` for an image, `inch` for a PDF), the unit a field's polygon is in. Runs saved
before this revision have none, and their items show no boxes. Append-only like its
run (security.md rule 32): the pipeline may SELECT and INSERT, staff-api may SELECT.

Grants are explicit: the table first loses the default privileges 0001_intake set for
new tables, then gets exactly its own.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0008_extraction_pages"
down_revision: str | Sequence[str] | None = "0007_staff_queue"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "intake"
TABLE = "extraction_page"
# domain/extraction.py PAGE_UNITS, copied on purpose (see 0001_intake).
UNITS = ("pixel", "inch")


def _roles() -> tuple[str, str]:
    """The pipeline and staff-api logins, quoted as identifiers (env.py checked them)."""
    roles: dict[str, str] = context.config.attributes["roles"]
    quote = op.get_bind().dialect.identifier_preparer.quote_identifier
    return quote(roles["pipeline_role"]), quote(roles["staff_api_role"])


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column(
            "run_id",
            sa.Uuid,
            sa.ForeignKey(f"{SCHEMA}.extraction_run.run_id"),
            primary_key=True,
        ),
        sa.Column("page", sa.Integer, primary_key=True),
        sa.Column("width", sa.Double, nullable=False),
        sa.Column("height", sa.Double, nullable=False),
        sa.Column("unit", sa.Text, nullable=False),
        sa.CheckConstraint("page > 0", name="ck_extraction_page_page"),
        sa.CheckConstraint("width > 0 AND height > 0", name="ck_extraction_page_size"),
        sa.CheckConstraint(
            f"unit IN ({', '.join(repr(u) for u in UNITS)})",
            name="ck_extraction_page_unit",
        ),
        schema=SCHEMA,
    )
    pipeline, staff_api = _roles()
    target = f"{SCHEMA}.{TABLE}"
    for role in (pipeline, staff_api):
        op.execute(f"REVOKE ALL ON {target} FROM {role}")
    op.execute(f"GRANT SELECT, INSERT ON {target} TO {pipeline}")
    op.execute(f"GRANT SELECT ON {target} TO {staff_api}")


def downgrade() -> None:
    """Drops the table, and its grants with it."""
    op.drop_table(TABLE, schema=SCHEMA)
