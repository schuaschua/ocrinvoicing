"""Seeding for the Story 2.5 and 2.6 `validate` stage tests: invoices with their runs,
fields, lines, photo time, image hash and bank fingerprints, written as the deployer
(the owner), as the quality and extract stages and admin Correct would have left
them. Synthetic values only (security.md rule 1)."""

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, func, insert
from sqlalchemy.dialects.postgresql import insert as pg_insert

from apps._pipeline_fakes import CORRELATION_ID, invoice_id
from contracts.purchasing_contract import SUPPLIER_ALPHA
from invoicing.adapters.postgres.invoices import signed_phash
from invoicing.adapters.postgres.schema import (
    extraction_run,
    image_hash,
    invoice,
    invoice_field,
    invoice_line,
)
from invoicing.adapters.postgres.suppliers import supplier
from invoicing.ports.messages import QueueMessage

MASTER_NAME = "Synthetic Alpha Building Supplies"
MASTER_TAX_ID = "201912345K"
CONFIDENT = 0.99
# A day after PO-45012's latest goods receipt (2026-09-15), in Singapore time.
IN_RANGE_PHOTO = datetime(2026, 9, 16, 2, 0, tzinfo=UTC)


def message(for_invoice: UUID) -> str:
    return QueueMessage.first(
        for_invoice, CORRELATION_ID, datetime(2026, 9, 30, tzinfo=UTC)
    ).to_json()


def seed_master(owner: Engine) -> None:
    """Synthetic Alpha's `master.supplier` row."""
    with owner.begin() as connection:
        statement = pg_insert(supplier).values(
            id=SUPPLIER_ALPHA, name=MASTER_NAME, tax_id=MASTER_TAX_ID
        )
        connection.execute(
            statement.on_conflict_do_update(
                index_elements=[supplier.c.id],
                set_={"name": MASTER_NAME, "tax_id": MASTER_TAX_ID},
            )
        )


class Seeder:
    """Writes invoices as the deployer (the owner)."""

    def __init__(self, owner: Engine) -> None:
        self.owner = owner

    def invoice(
        self,
        n: int,
        *,
        fields: Mapping[str, tuple[str | Decimal | None, float]],
        lines: list[tuple[str | None, str | None, str]],
        status: str = "awaiting_validation",
        source: str = "link",
        delivery_id: UUID | None = None,
        run: bool = True,
        matched: Mapping[int, UUID] | None = None,
        photo_taken_at: datetime | None = IN_RANGE_PHOTO,
        phash: int | None = None,
        bank: Mapping[str, str | None] | None = None,
    ) -> UUID:
        """`lines` are (product_code, quantity, unit_price); `matched` pre-fills a
        line's `po_line_id` (an invoice validated earlier); `bank` maps a bank field id
        (`payment[<n>].<id>`) to its fingerprint (None: found with no value)."""
        created = invoice_id(n)
        run_id = UUID(int=n)
        with self.owner.begin() as connection:
            connection.execute(
                insert(invoice).values(
                    id=created,
                    correlation_id=CORRELATION_ID,
                    source=source,
                    supplier_id=SUPPLIER_ALPHA,
                    delivery_id=delivery_id,
                    content_type="image/jpeg",
                    device_check="passed",
                    photo_taken_at=photo_taken_at,
                    status=status,
                    status_changed_at=func.now(),
                    post_failures=0,
                    created_at=func.now(),
                )
            )
            if phash is not None:
                connection.execute(
                    insert(image_hash).values(
                        invoice_id=created,
                        phash=signed_phash(phash),
                        created_at=func.now(),
                    )
                )
            if not run:
                return created
            connection.execute(
                insert(extraction_run).values(
                    run_id=run_id,
                    invoice_id=created,
                    model_id="prebuilt-invoice",
                    api_version="2024-11-30",
                    pages=1,
                    created_at=func.now(),
                )
            )
            rows: list[dict[str, Any]] = []
            for field_id, (value, confidence) in fields.items():
                rows.append(
                    {
                        "field_id": field_id,
                        "value_text": value if isinstance(value, str) else None,
                        "value_number": value if isinstance(value, Decimal) else None,
                        "confidence": confidence,
                    }
                )
            for field_id, fingerprint in (bank or {}).items():
                rows.append(
                    {
                        "field_id": field_id,
                        "confidence": CONFIDENT,
                        "bank_ciphertext": None if fingerprint is None else b"pgp",
                        "bank_fingerprint": fingerprint,
                    }
                )
            for number, row in enumerate(rows):
                connection.execute(
                    insert(invoice_field).values(
                        id=UUID(int=n * 1000 + number),
                        invoice_id=created,
                        run_id=run_id,
                        source="di",
                        created_at=func.now(),
                        **row,
                    )
                )
        # After the commit: each line is its own transaction, like an admin's row.
        for line_no, (code, quantity, price) in enumerate(lines, start=1):
            self.line(created, run_id, n, line_no, code, quantity, price, matched)
        return created

    def line(
        self,
        created: UUID,
        run_id: UUID,
        n: int,
        line_no: int,
        code: str | None,
        quantity: str | None,
        price: str,
        matched: Mapping[int, UUID] | None = None,
        *,
        source: str = "di",
    ) -> None:
        qty = None if quantity is None else Decimal(quantity)
        with self.owner.begin() as connection:
            connection.execute(
                insert(invoice_line).values(
                    id=UUID(
                        int=n * 1000 + 500 + line_no + (50 if source == "admin" else 0)
                    ),
                    invoice_id=created,
                    run_id=run_id,
                    line_no=line_no,
                    product_code=code,
                    quantity=qty,
                    unit_price=Decimal(price),
                    amount=(qty or Decimal(1)) * Decimal(price),
                    confidence=1.0
                    if source == "admin"
                    else (0.0 if qty is None else CONFIDENT),
                    po_line_id=(matched or {}).get(line_no),
                    source=source,
                    created_at=func.now(),
                )
            )


def header(
    sub_total: str,
    po: str | None = "PO-45012",
    tax_id: str | None = "2019-12345-k",
    number: str = "INV-A-1",
) -> dict[str, tuple[str | Decimal | None, float]]:
    fields: dict[str, tuple[str | Decimal | None, float]] = {
        "vendor_name": ("Synthetic Alpha Building Supplies Pte. Ltd.", 0.995),
        "invoice_number": (number, CONFIDENT),
        "invoice_date": ("2026-09-20", CONFIDENT),
        "sub_total": (Decimal(sub_total), CONFIDENT),
        "invoice_total": (Decimal(sub_total) * Decimal("1.09"), CONFIDENT),
    }
    if po is not None:
        fields["purchase_order"] = (po, CONFIDENT)
    if tax_id is not None:
        fields["vendor_tax_id"] = (tax_id, CONFIDENT)
    return fields


def one(engine: Engine, statement: Any) -> Any:
    with engine.connect() as connection:
        return connection.execute(statement).one()
