"""The intake blob's metadata (AD-5): who wrote the upload and for which supplier. The
`quality` stage creates the invoice row from it, so it is the contract between the
intake writers (`supplier-api`, `staff-api` goods-in) and the pipeline."""

from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    ValidationError,
    field_serializer,
    field_validator,
)

from invoicing.domain.upload import UploadContentType


class IntakeSource(StrEnum):
    """Who wrote the upload (AD-5)."""

    LINK = "link"
    GOODS_IN = "goods_in"


class DeviceCheck(StrEnum):
    """The page's own photo check (CAP-3). `overridden` means "Send it anyway"
    (Story 1.9); until then every upload is `passed`."""

    PASSED = "passed"
    OVERRIDDEN = "overridden"


class IntakeBlobMetadata(BaseModel):
    """`IntakeBlobMetadata{invoice_id, source, supplier_id, delivery_id?, content_type,
    uploaded_at, device_check}`, stored as the metadata of `images/<invoice_id>`.
    `delivery_id` is set for goods-in scans only and is absent otherwise."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    invoice_id: UUID
    source: IntakeSource
    supplier_id: UUID
    delivery_id: UUID | None = None
    content_type: UploadContentType
    uploaded_at: AwareDatetime
    device_check: DeviceCheck

    @field_validator("uploaded_at")
    @classmethod
    def _to_utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @field_serializer("uploaded_at")
    def _iso_utc(self, value: datetime) -> str:
        # Timestamps are ISO 8601 UTC (spine Consistency Conventions: Dates).
        return (
            value.astimezone(UTC)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )

    def to_blob_metadata(self) -> dict[str, str]:
        """Blob metadata: ASCII string values only, with `delivery_id` left out when
        it is not set."""
        return {
            key: str(value)
            for key, value in self.model_dump(mode="json").items()
            if value is not None
        }

    @classmethod
    def from_blob_metadata(cls, metadata: Mapping[str, str]) -> Self:
        """Parse a blob's metadata. Blob storage may return keys in any case; unknown
        keys or missing fields raise ValueError, naming no values."""
        lowered = {key.lower(): value for key, value in metadata.items()}
        try:
            return cls.model_validate(lowered)
        except ValidationError:
            raise ValueError("the blob metadata is not IntakeBlobMetadata") from None
