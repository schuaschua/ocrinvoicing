"""The upload intake both writers share (AD-5, AD-6): supplier-api's `POST /api/upload`
and staff-api's goods-in scan (Story 4.1). Each writer decides who the upload is for
(the link's supplier, or the delivery's) and hands the checked request to
`accept_upload`, which writes Table Storage, blob storage and `q-quality` only, in this
order:

1. `Idempotency-Key -> invoice_id` into `uploadkeys`, unless the key is stored already;
   then the stored invoice is used.
2. The original bytes to `images/<invoice_id>` with `IntakeBlobMetadata`, unless the
   blob exists.
3. A `QueueMessage` on `q-quality`.

A retry with the same key replays steps 2 and 3, so a failed attempt is completed and
a second invoice is never created; a duplicate message is harmless (AD-2). A key is one
file of one owner (supplier, source and delivery): reused for another owner or other
bytes, it is refused with 409 before anything else is written.

The body is the raw file (not multipart), stored exactly as sent. The file type comes
from its bytes, never from the request's Content-Type. Never log the key, the file name
or its bytes.
"""

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import azure.functions as func

from invoicing.adapters.logging import log_event
from invoicing.domain.errors import IdempotencyKeyConflictError, ValidationFailedError
from invoicing.domain.ids import new_uuid7, parse_uuid
from invoicing.domain.upload import (
    DeviceCheck,
    UploadContentType,
    check_declared_length,
    check_upload,
    parse_device_check,
)
from invoicing.ports.blobs import ImageStore
from invoicing.ports.intake import IntakeBlobMetadata, IntakeSource
from invoicing.ports.messages import QueueMessage
from invoicing.ports.queue import QueueName, QueueSender
from invoicing.ports.upload_keys import UploadKey, UploadKeyStore

IDEMPOTENCY_KEY_HEADER = "Idempotency-Key"
DEVICE_CHECK_HEADER = "X-Device-Check"
KEY_MESSAGE = "This upload has no valid key. Reload the page and send the file again."

_logger = logging.getLogger("invoicing.upload")


def upload_key(req: func.HttpRequest) -> UUID:
    """The request's Idempotency-Key: a UUID the page makes once per chosen file."""
    key = parse_uuid(req.headers.get(IDEMPOTENCY_KEY_HEADER))
    if key is None or key.int == 0:
        raise ValidationFailedError(KEY_MESSAGE)
    return key


@dataclass(frozen=True)
class CheckedUpload:
    """A request that passed every upload rule: its key, file and device check."""

    key: UUID
    body: bytes
    content_type: UploadContentType
    content_sha256: str
    device_check: DeviceCheck


def checked_upload(req: func.HttpRequest) -> CheckedUpload:
    """The upload in `req`, or the rule it breaks: 400 for a missing or malformed key,
    an unknown `X-Device-Check` (absent means `passed`, Story 1.9) or an empty file,
    413 over 4 MB, 415 for anything but JPEG, PNG or PDF. Reads nothing else."""
    key = upload_key(req)
    device_check = parse_device_check(req.headers.get(DEVICE_CHECK_HEADER))
    # An early refusal when the client declared a length over the limit.
    check_declared_length(req.headers.get("Content-Length"))
    body = req.get_body()
    content_type = check_upload(body)
    return CheckedUpload(
        key=key,
        body=body,
        content_type=content_type,
        content_sha256=hashlib.sha256(body).hexdigest(),
        device_check=device_check,
    )


@dataclass(frozen=True)
class UploadOwner:
    """Who an upload is for, as its writer decided it (AD-5): never read from the
    invoice itself."""

    supplier_id: UUID
    source: IntakeSource
    delivery_id: UUID | None = None


async def accept_upload(
    upload: CheckedUpload,
    owner: UploadOwner,
    *,
    correlation_id: UUID,
    now: datetime,
    keys: UploadKeyStore,
    images: ImageStore,
    queue: QueueSender,
) -> UploadKey:
    """Steps 1 to 3 (AD-6); returns what the key holds, the first attempt's invoice.
    Raises `IdempotencyKeyConflictError` (409) for a key another owner or other bytes
    hold, and `ServiceUnavailableError` when storage fails (a retry completes it)."""
    # Step 1: the key decides the invoice.
    stored, inserted = await keys.claim(
        upload.key,
        UploadKey(
            invoice_id=new_uuid7(),
            supplier_id=owner.supplier_id,
            correlation_id=correlation_id,
            created_at=now,
            content_sha256=upload.content_sha256,
            content_type=upload.content_type,
            device_check=upload.device_check,
            source=owner.source,
            delivery_id=owner.delivery_id,
        ),
    )
    # A key is one file of one owner: another owner's key, or the same key with other
    # bytes, would otherwise return that upload and drop this file.
    if (stored.supplier_id, stored.source, stored.delivery_id) != (
        owner.supplier_id,
        owner.source,
        owner.delivery_id,
    ) or (stored.content_sha256, stored.content_type) != (
        upload.content_sha256,
        upload.content_type,
    ):
        log_event(_logger, "upload.key_conflict", code="IDEMPOTENCY_KEY_CONFLICT")
        raise IdempotencyKeyConflictError()
    # A retry that reports another device check keeps the stored one; say so.
    if stored.device_check != upload.device_check:
        log_event(
            _logger,
            "upload.device_check_mismatch",
            invoice_id=stored.invoice_id,
            code="DEVICE_CHECK_MISMATCH",
            device_check=stored.device_check,
        )

    # Step 2: the original bytes, once.
    written = await images.put_if_absent(
        upload.body,
        IntakeBlobMetadata(
            invoice_id=stored.invoice_id,
            source=owner.source,
            supplier_id=owner.supplier_id,
            delivery_id=owner.delivery_id,
            content_type=upload.content_type,
            uploaded_at=stored.created_at,
            # The first attempt's value: a replay never changes it.
            device_check=stored.device_check,
        ),
    )

    # Step 3: the quality stage's message, in the first attempt's trace and with its
    # time, so a replay's message matches the first one.
    await queue.send(
        QueueName.QUALITY,
        QueueMessage.first(stored.invoice_id, stored.correlation_id, stored.created_at),
    )
    # A goods-in scan's delivery; a supplier upload has none (not logged as None).
    delivery: dict[str, object] = (
        {} if owner.delivery_id is None else {"delivery_id": owner.delivery_id}
    )
    log_event(
        _logger,
        "upload.accepted",
        level=logging.INFO,
        invoice_id=stored.invoice_id,
        source=owner.source,
        # "existing": a retry, or the loser of a race on the same key.
        status="new" if inserted else "existing",
        blob_written=written,
        content_type=upload.content_type,
        device_check=stored.device_check,
        size_bytes=len(upload.body),
        **delivery,
    )
    return stored
