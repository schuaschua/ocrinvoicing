"""Story 3.2: the `post` stage, against a real PostgreSQL 18 signed in as the pipeline
login, through the real accounts adapter (`adapters/accounts_xml/client.py`) with a
fake HTTP transport, a fake credential and a fake queue; then a clean upload end to
end, from `q-quality` to `posted`, with accounts-sim's own endpoint in-process behind
the transport. Nothing reaches Azure or the network (coding-style.md rule 23).
Synthetic data only (security.md rule 1).

Two merged tests (the 200-case cap, coding-style.md rule 20 exception): each plan
matrix row is a block of assertions, in order."""

import asyncio
import json
import logging
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import aiohttp
import azure.functions as func
import pytest
from azure.core.credentials import AccessToken
from azure.core.exceptions import ClientAuthenticationError
from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy import func as sql_func

from _documents import exif, jpeg, page
from apps._pipeline_fakes import (
    CORRELATION_ID,
    FakeImages,
    FakeMetrics,
    FakeQueue,
    FakeReminders,
    FakeUploadKeys,
    metadata,
)
from apps._validation_seed import Seeder, header, message, one, seed_master
from apps.test_story_2_3_extract import _item, _money, _number, _text
from conftest import PostgresServer, login_engine
from contracts.purchasing_contract import CEMENT, SUPPLIER_ALPHA
from invoicing.adapters.accounts_xml.client import AccountsXmlClient
from invoicing.adapters.accounts_xml.contract import (
    AccountsInvoiceLine,
    parse_invoice,
    result_xml,
)
from invoicing.adapters.document_intelligence import HttpResponse
from invoicing.adapters.documents import load_quality_thresholds
from invoicing.adapters.postgres.extraction import PostgresExtractionRepository
from invoicing.adapters.postgres.invoices import PostgresInvoiceRepository
from invoicing.adapters.postgres.posting import PostgresPostingRepository
from invoicing.adapters.postgres.schema import admin_item, invoice, status_history
from invoicing.adapters.postgres.sim_accounts import PostgresSimAccounts
from invoicing.adapters.postgres.suppliers import PostgresSupplierReader
from invoicing.adapters.postgres.validation import PostgresValidationRepository
from invoicing.adapters.purchasing_factory import purchasing_port
from invoicing.apps.accounts_sim.invoices import PRINCIPAL_ID_HEADER, invoices_endpoint
from invoicing.apps.pipeline.extract import ExtractDependencies, extract_handler
from invoicing.apps.pipeline.post import PostAction, PostDependencies, post_handler
from invoicing.apps.pipeline.quality import StageFailed, quality_handler
from invoicing.apps.pipeline.sweeper import Sweeper
from invoicing.apps.pipeline.validate import ValidateDependencies, validate_handler
from invoicing.domain.extraction import map_invoice, page_sizes
from invoicing.domain.posting import POST_BACKOFF
from invoicing.domain.status import InvoiceStatus
from invoicing.domain.transitions import plan_transition
from invoicing.ports.extraction import (
    Analysis,
    AnalyzeRequest,
    DefaultModelSelector,
    OperationSaver,
    PageReservation,
)
from invoicing.ports.messages import QueueMessage
from invoicing.ports.queue import QueueName

BASE_URL = "https://babaloo-sea-lng-func-04.azurewebsites.net/api"
AUDIENCE = "api://30000000-0000-0000-0000-0000000000b1"
TOKEN = "synthetic-accounts-token"  # noqa: S105  # a fake token, never a secret
# conftest APP_ONLY_SETTINGS: this environment's pipeline identity (accounts-sim's one
# caller, whose principal id built-in auth would pass on).
PIPELINE = UUID("10000000-0000-0000-0000-000000000003")


class FakeCredential:
    """A managed identity that records every scope it is asked for."""

    def __init__(self) -> None:
        self.scopes: list[tuple[str, ...]] = []
        # Raised instead of a token while set.
        self.failing: Exception | None = None

    async def get_token(self, *scopes: str, **kwargs: Any) -> AccessToken:
        self.scopes.append(scopes)
        if self.failing is not None:
            raise self.failing
        return AccessToken(TOKEN, 4_102_444_800)


