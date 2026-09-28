"""Story 1.3: safe logging, matrix row "Log redaction"."""

import logging
from enum import StrEnum
from uuid import UUID

import pytest

from invoicing.adapters.logging import (
    ALLOWED_KEYS,
    DROPPED_FIELDS_KEY,
    bind_correlation_id,
    event_fields,
    log_event,
    safe_fields,
)
from invoicing.adapters.telemetry import correlation_span

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
    assert event_fields(record) == {
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
    assert event_fields(caplog.records[0]) == {"version": "0.1.0"}


@pytest.mark.parametrize("value", ["quality\ncode=FORGED", "tab\there", "bell\x07"])
def test_story_1_3_values_with_control_characters_are_dropped(value: str) -> None:
    assert safe_fields({"stage": value, "code": "OK"}) == {"code": "OK"}


# --- Story 1.5: the bound correlation id --------------------------------------------------

BOUND = UUID("0192f0c1-7a2b-7c3d-8e4f-000000000001")
OUTER = UUID("0192f0c1-7a2b-7c3d-8e4f-000000000002")


def _logged(caplog: pytest.LogCaptureFixture, **fields: object) -> dict[str, object]:
    logger = logging.getLogger("test.bound")
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="test.bound"):
        log_event(logger, "thing.done", **fields)
    return event_fields(caplog.records[-1])


def test_story_1_5_a_dropped_caller_correlation_id_is_replaced_by_the_bound_one(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with bind_correlation_id(BOUND):
        fields = _logged(caplog, correlation_id="bad\nid")
    assert fields == {"correlation_id": str(BOUND), "dropped_fields": 1}


def test_story_1_5_the_callers_own_valid_id_wins(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with bind_correlation_id(BOUND):
        fields = _logged(caplog, correlation_id=OUTER)
    assert fields == {"correlation_id": str(OUTER)}


def test_story_1_5_the_id_is_unbound_after_the_block_even_on_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with bind_correlation_id(BOUND):
        pass
    assert _logged(caplog) == {}
    with pytest.raises(RuntimeError), bind_correlation_id(BOUND):
        raise RuntimeError
    assert _logged(caplog) == {}


def test_story_1_5_a_correlation_span_unbinds_on_exit_and_on_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with correlation_span("x", BOUND):
        pass
    assert _logged(caplog) == {}
    with pytest.raises(RuntimeError), correlation_span("x", BOUND):
        raise RuntimeError
    assert _logged(caplog) == {}


def test_story_1_5_nested_ids_restore_the_outer_one(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with bind_correlation_id(OUTER):
        with bind_correlation_id(BOUND):
            assert _logged(caplog)["correlation_id"] == str(BOUND)
        assert _logged(caplog)["correlation_id"] == str(OUTER)


def test_story_1_5_allowed_keys_never_clash_with_log_record_fields() -> None:
    reserved = set(vars(logging.makeLogRecord({}))) | {"message", "asctime"}
    assert (ALLOWED_KEYS | {DROPPED_FIELDS_KEY}).isdisjoint(reserved)
