"""Story 2.6: the `validate` stage's duplicate, photo-date and bank checks and the
reminder cleanup, against a real PostgreSQL 18 signed in as the pipeline login, with
the purchasing simulation's synthetic seed (PO-45012 of Synthetic Alpha, its latest
receipt on 2026-09-15) and fakes for the queue and the reminder table.

One merged test (the 200-case cap, coding-style.md rule 20 exception): each plan
matrix row is a block of assertions, in order."""

import asyncio
import logging
import threading
import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine, create_engine, delete, func, insert, select, text

from apps._pipeline_fakes import FakeQueue, FakeReminders
from apps._validation_seed import Seeder, header, message, seed_master
from conftest import PostgresServer
from contracts.purchasing_contract import DELIVERY_12_2, SUPPLIER_ALPHA
from invoicing.adapters.logging import MAX_VALUE_LENGTH, event_fields
from invoicing.adapters.postgres.invoices import PostgresInvoiceRepository
from invoicing.adapters.postgres.schema import admin_item, invoice
from invoicing.adapters.postgres.suppliers import PostgresSupplierReader, supplier_bank
from invoicing.adapters.postgres.validation import PostgresValidationRepository
from invoicing.adapters.purchasing_factory import purchasing_port
from invoicing.apps.pipeline.validate import (
    ValidateAction,
    ValidateDependencies,
    ValidateOutcome,
    validate_handler,
)

# Synthetic fingerprints (lowercase hex, as the HMAC gives them).
IBAN = "1" * 64
SWIFT = "2" * 64
OTHER_IBAN = "3" * 64
PO = "PO-45012"
# Far apart: more than 8 bits differ between any two of them.
PHASH_COPY, PHASH_RESEND, PHASH_OTHER = (
    0x0,
    0xFFFF_0000_0000_0000,
    0x0000_FFFF_FFFF_0000,
)
# A bounded wait for another connection's state, never for time-based behaviour.
WAIT_SECONDS = 10.0


def _scan(number: str) -> dict[str, Any]:
    """A goods-in scan of delivery 2 (50 rebar at 18.50): its PO passes and nothing
    is deducted for other invoices, so copies differ only by the 2.6 checks."""
    return {
        "fields": header("925.00", po=None, tax_id=None, number=number),
        "lines": [("ALP-RB-12", "50", "18.50")],
        "source": "goods_in",
        "delivery_id": DELIVERY_12_2,
    }


def _items(engine: Engine, for_invoice: UUID) -> dict[str, Any]:
    with engine.connect() as connection:
        return {
            row.reason: row
            for row in connection.execute(
                select(admin_item).where(admin_item.c.invoice_id == for_invoice)
            )
        }


def _waiting_for_advisory_lock(owner: Engine) -> bool:
    with owner.connect() as connection:
        waiting = connection.execute(
            text(
                "SELECT count(*) FROM pg_locks"
                " WHERE locktype = 'advisory' AND NOT granted"
            )
        ).scalar_one()
    return bool(waiting)


