"""Invoice search and detail for admin and finance (Story 3.4, AD-3, AD-11, AD-18):

- `GET api/invoices`: every invoice, newest first, 50 a page. Query (all optional,
  combined): `page` (1 or more), `supplier_id` (a UUID), `status` (AD-3 codes,
  comma-separated), `invoice_number` (matched on the AD-18 current value, normalised
  like the duplicate check) and `reference` (a supplier reference, `R-` and 8
  characters, any case), and `q`, the one search box: 1 to 64 characters after
  trimming, matching an invoice's supplier reference, its normalised invoice number
  or its supplier's name (contains, any case). Anything else in them is 400
  `VALIDATION_FAILED`.
- `GET api/invoices/{invoice_id}`: its current fields (bank fields only as
  `bank_on_file`, never a value or mask), lines, status history (actor categories
  only) and accounts reference. No image endpoint on this surface.

`Surface.INVOICES` (admin, finance): 401 signed out; any other role gets 403 on the
search and 404 on the detail (security.md rule 5), before anything is read. Read-only;
no value sent or read is ever logged."""

import re
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from uuid import UUID

import azure.functions as func

from invoicing.adapters.http import Endpoint, json_response
from invoicing.adapters.principal import NOT_FOUND_MESSAGE, staff_endpoint
from invoicing.apps.staff_api.item import invoice_id_of
from invoicing.domain.errors import NotFoundError, ValidationFailedError
from invoicing.domain.ids import parse_uuid
from invoicing.domain.reference import parse_reference, supplier_reference
from invoicing.domain.roles import StaffPrincipal, Surface
from invoicing.domain.status import InvoiceStatus, Stage
from invoicing.domain.validation import normalise_invoice_number
from invoicing.ports.invoice_search import (
    PAGE_SIZE,
    InvoiceDetail,
    InvoiceSearchReader,
    SearchListing,
    SearchQuery,
    SearchRow,
)

_PAGE = re.compile(r"[1-9][0-9]{0,5}")
# Longer than any invoice number; refused unread beyond it.
MAX_INVOICE_NUMBER = 64
# The one search box (`q`), after trimming.
MAX_SEARCH_TEXT = 64
_CENT = Decimal("0.01")
_PIPELINE = "pipeline:"
_ADMIN = "admin:"
_STAGES = frozenset(stage.value for stage in Stage)


def actor_category(actor: str) -> str:
    """The history row's actor as shown: its pipeline stage, `admin` or `system`;
    never an admin's identity (Story 3.4)."""
    if actor.startswith(_ADMIN):
        return "admin"
    stage = actor.removeprefix(_PIPELINE)
    if actor.startswith(_PIPELINE) and stage in _STAGES:
        return stage
    return "system"


def _query(req: func.HttpRequest) -> SearchQuery:
    """The validated query; the messages never echo the value sent."""
    params = req.params
    page = 1
    page_text = params.get("page")
    if page_text is not None:
        if _PAGE.fullmatch(page_text) is None:
            raise ValidationFailedError("page must be a whole number from 1.")
        page = int(page_text)
    supplier_id: UUID | None = None
    supplier_text = params.get("supplier_id")
    if supplier_text is not None:
        supplier_id = parse_uuid(supplier_text)
        if supplier_id is None:
            raise ValidationFailedError("supplier_id must be a UUID.")
    statuses: set[InvoiceStatus] = set()
    status_text = params.get("status")
    if status_text is not None:
        for code in status_text.split(","):
            try:
                statuses.add(InvoiceStatus(code.strip()))
            except ValueError:
                raise ValidationFailedError("status is not a known status.") from None
    number: str | None = None
    number_text = params.get("invoice_number")
    if number_text is not None:
        if len(number_text) <= MAX_INVOICE_NUMBER:
            number = normalise_invoice_number(number_text)
        if not number:
            raise ValidationFailedError(
                "invoice_number must have letters or digits, 64 characters at most."
            )
    reference: bytes | None = None
    reference_text = params.get("reference")
    if reference_text is not None:
        reference = parse_reference(reference_text)
        if reference is None:
            raise ValidationFailedError("reference must be R- and 8 letters or digits.")
    text: str | None = None
    q_text = params.get("q")
    if q_text is not None:
        text = q_text.strip()
        if not text or len(text) > MAX_SEARCH_TEXT:
            raise ValidationFailedError(f"q must be 1 to {MAX_SEARCH_TEXT} characters.")
    return SearchQuery(
        page=page,
        supplier_id=supplier_id,
        statuses=frozenset(statuses),
        invoice_number=number,
        reference=reference,
        text=text,
    )


