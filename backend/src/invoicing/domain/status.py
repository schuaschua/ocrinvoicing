"""The invoice state machine (AD-3): the one `status` column, the transitions that
exist, and what a stage does when its claim changes zero rows (AD-2)."""

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum


class InvoiceStatus(StrEnum):
    """`intake.invoice.status`, the only lifecycle field (AD-3)."""

    RECEIVED = "received"
    AWAITING_EXTRACTION = "awaiting_extraction"
    EXTRACTING = "extracting"
    AWAITING_VALIDATION = "awaiting_validation"
    VALIDATING = "validating"
    READY_TO_POST = "ready_to_post"
    POSTING = "posting"
    POSTED = "posted"
    IN_ADMIN_QUEUE = "in_admin_queue"
    REJECTED = "rejected"


_S = InvoiceStatus

TERMINAL: frozenset[InvoiceStatus] = frozenset({_S.POSTED, _S.REJECTED})

# The AD-3 diagram's edges, except the way into `in_admin_queue`, which is
# `route_to_admin` only (AD-4) and is allowed from any other non-terminal status.
TRANSITIONS: frozenset[tuple[InvoiceStatus, InvoiceStatus]] = frozenset(
    {
        (_S.RECEIVED, _S.AWAITING_EXTRACTION),
        (_S.AWAITING_EXTRACTION, _S.EXTRACTING),
        (_S.EXTRACTING, _S.AWAITING_VALIDATION),
        (_S.AWAITING_VALIDATION, _S.VALIDATING),
        (_S.VALIDATING, _S.READY_TO_POST),
        (_S.READY_TO_POST, _S.POSTING),
        (_S.POSTING, _S.READY_TO_POST),
        (_S.POSTING, _S.POSTED),
        (_S.IN_ADMIN_QUEUE, _S.AWAITING_VALIDATION),
        (_S.IN_ADMIN_QUEUE, _S.READY_TO_POST),
        (_S.IN_ADMIN_QUEUE, _S.AWAITING_EXTRACTION),
        (_S.IN_ADMIN_QUEUE, _S.RECEIVED),
        (_S.IN_ADMIN_QUEUE, _S.REJECTED),
    }
)


def is_allowed(from_status: InvoiceStatus, to_status: InvoiceStatus) -> bool:
    """Whether `from_status -> to_status` is a transition of the state machine."""
    if to_status is _S.IN_ADMIN_QUEUE:
        return can_route_to_admin(from_status)
    return (from_status, to_status) in TRANSITIONS


def can_route_to_admin(from_status: InvoiceStatus) -> bool:
    """`in_admin_queue` is entered from any non-terminal status but itself (AD-3)."""
    return from_status not in TERMINAL and from_status is not _S.IN_ADMIN_QUEUE


class Stage(StrEnum):
    """The pipeline stages, each fed by its own queue (AD-2)."""

    QUALITY = "quality"
    EXTRACT = "extract"
    VALIDATE = "validate"
    POST = "post"


# AD-2 recovery: when a stage's transition changes zero rows it reads the status. A
# status in its final targets means the stage already finished, so the next stage is
# queued again (None: nothing follows) and the message acknowledged. Any other status
# is only acknowledged.
FINAL_TARGETS: Mapping[Stage, Mapping[InvoiceStatus, Stage | None]] = {
    Stage.QUALITY: {_S.AWAITING_EXTRACTION: Stage.EXTRACT},
    Stage.EXTRACT: {_S.AWAITING_VALIDATION: Stage.VALIDATE},
    Stage.VALIDATE: {_S.READY_TO_POST: Stage.POST, _S.IN_ADMIN_QUEUE: None},
    Stage.POST: {_S.POSTED: None},
}


def requeue_after_redelivery(
    stage: Stage, status: InvoiceStatus | None
) -> Stage | None:
    """The stage to queue again when `stage` finds the invoice already at `status`
    (AD-2), or None to only acknowledge."""
    if status is None:
        return None
    return FINAL_TARGETS[stage].get(status)


# Each stage's input status: the status its queue message expects (AD-2).
INPUT_STATUS: Mapping[Stage, InvoiceStatus] = {
    Stage.QUALITY: _S.RECEIVED,
    Stage.EXTRACT: _S.AWAITING_EXTRACTION,
    Stage.VALIDATE: _S.AWAITING_VALIDATION,
    Stage.POST: _S.READY_TO_POST,
}

# AD-3 claim-before-side-effect: a stage with a side effect moves the invoice from its
# input status to its claim status, under a lease. `quality` has no claim.
CLAIM_STATUS: Mapping[Stage, InvoiceStatus] = {
    Stage.EXTRACT: _S.EXTRACTING,
    Stage.VALIDATE: _S.VALIDATING,
    Stage.POST: _S.POSTING,
}


def lease_expired(claimed_until: datetime | None, now: datetime) -> bool:
    """Whether a claim's lease has run out (AD-3). A claim state with no lease at all
    counts as expired, so it can never strand an invoice."""
    return claimed_until is None or claimed_until <= now


def poison_route_from(
    stage: Stage,
    status: InvoiceStatus | None,
    claimed_until: datetime | None,
    now: datetime,
    next_attempt_at: datetime | None = None,
) -> InvoiceStatus | None:
    """The status a poison message of `stage` routes `PROCESSING_FAILED` from (AD-2),
    or None to only acknowledge it.

    Routed only while the invoice is still in the stage's input status, or in its
    claim status with an expired lease. A missing row counts as `received` for
    `quality` only: `route_to_admin` creates it from the blob metadata (AD-4).
    `ready_to_post` waiting on a scheduled retry (`next_attempt_at` in the future) is
    not the post stage's input yet: the backoff owns it (AD-3)."""
    if status is None:
        return _S.RECEIVED if stage is Stage.QUALITY else None
    if status is INPUT_STATUS[stage]:
        waiting = next_attempt_at is not None and next_attempt_at > now
        return None if stage is Stage.POST and waiting else status
    if status is CLAIM_STATUS.get(stage) and lease_expired(claimed_until, now):
        return status
    return None