def test_story_2_6_validate_stage(
    pipeline_engine: Engine,
    postgres_server: PostgresServer,
    purchasing_seeded: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="invoicing")
    owner = create_engine(
        postgres_server.url(postgres_server.deployer, purchasing_seeded)
    )
    seed_master(owner)
    with owner.begin() as connection:
        connection.execute(
            delete(supplier_bank).where(supplier_bank.c.supplier_id == SUPPLIER_ALPHA)
        )
        connection.execute(
            insert(supplier_bank),
            [
                {
                    "supplier_id": SUPPLIER_ALPHA,
                    "field_id": field_id,
                    "ciphertext": b"pgp",
                    "fingerprint": fingerprint,
                }
                for field_id, fingerprint in (("iban", IBAN), ("swift", SWIFT))
            ],
        )
    seed = Seeder(owner)
    queue = FakeQueue()
    reminders = FakeReminders()
    invoices = PostgresInvoiceRepository(pipeline_engine)
    handle = validate_handler(
        ValidateDependencies(
            invoices=invoices,
            validations=PostgresValidationRepository(pipeline_engine, invoices),
            purchasing=purchasing_port("sim", pipeline_engine),
            suppliers=PostgresSupplierReader(pipeline_engine),
            queue=queue,
            reminders=reminders,
        )
    )

    def run(for_invoice: UUID) -> ValidateOutcome:
        return asyncio.run(handle(message(for_invoice)))

    def status(for_invoice: UUID) -> str:
        with pipeline_engine.connect() as connection:
            return str(
                connection.execute(
                    select(invoice.c.status).where(invoice.c.id == for_invoice)
                ).scalar_one()
            )

    # --- Two copies: the later is DUPLICATE, whichever finishes first -----------------
    # Same fingerprint once normalised; the later copy also has the same image.
    original = seed.invoice(21, phash=PHASH_COPY, **_scan("INV-B-7"))
    copy = seed.invoice(22, phash=PHASH_COPY ^ 0xFF, **_scan("inv b 7"))
    outcome = run(copy)
    assert (outcome.action, outcome.reasons) == (ValidateAction.ROUTE, ("DUPLICATE",))
    assert _items(pipeline_engine, copy)["DUPLICATE"].detail == {
        "invoice_id": str(original),
        "basis": "fingerprint",
    }
    # The earlier copy, validated after it, never looks at the later one.
    assert run(original).action is ValidateAction.ADVANCE
    assert status(original) == "ready_to_post"
    # A matched PO's reminder row is deleted after each commit, routed or not.
    assert reminders.deleted == [(SUPPLIER_ALPHA, PO), (SUPPLIER_ALPHA, PO)]

    # --- Rejected original and a clear resend: not a duplicate ------------------------
    rejected = seed.invoice(
        23, phash=PHASH_RESEND, status="rejected", **_scan("INV-C-1")
    )
    resend = seed.invoice(24, phash=PHASH_RESEND, **_scan("INV-C-1"))
    assert run(resend).action is ValidateAction.ADVANCE
    assert status(rejected) == "rejected"

    # --- Photo date out of range, and a reminder delete that fails ---------------------
    reminders.failing = True
    early = seed.invoice(
        25,
        phash=PHASH_OTHER,
        photo_taken_at=datetime(2026, 9, 14, 3, tzinfo=UTC),
        **_scan("INV-D-1"),
    )
    outcome = run(early)
    assert (outcome.action, outcome.reasons) == (
        ValidateAction.ROUTE,
        ("DATE_MISMATCH",),
    )
    assert _items(pipeline_engine, early)["DATE_MISMATCH"].detail == {"days": -1}
    # The invoice is unaffected: routed and committed, the failure only logged.
    assert status(early) == "in_admin_queue"
    assert "REMINDER_DELETE_FAILED" in caplog.text
    reminders.failing = False

    # --- Bank change, no photo date and 2.5's reasons: one routing --------------------
    # An upload of the cement line (100 received, not invoiced elsewhere: 780.00).
    queue.sent.clear()
    changed = seed.invoice(
        26,
        fields={**header("780.00", number="INV-E-1"), "invoice_date": ("x", 0.5)},
        lines=[("ALP-CEM-50", "100", "7.80")],
        photo_taken_at=None,
        bank={
            "payment[0].iban": OTHER_IBAN,
            "payment[0].swift": SWIFT,
            "payment[0].bank_account_number": SWIFT,
        },
    )
    outcome = run(changed)
    assert outcome.action is ValidateAction.ROUTE
    assert queue.sent == []
    items = _items(pipeline_engine, changed)
    assert set(items) == {"LOW_CONFIDENCE", "NO_PHOTO_DATE", "BANK_CHANGED"}
    assert len({row.routing_id for row in items.values()}) == 1
    # The master holds no account number: changed, and never compared with SWIFT.
    assert items["BANK_CHANGED"].field_ids == [
        "payment[0].bank_account_number",
        "payment[0].iban",
    ]
    assert items["BANK_CHANGED"].detail == {}
    assert reminders.deleted[-1] == (SUPPLIER_ALPHA, PO)
    logged = " ".join(str(record.__dict__) for record in caplog.records)
    assert "LOW_CONFIDENCE,NO_PHOTO_DATE,BANK_CHANGED" in logged
    # Neither fingerprint nor field value reaches a log (security.md rule 31).
    for value in (OTHER_IBAN, SWIFT, "INV-E-1", "780.00"):
        assert value not in logged

    # --- Phash duplicate: another number, the same image, the top bit set -----------
    # Unsigned 64-bit hashes (stored signed): 8 bits apart, and more than 8 from every
    # hash above, so only the phash can match.
    photo = (1 << 63) | 0xFFFF_FFFF
    first_photo = seed.invoice(28, phash=photo, **_scan("INV-G-1"))
    second_photo = seed.invoice(29, phash=photo ^ 0xFF00, **_scan("INV-G-2"))
    assert run(first_photo).action is ValidateAction.ADVANCE
    outcome = run(second_photo)
    assert (outcome.action, outcome.reasons) == (ValidateAction.ROUTE, ("DUPLICATE",))
    assert _items(pipeline_engine, second_photo)["DUPLICATE"].detail == {
        "invoice_id": str(first_photo),
        "basis": "phash",
    }

    # --- Five reasons: too long for one log value, so one event per reason ----------
    caplog.clear()
    many = seed.invoice(
        30,
        fields={
            **header("5.00", tax_id="T99999999Z", number="INV-H-1"),
            "invoice_date": ("x", 0.5),
        },
        lines=[("ALP-CEM-50", "1", "1.00")],
        photo_taken_at=None,
        bank={"payment[0].iban": OTHER_IBAN},
    )
    codes = (
        "LOW_CONFIDENCE",
        "PO_MISMATCH",
        "SUPPLIER_ID_MISMATCH",
        "NO_PHOTO_DATE",
        "BANK_CHANGED",
    )
    outcome = run(many)
    assert (outcome.action, outcome.reasons) == (ValidateAction.ROUTE, codes)
    assert len(",".join(codes)) > MAX_VALUE_LENGTH
    events = [
        (record.getMessage().split(" ", 1)[0], event_fields(record))
        for record in caplog.records
    ]
    assert [f["reason"] for e, f in events if e == "validate.reason"] == list(codes)
    ((done,),) = [[f for e, f in events if e == "validate.done"]]
    assert done["count"] == len(codes)
    assert "reason" not in done

    # --- Lock proof: the finish waits while another holds the supplier's lock ---------
    locked = seed.invoice(27, phash=PHASH_OTHER ^ 0xFFFF, **_scan("INV-F-1"))
    finished: list[ValidateOutcome] = []
    holder = owner.connect()
    transaction = holder.begin()
    holder.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(CAST(:s AS text), 0))"),
        {"s": str(SUPPLIER_ALPHA)},
    )
    worker = threading.Thread(target=lambda: finished.append(run(locked)))
    worker.start()
    try:
        deadline = time.monotonic() + WAIT_SECONDS
        while not _waiting_for_advisory_lock(owner):
            assert time.monotonic() < deadline, "the finish never asked for the lock"
            time.sleep(0.02)
        # Claimed, blocked on the lock, nothing finished.
        assert worker.is_alive()
        assert finished == []
        assert status(locked) == "validating"
    finally:
        transaction.commit()
        holder.close()
    worker.join(WAIT_SECONDS)
    assert not worker.is_alive()
    assert [o.action for o in finished] == [ValidateAction.ADVANCE]
    assert status(locked) == "ready_to_post"
    with owner.begin() as connection:
        assert (
            connection.execute(select(func.count()).select_from(invoice)).scalar_one()
            == 10
        )
        # The master rows are shared by the session's other tests: leave none behind.
        connection.execute(
            delete(supplier_bank).where(supplier_bank.c.supplier_id == SUPPLIER_ALPHA)
        )
    owner.dispose()
