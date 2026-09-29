"""Story 1.7: link tokens (AD-6), matrix row "Missing/malformed token"."""

import base64
import hashlib

from invoicing.domain.links import TOKEN_LENGTH, parse_token, token_hash

# Synthetic: 32 fixed bytes, never a real link.
TOKEN = base64.urlsafe_b64encode(bytes(range(32))).rstrip(b"=").decode()


def test_story_1_7_token_parse_and_hash() -> None:
    """Covers: a 256-bit base64url token is accepted (dashes and underscores too); malformed
    tokens are refused; the token hash is the SHA-256 hex of the token text."""
    # A 256-bit base64url token is accepted.
    assert len(TOKEN) == TOKEN_LENGTH == 43
    assert parse_token(TOKEN) == TOKEN
    dashes = base64.urlsafe_b64encode(b"\xfb\xff" * 16).rstrip(b"=").decode()
    assert "-" in dashes or "_" in dashes
    assert parse_token(dashes) == dashes

    # Malformed tokens are refused.
    for text in [TOKEN[:-1] + "+"]:
        assert parse_token(text) is None, text

    # The token hash is the SHA-256 hex of the token text.
    expected = hashlib.sha256(TOKEN.encode("ascii")).hexdigest()
    assert token_hash(TOKEN) == expected
    assert len(expected) == 64 and expected == expected.lower()
