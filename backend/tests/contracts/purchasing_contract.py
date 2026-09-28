"""The `PurchasingPort` contract (AD-10, Story 2.4): behaviour every purchasing adapter
must show, the simulation today and the real system later, so they can't drift.

Reuse it by subclassing `PurchasingContract` in a `test_*.py` module (class name
starting with `Test`) and providing a `purchasing` fixture: the adapter under test,
holding the reference data set `backend/seed/sim_purchasing.json` (synthetic,
security.md rule 1). Every expectation below is a fact of that data set.
"""

import asyncio
from collections.abc import Coroutine
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from invoicing.ports.purchasing import (
    Delivery,
    DeliveryDates,
    GoodsReceipt,
    OverduePo,
    PurchaseOrder,
    PurchasingPort,
)

SUPPLIER_ALPHA = UUID("01a0c450-6c00-7b7b-8aa9-4ccade9f5526")
SUPPLIER_BETA = UUID("01a0c450-6fe8-7cb7-9e60-74d841e2024a")
SUPPLIER_GAMMA = UUID("01a0c450-73d0-7ee3-94ca-ef9fef9d793d")
CEMENT = UUID("01a0c450-77b8-7941-bf2d-d448fcfc8ebd")
REBAR = UUID("01a0c450-7ba0-7326-9cb4-e985278518b7")

# PO-45012: delivered in 2 parts; the second part only receives line 2, due later.
PO_TWO_PARTS = "PO-45012"
LINE_12_1 = UUID("01a0c450-8370-7ad0-8b7e-e79b9256c746")
LINE_12_2 = UUID("01a0c450-8758-7c9d-8bc2-3f4db6df5878")
DELIVERY_12_1 = UUID("01a0c450-9ec8-75d6-8da5-5adc523d9350")
DELIVERY_12_2 = UUID("01a0c450-a2b0-75b9-9eac-12e4d657f199")
# PO-45014: ordered, never delivered or received, not yet due.
PO_NO_RECEIPT = "PO-45014"
# PO-45015: no delivery, due 2026-09-15: overdue.
PO_OVERDUE = "PO-45015"
# PO-45016: the goods-in delivery.
PO_GOODS_IN = "PO-45016"
DELIVERY_GOODS_IN = UUID("01a0c450-aa80-72d5-bb5c-e21dfa7e05aa")
# PO-45017: delivered, not yet received.
PO_NOT_RECEIVED = "PO-45017"
DELIVERY_NOT_RECEIVED = UUID("01a0c450-c1f0-7569-b3aa-76f1c8cc87a8")


