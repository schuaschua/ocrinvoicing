"""The purchasing simulation's seed (Story 2.4, CAP-20): synthetic POs, lines,
materials, deliveries and goods receipts from a JSON file, upserted by natural key so
running it again changes nothing.

Only the operator runs it (`python -m invoicing.tools.seed_purchasing`), as the
deploy identity that owns the schema: the app logins can't write here (AD-11).
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from sqlalchemy import Connection, Select, select
from sqlalchemy.dialects.postgresql import insert

from invoicing.adapters.purchasing_sim.schema import (
    delivery,
    goods_receipt,
    goods_receipt_line,
    material,
    po_line,
    purchase_order,
)

# backend/seed/, next to src/: the operator runs the seed from a checkout.
DEFAULT_SEED_FILE = Path(__file__).resolve().parents[4] / "seed" / "sim_purchasing.json"

Code = Annotated[
    str, StringConstraints(min_length=1, max_length=64, strip_whitespace=True)
]
Money = Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=2)]
Quantity = Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=3)]


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SeedSupplier(_Model):
    """A supplier id the POs may use; the name is only a label for the reader."""

    supplier_id: UUID
    name: str


class SeedMaterial(_Model):
    material_id: UUID
    code: Code
    name: Annotated[str, StringConstraints(min_length=1)]


class SeedLine(_Model):
    po_line_id: UUID
    line_no: int = Field(gt=0)
    material_code: Code
    supplier_product_code: Code
    unit_price: Money
    quantity: Quantity
    expected_date: date


class SeedReceipt(_Model):
    receipt_id: UUID
    received_date: date
    # Received quantity per PO line number.
    lines: dict[int, Quantity] = Field(min_length=1)


class SeedDelivery(_Model):
    delivery_id: UUID
    delivery_no: int = Field(gt=0)
    delivery_date: date
    receipt: SeedReceipt | None = None


class SeedPurchaseOrder(_Model):
    po_number: Code
    supplier_id: UUID
    order_date: date
    lines: tuple[SeedLine, ...] = Field(min_length=1)
    deliveries: tuple[SeedDelivery, ...] = ()

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        line_nos = [line.line_no for line in self.lines]
        if len(set(line_nos)) != len(line_nos):
            raise ValueError(f"{self.po_number}: line numbers repeat")
        delivery_nos = [d.delivery_no for d in self.deliveries]
        if len(set(delivery_nos)) != len(delivery_nos):
            raise ValueError(f"{self.po_number}: delivery numbers repeat")
        # A receipt names its lines by this PO's line numbers, so every received
        # po_line_id belongs to the delivery's PO by construction.
        ordered = {line.line_no: line.quantity for line in self.lines}
        received = dict.fromkeys(ordered, Decimal(0))
        for line in self.lines:
            if line.expected_date < self.order_date:
                raise ValueError(
                    f"{self.po_number}: a line is expected before the order"
                )
        for item in self.deliveries:
            if item.delivery_date < self.order_date:
                raise ValueError(f"{self.po_number}: a delivery is before the order")
            if item.receipt is None:
                continue
            if not set(item.receipt.lines) <= set(ordered):
                raise ValueError(
                    f"{self.po_number}: a receipt names a line the PO does not have"
                )
            if item.receipt.received_date < item.delivery_date:
                raise ValueError(f"{self.po_number}: a receipt is before its delivery")
            for line_no, quantity in item.receipt.lines.items():
                received[line_no] += quantity
        if any(received[n] > ordered[n] for n in ordered):
            raise ValueError(f"{self.po_number}: more received than ordered on a line")
        return self


class PurchasingSeed(_Model):
    """The whole seed file."""

    about: str = ""
    suppliers: tuple[SeedSupplier, ...] = Field(min_length=1)
    materials: tuple[SeedMaterial, ...] = Field(min_length=1)
    purchase_orders: tuple[SeedPurchaseOrder, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _references(self) -> Self:
        suppliers = {s.supplier_id for s in self.suppliers}
        codes = [m.code for m in self.materials]
        if len(set(codes)) != len(codes):
            raise ValueError("material codes repeat")
        po_numbers = [po.po_number for po in self.purchase_orders]
        if len(set(po_numbers)) != len(po_numbers):
            raise ValueError("PO numbers repeat")
        ids = [m.material_id for m in self.materials]
        for po in self.purchase_orders:
            if po.supplier_id not in suppliers:
                raise ValueError(f"{po.po_number}: supplier is not in `suppliers`")
            for line in po.lines:
                if line.material_code not in codes:
                    raise ValueError(f"{po.po_number}: unknown material code")
                ids.append(line.po_line_id)
            for item in po.deliveries:
                ids.append(item.delivery_id)
                if item.receipt is not None:
                    ids.append(item.receipt.receipt_id)
        if len(set(ids)) != len(ids):
            raise ValueError("ids repeat")
        return self


def load_seed(path: Path = DEFAULT_SEED_FILE) -> PurchasingSeed:
    """Parse and check a seed file (pydantic `ValidationError` when it is invalid)."""
    return PurchasingSeed.model_validate_json(path.read_bytes())


@dataclass(frozen=True)
class SeedResult:
    """Rows upserted per table, and rows in the database the file doesn't hold
    (left as they are: the seed never deletes)."""

    written: dict[str, int]
    not_in_file: dict[str, int]


def _id_conflicts(connection: Connection, data: PurchasingSeed) -> None:
    """ValueError naming the first id in `data` that the database already holds
    under another natural key (it would break the upsert with a key violation)."""
    materials: dict[UUID, tuple[object, ...]] = {
        m.material_id: (m.code,) for m in data.materials
    }
    lines: dict[UUID, tuple[object, ...]] = {
        line.po_line_id: (po.po_number, line.line_no)
        for po in data.purchase_orders
        for line in po.lines
    }
    deliveries: dict[UUID, tuple[object, ...]] = {
        d.delivery_id: (po.po_number, d.delivery_no)
        for po in data.purchase_orders
        for d in po.deliveries
    }
    receipts: dict[UUID, tuple[object, ...]] = {
        d.receipt.receipt_id: (po.po_number, d.delivery_no)
        for po in data.purchase_orders
        for d in po.deliveries
        if d.receipt is not None
    }
    checks: list[tuple[str, dict[UUID, tuple[object, ...]], Select[Any]]] = [
        ("material", materials, select(material.c.material_id, material.c.code)),
        (
            "PO line",
            lines,
            select(po_line.c.po_line_id, po_line.c.po_number, po_line.c.line_no),
        ),
        (
            "delivery",
            deliveries,
            select(
                delivery.c.delivery_id, delivery.c.po_number, delivery.c.delivery_no
            ),
        ),
        (
            "receipt",
            receipts,
            select(
                goods_receipt.c.receipt_id, delivery.c.po_number, delivery.c.delivery_no
            ).join(delivery, delivery.c.delivery_id == goods_receipt.c.delivery_id),
        ),
    ]
    for kind, expected, query in checks:
        id_column = query.selected_columns[0]
        for row in connection.execute(query.where(id_column.in_(list(expected)))):
            if tuple(row[1:]) != expected[row[0]]:
                raise ValueError(
                    f"{kind} id {row[0]} is already stored under another natural key"
                )


def _keys(connection: Connection, query: Select[Any]) -> set[tuple[object, ...]]:
    return {tuple(row) for row in connection.execute(query)}


def seed(connection: Connection, data: PurchasingSeed) -> SeedResult:
    """Upsert `data` by natural key (material code, PO number, PO and line number,
    PO and delivery number, delivery, receipt and PO line) in the caller's
    transaction. Existing ids are kept, so running it twice changes nothing. An id
    already stored under another natural key raises ValueError before any write."""
    _id_conflicts(connection, data)
    counts = dict.fromkeys(
        (
            table.name
            for table in (
                material,
                purchase_order,
                po_line,
                delivery,
                goods_receipt,
                goods_receipt_line,
            )
        ),
        0,
    )
    material_ids: dict[str, UUID] = {}
    for known in data.materials:
        statement = insert(material).values(
            material_id=known.material_id, code=known.code, name=known.name
        )
        material_ids[known.code] = connection.execute(
            statement.on_conflict_do_update(
                index_elements=[material.c.code],
                set_={"name": statement.excluded.name},
            ).returning(material.c.material_id)
        ).scalar_one()
        counts["material"] += 1

    for po in data.purchase_orders:
        statement = insert(purchase_order).values(
            po_number=po.po_number, supplier_id=po.supplier_id, order_date=po.order_date
        )
        connection.execute(
            statement.on_conflict_do_update(
                index_elements=[purchase_order.c.po_number],
                set_={
                    "supplier_id": statement.excluded.supplier_id,
                    "order_date": statement.excluded.order_date,
                },
            )
        )
        counts["purchase_order"] += 1

        line_ids: dict[int, UUID] = {}
        for line in po.lines:
            statement = insert(po_line).values(
                po_line_id=line.po_line_id,
                po_number=po.po_number,
                line_no=line.line_no,
                material_id=material_ids[line.material_code],
                supplier_product_code=line.supplier_product_code,
                unit_price=line.unit_price,
                quantity=line.quantity,
                expected_date=line.expected_date,
            )
            line_ids[line.line_no] = connection.execute(
                statement.on_conflict_do_update(
                    index_elements=[po_line.c.po_number, po_line.c.line_no],
                    set_={
                        name: statement.excluded[name]
                        for name in (
                            "material_id",
                            "supplier_product_code",
                            "unit_price",
                            "quantity",
                            "expected_date",
                        )
                    },
                ).returning(po_line.c.po_line_id)
            ).scalar_one()
            counts["po_line"] += 1

        for item in po.deliveries:
            statement = insert(delivery).values(
                delivery_id=item.delivery_id,
                po_number=po.po_number,
                delivery_no=item.delivery_no,
                delivery_date=item.delivery_date,
            )
            delivery_id: UUID = connection.execute(
                statement.on_conflict_do_update(
                    index_elements=[delivery.c.po_number, delivery.c.delivery_no],
                    set_={"delivery_date": statement.excluded.delivery_date},
                ).returning(delivery.c.delivery_id)
            ).scalar_one()
            counts["delivery"] += 1
            if item.receipt is None:
                continue
            statement = insert(goods_receipt).values(
                receipt_id=item.receipt.receipt_id,
                delivery_id=delivery_id,
                received_date=item.receipt.received_date,
            )
            receipt_id: UUID = connection.execute(
                statement.on_conflict_do_update(
                    index_elements=[goods_receipt.c.delivery_id],
                    set_={"received_date": statement.excluded.received_date},
                ).returning(goods_receipt.c.receipt_id)
            ).scalar_one()
            counts["goods_receipt"] += 1
            for line_no, quantity in item.receipt.lines.items():
                statement = insert(goods_receipt_line).values(
                    receipt_id=receipt_id,
                    po_line_id=line_ids[line_no],
                    quantity=quantity,
                )
                connection.execute(
                    statement.on_conflict_do_update(
                        index_elements=[
                            goods_receipt_line.c.receipt_id,
                            goods_receipt_line.c.po_line_id,
                        ],
                        set_={"quantity": statement.excluded.quantity},
                    )
                )
                counts["goods_receipt_line"] += 1
    return SeedResult(written=counts, not_in_file=_not_in_file(connection, data))


def _not_in_file(connection: Connection, data: PurchasingSeed) -> dict[str, int]:
    """Per table, the rows whose natural key the file doesn't hold."""
    pos = data.purchase_orders
    received = [(po, d, d.receipt) for po in pos for d in po.deliveries if d.receipt]
    in_file: dict[str, set[tuple[object, ...]]] = {
        "material": {(m.code,) for m in data.materials},
        "purchase_order": {(po.po_number,) for po in pos},
        "po_line": {(po.po_number, line.line_no) for po in pos for line in po.lines},
        "delivery": {
            (po.po_number, d.delivery_no) for po in pos for d in po.deliveries
        },
        "goods_receipt": {(po.po_number, d.delivery_no) for po, d, _ in received},
        "goods_receipt_line": {
            (po.po_number, d.delivery_no, line_no)
            for po, d, r in received
            for line_no in r.lines
        },
    }
    receipt_delivery = goods_receipt.join(
        delivery, delivery.c.delivery_id == goods_receipt.c.delivery_id
    )
    stored = {
        "material": select(material.c.code),
        "purchase_order": select(purchase_order.c.po_number),
        "po_line": select(po_line.c.po_number, po_line.c.line_no),
        "delivery": select(delivery.c.po_number, delivery.c.delivery_no),
        "goods_receipt": select(
            delivery.c.po_number, delivery.c.delivery_no
        ).select_from(receipt_delivery),
        "goods_receipt_line": select(
            delivery.c.po_number, delivery.c.delivery_no, po_line.c.line_no
        ).select_from(
            goods_receipt_line.join(
                goods_receipt,
                goods_receipt.c.receipt_id == goods_receipt_line.c.receipt_id,
            )
            .join(delivery, delivery.c.delivery_id == goods_receipt.c.delivery_id)
            .join(po_line, po_line.c.po_line_id == goods_receipt_line.c.po_line_id)
        ),
    }
    return {
        table: len(_keys(connection, query) - in_file[table])
        for table, query in stored.items()
    }
