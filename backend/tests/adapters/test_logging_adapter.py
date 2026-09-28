"""Story 1.3: safe logging, matrix row "Log redaction"."""

import logging
from enum import StrEnum
from uuid import UUID

import pytest

from invoicing.adapters.logging import log_event, safe_fields

INVOICE_ID = UUID("0192f0c1-7a2b-7c3d-8e4f-0123456789ab")


# A link token, a header, a header map and a bank value: all must be dropped.
LEAKS: dict[str, object] = {
    "upload_token": "c2VjcmV0LXRva2Vu",
    "authorization": "Bearer abc.def",
    "headers": {"X-Upload-Token": "c2VjcmV0LXRva2Vu"},
    "value_text": "DBS 012-345678-9",
}


class Stage(StrEnum):
    QUALITY = "quality"


def test_story_1_3_only_allow_listed_keys_are_emitted(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("test.redaction")
    with caplog.at_level(logging.INFO, logger="test.redaction"):
        log_event(
            logger,
            "upload.accepted",
            invoice_id=INVOICE_ID,
            code="VALIDATION_FAILED",
            duration_ms=12.5,
            attempt=2,
            stage=Stage.QUALITY,
            **LEAKS,
        )
    (record,) = caplog.records
    message = record.getMessage()
    assert record.custom_dimensions == {  # type: ignore[attr-defined]  # set through `extra`
        "invoice_id": str(INVOICE_ID),
        "code": "VALIDATION_FAILED",
        "duration_ms": 12.5,
        "attempt": 2,
        "stage": "quality",
        "dropped_fields": 4,
    }
    assert message.startswith("upload.accepted ")
    for secret in (
        "c2VjcmV0LXRva2Vu",
        "Bearer",
        "012-345678-9",
        "upload_token",
        "X-Upload-Token",
    ):
        assert secret not in message


def test_story_1_3_allowed_keys_with_unsafe_values_are_dropped() -> None:
    assert safe_fields(
        {"code": "x" * 65, "status": {"nested": "value"}, "count": True}
    ) == {"count": True}


def test_story_1_3_nothing_dropped_means_no_dropped_count(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("test.clean")
    with caplog.at_level(logging.INFO, logger="test.clean"):
        log_event(logger, "health.ok", version="0.1.0")
    assert caplog.records[0].custom_dimensions == {"version": "0.1.0"}  # type: ignore[attr-defined]  # via `extra`


@pytest.mark.parametrize("value", ["quality\ncode=FORGED", "tab\there", "bell\x07"])
def test_story_1_3_values_with_control_characters_are_dropped(value: str) -> None:
    assert safe_fields({"stage": value, "code": "OK"}) == {"code": "OK"}
