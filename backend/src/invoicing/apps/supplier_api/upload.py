"""`POST /api/upload` (AD-6): a supplier sends one invoice file and gets its reference.
Table Storage, blob storage and `q-quality` only, never PostgreSQL, in this order:

1. `Idempotency-Key -> invoice_id` into `uploadkeys`, unless the key is stored already;
   then the stored invoice is used.
2. The original bytes to `images/<invoice_id>` with `IntakeBlobMetadata`, unless the
   blob exists.
3. A `QueueMessage` on `q-quality`, then `{invoice_id, reference}`.

A retry with the same key replays steps 2 and 3, so a failed attempt is completed and
a second invoice is never created; a duplicate message is harmless (AD-2).

The body is the raw file (not multipart), stored exactly as sent. The file type comes
from its bytes, never from the request's Content-Type. Never log the token, the key,
the file name or its bytes.
"""

import hashlib
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

import azure.functions as func

from invoicing.adapters.http import Endpoint, http_endpoint, json_response
from invoicing.adapters.logging import log_event
from invoicing.apps.supplier_api.link import current_link
from invoicing.domain.errors import (
    IdempotencyKeyConflictError,
    ValidationFailedError,
)
from invoicing.domain.ids import new_uuid7, parse_uuid
from invoicing.domain.reference import supplier_reference
from invoicing.domain.upload import check_declared_length, check_upload
from invoicing.ports.blobs import ImageStore
from invoicing.ports.intake import DeviceCheck, IntakeBlobMetadata, IntakeSource
from invoicing.ports.links import SupplierLinkRegistry
from invoicing.ports.messages import QueueMessage
from invoicing.ports.queue import QueueName, QueueSender
from invoicing.ports.upload_keys import UploadKey, UploadKeyStore

IDEMPOTENCY_KEY_HEADER = "Idempotency-Key"
KEY_MESSAGE = "This upload has no valid key. Reload the page and send the file again."

_logger = logging.getLogger("invoicing.upload")


def _now() -> datetime:
    return datetime.now(UTC)


def upload_key(req: func.HttpRequest) -> UUID:
    """The request's Idempotency-Key: a UUID the page makes once per chosen file."""
    key = parse_uuid(req.headers.get(IDEMPOTENCY_KEY_HEADER))
    if key is None or key.int == 0:
        raise ValidationFailedError(KEY_MESSAGE)
    return key


def upload_endpoint(
    registry: Callable[[], SupplierLinkRegistry],
    keys: Callable[[], UploadKeyStore],
    images: Callable[[], ImageStore],
    queue: Callable[[], QueueSender],
    clock: Callable[[], datetime] | None = None,
) -> Endpoint:
    """`POST /api/upload`: 200 `{invoice_id, reference}`. 401 for a link that can't be
    used, 400 for a missing or malformed key, 413 over 4 MB, 415 for anything but
    JPEG, PNG or PDF, 409 for a key another supplier holds or that was used for other
    bytes, 503 when storage fails. Nothing is written unless every check passed.
    `clock` defaults to the current UTC time."""

    async def upload(req: func.HttpRequest, correlation_id: UUID) -> func.HttpResponse:
        link = await current_link(req, registry())
        key = upload_key(req)
        # An early refusal when the client declared a length over the limit.
        check_declared_length(req.headers.get("Content-Length"))
        body = req.get_body()
        content_type = check_upload(body)
        content_sha256 = hashlib.sha256(body).hexdigest()
        now = (clock or _now)()

        # Step 1: the key decides the invoice.
        stored, inserted = await keys().claim(
            key,
            UploadKey(
                invoice_id=new_uuid7(),
                supplier_id=link.supplier_id,
                correlation_id=correlation_id,
                created_at=now,
                content_sha256=content_sha256,
                content_type=content_type,
            ),
        )
        # A key is one file of one supplier: another supplier's key, or the same key
        # with other bytes, would otherwise return that upload and drop this file.
        if stored.supplier_id != link.supplier_id or (
            stored.content_sha256,
            stored.content_type,
        ) != (content_sha256, content_type):
            log_event(_logger, "upload.key_conflict", code="IDEMPOTENCY_KEY_CONFLICT")
            raise IdempotencyKeyConflictError()

        # Step 2: the original bytes, once.
        written = await images().put_if_absent(
            body,
            IntakeBlobMetadata(
                invoice_id=stored.invoice_id,
                source=IntakeSource.LINK,
                supplier_id=link.supplier_id,
                content_type=content_type,
                uploaded_at=stored.created_at,
                # Story 1.9 adds the device check and "Send it anyway".
                device_check=DeviceCheck.PASSED,
            ),
        )

        # Step 3: the quality stage's message, in the first attempt's trace and with
        # its time, so a replay's message matches the first one.
        await queue().send(
            QueueName.QUALITY,
            QueueMessage.first(
                stored.invoice_id, stored.correlation_id, stored.created_at
            ),
        )
        log_event(
            _logger,
            "upload.accepted",
            invoice_id=stored.invoice_id,
            # "existing": a retry, or the loser of a race on the same key.
            status="new" if inserted else "existing",
            blob_written=written,
            content_type=content_type,
            size_bytes=len(body),
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
