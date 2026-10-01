"""Telemetry to Application Insights through the Azure Monitor OpenTelemetry distro
(AD-17, azure.md rule 16, security.md rule 33).

- Configured once per app, from its settings, with an Entra credential (Application
  Insights has local auth off) and fixed-ratio sampling.
- One trace per correlation id: the trace id *is* the correlation id (both are 128
  bits), so a request and every queue message it causes share one trace in every app,
  and the trace-id-based sampler keeps or drops that trace as a whole.
- Only the `invoicing` loggers are exported, so the log_event allow-list stays the only
  way fields reach telemetry. HTTP-client and web-framework instrumentations, which
  record URLs and headers, stay off.
"""

import functools
import logging
import secrets
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from azure.identity import ManagedIdentityCredential
from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace.sampling import Sampler
from opentelemetry.trace import (
    NonRecordingSpan,
    Span,
    SpanContext,
    SpanKind,
    TraceFlags,
)

from invoicing.adapters.logging import bind_correlation_id, log_event, safe_fields

# Logs from this logger and its children are exported, and nothing else.
TELEMETRY_LOGGER = "invoicing"
TRACER_NAME = "invoicing"
CORRELATION_ATTRIBUTE = "correlation_id"

# Every instrumentation the distro turns on by default, except the Azure SDK's (its
# dependency spans carry no headers or bodies). The others record full URLs and
# headers of requests the apps don't make through them anyway.
DISABLED_INSTRUMENTATIONS = (
    "django",
    "fastapi",
    "flask",
    "httpx",
    "httpx2",
    "psycopg2",
    "requests",
    "urllib",
    "urllib3",
)

_logger = logging.getLogger("invoicing.telemetry")

# The Azure SDK logs every request and response line of its HTTP pipeline at INFO
# (headers redacted). The Functions host forwards them to Application Insights, where
# they are noise against the daily cap (Dev walkthrough follow-up 5).
SDK_HTTP_LOGGER = "azure.core.pipeline.policies.http_logging_policy"


def quiet_sdk_http_logging() -> None:
    """Keep only the Azure SDK's HTTP warnings and errors, whether or not telemetry
    is on (the host forwards worker logs either way)."""
    logging.getLogger(SDK_HTTP_LOGGER).setLevel(logging.WARNING)


@dataclass(frozen=True)
class TelemetryConfig:
    """What configure_telemetry needs, taken from one app's settings."""

    service_name: str
    # None when the app has no Application Insights (local runs): telemetry stays off.
    connection_string: str | None
    # The user-assigned identity that holds Monitoring Metrics Publisher (AD-17).
    client_id: UUID
    # Fraction of traces kept, in (0, 1); below 1 means sampling is on (AD-17).
    sampling_ratio: float


type Configure = Callable[..., None]
type CredentialFactory = Callable[[str], Any]

_configured = False
# The ratio configure_telemetry set; 1.0 (keep everything) until then, when nothing is
# exported anyway.
_sampling_ratio = 1.0


def _azure_monitor() -> Configure:
    # Imported on first use: the distro is large and only needed when telemetry is on.
    from azure.monitor.opentelemetry import configure_azure_monitor

    return configure_azure_monitor


def _managed_identity(client_id: str) -> ManagedIdentityCredential:
    return ManagedIdentityCredential(client_id=client_id)


def azure_monitor_options(
    config: TelemetryConfig, credential: object
) -> dict[str, Any]:
    """The keyword arguments passed to `configure_azure_monitor`."""
    return {
        "connection_string": config.connection_string,
        "credential": credential,
        "sampling_ratio": config.sampling_ratio,
        "logger_name": TELEMETRY_LOGGER,
        # The app's name becomes cloud_RoleName in Application Insights.
        "resource": Resource.create({"service.name": config.service_name}),
        "instrumentation_options": {
            name: {"enabled": False} for name in DISABLED_INSTRUMENTATIONS
        },
        # Logs follow their trace's sampling decision, so a kept trace is complete and
        # a dropped one costs nothing against the daily cap (AD-17).
        "enable_trace_based_sampling_for_logs": True,
        # Not needed for the PoC, and each adds ingestion.
        "enable_live_metrics": False,
        "enable_performance_counters": False,
    }


