"""The admin actions, run by staff-api (Stories 2.10 and 3.3, AD-3, AD-4, AD-11,
AD-18). One adapter,
over PostgreSQL (`adapters/postgres/admin_actions.py`).

Each method is one transaction on a queued invoice: the `domain/actions.py` guard,
re-checked on the open reasons (the latest `routing_id`), then the conditional
transition from `in_admin_queue`, then the action's rows and its `audit.event` row
(ids and the admin's object id only, never a field value). Nothing is enqueued or
written to blob storage here: the caller does that after the commit.

Every method raises `DatabaseOfflineError` when the database can't be reached (AD-7),
and `correct` raises `ValidationFailedError` (nothing written) for a field or value it
can't take."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from invoicing.domain.actions import Correction, LineEdits


class Outcome(StrEnum):
    """How an action ended."""

    HANDLED = "handled"
    # Unknown invoice: 404, so its existence isn't revealed.
    NOT_FOUND = "not_found"
    # No longer queued, or its transition changed no rows: another admin acted first.
    CONFLICT = "conflict"
    # The open reasons don't allow the action.
    NOT_ALLOWED = "not_allowed"
    # Approve with `BANK_CHANGED` open, without both call-back checks (AD-11).
    CHECKS_REQUIRED = "checks_required"


@dataclass(frozen=True)
class ActionResult:
    """An action's outcome. When handled: the invoice's correlation id (for the queue
    message) and, for Correct, what was written and when (for the corrections blob)."""

    outcome: Outcome
    correlation_id: UUID | None = None
    correction: Correction | None = field(default=None, repr=False)
    at: datetime | None = None


class AdminActions(Protocol):
    """The Story 2.10 and 3.3 actions on a queued invoice. `admin_oid` is the acting
    admin's Entra object id, recorded in the audit entry; `routing_id` is the routing
    the admin saw: any other latest routing is `CONFLICT` (routed again meanwhile)."""

    async def correct(
        self,
        invoice_id: UUID,
        fields: Mapping[str, str],
        lines: LineEdits,
        admin_oid: str,
        routing_id: UUID | None,
    ) -> ActionResult:
        """New `source=admin` rows on the latest run and the move to
        `awaiting_validation`, in one transaction."""
        ...

    async def reextract(
        self, invoice_id: UUID, admin_oid: str, routing_id: UUID | None
    ) -> ActionResult:
        """The move to `awaiting_extraction`."""
        ...

    async def retry_intake(
        self, invoice_id: UUID, admin_oid: str, routing_id: UUID | None
    ) -> ActionResult:
        """The move to `received`, so the upload goes through the quality stage again."""
        ...

    async def reject(
        self, invoice_id: UUID, reason: str, admin_oid: str, routing_id: UUID | None
    ) -> ActionResult:
        """The move to `rejected`; `reason` is kept in the audit entry only."""
        ...

    async def approve(
        self,
        invoice_id: UUID,
        reason: str,
        checks: Mapping[str, bool],
        admin_oid: str,
        routing_id: UUID | None,
    ) -> ActionResult:
        """The move to `ready_to_post` (its posting count and backoff reset, AD-3);
        `reason` and `checks` are kept in the audit entry only. `CHECKS_REQUIRED` when
        `BANK_CHANGED` is open and `checks` doesn't confirm both call-back checks."""
        ...
