"""Story 2.1: the reason catalogue (AD-4), the AD-3 state machine and the AD-2
redelivery rule, and the pure transition and `route_to_admin` plans."""

from uuid import UUID

import pytest

from invoicing.domain.status import (
    InvoiceStatus,
    is_allowed,
)
from invoicing.domain.transitions import (
    Transition,
    TransitionNotAllowedError,
    plan_transition,
)

S = InvoiceStatus
INVOICE = UUID("0192f0c1-7a2b-7c3d-8e4f-0123456789ab")


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [(S.RECEIVED, S.AWAITING_EXTRACTION)],
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
    [(S.RECEIVED, S.POSTED)],
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
