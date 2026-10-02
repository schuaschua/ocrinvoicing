"""Suppliers list and supplier page for procurement, finance and management (Story 4.4,
Flow 5, AD-11):

- `GET api/suppliers`: `{items: [{supplier_id, name}], page, page_size, total}`, 50 a
  page, by name in any case then id. Query (both optional): `page` (1 or more) and
  `q`, 1 to 64 characters after trimming, matching names that contain it in any case
  (LIKE wildcards are literal). Anything else in them is 400 `VALIDATION_FAILED`.
- `GET api/suppliers/{supplier_id}`: `{supplier_id, name}`; 404 for an unknown or
  malformed id.
- `GET api/suppliers/{supplier_id}/deliveries` (Story 4.5, CAP-19): the supplier's
  deliveries of the last 365 days (Singapore date), newest first, at most 200:
  `{items: [{po_number, delivery_no, promised_date, delivered_date, received_date,
  days_late, days_to_receive, days_overall}], truncated}`. Read from `PurchasingPort`
  only (AD-10), after the supplier is found in the master; the gaps come from the
  domain (domain/deliveries.py).
- `GET api/suppliers/{supplier_id}/scorecard` (Story 5.5, CAP-17, AD-20): `{on_time:
  {rate, receipts, on_time, avg_days_late} | null, materials: [{material_id, name,
  change_pct, latest_unit_price, points: [{invoice_date, unit_price}]}]}`. `on_time`
  is the supplier's `analytics.supplier_on_time` row (receipt lines of the last 365
  days), null with none. Each material has its posted prices of the last 365 days
  (Singapore date, today included), oldest first; `change_pct` is first to latest in
  percent, null with one price. Materials by name; one `analytics.material` hasn't
  named yet is left out until the refresh job names it, as on Price comparison.
  Money and `change_pct` are 2-decimal strings, `rate` 4-decimal, `avg_days_late`
  2-decimal. Read from `DashboardReader` only (AD-13: never the invoice or
  purchasing tables), after the supplier is found in the master.

Only `master.supplier.id` and `name` are read: never a tax id, phone or bank field.
`Surface.SUPPLIERS` and `Surface.SUPPLIER_SCORECARD`: 401 signed out; any other role
gets 403 on the list and 404 on one supplier, its deliveries or its scorecard
(security.md rule 5), before anything is
read. Read-only; no value sent or read is ever logged."""

import re
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

import azure.functions as func

from invoicing.adapters.http import Endpoint, json_response
from invoicing.adapters.principal import NOT_FOUND_MESSAGE, staff_endpoint
from invoicing.apps.staff_api.watchlist import days_text
from invoicing.domain.analytics import PricePoint, change_pct, money
from invoicing.domain.dates import singapore_date
from invoicing.domain.deliveries import delivery_gaps
from invoicing.domain.errors import NotFoundError, ValidationFailedError
from invoicing.domain.ids import parse_uuid
from invoicing.domain.roles import StaffPrincipal, Surface
from invoicing.ports.dashboards import DashboardReader, Scorecard
from invoicing.ports.purchasing import (
    SUPPLIER_DELIVERIES_MAX,
    PurchasingPort,
    SupplierDelivery,
)
from invoicing.ports.suppliers import SUPPLIER_PAGE_SIZE, SupplierDirectory

_PAGE = re.compile(r"[1-9][0-9]{0,5}")
# The search box (`q`), after trimming.
MAX_SEARCH_TEXT = 64
# Story 4.5: how far back the Deliveries tab looks.
DELIVERY_DAYS = 365
# Story 5.5 (AD-20): how far back the Scorecard's price trend looks.
SCORECARD_DAYS = 365
_RATE = Decimal("0.0001")


def _unsigned_zero(value: Decimal) -> Decimal:
    """`value`, with a negative zero (-0.00) as 0.00."""
    return abs(value) if value == 0 else value


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(day: date | None) -> str | None:
    return None if day is None else day.isoformat()


def _delivery_item(entry: SupplierDelivery) -> dict[str, object]:
    dates = entry.dates
    gaps = delivery_gaps(dates.promised_date, dates.delivered_date, dates.received_date)
    return {
        "po_number": entry.po_number,
        "delivery_no": entry.delivery_no,
        "promised_date": _iso(dates.promised_date),
        "delivered_date": _iso(dates.delivered_date),
        "received_date": _iso(dates.received_date),
        "days_late": gaps.days_late,
        "days_to_receive": gaps.days_to_receive,
        "days_overall": gaps.days_overall,
    }


def _scorecard_body(found: Scorecard, today: date) -> dict[str, object]:
    by_material: dict[UUID, list[PricePoint]] = {}
    for point in found.points:  # by material, then oldest first
        if point.invoice_date <= today:
            by_material.setdefault(point.material_id, []).append(point)
    named = [
        (found.material_names[m], m) for m in by_material if m in found.material_names
    ]
    held = found.on_time
    on_time = (
        None
        if held is None
        else {
            "rate": str(held.on_time_rate.quantize(_RATE, rounding=ROUND_HALF_UP)),
            "receipts": held.receipts,
            "on_time": held.on_time,
            "avg_days_late": days_text(_unsigned_zero(held.avg_days_late)),
        }
    )
    materials = []
    for name, material_id in sorted(named, key=lambda n: (n[0].casefold(), n)):
        points = by_material[material_id]
        change = change_pct([p.unit_price for p in points])
        materials.append(
            {
                "material_id": str(material_id),
                "name": name,
                "change_pct": None if change is None else str(_unsigned_zero(change)),
                "latest_unit_price": str(money(points[-1].unit_price)),
                "points": [
                    {
                        "invoice_date": p.invoice_date.isoformat(),
                        "unit_price": str(money(p.unit_price)),
                    }
                    for p in points
                ],
            }
        )
    return {"on_time": on_time, "materials": materials}


