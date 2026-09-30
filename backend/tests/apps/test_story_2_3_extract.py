"""Story 2.3: the `extract` stage end to end, against a real PostgreSQL 18 (signed in
as the pipeline login) with a fake Document Intelligence behind the real adapter's
HTTP seam, a fake clock and sleep (no real waiting), and fake blob and queue clients.

One merged test (the 200-case cap, coding-style.md rule 20 exception): each matrix
row of the plan is a block of assertions, in order."""

import asyncio
import json
import logging
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from azure.core.credentials import AccessToken
from sqlalchemy import Engine, create_engine, func, select, text

from _pgp import make_test_key_pair
from apps._pipeline_fakes import (
    CORRELATION_ID,
    FakeImages,
    FakeMetrics,
    FakeQueue,
    invoice_id,
    metadata,
)
from conftest import PostgresServer
from invoicing.adapters.document_intelligence import (
    DocumentIntelligenceAnalyzer,
    HttpResponse,
)
from invoicing.adapters.postgres.extraction import PostgresExtractionRepository
from invoicing.adapters.postgres.invoices import PostgresInvoiceRepository
from invoicing.adapters.postgres.schema import (
    admin_item,
    di_operation,
    extraction_page,
    extraction_run,
    invoice,
    invoice_field,
    invoice_line,
)
from invoicing.adapters.postgres.suppliers import BankKeys
from invoicing.apps.pipeline.extract import (
    ExtractAction,
    ExtractDependencies,
    extract_handler,
)
from invoicing.apps.pipeline.quality import StageFailed
from invoicing.domain.status import InvoiceStatus
from invoicing.domain.suppliers import bank_fingerprint
from invoicing.domain.transitions import plan_transition
from invoicing.domain.upload import UploadContentType
from invoicing.ports.extraction import DefaultModelSelector
from invoicing.ports.invoices import NewInvoice
from invoicing.ports.messages import QueueMessage
from invoicing.ports.queue import QueueName

ENDPOINT = "https://babaloo-sea-lng-di-21.cognitiveservices.azure.com/"
HMAC_KEY = "synthetic-hmac-key-for-tests"
# Synthetic bank values, printed with spaces and hyphens (AD-11 normalises them).
BANK = {
    "BankAccountNumber": ("123-456 789", "123456789"),
    "IBAN": ("sg12 abcd 0000 1234 5678", "SG12ABCD000012345678"),
    "SWIFT": ("abcd sg sg", "ABCDSGSG"),
}
BANK_FIELD_IDS = {
    "BankAccountNumber": "payment[0].bank_account_number",
    "IBAN": "payment[0].iban",
    "SWIFT": "payment[0].swift",
}


def _region(page: int = 1) -> list[dict[str, Any]]:
    return [{"pageNumber": page, "polygon": [1.0, 2.0, 3.5, 2.0, 3.5, 4.0, 1.0, 4.0]}]


def _text(value: str, confidence: float) -> dict[str, Any]:
    return {
        "type": "string",
        "valueString": value,
        "content": value,
        "confidence": confidence,
        "boundingRegions": _region(),
    }


def _money(amount: str, confidence: float = 0.99) -> dict[str, Any]:
    return {
        "type": "currency",
        # DI reports USD for Singapore invoices: never used (AD-8).
        "valueCurrency": {"amount": float(amount), "currencyCode": "USD"},
        "content": f"${amount}",
        "confidence": confidence,
        "boundingRegions": _region(),
    }


def _number(value: str, confidence: float = 0.99) -> dict[str, Any]:
    return {"type": "number", "valueNumber": float(value), "confidence": confidence}


def _item(fields: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "valueObject": fields, "confidence": 0.9}


