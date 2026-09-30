"""Safe structured logging: ids, codes and timings only (spine Consistency
Conventions: Logging; security.md rule 31).

Every field goes through an allow-list, so a token, header or field value passed by
mistake is dropped before it reaches Application Insights. The kept fields are set on
the log record as plain attributes, which the OpenTelemetry handler (Story 1.5,
adapters/telemetry.py) exports as custom dimensions; nothing else on a record is ours.
"""

import logging
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from enum import Enum
from uuid import UUID

from opentelemetry import context, trace

# Keys that hold ids, codes or timings. Nothing else is ever emitted.
ALLOWED_KEYS = frozenset(
    {
        # The accounts system's reference for a posted invoice (Story 3.2): an id.
        "accounts_ref",
        "app",
        "attempt",
        "blob_written",
        "code",
        "content_type",
        "correlation_id",
        "count",
        # Sweeper counts (Story 2.2).
        "deleted",
        # A goods-in scan's delivery (Story 4.1): a purchasing record id.
        "delivery_id",
        # passed | overridden | skipped: the page's photo check (Story 1.9), a code.
        "device_check",
        "duration_ms",
        "failures",
        "field_id",
        "from_status",
        "http_status",
        "invoice_id",
        "orphans",
        # DI pages this month as a percentage of the cap (Story 2.3, ar-03): a number.
        "pages_used_pct",
        "queue",
        "reason",
        "requeued",
        "routing_id",
        "run_id",
        "size_bytes",
        # link | goods_in: who wrote an upload (AD-5), a code.
        "source",
        "stage",
        "status",
        "to_status",
        "version",
    }
)

# Ids and codes are short; anything longer is not what an allowed key should carry.
MAX_VALUE_LENGTH = 64

type LogValue = str | int | float | bool

# Set on a record when fields were dropped, so a leak attempt is visible.
DROPPED_FIELDS_KEY = "dropped_fields"

# The correlation id of the request or message being handled (Story 1.5): every
# log_event inside `bind_correlation_id` carries it, so one id is one trace (AD-17).
_correlation_id: ContextVar[UUID | None] = ContextVar(
    "invoicing_correlation_id", default=None
)


@contextmanager
def bind_correlation_id(correlation_id: UUID) -> Iterator[None]:
    """Within this block, log_event adds `correlation_id` when the caller omits it."""
    token = _correlation_id.set(correlation_id)
    try:
        yield
    finally:
        _correlation_id.reset(token)


def safe_fields(
    fields: Mapping[str, object], *, allowed: frozenset[str] = ALLOWED_KEYS
) -> dict[str, LogValue]:
    """Keep only `allowed` keys with short scalar values; drop everything else."""
    kept: dict[str, LogValue] = {}
    for key, value in fields.items():
        if key not in allowed:
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
        kept[DROPPED_FIELDS_KEY] = dropped
    bound = _correlation_id.get()
    # Also when the caller's own value was dropped as unsafe.
    if bound is not None and "correlation_id" not in kept:
        kept["correlation_id"] = str(bound)
    text = " ".join(f"{key}={value}" for key, value in sorted(kept.items()))
    # Flat attributes, not one dict: the OpenTelemetry handler exports each record
    # attribute as a custom dimension. None of the allowed keys is a LogRecord field.
    logger.log(level, "%s %s", event, text, extra=kept)


def log_unsampled_event(
    logger: logging.Logger, event: str, *, level: int = logging.INFO, **fields: object
) -> None:
    """`log_event` outside any trace, so trace-based log sampling always keeps it."""
    # AD-17: the log alerts read these events, and logs follow their trace's sampling
    # decision (0.5), so they are logged with no active span and never sampled out.
    token = context.attach(trace.set_span_in_context(trace.INVALID_SPAN))
    try:
        log_event(logger, event, level=level, **fields)
    finally:
        context.detach(token)


def event_fields(record: logging.LogRecord) -> dict[str, LogValue]:
    """The safe fields log_event set on `record`."""
    names = ALLOWED_KEYS | {DROPPED_FIELDS_KEY}
    return {key: value for key, value in vars(record).items() if key in names}
