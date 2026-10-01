"""Watchlist (Story 5.4, CAP-15, CAP-16, FR15, FR16, AD-13, AD-20): the suppliers the
analytics refresh job listed, with their evidence and the ranked alternatives for each
material involved, from the `analytics` tables only, never the invoice tables or
purchasing.

- `GET api/watchlist`: `{has_price_points, entries: [{supplier_id, supplier_name,
  rules: [{rule, first_added_on, avg_days_late, evidence: [...]}], alternatives:
  [{material_id, material_name, suppliers: [{supplier_id, supplier_name,
  latest_unit_price, on_time_rate, watchlisted}]}]}]}`. Entries by their most recent
  `first_added_on`, then supplier name; rules in AD-20 order (`price_rises`, `late`,
  `price_gap`). Evidence per rule:
  - `price_rises`: `{material_id, material_name, invoice_id, invoice_date,
    unit_price, previous_invoice_id, previous_invoice_date, previous_unit_price,
    pct}`, latest first;
  - `late`: `{material_id, material_name, received_date, days_late}`, latest first,
    at most 20; the rule carries the supplier's `avg_days_late` (null on others);
  - `price_gap`: `{material_id, material_name, invoice_id, invoice_date, unit_price,
    lowest_unit_price, cheapest_supplier_id, cheapest_supplier_name, pct}`.
  Alternatives are computed here (CAP-16) for every material in the evidence and,
  for `late`, of every late receipt line in the last 365 days (not only the 20
  shown): the other suppliers with a posted price for the material in the last 90
  days, by latest price, then on-time rate (best first, none last), then name, each
  marked `watchlisted` when it is itself on the watchlist. `has_price_points` tells the page's two empty states
  apart. Money is a 2-decimal string, rates 4-decimal strings or null. Evidence
  invoice ids go only to the roles that can open an invoice (admin, finance;
  EXPERIENCE.md Evidence list), so they are null for the Watchlist's roles.

`Surface.WATCHLIST` (procurement, management): 401 signed out, 403 for any other role,
before anything is read; 503 `DB_OFFLINE` when the database is stopped. Supplier names
come from the master directory.
"""

from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import azure.functions as func

from invoicing.adapters.http import Endpoint, json_response
from invoicing.adapters.principal import staff_endpoint
from invoicing.domain.analytics import (
    RULE_LATE,
    RULE_PRICE_GAP,
    RULE_PRICE_RISES,
    WATCHLIST_RULES,
    alternatives,
)
from invoicing.domain.dates import singapore_date
from invoicing.domain.roles import SURFACE_ROLES, StaffPrincipal, Surface
from invoicing.ports.dashboards import DashboardReader, WatchlistRow
from invoicing.ports.suppliers import SupplierDirectory

_CENT = Decimal("0.01")
_RATE = Decimal("0.0001")


def _now() -> datetime:
    return datetime.now(UTC)


def _money(value: Decimal | str) -> str:
    return str(Decimal(value).quantize(_CENT))


def days_text(value: Decimal) -> str:
    """An average number of days, 2 decimals (`supplier_on_time.avg_days_late`)."""
    return str(value.quantize(_CENT))


def _rate(value: Decimal | None) -> str | None:
    return None if value is None else str(value.quantize(_RATE))


def _materials(row: WatchlistRow) -> list[str]:
    return [str(item["material_id"]) for item in row.evidence]


