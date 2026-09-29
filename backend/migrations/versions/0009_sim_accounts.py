"""The accounts simulation's store: posted invoices and the failure mode, read and
written by the accounts-sim login only (Story 3.1, AD-10, AD-11).

Revision ID: 0009_sim_accounts
Revises: 0008_extraction_pages
Create Date: 2026-09-30

Backward-compatible only (coding-style.md rule 29): a new schema, nothing changed.

- `invoice`: one row per `invoice_id` (unique: a repeat post returns the stored
  `accounts_ref`, AD-10). `accounts_ref` is `SIM-` and a sequence number of at least 6 digits. The
  document is the XML as received; there is no bank data in the contract or here.
- `failure_mode`: one row (id 1). While `fail_next` > 0, each call answers `status`
  and decrements it, so posting retries can be tested end to end (Story 3.1). Set by
  the operator, as the accounts-sim login or the deploy identity.

The accounts-sim login gets SELECT and INSERT on `invoice` (no UPDATE or DELETE: a
posted invoice is never changed), the sequence's USAGE, and SELECT and UPDATE on
`failure_mode`. No other login gets anything on the schema.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0009_sim_accounts"
down_revision: str | Sequence[str] | None = "0008_extraction_pages"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "sim_accounts"
REF_SEQUENCE = "accounts_ref_seq"
GRANTS = (
    ("TABLE", "invoice", "SELECT, INSERT"),
    ("TABLE", "failure_mode", "SELECT, UPDATE"),
    ("SEQUENCE", REF_SEQUENCE, "USAGE"),
)


def _accounts_sim() -> str:
    """The accounts-sim login, quoted as an identifier (env.py checked its shape)."""
    roles: dict[str, str] = context.config.attributes["roles"]
    quote = op.get_bind().dialect.identifier_preparer.quote_identifier
    return quote(roles["accounts_sim_role"])


def upgrade() -> None:
    op.execute(sa.schema.CreateSchema(SCHEMA))
    op.execute(sa.schema.CreateSequence(sa.Sequence(REF_SEQUENCE, schema=SCHEMA)))

    op.create_table(
        "invoice",
        sa.Column(
            "accounts_ref",
            sa.Text,
            primary_key=True,
            # At least 6 digits, zero-padded, and never truncated: past 999999 it
            # widens (lpad would cut it, to_char would print ######). nextval is
            # evaluated once, so the pad is done by stripping surplus zeros.
            server_default=sa.text(
                "'SIM-' || regexp_replace('00000' || "
                f"nextval('{SCHEMA}.{REF_SEQUENCE}')::text, '^0*([0-9]{{6,}})$', '\\1')"
            ),
        ),
        sa.Column("invoice_id", sa.Uuid, nullable=False),
        sa.Column("supplier_id", sa.Uuid, nullable=False),
        sa.Column("invoice_number", sa.Text, nullable=False),
        # Spine conventions: money is numeric(18,2), read back as Decimal.
        sa.Column("invoice_total", sa.Numeric(18, 2, asdecimal=True), nullable=False),
        sa.Column("document", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("invoice_id", name="uq_sim_accounts_invoice_invoice_id"),
        schema=SCHEMA,
    )

    op.create_table(
        "failure_mode",
        sa.Column("id", sa.SmallInteger, primary_key=True),
        sa.Column("fail_next", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.Integer, nullable=False, server_default="503"),
        sa.CheckConstraint("id = 1", name="ck_failure_mode_one_row"),
        sa.CheckConstraint("fail_next >= 0", name="ck_failure_mode_fail_next"),
        sa.CheckConstraint("status BETWEEN 400 AND 599", name="ck_failure_mode_status"),
        schema=SCHEMA,
    )
    # The one row, off: fail_next 0 (its defaults).
    op.execute(
        sa.table("failure_mode", sa.column("id"), schema=SCHEMA).insert().values(id=1)
    )

    role = _accounts_sim()
    op.execute(f"GRANT USAGE ON SCHEMA {SCHEMA} TO {role}")
    for kind, name, privileges in GRANTS:
        op.execute(f"GRANT {privileges} ON {kind} {SCHEMA}.{name} TO {role}")


def downgrade() -> None:
    """Drops the schema, and its grants with it. Needs the same `-x` role arguments as
    the upgrade (env.py requires them)."""
    op.drop_table("failure_mode", schema=SCHEMA)
    op.drop_table("invoice", schema=SCHEMA)
    op.execute(sa.schema.DropSequence(sa.Sequence(REF_SEQUENCE, schema=SCHEMA)))
    op.execute(f"REVOKE USAGE ON SCHEMA {SCHEMA} FROM {_accounts_sim()}")
    op.execute(sa.schema.DropSchema(SCHEMA))
