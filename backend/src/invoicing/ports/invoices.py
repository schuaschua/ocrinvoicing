"""The invoice store (AD-3, AD-4, AD-5): `intake.invoice`, its status history, admin
items and image hashes. One adapter, over PostgreSQL (`adapters/postgres/`)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from invoicing.domain.status import InvoiceStatus
from invoicing.domain.transitions import AdminRouting, Transition
from invoicing.ports.intake import IntakeBlobMetadata


@dataclass(frozen=True)
class NewInvoice:
    """An invoice row to create from its intake blob (AD-5): the supplier comes from
    the metadata only, never from OCR."""

    metadata: IntakeBlobMetadata
    correlation_id: UUID
    # The history row's actor, e.g. `pipeline:quality`.
    actor: str


@dataclass(frozen=True)
class QualityFacts:
    """What the quality stage learnt about the original, saved with its transition:
    `photo_taken_at` (UTC, AD-19; None when the file has none) and the 64-bit
    perceptual hash as an unsigned integer (AD-9; None for PDFs)."""

    photo_taken_at: datetime | None
    phash: int | None


class InvoiceRepository(Protocol):
    """Every write is one transaction; a transition is conditional on the current
    status and writes its history row with it (AD-3)."""

    async def status(self, invoice_id: UUID) -> InvoiceStatus | None:
        """The invoice's status, or None when there is no row."""
        ...

    async def insert_if_absent(self, invoice: NewInvoice) -> bool:
        """Create the row as `received` with its first history row, unless it exists
        (`INSERT ... ON CONFLICT (id) DO NOTHING`, AD-5). True when created now."""
        ...

    async def transition(
        self, plan: Transition, *, quality: QualityFacts | None = None
    ) -> bool:
        """Run `plan` (and save `quality` with it). False when the status was not
        `plan.from_status`, so nothing changed (AD-2)."""
        ...

    async def route_to_admin(
        self,
        routing: AdminRouting,
        *,
        metadata: NewInvoice | None = None,
        quality: QualityFacts | None = None,
    ) -> bool:
        """Move the invoice into `in_admin_queue` with one admin item per reason, all
        in one transaction (AD-4); with `metadata`, create a missing row first. False
        when the status was not the routing's `from_status`: nothing is written."""
        ...
