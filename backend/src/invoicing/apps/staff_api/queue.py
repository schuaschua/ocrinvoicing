"""`GET /api/admin/queue`: the admin queue list (Story 2.8, AD-4, AD-8, UX-DR9).

Admins only (`Surface.ADMIN_QUEUE`): 401 without a principal, 403 for any other role,
before anything is read. Query: `page` (1 or more, default 1), `reason` (an AD-4 code)
and `supplier_id` (a UUID); anything else in them is 400 `VALIDATION_FAILED`. Read-only.
"""

import re
from datetime import UTC
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

import azure.functions as func

from invoicing.adapters.http import Endpoint, json_response
from invoicing.adapters.principal import staff_endpoint
from invoicing.domain.errors import ValidationFailedError
from invoicing.domain.ids import parse_uuid
from invoicing.domain.reasons import ReasonCode
from invoicing.domain.roles import StaffPrincipal, Surface
from invoicing.ports.admin_queue import (
    PAGE_SIZE,
    AdminQueueReader,
    QueueListing,
    QueueQuery,
    QueueRow,
)

# A page number: a whole number from 1, short enough that the offset stays sane.
_PAGE = re.compile(r"[1-9][0-9]{0,5}")
# AD-8 / UX: the page-cap Alert shows from 80 % of this environment's monthly cap.
_WARN_NUMERATOR, _WARN_DENOMINATOR = 4, 5
_CENT = Decimal("0.01")


def _query(req: func.HttpRequest) -> QueueQuery:
    """The validated query; the messages never echo the value sent."""
    params = req.params
    page_text = params.get("page")
    page = 1
    if page_text is not None:
        if _PAGE.fullmatch(page_text) is None:
            raise ValidationFailedError("page must be a whole number from 1.")
        page = int(page_text)
    reason: ReasonCode | None = None
    reason_text = params.get("reason")
    if reason_text is not None:
        try:
            reason = ReasonCode(reason_text)
        except ValueError:
            raise ValidationFailedError("reason is not a known reason.") from None
    supplier_id: UUID | None = None
    supplier_text = params.get("supplier_id")
    if supplier_text is not None:
        supplier_id = parse_uuid(supplier_text)
        if supplier_id is None:
            raise ValidationFailedError("supplier_id must be a UUID.")
    return QueueQuery(page=page, reason=reason, supplier_id=supplier_id)


def _item(row: QueueRow, currency: str) -> dict[str, object]:
    # coding-style.md rule 4: the amount on the wire is a 2-decimal string.
    amount = (
        None
        if row.invoice_total is None
        else str(row.invoice_total.quantize(_CENT, rounding=ROUND_HALF_UP))
    )
    return {
        "invoice_id": str(row.invoice_id),
        "received_at": row.received_at.astimezone(UTC).isoformat(),
        "supplier_id": str(row.supplier_id),
        "supplier_name": row.supplier_name,
        "amount": amount,
        "currency": None if amount is None else currency,
        "reasons": list(row.reasons),
    }


def page_usage(pages_used: int, page_cap: int) -> dict[str, int] | None:
    """`{pages_used, page_cap}` from 80 % of the cap, else None: the client never
    works out the threshold itself."""
    if pages_used * _WARN_DENOMINATOR >= page_cap * _WARN_NUMERATOR:
        return {"pages_used": pages_used, "page_cap": page_cap}
    return None


def _body(
    listing: QueueListing, query: QueueQuery, *, page_cap: int, currency: str
) -> dict[str, object]:
    return {
        "items": [_item(row, currency) for row in listing.rows],
        "page": query.page,
        "page_size": PAGE_SIZE,
        "total": listing.total,
        "page_usage": page_usage(listing.pages_used, page_cap),
        "suppliers": [
            {"supplier_id": str(s.supplier_id), "supplier_name": s.name}
            for s in listing.suppliers
        ],
    }


def queue_endpoint(
    reader: AdminQueueReader,
    *,
    page_cap: int,
    currency: str,
    platform_auth_trusted: bool,
) -> Endpoint:
    """200 `{items, page, page_size, total, page_usage, suppliers}` for an admin; 400,
    401, 403 or 503 `DB_OFFLINE` otherwise. `platform_auth_trusted` has no default:
    the wiring must always pass the setting (AD-14: fail closed)."""

    async def admin_queue(
        req: func.HttpRequest, correlation_id: UUID, principal: StaffPrincipal
    ) -> func.HttpResponse:
        query = _query(req)
        listing = await reader.read(query)
        return json_response(
            _body(listing, query, page_cap=page_cap, currency=currency),
            status=200,
            correlation_id=correlation_id,
        )

    return staff_endpoint(
        admin_queue,
        surface=Surface.ADMIN_QUEUE,
        platform_auth_trusted=platform_auth_trusted,
    )
