"""The upload rules the server enforces whatever the page did (AD-6, coding-style.md
rule 16): JPEG, PNG or PDF, decided by the file's own bytes, and 4 MB or less; and the
page's own photo check, as it reports it (Story 1.9)."""

from enum import StrEnum

from invoicing.domain.errors import (
    PayloadTooLargeError,
    UnsupportedMediaTypeError,
    ValidationFailedError,
)

MAX_UPLOAD_BYTES = 4 * 1024 * 1024


class DeviceCheck(StrEnum):
    """The page's own photo check (CAP-3), stored as `device_check` (AD-5).
    `overridden` means the supplier chose "Send it anyway" after 2 failed checks;
    `skipped` means the page couldn't run the check (no decoder, a failed decode, its
    time cap, or a PDF whose pages it couldn't count). The server's quality stage
    checks every upload again either way, so `skipped` is processed like `passed`
    (AD-6)."""

    PASSED = "passed"
    OVERRIDDEN = "overridden"
    SKIPPED = "skipped"


DEVICE_CHECK_MESSAGE = (
    "This upload's photo check is not valid. Reload the page and send the file again."
)


def parse_device_check(value: str | None) -> DeviceCheck:
    """The `X-Device-Check` header: absent means `passed` (a page from before Story
    1.9, or a goods-in scan); `passed`, `overridden` or `skipped` in any case; anything
    else is refused, never guessed."""
    if value is None:
        return DeviceCheck.PASSED
    try:
        return DeviceCheck(value.strip().lower())
    except ValueError:
        raise ValidationFailedError(DEVICE_CHECK_MESSAGE) from None


class UploadContentType(StrEnum):
    """The only accepted file types, as stored in the blob metadata (AD-5)."""

    JPEG = "image/jpeg"
    PNG = "image/png"
    PDF = "application/pdf"


# Magic bytes. The client's Content-Type is never trusted: a GIF or HEIC labelled
# image/jpeg is still refused.
_SIGNATURES: tuple[tuple[bytes, UploadContentType], ...] = (
    (b"\xff\xd8\xff", UploadContentType.JPEG),
    (b"\x89PNG\r\n\x1a\n", UploadContentType.PNG),
)
# PDF readers accept the header anywhere in the first 1024 bytes (some generators put
# a byte-order mark or junk before it), so this does too.
_PDF_HEADER = b"%PDF-"
_PDF_HEADER_WINDOW = 1024


def sniff_content_type(data: bytes) -> UploadContentType | None:
    """The type of `data` by its magic bytes, or None when it is none of the accepted
    ones."""
    for signature, content_type in _SIGNATURES:
        if data.startswith(signature):
            return content_type
    if _PDF_HEADER in data[:_PDF_HEADER_WINDOW]:
        return UploadContentType.PDF
    return None


def check_declared_length(content_length: str | None) -> None:
    """Refuse a request whose Content-Length already says it is too large, before any
    other work. An early refusal only: the Functions host has already read the body,
    so this saves no memory. A missing or unreadable header is left to
    `check_upload`, which checks the actual length."""
    if content_length is None:
        return
    text = content_length.strip()
    if text.isdecimal() and int(text) > MAX_UPLOAD_BYTES:
        raise PayloadTooLargeError()


def check_upload(data: bytes) -> UploadContentType:
    """The type of an acceptable upload. Raises for an empty, too large or
    unsupported file, each with a plain message."""
    if not data:
        raise ValidationFailedError("The file is empty. Choose the invoice again.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise PayloadTooLargeError()
    content_type = sniff_content_type(data)
    if content_type is None:
        raise UnsupportedMediaTypeError()
    return content_type
