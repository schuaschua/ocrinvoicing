"""Transition and `route_to_admin` plans (AD-3, AD-4).

Pure: each function checks the state machine and returns what one transaction must
do. The Postgres adapter executes a plan as a conditional `UPDATE ... WHERE id = :id
AND status = :from` plus its `intake.status_history` row (and, for a routing, its
`intake.admin_item` rows) in one transaction; zero rows changed means the plan is
discarded (AD-2).
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from types import MappingProxyType
from uuid import UUID

from invoicing.domain.ids import new_uuid7
from invoicing.domain.reasons import ReasonCode
from invoicing.domain.status import (
    CLAIM_STATUS,
    INPUT_STATUS,
    InvoiceStatus,
    Stage,
    can_route_to_admin,
    is_allowed,
    lease_expired,
)

# AD-3: a claim holds the invoice for 10 minutes; after that it may be reclaimed.
CLAIM_LEASE = timedelta(minutes=10)


class TransitionNotAllowedError(ValueError):
    """A transition the AD-3 state machine does not have. A programming error, never
    a data problem, so it names only the two statuses."""

    def __init__(self, from_status: InvoiceStatus, to_status: InvoiceStatus) -> None:
        super().__init__(f"no transition {from_status} -> {to_status}")
        self.from_status = from_status
        self.to_status = to_status


@dataclass(frozen=True)
class Transition:
    """One conditional status change and its history row."""

    invoice_id: UUID
    from_status: InvoiceStatus
    to_status: InvoiceStatus
    # Who moved it, e.g. `pipeline:quality` (the history row's `actor`).
    actor: str
    # AD-2 poison guard: from a claim status, only while its lease has expired, so a
    # live claim is never taken (the adapter adds `AND claimed_until <= now()`).
    require_expired_lease: bool = False


def plan_transition(
    invoice_id: UUID,
    from_status: InvoiceStatus,
    to_status: InvoiceStatus,
    actor: str,
) -> Transition:
    """The plan for `from_status -> to_status`. `in_admin_queue` is refused here: the
    only way in is `route_to_admin` (AD-4)."""
    if to_status is InvoiceStatus.IN_ADMIN_QUEUE or not is_allowed(
        from_status, to_status
    ):
        raise TransitionNotAllowedError(from_status, to_status)
    return Transition(invoice_id, from_status, to_status, actor)


def _empty_detail() -> Mapping[str, object]:
    return MappingProxyType({})


@dataclass(frozen=True)
class AdminReason:
    """One reason to route, with what the admin screen needs to show it (AD-4).
    `field_ids` are AD-18 field ids; `detail` holds ids, codes and amounts, never
    bank details (AD-11)."""

    reason: ReasonCode
    field_ids: tuple[str, ...] = ()
    detail: Mapping[str, object] = field(default_factory=_empty_detail)
    run_id: UUID | None = None


@dataclass(frozen=True)
class AdminItem:
    """One `intake.admin_item` row."""

    id: UUID
    invoice_id: UUID
    routing_id: UUID
    reason: ReasonCode
    field_ids: tuple[str, ...]
    detail: Mapping[str, object]
    run_id: UUID | None


@dataclass(frozen=True)
class AdminRouting:
    """The transition into `in_admin_queue` and its admin items, one transaction."""

    transition: Transition
    routing_id: UUID
    items: tuple[AdminItem, ...]


def route_to_admin(
    invoice_id: UUID,
    reasons: Sequence[ReasonCode | AdminReason],
    from_status: InvoiceStatus,
    *,
    actor: str,
    new_id: Callable[[], UUID] = new_uuid7,
    require_expired_lease: bool = False,
) -> AdminRouting:
    """The only way into `in_admin_queue` (AD-4): one admin item per reason, all
    under one new UUIDv7 `routing_id`. Every failing reason is routed together, so
    an admin sees them all; a reason given twice is kept once. The caller passes its
    claim state as `from_status`; a poison trigger routing from a claim state it does
    not hold sets `require_expired_lease` (AD-2)."""
    if not can_route_to_admin(from_status):
        raise TransitionNotAllowedError(from_status, InvoiceStatus.IN_ADMIN_QUEUE)
    unique: dict[ReasonCode, AdminReason] = {}
    for reason in reasons:
        item = reason if isinstance(reason, AdminReason) else AdminReason(reason)
        unique.setdefault(item.reason, item)
    if not unique:
        raise ValueError("route_to_admin needs at least one reason")
    routing_id = new_id()
    items = tuple(
        AdminItem(
            id=new_id(),
            invoice_id=invoice_id,
            routing_id=routing_id,
            reason=item.reason,
            field_ids=item.field_ids,
            detail=item.detail,
            run_id=item.run_id,
        )
        for item in unique.values()
    )
    transition = Transition(
        invoice_id,
        from_status,
        InvoiceStatus.IN_ADMIN_QUEUE,
        actor,
        require_expired_lease=require_expired_lease,
    )
    return AdminRouting(transition=transition, routing_id=routing_id, items=items)


@dataclass(frozen=True)
class Claim:
    """A stage's claim on an invoice (AD-3): from its input status to its claim
    status with a lease, or a reclaim of that claim status once the lease expired."""

    invoice_id: UUID
    stage: Stage
    input_status: InvoiceStatus
    claim_status: InvoiceStatus
    actor: str
    lease: timedelta = CLAIM_LEASE


def plan_claim(invoice_id: UUID, stage: Stage, actor: str) -> Claim:
    """The claim `stage` makes before its side effect. `quality` has none."""
    claim_status = CLAIM_STATUS.get(stage)
    if claim_status is None:
        raise ValueError(f"the {stage} stage makes no claim")
    return Claim(invoice_id, stage, INPUT_STATUS[stage], claim_status, actor)


def claim_from(
    claim: Claim,
    status: InvoiceStatus | None,
    *,
    claimed_until: datetime | None,
    next_attempt_at: datetime | None,
    now: datetime,
) -> InvoiceStatus | None:
    """The status `claim` moves the invoice from, or None when it can't be claimed
    now, so the message is acknowledged (AD-3). A live lease is never taken. The post
    claim also waits for `next_attempt_at` (AD-3 posting backoff)."""
    if status is claim.input_status:
        due = next_attempt_at is None or next_attempt_at <= now
        return status if claim.stage is not Stage.POST or due else None
    if status is claim.claim_status and lease_expired(claimed_until, now):
        return status
    return None
