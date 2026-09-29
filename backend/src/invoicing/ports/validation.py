"""What the `validate` stage reads and writes in the invoice store (Stories 2.5 and
2.6, AD-18, AD-19, AD-9). One adapter, over PostgreSQL (`adapters/postgres/validation.py`).

Every method raises `DatabaseOfflineError` (domain/errors.py) when it can't connect to
PostgreSQL at all (AD-7); a failing query raises as it is."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Protocol
from uuid import UUID

from invoicing.domain.current_values import CurrentValues
from invoicing.domain.transitions import AdminRouting, Transition
from invoicing.domain.validation import DuplicateFacts, LineMatch
from invoicing.ports.intake import IntakeSource


@dataclass(frozen=True)
class InvoiceFacts:
    """Who sent the invoice and for which supplier (AD-5): the supplier is the
    invoice row's, never OCR's (P-5). `delivery_id` is set for goods-in scans;
    `photo_taken_at` (UTC) is None for a PDF or a photo without EXIF, and `phash`
    (unsigned 64-bit, AD-9) None when there is no image hash."""

    source: IntakeSource
    supplier_id: UUID
    delivery_id: UUID | None
    photo_taken_at: datetime | None = None
    phash: int | None = None


def _no_bank() -> Mapping[str, str]:
    return MappingProxyType({})


@dataclass(frozen=True)
class ValidationInput:
    """The invoice's facts, its AD-18 current values (None: no extraction run) and the
    supplier's `master.supplier_bank` fingerprints by bare field id (AD-11: never a
    ciphertext)."""

    facts: InvoiceFacts
    values: CurrentValues | None
    master_bank: Mapping[str, str] = field(default_factory=_no_bank)


@dataclass(frozen=True)
class ValidationResult:
    """What one validation saves, in one transaction: `invoice.po_number`, the PO line
    of each current invoice line (by row id; None clears it) and the finish, either
    `validating -> ready_to_post` or the routing of every failing reason (AD-4)."""

    po_number: str | None
    matches: Mapping[UUID, LineMatch | None]
    finish: Transition | AdminRouting


# Called under the per-supplier lock with the current quantity per `po_line_id` on the
# supplier's other non-rejected invoices, and the duplicate facts of the supplier's
# earlier (lower id) non-rejected invoices (AD-9).
type ComputeResult = Callable[
    [Mapping[UUID, Decimal], Sequence[DuplicateFacts]], ValidationResult
]


class ValidationRepository(Protocol):
    """The validate stage's reads and its one finishing transaction."""

    async def load(self, invoice_id: UUID) -> ValidationInput | None:
        """The invoice's facts and current values, or None when there is no invoice."""
        ...

    async def finish_locked(
        self, invoice_id: UUID, supplier_id: UUID, compute: ComputeResult
    ) -> bool:
        """One transaction under the supplier's advisory lock (AD-9, AD-19): read the
        other invoices' current quantities and the earlier invoices' duplicate facts,
        call `compute`, then make its finish and save its PO and line matches. False, with nothing written, when the finish
        changed no rows (AD-2)."""
        ...
