"""The `extract` stage's ports (Story 2.3, AD-3, AD-8, AD-18): which model reads an
invoice, the one Document Intelligence caller, and where runs are saved.

Every `DocumentAnalyzer` error carries a code only, never DI's text or a field value
(security.md rule 31)."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol
from uuid import UUID

from invoicing.domain.extraction import ExtractedInvoice
from invoicing.domain.transitions import Transition
from invoicing.domain.upload import UploadContentType

# AD-8: the default model and the only API version.
DEFAULT_MODEL_ID = "prebuilt-invoice"
DI_API_VERSION = "2024-11-30"


class ModelSelector(Protocol):
    """Picks the DI model per supplier format (AD-8). The CAP-10 seam: custom models
    arrive only through this port."""

    def model_for(self, supplier_id: UUID) -> str:
        """The model id to analyse this supplier's invoices with."""
        ...


class DefaultModelSelector:
    """Every supplier on `prebuilt-invoice` until custom models exist (CAP-10)."""

    def model_for(self, supplier_id: UUID) -> str:
        return DEFAULT_MODEL_ID


@dataclass(frozen=True)
class PageReservation:
    """Pages counted against the cap of `month` (its first day) before an analyze
    call (AD-8)."""

    month: date
    pages: int


@dataclass(frozen=True)
class SavedOperation:
    """An analyze call's `Operation-Location`, saved before polling (AD-8), and the
    month its pages were reserved in."""

    location: str
    month: date


@dataclass(frozen=True)
class AnalyzeRequest:
    """One invoice to analyse. With `resume`, the adapter polls that operation and
    sends no new analyze call, so `document` may be None."""

    invoice_id: UUID
    model_id: str
    content_type: UploadContentType
    document: bytes | None = field(default=None, repr=False)
    resume: SavedOperation | None = None


@dataclass(frozen=True)
class Analysis:
    """A finished analysis, already mapped to AD-18 rows; the raw result is gone."""

    model_id: str
    api_version: str
    pages: int
    invoice: ExtractedInvoice
    reservation: PageReservation


class ExtractionError(Exception):
    """A DI call that did not produce an analysis. The message is the code only."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class DiThrottled(ExtractionError):
    """DI answered 429: try again after `retry_after` seconds (AD-7)."""

    def __init__(self, retry_after: int) -> None:
        super().__init__("DI_THROTTLED")
        self.retry_after = retry_after


class DiQuotaExceeded(ExtractionError):
    """The page cap is reached, or DI refused with a quota error: the invoice goes to
    `EXTRACTION_QUOTA` (AD-8)."""


class DiAnalysisFailed(ExtractionError):
    """Any other DI failure (5xx, a failed or expired operation): retried."""


# `DiAnalysisFailed` codes after which a saved operation can never succeed.
DEAD_OPERATION_CODES = frozenset({"OPERATION_NOT_FOUND", "ANALYSIS_FAILED"})

type OperationSaver = Callable[[UUID, str], Awaitable[None]]


class DocumentAnalyzer(Protocol):
    """The only Document Intelligence caller (AD-8)."""

    async def analyze(
        self, request: AnalyzeRequest, save_operation: OperationSaver
    ) -> Analysis:
        """Analyse `request.document` (reserving its pages first), or resume polling
        `request.resume`. `save_operation(invoice_id, location)` is awaited before the
        first poll. Raises `DiThrottled`, `DiQuotaExceeded` or
        `DiAnalysisFailed`."""
        ...

    async def pages_used_pct(self) -> float:
        """This month's pages as a percentage of the cap, 0-100 (`di_pages_used_pct`)."""
        ...


@dataclass(frozen=True)
class NewRun:
    """One extraction run to save (AD-18) under a new UUIDv7 `run_id`."""

    run_id: UUID
    invoice_id: UUID
    analysis: Analysis


class ExtractionRepository(Protocol):
    """Extraction runs and saved operations (AD-3 save-before-finish, AD-18). Raises
    `DatabaseOfflineError` when PostgreSQL can't be reached (AD-7)."""

    async def latest_run_since_entry(self, invoice_id: UUID) -> UUID | None:
        """The newest run created after the invoice last entered
        `awaiting_extraction`, or None, so a Re-extract always reads again (AD-3)."""
        ...

    async def saved_operation(self, invoice_id: UUID) -> SavedOperation | None:
        """The saved `Operation-Location`, if it was saved after the invoice last
        entered `awaiting_extraction` (AD-8)."""
        ...

    async def save_operation(self, invoice_id: UUID, location: str) -> None:
        """Save (or replace) the invoice's `Operation-Location`."""
        ...

    async def forget_operation(self, invoice_id: UUID) -> None:
        """Delete the saved `Operation-Location` (DI expired or failed it), so the
        next retry analyses again."""
        ...

    async def save_run(self, run: NewRun, transition: Transition) -> bool:
        """In one transaction: the run, its fields (bank values encrypted and
        fingerprinted, AD-11) and lines, the page count reconciled to the result, and
        `transition`. False when the transition changed nothing: nothing is saved."""
        ...
