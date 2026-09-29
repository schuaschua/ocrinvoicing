"""Story 1.3: HTTP helpers, matrix rows "Unhandled error", "Domain error" and
"Correlation id"."""

import asyncio
import json
import logging
from uuid import UUID

import azure.functions as func
import pytest

from invoicing.adapters.http import (
    CORRELATION_HEADER,
    SECURITY_HEADERS,
    http_endpoint,
    json_response,
)
from invoicing.adapters.logging import event_fields
from invoicing.domain.errors import (
    DatabaseOfflineError,
    DomainError,
)

CALLER_ID = "0192f0c1-7a2b-7c3d-8e4f-0123456789ab"


def _request(headers: dict[str, str] | None = None) -> func.HttpRequest:
    return func.HttpRequest(
        method="GET", url="/api/thing", headers=headers or {}, body=b""
    )


def _call(handler: object, headers: dict[str, str] | None = None) -> func.HttpResponse:
    return asyncio.run(http_endpoint(handler)(_request(headers)))  # type: ignore[arg-type]  # test handlers


async def _ok(req: func.HttpRequest, correlation_id: UUID) -> func.HttpResponse:
    return json_response({"ok": True}, status=200, correlation_id=correlation_id)


async def _plain(req: func.HttpRequest, correlation_id: UUID) -> func.HttpResponse:
    return func.HttpResponse("plain", status_code=202)


async def _boom(req: func.HttpRequest, correlation_id: UUID) -> func.HttpResponse:
    raise RuntimeError("/srv/app/secret.py line 3: password=hunter2")


def test_story_1_3_responses_carry_security_headers_and_errors_never_leak_internals(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # --- Story 1.3: every response carries the security headers
    for handler in (_ok, _plain, _boom):
        response = _call(handler)
        for name, value in SECURITY_HEADERS.items():
            assert response.headers[name] == value
    assert "frame-ancestors 'none'" in SECURITY_HEADERS["Content-Security-Policy"]

    # --- Story 1.3: an unhandled error is a 500 without internals
    caplog.clear()
    with caplog.at_level(logging.INFO):
        response = _call(_boom, {CORRELATION_HEADER: CALLER_ID})
    body = json.loads(response.get_body())
    assert response.status_code == 500
    assert set(body) == {"code", "message", "correlation_id"}
    assert body["code"] == "INTERNAL_ERROR" and body["correlation_id"] == CALLER_ID
    assert response.headers[CORRELATION_HEADER] == CALLER_ID
    text = response.get_body().decode() + caplog.text
    for leak in ("hunter2", "/srv/app", "Traceback", "RuntimeError"):
        assert leak not in text
    (record,) = [r for r in caplog.records if r.name == "invoicing.http"]
    assert record.levelno == logging.ERROR
    assert event_fields(record) == {
        "correlation_id": CALLER_ID,
        "code": "INTERNAL_ERROR",
    }

    # --- Story 1.3: a domain error maps to its status and body
    for error, status in [(DatabaseOfflineError(), 503)]:

        async def raising(
            req: func.HttpRequest, correlation_id: UUID, error: DomainError = error
        ) -> func.HttpResponse:
            raise error

        caplog.clear()
        with caplog.at_level(logging.INFO):
            response = _call(raising, {CORRELATION_HEADER: CALLER_ID})
        assert response.status_code == status
        (record,) = [r for r in caplog.records if r.name == "invoicing.http"]
        assert record.getMessage().startswith("http.domain_error ")
        assert event_fields(record) == {
            "correlation_id": CALLER_ID,
            "code": error.code.value,
        }
        assert json.loads(response.get_body()) == {
            "code": error.code.value,
            "message": error.message,
            "correlation_id": CALLER_ID,
        }
        assert response.mimetype == "application/json"
