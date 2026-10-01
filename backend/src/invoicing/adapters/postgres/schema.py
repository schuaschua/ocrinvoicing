"""SQLAlchemy Core tables of the `intake` schema, as the Alembic migrations create
them (backend/migrations). Used for building statements only; never for creating
tables (migrations run in the pipeline, never at app start, AD-17)."""

from decimal import Decimal

from sqlalchemy import (
    ARRAY,
    TIMESTAMP,
    BigInteger,
    Boolean,
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
    UniqueConstraint,
    Uuid,
    func,
    text,
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

# Story 2.9: each analysed page's size (DI's width, height and unit), so the admin
# screen can draw field boxes. Append-only like its run (migration 0008).
extraction_page = Table(
    "extraction_page",
    metadata,
    Column(
        "run_id",
        Uuid,
        ForeignKey("intake.extraction_run.run_id"),
        primary_key=True,
    ),
    Column("page", Integer, primary_key=True),
    Column("width", Double, nullable=False),
    Column("height", Double, nullable=False),
    Column("unit", Text, nullable=False),
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

# --- `analytics` (Story 4.2, AD-13): written only by the analytics refresh job, read
# by staff-api. Its own metadata, like the schema it lives in.
ANALYTICS = "analytics"

analytics_metadata = MetaData(schema=ANALYTICS)

# CAP-12: the overdue list, replaced as a whole by each day's run.
overdue_po = Table(
    "overdue_po",
    analytics_metadata,
    Column("po_number", Text, primary_key=True),
    Column("supplier_id", Uuid, nullable=False),
    Column("expected_date", Date, nullable=False),
)

# One row per job and Singapore date that ran: the once-a-day guard and the date the
# list was made.
job_run = Table(
    "job_run",
    analytics_metadata,
    Column("job", Text, primary_key=True),
    Column("run_date", Date, primary_key=True),
    Column("finished_at", TIMESTAMP(timezone=True), nullable=False),
)


# --- Story 5.1 (AD-20, migration 0011): the summary tables. Money is numeric(18,2),
# rates numeric(5,4).


def _money() -> Numeric[Decimal]:
    return Numeric(18, 2, asdecimal=True)


def _rate() -> Numeric[Decimal]:
    return Numeric(5, 4, asdecimal=True)


# One row per AD-18 current line with a material of a posted invoice (SGD).
price_point = Table(
    "price_point",
    analytics_metadata,
    Column("invoice_id", Uuid, primary_key=True),
    Column("line_no", Integer, primary_key=True),
    Column("supplier_id", Uuid, nullable=False),
    Column("material_id", Uuid, nullable=False),
    Column("invoice_date", Date, nullable=False),
    Column("unit_price", _money(), nullable=False),
    Column("posted_at", TIMESTAMP(timezone=True), nullable=False),
)

# One row per posted invoice; `posted_month` is the first day of its Singapore month.
invoice_fact = Table(
    "invoice_fact",
    analytics_metadata,
    Column("invoice_id", Uuid, primary_key=True),
    Column("supplier_id", Uuid, nullable=False),
    Column("invoice_date", Date, nullable=False),
    Column("posted_month", Date, nullable=False),
    Column("total", _money()),
    Column("straight_through", Boolean, nullable=False),
)

supplier_month = Table(
    "supplier_month",
    analytics_metadata,
    Column("supplier_id", Uuid, primary_key=True),
    Column("month", Date, primary_key=True),
    Column("spend", _money(), nullable=False),
    Column("posted_count", Integer, nullable=False),
)

month_summary = Table(
    "month_summary",
    analytics_metadata,
    Column("month", Date, primary_key=True),
    Column("posted_count", Integer, nullable=False),
    Column("straight_through_count", Integer, nullable=False),
    Column("straight_through_share", _rate(), nullable=False),
)

# By the Singapore month of the invoice's `created_at`, posted or not (AD-20).
supplier_month_flags = Table(
    "supplier_month_flags",
    analytics_metadata,
    Column("supplier_id", Uuid, primary_key=True),
    Column("month", Date, primary_key=True),
    Column("flagged_count", Integer, nullable=False),
    Column("duplicate_count", Integer, nullable=False),
)

receipt_lateness = Table(
    "receipt_lateness",
    analytics_metadata,
    Column("receipt_id", Uuid, primary_key=True),
    Column("po_line_id", Uuid, primary_key=True),
    Column("supplier_id", Uuid, nullable=False),
    Column("material_id", Uuid, nullable=False),
    Column("received_date", Date, nullable=False),
    Column("days_late", Integer, nullable=False),
)

supplier_on_time = Table(
    "supplier_on_time",
    analytics_metadata,
    Column("supplier_id", Uuid, primary_key=True),
    Column("receipts", Integer, nullable=False),
    Column("on_time", Integer, nullable=False),
    Column("on_time_rate", _rate(), nullable=False),
    Column("avg_days_late", Numeric(8, 2, asdecimal=True), nullable=False),
)

# The highest `posted_at` a job processed.
watermark = Table(
    "watermark",
    analytics_metadata,
    Column("job", Text, primary_key=True),
    Column("posted_at", TIMESTAMP(timezone=True), nullable=False),
)

# CAP-14 and CAP-15 (Stories 5.3 and 5.4), each stored once by `dedupe_key`.
alert = Table(
    "alert",
    analytics_metadata,
    Column("alert_id", Uuid, primary_key=True),
    Column("kind", Text, nullable=False),
    Column("dedupe_key", Text, nullable=False),
    Column("supplier_id", Uuid, nullable=False),
    Column("material_id", Uuid),
    Column("detail", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column(
        "created_at",
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    Column("emailed_at", TIMESTAMP(timezone=True)),
    UniqueConstraint("dedupe_key", name="uq_alert_dedupe_key"),
)

# Story 5.3 (migration 0012): the names of the materials with price points, from
# purchasing (AD-10), so dashboards never read it.
material = Table(
    "material",
    analytics_metadata,
    Column("material_id", Uuid, primary_key=True),
    Column("name", Text, nullable=False),
)