class ScriptedAccounts:
    """The accounts system behind the adapter's HTTP seam: answers each call with the
    next scripted response (a response, or an exception to raise), else stores it."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, str], bytes]] = []
        self.script: list[HttpResponse | Exception] = []

    async def request(
        self, method: str, url: str, headers: Mapping[str, str], body: bytes | None
    ) -> HttpResponse:
        self.calls.append((method, url, dict(headers), body or b""))
        if self.script:
            answer = self.script.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer
        return HttpResponse(201, {}, result_xml(f"SIM-{len(self.calls):06d}"))


def _error(status: int, code: str = "SIMULATED_FAILURE") -> HttpResponse:
    return HttpResponse(status, {}, json.dumps({"code": code}).encode())


def _row(engine: Engine, for_invoice: UUID) -> Any:
    return one(engine, select(invoice).where(invoice.c.id == for_invoice))


def _db_now(engine: Engine) -> datetime:
    return one(engine, select(sql_func.now()))[0]


def test_story_3_2_post_stage_posts_backs_off_and_routes(
    pipeline_engine: Engine,
    postgres_server: PostgresServer,
    intake_database: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="invoicing")
    owner = create_engine(
        postgres_server.url(postgres_server.deployer, intake_database)
    )
    seed_master(owner)
    seed = Seeder(owner)
    queue = FakeQueue()
    accounts = ScriptedAccounts()
    credential = FakeCredential()
    invoices = PostgresInvoiceRepository(pipeline_engine)
    handle = post_handler(
        PostDependencies(
            invoices=invoices,
            postings=PostgresPostingRepository(pipeline_engine, invoices),
            validations=PostgresValidationRepository(pipeline_engine, invoices),
            accounts=AccountsXmlClient(
                base_url=BASE_URL,
                audience=AUDIENCE,
                credential=credential,  # type: ignore[arg-type]  # the fake's shape
                transport=accounts,
            ),
            queue=queue,
            currency="SGD",
        )
    )

    def owner_sql(statement: str, for_invoice: UUID) -> None:
        with owner.begin() as connection:
            connection.execute(text(statement), {"id": for_invoice})

    def ready(n: int, price: str = "10.00", status: str = "ready_to_post") -> UUID:
        """A validated invoice: 10 x `price` of cement on PO-45012, 9 % tax."""
        created = seed.invoice(
            n,
            fields={
                **header("100.00"),
                "total_tax": (Decimal("9.00"), 0.99),
            },
            lines=[("ALP-CEM-50", "10", price)],
            status=status,
        )
        owner_sql(
            "UPDATE intake.invoice SET po_number = 'PO-45012' WHERE id = :id", created
        )
        with owner.begin() as connection:
            connection.execute(
                text(
                    "UPDATE intake.invoice_line SET description = 'Synthetic cement',"
                    " material_id = :m WHERE invoice_id = :id"
                ),
                {"id": created, "m": CEMENT},
            )
        return created

    def run(for_invoice: UUID, attempt: int = 1) -> Any:
        body = QueueMessage(
            invoice_id=for_invoice,
            correlation_id=CORRELATION_ID,
            first_enqueued_at=datetime(2026, 9, 30, tzinfo=UTC),
            attempt=attempt,
        ).to_json()
        return asyncio.run(handle(body))

    def due_now(for_invoice: UUID) -> None:
        """The backoff has run out (time moved on)."""
        owner_sql(
            "UPDATE intake.invoice SET next_attempt_at = now() - interval '1 second'"
            " WHERE id = :id",
            for_invoice,
        )

    # --- Post: claimed, the current values posted as XML, ref saved, then posted ------
    first = ready(1)
    outcome = run(first)
    assert outcome.action is PostAction.POSTED
    row = _row(pipeline_engine, first)
    assert (row.status, row.accounts_ref, row.claimed_until) == (
        "posted",
        "SIM-000001",
        None,
    )
    posted_at = one(
        pipeline_engine,
        select(status_history.c.at).where(
            status_history.c.invoice_id == first, status_history.c.to_status == "posted"
        ),
    )[0]
    assert row.posted_at == posted_at
    ((method, url, headers, body),) = accounts.calls
    assert (method, url) == ("POST", f"{BASE_URL}/invoices")
    assert headers["authorization"] == f"Bearer {TOKEN}"
    assert credential.scopes == [(f"{AUDIENCE}/.default",)]
    sent = parse_invoice(body)
    assert (sent.invoice_id, sent.supplier_id, sent.po_number, sent.currency) == (
        first,
        SUPPLIER_ALPHA,
        "PO-45012",
        "SGD",
    )
    assert (sent.invoice_number, sent.invoice_date) == ("INV-A-1", date(2026, 9, 20))
    assert (sent.sub_total, sent.total_tax, sent.invoice_total) == (
        Decimal("100.00"),
        Decimal("9.00"),
        Decimal("109.00"),
    )
    (line,) = sent.lines
    assert line == AccountsInvoiceLine(
        line_no=1,
        material_id=CEMENT,
        description="Synthetic cement",
        quantity=Decimal("10.000"),
        unit_price=Decimal("10.00"),
        amount=Decimal("100.00"),
    )
    assert queue.sent == []
    # Redelivered after posting: only acknowledged, never posted twice (AD-2).
    assert run(first).action is PostAction.ACK
    assert len(accounts.calls) == 1

    # --- Early message: back on q-post for the rest of the wait, nothing claimed ------
    early = ready(2)
    owner_sql(
        "UPDATE intake.invoice SET next_attempt_at = now() + interval '10 minutes'"
        " WHERE id = :id",
        early,
    )
    history = one(
        pipeline_engine,
        select(sql_func.count()).where(status_history.c.invoice_id == early),
    )[0]
    outcome = run(early, attempt=3)
    assert outcome.action is PostAction.EARLY
    ((queued, again, delay),) = queue.sent
    assert (queued, again.invoice_id, again.attempt) == (QueueName.POST, early, 3)
    assert 590 <= delay <= 600
    assert _row(pipeline_engine, early).status == "ready_to_post"
    assert (
        one(
            pipeline_engine,
            select(sql_func.count()).where(status_history.c.invoice_id == early),
        )[0]
        == history
    )
    assert len(accounts.calls) == 1

    # --- Saved ref: a crash after saving it; the retry never calls again --------------
    saved = ready(3, status="posting")
    owner_sql(
        "UPDATE intake.invoice SET accounts_ref = 'SIM-777777',"
        " claimed_until = now() - interval '1 minute' WHERE id = :id",
        saved,
    )
    assert run(saved).action is PostAction.REUSE
    assert (_row(pipeline_engine, saved).status, _row(pipeline_engine, saved).accounts_ref) == ("posted", "SIM-777777")  # fmt: skip
    assert len(accounts.calls) == 1

    # --- Failures 1-4 back off 1/5/15/60 min; a lost message is swept; the 5th routes -
    queue.sent.clear()
    failing = ready(4)
    accounts.script = [
        _error(503),
        _error(400, "XML_INVALID"),
        TimeoutError(),
        _error(429),
        HttpResponse(502, {}, b"<html>Bad gateway: 109.00</html>"),
    ]
    codes = []
    for failures, wait in enumerate(POST_BACKOFF, start=1):
        # Always attempt 1 on the message: the count is post_failures (AD-3).
        outcome = run(failing, attempt=1)
        assert outcome.action is PostAction.RETRY
        codes.append((outcome.error.status, outcome.error.code))
        row = _row(pipeline_engine, failing)
        assert (row.status, row.post_failures, row.claimed_until) == (
            "ready_to_post",
            failures,
            None,
        )
        ahead = row.next_attempt_at - _db_now(pipeline_engine)
        assert wait - timedelta(seconds=5) < ahead <= wait
        (queued, again, delay) = queue.sent.pop()
        assert (queued, again.invoice_id, again.attempt, delay) == (
            QueueName.POST,
            failing,
            2,
            int(wait.total_seconds()),
        )
        if failures == 2:
            # The delayed message is lost: once due and stale, the sweeper sends
            # another, and the count is kept.
            owner_sql(
                "UPDATE intake.invoice SET status_changed_at = now()"
                " - interval '2 hours' WHERE id = :id",
                failing,
            )
            due_now(failing)
            sweep_queue = FakeQueue()
            started = _db_now(pipeline_engine) - timedelta(hours=2)
            result = asyncio.run(
                Sweeper(
                    PostgresInvoiceRepository(
                        pipeline_engine, database_started_at=started
                    ),
                    FakeUploadKeys(),
                    FakeImages(),
                    sweep_queue,
                    FakeMetrics(),
                ).run()
            )
            assert result.requeued == 1
            assert [(q, m.invoice_id) for q, m, _ in sweep_queue.sent] == [
                (QueueName.POST, failing)
            ]
            assert _row(pipeline_engine, failing).post_failures == 2
        due_now(failing)
    assert codes == [
        (503, "SIMULATED_FAILURE"),
        (400, "XML_INVALID"),
        (None, "TIMEOUT"),
        (429, "SIMULATED_FAILURE"),
    ]
    outcome = run(failing, attempt=1)
    assert outcome.action is PostAction.ROUTE
    assert queue.sent == []
    row = _row(pipeline_engine, failing)
    assert (row.status, row.post_failures, row.accounts_ref) == (
        "in_admin_queue",
        5,
        None,
    )
    with pipeline_engine.connect() as connection:
        (item,) = connection.execute(
            select(admin_item.c.reason, admin_item.c.detail).where(
                admin_item.c.invoice_id == failing
            )
        ).all()
    # The error's status and code only: the answer's body is never kept.
    assert tuple(item) == ("ACCOUNTS_API_ERROR", {"status": 502, "code": "HTTP_502"})
    assert len(accounts.calls) == 1 + 5

    # --- Builder refuses: a price the wire can't carry is an accounts error -----------
    refused = ready(5, price="7.805")
    outcome = run(refused)
    assert (outcome.action, outcome.error.status, outcome.error.code) == (
        PostAction.RETRY,
        None,
        "XML_INVALID",
    )
    assert _row(pipeline_engine, refused).post_failures == 1
    assert len(accounts.calls) == 6

    # --- No tax total and no line description: both optional, so it posts ------------
    untaxed = ready(6)
    owner_sql(
        "DELETE FROM intake.invoice_field WHERE invoice_id = :id"
        " AND field_id = 'total_tax'",
        untaxed,
    )
    owner_sql(
        "UPDATE intake.invoice_line SET description = NULL WHERE invoice_id = :id",
        untaxed,
    )
    assert run(untaxed).action is PostAction.POSTED
    sent = parse_invoice(accounts.calls[-1][3])
    assert (sent.invoice_id, sent.total_tax, sent.lines[0].description) == (
        untaxed,
        None,
        None,
    )
    assert b"total_tax" not in accounts.calls[-1][3]

    # --- No extraction run: raised with a code, lease ended, nothing posted -----------
    calls = len(accounts.calls)
    no_run = seed.invoice(7, fields={}, lines=[], status="ready_to_post", run=False)
    with pytest.raises(StageFailed, match="NO_EXTRACTION_RUN"):
        run(no_run)
    # Released like every stage's claim (AD-3): the lease is over, so the host's retry
    # reclaims it at once, and after 5 tries the poison trigger routes it.
    ended = one(
        pipeline_engine,
        select(invoice.c.status, invoice.c.claimed_until <= sql_func.now()).where(
            invoice.c.id == no_run
        ),
    )
    assert tuple(ended) == ("posting", True)
    assert len(accounts.calls) == calls

    # --- Unreachable, no token, a bad answer, a free-text error code: all back off ----
    def fails_once(n: int, expected: tuple[int | None, str]) -> UUID:
        created = ready(n)
        outcome = run(created)
        assert (outcome.action, (outcome.error.status, outcome.error.code)) == (
            PostAction.RETRY,
            expected,
        )
        row = _row(pipeline_engine, created)
        assert (row.status, row.post_failures, row.accounts_ref) == (
            "ready_to_post",
            1,
            None,
        )
        return created

    accounts.script = [aiohttp.ClientConnectionError()]
    fails_once(8, (None, "UNREACHABLE"))
    calls = len(accounts.calls)
    credential.failing = ClientAuthenticationError("synthetic: no token")
    fails_once(9, (None, "UNREACHABLE"))
    credential.failing = None
    assert len(accounts.calls) == calls
    accounts.script = [
        HttpResponse(201, {}, result_xml("not a ref!")),
        HttpResponse(201, {}, b"<other><accounts_ref>SIM-1</accounts_ref></other>"),
        _error(422, "total 109.00 rejected"),
    ]
    fails_once(10, (201, "BAD_RESULT"))
    fails_once(11, (201, "BAD_RESULT"))
    fails_once(12, (422, "HTTP_422"))
    # A namespaced answer is read by local name.
    accounts.script = [
        HttpResponse(
            201,
            {},
            b'<r:result xmlns:r="urn:accounts"><r:accounts_ref>SIM-9'
            b"</r:accounts_ref></r:result>",
        )
    ]
    namespaced = ready(13)
    assert run(namespaced).action is PostAction.POSTED
    assert _row(pipeline_engine, namespaced).accounts_ref == "SIM-9"

    # --- Reset: entering ready_to_post from in_admin_queue or validating --------------
    asyncio.run(
        invoices.transition(
            plan_transition(
                failing,
                InvoiceStatus.IN_ADMIN_QUEUE,
                InvoiceStatus.READY_TO_POST,
                "staff:approve",
            )
        )
    )
    owner_sql("UPDATE intake.invoice SET status = 'validating' WHERE id = :id", refused)
    asyncio.run(
        invoices.transition(
            plan_transition(
                refused,
                InvoiceStatus.VALIDATING,
                InvoiceStatus.READY_TO_POST,
                "pipeline:validate",
            )
        )
    )
    for reset in (failing, refused):
        row = _row(pipeline_engine, reset)
        assert (row.status, row.post_failures, row.next_attempt_at) == (
            "ready_to_post",
            0,
            None,
        )

    # --- No field value, token or answer body reaches a log (security.md rule 31) -----
    # Logging's own timing fields are left out: a timestamp such as relativeCreated
    # 40947.805576 contains "7.805" by chance (Jenkins, 2026-10-02).
    timing = ("created", "msecs", "relativeCreated")
    logged = caplog.text + " ".join(
        str({key: value for key, value in vars(r).items() if key not in timing})
        for r in caplog.records
    )
    for value in ("INV-A-1", "Synthetic", "109.00", "7.805", TOKEN, "Bad gateway"):
        assert value not in logged, value
    owner.dispose()


class FakeAnalyzer:
    """Document Intelligence's answer for one clean invoice, mapped the real way."""

    def __init__(self, fields: Mapping[str, Any]) -> None:
        self.fields = fields

    async def analyze(
        self, request: AnalyzeRequest, save_operation: OperationSaver
    ) -> Analysis:
        pages = [{"pageNumber": 1, "width": 1000, "height": 1400, "unit": "pixel"}]
        return Analysis(
            model_id="prebuilt-invoice",
            api_version="2024-11-30",
            pages=1,
            invoice=map_invoice(self.fields, "SGD"),
            reservation=PageReservation(date(2026, 9, 1), 1),
            pages_info=page_sizes(pages),
        )

    async def pages_used_pct(self) -> float:
        return 1.0


