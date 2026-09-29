"""SQLAlchemy Core tables of the `intake` schema, as the Alembic migrations create
them (backend/migrations). Used for building statements only; never for creating
tables (migrations run in the pipeline, never at app start, AD-17)."""

from sqlalchemy import (
    ARRAY,
    TIMESTAMP,
    BigInteger,
    Column,
    Date,
    Double,
    ForeignKey,
    Integer,
    LargeBinary,
    MetaData,
    Numeric,
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

# AD-18: one row per extraction, the saved result of AD-3. The raw DI result is not
# stored. Append-only, like its fields and lines (migration 0005).
extraction_run = Table(
    "extraction_run",
    metadata,
    Column("run_id", Uuid, primary_key=True),
    Column("invoice_id", Uuid, ForeignKey("intake.invoice.id"), nullable=False),
    Column("model_id", Text, nullable=False),
    Column("api_version", Text, nullable=False),
    Column("pages", Integer, nullable=False),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False),
)

# AD-18: one row per header field. A bank field (AD-11) holds ciphertext plus
# fingerprint and never a value.
invoice_field = Table(
    "invoice_field",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("invoice_id", Uuid, ForeignKey("intake.invoice.id"), nullable=False),
    Column("run_id", Uuid, ForeignKey("intake.extraction_run.run_id"), nullable=False),
    Column("field_id", Text, nullable=False),
    Column("value_text", Text),
    Column("value_number", Numeric(asdecimal=True)),
    Column("value_date", Date),
    Column("currency", Text),
    Column("confidence", Double),
    Column("page", Integer),
    Column("polygon", JSONB),
    Column("source", Text, nullable=False),
    Column("bank_ciphertext", LargeBinary),
    Column("bank_fingerprint", Text),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False),
)

# AD-18: one row per line; `po_line_id` and `material_id` are the validate stage's.
invoice_line = Table(
    "invoice_line",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("invoice_id", Uuid, ForeignKey("intake.invoice.id"), nullable=False),
    Column("run_id", Uuid, ForeignKey("intake.extraction_run.run_id"), nullable=False),
    Column("line_no", Integer, nullable=False),
    Column("product_code", Text),
    Column("description", Text),
    Column("quantity", Numeric(asdecimal=True)),
    Column("unit", Text),
    Column("unit_price", Numeric(asdecimal=True)),
    Column("amount", Numeric(asdecimal=True)),
    Column("tax", Numeric(asdecimal=True)),
    Column("confidence", Double, nullable=False),
    Column("po_line_id", Uuid),
    Column("material_id", Uuid),
    Column("source", Text, nullable=False),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False),
)

# AD-8: pages used per calendar month (its first day) and the last DI request time,
# both changed only under pg_advisory_xact_lock.
di_usage = Table(
    "di_usage",
    metadata,
    Column("month", Date, primary_key=True),
    Column("pages", Integer, nullable=False),
    Column("last_call_at", TIMESTAMP(timezone=True)),
)

# AD-8: an analyze call's Operation-Location, saved before polling so a retry resumes.
di_operation = Table(
    "di_operation",
    metadata,
    Column("invoice_id", Uuid, ForeignKey("intake.invoice.id"), primary_key=True),
    Column("operation_location", Text, nullable=False),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False),
)
