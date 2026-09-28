"""Story 1.5: telemetry start-up and one trace per correlation id, matrix rows
"Telemetry on" and "One trace per correlation id". In-memory exporters only; nothing
reaches Azure."""

import asyncio
import logging
from typing import Any
from uuid import UUID

import azure.functions as func
import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from opentelemetry.trace import SpanKind, StatusCode

from invoicing.adapters.http import CORRELATION_HEADER, http_endpoint, json_response
from invoicing.adapters.logging import event_fields, log_event
from invoicing.adapters.telemetry import (
    DISABLED_INSTRUMENTATIONS,
    TELEMETRY_LOGGER,
    TelemetryConfig,
    configure_telemetry,
    correlation_context,
    correlation_span,
    is_sampled,
    reset_for_tests,
)
from invoicing.domain.ids import new_uuid7

CONNECTION_STRING = (
    "InstrumentationKey=00000000-0000-0000-0000-00000000abcd;"
    "IngestionEndpoint=https://southeastasia-0.in.applicationinsights.azure.com/"
)
CLIENT_ID = UUID("00000000-0000-0000-0000-00000000c1d0")
CALLER_ID = "0192f0c1-7a2b-7c3d-8e4f-0123456789ab"


def _config(**overrides: Any) -> TelemetryConfig:
    values: dict[str, Any] = {
        "service_name": "supplier-api",
        "connection_string": CONNECTION_STRING,
        "client_id": CLIENT_ID,
        "sampling_ratio": 0.5,
    }
    values.update(overrides)
    return TelemetryConfig(**values)


class _FakeAzureMonitor:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


def test_story_1_5_telemetry_is_configured_once_with_entra_and_sampling() -> None:
    fake = _FakeAzureMonitor()
    credentials: list[str] = []

    def credential(client_id: str) -> str:
        credentials.append(client_id)
        return f"credential-for-{client_id}"

    assert configure_telemetry(_config(), configure=fake, credential_factory=credential)
    # A second start-up in the same process configures nothing.
    assert configure_telemetry(_config(), configure=fake, credential_factory=credential)

    (options,) = fake.calls
    assert credentials == [str(CLIENT_ID)]
    assert options["credential"] == f"credential-for-{CLIENT_ID}"
    assert options["connection_string"] == CONNECTION_STRING
    assert options["sampling_ratio"] == 0.5
    assert options["logger_name"] == TELEMETRY_LOGGER == "invoicing"
    assert options["resource"].attributes["service.name"] == "supplier-api"
    assert options["enable_trace_based_sampling_for_logs"] is True
    instrumentations = options["instrumentation_options"]
    assert set(instrumentations) == set(DISABLED_INSTRUMENTATIONS)
    assert "azure_sdk" not in instrumentations
    assert all(option == {"enabled": False} for option in instrumentations.values())


def test_story_1_5_every_distro_instrumentation_but_azure_sdk_is_off() -> None:
    from azure.monitor.opentelemetry._constants import (
        _FULLY_SUPPORTED_INSTRUMENTED_LIBRARIES,
    )

    assert set(DISABLED_INSTRUMENTATIONS) == set(
        _FULLY_SUPPORTED_INSTRUMENTED_LIBRARIES
    ) - {"azure_sdk"}


def test_story_1_5_the_default_credential_is_the_apps_managed_identity() -> None:
    fake = _FakeAzureMonitor()
    configure_telemetry(_config(), configure=fake)
    credential = fake.calls[0]["credential"]
    assert type(credential).__name__ == "ManagedIdentityCredential"


@pytest.mark.parametrize("connection_string", [None, ""])
def test_story_1_5_missing_connection_string_leaves_telemetry_off_with_one_warning(
    connection_string: str | None, caplog: pytest.LogCaptureFixture
) -> None:
    fake = _FakeAzureMonitor()
    with caplog.at_level(logging.INFO, logger="invoicing.telemetry"):
        on = configure_telemetry(
            _config(connection_string=connection_string), configure=fake
        )
    assert on is False and fake.calls == []
    (record,) = caplog.records
    assert record.levelno == logging.WARNING
    assert record.getMessage().startswith("telemetry.disabled ")
    assert event_fields(record) == {
        "app": "supplier-api",
        "code": "NO_CONNECTION_STRING",
    }
    assert str(CLIENT_ID) not in caplog.text


