"""Story 1.8: the `images` blob adapter (AD-6). A fake client for the mapping, and the
real SDK pipeline over a fake transport for what goes on the wire and into logs."""

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from azure.core.exceptions import (
    ResourceExistsError,
)

from invoicing.adapters.blob_images import BlobImageStore
from invoicing.domain.upload import UploadContentType
from invoicing.ports.blobs import (
    ImageStore,
)
from invoicing.ports.intake import DeviceCheck, IntakeBlobMetadata, IntakeSource

INVOICE_ID = UUID("0192f0c1-7a2b-7c3d-8e4f-0123456789ab")
METADATA = IntakeBlobMetadata(
    invoice_id=INVOICE_ID,
    source=IntakeSource.LINK,
    supplier_id=UUID("0192f0c1-0000-7000-8000-000000000001"),
    content_type=UploadContentType.JPEG,
    uploaded_at=datetime(2026, 9, 29, 1, 30, tzinfo=UTC),
    device_check=DeviceCheck.PASSED,
)
# Bytes a re-encoder would change: an EXIF-bearing JPEG header and trailing padding.
DATA = b"\xff\xd8\xff\xe1\x00\x18Exif\x00\x00MM\x00*" + bytes(range(256)) * 4


class FakeContainer:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.uploads: list[tuple[str, bytes, dict[str, Any]]] = []
        self.closed = False

    async def upload_blob(self, name: str, data: bytes, **kwargs: Any) -> Any:
        self.uploads.append((name, data, kwargs))
        if self.error is not None:
            raise self.error
        return None

    async def close(self) -> None:
        self.closed = True


def _put(container: FakeContainer) -> bool:
    store: ImageStore = BlobImageStore(container)
    return asyncio.run(store.put_if_absent(DATA, METADATA))


def test_story_1_8_a_new_blob_is_written_once_with_its_metadata() -> None:
    container = FakeContainer()
    assert _put(container) is True
    ((name, data, kwargs),) = container.uploads
    assert name == str(INVOICE_ID)
    assert data is DATA
    assert kwargs["overwrite"] is False
    assert kwargs["metadata"] == METADATA.to_blob_metadata()
    assert kwargs["content_settings"].content_type == "image/jpeg"


def _exists(error_code: str) -> ResourceExistsError:
    # As the storage SDK raises it: status 409 and the service's error code.
    error = ResourceExistsError(error_code)
    error.status_code = 409
    error.error_code = error_code  # type: ignore[attr-defined]  # set by the SDK
    return error


def test_story_1_8_an_existing_blob_is_left_alone() -> None:
    assert _put(FakeContainer(_exists("BlobAlreadyExists"))) is False
