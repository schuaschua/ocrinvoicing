"""The analytics summary tables and `analytics.alert` (Story 5.1, AD-13, AD-20).

Revision ID: 0011_analytics_summaries
Revises: 0010_analytics
Create Date: 2026-10-01

Backward-compatible only (coding-style.md rule 29): new tables, nothing changed.

Written by the analytics refresh job's daily summary step, read by staff-api's
dashboards (Stories 5.3 to 5.6) through `ports/dashboards.py`:

- `price_point` and `invoice_fact`: one row per current line with a material, and one
  per invoice, of each posted invoice (AD-20), rewritten per invoice from the
  `watermark`.
- `supplier_month`, `month_summary`, `supplier_month_flags`, `receipt_lateness` and
  `supplier_on_time`: recomputed in full by each day's run.
- `watermark`: the highest `posted_at` processed, per job.
- `alert`: the CAP-14 and CAP-15 alerts of Stories 5.3 and 5.4, each stored once by
  its `dedupe_key`; `emailed_at` is set when Story 5.2's email went out.

Money is `numeric(18,2)`, rates `numeric(5,4)` (AD-20). AD-13: the pipeline login is
the only writer, with only what it uses: SELECT, INSERT and DELETE on the rewritten
tables; SELECT, INSERT and UPDATE on `watermark` (it only moves forward); SELECT,
INSERT and UPDATE of `emailed_at` alone on `alert`, so an alert is never changed or
erased. staff-api gets SELECT only.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0011_analytics_summaries"
down_revision: str | Sequence[str] | None = "0010_analytics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "analytics"
REWRITTEN = "SELECT, INSERT, DELETE"
PIPELINE_GRANTS = {
    "price_point": REWRITTEN,
    "invoice_fact": REWRITTEN,
    "supplier_month": REWRITTEN,
    "month_summary": REWRITTEN,
    "supplier_month_flags": REWRITTEN,
    "receipt_lateness": REWRITTEN,
    "supplier_on_time": REWRITTEN,
    "watermark": "SELECT, INSERT, UPDATE",
    "alert": "SELECT, INSERT, UPDATE (emailed_at)",
}
STAFF_API_GRANTS = dict.fromkeys(PIPELINE_GRANTS, "SELECT")


def _money() -> sa.Numeric:
    return sa.Numeric(18, 2)


def _rate() -> sa.Numeric:
    return sa.Numeric(5, 4)


def _timestamp() -> sa.DateTime:
    return sa.DateTime(timezone=True)


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
        "price_point",
        sa.Column("invoice_id", sa.Uuid, primary_key=True),
        sa.Column("line_no", sa.Integer, primary_key=True),
        sa.Column("supplier_id", sa.Uuid, nullable=False),
        sa.Column("material_id", sa.Uuid, nullable=False),
        sa.Column("invoice_date", sa.Date, nullable=False),
        sa.Column("unit_price", _money(), nullable=False),
        sa.Column("posted_at", _timestamp(), nullable=False),
        schema=SCHEMA,
    )
    # AD-20: "previous price" is per supplier and material, by invoice_date.
    op.create_index(
        "ix_price_point_material",
        "price_point",
        ["material_id", "supplier_id", "invoice_date"],
        schema=SCHEMA,
    )
    op.create_table(
        "invoice_fact",
        sa.Column("invoice_id", sa.Uuid, primary_key=True),
        sa.Column("supplier_id", sa.Uuid, nullable=False),
        sa.Column("invoice_date", sa.Date, nullable=False),
        sa.Column("posted_month", sa.Date, nullable=False),
        sa.Column("total", _money()),
        sa.Column("straight_through", sa.Boolean, nullable=False),
        schema=SCHEMA,
    )
    op.create_table(
        "supplier_month",
        sa.Column("supplier_id", sa.Uuid, primary_key=True),
        sa.Column("month", sa.Date, primary_key=True),
        sa.Column("spend", _money(), nullable=False),
        sa.Column("posted_count", sa.Integer, nullable=False),
        schema=SCHEMA,
    )
    op.create_table(
        "month_summary",
        sa.Column("month", sa.Date, primary_key=True),
        sa.Column("posted_count", sa.Integer, nullable=False),
        sa.Column("straight_through_count", sa.Integer, nullable=False),
        sa.Column("straight_through_share", _rate(), nullable=False),
        schema=SCHEMA,
    )
    op.create_table(
        "supplier_month_flags",
        sa.Column("supplier_id", sa.Uuid, primary_key=True),
        sa.Column("month", sa.Date, primary_key=True),
        sa.Column("flagged_count", sa.Integer, nullable=False),
        sa.Column("duplicate_count", sa.Integer, nullable=False),
        schema=SCHEMA,
    )
    op.create_table(
        "receipt_lateness",
        sa.Column("receipt_id", sa.Uuid, primary_key=True),
        sa.Column("po_line_id", sa.Uuid, primary_key=True),
        sa.Column("supplier_id", sa.Uuid, nullable=False),
        sa.Column("material_id", sa.Uuid, nullable=False),
        sa.Column("received_date", sa.Date, nullable=False),
        sa.Column("days_late", sa.Integer, nullable=False),
        schema=SCHEMA,
    )
    op.create_table(
        "supplier_on_time",
        sa.Column("supplier_id", sa.Uuid, primary_key=True),
        sa.Column("receipts", sa.Integer, nullable=False),
        sa.Column("on_time", sa.Integer, nullable=False),
        sa.Column("on_time_rate", _rate(), nullable=False),
        sa.Column("avg_days_late", sa.Numeric(8, 2), nullable=False),
        schema=SCHEMA,
    )
    op.create_table(
        "watermark",
        sa.Column("job", sa.Text, primary_key=True),
        sa.Column("posted_at", _timestamp(), nullable=False),
        schema=SCHEMA,
    )
    op.create_table(
        "alert",
        sa.Column("alert_id", sa.Uuid, primary_key=True),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("dedupe_key", sa.Text, nullable=False),
        sa.Column("supplier_id", sa.Uuid, nullable=False),
        sa.Column("material_id", sa.Uuid),
        sa.Column(
            "detail", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "created_at", _timestamp(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("emailed_at", _timestamp()),
        sa.UniqueConstraint("dedupe_key", name="uq_alert_dedupe_key"),
        schema=SCHEMA,
    )
    for role, grants in _grants():
        for table, privileges in grants.items():
            op.execute(f"GRANT {privileges} ON {SCHEMA}.{table} TO {role}")


def downgrade() -> None:
    """Revokes the grants and drops the tables (the schema is 0010's). Needs the same
    `-x` role arguments as the upgrade (env.py requires them)."""
    for role, grants in _grants():
        for table, privileges in grants.items():
            op.execute(f"REVOKE {privileges} ON {SCHEMA}.{table} FROM {role}")
    for table in reversed(PIPELINE_GRANTS):
        op.drop_table(table, schema=SCHEMA)
