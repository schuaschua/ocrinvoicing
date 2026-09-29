"""`ExtractionRepository` over PostgreSQL (Story 2.3, AD-3, AD-8, AD-11, AD-18).

A run, its fields and lines, the page reconciliation and the final transition are one
transaction, so a run is either saved with its transition or not at all. Bank values
are normalised, fingerprinted in Python (`domain/suppliers.py`) and encrypted in SQL
with `pgp_pub_encrypt` and the environment's public key, from their first write; no
plaintext bank value is ever bound to a value column (a check in migration 0005
refuses one too).

"Since entry" means created after the invoice's latest `status_history` row into
`awaiting_extraction`, so an admin Re-extract always reads again (AD-3).
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Connection,
    Date,
    Engine,
    ScalarSelect,
    cast,
    delete,
    func,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert

from invoicing.adapters.postgres.engine import open_connection
from invoicing.adapters.postgres.invoices import PostgresInvoiceRepository
from invoicing.adapters.postgres.schema import (
    di_operation,
    di_usage,
    extraction_run,
    invoice_field,
    invoice_line,
    status_history,
)
from invoicing.adapters.postgres.suppliers import BankKeys
from invoicing.domain.extraction import FieldRow
from invoicing.domain.ids import new_uuid7
from invoicing.domain.status import InvoiceStatus
from invoicing.domain.suppliers import bank_fingerprint, normalise_bank_value
from invoicing.domain.transitions import Transition
from invoicing.ports.extraction import NewRun, SavedOperation

# AD-8: the one advisory lock every di_usage change is made under (the page count and
# the last call time), in this database. Any constant works; this is "DI" in ASCII.
DI_USAGE_LOCK_KEY = 0x4449
DI_SOURCE = "di"

type BankKeysProvider = Callable[[], Awaitable[BankKeys]]


def lock_di_usage(connection: Connection) -> None:
    """Take the AD-8 lock until the caller's transaction ends."""
    connection.execute(
        text("SELECT pg_advisory_xact_lock(:key)"), {"key": DI_USAGE_LOCK_KEY}
    )


def utc_month(timestamp: Any) -> Any:
    """SQL: the first day of the UTC calendar month of `timestamp` (a `date`)."""
    return cast(func.date_trunc("month", func.timezone("UTC", timestamp)), Date)


def _entered_extraction(invoice_id: UUID) -> ScalarSelect[Any]:
    return (
        select(func.max(status_history.c.at))
        .where(
            status_history.c.invoice_id == invoice_id,
            status_history.c.to_status == InvoiceStatus.AWAITING_EXTRACTION.value,
        )
        .scalar_subquery()
    )


