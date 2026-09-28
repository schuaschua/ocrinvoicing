"""Upload idempotency keys (AD-6): which invoice an upload's `Idempotency-Key` created.

Storage contract, shared with the sweeper that deletes rows older than 24 hours (Story 2.2):

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
