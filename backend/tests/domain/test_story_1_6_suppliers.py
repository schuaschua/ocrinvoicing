"""Story 1.6: bank value fingerprints (AD-11) and link tokens (AD-6). Pure domain: no
database, no Azure. The CSV rules are checked through the load script
(tests/tools/test_story_1_6_load_suppliers.py)."""

import hashlib
import hmac

from invoicing.domain.links import (
    TOKEN_LENGTH,
    new_token,
    parse_token,
    token_hash,
    upload_link,
)
from invoicing.domain.suppliers import bank_fingerprint, normalise_bank_value


def test_story_1_6_fingerprints_normalise_and_tokens_are_256_random_bits() -> None:
    # Spaces (any whitespace) and hyphens are stripped, then uppercased (AD-11).
    assert normalise_bank_value(" sg12-3456\t7890 ") == "SG1234567890"
    key = "synthetic-hmac-key"
    expected = hmac.new(key.encode(), b"DBSSSGSG", hashlib.sha256).hexdigest()
    assert bank_fingerprint(key, "dbss-sg sg") == expected
    assert bank_fingerprint(key, "DBSSSGSG") == expected
    assert bank_fingerprint("another-key", "DBSSSGSG") != expected
    assert bank_fingerprint(key, "DBSSSGSX") != expected

    tokens = {new_token() for _ in range(64)}
    assert len(tokens) == 64
    for token in tokens:
        # Canonical base64url of 32 bytes: what Story 1.7 accepts.
        assert len(token) == TOKEN_LENGTH and parse_token(token) == token
        assert len(token_hash(token)) == 64
    token = tokens.pop()
    # The token sits in the fragment, which browsers never send (AD-6).
    assert upload_link("babaloo-sea-lng-func-01.azurewebsites.net", token) == (
        f"https://babaloo-sea-lng-func-01.azurewebsites.net/u#{token}"
    )
