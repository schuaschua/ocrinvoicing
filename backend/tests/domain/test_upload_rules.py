"""Story 1.8: the server's upload rules (AD-6): JPEG, PNG or PDF by magic bytes, and
4 MB or less, whatever the client declared."""

import pytest

from invoicing.domain.errors import (
    ErrorCode,
    IdempotencyKeyConflictError,
    ValidationFailedError,
)
from invoicing.domain.upload import (
    DEVICE_CHECK_MESSAGE,
    MAX_UPLOAD_BYTES,
    DeviceCheck,
    UploadContentType,
    check_declared_length,
    check_upload,
    parse_device_check,
    sniff_content_type,
)

JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF = b"%PDF-1.7\n" + b"\x00" * 64
GIF = b"GIF89a" + b"\x00" * 64
HEIC = b"\x00\x00\x00\x18ftypheic" + b"\x00" * 64


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (JPEG, UploadContentType.JPEG),
        (PNG, UploadContentType.PNG),
        (PDF, UploadContentType.PDF),
    ],
)
def test_story_1_8_accepted_types_are_recognised_by_their_bytes(
    data: bytes, expected: UploadContentType
) -> None:
    assert sniff_content_type(data) is expected
    assert check_upload(data) is expected


@pytest.mark.parametrize(
    "data",
    [GIF, HEIC, b"<html>", b"\xff\xd8", b"PDF-1.7", b"\x00" * 1020 + b"%PDF-1.7"],
)
def test_story_1_8_other_bytes_are_unsupported_with_a_plain_message(
    data: bytes,
) -> None:
    assert sniff_content_type(data) is None
    with pytest.raises(Exception) as raised:
        check_upload(data)
    error = raised.value
    assert getattr(error, "code", None) is ErrorCode.UNSUPPORTED_MEDIA_TYPE
    assert "JPEG" in str(error) and "PDF" in str(error)


@pytest.mark.parametrize("prefix", [b" ", b"\xef\xbb\xbf", b"\x00" * 1019])
def test_story_1_8_a_pdf_header_within_the_first_1024_bytes_is_a_pdf(
    prefix: bytes,
) -> None:
    assert check_upload(prefix + b"%PDF-1.7\n" + b"\x00" * 64) is UploadContentType.PDF


def test_story_1_8_four_mb_is_accepted_and_one_byte_more_is_too_large() -> None:
    assert MAX_UPLOAD_BYTES == 4 * 1024 * 1024
    exact = JPEG + b"\x00" * (MAX_UPLOAD_BYTES - len(JPEG))
    assert check_upload(exact) is UploadContentType.JPEG
    with pytest.raises(Exception) as raised:
        check_upload(exact + b"\x00")
    assert getattr(raised.value, "code", None) is ErrorCode.PAYLOAD_TOO_LARGE
    assert "4 MB" in str(raised.value)


def test_story_1_8_an_empty_file_is_refused() -> None:
    with pytest.raises(Exception) as raised:
        check_upload(b"")
    assert getattr(raised.value, "code", None) is ErrorCode.VALIDATION_FAILED


@pytest.mark.parametrize(
    "header", [None, "", "abc", "-5", "100", str(MAX_UPLOAD_BYTES)]
)
def test_story_1_8_a_declared_length_within_the_limit_or_unreadable_passes(
    header: str | None,
) -> None:
    check_declared_length(header)


@pytest.mark.parametrize("header", [str(MAX_UPLOAD_BYTES + 1), " 99999999 "])
def test_story_1_8_a_declared_length_over_the_limit_is_refused_before_reading(
    header: str,
) -> None:
    with pytest.raises(Exception) as raised:
        check_declared_length(header)
    assert getattr(raised.value, "code", None) is ErrorCode.PAYLOAD_TOO_LARGE


def test_story_1_8_key_conflict_says_nothing_about_the_other_upload() -> None:
    error = IdempotencyKeyConflictError()
    assert error.code is ErrorCode.IDEMPOTENCY_KEY_CONFLICT
    assert "supplier" not in error.message.lower()


# --- Story 1.9: the page's device check -----------------------------------------------


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, DeviceCheck.PASSED),
        ("passed", DeviceCheck.PASSED),
        ("overridden", DeviceCheck.OVERRIDDEN),
        (" Overridden ", DeviceCheck.OVERRIDDEN),
        ("skipped", DeviceCheck.SKIPPED),
        (" SKIPPED ", DeviceCheck.SKIPPED),
    ],
)
def test_story_1_9_the_device_check_header_is_read(
    header: str | None, expected: DeviceCheck
) -> None:
    assert parse_device_check(header) is expected


@pytest.mark.parametrize(
    "header", ["", "failed", "true", "passed,overridden", "skip", "skipped,passed"]
)
def test_story_1_9_any_other_device_check_is_refused(header: str) -> None:
    with pytest.raises(ValidationFailedError) as refused:
        parse_device_check(header)
    assert refused.value.code is ErrorCode.VALIDATION_FAILED
    # One fixed message: never what the client sent.
    assert refused.value.message == DEVICE_CHECK_MESSAGE
