"""Story 1.5: the metrics helper, matrix rows "Metric emitted" and "Metric name".
An in-memory metric reader; nothing reaches Azure."""

import logging
from typing import Any

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    InMemoryMetricReader,
    MetricExporter,
    MetricExportResult,
    MetricsData,
    PeriodicExportingMetricReader,
)

from invoicing.adapters import metrics as metrics_adapter
from invoicing.adapters.metrics import OpenTelemetryMetrics
from invoicing.ports.metrics import MetricName


class RecordingExporter(MetricExporter):
    """Keeps the names of the metrics each export sends."""

    def __init__(self) -> None:
        super().__init__()
        self.sent: list[str] = []

    def export(
        self, metrics_data: MetricsData, timeout_millis: float = 10_000, **kwargs: Any
    ) -> MetricExportResult:
        self.sent += [
            metric.name
            for resource in metrics_data.resource_metrics
            for scope in resource.scope_metrics
            for metric in scope.metrics
        ]
        return MetricExportResult.SUCCESS

    def force_flush(self, timeout_millis: float = 10_000) -> bool:
        return True

    def shutdown(self, timeout_millis: float = 30_000, **kwargs: Any) -> None:
        return None


@pytest.fixture
def reader() -> InMemoryMetricReader:
    return InMemoryMetricReader()


@pytest.fixture
def recorder(reader: InMemoryMetricReader) -> OpenTelemetryMetrics:
    provider = MeterProvider(metric_readers=[reader])
    return OpenTelemetryMetrics(provider.get_meter("test"))


def _points(
    reader: InMemoryMetricReader,
) -> dict[str, list[tuple[dict[str, Any], float]]]:
    """Metric name -> [(attributes, value)] from one collection."""
    found: dict[str, list[tuple[dict[str, Any], float]]] = {}
    data = reader.get_metrics_data()
    if data is None:
        return found
    for resource in data.resource_metrics:
        for scope in resource.scope_metrics:
            for metric in scope.metrics:
                found[metric.name] = [
                    (dict(point.attributes or {}), point.value)  # type: ignore[union-attr]  # number points
                    for point in metric.data.data_points
                ]
    return found


def test_story_1_5_poison_message_counter_and_each_metric_exported_at_once(
    recorder: OpenTelemetryMetrics,
    reader: InMemoryMetricReader,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    recorder.emit_metric("poison_message", 1, {"queue": "q-extract"})
    recorder.emit_metric(MetricName.POISON_MESSAGE, 2, {"queue": "q-extract"})
    assert _points(reader)["poison_message"] == [({"queue": "q-extract"}, 3)]

    # Story 1.5/2.2/2.3 fix: each metric is exported when recorded, before a
    # short-lived Flex instance stops (a 60 s periodic export would come too late).
    exporter = RecordingExporter()
    live = MeterProvider(
        metric_readers=[
            PeriodicExportingMetricReader(exporter, export_interval_millis=60_000)
        ]
    )
    monkeypatch.setattr(metrics_adapter.metrics, "get_meter_provider", lambda: live)
    OpenTelemetryMetrics(live.get_meter("test")).emit_metric("stuck_invoices", 3)
    assert exporter.sent == ["stuck_invoices"]
    live.shutdown()

    # A failed export (False) or a raising flush is logged by the metric's name only,
    # and never fails the stage that recorded it.
    def broken() -> bool:
        raise OSError("export failed")

    with caplog.at_level(logging.WARNING, logger="invoicing.metrics"):
        for flush in (lambda: False, broken):
            OpenTelemetryMetrics(live.get_meter("test"), flush=flush).emit_metric(
                "di_pages_used_pct", 10
            )
    failed = [
        r.getMessage() for r in caplog.records if "flush_failed" in r.getMessage()
    ]
    assert len(failed) == 2
    assert all("di_pages_used_pct" in message for message in failed)