@pytest.mark.parametrize("ratio", [0, 1, 1.5])
def test_story_1_5_sampling_must_be_on(ratio: float) -> None:
    with pytest.raises(ValueError, match="sampling_ratio"):
        configure_telemetry(
            _config(sampling_ratio=ratio), configure=_FakeAzureMonitor()
        )


def test_story_1_5_the_connection_string_is_never_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG):
        configure_telemetry(_config(), configure=_FakeAzureMonitor())
    assert "InstrumentationKey" not in caplog.text


# --- One trace per correlation id ----------------------------------------------------


def test_story_1_5_a_correlation_span_uses_the_id_as_its_trace_id(
    spans: InMemorySpanExporter, caplog: pytest.LogCaptureFixture
) -> None:
    correlation_id = UUID(CALLER_ID)
    logger = logging.getLogger("invoicing.test")
    with (
        caplog.at_level(logging.INFO, logger="invoicing.test"),
        correlation_span(
            "stage.extract", correlation_id, invoice_id=correlation_id, headers="x"
        ),
        # Nested spans stay in the same trace.
        correlation_span("stage.extract.inner", correlation_id),
    ):
        log_event(logger, "stage.done", stage="extract")

    inner, outer = spans.get_finished_spans()
    for span in (inner, outer):
        assert span.context.trace_id == correlation_id.int
        assert span.attributes["correlation_id"] == CALLER_ID
    assert inner.parent.span_id == outer.context.span_id
    # Attributes pass the log allow-list: headers are dropped.
    assert "headers" not in outer.attributes
    assert outer.attributes["invoice_id"] == CALLER_ID
    # A log with no correlation_id of its own still carries the bound one.
    (record,) = caplog.records
    assert event_fields(record) == {"stage": "extract", "correlation_id": CALLER_ID}


def test_story_1_5_two_messages_with_one_correlation_id_share_a_trace(
    spans: InMemorySpanExporter,
) -> None:
    correlation_id = UUID(CALLER_ID)
    with correlation_span("stage.quality", correlation_id):
        pass
    with correlation_span("stage.extract", correlation_id):
        pass
    first, second = spans.get_finished_spans()
    assert first.context.trace_id == second.context.trace_id == correlation_id.int


def test_story_1_5_a_nil_correlation_id_uses_the_current_context() -> None:
    assert correlation_context(UUID(int=0)) is None


def test_story_1_5_span_failures_record_no_exception_text(
    spans: InMemorySpanExporter,
) -> None:
    with (
        pytest.raises(RuntimeError),
        correlation_span("stage.post", UUID(CALLER_ID)),
    ):
        raise RuntimeError("password=hunter2")
    (span,) = spans.get_finished_spans()
    assert span.status.status_code == StatusCode.ERROR
    assert span.events == ()


def _request(headers: dict[str, str]) -> func.HttpRequest:
    return func.HttpRequest(method="GET", url="/api/thing", headers=headers, body=b"")


def test_story_1_5_an_http_request_is_one_server_span_carrying_the_header_id(
    spans: InMemorySpanExporter, caplog: pytest.LogCaptureFixture
) -> None:
    logger = logging.getLogger("invoicing.test")

    async def handler(req: func.HttpRequest, correlation_id: UUID) -> func.HttpResponse:
        log_event(logger, "thing.read", code="OK")
        return json_response({}, status=200, correlation_id=correlation_id)

    with caplog.at_level(logging.INFO, logger="invoicing.test"):
        response = asyncio.run(
            http_endpoint(handler)(_request({CORRELATION_HEADER: CALLER_ID}))
        )
    assert response.status_code == 200
    (span,) = spans.get_finished_spans()
    assert span.name == "handler" and span.kind == SpanKind.SERVER
    assert span.attributes["correlation_id"] == CALLER_ID
    assert span.attributes["http.response.status_code"] == 200
    assert span.context.trace_id == UUID(CALLER_ID).int
    (record,) = caplog.records
    assert event_fields(record)["correlation_id"] == CALLER_ID


