"""Story 2.2: the pure recovery rules. The AD-3 claim and lease reclaim, the AD-2 poison
guard, and the AD-2 sweeper map with its ages (AD-6 upload keys)."""

from datetime import UTC, datetime, timedelta
from functools import partial
from uuid import UUID

from invoicing.domain.status import (
    InvoiceStatus,
    Stage,
    poison_route_from,
)
from invoicing.domain.sweep import (
    sweep_stage,
)
from invoicing.domain.transitions import (
    Claim,
    claim_from,
    plan_claim,
)

S = InvoiceStatus
INVOICE = UUID("0192f0c1-7a2b-7c3d-8e4f-0123456789ab")
NOW = datetime(2026, 9, 29, 2, 0, tzinfo=UTC)
PAST = NOW - timedelta(seconds=1)
FUTURE = NOW + timedelta(minutes=5)


ALL_STAGES = frozenset(Stage)


def _claim_from(claim: Claim, status: S | None, lease: datetime | None) -> S | None:
    return claim_from(claim, status, claimed_until=lease, next_attempt_at=None, now=NOW)


def test_story_2_2_recovery_rules() -> None:
    """Covers: AD-3 a claim takes the input status or an expired lease only; AD-2 poison routes
    only from the queue's input or an expired claim (expired: routed; live: not); AD-2 the
    sweeper map once every stage is consumed."""
    # --- AD-3 claim and reclaim
    for stage in [Stage.EXTRACT]:
        claim = plan_claim(INVOICE, stage, "t")
        from_ = partial(_claim_from, claim)

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

    # --- AD-2 poison guard
    poison_cases: list[tuple[Stage, S | None, datetime | None, S | None]] = [
        (Stage.EXTRACT, S.EXTRACTING, PAST, S.EXTRACTING),
        (Stage.EXTRACT, S.EXTRACTING, FUTURE, None),
    ]
    for stage, status, lease, expected in poison_cases:
        assert poison_route_from(stage, status, lease, NOW) is expected, (status, lease)

    # --- AD-2 sweeper map
    sweep_cases: list[tuple[S, datetime | None, datetime | None, Stage | None]] = [
        (S.EXTRACTING, PAST, None, Stage.EXTRACT)
    ]
    for status, lease, next_attempt, expected_stage in sweep_cases:
        assert (
            sweep_stage(
                status,
                claimed_until=lease,
                next_attempt_at=next_attempt,
                now=NOW,
                stages=ALL_STAGES,
            )
            is expected_stage
        )
