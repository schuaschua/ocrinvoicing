"""Story 1.8: the `images` blob adapter (AD-6). A fake client for the mapping, and the
real SDK pipeline over a fake transport for what goes on the wire and into logs."""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from _sdk_transport import FakeTransport
from azure.core.credentials import AzureNamedKeyCredential
from azure.core.exceptions import (
    ClientAuthenticationError,
    HttpResponseError,
    ResourceExistsError,
    ResourceNotFoundError,
    ServiceRequestError,
)
from azure.storage.blob.aio import ContainerClient

from invoicing.adapters import blob_images
from invoicing.adapters.blob_images import BlobImageStore
from invoicing.adapters.logging import event_fields
from invoicing.domain.errors import ServiceUnavailableError
from invoicing.domain.upload import UploadContentType
from invoicing.ports.blobs import ImageStore
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


def test_story_1_8_any_other_conflict_is_a_503_not_already_stored(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with (
        caplog.at_level(logging.DEBUG, logger="invoicing"),
        pytest.raises(ServiceUnavailableError),
    ):
        _put(FakeContainer(_exists("ContainerBeingDeleted")))
    assert [
        (event_fields(r).get("code"), r.levelno)
        for r in caplog.records
        if r.getMessage().startswith("images.unavailable ")
    ] == [("HTTP_409", logging.ERROR)]


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (ServiceRequestError("connection reset"), "TRANSIENT"),
        (HttpResponseError(message=f"500 for images/{INVOICE_ID}"), "TRANSIENT"),
        (ClientAuthenticationError("no role"), "AUTH_FAILED"),
        (ResourceNotFoundError("ContainerNotFound"), "RESOURCE_NOT_FOUND"),
    ],
)
def test_story_1_8_a_storage_failure_is_a_retryable_503_logged_by_code(
    error: Exception, code: str, caplog: pytest.LogCaptureFixture
) -> None:
    with (
        caplog.at_level(logging.DEBUG, logger="invoicing"),
        pytest.raises(ServiceUnavailableError) as raised,
    ):
        _put(FakeContainer(error))
    assert raised.value.__cause__ is None and raised.value.__suppress_context__
    codes = [
        event_fields(r).get("code")
        for r in caplog.records
        if r.getMessage().startswith("images.unavailable ")
    ]
    assert codes == [code]


def test_story_1_8_close_releases_the_client_and_the_credential() -> None:
    class FakeCredential:
        closed = False

        async def close(self) -> None:
            self.closed = True

    container, credential = FakeContainer(), FakeCredential()
    asyncio.run(BlobImageStore(container, credential).close())
    assert container.closed and credential.closed


def test_story_1_8_managed_identity_store_targets_the_images_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_ids: list[str] = []

    class FakeManagedIdentity:
        def __init__(self, *, client_id: str) -> None:
            client_ids.append(client_id)

        async def get_token(self, *scopes: str, **kwargs: Any) -> Any:
            raise AssertionError("no token is requested in this test")

        async def close(self) -> None:
            return None

    monkeypatch.setattr(blob_images, "ManagedIdentityCredential", FakeManagedIdentity)

    async def build() -> None:
        store = BlobImageStore.with_managed_identity(
            "babaloosealngst01", "00000000-0000-0000-0000-00000000c1d0"
        )
        container = store._container
        assert isinstance(container, ContainerClient)
        assert container.container_name == "images"
        assert container.url == "https://babaloosealngst01.blob.core.windows.net/images"
        await store.close()

    asyncio.run(build())
    assert client_ids == ["00000000-0000-0000-0000-00000000c1d0"]


# --- The real SDK pipeline -----------------------------------------------------------


def _sdk_put(status: int) -> tuple[bool | None, FakeTransport]:
    headers = {
        "Content-Type": "application/xml",
        "x-ms-error-code": "BlobAlreadyExists",
    }
    transport = FakeTransport([(status, b"", headers if status == 409 else {})])
    container = ContainerClient(
        account_url="https://babaloosealngst01.blob.core.windows.net",
        container_name="images",
        credential=AzureNamedKeyCredential("babaloosealngst01", "a2V5"),
        transport=transport,
        retry_total=0,
    )

    async def put() -> bool:
        async with container:
            return await BlobImageStore(container).put_if_absent(DATA, METADATA)

    return asyncio.run(put()), transport


def test_story_1_8_the_wire_request_is_a_conditional_put_of_the_exact_bytes() -> None:
    written, transport = _sdk_put(201)
    assert written is True
    ((request,),) = [transport.requests]
    assert request.method == "PUT"
    assert request.url.startswith(
        f"https://babaloosealngst01.blob.core.windows.net/images/{INVOICE_ID}"
    )
    # Create-if-absent is enforced by the service, not by a read first.
    assert request.headers["If-None-Match"] == "*"
    assert request.headers["x-ms-blob-type"] == "BlockBlob"
    assert request.headers["x-ms-blob-content-type"] == "image/jpeg"
    for key, value in METADATA.to_blob_metadata().items():
        assert request.headers[f"x-ms-meta-{key}"] == value
    assert "x-ms-meta-delivery_id" not in request.headers
    # The original bytes, byte for byte.
    assert bytes(request.body) == DATA


def test_story_1_8_the_services_already_exists_answer_means_not_written() -> None:
    written, _ = _sdk_put(409)
    assert written is False
