"""AD-20 analytics rules (Story 5.1): the pure part of the analytics refresh job's
daily summaries. The adapter reads the rows and writes what these return. Story 5.3
adds the price-rise rule (CAP-14), evaluated in the same step.

Months are the first day of a Singapore month. Money is `Decimal` rounded half-up to
2 places, rates to 4 (`numeric(18,2)` and `numeric(5,4)` in `analytics`). The
currency is the configured invoice currency (SGD, AD-20), so none is carried.
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
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
