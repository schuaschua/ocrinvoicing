"""The one queue message shape (AD-2). All other data is read from blob storage and
PostgreSQL, so a message never carries invoice content."""

from datetime import UTC, datetime
from typing import Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    field_serializer,
    field_validator,
)


class QueueMessage(BaseModel):
    """`QueueMessage{invoice_id, correlation_id, first_enqueued_at, attempt}`, sent as
    plain JSON text (host.json `messageEncoding: none`)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    invoice_id: UUID
    correlation_id: UUID
    first_enqueued_at: AwareDatetime
    # Informational only: posting failures are counted in `post_failures` (AD-3).
    # Strict: `true`, `"3"` or `2.0` on the wire is a malformed message.
    attempt: StrictInt = Field(ge=1)

    @classmethod
    def first(cls, invoice_id: UUID, correlation_id: UUID, now: datetime) -> Self:
        """The first message for an invoice's step, enqueued at `now`."""
        return cls(
            invoice_id=invoice_id,
            correlation_id=correlation_id,
            first_enqueued_at=now,
            attempt=1,
        )

    @field_validator("first_enqueued_at")
    @classmethod
    def _to_utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @field_serializer("first_enqueued_at")
    def _iso_utc(self, value: datetime) -> str:
        # Timestamps are ISO 8601 UTC (spine Consistency Conventions: Dates).
        return (
            value.astimezone(UTC)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )

    def to_json(self) -> str:
        """The exact text put on the queue: the four fields and nothing else."""
        return self.model_dump_json()

    @classmethod
    def from_json(cls, text: str | bytes) -> Self:
        """Parse a message taken off a queue; unknown or missing fields are rejected."""
        return cls.model_validate_json(text)
