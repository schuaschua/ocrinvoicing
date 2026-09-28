"""UUIDv7 ids for every entity (spine Consistency Conventions: Ids).

Python 3.13 has no `uuid.uuid7`, so this builds one per RFC 9562 from the standard
library only.
"""

import re
import secrets
import time
from uuid import UUID

_MAX_UNIX_MS = (1 << 48) - 1
_CANONICAL = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def new_uuid7(unix_ms: int | None = None) -> UUID:
    """Return a new UUIDv7: 48-bit Unix time in ms, then 74 random bits."""
    ms = time.time_ns() // 1_000_000 if unix_ms is None else unix_ms
    if not 0 <= ms <= _MAX_UNIX_MS:
        raise ValueError("unix_ms must fit in 48 bits")
    random_bits = int.from_bytes(secrets.token_bytes(10))
    rand_a = (random_bits >> 62) & 0xFFF
    rand_b = random_bits & ((1 << 62) - 1)
    value = (ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return UUID(int=value)


def parse_uuid(text: str | None) -> UUID | None:
    """Return the UUID in `text` when it is in canonical 8-4-4-4-12 form, else None."""
    if text is None:
        return None
    candidate = text.strip().lower()
    if _CANONICAL.fullmatch(candidate) is None:
        return None
    return UUID(candidate)
