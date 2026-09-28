"""Story 1.3: UUIDv7 ids (spine Consistency Conventions: Ids)."""

from uuid import UUID

import pytest

from invoicing.domain.ids import new_uuid7, parse_uuid


def test_story_1_3_new_ids_are_rfc_9562_version_7() -> None:
    value = new_uuid7()
    assert value.version == 7
    assert value.variant == "specified in RFC 4122"


def test_story_1_3_ids_carry_their_millisecond_timestamp_and_sort_by_it() -> None:
    early, late = (
        new_uuid7(unix_ms=1_790_000_000_000),
        new_uuid7(unix_ms=1_790_000_000_001),
    )
    assert early.int >> 80 == 1_790_000_000_000
    assert early < late


def test_story_1_3_ids_in_the_same_millisecond_differ() -> None:
    assert len({new_uuid7(unix_ms=5) for _ in range(100)}) == 100


@pytest.mark.parametrize("unix_ms", [-1, 1 << 48])
def test_story_1_3_timestamp_outside_48_bits_is_refused(unix_ms: int) -> None:
    with pytest.raises(ValueError, match="48 bits"):
        new_uuid7(unix_ms=unix_ms)


def test_story_1_3_parse_accepts_only_canonical_uuids() -> None:
    text = "0192F0C1-7A2B-7C3D-8E4F-0123456789AB"
    assert parse_uuid(text) == UUID(text)
    assert parse_uuid(f"  {text}  ") == UUID(text)
    for bad in (
        None,
        "",
        "not-a-uuid",
        "0192f0c17a2b7c3d8e4f0123456789ab",
        "{0192f0c1-7a2b-7c3d-8e4f-0123456789ab}",
    ):
        assert parse_uuid(bad) is None
