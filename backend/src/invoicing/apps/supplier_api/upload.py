"""`POST /api/upload` (AD-6): a supplier sends one invoice file and gets its reference.
The link decides the supplier; the key, blob and `q-quality` steps, in that order and
never PostgreSQL, are the shared intake (`apps/intake_upload.py`), so a retry never
creates a second invoice.

`X-Device-Check` (Story 1.9) says how the page's photo check went: `passed` (the
default when absent), `overridden` ("Send it anyway") or `skipped` (the page couldn't
check the file); anything else is a 400. It is
bound to the key with the invoice, so a replay keeps the first attempt's value.

The body is the raw file (not multipart), stored exactly as sent. The file type comes
from its bytes, never from the request's Content-Type. Never log the token, the key,
the file name or its bytes.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

import azure.functions as func

from invoicing.adapters.http import Endpoint, http_endpoint, json_response
from invoicing.apps.intake_upload import UploadOwner, accept_upload, checked_upload
from invoicing.apps.supplier_api.link import current_link
from invoicing.domain.reference import supplier_reference
from invoicing.ports.blobs import ImageStore
from invoicing.ports.intake import IntakeSource
from invoicing.ports.links import SupplierLinkRegistry
from invoicing.ports.queue import QueueSender
from invoicing.ports.upload_keys import UploadKeyStore


def _now() -> datetime:
    return datetime.now(UTC)


def upload_endpoint(
    registry: Callable[[], SupplierLinkRegistry],
    keys: Callable[[], UploadKeyStore],
    images: Callable[[], ImageStore],
    queue: Callable[[], QueueSender],
    clock: Callable[[], datetime] | None = None,
) -> Endpoint:
    """`POST /api/upload`: 200 `{invoice_id, reference}`. 401 for a link that can't be
    used, 400 for a missing or malformed key or an unknown `X-Device-Check`, 413 over 4 MB, 415 for anything but
    JPEG, PNG or PDF, 409 for a key another supplier holds or that was used for other
    bytes, 503 when storage fails. Nothing is written unless every check passed.
    `clock` defaults to the current UTC time."""

    async def upload(req: func.HttpRequest, correlation_id: UUID) -> func.HttpResponse:
        link = await current_link(req, registry())
        stored = await accept_upload(
            checked_upload(req),
            UploadOwner(supplier_id=link.supplier_id, source=IntakeSource.LINK),
            correlation_id=correlation_id,
            now=(clock or _now)(),
            keys=keys(),
            images=images(),
            queue=queue(),
        )
        return json_response(
            {
                "invoice_id": str(stored.invoice_id),
                "reference": supplier_reference(stored.invoice_id),
            },
            status=200,
            correlation_id=correlation_id,
        )

    # Anonymous: the caller's X-Correlation-Id is ignored (it would choose the trace id).
    return http_endpoint(upload, trust_caller_correlation_id=False)
