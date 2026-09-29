"""Extraction runs, fields and lines, DI usage and saved operations, with the AD-11
grants (Story 2.3, AD-8, AD-18).

Revision ID: 0005_extraction
Revises: 0004_master_audit
Create Date: 2026-09-30

Backward-compatible only (coding-style.md rule 29): five new tables, nothing changed.

- `extraction_run`, `invoice_field`, `invoice_line` (AD-18): append-only for both app
  logins (security.md rule 32; an admin correction adds a row, never updates one).
  A bank field (`payment[<n>].bank_account_number|iban|swift`) may hold only
  ciphertext plus fingerprint: a check refuses any value column on it (AD-11).
- `di_usage(month, pages, last_call_at)` and `di_operation(invoice_id,
  operation_location, created_at)` (AD-8): the Document Intelligence adapter's state,
  read and written by the pipeline login only (which may also delete a saved
  operation that DI expired or failed).

Grants are explicit: each table first loses the default privileges 0001_intake set
for new tables, then gets exactly its own. The value lists are copies of the domain's
at the time of writing, on purpose (see 0001_intake).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision: str = "0005_extraction"
down_revision: str | Sequence[str] | None = "0004_master_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "intake"
# AD-18 row sources.
SOURCES = ("di", "admin")
# domain/extraction.py is_bank_field_id: payment[<n>].<domain/suppliers.py BANK_FIELD_IDS>.
BANK_FIELD_ID_PATTERN = r"^payment\[[0-9]+\]\.(bank_account_number|iban|swift)$"

# (table, pipeline privileges, staff-api privileges), in creation order.
TABLE_GRANTS = (
    ("extraction_run", "SELECT, INSERT", "SELECT, INSERT"),
    ("invoice_field", "SELECT, INSERT", "SELECT, INSERT"),
    ("invoice_line", "SELECT, INSERT", "SELECT, INSERT"),
    ("di_usage", "SELECT, INSERT, UPDATE", None),
    # DELETE: a saved operation DI expired or failed is forgotten (Story 2.3).
    ("di_operation", "SELECT, INSERT, UPDATE, DELETE", None),
)


def _in(column: str, values: Sequence[str]) -> str:
    # Literals from the constants above only, never from input.
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _timestamp() -> sa.TIMESTAMP:
    return sa.TIMESTAMP(timezone=True)


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at", _timestamp(), nullable=False, server_default=sa.func.now()
    )


def _invoice_id(primary_key: bool = False) -> sa.Column:
    return sa.Column(
        "invoice_id",
        sa.Uuid,
        sa.ForeignKey(f"{SCHEMA}.invoice.id"),
        nullable=False,
        primary_key=primary_key,
    )


def _run_id() -> sa.Column:
    return sa.Column(
        "run_id",
        sa.Uuid,
        sa.ForeignKey(f"{SCHEMA}.extraction_run.run_id"),
        nullable=False,
    )


def _roles() -> tuple[str, str]:
    """The pipeline and staff-api logins, quoted as identifiers (env.py checked them)."""
    roles: dict[str, str] = context.config.attributes["roles"]
    quote = op.get_bind().dialect.identifier_preparer.quote_identifier
    return quote(roles["pipeline_role"]), quote(roles["staff_api_role"])


def upgrade() -> None:
    op.create_table(
        "extraction_run",
        sa.Column("run_id", sa.Uuid, primary_key=True),
        _invoice_id(),
        sa.Column("model_id", sa.Text, nullable=False),
        sa.Column("api_version", sa.Text, nullable=False),
        sa.Column("pages", sa.Integer, nullable=False),
        _created_at(),
        sa.CheckConstraint("pages >= 0", name="ck_extraction_run_pages"),
        schema=SCHEMA,
    )
    # AD-3: the latest run since the invoice last entered awaiting_extraction.
    op.create_index(
        "ix_extraction_run_invoice",
        "extraction_run",
        ["invoice_id", "created_at"],
        schema=SCHEMA,
    )

    bank_field = f"field_id ~ '{BANK_FIELD_ID_PATTERN}'"
    op.create_table(
        "invoice_field",
        sa.Column("id", sa.Uuid, primary_key=True),
        _invoice_id(),
        _run_id(),
        sa.Column("field_id", sa.Text, nullable=False),
        sa.Column("value_text", sa.Text),
        # Exact, as DI read it; validation compares it (coding-style.md rule 4).
        sa.Column("value_number", sa.Numeric),
        sa.Column("value_date", sa.Date),
        # INVOICE_CURRENCY for amounts (AD-8); NULL otherwise.
        sa.Column("currency", sa.Text),
        sa.Column("confidence", sa.Double),
        sa.Column("page", sa.Integer),
        # The first bounding region's points, for the admin crop.
        sa.Column("polygon", postgresql.JSONB),
        sa.Column("source", sa.Text, nullable=False),
        # AD-11: pgp_pub_encrypt of the normalised value, and its HMAC-SHA256.
        sa.Column("bank_ciphertext", sa.LargeBinary),
        sa.Column("bank_fingerprint", sa.Text),
        _created_at(),
        sa.CheckConstraint("btrim(field_id) <> ''", name="ck_invoice_field_field_id"),
        sa.CheckConstraint(_in("source", SOURCES), name="ck_invoice_field_source"),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_invoice_field_confidence",
        ),
        sa.CheckConstraint("page IS NULL OR page > 0", name="ck_invoice_field_page"),
        sa.CheckConstraint(
            "num_nonnulls(value_text, value_number, value_date, bank_ciphertext) <= 1",
            name="ck_invoice_field_one_value",
        ),
        sa.CheckConstraint(
            "(bank_ciphertext IS NULL) = (bank_fingerprint IS NULL)",
            name="ck_invoice_field_bank_pair",
        ),
        sa.CheckConstraint(
            "bank_fingerprint IS NULL OR bank_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_invoice_field_bank_fingerprint",
        ),
        # AD-11: a bank field never holds a plaintext value, and only a bank field
        # holds ciphertext.
        sa.CheckConstraint(
            f"NOT ({bank_field}) OR num_nonnulls(value_text, value_number, value_date) = 0",
            name="ck_invoice_field_bank_no_plaintext",
        ),
        sa.CheckConstraint(
            f"bank_ciphertext IS NULL OR {bank_field}",
            name="ck_invoice_field_bank_only",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_invoice_field_run", "invoice_field", ["run_id", "field_id"], schema=SCHEMA
    )

    op.create_table(
        "invoice_line",
        sa.Column("id", sa.Uuid, primary_key=True),
        _invoice_id(),
        _run_id(),
        sa.Column("line_no", sa.Integer, nullable=False),
        sa.Column("product_code", sa.Text),
        sa.Column("description", sa.Text),
        sa.Column("quantity", sa.Numeric),
        sa.Column("unit", sa.Text),
        sa.Column("unit_price", sa.Numeric),
        sa.Column("amount", sa.Numeric),
        sa.Column("tax", sa.Numeric),
        # The lowest of the line's checked fields (AD-18).
        sa.Column("confidence", sa.Double, nullable=False),
        # Filled by the validate stage (AD-19).
        sa.Column("po_line_id", sa.Uuid),
        sa.Column("material_id", sa.Uuid),
        sa.Column("source", sa.Text, nullable=False),
        _created_at(),
        sa.CheckConstraint("line_no > 0", name="ck_invoice_line_line_no"),
        sa.CheckConstraint(_in("source", SOURCES), name="ck_invoice_line_source"),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_invoice_line_confidence"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_invoice_line_run", "invoice_line", ["run_id", "line_no"], schema=SCHEMA
    )

    op.create_table(
        "di_usage",
        # The first day of the calendar month (UTC) the pages count against.
        sa.Column("month", sa.Date, primary_key=True),
        sa.Column("pages", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_call_at", _timestamp()),
        sa.CheckConstraint("pages >= 0", name="ck_di_usage_pages"),
        sa.CheckConstraint(
            "extract(day FROM month) = 1", name="ck_di_usage_month_start"
        ),
        schema=SCHEMA,
    )

    op.create_table(
        "di_operation",
        _invoice_id(primary_key=True),
        sa.Column("operation_location", sa.Text, nullable=False),
        _created_at(),
        sa.CheckConstraint(
            "operation_location LIKE 'https://%'",
            name="ck_di_operation_location",
        ),
        schema=SCHEMA,
    )

    pipeline, staff_api = _roles()
    for table, pipeline_privileges, staff_privileges in TABLE_GRANTS:
        target = f"{SCHEMA}.{table}"
        # Drop what 0001_intake's default privileges gave, then grant exactly this.
        for role in (pipeline, staff_api):
            op.execute(f"REVOKE ALL ON {target} FROM {role}")
        op.execute(f"GRANT {pipeline_privileges} ON {target} TO {pipeline}")
        if staff_privileges is not None:
            op.execute(f"GRANT {staff_privileges} ON {target} TO {staff_api}")


def downgrade() -> None:
    """Drops the five tables, and their grants with them. Needs the same `-x` role
    arguments as the upgrade (env.py requires them)."""
    for table, _, _ in reversed(TABLE_GRANTS):
        op.drop_table(table, schema=SCHEMA)
