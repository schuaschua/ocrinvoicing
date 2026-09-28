"""The supplier's link (AD-6): `GET /api/link`, and the lookup every supplier-api call
makes from the `X-Upload-Token` header. Table Storage only, never PostgreSQL."""

from collections.abc import Callable
from uuid import UUID

import azure.functions as func

from invoicing.adapters.http import Endpoint, http_endpoint, json_response
from invoicing.domain.errors import LinkNotValidError
from invoicing.domain.links import parse_token, token_hash
from invoicing.ports.links import SupplierLink, SupplierLinkRegistry

# Read here and nowhere else; never logged, echoed or put in an error (AD-14).
# A header name, not a credential (S105).
UPLOAD_TOKEN_HEADER = "X-Upload-Token"  # noqa: S105


async def current_link(
    req: func.HttpRequest, registry: SupplierLinkRegistry
) -> SupplierLink:
    """The active link the request's token belongs to. A missing, malformed, unknown or
    revoked token raises the same `LinkNotValidError` (UX-DR7); a malformed one never
    reaches the table."""
    token = parse_token(req.headers.get(UPLOAD_TOKEN_HEADER))
    if token is None:
        raise LinkNotValidError()
    link = await registry.resolve(token_hash(token))
    if link is None or not link.is_active:
        raise LinkNotValidError()
    return link


def link_endpoint(registry: Callable[[], SupplierLinkRegistry]) -> Endpoint:
    """`GET /api/link`: 200 `{"supplier_name"}` for an active link. The supplier id stays
    on the server."""

    async def link(req: func.HttpRequest, correlation_id: UUID) -> func.HttpResponse:
        found = await current_link(req, registry())
        return json_response(
            {"supplier_name": found.supplier_name},
            status=200,
            correlation_id=correlation_id,
        )

    # Anonymous: the caller's X-Correlation-Id is ignored (it would choose the trace id).
    return http_endpoint(link, trust_caller_correlation_id=False)
