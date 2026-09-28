"""Story 2.2: the pure recovery rules. The AD-3 claim and lease reclaim, the AD-2 poison
guard, and the AD-2 sweeper map with its ages (AD-6 upload keys)."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from invoicing.domain.reasons import ReasonCode
from invoicing.domain.status import (
    CLAIM_STATUS,
    INPUT_STATUS,
    InvoiceStatus,
    Stage,
    lease_expired,
    poison_route_from,
)
from invoicing.domain.sweep import (
    CONSUMED_QUEUES,
    STALE_AFTER,
    SWEEP_LIMIT,
    UPLOAD_KEY_TTL,
    sweep_stage,
    sweep_statuses,
    upload_key_expired,
)
from invoicing.domain.transitions import (
    CLAIM_LEASE,
    claim_from,
    plan_claim,
    route_to_admin,
)

S = InvoiceStatus
INVOICE = UUID("0192f0c1-7a2b-7c3d-8e4f-0123456789ab")
NOW = datetime(2026, 9, 29, 2, 0, tzinfo=UTC)
PAST = NOW - timedelta(seconds=1)
FUTURE = NOW + timedelta(minutes=5)


# --- AD-3 claim and reclaim ---------------------------------------------------------------


def test_story_2_2_each_side_effect_stage_claims_its_input_with_a_ten_minute_lease() -> (
    None
):
    assert CLAIM_LEASE == timedelta(minutes=10)
    assert {
        stage: (INPUT_STATUS[stage], CLAIM_STATUS[stage]) for stage in CLAIM_STATUS
    } == {
        Stage.EXTRACT: (S.AWAITING_EXTRACTION, S.EXTRACTING),
        Stage.VALIDATE: (S.AWAITING_VALIDATION, S.VALIDATING),
        Stage.POST: (S.READY_TO_POST, S.POSTING),
    }
    claim = plan_claim(INVOICE, Stage.EXTRACT, "pipeline:extract")
    assert (claim.input_status, claim.claim_status, claim.lease) == (
        S.AWAITING_EXTRACTION,
        S.EXTRACTING,
        CLAIM_LEASE,
    )


def test_story_2_2_quality_makes_no_claim() -> None:
    with pytest.raises(ValueError, match="no claim"):
        plan_claim(INVOICE, Stage.QUALITY, "pipeline:quality")


@pytest.mark.parametrize("stage", [Stage.EXTRACT, Stage.VALIDATE, Stage.POST])
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


def test_story_2_2_the_post_claim_waits_for_its_next_attempt() -> None:
    claim = plan_claim(INVOICE, Stage.POST, "t")
    for next_attempt, expected in [
        (None, S.READY_TO_POST),
        (PAST, S.READY_TO_POST),
        (FUTURE, None),
    ]:
        assert (
            claim_from(
                claim,
                S.READY_TO_POST,
                claimed_until=None,
                next_attempt_at=next_attempt,
                now=NOW,
            )
            is expected
        )
    # Other stages ignore it.
    extract = plan_claim(INVOICE, Stage.EXTRACT, "t")
    assert (
        claim_from(
            extract,
            S.AWAITING_EXTRACTION,
            claimed_until=None,
            next_attempt_at=FUTURE,
            now=NOW,
        )
        is S.AWAITING_EXTRACTION
    )


def test_story_2_2_a_missing_lease_counts_as_expired() -> None:
    assert lease_expired(None, NOW)
    assert lease_expired(NOW, NOW)
    assert not lease_expired(FUTURE, NOW)


# --- AD-2 poison guard ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("stage", "status", "lease", "expected"),
    [
        # q-quality: `received` or no row (route_to_admin creates it).
        (Stage.QUALITY, S.RECEIVED, None, S.RECEIVED),
        (Stage.QUALITY, None, None, S.RECEIVED),
        (Stage.QUALITY, S.AWAITING_EXTRACTION, None, None),
        (Stage.QUALITY, S.IN_ADMIN_QUEUE, None, None),
        # q-extract: its input, or its claim with an expired lease.
        (Stage.EXTRACT, S.AWAITING_EXTRACTION, None, S.AWAITING_EXTRACTION),
        (Stage.EXTRACT, S.EXTRACTING, PAST, S.EXTRACTING),
        (Stage.EXTRACT, S.EXTRACTING, FUTURE, None),
        (Stage.EXTRACT, S.AWAITING_VALIDATION, None, None),
        (Stage.EXTRACT, None, None, None),
        (Stage.VALIDATE, S.AWAITING_VALIDATION, None, S.AWAITING_VALIDATION),
        (Stage.VALIDATE, S.VALIDATING, PAST, S.VALIDATING),
        (Stage.VALIDATE, S.VALIDATING, FUTURE, None),
        (Stage.VALIDATE, S.READY_TO_POST, None, None),
        (Stage.POST, S.READY_TO_POST, None, S.READY_TO_POST),
        (Stage.POST, S.POSTING, PAST, S.POSTING),
        (Stage.POST, S.POSTING, FUTURE, None),
        (Stage.POST, S.POSTED, None, None),
        (Stage.POST, S.REJECTED, None, None),
    ],
)
def test_story_2_2_poison_routes_only_from_the_queues_input_or_an_expired_claim(
    stage: Stage, status: S | None, lease: datetime | None, expected: S | None
) -> None:
    assert poison_route_from(stage, status, lease, NOW) is expected


@pytest.mark.parametrize(
    ("next_attempt", "expected"),
    [(None, S.READY_TO_POST), (PAST, S.READY_TO_POST), (FUTURE, None)],
)
def test_story_2_2_a_post_poison_never_routes_an_invoice_waiting_on_its_backoff(
    next_attempt: datetime | None, expected: S | None
) -> None:
    # AD-3: a scheduled retry owns `ready_to_post` until `next_attempt_at`.
    assert (
        poison_route_from(Stage.POST, S.READY_TO_POST, None, NOW, next_attempt)
        is expected
    )
    # Other stages have no backoff.
    assert (
        poison_route_from(Stage.EXTRACT, S.AWAITING_EXTRACTION, None, NOW, FUTURE)
        is S.AWAITING_EXTRACTION
    )


def test_story_2_2_a_routing_from_a_claim_it_does_not_hold_needs_an_expired_lease() -> (
    None
):
    plain = route_to_admin(
        INVOICE, [ReasonCode.PROCESSING_FAILED], S.RECEIVED, actor="t"
    )
    assert plain.transition.require_expired_lease is False
    guarded = route_to_admin(
        INVOICE,
        [ReasonCode.PROCESSING_FAILED],
        S.EXTRACTING,
        actor="t",
        require_expired_lease=True,
    )
    assert guarded.transition.require_expired_lease is True


# --- AD-2 sweeper map -----------------------------------------------------------------------

ALL_STAGES = frozenset(Stage)


@pytest.mark.parametrize(
    ("status", "lease", "next_attempt", "expected"),
    [
        (S.RECEIVED, None, None, Stage.QUALITY),
        (S.AWAITING_EXTRACTION, None, None, Stage.EXTRACT),
        (S.EXTRACTING, PAST, None, Stage.EXTRACT),
        (S.EXTRACTING, None, None, Stage.EXTRACT),
        (S.EXTRACTING, FUTURE, None, None),
        (S.AWAITING_VALIDATION, None, None, Stage.VALIDATE),
        (S.VALIDATING, PAST, None, Stage.VALIDATE),
        (S.VALIDATING, FUTURE, None, None),
        (S.READY_TO_POST, None, None, Stage.POST),
        (S.READY_TO_POST, None, PAST, Stage.POST),
        (S.READY_TO_POST, None, FUTURE, None),
        (S.POSTING, PAST, None, Stage.POST),
        (S.POSTING, FUTURE, None, None),
        (S.IN_ADMIN_QUEUE, None, None, None),
        (S.POSTED, None, None, None),
        (S.REJECTED, None, None, None),
    ],
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


def test_story_2_2_today_only_the_quality_queue_has_a_consumer() -> None:
    assert CONSUMED_QUEUES == {Stage.QUALITY}
    assert sweep_statuses() == {S.RECEIVED}
    assert sweep_stage(
        S.RECEIVED, claimed_until=None, next_attempt_at=None, now=NOW
    ) is (Stage.QUALITY)
    # No consumer yet: sweeping there would pile messages up (and keep the alert on).
    for status in [S.AWAITING_EXTRACTION, S.AWAITING_VALIDATION, S.READY_TO_POST]:
        assert (
            sweep_stage(status, claimed_until=None, next_attempt_at=None, now=NOW)
            is None
        )


def test_story_2_2_the_sweeper_never_reads_admin_or_final_statuses() -> None:
    assert sweep_statuses(ALL_STAGES) == set(S) - {
        S.IN_ADMIN_QUEUE,
        S.POSTED,
        S.REJECTED,
    }
    assert sweep_statuses(frozenset({Stage.EXTRACT})) == {
        S.AWAITING_EXTRACTION,
        S.EXTRACTING,
    }


def test_story_2_2_stale_means_an_hour_keys_live_a_day_and_sweeps_are_capped() -> None:
    assert STALE_AFTER == timedelta(hours=1)
    assert UPLOAD_KEY_TTL == timedelta(hours=24)
    assert SWEEP_LIMIT == 500
    assert upload_key_expired(NOW - timedelta(hours=24, seconds=1), NOW)
    assert not upload_key_expired(NOW - timedelta(hours=23), NOW)
