"""Upload idempotency keys (AD-6): which invoice an upload's `Idempotency-Key` created.

Storage contract, shared with the sweeper (Story 2.2), which re-enqueues uploads whose
enqueue was lost and deletes rows older than 24 hours:

- Azure Table `uploadkeys`, one entity per key.
- `RowKey` = the key, a UUID in canonical lowercase 8-4-4-4-12 form.
- `PartitionKey` = the first 2 hex characters of the key (the `supplierlinks` scheme).
- Properties: `invoice_id` and `supplier_id` (UUID strings), `correlation_id` (the first
  attempt's, so a replay's queue message stays in the upload's trace), `created_at`
  (UTC datetime), and `content_sha256` (lowercase hex) and `content_type` of the file,
  so a key reused for different bytes is refused instead of dropping the new file.
- `device_check` (Story 1.9): `passed` or `overridden`, as the first attempt sent it. A
  replay keeps it, whatever the retry sends. A row without it, or with it empty
  (written before 1.9), reads as `passed`.
- `recovered_at` (Story 2.2): UTC datetime, set by the sweeper once it re-enqueued an
  orphaned upload, so each orphan is recovered once. Absent otherwise.

The key is a client-chosen value: never log it.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from invoicing.domain.upload import DeviceCheck, UploadContentType

UPLOAD_KEYS_TABLE = "uploadkeys"
PARTITION_KEY_LENGTH = 2


def row_key(key: UUID) -> str:
    """The `RowKey` of `key`."""
    return str(key)


def partition_key(key: UUID) -> str:
    """The `PartitionKey` of `key`."""
    return key.hex[:PARTITION_KEY_LENGTH]


@dataclass(frozen=True)
class UploadKey:
    """What a key maps to: the invoice it created, and for whom."""

    invoice_id: UUID
    supplier_id: UUID
    correlation_id: UUID
    created_at: datetime
    content_sha256: str
    content_type: UploadContentType
    device_check: DeviceCheck


class UploadKeyStore(Protocol):
    """Insert-if-absent over the `uploadkeys` table."""

    async def claim(self, key: UUID, candidate: UploadKey) -> tuple[UploadKey, bool]:
        """Store `candidate` under `key` unless the key is already stored. Returns what
        is stored under it and whether this call inserted it: `(candidate, True)`, or
        the earlier entry and False (whoever holds it; the caller checks the supplier
        and the content). Two concurrent claims return the same entry, and only one
        of them True. Raises `ServiceUnavailableError` when the store can't answer."""
        ...


@dataclass(frozen=True)
class AgedUploadKey:
    """A stored key and what it maps to, as the sweeper lists them, with the row's
    ETag (every write is conditional on it) and `recovered_at`."""

    key: UUID
    value: UploadKey
    etag: str
    recovered_at: datetime | None = None


class AgedUploadKeys(Protocol):
    """The sweeper's view of `uploadkeys` (AD-2, AD-6)."""

    async def older_than(self, cutoff: datetime, limit: int) -> list[AgedUploadKey]:
        """At most `limit` readable keys created before `cutoff`. A row that can't be
        read is skipped and logged by a code. Raises `ServiceUnavailableError` when
        the store can't answer."""
        ...

    async def mark_recovered(
        self, item: AgedUploadKey, at: datetime
    ) -> AgedUploadKey | None:
        """Set `recovered_at` on `item`'s row if it is unchanged since it was listed
        (its ETag). The updated item with its new ETag, or None when the row changed
        or is gone. Raises `ServiceUnavailableError` when the store can't answer."""
        ...

    async def delete(self, item: AgedUploadKey) -> bool:
        """Delete `item`'s row if it is unchanged since it was listed (its ETag). True
        when deleted or already gone, False when it changed. Raises
        `ServiceUnavailableError` when the store can't answer."""
        ...