def _reference(invoice_id: UUID) -> str | None:
    # Every invoice id is a UUIDv7 (spine: Ids); anything else has no reference.
    return supplier_reference(invoice_id) if invoice_id.version == 7 else None


def _money(value: Decimal | None) -> str | None:
    # coding-style.md rule 4: an amount on the wire is a 2-decimal string.
    if value is None:
        return None
    try:
        return str(value.quantize(_CENT, rounding=ROUND_HALF_UP))
    except InvalidOperation:
        # A misread amount too big to quantize still shows, as it was read.
        return str(value)


def _number(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _at(value: datetime | None) -> str | None:
    return None if value is None else value.astimezone(UTC).isoformat()


def _row(row: SearchRow, currency: str) -> dict[str, object]:
    amount = _money(row.invoice_total)
    return {
        "invoice_id": str(row.invoice_id),
        "reference": _reference(row.invoice_id),
        "received_at": _at(row.received_at),
        "supplier_id": str(row.supplier_id),
        "supplier_name": row.supplier_name,
        "invoice_number": row.invoice_number,
        "amount": amount,
        "currency": None if amount is None else row.currency or currency,
        "status": row.status,
        "after_correction": row.after_correction,
    }


def _listing(
    listing: SearchListing, query: SearchQuery, currency: str
) -> dict[str, object]:
    return {
        "items": [_row(row, currency) for row in listing.rows],
        "page": query.page,
        "page_size": PAGE_SIZE,
        "total": listing.total,
        "suppliers": [
            {"supplier_id": str(s.supplier_id), "supplier_name": s.name}
            for s in listing.suppliers
        ],
    }


def _detail(detail: InvoiceDetail) -> dict[str, object]:
    return {
        "invoice_id": str(detail.invoice_id),
        "reference": _reference(detail.invoice_id),
        "received_at": _at(detail.received_at),
        "supplier_id": str(detail.supplier_id),
        "supplier_name": detail.supplier_name,
        "status": detail.status,
        "after_correction": detail.after_correction,
        "accounts_ref": detail.accounts_ref,
        "posted_at": _at(detail.posted_at),
        "fields": [
            {
                "field_id": f.field_id,
                "value": f.value if f.amount is None else _money(f.amount),
                "currency": f.currency,
            }
            for f in detail.fields
        ],
        # AD-11: on file or not, nothing more, for every role on this surface.
        "bank_on_file": detail.bank_on_file,
        "lines": [
            {
                "line_no": line.line_no,
                "product_code": line.product_code,
                "description": line.description,
                "quantity": _number(line.quantity),
                "unit_price": _money(line.unit_price),
                "amount": _money(line.amount),
            }
            for line in detail.lines
        ],
        "history": [
            {
                "from_status": entry.from_status,
                "to_status": entry.to_status,
                "at": _at(entry.at),
                "actor": actor_category(entry.actor),
            }
            for entry in detail.history
        ],
    }


def invoices_endpoints(
    reader: InvoiceSearchReader,
    *,
    currency: str,
    platform_auth_trusted: bool,
) -> tuple[Endpoint, Endpoint]:
    """(search, detail). `platform_auth_trusted` has no default: the wiring must
    always pass the setting (AD-14: fail closed)."""

    async def invoice_search(
        req: func.HttpRequest, correlation_id: UUID, principal: StaffPrincipal
    ) -> func.HttpResponse:
        query = _query(req)
        listing = await reader.search(query)
        return json_response(
            _listing(listing, query, currency),
            status=200,
            correlation_id=correlation_id,
        )

    async def invoice_detail(
        req: func.HttpRequest, correlation_id: UUID, principal: StaffPrincipal
    ) -> func.HttpResponse:
        detail = await reader.detail(invoice_id_of(req))
        if detail is None:
            raise NotFoundError(NOT_FOUND_MESSAGE)
        return json_response(_detail(detail), status=200, correlation_id=correlation_id)

    return (
        staff_endpoint(
            invoice_search,
            surface=Surface.INVOICES,
            platform_auth_trusted=platform_auth_trusted,
        ),
        staff_endpoint(
            invoice_detail,
            surface=Surface.INVOICES,
            platform_auth_trusted=platform_auth_trusted,
            hide_from_others=True,
        ),
    )
