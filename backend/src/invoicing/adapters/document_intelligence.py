"""The only Document Intelligence caller (Story 2.3, AD-8).

REST, not the SDK: the adapter owns every request, so the rate limit covers polls too
and the `Operation-Location` can be saved before the first poll (the SDK's poller
hides both). No new dependency: `aiohttp` and `azure-identity` are already there.

- API `2024-11-30`, the resource's custom subdomain, and a managed-identity token for
  `https://cognitiveservices.azure.com/.default`; no key exists.
- Rate: at most 1 request every 2 seconds in this environment, polls included. The
  last call time is kept in `intake.di_usage` under `pg_advisory_xact_lock`, so the
  limit holds across instances, restarts and redeploys.
- Pages: an analyze call reserves its pages (`pages_to_reserve`) under the same lock
  and in the same transaction as its request slot, so two instances can't both pass
  the monthly cap; the run reconciles them to the real count when it is saved.
- The result is mapped to AD-18 rows (`domain.extraction`) and the raw JSON dropped.

Errors carry codes only: DI's error text is never logged or raised, and no field
value ever is (security.md rule 31).
"""

import asyncio
import base64
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, NoReturn, Protocol
from urllib.parse import quote, urlsplit
from uuid import UUID

import aiohttp
from azure.core.credentials_async import AsyncTokenCredential
from sqlalchemy import Engine, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from invoicing.adapters.logging import log_event
from invoicing.adapters.postgres.engine import open_connection
from invoicing.adapters.postgres.extraction import lock_di_usage, utc_month
from invoicing.adapters.postgres.schema import di_usage
from invoicing.domain.extraction import map_invoice, pages_to_reserve
from invoicing.ports.extraction import (
    DI_API_VERSION,
    Analysis,
    AnalyzeRequest,
    DiAnalysisFailed,
    DiQuotaExceeded,
    DiThrottled,
    OperationSaver,
    PageReservation,
)

COGNITIVE_SERVICES_SCOPE = "https://cognitiveservices.azure.com/.default"
# AD-8: Dev and Prod each send at most one request every 2 s: together 1 a second.
MIN_INTERVAL = timedelta(seconds=2)
# Polls per stage run before giving up for now; the retry resumes the saved operation.
MAX_POLLS = 60
# Seconds to wait when DI sends no usable Retry-After.
DEFAULT_POLL_SECONDS = 2
DEFAULT_THROTTLE_SECONDS = 30
# A 429 re-enqueue waits at most this long (AD-7 uses the same queue delay).
MAX_RETRY_AFTER_SECONDS = 3600
REQUEST_TIMEOUT_SECONDS = 60
# F0 answers an exhausted monthly allowance with 403; its error code or message names
# the quota. [ASSUMPTION] Confirm the exact code on the first quota error in Dev.
QUOTA_CODES = frozenset({"QuotaExceeded", "OutOfQuota", "OutOfCallVolumeQuota"})

_logger = logging.getLogger("invoicing.document_intelligence")


@dataclass(frozen=True)
class HttpResponse:
    """One HTTP answer: status, headers (lower-case names) and body."""

    status: int
    headers: Mapping[str, str]
    body: bytes = field(default=b"", repr=False)


class HttpTransport(Protocol):
    """Sends one HTTP request; tests pass a fake (coding-style.md rule 23)."""

    async def request(
        self, method: str, url: str, headers: Mapping[str, str], body: bytes | None
    ) -> HttpResponse: ...


class AiohttpTransport:
    """`HttpTransport` over one `aiohttp` session, opened on first use."""

    def __init__(self, timeout_seconds: float = REQUEST_TIMEOUT_SECONDS) -> None:
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self._session: aiohttp.ClientSession | None = None

    async def request(
        self, method: str, url: str, headers: Mapping[str, str], body: bytes | None
    ) -> HttpResponse:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        async with self._session.request(
            method, url, headers=dict(headers), data=body, allow_redirects=False
        ) as response:
            return HttpResponse(
                status=response.status,
                headers={
                    name.lower(): value for name, value in response.headers.items()
                },
                body=await response.read(),
            )


def _now() -> datetime:
    return datetime.now(UTC)


def _seconds(headers: Mapping[str, str], default: int) -> int:
    """`Retry-After` in whole seconds, within 1 and `MAX_RETRY_AFTER_SECONDS`."""
    value = headers.get("retry-after", "")
    seconds = int(value) if value.strip().isdigit() else default
    return min(max(seconds, 1), MAX_RETRY_AFTER_SECONDS)


def _json(body: bytes) -> dict[str, Any]:
    try:
        # Amounts stay exact (coding-style.md rule 4).
        document = json.loads(body, parse_float=Decimal)
    except ValueError:
        return {}
    return document if isinstance(document, dict) else {}


