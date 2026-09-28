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
from invoicing.ports.blobs import (
    ImageNotFoundError,
    ImageReader,
    ImageStore,
    StoredImage,
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


# --- Story 2.1: reading an original back for the quality stage -------------------------


class FakeDownloader:
    def __init__(self, data: bytes, metadata: dict[str, str]) -> None:
        self._data = data
        self.properties = type("Properties", (), {"metadata": metadata})()

    async def readall(self) -> bytes:
        return self._data


class ReadingContainer(FakeContainer):
    def __init__(
        self,
        downloader: FakeDownloader | None = None,
        error: Exception | None = None,
    ) -> None:
        super().__init__()
        self.downloader = downloader
        self.read_error = error
        self.downloads: list[str] = []

    async def download_blob(self, blob: str, **kwargs: Any) -> Any:
        self.downloads.append(blob)
        if self.read_error is not None:
            raise self.read_error
        return self.downloader


def _get(container: ReadingContainer) -> StoredImage:
    reader: ImageReader = BlobImageStore(container)
    return asyncio.run(reader.get(INVOICE_ID))


def _not_found(error_code: str) -> ResourceNotFoundError:
    error = ResourceNotFoundError(error_code)
    error.status_code = 404
    error.error_code = error_code  # type: ignore[attr-defined]  # set by the SDK
    return error


def test_story_2_1_get_returns_the_original_bytes_and_their_metadata() -> None:
    # Blob storage may return metadata keys in another case.
    stored = {k.upper(): v for k, v in METADATA.to_blob_metadata().items()}
    container = ReadingContainer(FakeDownloader(DATA, stored))
    image = _get(container)
    assert container.downloads == [str(INVOICE_ID)]
    assert image == StoredImage(data=DATA, metadata=METADATA)


def test_story_2_1_a_missing_blob_raises_not_found_logged_by_code(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with (
        caplog.at_level(logging.DEBUG, logger="invoicing"),
        pytest.raises(ImageNotFoundError) as raised,
    ):
        _get(ReadingContainer(error=_not_found("BlobNotFound")))
    assert raised.value.__cause__ is None and raised.value.__suppress_context__
    (record,) = [r for r in caplog.records if r.name.startswith("invoicing")]
    assert record.getMessage().startswith("images.not_found ")
    assert event_fields(record) == {
        "invoice_id": str(INVOICE_ID),
        "code": "IMAGE_NOT_FOUND",
    }


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (_not_found("ContainerNotFound"), "RESOURCE_NOT_FOUND"),
        (ServiceRequestError("connection reset"), "TRANSIENT"),
        (ClientAuthenticationError("no role"), "AUTH_FAILED"),
    ],
)
def test_story_2_1_a_read_failure_is_service_unavailable(
    error: Exception, code: str, caplog: pytest.LogCaptureFixture
) -> None:
    with (
        caplog.at_level(logging.DEBUG, logger="invoicing"),
        pytest.raises(ServiceUnavailableError),
    ):
        _get(ReadingContainer(error=error))
    assert [
        event_fields(r).get("code")
        for r in caplog.records
        if r.getMessage().startswith("images.unavailable ")
    ] == [code]


def test_story_2_1_metadata_that_is_not_intake_metadata_is_refused() -> None:
    with pytest.raises(ValueError, match="not IntakeBlobMetadata"):
        _get(ReadingContainer(FakeDownloader(DATA, {"invoice_id": str(INVOICE_ID)})))


def test_story_2_1_the_wire_404_blob_not_found_is_not_found() -> None:
    transport = FakeTransport(
        [
            (
                404,
                b"",
                {"x-ms-error-code": "BlobNotFound", "Content-Type": "application/xml"},
            )
        ]
    )
    container = ContainerClient(
        account_url="https://babaloosealngst01.blob.core.windows.net",
        container_name="images",
        credential=AzureNamedKeyCredential("babaloosealngst01", "a2V5"),
        transport=transport,
        retry_total=0,
    )

    async def get() -> StoredImage:
        async with container:
            return await BlobImageStore(container).get(INVOICE_ID)

    with pytest.raises(ImageNotFoundError):
        asyncio.run(get())
    (request,) = transport.requests
    assert request.method == "GET"
    assert request.url.startswith(
        f"https://babaloosealngst01.blob.core.windows.net/images/{INVOICE_ID}"
    )


# --- Story 2.2: the sweeper's existence check --------------------------------------------


class _Properties:
    def __init__(self, metadata: dict[str, str]) -> None:
        self.metadata = metadata


class _BlobClient:
    def __init__(self, error: Exception | None, metadata: dict[str, str]) -> None:
        self.error = error
        self.metadata = metadata
        self.calls = 0

    async def get_blob_properties(self) -> Any:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return _Properties(self.metadata)


