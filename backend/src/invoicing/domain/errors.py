"""API error codes and the domain error base (spine Consistency Conventions: Errors).

AD-4 reason codes live in `domain/reasons.py` (Story 2.1); these are the codes
an API returns in its `{code, message, correlation_id}` body.
"""

from enum import StrEnum


class ErrorCode(StrEnum):
    """The only API error codes. Adapters map each one to an HTTP status."""

    INTERNAL_ERROR = "INTERNAL_ERROR"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    # A staff-api call with no valid built-in auth principal (AD-14): HTTP 401.
    UNAUTHENTICATED = "UNAUTHENTICATED"
    # staff-api runs in Azure with built-in auth off, so no principal can be trusted
    # (AD-14): every staff route fails closed with HTTP 401.
    AUTH_DISABLED = "AUTH_DISABLED"
    # A signed-in staff user without a role the route allows (AD-14): HTTP 403.
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
    # An upload's Idempotency-Key is already held by another supplier (AD-6): HTTP 409.
    IDEMPOTENCY_KEY_CONFLICT = "IDEMPOTENCY_KEY_CONFLICT"
    # An admin item's image was deleted by the 30-day retention rule (AD-15): HTTP 404.
    IMAGE_DELETED = "IMAGE_DELETED"


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


class PayloadTooLargeError(DomainError):
    """An upload over the size limit (AD-6: 4 MB)."""

    def __init__(
        self, message: str = "This file is too big. Send a file of 4 MB or less."
    ) -> None:
        super().__init__(ErrorCode.PAYLOAD_TOO_LARGE, message)


class UnsupportedMediaTypeError(DomainError):
    """An upload whose bytes are not JPEG, PNG or PDF (AD-6)."""

    def __init__(
        self,
        message: str = "This file can't be sent. Send a JPEG or PNG photo, or a PDF.",
    ) -> None:
        super().__init__(ErrorCode.UNSUPPORTED_MEDIA_TYPE, message)


class IdempotencyKeyConflictError(DomainError):
    """The upload's Idempotency-Key belongs to another supplier's upload (AD-6). The
    message says nothing about that upload."""

    def __init__(self) -> None:
        super().__init__(
            ErrorCode.IDEMPOTENCY_KEY_CONFLICT,
            "This upload can't be accepted. Choose the file again and send it.",
        )


class UnauthenticatedError(DomainError):
    """No signed-in staff user: the built-in auth principal is missing or malformed
    (AD-14). The staff app answers with its session-ended dialog."""

    def __init__(self) -> None:
        super().__init__(
            ErrorCode.UNAUTHENTICATED,
            "Your session ended. Sign in again to continue.",
        )


class AuthDisabledError(DomainError):
    """staff-api is running in Azure without built-in auth: fail closed (AD-14)."""

    def __init__(self) -> None:
        super().__init__(
            ErrorCode.AUTH_DISABLED,
            "Sign-in is not set up for this app. Contact your administrator.",
        )


class ForbiddenError(DomainError):
    """The signed-in staff user has none of the roles the route allows (AD-14)."""

    def __init__(self) -> None:
        super().__init__(ErrorCode.FORBIDDEN, "You don't have access to that page.")


class ImageDeletedError(DomainError):
    """The invoice's image is gone: the 30-day retention rule deleted it (AD-15)."""

    def __init__(self) -> None:
        super().__init__(ErrorCode.IMAGE_DELETED, "Image deleted after 30 days.")
