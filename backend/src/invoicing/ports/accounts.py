"""The accounts system (AD-10, Story 3.2): `AccountsPort.post_invoice` sends one
invoice and answers its `accounts_ref`, and `PostingRepository` holds what the `post`
stage reads and writes in the invoice store.

One accounts adapter, `adapters/accounts_xml/`, builds the XML and calls
`ACCOUNTS_BASE_URL` (accounts-sim today; the real system changes only that setting
and the auth settings). The port is idempotent on `invoice_id`: a repeat call answers
the same reference. The adapter never retries; the stage backs off (AD-3).
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from invoicing.domain.current_values import CurrentValues
from invoicing.domain.posting import PostRetry
from invoicing.domain.transitions import AdminRouting, Transition


@dataclass(frozen=True)
class InvoiceToPost:
    """What is posted: the invoice's ids, its current PO (AD-19), the invoice currency
    (configuration: DI reports none for SGD) and its AD-18 current values."""

    invoice_id: UUID
    supplier_id: UUID
    po_number: str | None
    currency: str
    values: CurrentValues


class AccountsError(Exception):
    """The accounts system did not store the invoice: an HTTP error (`status`), a
    timeout or an unreachable host (`status` None), or a document the contract
    refuses (`XML_INVALID`). `code` is a code, never a value or the error text."""

    def __init__(self, status: int | None, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


class AccountsPort(Protocol):
    """Posts invoices to the accounts system (AD-10)."""

    async def post_invoice(self, invoice: InvoiceToPost) -> str:
        """Send `invoice` once and return its `accounts_ref` (the same reference for
        a repeat `invoice_id`). Raises `AccountsError`; never retries."""
        ...


@dataclass(frozen=True)
class PostingState:
    """The invoice facts the post stage needs besides its current values: the
    supplier, the current PO and an `accounts_ref` saved by an earlier try."""

    supplier_id: UUID
    po_number: str | None
    accounts_ref: str | None


# Called in the failure transaction with this failure's number (1 for the first).
type DecideFailure = Callable[[int], PostRetry | AdminRouting]


class PostingRepository(Protocol):
    """The post stage's writes (AD-3). Every method raises `DatabaseOfflineError`
    when it can't connect (AD-7)."""

    async def state(self, invoice_id: UUID) -> PostingState | None:
        """The invoice's supplier, PO and saved `accounts_ref`, or None: no row."""
        ...

    async def save_ref(self, invoice_id: UUID, accounts_ref: str) -> bool:
        """Save `accounts_ref` while the invoice is `posting`, before the finish (AD-3
        save-before-finish). False when it is no longer `posting`."""
        ...

    async def finish(self, plan: Transition) -> bool:
        """`posting -> posted` with `posted_at` equal to its history row's `at`, and
        the lease ended, in one transaction. False when nothing changed (AD-2)."""
        ...

    async def fail(
        self, invoice_id: UUID, decide: DecideFailure
    ) -> PostRetry | AdminRouting | None:
        """One transaction: count this failure, then either retry (`posting ->
        ready_to_post`, `next_attempt_at` = now + delay, lease released) or route.
        None, with nothing written, when the invoice is no longer `posting`."""
        ...
