"""Story 1.8: `IntakeBlobMetadata` (AD-5) and the `uploadkeys` key scheme (AD-6)."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from invoicing.ports.blobs import IMAGES_CONTAINER, image_blob_name
from invoicing.ports.intake import DeviceCheck, IntakeBlobMetadata, IntakeSource
from invoicing.ports.upload_keys import UPLOAD_KEYS_TABLE, partition_key, row_key

INVOICE_ID = UUID("0192f0c1-7a2b-7c3d-8e4f-0123456789ab")
SUPPLIER_ID = UUID("0192f0c1-0000-7000-8000-000000000001")
SGT = timezone(timedelta(hours=8))


def _metadata(**changes: object) -> IntakeBlobMetadata:
    fields: dict[str, object] = {
        "invoice_id": INVOICE_ID,
        "source": IntakeSource.LINK,
        "supplier_id": SUPPLIER_ID,
        "content_type": "image/jpeg",
        "uploaded_at": datetime(2026, 9, 29, 9, 30, tzinfo=SGT),
        "device_check": DeviceCheck.PASSED,
        **changes,
    }
    return IntakeBlobMetadata.model_validate(fields)


def test_story_1_8_supplier_upload_metadata_has_no_delivery_id() -> None:
    assert _metadata().to_blob_metadata() == {
        "invoice_id": str(INVOICE_ID),
        "source": "link",
        "supplier_id": str(SUPPLIER_ID),
        "content_type": "image/jpeg",
        "uploaded_at": "2026-09-29T01:30:00.000000Z",
        "device_check": "passed",
    }


def test_story_1_8_goods_in_metadata_carries_the_delivery_id() -> None:
    delivery = UUID("0192f0c1-0000-7000-8000-0000000000de")
    blob = _metadata(source="goods_in", delivery_id=delivery).to_blob_metadata()
    assert blob["delivery_id"] == str(delivery) and blob["source"] == "goods_in"


def test_story_1_8_metadata_round_trips_whatever_the_key_case() -> None:
    stored = {
        key.upper(): value for key, value in _metadata().to_blob_metadata().items()
    }
    parsed = IntakeBlobMetadata.from_blob_metadata(stored)
    assert parsed == _metadata()
    assert parsed.uploaded_at.tzinfo is UTC


@pytest.mark.parametrize(
    "changes",
    [
        {"content_type": "image/gif"},
        {"source": "email"},
        {"device_check": "skipped"},
        {"uploaded_at": "2026-09-29T09:30:00"},  # naive
    ],
)
def test_story_1_8_metadata_refuses_values_outside_the_contract(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        _metadata(**changes)


def test_story_1_8_unknown_or_missing_blob_metadata_is_a_plain_value_error() -> None:
    blob = _metadata().to_blob_metadata()
    with pytest.raises(ValueError, match="not IntakeBlobMetadata") as raised:
        IntakeBlobMetadata.from_blob_metadata({**blob, "file_name": "secret.jpg"})
    assert "secret.jpg" not in str(raised.value)
    blob.pop("supplier_id")
    with pytest.raises(ValueError, match="not IntakeBlobMetadata"):
        IntakeBlobMetadata.from_blob_metadata(blob)


def test_story_1_8_blob_and_key_names_follow_the_storage_contract() -> None:
    assert IMAGES_CONTAINER == "images"
    assert image_blob_name(INVOICE_ID) == "0192f0c1-7a2b-7c3d-8e4f-0123456789ab"
    assert UPLOAD_KEYS_TABLE == "uploadkeys"
    key = UUID("3FA85F64-5717-4562-B3FC-2C963F66AFA6")
    assert row_key(key) == "3fa85f64-5717-4562-b3fc-2c963f66afa6"
    assert partition_key(key) == "3f"