def watchlist_endpoint(
    reader: DashboardReader,
    suppliers: SupplierDirectory,
    *,
    platform_auth_trusted: bool,
    clock: Callable[[], datetime] = _now,
) -> Endpoint:
    """`GET api/watchlist`. `platform_auth_trusted` has no default: the wiring must
    always pass the setting (AD-14: fail closed)."""

    async def watchlist(
        req: func.HttpRequest, correlation_id: UUID, principal: StaffPrincipal
    ) -> func.HttpResponse:
        today = singapore_date(clock())
        found = await reader.watchlist(today)
        # Only the roles that can open an invoice see which one (EXPERIENCE.md).
        show_invoice = principal.has_any(SURFACE_ROLES[Surface.INVOICES])

        def invoice(held: Any) -> str | None:
            return None if not show_invoice or held is None else str(held)

        listed_set = {row.supplier_id for row in found.rows}
        listed = sorted(listed_set)
        wanted = set(listed) | {point.supplier_id for point in found.points}
        wanted |= {
            UUID(item["cheapest_supplier_id"])
            for row in found.rows
            if row.rule == RULE_PRICE_GAP
            for item in row.evidence
        }
        names = await suppliers.names(wanted)
        rates = {key: held.on_time_rate for key, held in found.on_time.items()}

        def material(held: Any) -> dict[str, Any]:
            key = UUID(str(held))
            return {
                "material_id": str(key),
                "material_name": found.material_names.get(key),
            }

        def evidence(row: WatchlistRow) -> list[dict[str, Any]]:
            if row.rule == RULE_PRICE_RISES:
                return [
                    {
                        **material(item["material_id"]),
                        "invoice_id": invoice(item["current"].get("invoice_id")),
                        "invoice_date": item["current"]["invoice_date"],
                        "unit_price": _money(item["current"]["unit_price"]),
                        "previous_invoice_id": invoice(
                            item["previous"].get("invoice_id")
                        ),
                        "previous_invoice_date": item["previous"]["invoice_date"],
                        "previous_unit_price": _money(item["previous"]["unit_price"]),
                        "pct": _money(item["pct"]),
                    }
                    for item in row.evidence
                ]
            if row.rule == RULE_LATE:
                return [
                    {
                        **material(item["material_id"]),
                        "received_date": item["received_date"],
                        "days_late": int(item["days_late"]),
                    }
                    for item in row.evidence
                ]
            return [
                {
                    **material(item["material_id"]),
                    "invoice_id": invoice(item.get("invoice_id")),
                    "invoice_date": item["invoice_date"],
                    "unit_price": _money(item["unit_price"]),
                    "lowest_unit_price": _money(item["lowest_unit_price"]),
                    "cheapest_supplier_id": item["cheapest_supplier_id"],
                    "cheapest_supplier_name": names.get(
                        UUID(item["cheapest_supplier_id"])
                    ),
                    "pct": _money(item["pct"]),
                }
                for item in row.evidence
            ]

        def avg_days_late(supplier_id: UUID, rule: str) -> str | None:
            held = found.on_time.get(supplier_id)
            if rule != RULE_LATE or held is None:
                return None
            return days_text(held.avg_days_late)

        entries: list[tuple[date, str, dict[str, Any]]] = []
        for supplier_id in listed:
            rows = sorted(
                (row for row in found.rows if row.supplier_id == supplier_id),
                key=lambda row: WATCHLIST_RULES.index(row.rule),
            )
            materials = list(
                dict.fromkeys(
                    [key for row in rows for key in _materials(row)]
                    + [
                        str(key)
                        for key in found.late_materials.get(supplier_id, ())
                        if any(row.rule == RULE_LATE for row in rows)
                    ]
                )
            )
            name = names.get(supplier_id)
            entry = {
                "supplier_id": str(supplier_id),
                "supplier_name": name,
                "rules": [
                    {
                        "rule": row.rule,
                        "first_added_on": row.first_added_on.isoformat(),
                        "avg_days_late": avg_days_late(supplier_id, row.rule),
                        "evidence": evidence(row),
                    }
                    for row in rows
                ],
                "alternatives": [
                    {
                        **material(key),
                        "suppliers": [
                            {
                                "supplier_id": str(item.supplier_id),
                                "supplier_name": names.get(item.supplier_id),
                                "latest_unit_price": _money(item.latest_unit_price),
                                "on_time_rate": _rate(item.on_time_rate),
                                "watchlisted": item.supplier_id in listed_set,
                            }
                            for item in alternatives(
                                today,
                                UUID(key),
                                supplier_id,
                                found.points,
                                rates,
                                names,
                            )
                        ],
                    }
                    for key in materials
                ],
            }
            newest = max(row.first_added_on for row in rows)
            entries.append((newest, (name or "").casefold(), entry))
        # The most recently listed first, then by name (and id, for a stable order).
        entries.sort(key=lambda e: (-e[0].toordinal(), e[1], e[2]["supplier_id"]))
        return json_response(
            {
                "has_price_points": found.has_price_points,
                "entries": [entry for _, _, entry in entries],
            },
            status=200,
            correlation_id=correlation_id,
        )

    return staff_endpoint(
        watchlist,
        surface=Surface.WATCHLIST,
        platform_auth_trusted=platform_auth_trusted,
    )
