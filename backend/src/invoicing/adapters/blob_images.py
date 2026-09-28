"""`ImageStore` over the blob container `images` (AD-6, AD-15), signed in with the
app's user-assigned managed identity. Blob name: `ports/blobs.py`."""

import logging
from collections.abc import Awaitable
from typing import Any, Protocol, Self
from uuid import UUID

from azure.core.exceptions import (
    AzureError,
    ResourceExistsError,
    ResourceNotFoundError,
)
from azure.identity.aio import ManagedIdentityCredential
from azure.storage.blob import ContentSettings
from azure.storage.blob.aio import ContainerClient

from invoicing.adapters.logging import log_event
from invoicing.adapters.storage_errors import raise_unavailable
from invoicing.ports.blobs import (
    IMAGES_CONTAINER,
    ImageNotFoundError,
    StoredImage,
    image_blob_name,
)
from invoicing.ports.intake import IntakeBlobMetadata

_logger = logging.getLogger("invoicing.images")


class _ContainerClient(Protocol):
    # Not `async def`: the SDK's tracing decorator types it as returning an Awaitable.
    def upload_blob(self, name: str, data: bytes, **kwargs: Any) -> Awaitable[Any]: ...

    def download_blob(self, blob: str, **kwargs: Any) -> Awaitable[Any]: ...

    async def close(self) -> None: ...


class _Closeable(Protocol):
    async def close(self) -> None: ...


class BlobImageStore:
    """Writes upload originals to `images`, never overwriting one, and reads them
    back (`ImageStore`, `ImageReader`)."""

    def __init__(
        self, container: _ContainerClient, credential: _Closeable | None = None
    ) -> None:
        self._container = container
        self._credential = credential

    @classmethod
    def with_managed_identity(cls, account_name: str, client_id: str) -> Self:
        """A store on `account_name`, authenticated as the user-assigned identity."""
        credential = ManagedIdentityCredential(client_id=client_id)
        container = ContainerClient(
            account_url=f"https://{account_name}.blob.core.windows.net",
            container_name=IMAGES_CONTAINER,
            credential=credential,
        )
        return cls(container, credential)

    async def put_if_absent(self, data: bytes, metadata: IntakeBlobMetadata) -> bool:
        try:
            # overwrite=False sends If-None-Match: *, so the service refuses a second
            # write atomically. The bytes go up exactly as received (AD-6); an upload of
            # 4 MB or less is one Put Blob, so a crash never leaves a partial blob.
            await self._container.upload_blob(
                image_blob_name(metadata.invoice_id),
                data,
                overwrite=False,
                metadata=metadata.to_blob_metadata(),
                content_settings=ContentSettings(content_type=metadata.content_type),
            )
        except ResourceExistsError as error:
            # Only this code (set by the storage SDK) means the blob is there; any
            # other 409, such as a container being deleted, is a fault.
            if getattr(error, "error_code", None) == "BlobAlreadyExists":
                return False
            raise_unavailable(_logger, "images.unavailable", error)
        except AzureError as error:
            raise_unavailable(_logger, "images.unavailable", error)
        return True

    async def get(self, invoice_id: UUID) -> StoredImage:
        try:
            downloader = await self._container.download_blob(
                image_blob_name(invoice_id)
            )
            data = await downloader.readall()
            metadata = dict(downloader.properties.metadata or {})
        except ResourceNotFoundError as error:
            # Only this code means the blob is missing; a missing container is a fault.
            if getattr(error, "error_code", None) == "BlobNotFound":
                log_event(
                    _logger,
                    "images.not_found",
                    level=logging.WARNING,
                    invoice_id=invoice_id,
                    code="IMAGE_NOT_FOUND",
                )
                raise ImageNotFoundError("the upload original does not exist") from None
            raise_unavailable(_logger, "images.unavailable", error)
        except AzureError as error:
            raise_unavailable(_logger, "images.unavailable", error)
        return StoredImage(
            data=bytes(data), metadata=IntakeBlobMetadata.from_blob_metadata(metadata)
        )

    async def close(self) -> None:
        """Release the HTTP session and the credential."""
        await self._container.close()
        if self._credential is not None:
            await self._credential.close()
