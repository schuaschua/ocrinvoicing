"""`GET /api/reminders` (Story 4.3, CAP-13, FR13): the overdue POs the weekly job wrote
for the link's supplier, for Upload home's read-only banner.

The supplier comes only from the `X-Upload-Token` link; nothing in the request can name
another. Table Storage only, never PostgreSQL (AD-6), so it answers while the database
is stopped. 200 `{"po_numbers": [...]}`, sorted; 401 `LINK_NOT_VALID` for a link that
can't be used, as `/api/link`; 503 when storage fails.
"""

from collections.abc import Callable
from uuid import UUID

import azure.functions as func

from invoicing.adapters.http import Endpoint, http_endpoint, json_response
from invoicing.apps.supplier_api.link import current_link
from invoicing.ports.links import SupplierLinkRegistry
from invoicing.ports.reminders import ReminderReader


def reminders_endpoint(
    registry: Callable[[], SupplierLinkRegistry],
    reminders: Callable[[], ReminderReader],
) -> Endpoint:
    """`GET /api/reminders` for the link's supplier."""

    async def list_reminders(
        req: func.HttpRequest, correlation_id: UUID
    ) -> func.HttpResponse:
        link = await current_link(req, registry())
        po_numbers = await reminders().list_for(link.supplier_id)
        return json_response(
            {"po_numbers": sorted(po_numbers)},
            status=200,
            correlation_id=correlation_id,
        )

    # Anonymous: the caller's X-Correlation-Id is ignored (it would choose the trace id).
    return http_endpoint(list_reminders, trust_caller_correlation_id=False)
