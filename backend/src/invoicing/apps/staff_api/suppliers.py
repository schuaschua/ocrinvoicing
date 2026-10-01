"""Suppliers list and supplier page for procurement, finance and management (Story 4.4,
Flow 5, AD-11):

- `GET api/suppliers`: `{items: [{supplier_id, name}], page, page_size, total}`, 50 a
  page, by name in any case then id. Query (both optional): `page` (1 or more) and
  `q`, 1 to 64 characters after trimming, matching names that contain it in any case
  (LIKE wildcards are literal). Anything else in them is 400 `VALIDATION_FAILED`.
- `GET api/suppliers/{supplier_id}`: `{supplier_id, name}`; 404 for an unknown or
  malformed id.

Only `master.supplier.id` and `name` are read: never a tax id, phone or bank field.
`Surface.SUPPLIERS` and `Surface.SUPPLIER_SCORECARD`: 401 signed out; any other role
gets 403 on the list and 404 on one supplier (security.md rule 5), before anything is
read. Read-only; no value sent or read is ever logged."""

import re
from uuid import UUID

import azure.functions as func

from invoicing.adapters.http import Endpoint, json_response
from invoicing.adapters.principal import NOT_FOUND_MESSAGE, staff_endpoint
from invoicing.domain.errors import NotFoundError, ValidationFailedError
from invoicing.domain.ids import parse_uuid
from invoicing.domain.roles import StaffPrincipal, Surface
from invoicing.ports.suppliers import SUPPLIER_PAGE_SIZE, SupplierDirectory

_PAGE = re.compile(r"[1-9][0-9]{0,5}")
# The search box (`q`), after trimming.
MAX_SEARCH_TEXT = 64


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
    *,
    platform_auth_trusted: bool,
) -> tuple[Endpoint, Endpoint]:
    """(list, one supplier). `platform_auth_trusted` has no default: the wiring must
    always pass the setting (AD-14: fail closed)."""

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
        supplier_id = parse_uuid(req.route_params.get("supplier_id"))
        if supplier_id is None:
            raise NotFoundError(NOT_FOUND_MESSAGE)
        name = await directory.get_name(supplier_id)
        if name is None:
            raise NotFoundError(NOT_FOUND_MESSAGE)
        return json_response(
            {"supplier_id": str(supplier_id), "name": name},
            status=200,
            correlation_id=correlation_id,
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
    )
