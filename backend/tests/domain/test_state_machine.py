"""Story 2.1: the reason catalogue (AD-4), the AD-3 state machine and the AD-2
redelivery rule, and the pure transition and `route_to_admin` plans."""

from uuid import UUID

import pytest

from invoicing.domain.ids import new_uuid7
from invoicing.domain.reasons import ReasonCode
from invoicing.domain.status import (
    TERMINAL,
    InvoiceStatus,
    Stage,
    can_route_to_admin,
    is_allowed,
    requeue_after_redelivery,
)
from invoicing.domain.transitions import (
    AdminReason,
    Transition,
    TransitionNotAllowedError,
    plan_transition,
    route_to_admin,
)

S = InvoiceStatus
INVOICE = UUID("0192f0c1-7a2b-7c3d-8e4f-0123456789ab")


def test_story_2_1_the_reason_catalogue_is_exactly_ad4() -> None:
    assert {code.value for code in ReasonCode} == {
        "UNREADABLE",
        "UNSUPPORTED_DOCUMENT",
        "EXTRACTION_QUOTA",
        "LOW_CONFIDENCE",
        "PO_MISMATCH",
        "DUPLICATE",
        "DATE_MISMATCH",
        "NO_PHOTO_DATE",
        "BANK_CHANGED",
        "SUPPLIER_ID_MISMATCH",
        "ACCOUNTS_API_ERROR",
        "PROCESSING_FAILED",
    }


def test_story_2_1_the_statuses_are_the_ad3_diagram() -> None:
    assert {s.value for s in InvoiceStatus} == {
        "received",
        "awaiting_extraction",
        "extracting",
        "awaiting_validation",
        "validating",
        "ready_to_post",
        "posting",
        "posted",
        "in_admin_queue",
        "rejected",
    }
    assert TERMINAL == {S.POSTED, S.REJECTED}


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [
        (S.RECEIVED, S.AWAITING_EXTRACTION),
        (S.AWAITING_EXTRACTION, S.EXTRACTING),
        (S.EXTRACTING, S.AWAITING_VALIDATION),
        (S.AWAITING_VALIDATION, S.VALIDATING),
        (S.VALIDATING, S.READY_TO_POST),
        (S.READY_TO_POST, S.POSTING),
        (S.POSTING, S.READY_TO_POST),
        (S.POSTING, S.POSTED),
        (S.IN_ADMIN_QUEUE, S.AWAITING_VALIDATION),
        (S.IN_ADMIN_QUEUE, S.READY_TO_POST),
        (S.IN_ADMIN_QUEUE, S.AWAITING_EXTRACTION),
        (S.IN_ADMIN_QUEUE, S.RECEIVED),
        (S.IN_ADMIN_QUEUE, S.REJECTED),
    ],
)
def test_story_2_1_diagram_transitions_are_planned(
    from_status: InvoiceStatus, to_status: InvoiceStatus
) -> None:
    assert is_allowed(from_status, to_status)
    assert plan_transition(INVOICE, from_status, to_status, "test") == Transition(
        INVOICE, from_status, to_status, "test"
    )


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [
        (S.RECEIVED, S.EXTRACTING),
        (S.RECEIVED, S.POSTED),
        (S.AWAITING_EXTRACTION, S.RECEIVED),
        (S.POSTED, S.READY_TO_POST),
        (S.REJECTED, S.RECEIVED),
        (S.VALIDATING, S.POSTED),
        (S.RECEIVED, S.RECEIVED),
    ],
)
def test_story_2_1_other_transitions_are_refused(
    from_status: InvoiceStatus, to_status: InvoiceStatus
) -> None:
    assert not is_allowed(from_status, to_status)
    with pytest.raises(TransitionNotAllowedError) as raised:
        plan_transition(INVOICE, from_status, to_status, "test")
    assert (raised.value.from_status, raised.value.to_status) == (
        from_status,
        to_status,
    )


def test_story_2_1_in_admin_queue_is_entered_only_through_route_to_admin() -> None:
    # Allowed by the state machine from any non-terminal status...
    assert is_allowed(S.RECEIVED, S.IN_ADMIN_QUEUE)
    # ...but plan_transition never plans it (AD-4: one way in).
    with pytest.raises(TransitionNotAllowedError):
        plan_transition(INVOICE, S.RECEIVED, S.IN_ADMIN_QUEUE, "test")


