"""The `images` container (AD-6, AD-15): each upload's original bytes, never
re-encoded, at `images/<invoice_id>` with its `IntakeBlobMetadata`."""

from typing import Protocol
from uuid import UUID

from invoicing.ports.intake import IntakeBlobMetadata

IMAGES_CONTAINER = "images"


def image_blob_name(invoice_id: UUID) -> str:
    """The blob name of an invoice's original upload inside `images`."""
    return str(invoice_id)


class ImageStore(Protocol):
    """Writes upload originals. Reading them arrives with the quality stage (2.1)."""

    async def put_if_absent(self, data: bytes, metadata: IntakeBlobMetadata) -> bool:
        """Store `data` at `images/<metadata.invoice_id>` unless a blob is already
        there. True when written now, False when it already existed (a replayed
        upload, AD-6). Raises `ServiceUnavailableError` when storage can't answer."""
        ...
