"""Price comparison (Story 5.3, CAP-14, FR14, AD-13, AD-20): suppliers' prices for one
material, from the `analytics` tables the refresh job writes, never the invoice tables
or purchasing.

- `GET api/materials`: `{items: [{material_id, name}]}`, the materials with posted
  prices, by name.
- `GET api/price-comparison?material_id=`: `{material_id, name, suppliers:
  [{supplier_id, supplier_name, latest_unit_price, latest_invoice_date,
  on_time_rate}], history: [{supplier_id, invoice_date, unit_price}], alerts:
  [{alert_id, created_at, supplier_id, supplier_name, pct, evidence: [{invoice_id,
  invoice_date, unit_price}]}]}`. Only suppliers with a price in the history window
  are listed, at their latest price there, sorted by latest price, then on-time
  rate (best first, none last), then name; `history` covers the last 365 days (Singapore dates,
  today included); alerts newest first, each with the previous and the rising price
  as evidence. Money is a 2-decimal string, rates 4-decimal strings or null.
  Evidence `invoice_id`s go only to the roles that can open an invoice (admin,
  finance; EXPERIENCE.md Evidence list); others get null. An unknown or malformed
  `material_id` is 404.

`Surface.PRICE_COMPARISON` (procurement, finance): 401 signed out, 403 for any other
role, before anything is read; 503 `DB_OFFLINE` when the database is stopped.
Supplier names come from the master directory.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import azure.functions as func

from invoicing.adapters.http import Endpoint, json_response
from invoicing.adapters.principal import NOT_FOUND_MESSAGE, staff_endpoint
from invoicing.domain.analytics import PricePoint
from invoicing.domain.dates import singapore_date
from invoicing.domain.errors import NotFoundError
from invoicing.domain.ids import parse_uuid
from invoicing.domain.roles import SURFACE_ROLES, StaffPrincipal, Surface
from invoicing.ports.dashboards import DashboardReader
from invoicing.ports.suppliers import SupplierDirectory

# AD-20: the last 365 days, today included.
HISTORY_WINDOW = timedelta(days=364)
_CENT = Decimal("0.01")
_RATE = Decimal("0.0001")


def _now() -> datetime:
    return datetime.now(UTC)


def _money(value: Decimal | str) -> str:
    return str(Decimal(value).quantize(_CENT))


def _evidence(held: dict[str, Any], show_invoice: bool) -> dict[str, Any]:
    return {
        "invoice_id": held.get("invoice_id") if show_invoice else None,
        "invoice_date": held.get("invoice_date"),
        "unit_price": _money(held["unit_price"]),
    }


def price_comparison_endpoints(
    reader: DashboardReader,
    suppliers: SupplierDirectory,
    *,
    platform_auth_trusted: bool,
    clock: Callable[[], datetime] = _now,
) -> tuple[Endpoint, Endpoint]:
    """(materials, price comparison). `platform_auth_trusted` has no default: the
    wiring must always pass the setting (AD-14: fail closed)."""

    async def materials(
        req: func.HttpRequest, correlation_id: UUID, principal: StaffPrincipal
    ) -> func.HttpResponse:
        listed = await reader.materials()
        return json_response(
            {
                "items": [
                    {"material_id": str(item.material_id), "name": item.name}
                    for item in listed
                ]
            },
            status=200,
            correlation_id=correlation_id,
        )

    async def price_comparison(
        req: func.HttpRequest, correlation_id: UUID, principal: StaffPrincipal
    ) -> func.HttpResponse:
        material_id = parse_uuid(req.params.get("material_id"))
        found = (
            None if material_id is None else await reader.price_comparison(material_id)
        )
        if found is None:
            raise NotFoundError(NOT_FOUND_MESSAGE)
        # Only the roles that can open an invoice see which one (EXPERIENCE.md).
        show_invoice = principal.has_any(SURFACE_ROLES[Surface.INVOICES])
        # Only suppliers with a price in the window, at their latest one there, so
        # the table, the chart and its "lowest" summary agree.
        since = singapore_date(clock()) - HISTORY_WINDOW
        recent = [point for point in found.points if point.invoice_date >= since]
        latest: dict[UUID, PricePoint] = {}
        for point in recent:  # in date, invoice, line order per supplier
            latest[point.supplier_id] = point
        names = await suppliers.names(
            set(latest) | {item.supplier_id for item in found.alerts}
        )

        def order(supplier_id: UUID) -> tuple[Decimal, bool, Decimal, str, str]:
            held = found.on_time_rates.get(supplier_id)
            name = names.get(supplier_id) or ""
            return (
                latest[supplier_id].unit_price,
                held is None,
                -(held or Decimal(0)),
                name.casefold(),
                str(supplier_id),
            )

        def rate(supplier_id: UUID) -> str | None:
            held = found.on_time_rates.get(supplier_id)
            return None if held is None else str(held.quantize(_RATE))

        return json_response(
            {
                "material_id": str(found.material.material_id),
                "name": found.material.name,
                "suppliers": [
                    {
                        "supplier_id": str(supplier_id),
                        "supplier_name": names.get(supplier_id),
                        "latest_unit_price": _money(latest[supplier_id].unit_price),
                        "latest_invoice_date": latest[
                            supplier_id
                        ].invoice_date.isoformat(),
                        "on_time_rate": rate(supplier_id),
                    }
                    for supplier_id in sorted(latest, key=order)
                ],
                "history": [
                    {
                        "supplier_id": str(point.supplier_id),
                        "invoice_date": point.invoice_date.isoformat(),
                        "unit_price": _money(point.unit_price),
                    }
                    for point in recent
                ],
                "alerts": [
                    {
                        "alert_id": str(item.alert_id),
                        "created_at": item.created_at.astimezone(UTC).isoformat(),
                        "supplier_id": str(item.supplier_id),
                        "supplier_name": names.get(item.supplier_id),
                        "pct": _money(item.detail["pct"]),
                        "evidence": [
                            _evidence(item.detail[key], show_invoice)
                            for key in ("previous", "current")
                        ],
                    }
                    for item in found.alerts
                ],
            },
            status=200,
            correlation_id=correlation_id,
        )

    return (
        staff_endpoint(
            materials,
            surface=Surface.PRICE_COMPARISON,
            platform_auth_trusted=platform_auth_trusted,
        ),
        staff_endpoint(
            price_comparison,
            surface=Surface.PRICE_COMPARISON,
            platform_auth_trusted=platform_auth_trusted,
        ),
    )
