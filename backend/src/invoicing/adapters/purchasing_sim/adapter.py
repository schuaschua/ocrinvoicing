"""`PurchasingPort` over the simulation's PostgreSQL schema (AD-10), read-only.

It reuses the app's engine: the app logins hold SELECT only on this schema (AD-11),
so the adapter can't write even by mistake. A method that can't connect raises
`DatabaseOfflineError` (engine.open_connection, AD-7). The queries run on a worker
thread, so the Functions event loop is never blocked (coding-style.md rule 11).
"""

import asyncio
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Connection, Engine, func, select

from invoicing.adapters.postgres.engine import open_connection
from invoicing.adapters.purchasing_sim.schema import (
    delivery,
    goods_receipt,
    goods_receipt_line,
    material,
    po_line,
    purchase_order,
)
from invoicing.ports.purchasing import (
    Delivery,
    DeliveryDates,
    GoodsReceipt,
    OverduePo,
    PoLine,
    PurchaseOrder,
)


class PurchasingSimAdapter:
    """The purchasing simulation, through SQLAlchemy Core with bound parameters."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    async def get_po(self, po_number: str) -> PurchaseOrder | None:
        return await asyncio.to_thread(self._read, self._get_po, po_number)

    async def get_receipts(self, po_number: str) -> tuple[GoodsReceipt, ...]:
        return await asyncio.to_thread(self._read, self._get_receipts, po_number)

    async def get_delivery(self, delivery_id: UUID) -> Delivery | None:
        return await asyncio.to_thread(self._read, self._get_delivery, delivery_id)

    async def list_overdue_pos(self, as_of: date) -> tuple[OverduePo, ...]:
        return await asyncio.to_thread(self._read, self._overdue, as_of)

    async def get_delivery_dates(self, po_number: str) -> tuple[DeliveryDates, ...]:
        return await asyncio.to_thread(self._read, self._delivery_dates, po_number)

    # --- one read each -----------------------------------------------------------------

    def _read[T, A](self, work: Callable[[Connection, A], T], argument: A) -> T:
        with open_connection(self._engine) as connection:
            return work(connection, argument)

    @staticmethod
    def _get_po(connection: Connection, po_number: str) -> PurchaseOrder | None:
        order = connection.execute(
            select(purchase_order.c.supplier_id, purchase_order.c.order_date).where(
                purchase_order.c.po_number == po_number
            )
        ).one_or_none()
        if order is None:
            return None
        rows = connection.execute(
            select(
                po_line.c.po_line_id,
                po_line.c.line_no,
                po_line.c.material_id,
                material.c.name,
                po_line.c.supplier_product_code,
                po_line.c.unit_price,
                po_line.c.quantity,
                po_line.c.expected_date,
            )
            .join(material, material.c.material_id == po_line.c.material_id)
            .where(po_line.c.po_number == po_number)
            .order_by(po_line.c.line_no)
        ).all()
        lines = tuple(
            PoLine(
                po_line_id=row.po_line_id,
                line_no=row.line_no,
                material_id=row.material_id,
                material_name=row.name,
                supplier_product_code=row.supplier_product_code,
                unit_price=row.unit_price,
                quantity=row.quantity,
                expected_date=row.expected_date,
            )
            for row in rows
        )
        return PurchaseOrder(
            po_number=po_number,
            supplier_id=order.supplier_id,
            order_date=order.order_date,
            lines=lines,
        )

    @staticmethod
    def _get_receipts(
        connection: Connection, po_number: str
    ) -> tuple[GoodsReceipt, ...]:
        rows = connection.execute(
            select(
                goods_receipt.c.receipt_id,
                goods_receipt.c.received_date,
                goods_receipt.c.delivery_id,
                goods_receipt_line.c.po_line_id,
                goods_receipt_line.c.quantity,
            )
            .join(delivery, delivery.c.delivery_id == goods_receipt.c.delivery_id)
            .join(
                goods_receipt_line,
                goods_receipt_line.c.receipt_id == goods_receipt.c.receipt_id,
            )
            .where(delivery.c.po_number == po_number)
            .order_by(
                goods_receipt.c.received_date,
                goods_receipt.c.receipt_id,
                goods_receipt_line.c.po_line_id,
            )
        ).all()
        received: dict[UUID, tuple[date, UUID, dict[UUID, Decimal]]] = {}
        for row in rows:
            _, _, lines = received.setdefault(
                row.receipt_id, (row.received_date, row.delivery_id, {})
            )
            lines[row.po_line_id] = row.quantity
        return tuple(
            GoodsReceipt(
                receipt_id=receipt_id,
                received_date=when,
                lines=lines,
                delivery_id=delivery_id,
            )
            for receipt_id, (when, delivery_id, lines) in received.items()
        )

    @staticmethod
    def _get_delivery(connection: Connection, delivery_id: UUID) -> Delivery | None:
        row = connection.execute(
            select(
                delivery.c.delivery_id,
                purchase_order.c.supplier_id,
                delivery.c.po_number,
                delivery.c.delivery_no,
                delivery.c.delivery_date,
            )
            .join(purchase_order, purchase_order.c.po_number == delivery.c.po_number)
            .where(delivery.c.delivery_id == delivery_id)
        ).one_or_none()
        if row is None:
            return None
        return Delivery(
            delivery_id=row.delivery_id,
            supplier_id=row.supplier_id,
            po_number=row.po_number,
            delivery_no=row.delivery_no,
            delivery_date=row.delivery_date,
        )

    @staticmethod
    def _overdue(connection: Connection, as_of: date) -> tuple[OverduePo, ...]:
        earliest = func.min(po_line.c.expected_date).label("expected_date")
        rows = connection.execute(
            select(purchase_order.c.po_number, purchase_order.c.supplier_id, earliest)
            .join(po_line, po_line.c.po_number == purchase_order.c.po_number)
            .group_by(purchase_order.c.po_number, purchase_order.c.supplier_id)
            .having(earliest < as_of)
            .order_by(earliest, purchase_order.c.po_number)
        ).all()
        return tuple(
            OverduePo(
                po_number=row.po_number,
                supplier_id=row.supplier_id,
                expected_date=row.expected_date,
            )
            for row in rows
        )

    @staticmethod
    def _delivery_dates(
        connection: Connection, po_number: str
    ) -> tuple[DeliveryDates, ...]:
        po_earliest = (
            select(func.min(po_line.c.expected_date))
            .where(po_line.c.po_number == po_number)
            .scalar_subquery()
        )
        received_earliest = (
            select(func.min(po_line.c.expected_date))
            .join(
                goods_receipt_line,
                goods_receipt_line.c.po_line_id == po_line.c.po_line_id,
            )
            .where(goods_receipt_line.c.receipt_id == goods_receipt.c.receipt_id)
            .correlate(goods_receipt)
            .scalar_subquery()
        )
        rows = connection.execute(
            select(
                delivery.c.delivery_id,
                func.coalesce(received_earliest, po_earliest).label("promised"),
                delivery.c.delivery_date,
                goods_receipt.c.received_date,
            )
            .outerjoin(
                goods_receipt, goods_receipt.c.delivery_id == delivery.c.delivery_id
            )
            .where(delivery.c.po_number == po_number)
            .order_by(delivery.c.delivery_date, delivery.c.delivery_no)
        ).all()
        return tuple(
            DeliveryDates(
                delivery_id=row.delivery_id,
                promised_date=row.promised,
                delivered_date=row.delivery_date,
                received_date=row.received_date,
            )
            for row in rows
        )
