"""`CorrectionsStore` over the blob container `corrections` (Story 2.10, FR10, AD-15),
signed in with the app's user-assigned managed identity. Blob name: `ports/blobs.py`.
The platform lifecycle rule deletes each blob 30 days after it is written (P-11)."""

import logging
from collections.abc import Awaitable
from typing import Any, Protocol, Self
from uuid import UUID

from azure.core.exceptions import AzureError
from azure.identity.aio import ManagedIdentityCredential
from azure.storage.blob import ContentSettings
from azure.storage.blob.aio import ContainerClient

from invoicing.adapters.storage_errors import raise_unavailable
from invoicing.ports.blobs import CORRECTIONS_CONTAINER, correction_blob_name

_logger = logging.getLogger("invoicing.corrections")

JSON = "application/json"


class _ContainerClient(Protocol):
    # Not `async def`: the SDK's tracing decorator types it as returning an Awaitable.
    def upload_blob(self, name: str, data: bytes, **kwargs: Any) -> Awaitable[Any]: ...

    async def close(self) -> None: ...


class _Closeable(Protocol):
    async def close(self) -> None: ...


class BlobCorrectionsStore:
    """Writes each correction once to `corrections`; a blob is never overwritten."""

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
            container_name=CORRECTIONS_CONTAINER,
            credential=credential,
        )
        return cls(container, credential)

    async def put(self, invoice_id: UUID, correction_id: UUID, data: bytes) -> None:
        try:
            # overwrite=False: a UUIDv7 name is new, and a blob is never replaced.
            await self._container.upload_blob(
                correction_blob_name(invoice_id, correction_id),
                data,
                overwrite=False,
                content_settings=ContentSettings(content_type=JSON),
            )
        except AzureError as error:
            raise_unavailable(_logger, "corrections.unavailable", error)

    async def close(self) -> None:
        """Release the HTTP session and the credential."""
        await self._container.close()
        if self._credential is not None:
            await self._credential.close()
