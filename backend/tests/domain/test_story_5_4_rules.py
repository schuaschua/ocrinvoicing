"""Story 5.4: the AD-20 watchlist rules (CAP-15) and the alternatives ranking
(CAP-16), pure. Synthetic data only (security.md rule 1). One merged test (the
200-case cap, coding-style.md rule 20 exception): each plan matrix row is a block of
assertions."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from invoicing.domain.analytics import (
    LateLine,
    PricePoint,
    SupplierOnTime,
    alternatives,
    watchlist_dedupe_key,
    watchlist_rules,
)

TODAY = date(2026, 10, 1)
A = UUID("0192f0c1-7a2b-7c3d-8e4f-0000000054a1")
B = UUID("0192f0c1-7a2b-7c3d-8e4f-0000000054b1")
C = UUID("0192f0c1-7a2b-7c3d-8e4f-0000000054c1")
D = UUID("0192f0c1-7a2b-7c3d-8e4f-0000000054d1")
E = UUID("0192f0c1-7a2b-7c3d-8e4f-0000000054e1")
M = UUID("0192f0c1-7a2b-7c3d-8e4f-0000000054f1")
N = UUID("0192f0c1-7a2b-7c3d-8e4f-0000000054f2")


def _ago(days: int) -> date:
    return TODAY - timedelta(days=days)


def _rise(supplier: UUID, n: int, days_ago: int) -> dict[str, Any]:
    """A price-rise alert's `detail`, as Story 5.3 stores it."""
    return {
        "supplier_id": str(supplier),
        "material_id": str(M),
        "pct": "2.50",
        "previous": {
            "invoice_id": f"0192f0c1-7a2b-7c3d-8e4f-{n:012x}",
            "invoice_date": _ago(days_ago + 1).isoformat(),
            "unit_price": "4.00",
        },
        "current": {
            "invoice_id": f"0192f0c1-7a2b-7c3d-8e4f-{n + 1:012x}",
            "invoice_date": _ago(days_ago).isoformat(),
            "unit_price": "4.10",
        },
    }


def _on_time(supplier: UUID, average: str, rate: str = "0.5000") -> SupplierOnTime:
    return SupplierOnTime(supplier, 10, 5, Decimal(rate), Decimal(average))


def _late(supplier: UUID, n: int, days_ago: int, late_by: int) -> LateLine:
    return LateLine(
        receipt_id=UUID(int=n),
        po_line_id=UUID(int=1),
        supplier_id=supplier,
        material_id=N,
        received_date=_ago(days_ago),
        days_late=late_by,
    )


def _point(supplier: UUID, n: int, days_ago: int, price: str) -> PricePoint:
    day = _ago(days_ago)
    return PricePoint(
        invoice_id=UUID(int=n),
        line_no=1,
        supplier_id=supplier,
        material_id=M,
        invoice_date=day,
        unit_price=Decimal(price),
        posted_at=datetime(day.year, day.month, day.day, 3, tzinfo=UTC),
    )


def _listed(**inputs: Any) -> dict[tuple[UUID, str], tuple[dict[str, Any], ...]]:
    args = {"rise_alerts": (), "on_time": (), "late_lines": (), "points": ()}
    hits = watchlist_rules(TODAY, **{**args, **inputs})
    return {(hit.supplier_id, hit.rule): hit.evidence for hit in hits}