def _error_code(body: bytes) -> str:
    error = _json(body).get("error")
    if not isinstance(error, dict):
        return ""
    inner = error.get("innererror")
    code = inner.get("code") if isinstance(inner, dict) else None
    return str(code or error.get("code") or "")


def _is_quota_error(body: bytes) -> bool:
    error = _json(body).get("error")
    if not isinstance(error, dict):
        return False
    words = f"{error.get('code', '')} {error.get('message', '')}".lower()
    return _error_code(body) in QUOTA_CODES or "quota" in words


class DocumentIntelligenceAnalyzer:
    """`DocumentAnalyzer` over the DI REST API, with the AD-8 limits in PostgreSQL."""

    def __init__(
        self,
        *,
        endpoint: str,
        credential: AsyncTokenCredential,
        engine: Engine,
        page_cap: int,
        currency: str,
        transport: HttpTransport | None = None,
        clock: Callable[[], datetime] = _now,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        max_polls: int = MAX_POLLS,
    ) -> None:
        if page_cap <= 0:
            raise ValueError("page_cap must be positive")
        parts = urlsplit(endpoint)
        if parts.scheme != "https" or not parts.netloc:
            raise ValueError("endpoint must be an https URL")
        self._origin = f"https://{parts.netloc}"
        self._credential = credential
        self._engine = engine
        self._page_cap = page_cap
        self._currency = currency
        self._transport = transport or AiohttpTransport()
        self._clock = clock
        self._sleep = sleep
        self._max_polls = max_polls

    # --- DocumentAnalyzer -----------------------------------------------------------

    async def analyze(
        self, request: AnalyzeRequest, save_operation: OperationSaver
    ) -> Analysis:
        needed = pages_to_reserve(request.content_type)
        if request.resume is not None:
            # AD-8: a retry resumes polling; its pages were reserved by the first try.
            location = request.resume.location
            reservation = PageReservation(request.resume.month, needed)
        else:
            if request.document is None:
                raise ValueError("a new analysis needs the document")
            month = await self._acquire(needed)
            reservation = PageReservation(month, needed)
            try:
                location = await self._start(request)
                await save_operation(request.invoice_id, location)
            except DiQuotaExceeded:
                # AD-8: DI counted the call against its quota; the pages stay counted.
                raise
            except Exception:
                # No operation was saved, so a retry reserves again: give these back.
                await asyncio.to_thread(self._release, month, needed)
                raise
        result = await self._poll(request.invoice_id, location)
        documents = result.get("documents")
        first = documents[0] if isinstance(documents, list) and documents else {}
        fields = first.get("fields") if isinstance(first, dict) else None
        pages = result.get("pages")
        return Analysis(
            model_id=str(result.get("modelId") or request.model_id),
            api_version=str(result.get("apiVersion") or DI_API_VERSION),
            pages=len(pages) if isinstance(pages, list) else 0,
            invoice=map_invoice(
                fields if isinstance(fields, dict) else {}, self._currency
            ),
            reservation=reservation,
        )

    async def pages_used_pct(self) -> float:
        pages = await asyncio.to_thread(self._pages_this_month)
        return min(100.0, pages * 100 / self._page_cap)

    # --- requests -------------------------------------------------------------------

    async def _start(self, request: AnalyzeRequest) -> str:
        url = (
            f"{self._origin}/documentintelligence/documentModels/"
            f"{quote(request.model_id, safe='')}:analyze?api-version={DI_API_VERSION}"
        )
        body = json.dumps(
            {"base64Source": base64.b64encode(request.document or b"").decode()}
        ).encode()
        response = await self._send(
            "POST", url, body, {"content-type": "application/json"}
        )
        if response.status == 202:
            location = response.headers.get("operation-location", "")
            # The token only ever goes to this resource (AD-8 custom subdomain).
            if not location.startswith(f"{self._origin}/"):
                raise self._failed(request.invoice_id, "BAD_OPERATION_LOCATION", 202)
            return location
        self._raise_for(request.invoice_id, response, "ANALYZE")

    async def _poll(self, invoice_id: UUID, location: str) -> dict[str, Any]:
        for _ in range(self._max_polls):
            response = await self._send("GET", location)
            if response.status != 200:
                self._raise_for(invoice_id, response, "POLL")
            document = _json(response.body)
            status = document.get("status")
            if status == "succeeded":
                result = document.get("analyzeResult")
                return result if isinstance(result, dict) else {}
            if status in ("failed", "canceled"):
                raise self._failed(
                    invoice_id, "ANALYSIS_FAILED", 200, _error_code(response.body)
                )
            await self._sleep(_seconds(response.headers, DEFAULT_POLL_SECONDS))
        raise self._failed(invoice_id, "POLL_TIMEOUT", 200)

    async def _send(
        self,
        method: str,
        url: str,
        body: bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        if body is None:
            # A poll: throttled like every request, with no pages (AD-8). An analyze
            # call took its slot with its page reservation in `analyze`.
            await self._acquire(0)
        token = await self._credential.get_token(COGNITIVE_SERVICES_SCOPE)
        return await self._transport.request(
            method,
            url,
            {**(headers or {}), "authorization": f"Bearer {token.token}"},
            body,
        )

    def _raise_for(
        self, invoice_id: UUID, response: HttpResponse, step: str
    ) -> NoReturn:
        if response.status == 429:
            retry_after = _seconds(response.headers, DEFAULT_THROTTLE_SECONDS)
            log_event(
                _logger,
                "di.throttled",
                level=logging.WARNING,
                invoice_id=invoice_id,
                code="DI_THROTTLED",
                http_status=429,
                duration_ms=retry_after * 1000,
            )
            raise DiThrottled(retry_after)
        if response.status == 403 and _is_quota_error(response.body):
            log_event(
                _logger,
                "di.quota",
                level=logging.WARNING,
                invoice_id=invoice_id,
                code="DI_QUOTA",
                http_status=403,
            )
            raise DiQuotaExceeded("DI_QUOTA")
        if response.status == 404 and step == "POLL":
            raise self._failed(invoice_id, "OPERATION_NOT_FOUND", 404)
        raise self._failed(
            invoice_id,
            f"{step}_HTTP_{response.status}",
            response.status,
            _error_code(response.body),
        )

    @staticmethod
    def _failed(
        invoice_id: UUID, code: str, http_status: int, di_code: str = ""
    ) -> DiAnalysisFailed:
        details: dict[str, object] = {"invoice_id": invoice_id, "code": code}
        if di_code:
            # DI's own error code, e.g. InvalidRequest: a code, never a value.
            details["reason"] = di_code
        log_event(
            _logger,
            "di.failed",
            level=logging.ERROR,
            http_status=http_status,
            **details,
        )
        return DiAnalysisFailed(code)

    # --- AD-8 limits, in PostgreSQL ---------------------------------------------------

    async def _acquire(self, pages: int) -> date:
        """Wait for this environment's next request slot and take it, reserving
        `pages` against the month's cap in the same transaction. Returns the month."""
        while True:
            wait, month = await asyncio.to_thread(self._try_acquire, pages)
            if wait <= 0:
                return month
            await self._sleep(wait)

    def _try_acquire(self, pages: int) -> tuple[float, date]:
        with open_connection(self._engine) as connection, connection.begin():
            lock_di_usage(connection)
            now = self._clock()
            month, last_call_at, used = connection.execute(
                select(
                    utc_month(func.now()),
                    select(func.max(di_usage.c.last_call_at)).scalar_subquery(),
                    select(di_usage.c.pages)
                    .where(di_usage.c.month == utc_month(func.now()))
                    .scalar_subquery(),
                )
            ).one()
            if last_call_at is not None:
                # Clamped: another instance's clock may run ahead of this one's.
                wait = min(
                    (last_call_at + MIN_INTERVAL - now).total_seconds(),
                    MIN_INTERVAL.total_seconds(),
                )
                if wait > 0:
                    return wait, month
            if pages and (used or 0) + pages > self._page_cap:
                log_event(
                    _logger,
                    "di.page_cap",
                    level=logging.WARNING,
                    code="PAGE_CAP",
                    count=used or 0,
                )
                raise DiQuotaExceeded("PAGE_CAP")
            statement = pg_insert(di_usage).values(
                month=month, pages=pages, last_call_at=now
            )
            connection.execute(
                statement.on_conflict_do_update(
                    index_elements=[di_usage.c.month],
                    set_={
                        "pages": di_usage.c.pages + statement.excluded.pages,
                        "last_call_at": statement.excluded.last_call_at,
                    },
                )
            )
            return 0.0, month

    def _release(self, month: date, pages: int) -> None:
        """Give back `pages` reserved in `month`; the last call time is kept."""
        with open_connection(self._engine) as connection, connection.begin():
            lock_di_usage(connection)
            connection.execute(
                update(di_usage)
                .where(di_usage.c.month == month)
                .values(pages=func.greatest(di_usage.c.pages - pages, 0))
            )

    def _pages_this_month(self) -> int:
        with open_connection(self._engine) as connection:
            used = connection.execute(
                select(di_usage.c.pages).where(
                    di_usage.c.month == utc_month(func.now())
                )
            ).scalar_one_or_none()
        return used or 0
