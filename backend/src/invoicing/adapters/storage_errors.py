"""Azure Storage failures as the API's retryable 503 (AD-6: the client keeps the file
and retries with the same key). The exception text may carry request URLs or keys, so
only a code is logged and the SDK error is never chained."""

import logging
from typing import NoReturn

from azure.core.exceptions import (
    AzureError,
    ClientAuthenticationError,
    HttpResponseError,
    ResourceNotFoundError,
)

from invoicing.adapters.logging import log_event
from invoicing.domain.errors import ServiceUnavailableError

# Request timeout and throttling: the service asks to be tried again.
_RETRYABLE_4XX = frozenset({408, 429})


def storage_error_code(error: AzureError) -> tuple[str, int]:
    """A code and log level for `error`. Only 5xx answers, 408, 429 and connection
    failures are transient (WARNING). Every other refusal is a fault that retrying
    won't fix (identity, role, missing table, container or queue, a bad request) and
    gets its own code at ERROR, so an alert can tell them apart; the caller sees 503
    either way."""
    if isinstance(error, ClientAuthenticationError):
        return "AUTH_FAILED", logging.ERROR
    if isinstance(error, ResourceNotFoundError):
        return "RESOURCE_NOT_FOUND", logging.ERROR
    status = error.status_code if isinstance(error, HttpResponseError) else None
    if status is not None and 400 <= status < 500 and status not in _RETRYABLE_4XX:
        return f"HTTP_{status}", logging.ERROR
    return "TRANSIENT", logging.WARNING


def raise_unavailable(
    logger: logging.Logger, event: str, error: AzureError, **fields: object
) -> NoReturn:
    """Log `event` with the error's code (and safe `fields`, such as the queue name)
    only, then raise `ServiceUnavailableError`."""
    code, level = storage_error_code(error)
    log_event(logger, event, level=level, code=code, **fields)
    raise ServiceUnavailableError() from None
