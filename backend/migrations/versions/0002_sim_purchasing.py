"""The purchasing simulation: materials, purchase orders, PO lines, deliveries and goods
receipts, read-only for the app logins (Story 2.4, AD-10, AD-11).

Revision ID: 0002_sim_purchasing
Revises: 0001_intake
Create Date: 2026-09-29

Backward-compatible only (coding-style.md rule 29): a new schema, nothing changed.
The app logins get SELECT only; the rows are written by the operator seed
(`python -m invoicing.tools.seed_purchasing`), run as the deploy identity that owns
the schema. Supplier ids have no foreign key to `master`: the simulation stands in
for another system, which only shares the ids (Story 1.6 maps them).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0002_sim_purchasing"
down_revision: str | Sequence[str] | None = "0001_intake"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "sim_purchasing"
TABLES = (
    "material",
    "purchase_order",
    "po_line",
    "delivery",
    "goods_receipt",
    "goods_receipt_line",
)
# AD-11: `sim_purchasing` read for the pipeline and staff-api logins, nothing more.
GRANT = "SELECT"


def _money() -> sa.Numeric:
    # Spine conventions: money is numeric(18,2), read back as Decimal.
    return sa.Numeric(18, 2, asdecimal=True)


def _quantity() -> sa.Numeric:
    return sa.Numeric(18, 3, asdecimal=True)


def _roles() -> list[str]:
    """The logins to grant to, quoted as identifiers (env.py checked their shape)."""
    roles: dict[str, str] = context.config.attributes["roles"]
    quote = op.get_bind().dialect.identifier_preparer.quote_identifier
    return [quote(roles["pipeline_role"]), quote(roles["staff_api_role"])]


def upgrade() -> None:
    op.execute(sa.schema.CreateSchema(SCHEMA))

    # Purchasing owns materials (AD-10); they never live in `master`.
    op.create_table(
        "material",
        sa.Column("material_id", sa.Uuid, primary_key=True),
        sa.Column("code", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.UniqueConstraint("code", name="uq_material_code"),
        schema=SCHEMA,
    )

    op.create_table(
        "purchase_order",
        sa.Column("po_number", sa.Text, primary_key=True),
        sa.Column("supplier_id", sa.Uuid, nullable=False),
        sa.Column("order_date", sa.Date, nullable=False),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_purchase_order_supplier", "purchase_order", ["supplier_id"], schema=SCHEMA
    )

    op.create_table(
        "po_line",
        sa.Column("po_line_id", sa.Uuid, primary_key=True),
        sa.Column(
            "po_number",
            sa.Text,
            sa.ForeignKey(f"{SCHEMA}.purchase_order.po_number"),
            nullable=False,
        ),
        sa.Column("line_no", sa.Integer, nullable=False),
        sa.Column(
            "material_id",
            sa.Uuid,
            sa.ForeignKey(f"{SCHEMA}.material.material_id"),
            nullable=False,
        ),
        sa.Column("supplier_product_code", sa.Text, nullable=False),
        sa.Column("unit_price", _money(), nullable=False),
        sa.Column("quantity", _quantity(), nullable=False),
        sa.Column("expected_date", sa.Date, nullable=False),
        sa.UniqueConstraint("po_number", "line_no", name="uq_po_line_number"),
        sa.CheckConstraint("line_no > 0", name="ck_po_line_line_no"),
        sa.CheckConstraint("unit_price >= 0", name="ck_po_line_unit_price"),
        sa.CheckConstraint("quantity > 0", name="ck_po_line_quantity"),
        schema=SCHEMA,
    )
    # Analytics and alternatives look lines up by material (AD-20).
    op.create_index("ix_po_line_material", "po_line", ["material_id"], schema=SCHEMA)

    op.create_table(
        "delivery",
        sa.Column("delivery_id", sa.Uuid, primary_key=True),
        sa.Column(
            "po_number",
            sa.Text,
            sa.ForeignKey(f"{SCHEMA}.purchase_order.po_number"),
            nullable=False,
        ),
        sa.Column("delivery_no", sa.Integer, nullable=False),
        sa.Column("delivery_date", sa.Date, nullable=False),
        sa.UniqueConstraint("po_number", "delivery_no", name="uq_delivery_number"),
        sa.CheckConstraint("delivery_no > 0", name="ck_delivery_delivery_no"),
        schema=SCHEMA,
    )

    # One goods receipt per delivery, once the goods are checked in.
    op.create_table(
        "goods_receipt",
        sa.Column("receipt_id", sa.Uuid, primary_key=True),
        sa.Column(
            "delivery_id",
            sa.Uuid,
            sa.ForeignKey(f"{SCHEMA}.delivery.delivery_id"),
            nullable=False,
        ),
        sa.Column("received_date", sa.Date, nullable=False),
        sa.UniqueConstraint("delivery_id", name="uq_goods_receipt_delivery"),
        schema=SCHEMA,
    )

    op.create_table(
        "goods_receipt_line",
        sa.Column(
            "receipt_id",
            sa.Uuid,
            sa.ForeignKey(f"{SCHEMA}.goods_receipt.receipt_id"),
            primary_key=True,
        ),
        sa.Column(
            "po_line_id",
            sa.Uuid,
            sa.ForeignKey(f"{SCHEMA}.po_line.po_line_id"),
            primary_key=True,
        ),
        sa.Column("quantity", _quantity(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_goods_receipt_line_quantity"),
        schema=SCHEMA,
    )
    # Quantity received per PO line (AD-19, AD-20).
    op.create_index(
        "ix_goods_receipt_line_po_line",
        "goods_receipt_line",
        ["po_line_id"],
        schema=SCHEMA,
    )

    for role in _roles():
        op.execute(f"GRANT USAGE ON SCHEMA {SCHEMA} TO {role}")
        for table in TABLES:
            op.execute(f"GRANT {GRANT} ON {SCHEMA}.{table} TO {role}")
        op.execute(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA {SCHEMA} GRANT {GRANT} ON TABLES TO {role}"
        )


def downgrade() -> None:
    """Revokes exactly what `upgrade` granted, then drops the schema. Needs the same
    `-x pipeline_role=... -x staff_api_role=...` as the upgrade (env.py requires them)."""
    for role in _roles():
        op.execute(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA {SCHEMA} REVOKE {GRANT} ON TABLES FROM {role}"
        )
        for table in TABLES:
            op.execute(f"REVOKE {GRANT} ON {SCHEMA}.{table} FROM {role}")
        op.execute(f"REVOKE USAGE ON SCHEMA {SCHEMA} FROM {role}")
    for table in reversed(TABLES):
        op.drop_table(table, schema=SCHEMA)
    op.execute(sa.schema.DropSchema(SCHEMA))
