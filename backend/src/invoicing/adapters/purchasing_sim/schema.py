"""SQLAlchemy Core tables of the `sim_purchasing` schema, as migration
0002_sim_purchasing creates them. Used for building statements only, never for
creating tables (AD-17)."""

from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    ForeignKey,
    Integer,
    MetaData,
    Numeric,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
)

SCHEMA = "sim_purchasing"

metadata = MetaData(schema=SCHEMA)


def _money() -> Numeric[Decimal]:
    return Numeric(18, 2, asdecimal=True)


def _quantity() -> Numeric[Decimal]:
    return Numeric(18, 3, asdecimal=True)


# Purchasing owns materials (AD-10). `code` is the seed's natural key.
material = Table(
    "material",
    metadata,
    Column("material_id", Uuid, primary_key=True),
    Column("code", Text, nullable=False),
    Column("name", Text, nullable=False),
    UniqueConstraint("code", name="uq_material_code"),
)

purchase_order = Table(
    "purchase_order",
    metadata,
    Column("po_number", Text, primary_key=True),
    Column("supplier_id", Uuid, nullable=False),
    Column("order_date", Date, nullable=False),
)

# Natural key (po_number, line_no).
po_line = Table(
    "po_line",
    metadata,
    Column("po_line_id", Uuid, primary_key=True),
    Column(
        "po_number",
        Text,
        ForeignKey(f"{SCHEMA}.purchase_order.po_number"),
        nullable=False,
    ),
    Column("line_no", Integer, nullable=False),
    Column(
        "material_id",
        Uuid,
        ForeignKey(f"{SCHEMA}.material.material_id"),
        nullable=False,
    ),
    Column("supplier_product_code", Text, nullable=False),
    Column("unit_price", _money(), nullable=False),
    Column("quantity", _quantity(), nullable=False),
    Column("expected_date", Date, nullable=False),
    UniqueConstraint("po_number", "line_no", name="uq_po_line_number"),
    CheckConstraint("line_no > 0", name="ck_po_line_line_no"),
    CheckConstraint("unit_price >= 0", name="ck_po_line_unit_price"),
    CheckConstraint("quantity > 0", name="ck_po_line_quantity"),
)

# Natural key (po_number, delivery_no). The supplier is the PO's.
delivery = Table(
    "delivery",
    metadata,
    Column("delivery_id", Uuid, primary_key=True),
    Column(
        "po_number",
        Text,
        ForeignKey(f"{SCHEMA}.purchase_order.po_number"),
        nullable=False,
    ),
    Column("delivery_no", Integer, nullable=False),
    Column("delivery_date", Date, nullable=False),
    UniqueConstraint("po_number", "delivery_no", name="uq_delivery_number"),
    CheckConstraint("delivery_no > 0", name="ck_delivery_delivery_no"),
)

# At most one per delivery (natural key delivery_id).
goods_receipt = Table(
    "goods_receipt",
    metadata,
    Column("receipt_id", Uuid, primary_key=True),
    Column(
        "delivery_id",
        Uuid,
        ForeignKey(f"{SCHEMA}.delivery.delivery_id"),
        nullable=False,
    ),
    Column("received_date", Date, nullable=False),
    UniqueConstraint("delivery_id", name="uq_goods_receipt_delivery"),
)

goods_receipt_line = Table(
    "goods_receipt_line",
    metadata,
    Column(
        "receipt_id",
        Uuid,
        ForeignKey(f"{SCHEMA}.goods_receipt.receipt_id"),
        primary_key=True,
    ),
    Column(
        "po_line_id", Uuid, ForeignKey(f"{SCHEMA}.po_line.po_line_id"), primary_key=True
    ),
    Column("quantity", _quantity(), nullable=False),
    CheckConstraint("quantity > 0", name="ck_goods_receipt_line_quantity"),
)
