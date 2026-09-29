"""Story 2.2: the pure recovery rules. The AD-3 claim and lease reclaim, the AD-2 poison
guard, and the AD-2 sweeper map with its ages (AD-6 upload keys)."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from invoicing.domain.status import (
    InvoiceStatus,
    Stage,
    poison_route_from,
)
from invoicing.domain.sweep import (
    sweep_stage,
)
from invoicing.domain.transitions import (
    claim_from,
    plan_claim,
)

S = InvoiceStatus
INVOICE = UUID("0192f0c1-7a2b-7c3d-8e4f-0123456789ab")
NOW = datetime(2026, 9, 29, 2, 0, tzinfo=UTC)
PAST = NOW - timedelta(seconds=1)
FUTURE = NOW + timedelta(minutes=5)


# --- AD-3 claim and reclaim ---------------------------------------------------------------


@pytest.mark.parametrize("stage", [Stage.EXTRACT])
def test_story_2_2_a_claim_takes_the_input_status_or_an_expired_lease_only(
    stage: Stage,
) -> None:
    claim = plan_claim(INVOICE, stage, "t")

    def from_(status: S | None, lease: datetime | None) -> S | None:
        return claim_from(
            claim, status, claimed_until=lease, next_attempt_at=None, now=NOW
        )

    assert from_(claim.input_status, None) is claim.input_status
    # Lease reclaim: the lease has expired (or there is none).
    assert from_(claim.claim_status, PAST) is claim.claim_status
    assert from_(claim.claim_status, NOW) is claim.claim_status
    assert from_(claim.claim_status, None) is claim.claim_status
    # A live lease is never taken.
    assert from_(claim.claim_status, FUTURE) is None
    # Moved on, or missing: zero rows, acknowledge.
    assert from_(S.IN_ADMIN_QUEUE, None) is None
    assert from_(S.POSTED, None) is None
    assert from_(None, None) is None


# --- AD-2 poison guard ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("stage", "status", "lease", "expected"),
    [
        (Stage.EXTRACT, S.EXTRACTING, PAST, S.EXTRACTING),
        (Stage.EXTRACT, S.EXTRACTING, FUTURE, None),
    ],
)
def test_story_2_2_poison_routes_only_from_the_queues_input_or_an_expired_claim(
    stage: Stage, status: S | None, lease: datetime | None, expected: S | None
) -> None:
    assert poison_route_from(stage, status, lease, NOW) is expected


# --- AD-2 sweeper map -----------------------------------------------------------------------

ALL_STAGES = frozenset(Stage)


@pytest.mark.parametrize(
    ("status", "lease", "next_attempt", "expected"),
    [(S.EXTRACTING, PAST, None, Stage.EXTRACT)],
)
def test_story_2_2_the_sweeper_map_is_ad2_once_every_stage_is_consumed(
    status: S,
    lease: datetime | None,
    next_attempt: datetime | None,
    expected: Stage | None,
) -> None:
    assert (
        sweep_stage(
            status,
            claimed_until=lease,
            next_attempt_at=next_attempt,
            now=NOW,
            stages=ALL_STAGES,
        )
        is expected
    )
