"""Supplier link tokens (AD-6): 256 random bits, base64url without padding, carried in
the URL fragment and sent as `X-Upload-Token`. Only `SHA-256(token)` is ever stored.

Never log, raise or return a token or its hash in an error (AD-14, security.md rule 31).
"""

import base64
import hashlib
import re

# 32 bytes encode to 43 base64url characters when unpadded.
TOKEN_BYTES = 32
TOKEN_LENGTH = 43
_TOKEN_TEXT = re.compile(r"[A-Za-z0-9_-]{43}")


def parse_token(text: str | None) -> str | None:
    """The token in `text` when it is exactly 256 bits in canonical base64url, else None."""
    if text is None or _TOKEN_TEXT.fullmatch(text) is None:
        return None
    # 43 base64url characters always decode once padded; the pattern checked that.
    raw = base64.urlsafe_b64decode(text + "=")
    # The last character carries 2 spare bits: only one spelling of each token is valid.
    if len(raw) != TOKEN_BYTES or base64.urlsafe_b64encode(raw)[:-1] != text.encode():
        return None
    return text


def token_hash(token: str) -> str:
    """The registry key of `token`: SHA-256 of its base64url text (ASCII), lowercase hex."""
    return hashlib.sha256(token.encode("ascii")).hexdigest()