class CheckingContainer:
    """Properties only: it has no `download_blob`, so a body download would fail."""

    def __init__(
        self, error: Exception | None = None, metadata: dict[str, str] | None = None
    ) -> None:
        self.blob = _BlobClient(error, metadata or {})
        self.names: list[str] = []

    def get_blob_client(self, blob: str) -> _BlobClient:
        self.names.append(blob)
        return self.blob

    async def close(self) -> None:
        return None


def _exists_in(container: CheckingContainer) -> bool:
    reader: ImageReader = BlobImageStore(container)  # type: ignore[arg-type]  # a structural fake
    return asyncio.run(reader.exists(INVOICE_ID))


def test_story_2_2_exists_reads_properties_only() -> None:
    container = CheckingContainer()
    assert _exists_in(container) is True
    assert container.names == [str(INVOICE_ID)] and container.blob.calls == 1


def test_story_2_2_a_missing_blob_does_not_exist() -> None:
    assert _exists_in(CheckingContainer(_not_found("BlobNotFound"))) is False


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (_not_found("ContainerNotFound"), "RESOURCE_NOT_FOUND"),
        (ServiceRequestError("connection reset"), "TRANSIENT"),
    ],
)
def test_story_2_2_an_existence_check_that_fails_is_service_unavailable(
    error: Exception, code: str, caplog: pytest.LogCaptureFixture
) -> None:
    with (
        caplog.at_level(logging.DEBUG, logger="invoicing"),
        pytest.raises(ServiceUnavailableError),
    ):
        _exists_in(CheckingContainer(error))
    assert [
        event_fields(r).get("code")
        for r in caplog.records
        if r.getMessage().startswith("images.unavailable ")
    ] == [code]


def test_story_2_2_the_wire_existence_check_is_a_head_request() -> None:
    transport = FakeTransport(
        [(404, b"", {"x-ms-error-code": "BlobNotFound"}), (200, b"", {})]
    )
    container = ContainerClient(
        account_url="https://babaloosealngst01.blob.core.windows.net",
        container_name="images",
        credential=AzureNamedKeyCredential("babaloosealngst01", "a2V5"),
        transport=transport,
        retry_total=0,
    )

    async def check() -> tuple[bool, bool]:
        async with container:
            store = BlobImageStore(container)
            return await store.exists(INVOICE_ID), await store.exists(INVOICE_ID)

    assert asyncio.run(check()) == (False, True)
    assert [r.method for r in transport.requests] == ["HEAD", "HEAD"]


def _metadata_of(container: CheckingContainer) -> IntakeBlobMetadata:
    reader: ImageReader = BlobImageStore(container)  # type: ignore[arg-type]  # a structural fake
    return asyncio.run(reader.metadata(INVOICE_ID))


def test_story_2_2_metadata_is_read_from_the_properties_never_the_bytes() -> None:
    stored = {k.upper(): v for k, v in METADATA.to_blob_metadata().items()}
    container = CheckingContainer(metadata=stored)
    assert _metadata_of(container) == METADATA
    assert container.names == [str(INVOICE_ID)] and container.blob.calls == 1


def test_story_2_2_metadata_of_a_missing_blob_is_not_found_logged_by_code(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with (
        caplog.at_level(logging.DEBUG, logger="invoicing"),
        pytest.raises(ImageNotFoundError),
    ):
        _metadata_of(CheckingContainer(_not_found("BlobNotFound")))
    (record,) = [r for r in caplog.records if r.name.startswith("invoicing")]
    assert event_fields(record) == {
        "invoice_id": str(INVOICE_ID),
        "code": "IMAGE_NOT_FOUND",
    }


def test_story_2_2_metadata_that_is_not_intake_metadata_is_refused() -> None:
    with pytest.raises(ValueError, match="not IntakeBlobMetadata"):
        _metadata_of(CheckingContainer(metadata={"invoice_id": str(INVOICE_ID)}))


def test_story_2_2_the_wire_metadata_read_is_one_head_request() -> None:
    headers = {f"x-ms-meta-{k}": v for k, v in METADATA.to_blob_metadata().items()}
    transport = FakeTransport([(200, b"", headers)])
    container = ContainerClient(
        account_url="https://babaloosealngst01.blob.core.windows.net",
        container_name="images",
        credential=AzureNamedKeyCredential("babaloosealngst01", "a2V5"),
        transport=transport,
        retry_total=0,
    )

    async def read() -> IntakeBlobMetadata:
        async with container:
            return await BlobImageStore(container).metadata(INVOICE_ID)

    assert asyncio.run(read()) == METADATA
    assert [r.method for r in transport.requests] == ["HEAD"]
