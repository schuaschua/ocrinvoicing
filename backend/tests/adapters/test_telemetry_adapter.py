"""Story 1.5: telemetry start-up and one trace per correlation id, matrix rows
"Telemetry on" and "One trace per correlation id". In-memory exporters only; nothing
reaches Azure."""

import asyncio
import logging
from typing import Any
from uuid import UUID

import azure.functions as func
import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind

from invoicing.adapters.http import CORRELATION_HEADER, http_endpoint, json_response
from invoicing.adapters.logging import event_fields, log_event
from invoicing.adapters.telemetry import (
    TelemetryConfig,
    configure_telemetry,
)

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


def test_story_1_5_the_connection_string_is_never_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG):
        configure_telemetry(_config(), configure=_FakeAzureMonitor())
    assert "InstrumentationKey" not in caplog.text


# --- One trace per correlation id ----------------------------------------------------


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
