"""The accounts simulation's store over PostgreSQL (Story 3.1, AD-10, AD-11): schema
`sim_accounts`, reached only by the accounts-sim login (migration 0009_sim_accounts).
SQLAlchemy Core with bound parameters (security.md rule 21); no value is logged."""

import asyncio

from sqlalchemy import (
    TIMESTAMP,
    Column,
    Engine,
    FetchedValue,
    Integer,
    MetaData,
    Numeric,
    SmallInteger,
    Table,
    Text,
    Uuid,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert

from invoicing.adapters.accounts_xml.contract import AccountsInvoice
from invoicing.adapters.postgres.engine import open_connection

SIM_ACCOUNTS = "sim_accounts"

metadata = MetaData(schema=SIM_ACCOUNTS)

# Statements only; the migration creates the tables (AD-17). `accounts_ref` and
# `created_at` come from their server defaults.
sim_invoice = Table(
    "invoice",
    metadata,
    Column("accounts_ref", Text, primary_key=True, server_default=FetchedValue()),
    Column("invoice_id", Uuid, nullable=False, unique=True),
    Column("supplier_id", Uuid, nullable=False),
    Column("invoice_number", Text, nullable=False),
    Column("invoice_total", Numeric(18, 2, asdecimal=True), nullable=False),
    Column("document", Text, nullable=False),
    Column(
        "created_at",
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=FetchedValue(),
    ),
)

failure_mode = Table(
    "failure_mode",
    metadata,
    Column("id", SmallInteger, primary_key=True),
    Column("fail_next", Integer, nullable=False),
    Column("status", Integer, nullable=False),
)

FAILURE_MODE_ROW = 1


class PostgresSimAccounts:
    """Stores posted invoices once per `invoice_id` and serves the failure mode."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    async def take_failure(self) -> int | None:
        """The status to fail this call with, counting it off `fail_next`; None when
        the failure mode is off. One statement, so concurrent calls never fail more
        than `fail_next` times between them."""
        return await asyncio.to_thread(self._take_failure)

    def _take_failure(self) -> int | None:
        statement = (
            update(failure_mode)
            .where(failure_mode.c.id == FAILURE_MODE_ROW, failure_mode.c.fail_next > 0)
            .values(fail_next=failure_mode.c.fail_next - 1)
            .returning(failure_mode.c.status)
        )
        with open_connection(self._engine) as connection, connection.begin():
            status = connection.execute(statement).scalar_one_or_none()
        return int(status) if status is not None else None

    async def store(self, invoice: AccountsInvoice, document: str) -> tuple[str, bool]:
        """`(accounts_ref, created)`: a new row and its reference, or, for an
        `invoice_id` already stored (whatever the document), the stored reference."""
        return await asyncio.to_thread(self._store, invoice, document)

    def _store(self, invoice: AccountsInvoice, document: str) -> tuple[str, bool]:
        statement = (
            insert(sim_invoice)
            .values(
                invoice_id=invoice.invoice_id,
                supplier_id=invoice.supplier_id,
                invoice_number=invoice.invoice_number,
                invoice_total=invoice.invoice_total,
                document=document,
            )
            # A concurrent post of the same invoice waits for the other to commit and
            # then inserts nothing (AD-10 idempotency); the re-read returns its ref.
            .on_conflict_do_nothing(index_elements=[sim_invoice.c.invoice_id])
            .returning(sim_invoice.c.accounts_ref)
        )
        with open_connection(self._engine) as connection, connection.begin():
            created = connection.execute(statement).scalar_one_or_none()
            if created is not None:
                return str(created), True
            stored: object = connection.execute(
                select(sim_invoice.c.accounts_ref).where(
                    sim_invoice.c.invoice_id == invoice.invoice_id
                )
            ).scalar_one()
        return str(stored), False