@pytest.mark.parametrize("status", list(InvoiceStatus))
def test_story_2_1_route_to_admin_from_any_non_terminal_status(
    status: InvoiceStatus,
) -> None:
    expected = status not in TERMINAL and status is not S.IN_ADMIN_QUEUE
    assert can_route_to_admin(status) is expected
    if expected:
        routing = route_to_admin(INVOICE, [ReasonCode.UNREADABLE], status, actor="t")
        assert routing.transition.from_status is status
        assert routing.transition.to_status is S.IN_ADMIN_QUEUE
    else:
        with pytest.raises(TransitionNotAllowedError):
            route_to_admin(INVOICE, [ReasonCode.UNREADABLE], status, actor="t")


def test_story_2_1_route_to_admin_writes_one_item_per_reason_under_one_routing_id() -> (
    None
):
    routing = route_to_admin(
        INVOICE,
        [
            ReasonCode.PO_MISMATCH,
            AdminReason(
                ReasonCode.LOW_CONFIDENCE,
                field_ids=("invoice_total",),
                detail={"confidence": "0.91"},
            ),
            ReasonCode.PO_MISMATCH,  # a repeat is kept once
        ],
        S.VALIDATING,
        actor="pipeline:validate",
    )
    assert routing.routing_id.version == 7
    assert [item.reason for item in routing.items] == [
        ReasonCode.PO_MISMATCH,
        ReasonCode.LOW_CONFIDENCE,
    ]
    assert {item.routing_id for item in routing.items} == {routing.routing_id}
    assert {item.invoice_id for item in routing.items} == {INVOICE}
    ids = [item.id for item in routing.items]
    assert len(set(ids)) == 2 and routing.routing_id not in ids
    low = routing.items[1]
    assert low.field_ids == ("invoice_total",)
    assert dict(low.detail) == {"confidence": "0.91"}
    assert routing.items[0].field_ids == () and dict(routing.items[0].detail) == {}
    assert routing.transition.actor == "pipeline:validate"


def test_story_2_1_each_route_to_admin_call_gets_its_own_routing_id() -> None:
    first = route_to_admin(INVOICE, [ReasonCode.UNREADABLE], S.RECEIVED, actor="t")
    second = route_to_admin(INVOICE, [ReasonCode.UNREADABLE], S.RECEIVED, actor="t")
    assert first.routing_id != second.routing_id


def test_story_2_1_route_to_admin_uses_the_injected_ids() -> None:
    first, second = new_uuid7(1), new_uuid7(2)
    ids = iter([first, second])
    routing = route_to_admin(
        INVOICE,
        [ReasonCode.UNREADABLE],
        S.RECEIVED,
        actor="t",
        new_id=lambda: next(ids),
    )
    assert routing.routing_id == first
    assert [item.id for item in routing.items] == [second]


def test_story_2_1_route_to_admin_needs_a_reason() -> None:
    with pytest.raises(ValueError, match="at least one reason"):
        route_to_admin(INVOICE, [], S.RECEIVED, actor="t")


@pytest.mark.parametrize(
    ("stage", "status", "requeue"),
    [
        (Stage.QUALITY, S.AWAITING_EXTRACTION, Stage.EXTRACT),
        (Stage.QUALITY, S.IN_ADMIN_QUEUE, None),
        (Stage.QUALITY, S.EXTRACTING, None),
        (Stage.QUALITY, S.RECEIVED, None),
        (Stage.QUALITY, None, None),
        (Stage.EXTRACT, S.AWAITING_VALIDATION, Stage.VALIDATE),
        (Stage.VALIDATE, S.READY_TO_POST, Stage.POST),
        (Stage.VALIDATE, S.IN_ADMIN_QUEUE, None),
        (Stage.POST, S.POSTED, None),
        (Stage.POST, S.POSTING, None),
    ],
)
def test_story_2_1_a_stage_finding_its_final_target_requeues_the_next_one(
    stage: Stage, status: InvoiceStatus | None, requeue: Stage | None
) -> None:
    assert requeue_after_redelivery(stage, status) is requeue