RESULT = {
    "apiVersion": "2024-11-30",
    "modelId": "prebuilt-invoice",
    "pages": [{"pageNumber": 1, "width": 1000, "height": 1400, "unit": "pixel"}],
    "documents": [
        {
            "docType": "invoice",
            "fields": {
                "VendorName": _text("Synthetic Supplies Pte Ltd", 0.995),
                "VendorTaxId": _text("201912345K", 0.97),
                "InvoiceId": _text("INV-0001", 0.99),
                "InvoiceDate": {
                    "type": "date",
                    "valueDate": "2026-09-28",
                    "content": "28 Sep 2026",
                    "confidence": 0.98,
                    "boundingRegions": _region(),
                },
                "PurchaseOrder": _text("PO-1001", 0.99),
                "SubTotal": _money("100.00"),
                "InvoiceTotal": _money("109.00"),
                "Items": {
                    "type": "array",
                    "valueArray": [
                        _item(
                            {
                                "ProductCode": _text("SKU-1", 0.99),
                                "Description": _text("Flour 25 kg", 0.9),
                                "Quantity": _number("4", 0.97),
                                "UnitPrice": _money("25.00", 0.99),
                                "Amount": _money("100.00", 0.98),
                            }
                        ),
                        # No product code: the line's confidence is 0 (AD-18).
                        _item({"Amount": _money("9.00")}),
                    ],
                },
                "PaymentDetails": {
                    "type": "array",
                    "valueArray": [
                        _item(
                            {name: _text(raw, 0.9) for name, (raw, _) in BANK.items()}
                        )
                    ],
                },
            },
        }
    ],
}


class Clock:
    """A fake clock that `sleep` moves on: nothing in the test waits for real."""

    def __init__(self) -> None:
        self.now = datetime.now(UTC)
        self.sleeps: list[float] = []

    def __call__(self) -> datetime:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += timedelta(seconds=seconds)


class FakeDocumentIntelligence:
    """The DI REST API: `analyze` and `polls` hold scripted answers, used in order;
    when empty, analyze accepts and a poll succeeds with RESULT."""

    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self.calls: list[tuple[str, datetime, str | None]] = []
        self.analyze: list[HttpResponse] = []
        self.polls: list[HttpResponse] = []
        self.operations = 0
        # Called on each analyze request, e.g. to read the page count mid-flight.
        self.on_post: Callable[[], None] | None = None

    def posts(self) -> int:
        return sum(1 for method, _, _ in self.calls if method == "POST")

    async def request(
        self, method: str, url: str, headers: Mapping[str, str], body: bytes | None
    ) -> HttpResponse:
        self.calls.append((method, self.clock(), headers.get("authorization")))
        if method == "POST":
            if self.on_post is not None:
                self.on_post()
            assert url == (
                f"{ENDPOINT}documentintelligence/documentModels/prebuilt-invoice"
                ":analyze?api-version=2024-11-30"
            )
            assert body is not None and "base64Source" in json.loads(body)
            if self.analyze:
                return self.analyze.pop(0)
            self.operations += 1
            location = (
                f"{ENDPOINT}documentintelligence/documentModels/prebuilt-invoice/"
                f"analyzeResults/op-{self.operations}?api-version=2024-11-30"
            )
            return HttpResponse(202, {"operation-location": location})
        if self.polls:
            return self.polls.pop(0)
        body_out = {"status": "succeeded", "analyzeResult": RESULT}
        return HttpResponse(200, {}, json.dumps(body_out).encode())


class FakeCredential:
    async def get_token(self, *scopes: str, **kwargs: Any) -> AccessToken:
        assert scopes == ("https://cognitiveservices.azure.com/.default",)
        return AccessToken("synthetic-token", 4_102_444_800)


def _message(for_invoice: UUID) -> str:
    return QueueMessage.first(
        for_invoice, CORRELATION_ID, datetime(2026, 9, 30, tzinfo=UTC)
    ).to_json()


def _rows(engine: Engine, table: Any, for_invoice: UUID) -> list[Any]:
    with engine.connect() as connection:
        return list(
            connection.execute(select(table).where(table.c.invoice_id == for_invoice))
        )