def test_story_5_4_rules() -> None:
    """3 rises in 365 days, 7.00 days late on average, and 5% above the cheapest of
    the last 90 days list a supplier, each with its evidence; one less does not; the
    alternatives rank by price, then on-time rate, then name."""
    # --- 3 rises: within 365 days (today-364 counts), latest first.
    rises = [_rise(A, 10, 0), _rise(A, 20, 364), _rise(A, 30, 100)]
    evidence = _listed(rise_alerts=rises)[A, "price_rises"]
    assert [item["current"]["invoice_date"] for item in evidence] == [
        _ago(0).isoformat(),
        _ago(100).isoformat(),
        _ago(364).isoformat(),
    ]
    assert evidence[0] == {key: rises[0][key] for key in evidence[0]}

    # --- 2 rises: two within 365 days and one older (today-365) is not listed.
    assert (
        _listed(rise_alerts=[_rise(A, 10, 0), _rise(A, 20, 1), _rise(A, 30, 365)]) == {}
    )

    # --- Late: 7.00 is listed, 6.99 is not; the evidence is the late lines only, at
    # most 20, latest first, in the 365 days.
    lines = [_late(A, n, n, 8) for n in range(1, 25)]
    lines += [_late(A, 100, 0, 0), _late(A, 101, 400, 30), _late(B, 102, 0, 9)]
    listed = _listed(
        on_time=[_on_time(A, "7.00"), _on_time(B, "6.99")], late_lines=lines
    )
    assert list(listed) == [(A, "late")]
    assert len(listed[A, "late"]) == 20
    assert listed[A, "late"][0] == {
        "receipt_id": str(UUID(int=1)),
        "material_id": str(N),
        "received_date": _ago(1).isoformat(),
        "days_late": 8,
    }
    assert listed[A, "late"][-1]["received_date"] == _ago(20).isoformat()

    # --- Price gap: A 4.20, B 4.00 (both within 90 days) lists A at +5.00%; C at
    # 4.19 (+4.75%) is not; A's own older, cheaper price is not its latest.
    points = [
        _point(A, 1, 30, "3.00"),
        _point(A, 2, 10, "4.20"),
        _point(B, 3, 89, "4.00"),
        _point(C, 4, 5, "4.19"),
    ]
    assert _listed(points=points) == {
        (A, "price_gap"): (
            {
                "material_id": str(M),
                "invoice_id": str(UUID(int=2)),
                "invoice_date": _ago(10).isoformat(),
                "unit_price": "4.20",
                "lowest_unit_price": "4.00",
                "cheapest_supplier_id": str(B),
                "pct": "5.00",
            },
        )
    }

    # --- Stale cheap: B's last price 100 days ago (or 90) isn't the lowest; nor is a
    # pricey supplier whose last price is that old listed.
    stale = [
        _point(A, 2, 10, "4.20"),
        _point(B, 3, 90, "4.00"),
        _point(D, 5, 100, "9.00"),
        _point(C, 4, 5, "4.19"),
    ]
    assert _listed(points=stale) == {}

    # --- Several rules: one hit per supplier and rule, by supplier then rule.
    both = watchlist_rules(
        TODAY,
        [_rise(B, 10, 1), _rise(B, 20, 2), _rise(B, 30, 3)],
        [_on_time(B, "9.00")],
        [],
        points,
    )
    assert [(hit.supplier_id, hit.rule) for hit in both] == [
        (A, "price_gap"),
        (B, "price_rises"),
        (B, "late"),
    ]
    assert watchlist_dedupe_key(A, "late", TODAY) == f"watchlist:{A}:late:2026-10-01"

    # --- Alternatives: the others with a price in the last 90 days, by latest price,
    # then on-time rate (best first, none last), then name.
    ranked = [
        _point(A, 1, 1, "4.50"),
        _point(B, 2, 3, "4.00"),
        _point(C, 3, 2, "4.00"),
        _point(D, 4, 1, "4.00"),
        _point(E, 5, 4, "3.00"),
        _point(E, 6, 2, "4.00"),  # E's latest
        _point(UUID(int=9), 7, 95, "1.00"),  # stale: not an alternative
    ]
    rates = {B: Decimal("0.5000"), C: Decimal("0.9000"), E: Decimal("0.5000")}
    names = {B: "Zeta Soles", E: "Alpha Soles"}
    found = alternatives(TODAY, M, A, ranked, rates, names)
    assert [(item.supplier_id, item.latest_unit_price) for item in found] == [
        (C, Decimal("4.00")),
        (E, Decimal("4.00")),
        (B, Decimal("4.00")),
        (D, Decimal("4.00")),
    ]
    assert [item.on_time_rate for item in found] == [
        Decimal("0.9000"),
        Decimal("0.5000"),
        Decimal("0.5000"),
        None,
    ]
    assert alternatives(TODAY, N, A, ranked, rates, names) == []
