"""Story 1.3: domain error codes (spine Consistency Conventions: Errors)."""

from invoicing.domain.errors import (
    DatabaseOfflineError,
    DomainError,
    ErrorCode,
    NotFoundError,
    ValidationFailedError,
)


def test_story_1_3_error_codes_are_their_own_names() -> None:
    assert {code.value for code in ErrorCode} >= {
        "INTERNAL_ERROR",
        "VALIDATION_FAILED",
        "NOT_FOUND",
        "DB_OFFLINE",
    }
    assert all(code.value == code.name for code in ErrorCode)


def test_story_1_3_domain_errors_carry_a_code_and_a_plain_message() -> None:
    error = DomainError(ErrorCode.CONFLICT, "Already posted.")
    assert (error.code, error.message, str(error)) == (
        ErrorCode.CONFLICT,
        "Already posted.",
        "Already posted.",
    )
    assert ValidationFailedError("Bad file.").code is ErrorCode.VALIDATION_FAILED
    assert NotFoundError("No such invoice.").code is ErrorCode.NOT_FOUND
    offline = DatabaseOfflineError()
    assert offline.code is ErrorCode.DB_OFFLINE and offline.message
