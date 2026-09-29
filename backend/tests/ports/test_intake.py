"""Story 1.8: `IntakeBlobMetadata` (AD-5) and the `uploadkeys` key scheme (AD-6)."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

from invoicing.ports.intake import DeviceCheck, IntakeBlobMetadata, IntakeSource

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


def test_story_1_8_metadata_round_trips_whatever_the_key_case() -> None:
    stored = {
        key.upper(): value for key, value in _metadata().to_blob_metadata().items()
    }
    parsed = IntakeBlobMetadata.from_blob_metadata(stored)
    assert parsed == _metadata()
    assert parsed.uploaded_at.tzinfo is UTC