def _status(engine: Engine, for_invoice: UUID) -> tuple[str, bool]:
    """The invoice's status and whether its lease has ended."""
    with engine.connect() as connection:
        status, ended = connection.execute(
            select(
                invoice.c.status,
                invoice.c.claimed_until.is_(None)
                | (invoice.c.claimed_until <= func.now()),
            ).where(invoice.c.id == for_invoice)
        ).one()
    return status, ended


def _pages(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text(
                    "SELECT coalesce(sum(pages), 0) FROM intake.di_usage WHERE month ="
                    " date_trunc('month', timezone('UTC', now()))::date"
                )
            ).scalar_one()
        )


def test_story_2_3_extract_stage(
    pipeline_engine: Engine,
    postgres_server: PostgresServer,
    intake_database: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="invoicing")
    owner = create_engine(
        postgres_server.url(postgres_server.deployer, intake_database)
    )
    pair = make_test_key_pair()
    reads: list[int] = []

    async def bank_keys() -> BankKeys:
        reads.append(1)
        return BankKeys(public_key=pair.public_key, hmac_key=HMAC_KEY)

    clock = Clock()
    di = FakeDocumentIntelligence(clock)
    images, queue, metrics = FakeImages(), FakeQueue(), FakeMetrics()
    invoices = PostgresInvoiceRepository(pipeline_engine)
    handle = extract_handler(
        ExtractDependencies(
            images=images,
            invoices=invoices,
            extractions=PostgresExtractionRepository(
                pipeline_engine, invoices, bank_keys
            ),
            analyzer=DocumentIntelligenceAnalyzer(
                endpoint=ENDPOINT,
                credential=FakeCredential(),
                engine=pipeline_engine,
                page_cap=100,
                currency="SGD",
                transport=di,
                clock=clock,
                sleep=clock.sleep,
            ),
            models=DefaultModelSelector(),
            queue=queue,
            metrics=metrics,
        ),
        clock=clock,
    )

    def awaiting_extraction(
        n: int, content_type: UploadContentType = UploadContentType.JPEG
    ) -> UUID:
        created = invoice_id(n)
        stored = metadata(created).model_copy(update={"content_type": content_type})
        images.put(stored)
        asyncio.run(
            invoices.insert_if_absent(NewInvoice(stored, CORRELATION_ID, "test"))
        )
        asyncio.run(
            invoices.transition(
                plan_transition(
                    created,
                    InvoiceStatus.RECEIVED,
                    InvoiceStatus.AWAITING_EXTRACTION,
                    "test",
                )
            )
        )
        return created

    def run(for_invoice: UUID) -> Any:
        return asyncio.run(handle(_message(for_invoice)))

    # --- Happy path, with the throttle: DI was last called 0.5 s ago --------------------
    first = awaiting_extraction(1)
    with pipeline_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO intake.di_usage (month, pages, last_call_at) VALUES"
                " (date_trunc('month', timezone('UTC', now()))::date, 0, :at)"
            ),
            {"at": clock() - timedelta(seconds=0.5)},
        )
    di.polls.append(
        HttpResponse(
            200, {"retry-after": "1"}, json.dumps({"status": "running"}).encode()
        )
    )
    outcome = run(first)
    assert outcome.action is ExtractAction.ADVANCE
    # AD-8: the analyze call waited out the rest of the 2 s, and every request (polls
    # included) is at least 2 s after the one before, with a managed-identity token.
    assert clock.sleeps[0] == pytest.approx(1.5)
    assert [method for method, _, _ in di.calls] == ["POST", "GET", "GET"]
    gaps = [b[1] - a[1] for a, b in zip(di.calls, di.calls[1:], strict=False)]
    assert all(gap >= timedelta(seconds=2) for gap in gaps)
    assert {auth for _, _, auth in di.calls} == {"Bearer synthetic-token"}
    assert _status(pipeline_engine, first) == ("awaiting_validation", True)
    assert [(q, m.invoice_id) for q, m, _ in queue.sent] == [
        (QueueName.VALIDATE, first)
    ]
    (run_row,) = _rows(pipeline_engine, extraction_run, first)
    assert (run_row.model_id, run_row.api_version, run_row.pages) == (
        "prebuilt-invoice",
        "2024-11-30",
        1,
    )
    assert len(_rows(pipeline_engine, di_operation, first)) == 1
    # Story 2.9: the page's size is kept for the admin boxes.
    with pipeline_engine.connect() as connection:
        sizes = connection.execute(
            select(
                extraction_page.c.page,
                extraction_page.c.width,
                extraction_page.c.height,
                extraction_page.c.unit,
            ).where(extraction_page.c.run_id == run_row.run_id)
        ).all()
    assert [tuple(size) for size in sizes] == [(1, 1000.0, 1400.0, "pixel")]
    fields = {row.field_id: row for row in _rows(pipeline_engine, invoice_field, first)}
    # AD-18 field ids: snake_case, InvoiceId -> invoice_number, payment[n].<bank field>.
    assert set(fields) == {
        "vendor_name",
        "vendor_tax_id",
        "invoice_number",
        "invoice_date",
        "purchase_order",
        "sub_total",
        "invoice_total",
        "payment[0].bank_account_number",
        "payment[0].iban",
        "payment[0].swift",
    }
    assert {row.run_id for row in fields.values()} == {run_row.run_id}
    assert {row.source for row in fields.values()} == {"di"}
    total = fields["invoice_total"]
    assert (total.value_number, total.currency) == (Decimal("109.00"), "SGD")
    assert fields["invoice_number"].value_text == "INV-0001"
    assert fields["invoice_date"].value_date == date(2026, 9, 28)
    vendor = fields["vendor_name"]
    assert (vendor.confidence, vendor.page) == (0.995, 1)
    assert vendor.polygon == [1.0, 2.0, 3.5, 2.0, 3.5, 4.0, 1.0, 4.0]
    lines = sorted(_rows(pipeline_engine, invoice_line, first), key=lambda r: r.line_no)
    assert [(line.line_no, line.confidence) for line in lines] == [(1, 0.97), (2, 0.0)]
    assert (lines[0].product_code, lines[0].quantity, lines[0].unit_price) == (
        "SKU-1",
        Decimal(4),
        Decimal("25.00"),
    )
    # AD-11: bank fields hold ciphertext of the normalised value and its HMAC only.
    with owner.connect() as connection:
        for di_name, (_, normalised) in BANK.items():
            row = fields[BANK_FIELD_IDS[di_name]]
            assert (row.value_text, row.value_number, row.value_date) == (
                None,
                None,
                None,
            )
            assert row.bank_fingerprint == bank_fingerprint(HMAC_KEY, normalised)
            decrypted = connection.execute(
                text("SELECT pgp_pub_decrypt(:c, dearmor(:k))"),
                {"c": row.bank_ciphertext, "k": pair.private_key},
            ).scalar_one()
            assert decrypted == normalised
        # No plaintext bank value in any row of any intake table, nor in any log.
        tables = connection.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'intake'")
        ).scalars()
        dump = " ".join(
            str(connection.execute(text(f"SELECT t::text FROM intake.{name} t")).all())  # noqa: S608  # catalogue names
            for name in tables
        ).upper()
    logged = " ".join(str(record.__dict__) for record in caplog.records).upper()
    for raw, normalised in BANK.values():
        for value in (raw.upper(), normalised):
            assert value not in dump and value not in logged
    assert _pages(pipeline_engine) == 1
    assert metrics.emitted[-1] == ("di_pages_used_pct", 1.0, {})
    # The ar-03 log alert parses this event's message (AD-17).
    usage = [
        r.getMessage()
        for r in caplog.records
        if r.getMessage().startswith("extract.di_usage ")
    ]
    assert usage[-1].endswith(" pages_used_pct=1.0")

    # --- Claim lost: already awaiting_validation; q-validate queued again (AD-2) -------
    queue.sent.clear()
    assert run(first).action is ExtractAction.ACK
    assert [q for q, _, _ in queue.sent] == [QueueName.VALIDATE]

    # --- Retry after a saved run: reused, DI not called, no pages counted (AD-3) --------
    with owner.begin() as connection:
        connection.execute(
            text(
                "UPDATE intake.invoice SET status = 'extracting',"
                " claimed_until = now() - interval '1 minute' WHERE id = :id"
            ),
            {"id": first},
        )
    calls = len(di.calls)
    assert run(first).action is ExtractAction.REUSE
    assert len(di.calls) == calls and _pages(pipeline_engine) == 1
    assert len(_rows(pipeline_engine, extraction_run, first)) == 1
    assert _status(pipeline_engine, first)[0] == "awaiting_validation"

    # --- Re-extract: re-entered awaiting_extraction after the run: DI called again ------
    with owner.begin() as connection:
        connection.execute(
            text(
                "UPDATE intake.invoice SET status = 'awaiting_extraction' WHERE id = :id"
            ),
            {"id": first},
        )
        connection.execute(
            text(
                "INSERT INTO intake.status_history VALUES (gen_random_uuid(), :id,"
                " 'in_admin_queue', 'awaiting_extraction', 'staff-api:test', now())"
            ),
            {"id": first},
        )
    assert run(first).action is ExtractAction.ADVANCE
    assert di.posts() == 2 and _pages(pipeline_engine) == 2
    assert len(_rows(pipeline_engine, extraction_run, first)) == 2
    # Keys come from Key Vault through the loader; each run with bank values asks.
    assert len(reads) == 2

    # --- 429 on a poll: the same message after Retry-After, lease ended (AD-7) ----------
    second = awaiting_extraction(2)
    di.polls.append(HttpResponse(429, {"retry-after": "7"}))
    queue.sent.clear()
    outcome = run(second)
    assert (outcome.action, outcome.delay_seconds) == (ExtractAction.RETRY, 7)
    ((sent_queue, sent, delay),) = queue.sent
    assert (sent_queue, delay) == (QueueName.EXTRACT, 7)
    assert sent.to_json() == _message(second)
    assert _status(pipeline_engine, second) == ("extracting", True)
    assert di.posts() == 3 and _pages(pipeline_engine) == 3

    # --- The retry resumes polling the saved Operation-Location -------------------------
    assert run(second).action is ExtractAction.ADVANCE
    assert di.posts() == 3 and _pages(pipeline_engine) == 3
    assert _status(pipeline_engine, second)[0] == "awaiting_validation"

    # --- Other failures: raised with a code for a host retry, lease ended ---------------
    third = awaiting_extraction(3)
    di.polls.append(
        HttpResponse(500, {}, b'{"error": {"code": "InternalServerError"}}')
    )
    with pytest.raises(StageFailed, match="POLL_HTTP_500"):
        run(third)
    assert _status(pipeline_engine, third) == ("extracting", True)
    # A saved operation DI no longer knows (404) is forgotten, so the next retry
    # analyses afresh instead of polling it for ever.
    assert len(_rows(pipeline_engine, di_operation, third)) == 1
    di.polls.append(HttpResponse(404, {}))
    with pytest.raises(StageFailed, match="OPERATION_NOT_FOUND"):
        run(third)
    assert _rows(pipeline_engine, di_operation, third) == []
    posts = di.posts()
    assert run(third).action is ExtractAction.ADVANCE
    assert di.posts() == posts + 1

    # --- 429 on the analyze call: its reserved pages are given back ---------------------
    sixth = awaiting_extraction(6)
    di.analyze.append(HttpResponse(429, {"retry-after": "5"}))
    pages = _pages(pipeline_engine)
    assert run(sixth).action is ExtractAction.RETRY
    assert _pages(pipeline_engine) == pages
    assert _rows(pipeline_engine, di_operation, sixth) == []

    # --- A PDF: 2 pages reserved, settled at the 3 DI returned with the run (AD-8) ------
    # Its result also has a non-array PaymentDetails (never stored as one plaintext
    # field, AD-11) and a SubTotal whose amount doesn't parse (confidence 0, AD-18).
    # Story 2.9: of its page sizes, a repeated pageNumber and an unknown unit are
    # dropped; the run still saves.
    seventh = awaiting_extraction(7, UploadContentType.PDF)
    fields_7 = dict(RESULT["documents"][0]["fields"])
    fields_7["PaymentDetails"] = _text("SG12 ABCD 0000 1234 5678", 0.9)
    fields_7["SubTotal"] = {"type": "currency", "valueCurrency": {}, "confidence": 0.9}
    result_7 = {
        **RESULT,
        "pages": [
            {"pageNumber": 1, "width": 8.5, "height": 11, "unit": "inch"},
            {"pageNumber": 1, "width": 9, "height": 12, "unit": "inch"},
            {"pageNumber": 2, "width": 0, "height": 11, "unit": "furlong"},
        ],
        "documents": [{"docType": "invoice", "fields": fields_7}],
    }
    di.polls.append(
        HttpResponse(
            200,
            {},
            json.dumps({"status": "succeeded", "analyzeResult": result_7}).encode(),
        )
    )
    pages = _pages(pipeline_engine)
    during: list[int] = []
    di.on_post = lambda: during.append(_pages(pipeline_engine))
    assert run(seventh).action is ExtractAction.ADVANCE
    di.on_post = None
    assert during == [pages + 2]
    assert _pages(pipeline_engine) == pages + 3
    (run_7,) = _rows(pipeline_engine, extraction_run, seventh)
    with pipeline_engine.connect() as connection:
        sizes = connection.execute(
            select(
                extraction_page.c.page,
                extraction_page.c.width,
                extraction_page.c.height,
                extraction_page.c.unit,
            ).where(extraction_page.c.run_id == run_7.run_id)
        ).all()
    assert [tuple(size) for size in sizes] == [(1, 8.5, 11.0, "inch")]
    fields = {r.field_id: r for r in _rows(pipeline_engine, invoice_field, seventh)}
    assert "payment_details" not in fields
    assert (fields["sub_total"].value_number, fields["sub_total"].confidence) == (
        None,
        0.0,
    )

    # --- DI quota error: reservation kept, EXTRACTION_QUOTA -----------------------------
    fourth = awaiting_extraction(4)
    di.analyze.append(
        HttpResponse(
            403,
            {},
            b'{"error": {"code": "403", "message": "Out of call volume quota for F0"}}',
        )
    )
    pages = _pages(pipeline_engine)
    outcome = run(fourth)
    assert (outcome.action, outcome.reason) == (ExtractAction.ROUTE, "EXTRACTION_QUOTA")
    assert _pages(pipeline_engine) == pages + 1
    assert [r.reason for r in _rows(pipeline_engine, admin_item, fourth)] == [
        "EXTRACTION_QUOTA"
    ]

    # --- Page cap reached: routed without calling DI ------------------------------------
    fifth = awaiting_extraction(5)
    with owner.begin() as connection:
        connection.execute(text("UPDATE intake.di_usage SET pages = 100"))
    calls = len(di.calls)
    caplog.clear()
    outcome = run(fifth)
    assert (outcome.action, outcome.reason) == (ExtractAction.ROUTE, "EXTRACTION_QUOTA")
    assert len(di.calls) == calls
    assert _status(pipeline_engine, fifth)[0] == "in_admin_queue"
    assert metrics.emitted[-1] == ("di_pages_used_pct", 100.0, {})
    usage = [
        r.getMessage()
        for r in caplog.records
        if r.getMessage().startswith("extract.di_usage ")
    ]
    assert usage[-1].endswith(" pages_used_pct=100.0")
    owner.dispose()
