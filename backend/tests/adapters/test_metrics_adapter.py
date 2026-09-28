"""Story 1.5: the metrics helper, matrix rows "Metric emitted" and "Metric name".
An in-memory metric reader; nothing reaches Azure."""

import logging
import threading
import time
from typing import Any

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from invoicing.adapters import metrics as metrics_adapter
from invoicing.adapters.logging import event_fields
from invoicing.adapters.metrics import OpenTelemetryMetrics, emit_metric
from invoicing.ports.metrics import ALLOWED_DIMENSIONS, MetricName, MetricsPort


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


def test_story_1_5_the_adapter_implements_the_port(
    recorder: OpenTelemetryMetrics,
) -> None:
    port: MetricsPort = recorder
    assert callable(port.emit_metric)


def test_story_1_5_poison_message_is_a_counter_with_its_queue(
    recorder: OpenTelemetryMetrics, reader: InMemoryMetricReader
) -> None:
    recorder.emit_metric("poison_message", 1, {"queue": "q-extract"})
    recorder.emit_metric(MetricName.POISON_MESSAGE, 2, {"queue": "q-extract"})
    assert _points(reader)["poison_message"] == [({"queue": "q-extract"}, 3)]


@pytest.mark.parametrize(
    ("name", "value"), [("stuck_invoices", 4), ("di_pages_used_pct", 81.5)]
)
def test_story_1_5_levels_are_gauges_keeping_the_last_value(
    name: str,
    value: float,
    recorder: OpenTelemetryMetrics,
    reader: InMemoryMetricReader,
) -> None:
    recorder.emit_metric(name, 1)
    recorder.emit_metric(name, value)
    assert _points(reader)[name] == [({}, value)]


@pytest.mark.parametrize(
    "dimensions",
    [
        {"queue": "q-extract", "vendor_name": "ACME Pte Ltd"},
        {"queue": "q-extract", "headers": {"Authorization": "Bearer x"}},
        {"queue": "q-extract", "invoice_id": "0192f0c1-7a2b-7c3d-8e4f-0123456789ab"},
    ],
)
def test_story_1_5_unknown_dimension_keys_are_dropped_not_raised(
    dimensions: dict[str, object],
    recorder: OpenTelemetryMetrics,
    reader: InMemoryMetricReader,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="invoicing.metrics"):
        recorder.emit_metric("poison_message", 1, dimensions)
    assert _points(reader)["poison_message"] == [({"queue": "q-extract"}, 1)]
    (record,) = caplog.records
    assert event_fields(record) == {"code": "poison_message", "count": 1}
    assert "ACME" not in caplog.text and "Bearer" not in caplog.text


@pytest.mark.parametrize(
    "queue", [["q-extract"], {"name": "q-extract"}, "x" * 65, "q\nextract", None]
)
def test_story_1_5_non_scalar_or_unsafe_dimension_values_are_dropped(
    queue: object, recorder: OpenTelemetryMetrics, reader: InMemoryMetricReader
) -> None:
    recorder.emit_metric("poison_message", 1, {"queue": queue})
    assert _points(reader)["poison_message"] == [({}, 1)]


@pytest.mark.parametrize(
    "name", ["poison_messages", "invoice_total", "", "POISON_MESSAGE"]
)
def test_story_1_5_a_name_outside_the_allow_list_raises(
    name: str, recorder: OpenTelemetryMetrics, reader: InMemoryMetricReader
) -> None:
    with pytest.raises(ValueError, match="unknown metric name"):
        recorder.emit_metric(name, 1)
    assert _points(reader) == {}


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("poison_message", -1),
        ("di_pages_used_pct", float("nan")),
        ("di_pages_used_pct", float("inf")),
    ],
)
def test_story_1_5_a_bad_value_raises(
    name: str, value: object, recorder: OpenTelemetryMetrics
) -> None:
    with pytest.raises(ValueError, match=name):
        recorder.emit_metric(name, value)  # type: ignore[arg-type]  # the bad values under test


@pytest.mark.parametrize(
    ("name", "value"), [("poison_message", True), ("stuck_invoices", "3")]
)
def test_story_1_5_a_value_that_is_not_a_number_raises(
    name: str, value: object, recorder: OpenTelemetryMetrics
) -> None:
    with pytest.raises(TypeError, match=name):
        recorder.emit_metric(name, value)  # type: ignore[arg-type]  # the bad values under test


def test_story_1_5_only_poison_message_has_a_dimension() -> None:
    assert ALLOWED_DIMENSIONS == {
        MetricName.POISON_MESSAGE: frozenset({"queue"}),
        MetricName.STUCK_INVOICES: frozenset(),
        MetricName.DI_PAGES_USED_PCT: frozenset(),
    }


def test_story_1_5_the_module_helper_uses_one_recorder_on_the_global_meter(
    monkeypatch: pytest.MonkeyPatch, reader: InMemoryMetricReader
) -> None:
    provider = MeterProvider(metric_readers=[reader])
    monkeypatch.setattr(metrics_adapter, "_default", None)
    monkeypatch.setattr(metrics_adapter.metrics, "get_meter", provider.get_meter)
    emit_metric("poison_message", 1, {"queue": "q-post"})
    emit_metric("poison_message", 1, {"queue": "q-post"})
    assert _points(reader)["poison_message"] == [({"queue": "q-post"}, 2)]


# --- Story 1.5 review: value bounds and the shared recorder --------------------------------


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("poison_message", 10**400),
        ("di_pages_used_pct", -0.1),
        ("di_pages_used_pct", 100.5),
    ],
)
def test_story_1_5_out_of_range_values_raise_value_error(
    name: str,
    value: float,
    recorder: OpenTelemetryMetrics,
    reader: InMemoryMetricReader,
) -> None:
    with pytest.raises(ValueError, match=name):
        recorder.emit_metric(name, value)
    assert _points(reader) == {}


@pytest.mark.parametrize("value", [0, 100, 80])
def test_story_1_5_page_percentages_from_0_to_100_are_kept(
    value: float, recorder: OpenTelemetryMetrics, reader: InMemoryMetricReader
) -> None:
    recorder.emit_metric("di_pages_used_pct", value)
    assert _points(reader)["di_pages_used_pct"] == [({}, value)]


def test_story_1_5_threads_share_one_default_recorder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[object] = []
    barrier = threading.Barrier(8)

    class SlowRecorder:
        def __init__(self) -> None:
            created.append(self)
            time.sleep(0.01)

        def emit_metric(self, *args: object) -> None:
            pass

    def emit() -> None:
        barrier.wait()
        emit_metric("stuck_invoices", 1)

    monkeypatch.setattr(metrics_adapter, "_default", None)
    monkeypatch.setattr(metrics_adapter, "OpenTelemetryMetrics", SlowRecorder)
    threads = [threading.Thread(target=emit) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(created) == 1
