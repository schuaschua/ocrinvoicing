"""Fakes for the pipeline tests: blob storage, queues, metrics, the `uploadkeys` table
(Story 2.2) and the `supplierreminders` table (Story 2.6). Nothing reaches Azure (coding-style.md rule 23)."""

import socket
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Engine

from invoicing.adapters.postgres.engine import postgres_engine
from invoicing.domain.errors import ServiceUnavailableError
from invoicing.domain.upload import UploadContentType
from invoicing.ports.blobs import ImageNotFoundError, StoredImage
from invoicing.ports.intake import DeviceCheck, IntakeBlobMetadata, IntakeSource
from invoicing.ports.messages import QueueMessage
from invoicing.ports.queue import QueueName
from invoicing.ports.upload_keys import AgedUploadKey, UploadKey

SUPPLIER_ID = UUID("0192f0c1-0000-7000-8000-000000000001")
CORRELATION_ID = UUID("0192f0c1-7a2b-7c3d-8e4f-0000000000c0")
UPLOADED_AT = datetime(2026, 9, 29, 1, 30, tzinfo=UTC)


def invoice_id(n: int) -> UUID:
    """A UUIDv7 invoice id, distinct per `n`."""
    return UUID(f"0192f0c1-7a2b-7c3d-8e4f-{n:012x}")


def metadata(
    for_invoice: UUID,
    *,
    source: IntakeSource = IntakeSource.LINK,
    delivery_id: UUID | None = None,
) -> IntakeBlobMetadata:
    return IntakeBlobMetadata(
        invoice_id=for_invoice,
        source=source,
        supplier_id=SUPPLIER_ID,
        delivery_id=delivery_id,
        content_type=UploadContentType.JPEG,
        uploaded_at=UPLOADED_AT,
        device_check=DeviceCheck.PASSED,
    )


class FakeImages:
    """`ImageReader` over a dict of blobs."""

    def __init__(self) -> None:
        self.blobs: dict[UUID, StoredImage] = {}
        self.reads: list[UUID] = []

    def put(self, stored: IntakeBlobMetadata, data: bytes = b"jpeg") -> None:
        self.blobs[stored.invoice_id] = StoredImage(data, stored)

    async def get(self, invoice_id: UUID) -> StoredImage:
        self.reads.append(invoice_id)
        if invoice_id not in self.blobs:
            raise ImageNotFoundError("the upload original does not exist")
        return self.blobs[invoice_id]

    async def metadata(self, invoice_id: UUID) -> IntakeBlobMetadata:
        # Properties only: no body read is recorded.
        if invoice_id not in self.blobs:
            raise ImageNotFoundError("the upload original does not exist")
        return self.blobs[invoice_id].metadata

    async def exists(self, invoice_id: UUID) -> bool:
        return invoice_id in self.blobs


class FakeQueue:
    """`QueueSender` that records what it sends."""

    def __init__(self) -> None:
        self.sent: list[tuple[QueueName, QueueMessage, int]] = []

    async def send(
        self, queue: QueueName, message: QueueMessage, *, delay_seconds: int = 0
    ) -> None:
        self.sent.append((queue, message, delay_seconds))


class FakeMetrics:
    """`MetricsPort` that records every value."""

    def __init__(self) -> None:
        self.emitted: list[tuple[str, float, dict[str, object]]] = []

    def emit_metric(
        self,
        name: str,
        value: float,
        dimensions: Mapping[str, object] | None = None,
    ) -> None:
        self.emitted.append((str(name), value, dict(dimensions or {})))


class FakeUploadKeys:
    """`AgedUploadKeys` over a dict, with a version per row as its ETag. `changed` keys
    have moved on since they were listed (ETag mismatch)."""

    def __init__(self) -> None:
        self.rows: dict[UUID, UploadKey] = {}
        self.recovered: dict[UUID, datetime] = {}
        self.versions: dict[UUID, int] = {}
        self.changed: set[UUID] = set()
        self.deleted: list[UUID] = []

    def add(
        self,
        key: UUID,
        for_invoice: UUID,
        created_at: datetime,
        correlation_id: UUID = CORRELATION_ID,
    ) -> UploadKey:
        entry = UploadKey(
            invoice_id=for_invoice,
            supplier_id=SUPPLIER_ID,
            correlation_id=correlation_id,
            created_at=created_at,
            content_sha256="ab" * 32,
            content_type=UploadContentType.JPEG,
            device_check=DeviceCheck.PASSED,
        )
        self.rows[key] = entry
        self.versions[key] = 1
        return entry

    def _etag(self, key: UUID) -> str:
        return f"v{self.versions[key]}"

    def _current(self, item: AgedUploadKey) -> bool:
        return (
            item.key in self.rows
            and item.key not in self.changed
            and item.etag == self._etag(item.key)
        )

    async def older_than(self, cutoff: datetime, limit: int) -> list[AgedUploadKey]:
        return [
            AgedUploadKey(key, entry, self._etag(key), self.recovered.get(key))
            for key, entry in self.rows.items()
            if entry.created_at < cutoff
        ][:limit]

    async def mark_recovered(
        self, item: AgedUploadKey, at: datetime
    ) -> AgedUploadKey | None:
        if not self._current(item):
            return None
        self.recovered[item.key] = at
        self.versions[item.key] += 1
        return AgedUploadKey(item.key, item.value, self._etag(item.key), at)

    async def delete(self, item: AgedUploadKey) -> bool:
        if item.key not in self.rows:
            return True
        if not self._current(item):
            return False
        del self.rows[item.key]
        self.deleted.append(item.key)
        return True


class FakeReminders:
    """`ReminderStore` that records each delete; `failing` makes every delete raise."""

    def __init__(self) -> None:
        self.deleted: list[tuple[UUID, str]] = []
        self.failing = False

    async def delete(self, supplier_id: UUID, po_number: str) -> None:
        if self.failing:
            raise ServiceUnavailableError()
        self.deleted.append((supplier_id, po_number))


def _closed_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
    return port


@contextmanager
def stopped_database() -> Iterator[Engine]:
    """An engine for a PostgreSQL server that is not running."""
    engine = postgres_engine(
        host="127.0.0.1",
        port=_closed_port(),
        database="invoicing_test",
        user="pipeline-login",
        password=lambda: "unused",
        sslmode="disable",
    )
    try:
        yield engine
    finally:
        engine.dispose()
