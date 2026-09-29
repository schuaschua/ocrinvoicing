"""The admin item (Story 2.9, AD-4, AD-11, AD-18, UX-DR10 to UX-DR14):

- `GET api/admin/items/{invoice_id}`: the item's reasons, current fields (with their
  page and polygon), lines, page sizes, content type, and, when `BANK_CHANGED` is
  open, the supplier's phone on file and each changed bank field's masks.
- `GET api/admin/items/{invoice_id}/image`: the upload original, same-origin, with
  `Cache-Control: no-store`; 404 `IMAGE_DELETED` once the 30-day rule deleted it.
- `POST api/admin/items/{invoice_id}/bank/reveal` `{field_id, which}`: one full bank
  value, after its audit entry is written (UX-DR14).

Admins only. Anyone else, an unknown invoice or one not in `in_admin_queue` gets 404
(never 403, so its existence isn't revealed, security.md rule 5), before anything is
read or decrypted; 401 when signed out."""

import json
from datetime import UTC
from typing import Any
from uuid import UUID

import azure.functions as func

from invoicing.adapters.http import Endpoint, json_response
from invoicing.adapters.principal import (
    NOT_FOUND_MESSAGE,
    StaffHandler,
    staff_endpoint,
)
from invoicing.domain.errors import (
    ImageDeletedError,
    NotFoundError,
    ValidationFailedError,
)
from invoicing.domain.extraction import is_bank_field_id
from invoicing.domain.ids import parse_uuid
from invoicing.domain.roles import StaffPrincipal, Surface
from invoicing.ports.admin_item import AdminItem, AdminItemReader, RevealWhich
from invoicing.ports.blobs import ImageNotFoundError, ImageReader

# A reveal body is two short strings; anything bigger is refused unread.
MAX_REVEAL_BODY = 1024


def _invoice_id(req: func.HttpRequest) -> UUID:
    invoice_id = parse_uuid(req.route_params.get("invoice_id"))
    if invoice_id is None:
        raise NotFoundError(NOT_FOUND_MESSAGE)
    return invoice_id


def _number(value: Any) -> str | None:
    return None if value is None else str(value)


def _body(item: AdminItem, image_available: bool) -> dict[str, object]:
    return {
        "invoice_id": str(item.invoice_id),
        "received_at": item.received_at.astimezone(UTC).isoformat(),
        "content_type": item.content_type,
        "image_available": image_available,
        "supplier_id": str(item.supplier_id),
        "supplier_name": item.supplier_name,
        "supplier_phone": item.supplier_phone,
        "reasons": [
            {"code": r.code, "field_ids": list(r.field_ids), "detail": dict(r.detail)}
            for r in item.reasons
        ],
        "fields": [
            {
                "field_id": f.field_id,
                "value": f.value,
                "currency": f.currency,
                "confidence": f.confidence,
                "page": f.page,
                "polygon": None if f.polygon is None else list(f.polygon),
                "flagged": f.flagged,
                "bank": f.bank,
            }
            for f in item.fields
        ],
        "lines": [
            {
                "line_no": line.line_no,
                "product_code": line.product_code,
                "description": line.description,
                # coding-style.md rule 4: exact amounts as strings.
                "quantity": _number(line.quantity),
                "unit_price": _number(line.unit_price),
                "amount": _number(line.amount),
                "confidence": line.confidence,
            }
            for line in item.lines
        ],
        "pages": [
            {"page": p.page, "width": p.width, "height": p.height, "unit": p.unit}
            for p in item.pages
        ],
        "bank_changes": [
            {"field_id": c.field_id, "on_file": c.on_file, "new": c.new}
            for c in item.bank_changes
        ],
    }


def _reveal_request(req: func.HttpRequest) -> tuple[str, RevealWhich]:
    """The validated `{field_id, which}`; messages never echo what was sent."""
    raw = req.get_body() or b""
    if len(raw) > MAX_REVEAL_BODY:
        raise ValidationFailedError("The request is too big.")
    try:
        body = json.loads(raw)
    except ValueError:
        raise ValidationFailedError("The request must be JSON.") from None
    if not isinstance(body, dict):
        raise ValidationFailedError("The request must be a JSON object.")
    field_id = body.get("field_id")
    if not isinstance(field_id, str) or not is_bank_field_id(field_id):
        raise ValidationFailedError("field_id must be a bank field.")
    which_text = body.get("which")
    try:
        which = RevealWhich(which_text if isinstance(which_text, str) else "")
    except ValueError:
        raise ValidationFailedError('which must be "new" or "on_file".') from None
    return field_id, which


def item_endpoints(
    reader: AdminItemReader,
    images: ImageReader,
    *,
    platform_auth_trusted: bool,
) -> tuple[Endpoint, Endpoint, Endpoint]:
    """(item, image, reveal). `platform_auth_trusted` has no default: the wiring must
    always pass the setting (AD-14: fail closed)."""

    async def admin_item(
        req: func.HttpRequest, correlation_id: UUID, principal: StaffPrincipal
    ) -> func.HttpResponse:
        invoice_id = _invoice_id(req)
        item = await reader.read(invoice_id)
        if item is None:
            raise NotFoundError(NOT_FOUND_MESSAGE)
        available = await images.exists(invoice_id)
        return json_response(
            _body(item, available), status=200, correlation_id=correlation_id
        )

    async def admin_item_image(
        req: func.HttpRequest, correlation_id: UUID, principal: StaffPrincipal
    ) -> func.HttpResponse:
        invoice_id = _invoice_id(req)
        content_type = await reader.content_type(invoice_id)
        if content_type is None:
            raise NotFoundError(NOT_FOUND_MESSAGE)
        try:
            stored = await images.get(invoice_id)
        except ImageNotFoundError:
            raise ImageDeletedError() from None
        # The type saved at intake (AD-6 checked the bytes), never the blob's own; the
        # security headers, no-store included, are added by the wrapper.
        return func.HttpResponse(
            stored.data,
            status_code=200,
            headers={"Content-Type": content_type, "Content-Disposition": "inline"},
        )

    async def admin_bank_reveal(
        req: func.HttpRequest, correlation_id: UUID, principal: StaffPrincipal
    ) -> func.HttpResponse:
        invoice_id = _invoice_id(req)
        field_id, which = _reveal_request(req)
        if not principal.oid:
            # UX-DR14: every reveal's audit entry names the admin; without an object
            # id there is nobody to name, so nothing is decrypted.
            raise NotFoundError(NOT_FOUND_MESSAGE)
        value = await reader.reveal(invoice_id, field_id, which, principal.oid)
        if value is None:
            raise NotFoundError(NOT_FOUND_MESSAGE)
        return json_response(
            {"field_id": field_id, "which": which.value, "value": value},
            status=200,
            correlation_id=correlation_id,
        )

    def guarded(handler: StaffHandler) -> Endpoint:
        return staff_endpoint(
            handler,
            surface=Surface.ADMIN_ITEM,
            platform_auth_trusted=platform_auth_trusted,
            hide_from_others=True,
        )

    return guarded(admin_item), guarded(admin_item_image), guarded(admin_bank_reveal)
