"""Overdue POs (Story 4.2, CAP-12, AD-13): the list the analytics refresh job made.

- `GET api/overdue-pos`: `{made_at, suppliers: [{supplier_id, supplier_name, pos:
  [{po_number, expected_date}]}]}`. `made_at` is when the latest run finished (ISO 8601
  UTC), or null when no run has made the list yet. Suppliers are sorted by name (a
  supplier the master doesn't have, with a null name, last, by id), and each
  supplier's POs by expected date then PO number.

Read-only, from `analytics` only (AD-13: dashboards never compute). `Surface.OVERDUE_POS`
(admin, procurement, finance): 401 signed out, 403 for any other role, before anything
is read; 503 `DB_OFFLINE` when the database is stopped.
"""

from collections import defaultdict
from datetime import UTC
from uuid import UUID

import azure.functions as func

from invoicing.adapters.http import Endpoint, json_response
from invoicing.adapters.principal import staff_endpoint
from invoicing.domain.roles import StaffPrincipal, Surface
from invoicing.ports.analytics import OverdueReader
from invoicing.ports.purchasing import OverduePo
from invoicing.ports.suppliers import SupplierDirectory


def overdue_endpoint(
    reader: OverdueReader,
    suppliers: SupplierDirectory,
    *,
    platform_auth_trusted: bool,
) -> Endpoint:
    """`platform_auth_trusted` has no default: the wiring must always pass the
    setting (AD-14: fail closed)."""

    async def overdue_pos(
        req: func.HttpRequest, correlation_id: UUID, principal: StaffPrincipal
    ) -> func.HttpResponse:
        listed = await reader.overdue_list()
        by_supplier: dict[UUID, list[OverduePo]] = defaultdict(list)
        for po in listed.pos:
            by_supplier[po.supplier_id].append(po)
        names = await suppliers.names(by_supplier)

        def order(supplier_id: UUID) -> tuple[bool, str, str]:
            name = names.get(supplier_id)
            return (name is None, (name or "").casefold(), str(supplier_id))

        made_at = listed.made_at
        return json_response(
            {
                "made_at": None
                if made_at is None
                else made_at.astimezone(UTC).isoformat(),
                "suppliers": [
                    {
                        "supplier_id": str(supplier_id),
                        "supplier_name": names.get(supplier_id),
                        "pos": [
                            {
                                "po_number": po.po_number,
                                "expected_date": po.expected_date.isoformat(),
                            }
                            for po in sorted(
                                by_supplier[supplier_id],
                                key=lambda po: (po.expected_date, po.po_number),
                            )
                        ],
                    }
                    for supplier_id in sorted(by_supplier, key=order)
                ],
            },
            status=200,
            correlation_id=correlation_id,
        )

    return staff_endpoint(
        overdue_pos,
        surface=Surface.OVERDUE_POS,
        platform_auth_trusted=platform_auth_trusted,
    )