def run[T](call: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(call)


class PurchasingContract:
    """Subclass as `Test...` and provide the `purchasing` fixture."""

    @pytest.fixture
    def purchasing(self) -> PurchasingPort:
        raise NotImplementedError("the adapter's test module provides `purchasing`")

    def test_story_2_4_known_po_has_its_supplier_and_lines(
        self, purchasing: PurchasingPort
    ) -> None:
        po = run(purchasing.get_po(PO_TWO_PARTS))
        assert isinstance(po, PurchaseOrder)
        assert po.po_number == PO_TWO_PARTS
        assert po.supplier_id == SUPPLIER_ALPHA
        assert po.order_date == date(2026, 8, 20)
        assert [line.line_no for line in po.lines] == [1, 2]
        assert [line.po_line_id for line in po.lines] == [LINE_12_1, LINE_12_2]
        first, second = po.lines
        assert first.material_id == CEMENT
        assert first.material_name == "Portland cement, 50 kg bag"
        assert first.supplier_product_code == "ALP-CEM-50"
        assert first.unit_price == Decimal("7.80")
        assert first.quantity == Decimal(100)
        assert first.expected_date == date(2026, 9, 1)
        assert second.material_id == REBAR
        assert second.unit_price == Decimal("18.50")
        assert second.expected_date == date(2026, 9, 12)
        # Money and quantities are exact, never floats (coding-style.md rule 4).
        for line in po.lines:
            assert type(line.unit_price) is Decimal
            assert type(line.quantity) is Decimal
            assert type(line.expected_date) is date

    def test_story_2_4_fractional_quantities_are_exact(
        self, purchasing: PurchasingPort
    ) -> None:
        po = run(purchasing.get_po(PO_GOODS_IN))
        assert po is not None
        assert po.lines[0].quantity == Decimal("20.5")

    def test_story_2_4_unknown_po_is_none(self, purchasing: PurchasingPort) -> None:
        assert run(purchasing.get_po("NOPE")) is None

    def test_story_2_4_same_material_from_three_suppliers_at_different_prices(
        self, purchasing: PurchasingPort
    ) -> None:
        prices = {}
        for po_number in ("PO-45012", "PO-45013", "PO-45014"):
            po = run(purchasing.get_po(po_number))
            assert po is not None
            (cement,) = [line for line in po.lines if line.material_id == CEMENT]
            prices[po.supplier_id] = cement.unit_price
        assert set(prices) == {SUPPLIER_ALPHA, SUPPLIER_BETA, SUPPLIER_GAMMA}
        assert len(set(prices.values())) == 3

    def test_story_2_4_partial_delivery_has_two_receipts(
        self, purchasing: PurchasingPort
    ) -> None:
        receipts = run(purchasing.get_receipts(PO_TWO_PARTS))
        assert all(isinstance(r, GoodsReceipt) for r in receipts)
        assert [r.received_date for r in receipts] == [
            date(2026, 9, 2),
            date(2026, 9, 15),
        ]
        assert [dict(r.lines) for r in receipts] == [
            {LINE_12_1: Decimal(100)},
            {LINE_12_2: Decimal(50)},
        ]
        assert receipts[0].receipt_id != receipts[1].receipt_id

    @pytest.mark.parametrize(
        "po_number", [PO_NO_RECEIPT, PO_OVERDUE, PO_NOT_RECEIVED, "NOPE"]
    )
    def test_story_2_4_no_receipt_is_an_empty_list(
        self, purchasing: PurchasingPort, po_number: str
    ) -> None:
        assert run(purchasing.get_receipts(po_number)) == ()

    def test_story_2_4_delivery_has_its_supplier_po_and_date(
        self, purchasing: PurchasingPort
    ) -> None:
        assert run(purchasing.get_delivery(DELIVERY_GOODS_IN)) == Delivery(
            delivery_id=DELIVERY_GOODS_IN,
            supplier_id=SUPPLIER_GAMMA,
            po_number=PO_GOODS_IN,
            delivery_no=1,
            delivery_date=date(2026, 9, 29),
        )

    def test_story_2_4_unknown_delivery_is_none(
        self, purchasing: PurchasingPort
    ) -> None:
        unknown = UUID("01a0c450-0000-7000-8000-000000000000")
        assert run(purchasing.get_delivery(unknown)) is None

    @pytest.mark.parametrize(
        ("as_of", "expected"),
        [
            # Before any PO is due: nothing.
            (date(2026, 9, 1), []),
            (date(2026, 9, 2), [("PO-45012", date(2026, 9, 1))]),
            (
                date(2026, 9, 15),
                [("PO-45012", date(2026, 9, 1)), ("PO-45013", date(2026, 9, 5))],
            ),
            (
                date(2026, 9, 16),
                [
                    ("PO-45012", date(2026, 9, 1)),
                    ("PO-45013", date(2026, 9, 5)),
                    (PO_OVERDUE, date(2026, 9, 15)),
                ],
            ),
            (
                date(2026, 10, 1),
                [
                    ("PO-45012", date(2026, 9, 1)),
                    ("PO-45013", date(2026, 9, 5)),
                    (PO_OVERDUE, date(2026, 9, 15)),
                    (PO_NOT_RECEIVED, date(2026, 9, 25)),
                    (PO_GOODS_IN, date(2026, 9, 28)),
                ],
            ),
        ],
    )
    def test_story_2_4_overdue_is_earliest_expected_date_before_as_of(
        self,
        purchasing: PurchasingPort,
        as_of: date,
        expected: list[tuple[str, date]],
    ) -> None:
        overdue = run(purchasing.list_overdue_pos(as_of))
        assert all(isinstance(po, OverduePo) for po in overdue)
        assert [(po.po_number, po.expected_date) for po in overdue] == expected
        # PO-45014 is due 2026-10-20 (its earliest line), so it is never listed here.
        # Receipts don't matter: fully received POs are listed until invoiced (AD-13).
        assert PO_NO_RECEIPT not in {po.po_number for po in overdue}

    def test_story_2_4_overdue_names_the_supplier(
        self, purchasing: PurchasingPort
    ) -> None:
        overdue = run(purchasing.list_overdue_pos(date(2026, 9, 16)))
        assert {po.po_number: po.supplier_id for po in overdue}[
            PO_OVERDUE
        ] == SUPPLIER_BETA

    def test_story_2_4_delivery_dates_are_promised_delivered_received(
        self, purchasing: PurchasingPort
    ) -> None:
        assert run(purchasing.get_delivery_dates(PO_TWO_PARTS)) == (
            DeliveryDates(
                delivery_id=DELIVERY_12_1,
                promised_date=date(2026, 9, 1),
                delivered_date=date(2026, 9, 2),
                received_date=date(2026, 9, 2),
            ),
            # Only line 2 was received, so the promise is line 2's, not the PO's.
            DeliveryDates(
                delivery_id=DELIVERY_12_2,
                promised_date=date(2026, 9, 12),
                delivered_date=date(2026, 9, 14),
                received_date=date(2026, 9, 15),
            ),
        )

    def test_story_2_4_a_delivery_not_yet_received_has_no_received_date(
        self, purchasing: PurchasingPort
    ) -> None:
        # With no receipt the promise is the PO's earliest line.
        assert run(purchasing.get_delivery_dates(PO_NOT_RECEIVED)) == (
            DeliveryDates(
                delivery_id=DELIVERY_NOT_RECEIVED,
                promised_date=date(2026, 9, 25),
                delivered_date=date(2026, 9, 26),
                received_date=None,
            ),
        )

    @pytest.mark.parametrize("po_number", [PO_NO_RECEIPT, "NOPE"])
    def test_story_2_4_no_delivery_has_no_dates(
        self, purchasing: PurchasingPort, po_number: str
    ) -> None:
        assert run(purchasing.get_delivery_dates(po_number)) == ()
