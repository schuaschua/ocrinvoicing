"""The `images` container (AD-6, AD-15): each upload's original bytes, never
re-encoded, at `images/<invoice_id>` with its `IntakeBlobMetadata`."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from invoicing.ports.intake import IntakeBlobMetadata

IMAGES_CONTAINER = "images"


def image_blob_name(invoice_id: UUID) -> str:
    """The blob name of an invoice's original upload inside `images`."""
    return str(invoice_id)


class ImageNotFoundError(LookupError):
    """`images/<invoice_id>` does not exist. The message names no value."""


@dataclass(frozen=True)
class StoredImage:
    """An upload original and the metadata its intake writer stored with it (AD-5)."""

    data: bytes
    metadata: IntakeBlobMetadata


class ImageReader(Protocol):
    """Reads upload originals (the quality stage, Story 2.1)."""

    async def get(self, invoice_id: UUID) -> StoredImage:
        """The bytes and metadata of `images/<invoice_id>`. Raises
        `ImageNotFoundError` when there is no such blob, ValueError when its metadata
        is not `IntakeBlobMetadata`, and `ServiceUnavailableError` when storage can't
        answer."""
        ...

    async def metadata(self, invoice_id: UUID) -> IntakeBlobMetadata:
        """The metadata of `images/<invoice_id>`, from its properties only: the bytes
        are never downloaded (the poison trigger, Story 2.2). Raises like `get`."""
        ...

    async def exists(self, invoice_id: UUID) -> bool:
        """Whether `images/<invoice_id>` exists, without reading it (the sweeper's
        orphaned-upload check, Story 2.2). Raises `ServiceUnavailableError` when
        storage can't answer."""
        ...


class ImageStore(Protocol):
    """Writes upload originals."""

    async def put_if_absent(self, data: bytes, metadata: IntakeBlobMetadata) -> bool:
        """Store `data` at `images/<metadata.invoice_id>` unless a blob is already
        there. True when written now, False when it already existed (a replayed
        upload, AD-6). Raises `ServiceUnavailableError` when storage can't answer."""
        ...


# --- corrections (Story 2.10, FR10, AD-15) -----------------------------------------

CORRECTIONS_CONTAINER = "corrections"


def correction_blob_name(invoice_id: UUID, correction_id: UUID) -> str:
    """`<invoice_id>/<uuid7>.json` inside `corrections`: one blob per Save and
    re-check, never overwritten."""
    return f"{invoice_id}/{correction_id}.json"


class CorrectionsStore(Protocol):
    """Writes an admin's raw correction for later model training (FR10). The JSON never
    holds a bank value: bank fields can't be corrected (AD-11)."""

    async def put(self, invoice_id: UUID, correction_id: UUID, data: bytes) -> None:
        """Store `data` at `corrections/<invoice_id>/<correction_id>.json`, never
        overwriting a blob. Raises `ServiceUnavailableError` when storage can't
        answer."""
        ...
