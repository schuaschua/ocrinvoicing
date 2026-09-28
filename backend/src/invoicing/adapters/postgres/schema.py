"""SQLAlchemy Core tables of the `intake` schema, as the Alembic migrations create
them (backend/migrations). Used for building statements only; never for creating
tables (migrations run in the pipeline, never at app start, AD-17)."""

from sqlalchemy import (
    ARRAY,
    TIMESTAMP,
    BigInteger,
    Column,
    ForeignKey,
    Integer,
    MetaData,
    Table,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB

INTAKE = "intake"

metadata = MetaData(schema=INTAKE)

# AD-3: the invoice row. `status` is the only lifecycle field.
invoice = Table(
    "invoice",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("correlation_id", Uuid, nullable=False),
    Column("source", Text, nullable=False),
    Column("supplier_id", Uuid, nullable=False),
    Column("delivery_id", Uuid),
    Column("content_type", Text, nullable=False),
    Column("device_check", Text, nullable=False),
    Column("photo_taken_at", TIMESTAMP(timezone=True)),
    Column("po_number", Text),
    Column("status", Text, nullable=False),
    Column("status_changed_at", TIMESTAMP(timezone=True), nullable=False),
    Column("claimed_until", TIMESTAMP(timezone=True)),
    Column("next_attempt_at", TIMESTAMP(timezone=True)),
    Column("post_failures", Integer, nullable=False),
    Column("accounts_ref", Text),
    Column("posted_at", TIMESTAMP(timezone=True)),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False),
)

# AD-3: one row per transition, written in the transition's transaction. The insert
# that creates an invoice writes the first row, with no `from_status`.
status_history = Table(
    "status_history",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("invoice_id", Uuid, ForeignKey("intake.invoice.id"), nullable=False),
    Column("from_status", Text),
    Column("to_status", Text, nullable=False),
    Column("actor", Text, nullable=False),
    Column("at", TIMESTAMP(timezone=True), nullable=False),
)

# AD-4: one row per reason; an invoice's open reasons are its latest routing_id's.
admin_item = Table(
    "admin_item",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("invoice_id", Uuid, ForeignKey("intake.invoice.id"), nullable=False),
    Column("routing_id", Uuid, nullable=False),
    Column("run_id", Uuid),
    Column("reason", Text, nullable=False),
    Column("field_ids", ARRAY(Text), nullable=False),
    Column("detail", JSONB, nullable=False),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False),
)

# AD-9: the 64-bit perceptual hash of an image (signed bigint), kept after the image
# is deleted (AD-15).
image_hash = Table(
    "image_hash",
    metadata,
    Column("invoice_id", Uuid, ForeignKey("intake.invoice.id"), primary_key=True),
    Column("phash", BigInteger, nullable=False),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False),
)
