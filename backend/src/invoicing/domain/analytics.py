"""AD-20 analytics rules (Story 5.1): the pure part of the analytics refresh job's
daily summaries. The adapter reads the rows and writes what these return. Story 5.3
adds the price-rise rule (CAP-14), evaluated in the same step, and Story 5.4 the
watchlist rules (CAP-15) after it, with the alternatives ranking (CAP-16) staff-api
applies at read time; Story 5.5 the scorecard's price change (CAP-17).

Months are the first day of a Singapore month. Money is `Decimal` rounded half-up to
2 places, rates to 4 (`numeric(18,2)` and `numeric(5,4)` in `analytics`). The
currency is the configured invoice currency (SGD, AD-20), so none is carried.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from invoicing.domain.current_values import CurrentValues, FieldValue
from invoicing.domain.dates import singapore_date
from invoicing.domain.validation import INVOICE_DATE, INVOICE_TOTAL

_CENT = Decimal("0.01")
_RATE = Decimal("0.0001")


def month_start(day: date) -> date:
    """The first day of `day`'s month."""
    return day.replace(day=1)


def singapore_month(at: datetime) -> date:
    """The first day of the Singapore month of the aware instant `at`."""
    return month_start(singapore_date(at))


def money(value: Decimal) -> Decimal:
    """`value` rounded half-up to 2 places."""
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def rate(part: int, whole: int) -> Decimal:
    """`part / whole` rounded half-up to 4 places; `whole` is never 0."""
    return (Decimal(part) / Decimal(whole)).quantize(_RATE, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class PricePoint:
    """One current line with a material of a posted invoice (`analytics.price_point`)."""

    invoice_id: UUID
    line_no: int
    supplier_id: UUID
    material_id: UUID
    invoice_date: date
    unit_price: Decimal
    posted_at: datetime


@dataclass(frozen=True)
class InvoiceFact:
    """One posted invoice (`analytics.invoice_fact`)."""

    invoice_id: UUID
    supplier_id: UUID
    invoice_date: date
    posted_month: date
    total: Decimal | None
    straight_through: bool


@dataclass(frozen=True)
class SupplierMonth:
    """Spend and posted invoices per supplier and posted month."""

    supplier_id: UUID
    month: date
    spend: Decimal
    posted_count: int


@dataclass(frozen=True)
class MonthSummary:
    """The straight-through share of a posted month (CAP-18)."""

    month: date
    posted_count: int
    straight_through_count: int
    straight_through_share: Decimal


@dataclass(frozen=True)
class SupplierFlags:
    """Flagged and duplicate invoices per supplier and received month (CAP-18)."""

    supplier_id: UUID
    month: date
    flagged_count: int
    duplicate_count: int


@dataclass(frozen=True)
class SupplierOnTime:
    """A supplier's lateness over the window (CAP-17); `avg_days_late` counts early
    receipts as negative days."""

    supplier_id: UUID
    receipts: int
    on_time: int
    on_time_rate: Decimal
    avg_days_late: Decimal


def _invoice_date(held: FieldValue | None, posted_at: datetime) -> date:
    # DI reads a date as `value_date`; an admin may have typed it as text
    # (YYYY-MM-DD). Missing or unreadable: the Singapore date it was posted.
    if held is not None:
        if held.value_date is not None:
            return held.value_date
        try:
            return date.fromisoformat((held.value_text or "").strip())
        except ValueError:
            pass
    return singapore_date(posted_at)


def posted_summary(
    invoice_id: UUID,
    supplier_id: UUID,
    posted_at: datetime,
    straight_through: bool,
    values: CurrentValues | None,
) -> tuple[InvoiceFact, tuple[PricePoint, ...]]:
    """A posted invoice's fact and price points from its AD-18 current values, so a
    corrected line counts once, with its corrected value. Only a line with a material
    and a unit price above 0 has a price point."""
    fields = {} if values is None else values.fields
    invoice_date = _invoice_date(fields.get(INVOICE_DATE), posted_at)
    held_total = fields.get(INVOICE_TOTAL)
    total = None if held_total is None else held_total.value_number
    fact = InvoiceFact(
        invoice_id=invoice_id,
        supplier_id=supplier_id,
        invoice_date=invoice_date,
        posted_month=singapore_month(posted_at),
        total=None if total is None else money(total),
        straight_through=straight_through,
    )
    points = tuple(
        PricePoint(
            invoice_id=invoice_id,
            line_no=line.line_no,
            supplier_id=supplier_id,
            material_id=line.material_id,
            invoice_date=invoice_date,
            unit_price=money(line.unit_price),
            posted_at=posted_at,
        )
        for line in (() if values is None else values.lines)
        # A zero or negative price (a discount or credit) is no price point.
        if line.material_id is not None
        and line.unit_price is not None
        and line.unit_price > 0
    )
    return fact, points


def supplier_months(facts: Iterable[InvoiceFact]) -> list[SupplierMonth]:
    """Spend (the sum of totals) and count per supplier and posted month."""
    spend: dict[tuple[UUID, date], Decimal] = defaultdict(Decimal)
    counts: dict[tuple[UUID, date], int] = defaultdict(int)
    for fact in facts:
        key = (fact.supplier_id, fact.posted_month)
        spend[key] += fact.total or Decimal(0)
        counts[key] += 1
    return [
        SupplierMonth(supplier, month, money(spend[supplier, month]), count)
        for (supplier, month), count in sorted(counts.items())
    ]


def month_summaries(facts: Iterable[InvoiceFact]) -> list[MonthSummary]:
    """Posted and straight-through invoices, and their share, per posted month."""
    posted: dict[date, int] = defaultdict(int)
    straight: dict[date, int] = defaultdict(int)
    for fact in facts:
        posted[fact.posted_month] += 1
        straight[fact.posted_month] += fact.straight_through
    return [
        MonthSummary(month, posted[month], straight[month], rate(straight[month], n))
        for month, n in sorted(posted.items())
    ]


def supplier_flags(
    invoices: Iterable[tuple[UUID, datetime, bool]],
) -> list[SupplierFlags]:
    """From each flagged invoice's (supplier, `created_at`, has a DUPLICATE item):
    the counts per supplier and Singapore month received."""
    flagged: dict[tuple[UUID, date], int] = defaultdict(int)
    duplicates: dict[tuple[UUID, date], int] = defaultdict(int)
    for supplier_id, created_at, duplicate in invoices:
        key = (supplier_id, singapore_month(created_at))
        flagged[key] += 1
        duplicates[key] += duplicate
    return [
        SupplierFlags(supplier, month, count, duplicates[supplier, month])
        for (supplier, month), count in sorted(flagged.items())
    ]


def days_late(expected: date, received: date) -> int:
    """AD-20: received minus expected, in days; on time is 0 or less."""
    return (received - expected).days


def on_time_rates(lateness: Iterable[tuple[UUID, int]]) -> list[SupplierOnTime]:
    """From each receipt line's (supplier, days late): each supplier's on-time rate
    and average days late. A supplier with no receipts has no row."""
    late: dict[UUID, list[int]] = defaultdict(list)
    for supplier_id, late_by in lateness:
        late[supplier_id].append(late_by)
    result: list[SupplierOnTime] = []
    for supplier_id in sorted(late):
        all_days = late[supplier_id]
        on_time = sum(1 for d in all_days if d <= 0)
        average = (Decimal(sum(all_days)) / Decimal(len(all_days))).quantize(
            _CENT, rounding=ROUND_HALF_UP
        )
        result.append(
            SupplierOnTime(
                supplier_id,
                len(all_days),
                on_time,
                rate(on_time, len(all_days)),
                average,
            )
        )
    return result


# AD-20 (Story 5.3, CAP-14): a price rise is more than 2% above the previous price.
PRICE_RISE_THRESHOLD = Decimal("0.02")
PRICE_RISE = "price_rise"


@dataclass(frozen=True)
class PriceRise:
    """A posted unit price more than 2% above the same supplier's previous posted
    price for the material; `pct` is the rise in percent, 2 decimals."""

    previous: PricePoint
    current: PricePoint
    pct: Decimal

    @property
    def dedupe_key(self) -> str:
        """`analytics.alert.dedupe_key`: one alert per rising line, ever."""
        return f"{PRICE_RISE}:{self.current.invoice_id}:{self.current.line_no}"


def price_rises(points: Iterable[PricePoint]) -> list[PriceRise]:
    """AD-20: per supplier and material, the price points in `invoice_date`, then
    `invoice_id`, then `line_no` order; each one more than 2% above the last point of
    the invoice before it (`(new - prev) / prev > 0.02`, exact) is a rise. Lines of
    one invoice are never compared with each other, and the first invoice's price is
    never a rise."""
    series: dict[tuple[UUID, UUID], list[PricePoint]] = defaultdict(list)
    for point in points:
        series[point.supplier_id, point.material_id].append(point)
    rises: list[PriceRise] = []
    for key in sorted(series):
        ordered = sorted(
            series[key], key=lambda p: (p.invoice_date, p.invoice_id, p.line_no)
        )
        previous: PricePoint | None = None  # the earlier invoice's last point
        last: PricePoint | None = None
        for current in ordered:
            if last is not None and last.invoice_id != current.invoice_id:
                previous = last
            last = current
            if previous is None or previous.unit_price <= 0:
                continue
            change = (current.unit_price - previous.unit_price) / previous.unit_price
            if change > PRICE_RISE_THRESHOLD:
                rises.append(PriceRise(previous, current, money(change * 100)))
    return rises


# --- Story 5.4 (AD-20, CAP-15, CAP-16): the watchlist rules and the alternatives.
WATCHLIST = "watchlist"
RULE_PRICE_RISES = "price_rises"
RULE_LATE = "late"
RULE_PRICE_GAP = "price_gap"
# The order a supplier's rules are listed in.
WATCHLIST_RULES = (RULE_PRICE_RISES, RULE_LATE, RULE_PRICE_GAP)
# AD-20: 3 or more rises, 7 or more days late on average, 5% or more above the
# cheapest supplier.
MIN_PRICE_RISES = 3
LATE_DAYS = Decimal("7.00")
PRICE_GAP_THRESHOLD = Decimal("0.05")
# The last 365 days and the last 90 days, today included: the earliest day counted
# is today minus 364 (or 89).
RISE_WINDOW = timedelta(days=364)
PRICE_GAP_WINDOW = timedelta(days=89)
# At most this many late receipt lines are kept as a `late` entry's evidence.
LATE_EVIDENCE = 20


@dataclass(frozen=True)
class LateLine:
    """One goods-receipt line's lateness (`analytics.receipt_lateness`)."""

    receipt_id: UUID
    po_line_id: UUID
    supplier_id: UUID
    material_id: UUID
    received_date: date
    days_late: int


@dataclass(frozen=True)
class WatchlistHit:
    """A supplier listed under one rule on the run date, with its evidence (JSON
    values, as `analytics.watchlist.evidence` keeps them)."""

    supplier_id: UUID
    rule: str
    evidence: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class Alternative:
    """Another supplier of a material, at its latest price in the last 90 days."""

    supplier_id: UUID
    latest_unit_price: Decimal
    on_time_rate: Decimal | None


def _latest_prices(
    points: Iterable[PricePoint], today: date
) -> dict[UUID, dict[UUID, PricePoint]]:
    """Per material, each supplier's latest price point of the last 90 days (by
    invoice date, then invoice id, then line)."""
    since = today - PRICE_GAP_WINDOW
    latest: dict[UUID, dict[UUID, PricePoint]] = defaultdict(dict)
    for point in sorted(
        points, key=lambda p: (p.invoice_date, p.invoice_id, p.line_no)
    ):
        if since <= point.invoice_date <= today:
            latest[point.material_id][point.supplier_id] = point
    return latest


def _price_rises_hits(
    today: date, rise_alerts: Iterable[Mapping[str, Any]]
) -> list[WatchlistHit]:
    since = today - RISE_WINDOW
    rises: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
    for detail in rise_alerts:
        current = detail["current"]
        if since <= date.fromisoformat(current["invoice_date"]) <= today:
            rises[UUID(detail["supplier_id"])].append(
                {
                    "material_id": detail["material_id"],
                    "pct": detail["pct"],
                    "previous": detail["previous"],
                    "current": current,
                }
            )
    return [
        WatchlistHit(
            supplier_id,
            RULE_PRICE_RISES,
            tuple(
                sorted(
                    found,
                    key=lambda e: (
                        e["current"]["invoice_date"],
                        e["current"]["invoice_id"],
                    ),
                    reverse=True,
                )
            ),
        )
        for supplier_id, found in sorted(rises.items())
        if len(found) >= MIN_PRICE_RISES
    ]


def _late_hits(
    today: date, on_time: Iterable[SupplierOnTime], lines: Iterable[LateLine]
) -> list[WatchlistHit]:
    late = sorted(s.supplier_id for s in on_time if s.avg_days_late >= LATE_DAYS)
    since = today - RISE_WINDOW
    by_supplier: dict[UUID, list[LateLine]] = defaultdict(list)
    for line in lines:
        if line.days_late > 0 and since <= line.received_date <= today:
            by_supplier[line.supplier_id].append(line)
    hits: list[WatchlistHit] = []
    for supplier_id in late:
        latest = sorted(
            by_supplier[supplier_id],
            key=lambda x: (x.received_date, str(x.receipt_id), str(x.po_line_id)),
            reverse=True,
        )[:LATE_EVIDENCE]
        hits.append(
            WatchlistHit(
                supplier_id,
                RULE_LATE,
                tuple(
                    {
                        "receipt_id": str(line.receipt_id),
                        "material_id": str(line.material_id),
                        "received_date": line.received_date.isoformat(),
                        "days_late": line.days_late,
                    }
                    for line in latest
                ),
            )
        )
    return hits


def _price_gap_hits(today: date, points: Iterable[PricePoint]) -> list[WatchlistHit]:
    gaps: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
    for material_id, by_supplier in sorted(_latest_prices(points, today).items()):
        cheapest = min(
            by_supplier.values(), key=lambda p: (p.unit_price, str(p.supplier_id))
        )
        lowest = cheapest.unit_price
        for supplier_id, point in sorted(by_supplier.items()):
            if lowest <= 0:
                continue
            change = (point.unit_price - lowest) / lowest
            if change >= PRICE_GAP_THRESHOLD:
                gaps[supplier_id].append(
                    {
                        "material_id": str(material_id),
                        "invoice_id": str(point.invoice_id),
                        "invoice_date": point.invoice_date.isoformat(),
                        "unit_price": str(point.unit_price),
                        "lowest_unit_price": str(lowest),
                        "cheapest_supplier_id": str(cheapest.supplier_id),
                        "pct": str(money(change * 100)),
                    }
                )
    return [
        WatchlistHit(supplier_id, RULE_PRICE_GAP, tuple(found))
        for supplier_id, found in sorted(gaps.items())
    ]


def watchlist_rules(
    today: date,
    rise_alerts: Iterable[Mapping[str, Any]],
    on_time: Iterable[SupplierOnTime],
    late_lines: Iterable[LateLine],
    points: Iterable[PricePoint],
) -> list[WatchlistHit]:
    """AD-20 (CAP-15), on the Singapore run date `today`: `price_rises` is 3 or more
    price-rise alerts (their `detail`s) whose rising invoice is dated in the last 365
    days; `late` is an average of 7.00 or more days late, with up to 20 late receipt
    lines, latest first; `price_gap` is, for a material, a latest price at least 5%
    above the lowest latest price among the suppliers who posted it in the last 90
    days (`(latest - lowest) / lowest >= 0.05`, exact). By supplier, then rule."""
    hits = [
        *_price_rises_hits(today, rise_alerts),
        *_late_hits(today, on_time, late_lines),
        *_price_gap_hits(today, points),
    ]
    return sorted(hits, key=lambda h: (h.supplier_id, WATCHLIST_RULES.index(h.rule)))


def watchlist_dedupe_key(supplier_id: UUID, rule: str, first_added_on: date) -> str:
    """`analytics.alert.dedupe_key` of a watchlist alert: one per listing, so a
    supplier dropped and listed again is alerted again."""
    return f"{WATCHLIST}:{supplier_id}:{rule}:{first_added_on.isoformat()}"


def alternatives(
    today: date,
    material_id: UUID,
    exclude: UUID,
    points: Iterable[PricePoint],
    on_time_rates: Mapping[UUID, Decimal],
    names: Mapping[UUID, str],
) -> list[Alternative]:
    """CAP-16: the suppliers other than `exclude` with a posted price for
    `material_id` in the last 90 days, at their latest price there, ranked by that
    price, then on-time rate (best first, none last), then name."""
    latest = _latest_prices(points, today).get(material_id, {})
    ranked = sorted(
        (point for supplier_id, point in latest.items() if supplier_id != exclude),
        key=lambda p: (
            p.unit_price,
            on_time_rates.get(p.supplier_id) is None,
            -(on_time_rates.get(p.supplier_id) or Decimal(0)),
            (names.get(p.supplier_id) or "").casefold(),
            str(p.supplier_id),
        ),
    )
    return [
        Alternative(p.supplier_id, p.unit_price, on_time_rates.get(p.supplier_id))
        for p in ranked
    ]


def change_pct(prices: Sequence[Decimal]) -> Decimal | None:
    """Story 5.5 (CAP-17): the change from the first to the latest of a material's
    prices in the window, `(latest - first) / first * 100`, rounded half-up to 2
    places; None with fewer than 2 prices (or a first price that isn't above 0)."""
    if len(prices) < 2 or prices[0] <= 0:
        return None
    return money((prices[-1] - prices[0]) / prices[0] * 100)
