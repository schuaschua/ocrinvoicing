"""Story 1.8: how storage failures are classified before they become a 503."""

import logging

import pytest
from azure.core.exceptions import (
    AzureError,
    ClientAuthenticationError,
    HttpResponseError,
    ResourceExistsError,
    ResourceNotFoundError,
    ServiceRequestError,
    ServiceResponseError,
)

from invoicing.adapters.storage_errors import storage_error_code


def _status(error: HttpResponseError, status: int) -> HttpResponseError:
    error.status_code = status
    return error


@pytest.mark.parametrize(
    ("error", "code", "level"),
    [
        (ServiceRequestError("connection reset"), "TRANSIENT", logging.WARNING),
        (ServiceResponseError("read timed out"), "TRANSIENT", logging.WARNING),
        (HttpResponseError("no status"), "TRANSIENT", logging.WARNING),
        (_status(HttpResponseError("x"), 500), "TRANSIENT", logging.WARNING),
        (_status(HttpResponseError("x"), 503), "TRANSIENT", logging.WARNING),
        (_status(HttpResponseError("x"), 408), "TRANSIENT", logging.WARNING),
        (_status(HttpResponseError("x"), 429), "TRANSIENT", logging.WARNING),
        (ClientAuthenticationError("no role"), "AUTH_FAILED", logging.ERROR),
        (ResourceNotFoundError("gone"), "RESOURCE_NOT_FOUND", logging.ERROR),
        (_status(HttpResponseError("x"), 400), "HTTP_400", logging.ERROR),
        (_status(HttpResponseError("x"), 403), "HTTP_403", logging.ERROR),
        (_status(HttpResponseError("x"), 413), "HTTP_413", logging.ERROR),
        (_status(ResourceExistsError("x"), 409), "HTTP_409", logging.ERROR),
    ],
)
def test_story_1_8_only_server_and_connection_failures_are_transient(
    error: AzureError, code: str, level: int
) -> None:
    assert storage_error_code(error) == (code, level)
