"""Story 5.3: the AD-20 price-rise rule (CAP-14), pure. Synthetic data only
(security.md rule 1). One merged test (the 200-case cap, coding-style.md rule 20
exception): each plan matrix row is a block of assertions."""

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from invoicing.domain.analytics import PricePoint, price_rises

SUPPLIER_A = UUID("0192f0c1-7a2b-7c3d-8e4f-0000000053a1")
SUPPLIER_B = UUID("0192f0c1-7a2b-7c3d-8e4f-0000000053b1")
MATERIAL = UUID("0192f0c1-7a2b-7c3d-8e4f-0000000053c1")
OTHER = UUID("0192f0c1-7a2b-7c3d-8e4f-0000000053c2")


def _point(
    n: int,
    day: int,
    price: str,
    supplier: UUID = SUPPLIER_A,
    material: UUID = MATERIAL,
) -> PricePoint:
    return PricePoint(
        invoice_id=UUID(f"0192f0c1-7a2b-7c3d-8e4f-{n:012x}"),
        line_no=1,
        supplier_id=supplier,
        material_id=material,
        invoice_date=date(2026, 9, day),
        unit_price=Decimal(price),
        posted_at=datetime(2026, 9, day, 3, tzinfo=UTC),
    )


def test_story_5_3_price_rises() -> None:
    """More than 2% above the previous price is a rise, exactly 2% is not; points
    in invoice date, then invoice id order per supplier and material; the first price
    is never a rise."""
    # --- Rise: 4.00 then 4.10 is +2.5%; just over: 4.00 then 4.09 (+2.25%).
    first, rise = _point(1, 1, "4.00"), _point(2, 2, "4.10")
    (found,) = price_rises([rise, first])
    assert (found.previous, found.current, found.pct) == (first, rise, Decimal("2.50"))
    assert found.dedupe_key == f"price_rise:{rise.invoice_id}:1"
    (over,) = price_rises([_point(1, 1, "4.00"), _point(2, 2, "4.09")])
    assert over.pct == Decimal("2.25")

    # --- Not a rise: 4.00 then 4.08 (+2.0% exactly).
    assert price_rises([_point(1, 1, "4.00"), _point(2, 2, "4.08")]) == []

    # --- Same date: ordered by invoice id, so invoice 5 (4.00) comes before 6 (4.50).
    later, earlier = _point(6, 4, "4.50"), _point(5, 4, "4.00")
    (same_day,) = price_rises([later, earlier])
    assert (same_day.previous, same_day.current) == (earlier, later)
    assert same_day.pct == Decimal("12.50")

    # --- Two lines of one invoice are never compared with each other (4.00 then
    # 4.50 on invoice 7 is no rise); each is compared with the earlier invoice's
    # last line (4.50): 4.70 and 4.60 on invoice 8 both are.
    seven = _point(7, 5, "4.00")
    seven_last = replace(seven, line_no=2, unit_price=Decimal("4.50"))
    eight = _point(8, 6, "4.70")
    eight_b = replace(eight, line_no=2, unit_price=Decimal("4.60"))
    rises = price_rises([eight_b, seven, eight, seven_last])
    assert [(r.previous, r.current, r.pct) for r in rises] == [
        (seven_last, eight, Decimal("4.44")),
        (seven_last, eight_b, Decimal("2.22")),
    ]

    # --- First price: one point alone, and each supplier and material on its own.
    assert price_rises([_point(1, 1, "4.00")]) == []
    assert (
        price_rises(
            [
                _point(1, 1, "1.00"),
                _point(2, 2, "9.00", supplier=SUPPLIER_B),
                _point(3, 3, "9.00", material=OTHER),
            ]
        )
        == []
    )
