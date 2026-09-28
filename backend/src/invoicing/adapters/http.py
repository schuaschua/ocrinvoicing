"""HTTP helpers for the Function apps: correlation ids, the `{code, message,
correlation_id}` error shape, status mapping and security headers."""

import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from uuid import UUID

import azure.functions as func

from invoicing.adapters.logging import log_event
from invoicing.domain.errors import DomainError, ErrorCode
from invoicing.domain.ids import new_uuid7, parse_uuid

CORRELATION_HEADER = "X-Correlation-Id"

SECURITY_HEADERS_FILE = "security-headers.json"


def _security_headers_file() -> Path:
    """shared/security-headers.json: at the deploy package's root (ci/code-deploy.sh
    copies it there) or, in the repository, at the repository root."""
    parents = Path(__file__).resolve().parents
    # <package>/invoicing/adapters, then <repo>/backend/src/invoicing/adapters.
    for depth in (2, 4):
        if depth < len(parents):
            candidate = parents[depth] / "shared" / SECURITY_HEADERS_FILE
            if candidate.is_file():
                return candidate
    raise RuntimeError(f"shared/{SECURITY_HEADERS_FILE} not found")


def load_security_headers() -> dict[str, str]:
    """security.md rule 25 headers from their one source, which the web apps' preview
    server reads too (web/*/vite.config.ts)."""
    data = json.loads(_security_headers_file().read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in data.items()
    ):
        raise RuntimeError(f"shared/{SECURITY_HEADERS_FILE} must map names to strings")
    return data


# security.md rule 25: on every response, set by the app.
SECURITY_HEADERS: Mapping[str, str] = {
    **load_security_headers(),
    # API responses carry per-user data; never cache them.
    "Cache-Control": "no-store",
}

STATUS_BY_CODE: Mapping[ErrorCode, int] = {
    ErrorCode.INTERNAL_ERROR: 500,
    ErrorCode.VALIDATION_FAILED: 400,
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.CONFLICT: 409,
    ErrorCode.PAYLOAD_TOO_LARGE: 413,
    ErrorCode.UNSUPPORTED_MEDIA_TYPE: 415,
    ErrorCode.DB_OFFLINE: 503,
}

# security.md rule 26: a plain message, never a stack trace or internal detail.
INTERNAL_ERROR_MESSAGE = "Something went wrong. Try again later."

type Handler = Callable[[func.HttpRequest, UUID], Awaitable[func.HttpResponse]]
type Endpoint = Callable[[func.HttpRequest], Awaitable[func.HttpResponse]]

_logger = logging.getLogger("invoicing.http")


def correlation_id_for(req: func.HttpRequest) -> UUID:
    """The caller's `X-Correlation-Id` when it is a valid UUID, else a new UUIDv7."""
    return parse_uuid(req.headers.get(CORRELATION_HEADER)) or new_uuid7()


def json_response(
    body: Mapping[str, object], *, status: int, correlation_id: UUID
) -> func.HttpResponse:
    """A JSON response carrying the correlation id and the security headers."""
    headers = {**SECURITY_HEADERS, CORRELATION_HEADER: str(correlation_id)}
    return func.HttpResponse(
        json.dumps(body),
        status_code=status,
        headers=headers,
        mimetype="application/json",
        charset="utf-8",
    )


def error_response(
    code: ErrorCode, message: str, *, correlation_id: UUID
) -> func.HttpResponse:
    """The API error shape `{code, message, correlation_id}` with the code's status."""
    body = {
        "code": code.value,
        "message": message,
        "correlation_id": str(correlation_id),
    }
    return json_response(
        body, status=STATUS_BY_CODE[code], correlation_id=correlation_id
    )


def http_endpoint(
    handler: Handler, *, enforced_headers: Mapping[str, str] = SECURITY_HEADERS
) -> Endpoint:
    """Wrap `handler(req, correlation_id)` so domain errors map to their status and any
    other exception becomes a 500 `INTERNAL_ERROR`, logged by correlation id and code only.

    `enforced_headers` overwrite the handler's own on every successful response; error
    responses always carry `SECURITY_HEADERS`. Only the static-file adapter narrows them,
    to set its own Cache-Control."""

    # Not functools.wraps: the Functions host binds the trigger by the signature's
    # parameter name (`req`), and wraps would expose the handler's own signature.
    async def endpoint(req: func.HttpRequest) -> func.HttpResponse:
        correlation_id = correlation_id_for(req)
        try:
            response = await handler(req, correlation_id)
            if not isinstance(response, func.HttpResponse):
                raise TypeError("handler did not return an HttpResponse")
            for name, value in enforced_headers.items():
                response.headers[name] = value
            response.headers[CORRELATION_HEADER] = str(correlation_id)
            return response
        except DomainError as error:
            log_event(
                _logger,
                "http.domain_error",
                correlation_id=correlation_id,
                code=error.code,
            )
            return error_response(
                error.code, error.message, correlation_id=correlation_id
            )
        # The API boundary: any other failure becomes a 500 with no internals (security.md rule 26).
        except Exception:  # noqa: BLE001
            log_event(
                _logger,
                "http.unhandled_error",
                level=logging.ERROR,
                correlation_id=correlation_id,
                code=ErrorCode.INTERNAL_ERROR,
            )
            return error_response(
                ErrorCode.INTERNAL_ERROR,
                INTERNAL_ERROR_MESSAGE,
                correlation_id=correlation_id,
            )

    endpoint.__name__ = handler.__name__
    endpoint.__qualname__ = handler.__qualname__
    endpoint.__doc__ = handler.__doc__
    return endpoint