def test_story_1_5_a_500_marks_the_request_span_failed(
    spans: InMemorySpanExporter,
) -> None:
    async def handler(req: func.HttpRequest, correlation_id: UUID) -> func.HttpResponse:
        raise RuntimeError("boom")

    response = asyncio.run(http_endpoint(handler)(_request({})))
    assert response.status_code == 500
    (span,) = spans.get_finished_spans()
    assert span.status.status_code == StatusCode.ERROR
    assert span.attributes["correlation_id"] == response.headers[CORRELATION_HEADER]


# --- Review fixes: sampling decision, failure handling, logger set-up ---------------


def test_story_1_5_the_synthetic_parent_carries_a_consistent_sampling_decision() -> (
    None
):
    ratio = 0.5
    provider = TracerProvider(sampler=ParentBased(TraceIdRatioBased(ratio)))
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test")
    ids = [new_uuid7() for _ in range(200)]

    def recorded(correlation_id: UUID) -> bool:
        context = correlation_context(correlation_id, sampling_ratio=ratio)
        with tracer.start_as_current_span("x", context=context) as span:
            return span.is_recording()

    decisions = [recorded(cid) for cid in ids]
    assert any(decisions) and not all(decisions)
    # Deterministic per id: the same answer every time, in every app.
    assert [recorded(cid) for cid in ids] == decisions
    assert decisions == [is_sampled(cid, ratio) for cid in ids]


def test_story_1_5_the_configured_ratio_drives_the_parent_flag() -> None:
    ids = [new_uuid7() for _ in range(100)]
    configure_telemetry(_config(sampling_ratio=0.1), configure=_FakeAzureMonitor())

    def flag(cid: UUID) -> bool:
        context = correlation_context(cid)
        assert context is not None
        return trace.get_current_span(context).get_span_context().trace_flags.sampled

    assert [flag(cid) for cid in ids] == [is_sampled(cid, 0.1) for cid in ids]


def _broken(**kwargs: Any) -> None:
    raise RuntimeError("connection string InstrumentationKey=secret was rejected")


def _broken_credential(client_id: str) -> Any:
    raise RuntimeError("no identity " + client_id)


@pytest.mark.parametrize(
    ("configure", "credential"),
    [(_broken, None), (_FakeAzureMonitor(), _broken_credential)],
)
def test_story_1_5_a_failing_exporter_set_up_never_stops_the_app(
    configure: Any, credential: Any, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="invoicing.telemetry"):
        on = configure_telemetry(
            _config(), configure=configure, credential_factory=credential
        )
    assert on is False
    (record,) = caplog.records
    assert record.levelno == logging.ERROR
    assert record.getMessage().startswith("telemetry.failed ")
    assert event_fields(record) == {"app": "supplier-api", "code": "CONFIGURE_FAILED"}
    assert "secret" not in caplog.text and "no identity" not in caplog.text


def test_story_1_5_telemetry_on_exports_info_and_stops_propagation() -> None:
    logger = logging.getLogger(TELEMETRY_LOGGER)
    configure_telemetry(_config(), configure=_FakeAzureMonitor())
    assert logger.level == logging.INFO and logger.propagate is False
    reset_for_tests()
    assert logger.level == logging.NOTSET and logger.propagate is True


def test_story_1_5_telemetry_off_leaves_the_logger_alone() -> None:
    logger = logging.getLogger(TELEMETRY_LOGGER)
    configure_telemetry(_config(connection_string=None), configure=_FakeAzureMonitor())
    assert logger.level == logging.NOTSET and logger.propagate is True


def test_story_1_5_the_request_span_has_method_and_path_but_no_query(
    spans: InMemorySpanExporter,
) -> None:
    async def handler(req: func.HttpRequest, correlation_id: UUID) -> func.HttpResponse:
        return json_response({}, status=200, correlation_id=correlation_id)

    request = func.HttpRequest(
        method="GET",
        url="https://host.example/api/thing?token=abc",
        headers={},
        body=b"",
    )
    asyncio.run(http_endpoint(handler)(request))
    (span,) = spans.get_finished_spans()
    assert span.attributes["http.request.method"] == "GET"
    assert span.attributes["url.path"] == "/api/thing"
    assert "abc" not in str(dict(span.attributes))