class InProcessAccountsSim:
    """accounts-sim's `POST /api/invoices` behind the adapter's HTTP seam, as built-in
    auth would call it after accepting the pipeline's token."""

    def __init__(self, sim: Engine) -> None:
        self.urls: list[str] = []
        self.endpoint = invoices_endpoint(
            PostgresSimAccounts(sim),
            pipeline_principal_id=PIPELINE,
            platform_auth_trusted=True,
        )

    async def request(
        self, method: str, url: str, headers: Mapping[str, str], body: bytes | None
    ) -> HttpResponse:
        self.urls.append(url)
        assert headers["authorization"] == f"Bearer {TOKEN}"
        response = await self.endpoint(
            func.HttpRequest(
                method=method,
                url="/api/invoices",
                headers={PRINCIPAL_ID_HEADER: str(PIPELINE)},
                body=body or b"",
            )
        )
        return HttpResponse(
            response.status_code, dict(response.headers), response.get_body()
        )


def test_story_3_2_clean_upload_posts_end_to_end(
    pipeline_engine: Engine,
    postgres_server: PostgresServer,
    purchasing_seeded: str,
) -> None:
    owner = create_engine(
        postgres_server.url(postgres_server.deployer, purchasing_seeded)
    )
    seed_master(owner)
    with owner.begin() as connection:
        connection.execute(text("TRUNCATE sim_accounts.invoice"))
        connection.execute(text("UPDATE sim_accounts.failure_mode SET fail_next = 0"))
    sim = login_engine(postgres_server, postgres_server.accounts_sim, purchasing_seeded)
    uploaded = UUID("0192f0c1-7a2b-7c3d-8e4f-000000003201")
    images = FakeImages()
    # A sharp photo taken a day after PO-45012's last goods receipt (AD-19).
    images.put(
        metadata(uploaded).model_copy(update={"supplier_id": SUPPLIER_ALPHA}),
        jpeg(page(), exif(taken="2026:09:16 10:00:00", offset="+08:00")),
    )
    queue = FakeQueue()
    invoices = PostgresInvoiceRepository(pipeline_engine)
    validations = PostgresValidationRepository(pipeline_engine, invoices)
    accounts_sim = InProcessAccountsSim(sim)

    async def no_bank_keys() -> Any:
        raise AssertionError("a clean invoice has no bank value to encrypt")

    # 100 bags of cement at the PO's 7.80, all read confidently.
    analyzer = FakeAnalyzer(
        {
            "VendorName": _text("Synthetic Alpha Building Supplies Pte. Ltd.", 0.995),
            "VendorTaxId": _text("2019-12345-k", 0.99),
            "InvoiceId": _text("INV-E2E-1", 0.99),
            "InvoiceDate": {"type": "date", "valueDate": "2026-09-20", "confidence": 0.99},
            "PurchaseOrder": _text("PO-45012", 0.99),
            "SubTotal": _money("780.00"),
            "TotalTax": _money("70.20"),
            "InvoiceTotal": _money("850.20"),
            "Items": {
                "type": "array",
                "valueArray": [
                    _item(
                        {
                            "ProductCode": _text("ALP-CEM-50", 0.99),
                            "Description": _text("Portland cement 50 kg", 0.99),
                            "Quantity": _number("100", 0.99),
                            "UnitPrice": _money("7.80"),
                            "Amount": _money("780.00"),
                        }
                    )
                ],
            },
        }
    )  # fmt: skip
    handlers: dict[QueueName, Callable[[str], Any]] = {
        QueueName.QUALITY: quality_handler(
            images, invoices, queue, load_quality_thresholds()
        ),
        QueueName.EXTRACT: extract_handler(
            ExtractDependencies(
                images=images,
                invoices=invoices,
                extractions=PostgresExtractionRepository(
                    pipeline_engine, invoices, no_bank_keys
                ),
                analyzer=analyzer,
                models=DefaultModelSelector(),
                queue=queue,
                metrics=FakeMetrics(),
            )
        ),
        QueueName.VALIDATE: validate_handler(
            ValidateDependencies(
                invoices=invoices,
                validations=validations,
                purchasing=purchasing_port("sim", pipeline_engine),
                suppliers=PostgresSupplierReader(pipeline_engine),
                queue=queue,
                reminders=FakeReminders(),
            )
        ),
        QueueName.POST: post_handler(
            PostDependencies(
                invoices=invoices,
                postings=PostgresPostingRepository(pipeline_engine, invoices),
                validations=validations,
                accounts=AccountsXmlClient(
                    base_url=BASE_URL,
                    audience=AUDIENCE,
                    credential=FakeCredential(),  # type: ignore[arg-type]  # the fake's shape
                    transport=accounts_sim,
                ),
                queue=queue,
                currency="SGD",
            )
        ),
    }
    try:
        # The upload's message, then each stage's message in turn, as the host would.
        pending = [(QueueName.QUALITY, message(uploaded))]
        consumed: list[QueueName] = []
        while pending:
            name, body = pending.pop(0)
            consumed.append(name)
            asyncio.run(handlers[name](body))
            pending.extend((q, m.to_json()) for q, m, _ in queue.sent)
            queue.sent.clear()
        assert consumed == [
            QueueName.QUALITY,
            QueueName.EXTRACT,
            QueueName.VALIDATE,
            QueueName.POST,
        ]
        row = _row(pipeline_engine, uploaded)
        assert (row.status, row.post_failures) == ("posted", 0)
        with pipeline_engine.connect() as connection:
            steps = [
                r.to_status
                for r in connection.execute(
                    select(status_history.c.to_status)
                    .where(status_history.c.invoice_id == uploaded)
                    .order_by(status_history.c.at, status_history.c.id)
                )
            ]
            routed = connection.execute(
                select(sql_func.count()).where(admin_item.c.invoice_id == uploaded)
            ).scalar_one()
        assert steps == [
            "received",
            "awaiting_extraction",
            "extracting",
            "awaiting_validation",
            "validating",
            "ready_to_post",
            "posting",
            "posted",
        ]
        assert routed == 0
        assert accounts_sim.urls == [f"{BASE_URL}/invoices"]
        # Stored once by accounts-sim, under the reference the invoice now holds.
        with owner.connect() as connection:
            stored = connection.execute(
                text(
                    "SELECT accounts_ref, invoice_number, invoice_total"
                    " FROM sim_accounts.invoice WHERE invoice_id = :id"
                ),
                {"id": uploaded},
            ).one()
        assert tuple(stored) == (row.accounts_ref, "INV-E2E-1", Decimal("850.20"))
    finally:
        sim.dispose()
        owner.dispose()
