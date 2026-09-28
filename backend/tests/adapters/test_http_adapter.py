"""Story 1.3: HTTP helpers, matrix rows "Unhandled error", "Domain error" and
"Correlation id"."""

import asyncio
import json
import logging
from pathlib import Path
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
    ErrorCode,
    NotFoundError,
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


def test_story_1_3_caller_correlation_id_is_echoed() -> None:
    response = _call(_ok, {CORRELATION_HEADER: CALLER_ID.upper()})
    assert response.headers[CORRELATION_HEADER] == CALLER_ID


@pytest.mark.parametrize(
    "headers",
    [{}, {CORRELATION_HEADER: "not-a-uuid"}, {CORRELATION_HEADER: "' OR 1=1 --"}],
)
def test_story_1_3_missing_or_invalid_correlation_id_gets_a_new_uuid7(
    headers: dict[str, str],
) -> None:
    response = _call(_ok, headers)
    assert UUID(response.headers[CORRELATION_HEADER]).version == 7


def test_story_1_3_every_response_carries_the_security_headers() -> None:
    for handler in (_ok, _plain, _boom):
        response = _call(handler)
        for name, value in SECURITY_HEADERS.items():
            assert response.headers[name] == value
    assert "frame-ancestors 'none'" in SECURITY_HEADERS["Content-Security-Policy"]


def test_story_1_3_handler_responses_get_the_correlation_header() -> None:
    response = _call(_plain, {CORRELATION_HEADER: CALLER_ID})
    assert (
        response.status_code == 202
        and response.headers[CORRELATION_HEADER] == CALLER_ID
    )


def test_story_1_3_unhandled_error_is_a_500_without_internals(
    caplog: pytest.LogCaptureFixture,
) -> None:
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


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (NotFoundError("No such invoice."), 404),
        (DatabaseOfflineError(), 503),
        (DomainError(ErrorCode.VALIDATION_FAILED, "Bad file."), 400),
        (DomainError(ErrorCode.UNAUTHORIZED, "Sign in."), 401),
        (DomainError(ErrorCode.FORBIDDEN, "Not allowed."), 403),
        (DomainError(ErrorCode.CONFLICT, "Already done."), 409),
        (DomainError(ErrorCode.PAYLOAD_TOO_LARGE, "Too big."), 413),
        (DomainError(ErrorCode.UNSUPPORTED_MEDIA_TYPE, "Wrong type."), 415),
        (DomainError(ErrorCode.INTERNAL_ERROR, "Broken."), 500),
    ],
)
def test_story_1_3_domain_error_maps_to_its_status_and_body(
    error: DomainError, status: int, caplog: pytest.LogCaptureFixture
) -> None:
    async def handler(req: func.HttpRequest, correlation_id: UUID) -> func.HttpResponse:
        raise error

    with caplog.at_level(logging.INFO):
        response = _call(handler, {CORRELATION_HEADER: CALLER_ID})
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


def test_story_1_3_wrapped_endpoint_keeps_the_req_binding_name() -> None:
    import inspect

    endpoint = http_endpoint(_ok)
    assert list(inspect.signature(endpoint).parameters) == ["req"]
    assert endpoint.__name__ == "_ok"


def test_story_1_3_every_error_code_has_an_http_status() -> None:
    from invoicing.adapters.http import STATUS_BY_CODE

    assert set(STATUS_BY_CODE) == set(ErrorCode)


def test_story_1_3_responses_are_never_cached() -> None:
    assert SECURITY_HEADERS["Cache-Control"] == "no-store"
    assert _call(_ok).headers["Cache-Control"] == "no-store"


def test_story_1_3_handler_returning_a_non_response_is_an_internal_error() -> None:
    async def not_a_response(
        req: func.HttpRequest, correlation_id: UUID
    ) -> func.HttpResponse:
        return {"ok": True}  # type: ignore[return-value]  # the bug under test

    response = _call(not_a_response, {CORRELATION_HEADER: CALLER_ID})
    assert response.status_code == 500
    assert json.loads(response.get_body())["code"] == "INTERNAL_ERROR"
    assert response.headers[CORRELATION_HEADER] == CALLER_ID
    assert response.headers["Cache-Control"] == "no-store"


def test_story_1_4_security_headers_come_from_the_shared_file() -> None:
    repo = Path(__file__).resolve().parents[3]
    shared = json.loads((repo / "shared" / "security-headers.json").read_text())
    assert {k: v for k, v in SECURITY_HEADERS.items() if k != "Cache-Control"} == shared
    assert set(shared) == {
        "Strict-Transport-Security",
        "Content-Security-Policy",
        "X-Content-Type-Options",
        "Referrer-Policy",
    }
    assert "frame-ancestors 'none'" in shared["Content-Security-Policy"]
    assert "unsafe-inline" not in shared["Content-Security-Policy"]


# --- Story 1.5: who may choose the correlation (trace) id -------------------------------


def test_story_1_5_the_nil_uuid_is_treated_as_absent() -> None:
    response = _call(_ok, {CORRELATION_HEADER: "00000000-0000-0000-0000-000000000000"})
    assert UUID(response.headers[CORRELATION_HEADER]).version == 7


def test_story_1_5_an_untrusting_endpoint_ignores_the_callers_id() -> None:
    endpoint = http_endpoint(_ok, trust_caller_correlation_id=False)  # type: ignore[arg-type]  # test handler
    response = asyncio.run(endpoint(_request({CORRELATION_HEADER: CALLER_ID})))
    issued = UUID(response.headers[CORRELATION_HEADER])
    assert str(issued) != CALLER_ID and issued.version == 7
    assert json.loads(response.get_body()) == {"ok": True}
