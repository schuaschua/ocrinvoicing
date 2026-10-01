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
    GoodsReceipt,
    PurchaseOrder,
    PurchasingPort,
    ReceiptLine,
)

SUPPLIER_ALPHA = UUID("01a0c450-6c00-7b7b-8aa9-4ccade9f5526")
CEMENT = UUID("01a0c450-77b8-7941-bf2d-d448fcfc8ebd")
REBAR = UUID("01a0c450-7ba0-7326-9cb4-e985278518b7")

# PO-45012: delivered in 2 parts; the second part only receives line 2, due later.
PO_TWO_PARTS = "PO-45012"
LINE_12_1 = UUID("01a0c450-8370-7ad0-8b7e-e79b9256c746")
LINE_12_2 = UUID("01a0c450-8758-7c9d-8bc2-3f4db6df5878")
DELIVERY_12_1 = UUID("01a0c450-9ec8-75d6-8da5-5adc523d9350")
DELIVERY_12_2 = UUID("01a0c450-a2b0-75b9-9eac-12e4d657f199")
# Story 4.1: the other deliveries, by date (PO-45013 9-07, PO-45017 9-26, PO-45016 9-29).
DELIVERY_13_1 = UUID("01a0c450-a698-7572-8c2a-c08ca96f7ab9")
DELIVERY_16_1 = UUID("01a0c450-aa80-72d5-bb5c-e21dfa7e05aa")
DELIVERY_17_1 = UUID("01a0c450-c1f0-7569-b3aa-76f1c8cc87a8")


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
        # Story 2.5: each receipt names its delivery, so a goods-in scan finds its own.
        assert [r.delivery_id for r in receipts] == [DELIVERY_12_1, DELIVERY_12_2]

        # --- Story 5.1: receipt lines from a date, each with its PO line's supplier,
        # material and expected date (PO-45016's, received 29 Sep, comes after).
        lines = run(purchasing.receipt_lines(date(2026, 9, 15)))
        assert lines[0] == ReceiptLine(
            receipts[1].receipt_id,
            LINE_12_2,
            SUPPLIER_ALPHA,
            REBAR,
            date(2026, 9, 12),
            date(2026, 9, 15),
        )
        assert [line.received_date for line in lines] == [
            date(2026, 9, 15),
            date(2026, 9, 29),
        ]
        # --- Story 5.3: material names by id; an unknown id has none.
        assert run(purchasing.material_names([CEMENT, REBAR, LINE_12_1])) == {
            CEMENT: "Portland cement, 50 kg bag",
            REBAR: "Steel rebar, 12 mm x 12 m",
        }
        assert run(purchasing.material_names([])) == {}

        # --- Story 4.1: a delivery with its PO's supplier, the day's deliveries, and
        # the search by PO prefix (any case, wildcards literal), newest first.
        second = Delivery(
            DELIVERY_12_2, SUPPLIER_ALPHA, PO_TWO_PARTS, 2, date(2026, 9, 14)
        )
        assert run(purchasing.get_delivery(DELIVERY_12_2)) == second
        assert run(purchasing.list_deliveries(date(2026, 9, 14))) == (second,)
        assert run(purchasing.list_deliveries(date(2026, 9, 15))) == ()

        def found(text: str, since: date) -> list[UUID]:
            return [
                d.delivery_id for d in run(purchasing.search_deliveries(text, since))
            ]

        assert found("po-4501", date(2026, 9, 7)) == [
            DELIVERY_16_1,
            DELIVERY_17_1,
            DELIVERY_12_2,
            DELIVERY_13_1,
        ]
        assert found("PO-45012", date(2026, 9, 1)) == [DELIVERY_12_2, DELIVERY_12_1]
        assert found("", date(2026, 9, 20)) == [DELIVERY_16_1, DELIVERY_17_1]
        assert found("%", date(2026, 1, 1)) == []
        # As goods-in shows it: without "PO", or with a space.
        for said in ("45012", "po 45012", "PO45012"):
            assert found(said, date(2026, 1, 1)) == [DELIVERY_12_2, DELIVERY_12_1]
        assert found("%5012", date(2026, 1, 1)) == []
