"""Story 1.5: the metrics helper, matrix rows "Metric emitted" and "Metric name".
An in-memory metric reader; nothing reaches Azure."""

from typing import Any

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from invoicing.adapters.metrics import OpenTelemetryMetrics
from invoicing.ports.metrics import MetricName


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


def test_story_1_5_poison_message_is_a_counter_with_its_queue(
    recorder: OpenTelemetryMetrics, reader: InMemoryMetricReader
) -> None:
    recorder.emit_metric("poison_message", 1, {"queue": "q-extract"})
    recorder.emit_metric(MetricName.POISON_MESSAGE, 2, {"queue": "q-extract"})
    assert _points(reader)["poison_message"] == [({"queue": "q-extract"}, 3)]
