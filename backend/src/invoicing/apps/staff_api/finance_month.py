"""Finance month (Story 5.6, CAP-18, FR18, NFR19, AD-13, AD-20): one month's figures
per supplier and the straight-through share against the 90% target, from the
`analytics` tables the refresh job writes, never the invoice tables.

- `GET api/finance-month?month=YYYY-MM`: `{month, months, straight_through: {share,
  posted_count, straight_through_count, target}, history: [{month, share}],
  suppliers: [{supplier_id, supplier_name, spend, posted_count, price_rises,
  flagged_count, duplicate_count}]}`.
  - Without `month`: the latest month with any data, else the current Singapore
    month. `months` are the months with any data, newest first.
  - Spend and posted count by posted month (`supplier_month`), flags by received
    month (`supplier_month_flags`), price rises by the rising invoice's date, the
    share from `month_summary` (Story 5.1 rules). A supplier is listed when it has
    any of these in the month; by spend (highest first), then name (unnamed last).
  - `share` is null with nothing posted in the month. `history` is the shares of
    the last 24 months ending at the shown one, oldest first, for the page's chart.
    Months later than the current Singapore month are never listed or defaulted to.
  - Money is a 2-decimal string, rates 4-decimal strings. A malformed `month` is
    400 `VALIDATION_FAILED`; the message never echoes it.

`Surface.FINANCE_MONTH` (finance, management): 401 signed out, 403 for any other
role, before anything is read; 503 `DB_OFFLINE` when the database is stopped.
Supplier names come from the master directory.
"""

import re
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import azure.functions as func

from invoicing.adapters.http import Endpoint, json_response
from invoicing.adapters.principal import staff_endpoint
from invoicing.domain.analytics import singapore_month
from invoicing.domain.errors import ValidationFailedError
from invoicing.domain.roles import StaffPrincipal, Surface
from invoicing.ports.dashboards import DashboardReader, SupplierMonthRow
from invoicing.ports.suppliers import SupplierDirectory

# NFR19: at least 90% of invoices posted without an admin.
STRAIGHT_THROUGH_TARGET = Decimal("0.9000")
_CENT = Decimal("0.01")
_RATE = Decimal("0.0001")
_MONTH = re.compile(r"[0-9]{4}-[0-9]{2}")
_BAD_MONTH = "month must be a month as YYYY-MM."
# Plausible invoice years only; also keeps the month after any accepted one valid.
_YEARS = range(2000, 2101)


def _now() -> datetime:
    return datetime.now(UTC)


def _rate(value: Decimal) -> str:
    return str(value.quantize(_RATE))


def _month_text(month: date) -> str:
    return month.isoformat()[:7]


def parse_month(raw: str | None) -> date | None:
    """`raw` (YYYY-MM) as its first day; None when absent. Malformed is 400."""
    if raw is None:
        return None
    if not _MONTH.fullmatch(raw):
        raise ValidationFailedError(_BAD_MONTH)
    try:
        month = date.fromisoformat(f"{raw}-01")
    except ValueError:
        raise ValidationFailedError(_BAD_MONTH) from None
    if month.year not in _YEARS:
        raise ValidationFailedError(_BAD_MONTH)
    return month


def finance_month_endpoint(
    reader: DashboardReader,
    suppliers: SupplierDirectory,
    *,
    platform_auth_trusted: bool,
    clock: Callable[[], datetime] = _now,
) -> Endpoint:
    """The Finance month endpoint. `platform_auth_trusted` has no default: the wiring
    must always pass the setting (AD-14: fail closed)."""

    async def finance_month(
        req: func.HttpRequest, correlation_id: UUID, principal: StaffPrincipal
    ) -> func.HttpResponse:
        requested = parse_month(req.params.get("month"))
        found = await reader.finance_month(requested, singapore_month(clock()))
        rows = {row.supplier_id: row for row in found.suppliers}
        listed = set(rows) | {key for key, n in found.price_rises.items() if n > 0}
        names = await suppliers.names(listed)

        def row_of(supplier_id: UUID) -> SupplierMonthRow:
            return rows.get(supplier_id) or SupplierMonthRow(
                supplier_id=supplier_id,
                month=found.month,
                spend=Decimal("0.00"),
                posted_count=0,
                flagged_count=0,
                duplicate_count=0,
            )

        def order(supplier_id: UUID) -> tuple[Decimal, bool, str, str]:
            # Among equal spend: named by name, then unnamed, each then by id.
            name = names.get(supplier_id)
            return (
                -row_of(supplier_id).spend,
                name is None,
                (name or "").casefold(),
                str(supplier_id),
            )

        summary = found.summary
        return json_response(
            {
                "month": _month_text(found.month),
                "months": [_month_text(month) for month in found.months],
                "straight_through": {
                    "share": None
                    if summary is None
                    else _rate(summary.straight_through_share),
                    "posted_count": 0 if summary is None else summary.posted_count,
                    "straight_through_count": 0
                    if summary is None
                    else summary.straight_through_count,
                    "target": str(STRAIGHT_THROUGH_TARGET),
                },
                "history": [
                    {
                        "month": _month_text(item.month),
                        "share": _rate(item.straight_through_share),
                    }
                    for item in found.history
                ],
                "suppliers": [
                    {
                        "supplier_id": str(supplier_id),
                        "supplier_name": names.get(supplier_id),
                        "spend": str(row_of(supplier_id).spend.quantize(_CENT)),
                        "posted_count": row_of(supplier_id).posted_count,
                        "price_rises": found.price_rises.get(supplier_id, 0),
                        "flagged_count": row_of(supplier_id).flagged_count,
                        "duplicate_count": row_of(supplier_id).duplicate_count,
                    }
                    for supplier_id in sorted(listed, key=order)
                ],
            },
            status=200,
            correlation_id=correlation_id,
        )

    return staff_endpoint(
        finance_month,
        surface=Surface.FINANCE_MONTH,
        platform_auth_trusted=platform_auth_trusted,
    )
