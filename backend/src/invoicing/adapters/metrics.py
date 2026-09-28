"""`MetricsPort` over OpenTelemetry metrics, exported to Application Insights by the
Azure Monitor distro (adapters/telemetry.py). Before telemetry is configured, or when it
is off, the global meter records nothing and costs nothing."""

import logging
import math
import threading
from collections.abc import Mapping

from opentelemetry import metrics
from opentelemetry.metrics import Meter

from invoicing.adapters.logging import LogValue, log_event, safe_fields
from invoicing.ports.metrics import ALLOWED_DIMENSIONS, MetricName

METER_NAME = "invoicing"

# poison_message counts events, so it is a counter; the other two are levels.
COUNTERS = frozenset({MetricName.POISON_MESSAGE})

UNITS: Mapping[MetricName, str] = {
    MetricName.POISON_MESSAGE: "{message}",
    MetricName.STUCK_INVOICES: "{invoice}",
    MetricName.DI_PAGES_USED_PCT: "%",
}

_logger = logging.getLogger("invoicing.metrics")


def _metric_name(name: str) -> MetricName:
    try:
        return MetricName(name)
    except ValueError:
        raise ValueError(f"unknown metric name: {name!r}") from None


def _metric_value(metric: MetricName, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{metric.value} needs a number")
    try:
        amount = float(value)
    except OverflowError:
        raise ValueError(f"{metric.value} is too large") from None
    if not math.isfinite(amount):
        raise ValueError(f"{metric.value} needs a finite number")
    if metric in COUNTERS and amount < 0:
        raise ValueError(f"{metric.value} is a counter and cannot go down")
    if metric is MetricName.DI_PAGES_USED_PCT and not 0 <= amount <= 100:
        raise ValueError(f"{metric.value} is a percentage from 0 to 100")
    return value


def safe_dimensions(
    metric: MetricName, dimensions: Mapping[str, object] | None
) -> dict[str, LogValue]:
    """The metric's allow-listed dimensions with short, printable scalar values."""
    if not dimensions:
        return {}
    return safe_fields(dimensions, allowed=ALLOWED_DIMENSIONS[metric])


class OpenTelemetryMetrics:
    """Records the AD-17 custom metrics on one meter."""

    def __init__(self, meter: Meter | None = None) -> None:
        meter = meter or metrics.get_meter(METER_NAME)
        self._counters = {
            name: meter.create_counter(name.value, unit=UNITS[name])
            for name in MetricName
            if name in COUNTERS
        }
        self._gauges = {
            name: meter.create_gauge(name.value, unit=UNITS[name])
            for name in MetricName
            if name not in COUNTERS
        }

    def emit_metric(
        self,
        name: str,
        value: float,
        dimensions: Mapping[str, object] | None = None,
    ) -> None:
        metric = _metric_name(name)
        amount = _metric_value(metric, value)
        kept = safe_dimensions(metric, dimensions)
        dropped = len(dimensions or {}) - len(kept)
        if dropped:
            log_event(
                _logger,
                "metrics.dimensions_dropped",
                level=logging.WARNING,
                code=metric.value,
                count=dropped,
            )
        if metric in self._counters:
            self._counters[metric].add(amount, attributes=kept)
        else:
            self._gauges[metric].set(amount, attributes=kept)


_default: OpenTelemetryMetrics | None = None
_default_lock = threading.Lock()


def emit_metric(
    name: str, value: float, dimensions: Mapping[str, object] | None = None
) -> None:
    """Record one value on the global meter (set by configure_telemetry)."""
    global _default
    recorder = _default
    if recorder is None:
        with _default_lock:
            if _default is None:
                _default = OpenTelemetryMetrics()
            recorder = _default
    recorder.emit_metric(name, value, dimensions)
