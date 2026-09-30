"""`PostingRepository` over PostgreSQL (Story 3.2, AD-3, AD-10).

- `save_ref` keeps the accounts reference under `invoice_id` before the finish, so a
  retry after a crash never posts again (AD-3 save-before-finish).
- `finish` moves `posting -> posted` and sets `posted_at` in the transaction that
  writes the history row: both take `now()`, the transaction's start, so `posted_at`
  equals that row's `at`.
- `fail` counts the failure and either schedules the next try or routes, in one
  transaction that holds the invoice row.

SQLAlchemy Core with bound parameters (security.md rule 21), on a worker thread
(coding-style.md rule 11). No value is logged here.
"""

import asyncio
from uuid import UUID

from sqlalchemy import Engine, func, select, update

from invoicing.adapters.postgres.engine import open_connection
from invoicing.adapters.postgres.invoices import PostgresInvoiceRepository
from invoicing.adapters.postgres.schema import invoice
from invoicing.domain.posting import PostRetry
from invoicing.domain.status import InvoiceStatus
from invoicing.domain.transitions import AdminRouting, Transition
from invoicing.ports.accounts import DecideFailure, PostingState

_POSTING = InvoiceStatus.POSTING.value


class PostgresPostingRepository:
    """The post stage's reads and writes on `intake.invoice`."""

    def __init__(self, engine: Engine, invoices: PostgresInvoiceRepository) -> None:
        self._engine = engine
        self._invoices = invoices

    async def state(self, invoice_id: UUID) -> PostingState | None:
        return await asyncio.to_thread(self._state, invoice_id)

    async def save_ref(self, invoice_id: UUID, accounts_ref: str) -> bool:
        return await asyncio.to_thread(self._save_ref, invoice_id, accounts_ref)

    async def finish(self, plan: Transition) -> bool:
        return await asyncio.to_thread(self._finish, plan)

    async def fail(
        self, invoice_id: UUID, decide: DecideFailure
    ) -> PostRetry | AdminRouting | None:
        return await asyncio.to_thread(self._fail, invoice_id, decide)

    def _state(self, invoice_id: UUID) -> PostingState | None:
        with open_connection(self._engine) as connection:
            row = connection.execute(
                select(
                    invoice.c.supplier_id, invoice.c.po_number, invoice.c.accounts_ref
                ).where(invoice.c.id == invoice_id)
            ).first()
        if row is None:
            return None
        return PostingState(row[0], row[1], row[2])

    def _save_ref(self, invoice_id: UUID, accounts_ref: str) -> bool:
        with open_connection(self._engine) as connection, connection.begin():
            saved = connection.execute(
                update(invoice)
                .where(invoice.c.id == invoice_id, invoice.c.status == _POSTING)
                .values(accounts_ref=accounts_ref)
                .returning(invoice.c.id)
            ).first()
        return saved is not None

    def _finish(self, plan: Transition) -> bool:
        with open_connection(self._engine) as connection, connection.begin():
            return self._invoices.transition_in(connection, plan, posted_at=func.now())

    def _fail(
        self, invoice_id: UUID, decide: DecideFailure
    ) -> PostRetry | AdminRouting | None:
        with open_connection(self._engine) as connection, connection.begin():
            # The row is locked, so the count read is the count written.
            failures = connection.execute(
                select(invoice.c.post_failures)
                .where(invoice.c.id == invoice_id, invoice.c.status == _POSTING)
                .with_for_update()
            ).scalar_one_or_none()
            if failures is None:
                return None
            count = failures + 1
            decision = decide(count)
            if isinstance(decision, AdminRouting):
                if not self._invoices.route_in(connection, decision):
                    return None
                connection.execute(
                    update(invoice)
                    .where(invoice.c.id == invoice_id)
                    .values(post_failures=count)
                )
                return decision
            # AD-3: back to ready_to_post, counted, due later, lease released.
            if not self._invoices.transition_in(
                connection,
                decision.transition,
                post_failures=count,
                next_attempt_at=func.now() + decision.delay,
            ):
                return None
            return decision
