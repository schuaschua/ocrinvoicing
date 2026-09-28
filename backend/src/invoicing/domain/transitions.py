"""Transition and `route_to_admin` plans (AD-3, AD-4).

Pure: each function checks the state machine and returns what one transaction must
do. The Postgres adapter executes a plan as a conditional `UPDATE ... WHERE id = :id
AND status = :from` plus its `intake.status_history` row (and, for a routing, its
`intake.admin_item` rows) in one transaction; zero rows changed means the plan is
discarded (AD-2).
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from uuid import UUID

from invoicing.domain.ids import new_uuid7
from invoicing.domain.reasons import ReasonCode
from invoicing.domain.status import InvoiceStatus, can_route_to_admin, is_allowed


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
) -> AdminRouting:
    """The only way into `in_admin_queue` (AD-4): one admin item per reason, all
    under one new UUIDv7 `routing_id`. Every failing reason is routed together, so
    an admin sees them all; a reason given twice is kept once. The caller passes its
    claim state as `from_status`."""
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
        invoice_id, from_status, InvoiceStatus.IN_ADMIN_QUEUE, actor
    )
    return AdminRouting(transition=transition, routing_id=routing_id, items=items)
