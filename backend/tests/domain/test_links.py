"""Story 1.7: link tokens (AD-6), matrix row "Missing/malformed token"."""

import base64
import hashlib

import pytest

from invoicing.domain.errors import ErrorCode, LinkNotValidError
from invoicing.domain.links import TOKEN_LENGTH, parse_token, token_hash

# Synthetic: 32 fixed bytes, never a real link.
TOKEN = base64.urlsafe_b64encode(bytes(range(32))).rstrip(b"=").decode()


def test_story_1_7_a_256_bit_base64url_token_is_accepted() -> None:
    assert len(TOKEN) == TOKEN_LENGTH == 43
    assert parse_token(TOKEN) == TOKEN
    dashes = base64.urlsafe_b64encode(b"\xfb\xff" * 16).rstrip(b"=").decode()
    assert "-" in dashes or "_" in dashes
    assert parse_token(dashes) == dashes


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        TOKEN[:-1],  # too short
        TOKEN + "A",  # too long
        TOKEN + "=",  # padded
        TOKEN[:-1] + "+",  # base64, not base64url
        TOKEN[:-1] + "/",
        " " + TOKEN[1:],
        TOKEN[:-1] + "\n",
        "é" * 43,
        # The last character carries 2 spare bits: a non-zero one is not canonical.
        TOKEN[:-1] + "B" if TOKEN[-1] == "A" else TOKEN[:-1] + "Z",
    ],
)
def test_story_1_7_malformed_tokens_are_refused(text: str | None) -> None:
    assert parse_token(text) is None


def test_story_1_7_token_hash_is_sha256_hex_of_the_token_text() -> None:
    expected = hashlib.sha256(TOKEN.encode("ascii")).hexdigest()
    assert token_hash(TOKEN) == expected
    assert len(expected) == 64 and expected == expected.lower()


def test_story_1_7_link_not_valid_is_one_plain_message_for_every_case() -> None:
    error = LinkNotValidError()
    assert error.code is ErrorCode.LINK_NOT_VALID
    assert (
        error.message
        == "This link isn't working. Please contact your buyer at Babaloo."
    )
