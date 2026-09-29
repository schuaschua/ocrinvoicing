"""The supplier master and the audit log, with the AD-11 grants (Story 1.6).

Revision ID: 0004_master_audit
Revises: 0003_device_check_skipped
Create Date: 2026-09-29

Backward-compatible only (coding-style.md rule 29): two new schemas, nothing changed.

- `master.supplier{id, name, tax_id, phone}` and `master.supplier_bank{supplier_id,
  field_id, ciphertext, fingerprint}`, one bank row per AD-18 bank field id. Written
  only by the supplier load script, as Dj's login (`-x dj_role`).
- `audit.event(id, at, actor, action, entity, entity_id, detail)`: append-only
  (security.md rule 32). Every writer may INSERT every column but `at` and `actor`
  (their defaults always apply), staff-api may also SELECT, and nobody may UPDATE or
  DELETE. Downgrade is refused while it holds rows.

The pipeline login reads every `supplier_bank` column except `ciphertext` (a
column-level grant), so only staff-api, which alone holds the private key, ever reads
ciphertext. Neither schema sets default privileges: a later table gets its grants
explicitly, so it can never hand the pipeline a new ciphertext column by default.

`pgcrypto` (`pgp_pub_encrypt`, allow-listed on the server by Terraform) is created by
the operator database step as the server admin (infra/bootstrap/database-step5.sql);
`CREATE EXTENSION IF NOT EXISTS` here is then a no-op, and covers a server where the
owner may create it. Downgrade leaves the extension: it is the database's, not this
revision's.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision: str = "0004_master_audit"
down_revision: str | Sequence[str] | None = "0003_device_check_skipped"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MASTER = "master"
AUDIT = "audit"

# domain/suppliers.py BANK_FIELD_IDS (AD-18), copied on purpose (see 0001_intake).
BANK_FIELD_IDS = ("bank_account_number", "iban", "swift")
# Every supplier_bank column but `ciphertext`: what the pipeline may read (AD-11).
BANK_COLUMNS_WITHOUT_CIPHERTEXT = ("supplier_id", "field_id", "fingerprint")
# The audit.event columns a writer may set: never `at` or `actor`, whose defaults
# (now(), current_user) therefore always apply, so no login can forge them.
AUDIT_INSERT_COLUMNS = ("id", "action", "entity", "entity_id", "detail")


def _in(column: str, values: Sequence[str]) -> str:
    # Literals from the constants above only, never from input.
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _grants() -> list[tuple[str, str, str]]:
    """(privileges, object, login) for every grant, in upgrade order. Logins come
    from `-x` (env.py checked their shape) and are quoted as identifiers."""
    roles: dict[str, str] = context.config.attributes["roles"]
    quote = op.get_bind().dialect.identifier_preparer.quote_identifier
    pipeline = quote(roles["pipeline_role"])
    staff_api = quote(roles["staff_api_role"])
    dj = quote(roles["dj_role"])
    bank_columns = ", ".join(BANK_COLUMNS_WITHOUT_CIPHERTEXT)
    insert_audit = f"INSERT ({', '.join(AUDIT_INSERT_COLUMNS)})"
    return [
        # master: read/write for the load script (no DELETE: it never removes one).
        ("USAGE", f"SCHEMA {MASTER}", dj),
        ("SELECT, INSERT, UPDATE", f"{MASTER}.supplier", dj),
        ("SELECT, INSERT, UPDATE", f"{MASTER}.supplier_bank", dj),
        # master: staff-api reads everything, ciphertext included.
        ("USAGE", f"SCHEMA {MASTER}", staff_api),
        ("SELECT", f"{MASTER}.supplier", staff_api),
        ("SELECT", f"{MASTER}.supplier_bank", staff_api),
        # master: the pipeline reads everything except the ciphertext column.
        ("USAGE", f"SCHEMA {MASTER}", pipeline),
        ("SELECT", f"{MASTER}.supplier", pipeline),
        (f"SELECT ({bank_columns})", f"{MASTER}.supplier_bank", pipeline),
        # audit: INSERT for every login that writes it, SELECT for staff-api only.
        ("USAGE", f"SCHEMA {AUDIT}", dj),
        (insert_audit, f"{AUDIT}.event", dj),
        ("USAGE", f"SCHEMA {AUDIT}", pipeline),
        (insert_audit, f"{AUDIT}.event", pipeline),
        ("USAGE", f"SCHEMA {AUDIT}", staff_api),
        ("SELECT", f"{AUDIT}.event", staff_api),
        (insert_audit, f"{AUDIT}.event", staff_api),
    ]


def _timestamp() -> sa.TIMESTAMP:
    return sa.TIMESTAMP(timezone=True)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute(sa.schema.CreateSchema(MASTER))
    op.execute(sa.schema.CreateSchema(AUDIT))

    op.create_table(
        "supplier",
        # The same ids as the purchasing seed (backend/seed/sim_purchasing.json).
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        # AD-19 compares it with the printed tax id.
        sa.Column("tax_id", sa.Text),
        sa.Column("phone", sa.Text),
        sa.CheckConstraint("btrim(name) <> ''", name="ck_supplier_name"),
        schema=MASTER,
    )

    op.create_table(
        "supplier_bank",
        sa.Column(
            "supplier_id",
            sa.Uuid,
            sa.ForeignKey(f"{MASTER}.supplier.id"),
            primary_key=True,
        ),
        sa.Column("field_id", sa.Text, primary_key=True),
        # pgp_pub_encrypt output; only staff-api can decrypt it (AD-11).
        sa.Column("ciphertext", sa.LargeBinary, nullable=False),
        # HMAC-SHA256 of the normalised value, lowercase hex (AD-11).
        sa.Column("fingerprint", sa.Text, nullable=False),
        sa.CheckConstraint(
            _in("field_id", BANK_FIELD_IDS), name="ck_supplier_bank_field_id"
        ),
        sa.CheckConstraint(
            "fingerprint ~ '^[0-9a-f]{64}$'", name="ck_supplier_bank_fingerprint"
        ),
        schema=MASTER,
    )

    op.create_table(
        "event",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("at", _timestamp(), nullable=False, server_default=sa.func.now()),
        # The database login that wrote the row, whatever the writer passes.
        sa.Column(
            "actor", sa.Text, nullable=False, server_default=sa.text("current_user")
        ),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("entity", sa.Text, nullable=False),
        sa.Column("entity_id", sa.Text, nullable=False),
        # Ids and field ids only, never values (AD-11).
        sa.Column(
            "detail",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        schema=AUDIT,
    )
    op.create_index(
        "ix_event_entity", "event", ["entity", "entity_id", "at"], schema=AUDIT
    )

    for privileges, target, role in _grants():
        op.execute(f"GRANT {privileges} ON {target} TO {role}")


def downgrade() -> None:
    """Revokes exactly what `upgrade` granted, then drops both schemas. Needs the same
    `-x` role arguments as the upgrade (env.py requires them). Refused while
    `audit.event` holds rows: the audit log is append-only (security.md rule 32), and
    a downgrade must never be the way to delete it."""
    held = op.get_bind().execute(sa.text("SELECT count(*) FROM audit.event")).scalar()
    if held:
        raise RuntimeError(
            f"refusing to downgrade 0004_master_audit: {AUDIT}.event holds {held}"
            " row(s), and the audit log is append-only; export and remove it by hand"
            " first if this is really intended"
        )
    for privileges, target, role in reversed(_grants()):
        op.execute(f"REVOKE {privileges} ON {target} FROM {role}")
    op.drop_index("ix_event_entity", "event", schema=AUDIT)
    op.drop_table("event", schema=AUDIT)
    op.drop_table("supplier_bank", schema=MASTER)
    op.drop_table("supplier", schema=MASTER)
    op.execute(sa.schema.DropSchema(AUDIT))
    op.execute(sa.schema.DropSchema(MASTER))
