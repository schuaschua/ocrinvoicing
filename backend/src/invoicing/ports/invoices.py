"""The invoice store (AD-3, AD-4, AD-5): `intake.invoice`, its status history, admin
items and image hashes. One adapter, over PostgreSQL (`adapters/postgres/`).

Every method raises `DatabaseOfflineError` (domain/errors.py) when it can't connect to
PostgreSQL at all, typically because the server is stopped (AD-7, AD-12); a failing
query raises as it is."""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from invoicing.domain.status import InvoiceStatus, Stage
from invoicing.domain.transitions import AdminRouting, Claim, Transition
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


@dataclass(frozen=True)
class InvoiceState:
    """An invoice's status, lease and posting backoff, with the database's clock
    (`now`), which every lease is measured against (AD-3)."""

    status: InvoiceStatus
    claimed_until: datetime | None
    now: datetime
    next_attempt_at: datetime | None = None


@dataclass(frozen=True)
class StaleInvoice:
    """An invoice the sweeper may re-enqueue (AD-2): what `domain.sweep` decides on,
    and the ids its message carries."""

    invoice_id: UUID
    correlation_id: UUID
    status: InvoiceStatus
    claimed_until: datetime | None
    next_attempt_at: datetime | None
    # The invoice's `created_at`: the re-enqueued message's `first_enqueued_at`.
    created_at: datetime


@dataclass(frozen=True)
class StaleScan:
    """One sweep's read (AD-2). `settled` is whether the database has been up for
    longer than `stale_after`; until then `invoices` is empty, because messages that
    waited out the stop (AD-7) have not drained yet."""

    now: datetime
    settled: bool
    invoices: tuple[StaleInvoice, ...]


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

    async def state(self, invoice_id: UUID) -> InvoiceState | None:
        """The invoice's status and lease, or None when there is no row."""
        ...

    async def claim(self, claim: Claim) -> bool:
        """Move the invoice to `claim.claim_status` with a lease of `claim.lease`, from
        its input status or from an expired claim (AD-3). False when the invoice can't
        be claimed (another worker holds a live lease, or it moved on): nothing is
        written and the message is acknowledged."""
        ...

    async def release_claim(self, claim: Claim) -> bool:
        """End `claim`'s lease now, leaving the status as it is, so the stage's own
        retry (a DI 429 re-enqueue, a host retry) can reclaim it at once (AD-3: an
        expired lease may be reclaimed). False when the invoice is no longer in the
        claim status."""
        ...

    async def stale(
        self, stale_after: timedelta, *, stages: frozenset[Stage], limit: int
    ) -> StaleScan:
        """At most `limit` invoices the sweeper would send to one of `stages` (the
        `domain.sweep` map: expired leases only, backoffs that are due) whose status
        changed more than `stale_after` ago, once the database has been up for more
        than `stale_after` (`pg_postmaster_start_time()`, AD-2)."""
        ...

    async def existing(self, invoice_ids: Collection[UUID]) -> frozenset[UUID]:
        """Which of `invoice_ids` have an invoice row."""
        ...
