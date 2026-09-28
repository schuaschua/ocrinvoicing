"""API error codes and the domain error base (spine Consistency Conventions: Errors).

AD-4 reason codes live in `domain/reasons.py` (a later story); these are the codes
an API returns in its `{code, message, correlation_id}` body.
"""

from enum import StrEnum


class ErrorCode(StrEnum):
    """The only API error codes. Adapters map each one to an HTTP status."""

    INTERNAL_ERROR = "INTERNAL_ERROR"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    UNSUPPORTED_MEDIA_TYPE = "UNSUPPORTED_MEDIA_TYPE"
    # staff-api can't reach PostgreSQL (stopped out of hours, AD-12): HTTP 503.
    DB_OFFLINE = "DB_OFFLINE"
    # A supplier link that is missing, malformed, unknown or revoked (AD-6): HTTP 401,
    # one identical answer for every case (UX-DR7).
    LINK_NOT_VALID = "LINK_NOT_VALID"
    # A storage dependency failed transiently (not the database): HTTP 503.
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"


class DomainError(Exception):
    """An expected failure with an API code and a plain message safe to show a user."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ValidationFailedError(DomainError):
    """The request or its data breaks a rule."""

    def __init__(self, message: str) -> None:
        super().__init__(ErrorCode.VALIDATION_FAILED, message)


class NotFoundError(DomainError):
    """The requested entity does not exist (or the caller may not know it exists)."""

    def __init__(self, message: str) -> None:
        super().__init__(ErrorCode.NOT_FOUND, message)


class DatabaseOfflineError(DomainError):
    """PostgreSQL is unreachable, usually because it is stopped (AD-7, AD-12)."""

    def __init__(
        self, message: str = "The database is offline. Try again later."
    ) -> None:
        super().__init__(ErrorCode.DB_OFFLINE, message)


class LinkNotValidError(DomainError):
    """The supplier link can't be used. The same code and message for a missing,
    malformed, unknown or revoked token, so the answer reveals nothing (UX-DR7)."""

    def __init__(self) -> None:
        super().__init__(
            ErrorCode.LINK_NOT_VALID,
            "This link isn't working. Please contact your buyer at Babaloo.",
        )


class ServiceUnavailableError(DomainError):
    """A storage service failed or timed out; the caller may try again."""

    def __init__(
        self, message: str = "The service is busy. Try again in a moment."
    ) -> None:
        super().__init__(ErrorCode.SERVICE_UNAVAILABLE, message)