class PostgresExtractionRepository:
    """The `intake` extraction tables, through SQLAlchemy Core with bound parameters.
    `bank_keys` is awaited only when a run holds a bank value."""

    def __init__(
        self,
        engine: Engine,
        invoices: PostgresInvoiceRepository,
        bank_keys: BankKeysProvider,
        new_id: Callable[[], UUID] = new_uuid7,
    ) -> None:
        self._engine = engine
        self._invoices = invoices
        self._bank_keys = bank_keys
        self._new_id = new_id

    async def latest_run_since_entry(self, invoice_id: UUID) -> UUID | None:
        return await asyncio.to_thread(self._latest_run, invoice_id)

    async def saved_operation(self, invoice_id: UUID) -> SavedOperation | None:
        return await asyncio.to_thread(self._saved_operation, invoice_id)

    async def save_operation(self, invoice_id: UUID, location: str) -> None:
        await asyncio.to_thread(self._save_operation, invoice_id, location)

    async def forget_operation(self, invoice_id: UUID) -> None:
        await asyncio.to_thread(self._forget_operation, invoice_id)

    async def save_run(self, run: NewRun, transition: Transition) -> bool:
        has_bank_value = any(
            row.bank_value is not None for row in run.analysis.invoice.fields
        )
        keys = await self._bank_keys() if has_bank_value else None
        return await asyncio.to_thread(self._save_run, run, transition, keys)

    # --- one transaction each ---------------------------------------------------------

    def _latest_run(self, invoice_id: UUID) -> UUID | None:
        with open_connection(self._engine) as connection:
            value: UUID | None = connection.execute(
                select(extraction_run.c.run_id)
                .where(
                    extraction_run.c.invoice_id == invoice_id,
                    extraction_run.c.created_at > _entered_extraction(invoice_id),
                )
                .order_by(extraction_run.c.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()
        return value

    def _saved_operation(self, invoice_id: UUID) -> SavedOperation | None:
        with open_connection(self._engine) as connection:
            row = connection.execute(
                select(
                    di_operation.c.operation_location,
                    utc_month(di_operation.c.created_at),
                ).where(
                    di_operation.c.invoice_id == invoice_id,
                    di_operation.c.created_at > _entered_extraction(invoice_id),
                )
            ).first()
        return None if row is None else SavedOperation(location=row[0], month=row[1])

    def _save_operation(self, invoice_id: UUID, location: str) -> None:
        with open_connection(self._engine) as connection, connection.begin():
            statement = pg_insert(di_operation).values(
                invoice_id=invoice_id,
                operation_location=location,
                created_at=func.now(),
            )
            connection.execute(
                statement.on_conflict_do_update(
                    index_elements=[di_operation.c.invoice_id],
                    set_={
                        "operation_location": statement.excluded.operation_location,
                        "created_at": statement.excluded.created_at,
                    },
                )
            )

    def _forget_operation(self, invoice_id: UUID) -> None:
        with open_connection(self._engine) as connection, connection.begin():
            connection.execute(
                delete(di_operation).where(di_operation.c.invoice_id == invoice_id)
            )

    def _save_run(
        self, run: NewRun, transition: Transition, keys: BankKeys | None
    ) -> bool:
        with open_connection(self._engine) as connection, connection.begin():
            # The transition is the first write: when it changes nothing, nothing
            # else is written (AD-2).
            if not self._invoices.transition_in(connection, transition):
                return False
            analysis = run.analysis
            connection.execute(
                insert(extraction_run).values(
                    run_id=run.run_id,
                    invoice_id=run.invoice_id,
                    model_id=analysis.model_id,
                    api_version=analysis.api_version,
                    pages=analysis.pages,
                    created_at=func.now(),
                )
            )
            for row in analysis.invoice.fields:
                connection.execute(
                    insert(invoice_field).values(
                        id=self._new_id(),
                        invoice_id=run.invoice_id,
                        run_id=run.run_id,
                        source=DI_SOURCE,
                        created_at=func.now(),
                        **self._field_values(row, keys),
                    )
                )
            if analysis.invoice.lines:
                connection.execute(
                    insert(invoice_line).values(
                        invoice_id=run.invoice_id,
                        run_id=run.run_id,
                        source=DI_SOURCE,
                        created_at=func.now(),
                    ),
                    [
                        {
                            "id": self._new_id(),
                            "line_no": line.line_no,
                            "product_code": line.product_code,
                            "description": line.description,
                            "quantity": line.quantity,
                            "unit": line.unit,
                            "unit_price": line.unit_price,
                            "amount": line.amount,
                            "tax": line.tax,
                            "confidence": line.confidence,
                        }
                        for line in analysis.invoice.lines
                    ],
                )
            self._reconcile(
                connection,
                analysis.reservation.month,
                used=analysis.pages,
                reserved=analysis.reservation.pages,
            )
            return True

    @staticmethod
    def _field_values(row: FieldRow, keys: BankKeys | None) -> dict[str, Any]:
        values: dict[str, Any] = {
            "field_id": row.field_id,
            "confidence": row.confidence,
            "page": row.page,
            "polygon": None if row.polygon is None else list(row.polygon),
            "value_text": row.value_text,
            "value_number": row.value_number,
            "value_date": row.value_date,
            "currency": row.currency,
        }
        normalised = (
            None if row.bank_value is None else normalise_bank_value(row.bank_value)
        )
        if normalised:
            if keys is None:
                raise RuntimeError("bank keys are needed to save a bank field")
            # AD-11: the normalised value, the same string the fingerprint covers,
            # encrypted in SQL with bound parameters (security.md rule 21).
            values["bank_ciphertext"] = func.pgp_pub_encrypt(
                normalised, func.dearmor(keys.public_key)
            )
            values["bank_fingerprint"] = bank_fingerprint(keys.hmac_key, normalised)
        return values

    @staticmethod
    def _reconcile(
        connection: Connection, month: date, *, used: int, reserved: int
    ) -> None:
        """AD-8: count the pages the run really used instead of those reserved."""
        if used == reserved:
            return
        lock_di_usage(connection)
        connection.execute(
            update(di_usage)
            .where(di_usage.c.month == month)
            .values(pages=func.greatest(di_usage.c.pages + (used - reserved), 0))
        )