def configure_telemetry(
    config: TelemetryConfig,
    *,
    configure: Configure | None = None,
    credential_factory: CredentialFactory | None = None,
) -> bool:
    """Start exporting traces, logs and metrics, once per process. Returns whether
    telemetry is on. With no connection string the app still starts, with one warning
    that never includes a setting's value."""
    global _configured, _sampling_ratio
    if _configured:
        return True
    if not config.connection_string:
        log_event(
            _logger,
            "telemetry.disabled",
            level=logging.WARNING,
            app=config.service_name,
            code="NO_CONNECTION_STRING",
        )
        return False
    if not 0 < config.sampling_ratio < 1:
        raise ValueError("sampling_ratio must be between 0 and 1 (exclusive)")
    try:
        credential = (credential_factory or _managed_identity)(str(config.client_id))
        (configure or _azure_monitor())(**azure_monitor_options(config, credential))
    # Telemetry must never stop the app; the exception text may hold settings values.
    except Exception:  # noqa: BLE001
        log_event(
            _logger,
            "telemetry.failed",
            level=logging.ERROR,
            app=config.service_name,
            code="CONFIGURE_FAILED",
        )
        return False
    _configured = True
    _sampling_ratio = config.sampling_ratio
    # The logger inherits the host's WARNING; INFO events must export too. It stops
    # propagating so the Functions host does not export the same records a second time.
    telemetry_logger = logging.getLogger(TELEMETRY_LOGGER)
    telemetry_logger.setLevel(logging.INFO)
    telemetry_logger.propagate = False
    log_event(_logger, "telemetry.configured", app=config.service_name)
    return True


def reset_for_tests() -> None:
    """Forget that telemetry was configured (tests only; the host never calls it)."""
    global _configured, _sampling_ratio
    _configured = False
    _sampling_ratio = 1.0
    telemetry_logger = logging.getLogger(TELEMETRY_LOGGER)
    telemetry_logger.setLevel(logging.NOTSET)
    telemetry_logger.propagate = True


@functools.cache
def _ratio_sampler(sampling_ratio: float) -> Sampler:
    # Imported on first use, like the distro. The same trace-id-ratio sampler the
    # distro installs, so the parent's flag agrees with what the exporter keeps.
    from azure.monitor.opentelemetry.exporter import ApplicationInsightsSampler

    return ApplicationInsightsSampler(sampling_ratio=sampling_ratio)


def is_sampled(correlation_id: UUID, sampling_ratio: float) -> bool:
    """Whether `correlation_id`'s trace is kept at `sampling_ratio`: a trace-id ratio
    decision on the trace id derived from it, so every app gives the same answer.

    It hashes the whole trace id (Application Insights' algorithm). OpenTelemetry's
    TraceIdRatioBased reads only the low 64 bits, which in a UUID start with the fixed
    variant bits 10, so it would keep all or none of the traces at most ratios."""
    decision = _ratio_sampler(sampling_ratio).should_sample(
        None, correlation_id.int, "correlation"
    )
    return decision.decision.is_sampled()


def correlation_context(
    correlation_id: UUID, *, sampling_ratio: float | None = None
) -> Context | None:
    """A context whose trace id is `correlation_id`, or None to use the current one
    (already in that trace, or a nil id that can't be a trace id).

    The context holds a synthetic remote parent that stands for "earlier in this
    correlation id's trace". Its span id is random and no span with that id is ever
    exported, so in Application Insights each root span shows an orphan parent id; that
    is expected. Its sampled flag is the trace-id ratio decision for `sampling_ratio`
    (default: the configured ratio), so a parent-based sampler keeps or drops the whole
    trace consistently instead of keeping everything."""
    trace_id = correlation_id.int
    current = trace.get_current_span().get_span_context()
    if trace_id == 0 or (current.is_valid and current.trace_id == trace_id):
        return None
    ratio = _sampling_ratio if sampling_ratio is None else sampling_ratio
    flags = (
        TraceFlags.SAMPLED if is_sampled(correlation_id, ratio) else TraceFlags.DEFAULT
    )
    parent = SpanContext(
        trace_id=trace_id,
        span_id=secrets.randbits(64) or 1,
        is_remote=True,
        trace_flags=TraceFlags(flags),
    )
    return trace.set_span_in_context(NonRecordingSpan(parent))


@contextmanager
def correlation_span(
    name: str,
    correlation_id: UUID,
    *,
    kind: SpanKind = SpanKind.INTERNAL,
    **attributes: object,
) -> Iterator[Span]:
    """Run a block as a span in `correlation_id`'s trace, with `correlation_id` on the
    span and on every log_event inside it. Other attributes pass the log allow-list."""
    tracer = trace.get_tracer(TRACER_NAME)
    span_attributes = {
        **safe_fields(attributes),
        CORRELATION_ATTRIBUTE: str(correlation_id),
    }
    with (
        bind_correlation_id(correlation_id),
        tracer.start_as_current_span(
            name,
            context=correlation_context(correlation_id),
            kind=kind,
            attributes=span_attributes,
            # An exception's message and stack trace may hold values (security.md
            # rule 31); the span records only that it failed.
            record_exception=False,
        ) as span,
    ):
        yield span
