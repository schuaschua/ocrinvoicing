"""The intake schema: invoices, status history, admin items and image hashes, with the
AD-11 grants (Story 2.1).

Revision ID: 0001_intake
Revises:
Create Date: 2026-09-29

Backward-compatible only (coding-style.md rule 29): add first, remove in a later
release. Grants use the role names from `-x` (env.py), never literals.

The value lists below are copies of the domain's at the time of writing, on purpose:
a migration is history and never changes when the application code does. A later
value (a new reason code) comes with a migration that widens the check.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision: str = "0001_intake"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "intake"

# domain/status.py InvoiceStatus (AD-3).
STATUSES = (
    "received",
    "awaiting_extraction",
    "extracting",
    "awaiting_validation",
    "validating",
    "ready_to_post",
    "posting",
    "posted",
    "in_admin_queue",
    "rejected",
)
# domain/reasons.py ReasonCode (AD-4).
REASONS = (
    "UNREADABLE",
    "UNSUPPORTED_DOCUMENT",
    "EXTRACTION_QUOTA",
    "LOW_CONFIDENCE",
    "PO_MISMATCH",
    "DUPLICATE",
    "DATE_MISMATCH",
    "NO_PHOTO_DATE",
    "BANK_CHANGED",
    "SUPPLIER_ID_MISMATCH",
    "ACCOUNTS_API_ERROR",
    "PROCESSING_FAILED",
)
# ports/intake.py IntakeSource and domain/upload.py UploadContentType, DeviceCheck (AD-5).
SOURCES = ("link", "goods_in")
CONTENT_TYPES = ("image/jpeg", "image/png", "application/pdf")
DEVICE_CHECKS = ("passed", "overridden")

# AD-11: `intake` is read/write for the pipeline and staff-api logins, at least
# privilege: nobody deletes, and history, admin items and hashes are append-only
# (security.md rule 32). Only the invoice row itself is updated (its status).
TABLE_GRANTS = {
    "invoice": "SELECT, INSERT, UPDATE",
    "status_history": "SELECT, INSERT",
    "admin_item": "SELECT, INSERT",
    "image_hash": "SELECT, INSERT",
}
# Tables a later migration adds; it narrows them further when they are append-only.
DEFAULT_GRANT = "SELECT, INSERT, UPDATE"


def _in(column: str, values: Sequence[str]) -> str:
    # Literals from the constants above only, never from input.
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _timestamp() -> sa.TIMESTAMP:
    return sa.TIMESTAMP(timezone=True)


def _roles() -> list[str]:
    """The logins to grant to, quoted as identifiers (env.py checked their shape)."""
    roles: dict[str, str] = context.config.attributes["roles"]
    quote = op.get_bind().dialect.identifier_preparer.quote_identifier
    return [quote(roles["pipeline_role"]), quote(roles["staff_api_role"])]


def upgrade() -> None:
    op.execute(sa.schema.CreateSchema(SCHEMA))

    op.create_table(
        "invoice",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("correlation_id", sa.Uuid, nullable=False),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("supplier_id", sa.Uuid, nullable=False),
        sa.Column("delivery_id", sa.Uuid),
        sa.Column("content_type", sa.Text, nullable=False),
        sa.Column("device_check", sa.Text, nullable=False),
        sa.Column("photo_taken_at", _timestamp()),
        sa.Column("po_number", sa.Text),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column(
            "status_changed_at",
            _timestamp(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("claimed_until", _timestamp()),
        sa.Column("next_attempt_at", _timestamp()),
        sa.Column("post_failures", sa.Integer, nullable=False, server_default="0"),
        sa.Column("accounts_ref", sa.Text),
        sa.Column("posted_at", _timestamp()),
        sa.Column(
            "created_at", _timestamp(), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(_in("status", STATUSES), name="ck_invoice_status"),
        sa.CheckConstraint(_in("source", SOURCES), name="ck_invoice_source"),
        sa.CheckConstraint(
            _in("content_type", CONTENT_TYPES), name="ck_invoice_content_type"
        ),
        sa.CheckConstraint(
            _in("device_check", DEVICE_CHECKS), name="ck_invoice_device_check"
        ),
        sa.CheckConstraint("post_failures >= 0", name="ck_invoice_post_failures"),
        # AD-5: a goods-in scan has its delivery; a supplier upload has none.
        sa.CheckConstraint(
            "(source = 'goods_in') = (delivery_id IS NOT NULL)",
            name="ck_invoice_delivery",
        ),
        schema=SCHEMA,
    )
    # The sweeper (AD-2) finds invoices by status and age.
    op.create_index(
        "ix_invoice_status_changed",
        "invoice",
        ["status", "status_changed_at"],
        schema=SCHEMA,
    )
    # Duplicate and PO checks compare one supplier's invoices (AD-9, AD-19).
    op.create_index("ix_invoice_supplier", "invoice", ["supplier_id"], schema=SCHEMA)

    op.create_table(
        "status_history",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column(
            "invoice_id", sa.Uuid, sa.ForeignKey(f"{SCHEMA}.invoice.id"), nullable=False
        ),
        # NULL on the row written when the invoice is created.
        sa.Column("from_status", sa.Text),
        sa.Column("to_status", sa.Text, nullable=False),
        sa.Column("actor", sa.Text, nullable=False),
        sa.Column("at", _timestamp(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            f"from_status IS NULL OR {_in('from_status', STATUSES)}",
            name="ck_status_history_from",
        ),
        sa.CheckConstraint(_in("to_status", STATUSES), name="ck_status_history_to"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_status_history_invoice",
        "status_history",
        ["invoice_id", "at"],
        schema=SCHEMA,
    )

    op.create_table(
        "admin_item",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column(
            "invoice_id", sa.Uuid, sa.ForeignKey(f"{SCHEMA}.invoice.id"), nullable=False
        ),
        sa.Column("routing_id", sa.Uuid, nullable=False),
        # The extraction run the reason is about (AD-18); its table arrives with 2.3.
        sa.Column("run_id", sa.Uuid),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column(
            "field_ids",
            postgresql.ARRAY(sa.Text),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "detail",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at", _timestamp(), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(_in("reason", REASONS), name="ck_admin_item_reason"),
        schema=SCHEMA,
    )
    # Open reasons are the items of an invoice's latest routing_id (AD-4).
    op.create_index(
        "ix_admin_item_invoice_routing",
        "admin_item",
        ["invoice_id", "routing_id"],
        schema=SCHEMA,
    )

    op.create_table(
        "image_hash",
        sa.Column(
            "invoice_id",
            sa.Uuid,
            sa.ForeignKey(f"{SCHEMA}.invoice.id"),
            primary_key=True,
        ),
        # 64-bit phash (AD-9), stored as a signed bigint with the same bits.
        sa.Column("phash", sa.BigInteger, nullable=False),
        sa.Column(
            "created_at", _timestamp(), nullable=False, server_default=sa.func.now()
        ),
        schema=SCHEMA,
    )

    for role in _roles():
        op.execute(f"GRANT USAGE ON SCHEMA {SCHEMA} TO {role}")
        for table, privileges in TABLE_GRANTS.items():
            op.execute(f"GRANT {privileges} ON {SCHEMA}.{table} TO {role}")
        op.execute(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA {SCHEMA} GRANT {DEFAULT_GRANT} ON TABLES TO {role}"
        )


def downgrade() -> None:
    """Revokes exactly what `upgrade` granted, then drops the schema. Needs the same
    `-x pipeline_role=... -x staff_api_role=...` as the upgrade (env.py requires them)."""
    for role in _roles():
        op.execute(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA {SCHEMA} REVOKE {DEFAULT_GRANT} ON TABLES FROM {role}"
        )
        for table, privileges in TABLE_GRANTS.items():
            op.execute(f"REVOKE {privileges} ON {SCHEMA}.{table} FROM {role}")
        op.execute(f"REVOKE USAGE ON SCHEMA {SCHEMA} FROM {role}")
    op.drop_table("image_hash", schema=SCHEMA)
    op.drop_table("admin_item", schema=SCHEMA)
    op.drop_table("status_history", schema=SCHEMA)
    op.drop_table("invoice", schema=SCHEMA)
    op.execute(sa.schema.DropSchema(SCHEMA))
