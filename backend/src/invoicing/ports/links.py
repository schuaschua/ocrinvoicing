"""The supplier link registry (AD-6): which supplier a link token belongs to.

Storage contract, shared with the load script that issues and revokes links (Story 1.6):

- Azure Table `supplierlinks`, one entity per issued link. The token is never stored.
- `RowKey` = `token_hash(token)` (`domain/links.py`): SHA-256 of the token's base64url
  text, 64 lowercase hex characters.
- `PartitionKey` = the first 2 characters of that hash, which spreads links over 256
  partitions and keeps every lookup a single-entity read.
- Properties: `supplier_id` (the `master.supplier` id, a UUID string), `supplier_name`
  (display only), `issued_at` (UTC datetime) and `revoked_at` (UTC datetime, absent or
  null while the link is active). Revoking sets `revoked_at`; rows are never deleted.

The hash is as sensitive as a log field as the token itself: never log it (AD-14).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

SUPPLIER_LINKS_TABLE = "supplierlinks"
PARTITION_KEY_LENGTH = 2


def partition_key(token_hash: str) -> str:
    """The `PartitionKey` of the link whose `RowKey` is `token_hash`."""
    return token_hash[:PARTITION_KEY_LENGTH]


@dataclass(frozen=True)
class SupplierLink:
    """One registry entry. `supplier_name` is for display on the upload page only."""

    supplier_id: UUID
    supplier_name: str
    issued_at: datetime | None
    revoked_at: datetime | None

    @property
    def is_active(self) -> bool:
        """A revoked link accepts no uploads (AD-6)."""
        return self.revoked_at is None


class SupplierLinkRegistry(Protocol):
    """Resolves a link by its token hash. Story 1.6 adds issuing and revoking."""

    async def resolve(self, token_hash: str) -> SupplierLink | None:
        """The link stored under `token_hash`, or None when there is none. Raises
        `ServiceUnavailableError` when the store can't answer."""
        ...