def _query(req: func.HttpRequest) -> tuple[str | None, int]:
    """The validated (text, page); the messages never echo the value sent."""
    page = 1
    page_text = req.params.get("page")
    if page_text is not None:
        if _PAGE.fullmatch(page_text) is None:
            raise ValidationFailedError("page must be a whole number from 1.")
        page = int(page_text)
    text: str | None = None
    q_text = req.params.get("q")
    if q_text is not None:
        text = q_text.strip()
        # PostgreSQL refuses a NUL in text: a 400 here, not a 500 from the query.
        if not text or len(text) > MAX_SEARCH_TEXT or "\x00" in text:
            raise ValidationFailedError(f"q must be 1 to {MAX_SEARCH_TEXT} characters.")
    return text, page


def suppliers_endpoints(
    directory: SupplierDirectory,
    purchasing: PurchasingPort,
    dashboards: DashboardReader,
    *,
    platform_auth_trusted: bool,
    clock: Callable[[], datetime] | None = None,
) -> tuple[Endpoint, Endpoint, Endpoint, Endpoint]:
    """(list, one supplier, its deliveries, its scorecard). `platform_auth_trusted`
    has no default: the wiring must always pass the setting (AD-14: fail closed).
    `clock` defaults to the current UTC time."""

    async def known_supplier(req: func.HttpRequest) -> tuple[UUID, str]:
        """The route's supplier and its master name; 404 when unknown or malformed."""
        supplier_id = parse_uuid(req.route_params.get("supplier_id"))
        if supplier_id is None:
            raise NotFoundError(NOT_FOUND_MESSAGE)
        name = await directory.get_name(supplier_id)
        if name is None:
            raise NotFoundError(NOT_FOUND_MESSAGE)
        return supplier_id, name

    async def supplier_list(
        req: func.HttpRequest, correlation_id: UUID, principal: StaffPrincipal
    ) -> func.HttpResponse:
        text, page = _query(req)
        entries, total = await directory.page(text, page)
        return json_response(
            {
                "items": [
                    {"supplier_id": str(e.supplier_id), "name": e.name} for e in entries
                ],
                "page": page,
                "page_size": SUPPLIER_PAGE_SIZE,
                "total": total,
            },
            status=200,
            correlation_id=correlation_id,
        )

    async def supplier_detail(
        req: func.HttpRequest, correlation_id: UUID, principal: StaffPrincipal
    ) -> func.HttpResponse:
        supplier_id, name = await known_supplier(req)
        return json_response(
            {"supplier_id": str(supplier_id), "name": name},
            status=200,
            correlation_id=correlation_id,
        )

    async def supplier_deliveries(
        req: func.HttpRequest, correlation_id: UUID, principal: StaffPrincipal
    ) -> func.HttpResponse:
        # The master first: an unknown supplier is 404 before purchasing is read.
        supplier_id, _ = await known_supplier(req)
        # The last 365 days, today (Singapore) included.
        today = singapore_date((clock or _now)())
        since = today - timedelta(days=DELIVERY_DAYS - 1)
        found = await purchasing.supplier_delivery_dates(supplier_id, since)
        return json_response(
            {
                "items": [_delivery_item(e) for e in found[:SUPPLIER_DELIVERIES_MAX]],
                "truncated": len(found) > SUPPLIER_DELIVERIES_MAX,
            },
            status=200,
            correlation_id=correlation_id,
        )

    async def supplier_scorecard(
        req: func.HttpRequest, correlation_id: UUID, principal: StaffPrincipal
    ) -> func.HttpResponse:
        # The master first: an unknown supplier is 404 before analytics is read.
        supplier_id, _ = await known_supplier(req)
        today = singapore_date((clock or _now)())
        since = today - timedelta(days=SCORECARD_DAYS - 1)
        found = await dashboards.scorecard(supplier_id, since)
        return json_response(
            _scorecard_body(found, today), status=200, correlation_id=correlation_id
        )

    return (
        staff_endpoint(
            supplier_list,
            surface=Surface.SUPPLIERS,
            platform_auth_trusted=platform_auth_trusted,
        ),
        staff_endpoint(
            supplier_detail,
            surface=Surface.SUPPLIER_SCORECARD,
            platform_auth_trusted=platform_auth_trusted,
            hide_from_others=True,
        ),
        staff_endpoint(
            supplier_deliveries,
            surface=Surface.SUPPLIER_SCORECARD,
            platform_auth_trusted=platform_auth_trusted,
            hide_from_others=True,
        ),
        staff_endpoint(
            supplier_scorecard,
            surface=Surface.SUPPLIER_SCORECARD,
            platform_auth_trusted=platform_auth_trusted,
            hide_from_others=True,
        ),
    )
