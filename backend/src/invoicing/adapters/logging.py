"""Safe structured logging: ids, codes and timings only (spine Consistency
Conventions: Logging; security.md rule 31).

Every field goes through an allow-list, so a token, header or field value passed by
mistake is dropped before it reaches Application Insights.
"""

import logging
from collections.abc import Mapping
from enum import Enum
from uuid import UUID

# Keys that hold ids, codes or timings. Nothing else is ever emitted.
ALLOWED_KEYS = frozenset(
    {
        "app",
        "attempt",
        "code",
        "correlation_id",
        "count",
        "duration_ms",
        "field_id",
        "from_status",
        "http_status",
        "invoice_id",
        "queue",
        "reason",
        "routing_id",
        "run_id",
        "stage",
        "status",
        "to_status",
        "version",
    }
)

# Ids and codes are short; anything longer is not what an allowed key should carry.
MAX_VALUE_LENGTH = 64

type LogValue = str | int | float | bool


def safe_fields(fields: Mapping[str, object]) -> dict[str, LogValue]:
    """Keep only allow-listed keys with short scalar values; drop everything else."""
    kept: dict[str, LogValue] = {}
    for key, value in fields.items():
        if key not in ALLOWED_KEYS:
            continue
        if isinstance(value, Enum):
            value = value.value
        if isinstance(value, UUID):
            value = str(value)
        # Printable only: a newline or control character could forge log lines.
        short_text = (
            isinstance(value, str)
            and len(value) <= MAX_VALUE_LENGTH
            and value.isprintable()
        )
        if isinstance(value, bool | int | float | str) and (
            short_text or not isinstance(value, str)
        ):
            kept[key] = value
    return kept


def log_event(
    logger: logging.Logger, event: str, *, level: int = logging.INFO, **fields: object
) -> None:
    """Log `event` (a fixed name such as `http.unhandled_error`) with its safe fields."""
    kept = safe_fields(fields)
    dropped = len(fields) - len(kept)
    if dropped:
        kept["dropped_fields"] = dropped
    text = " ".join(f"{key}={value}" for key, value in sorted(kept.items()))
    logger.log(level, "%s %s", event, text, extra={"custom_dimensions": kept})
