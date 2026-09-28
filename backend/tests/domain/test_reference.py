"""Story 1.8: the supplier reference (EXPERIENCE.md "Supplier reference")."""

import re
from uuid import UUID

import pytest

from invoicing.domain.ids import new_uuid7
from invoicing.domain.reference import ALPHABET, supplier_reference

CROCKFORD = re.compile(r"R-[0-9A-HJKMNP-TV-Z]{8}")


def test_story_1_8_reference_is_r_dash_and_8_crockford_characters() -> None:
    for _ in range(200):
        assert CROCKFORD.fullmatch(supplier_reference(new_uuid7()))
    assert set(ALPHABET).isdisjoint("ILOU")
    assert len(set(ALPHABET)) == 32


def test_story_1_8_reference_comes_from_the_random_part_only() -> None:
    # Same random bits, different timestamps: the same reference.
    early = new_uuid7(unix_ms=1)
    rand = early.int & ((1 << 74) - 1)
    late = UUID(int=(early.int & ~(((1 << 48) - 1) << 80)) | (2**47 << 80))
    assert late.version == 7 and late.int & ((1 << 74) - 1) == rand
    assert supplier_reference(early) == supplier_reference(late)


def test_story_1_8_reference_is_the_low_40_bits_of_rand_b_in_order() -> None:
    # The version (7) and variant bits set, and rand_b's low 40 bits spelling 0..7
    # then 8..F in 5-bit groups: 7Q4KXM2D is the EXPERIENCE.md example.
    groups = [ALPHABET.index(c) for c in "7Q4KXM2D"]
    low40 = 0
    for group in groups:
        low40 = (low40 << 5) | group
    invoice_id = UUID(int=(0x7 << 76) | (0b10 << 62) | low40)
    assert supplier_reference(invoice_id) == "R-7Q4KXM2D"


def test_story_1_8_the_same_invoice_always_gives_the_same_reference() -> None:
    invoice_id = new_uuid7()
    assert supplier_reference(invoice_id) == supplier_reference(UUID(str(invoice_id)))


def test_story_1_8_a_non_v7_id_has_no_reference() -> None:
    with pytest.raises(ValueError, match="UUIDv7"):
        supplier_reference(UUID("12345678-1234-4234-8234-123456789abc"))
