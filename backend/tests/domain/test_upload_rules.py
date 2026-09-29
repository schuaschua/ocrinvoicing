"""Story 1.8: the server's upload rules (AD-6): JPEG, PNG or PDF by magic bytes, and
4 MB or less, whatever the client declared."""

import pytest

from invoicing.domain.errors import (
    ErrorCode,
)
from invoicing.domain.upload import (
    MAX_UPLOAD_BYTES,
    UploadContentType,
    check_upload,
    sniff_content_type,
)

JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF = b"%PDF-1.7\n" + b"\x00" * 64
GIF = b"GIF89a" + b"\x00" * 64


def test_story_1_8_upload_type_and_size_rules() -> None:
    """Covers: bytes other than JPEG, PNG or PDF are unsupported with a plain message; 4 MB is
    accepted and one byte more is too large."""
    # Other bytes are unsupported, with a plain message.
    for data in [GIF]:
        assert sniff_content_type(data) is None
        with pytest.raises(Exception) as raised:
            check_upload(data)
        error = raised.value
        assert getattr(error, "code", None) is ErrorCode.UNSUPPORTED_MEDIA_TYPE
        assert "JPEG" in str(error) and "PDF" in str(error)

    # 4 MB is accepted; one byte more is too large.
    assert MAX_UPLOAD_BYTES == 4 * 1024 * 1024
    exact = JPEG + b"\x00" * (MAX_UPLOAD_BYTES - len(JPEG))
    assert check_upload(exact) is UploadContentType.JPEG
    with pytest.raises(Exception) as raised:
        check_upload(exact + b"\x00")
    assert getattr(raised.value, "code", None) is ErrorCode.PAYLOAD_TOO_LARGE
    assert "4 MB" in str(raised.value)
