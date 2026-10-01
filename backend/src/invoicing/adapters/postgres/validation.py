"""`ValidationRepository` over PostgreSQL (Stories 2.5 and 2.6, AD-9, AD-18, AD-19).

Reads go through the one AD-18 current-value rule (`domain/current_values.py`). The
finish is one transaction under `pg_advisory_xact_lock` keyed on the supplier, which
also covers the AD-9 duplicate read: two invoices of one supplier never count the
same received quantity twice, and of two copies only the later is flagged. The
transition is its first write, so when it changes nothing, nothing else is written
(AD-2). Bank fields are read by fingerprint only, never the ciphertext (AD-11).
"""

import asyncio
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    BindParameter,
    Connection,
    Engine,
    Uuid,
    any_,
    bindparam,
    exists,
    select,
    text,
    update,
)

from invoicing.adapters.postgres.engine import open_connection
from invoicing.adapters.postgres.invoices import (
    PostgresInvoiceRepository,
    unsigned_phash,
)
from invoicing.adapters.postgres.schema import (
    extraction_run,
    image_hash,
    invoice,
    invoice_field,
    invoice_line,
)
from invoicing.adapters.postgres.suppliers import supplier_bank
from invoicing.domain.current_values import (
    CurrentValues,
    FieldValue,
    LineValue,
    RunRow,
    current_values,
)
from invoicing.domain.status import InvoiceStatus
from invoicing.domain.transitions import AdminRouting
from invoicing.domain.validation import (
    INVOICE_DATE,
    INVOICE_NUMBER,
    INVOICE_TOTAL,
    DuplicateFacts,
    duplicate_facts,
)
from invoicing.ports.intake import IntakeSource
from invoicing.ports.validation import (
    ComputeResult,
    InvoiceFacts,
    ValidationInput,
)

_LINE_COLUMNS = (
    invoice_line.c.id,
    invoice_line.c.invoice_id,
    invoice_line.c.line_no,
    invoice_line.c.run_id,
    invoice_line.c.source,
    invoice_line.c.created_at,
    invoice_line.c.confidence,
    invoice_line.c.product_code,
    invoice_line.c.quantity,
    invoice_line.c.unit_price,
    invoice_line.c.amount,
    invoice_line.c.po_line_id,
    # Story 3.2: posted with the line (the accounts contract).
    invoice_line.c.description,
    invoice_line.c.material_id,
)
# The value columns of a field row; never `bank_ciphertext` (AD-11).
_FIELD_COLUMNS = (
    invoice_field.c.id,
    invoice_field.c.invoice_id,
    invoice_field.c.field_id,
    invoice_field.c.run_id,
    invoice_field.c.source,
    invoice_field.c.created_at,
    invoice_field.c.confidence,
    invoice_field.c.value_text,
    invoice_field.c.value_number,
    invoice_field.c.value_date,
)
# AD-9: the fingerprint's field ids.
_DUPLICATE_FIELDS = (INVOICE_NUMBER, INVOICE_TOTAL, INVOICE_DATE)


def lock_supplier(connection: Connection, supplier_id: UUID) -> None:
    """AD-9 / AD-19: the per-supplier lock, until the caller's transaction ends. One
    64-bit key per supplier, shared with the duplicate check (Story 2.6)."""
    connection.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(CAST(:s AS text), 0))"),
        {"s": str(supplier_id)},
    )


def _line(row: Any) -> LineValue:
    return LineValue(
        id=row.id,
        line_no=row.line_no,
        run_id=row.run_id,
        source=row.source,
        created_at=row.created_at,
        confidence=row.confidence,
        product_code=row.product_code,
        quantity=row.quantity,
        unit_price=row.unit_price,
        amount=row.amount,
        po_line_id=row.po_line_id,
        description=row.description,
        material_id=row.material_id,
    )


def _field(row: Any, bank_fingerprint: str | None = None) -> FieldValue:
    return FieldValue(
        id=row.id,
        field_id=row.field_id,
        run_id=row.run_id,
        source=row.source,
        created_at=row.created_at,
        confidence=row.confidence,
        value_text=row.value_text,
        value_number=row.value_number,
        value_date=row.value_date,
        bank_fingerprint=bank_fingerprint,
    )


def _runs(rows: Iterable[Any]) -> dict[UUID, list[RunRow]]:
    runs: dict[UUID, list[RunRow]] = defaultdict(list)
    for row in rows:
        runs[row.invoice_id].append(RunRow(row.run_id, row.created_at))
    return runs


def id_array(ids: Sequence[UUID]) -> BindParameter[Sequence[UUID]]:
    """`ids` as one array parameter (`= ANY(:ids)`), never one bind per id, so a large
    batch stays under PostgreSQL's 65,535-parameter limit."""
    return bindparam("ids", ids, type_=ARRAY(Uuid))


def current_values_of(
    connection: Connection, ids: Iterable[UUID], field_ids: Iterable[str]
) -> dict[UUID, CurrentValues]:
    """The AD-18 current values (the `field_ids` fields and every line) of each
    invoice in `ids` that has a run, in one read per table; never a bank ciphertext
    (AD-11). Story 5.1's analytics refresh reads posted invoices through it."""
    wanted = list(ids)
    if not wanted:
        return {}
    runs = _runs(
        connection.execute(
            select(
                extraction_run.c.invoice_id,
                extraction_run.c.run_id,
                extraction_run.c.created_at,
            ).where(extraction_run.c.invoice_id == any_(id_array(wanted)))
        )
    )
    fields: dict[UUID, list[FieldValue]] = defaultdict(list)
    for row in connection.execute(
        select(*_FIELD_COLUMNS).where(
            invoice_field.c.invoice_id == any_(id_array(wanted)),
            invoice_field.c.field_id.in_(list(field_ids)),
        )
    ):
        fields[row.invoice_id].append(_field(row))
    lines: dict[UUID, list[LineValue]] = defaultdict(list)
    for row in connection.execute(
        select(*_LINE_COLUMNS).where(
            invoice_line.c.invoice_id == any_(id_array(wanted))
        )
    ):
        lines[row.invoice_id].append(_line(row))
    result: dict[UUID, CurrentValues] = {}
    for invoice_id, invoice_runs in runs.items():
        values = current_values(
            invoice_runs, fields.get(invoice_id, []), lines.get(invoice_id, [])
        )
        if values is not None:
            result[invoice_id] = values
    return result


class PostgresValidationRepository:
    """The validate stage's reads and finish, through SQLAlchemy Core with bound
    parameters (security.md rule 21), on a worker thread (coding-style.md rule 11)."""

    def __init__(self, engine: Engine, invoices: PostgresInvoiceRepository) -> None:
        self._engine = engine
        self._invoices = invoices

    async def load(self, invoice_id: UUID) -> ValidationInput | None:
        return await asyncio.to_thread(self._load, invoice_id)

    async def finish_locked(
        self, invoice_id: UUID, supplier_id: UUID, compute: ComputeResult
    ) -> bool:
        return await asyncio.to_thread(self._finish, invoice_id, supplier_id, compute)

    def _load(self, invoice_id: UUID) -> ValidationInput | None:
        with open_connection(self._engine) as connection:
            row = connection.execute(
                select(
                    invoice.c.source,
                    invoice.c.supplier_id,
                    invoice.c.delivery_id,
                    invoice.c.photo_taken_at,
                    image_hash.c.phash,
                )
                .select_from(invoice.outerjoin(image_hash))
                .where(invoice.c.id == invoice_id)
            ).one_or_none()
            if row is None:
                return None
            facts = InvoiceFacts(
                source=IntakeSource(row.source),
                supplier_id=row.supplier_id,
                delivery_id=row.delivery_id,
                photo_taken_at=row.photo_taken_at,
                phash=None if row.phash is None else unsigned_phash(row.phash),
            )
            runs = connection.execute(
                select(
                    extraction_run.c.invoice_id,
                    extraction_run.c.run_id,
                    extraction_run.c.created_at,
                ).where(extraction_run.c.invoice_id == invoice_id)
            ).all()
            # AD-11: a bank field's fingerprint, never its ciphertext.
            fields = connection.execute(
                select(*_FIELD_COLUMNS, invoice_field.c.bank_fingerprint).where(
                    invoice_field.c.invoice_id == invoice_id
                )
            ).all()
            lines = connection.execute(
                select(*_LINE_COLUMNS).where(invoice_line.c.invoice_id == invoice_id)
            ).all()
            # AD-19: the master's fingerprints only (the pipeline login cannot read
            # the ciphertext column at all, AD-11).
            master_bank = {
                bank.field_id: bank.fingerprint
                for bank in connection.execute(
                    select(supplier_bank.c.field_id, supplier_bank.c.fingerprint).where(
                        supplier_bank.c.supplier_id == row.supplier_id
                    )
                )
            }
        values = current_values(
            _runs(runs).get(invoice_id, []),
            (_field(f, f.bank_fingerprint) for f in fields),
            (_line(line) for line in lines),
        )
        return ValidationInput(facts=facts, values=values, master_bank=master_bank)

    @staticmethod
    def _earlier(
        connection: Connection, invoice_id: UUID, supplier_id: UUID
    ) -> list[DuplicateFacts]:
        """AD-9: the duplicate facts of the supplier's invoices that come before this
        one in id (UUIDv7) order and are not rejected, whatever their status."""
        earlier = (
            select(invoice.c.id)
            .where(
                invoice.c.supplier_id == supplier_id,
                invoice.c.id < invoice_id,
                invoice.c.status != InvoiceStatus.REJECTED.value,
            )
            .scalar_subquery()
        )
        hashes: dict[UUID, int | None] = {
            row.id: None if row.phash is None else unsigned_phash(row.phash)
            for row in connection.execute(
                select(invoice.c.id, image_hash.c.phash)
                .select_from(invoice.outerjoin(image_hash))
                .where(invoice.c.id.in_(earlier))
            )
        }
        runs = _runs(
            connection.execute(
                select(
                    extraction_run.c.invoice_id,
                    extraction_run.c.run_id,
                    extraction_run.c.created_at,
                ).where(extraction_run.c.invoice_id.in_(earlier))
            )
        )
        fields: dict[UUID, list[FieldValue]] = defaultdict(list)
        for row in connection.execute(
            select(*_FIELD_COLUMNS).where(
                invoice_field.c.invoice_id.in_(earlier),
                invoice_field.c.field_id.in_(_DUPLICATE_FIELDS),
            )
        ):
            fields[row.invoice_id].append(_field(row))
        return [
            duplicate_facts(
                other,
                current_values(runs.get(other, []), fields.get(other, []), ()),
                phash=phash,
            )
            for other, phash in hashes.items()
        ]

    @staticmethod
    def _invoiced_elsewhere(
        connection: Connection, invoice_id: UUID, supplier_id: UUID
    ) -> Mapping[UUID, Decimal]:
        """AD-19: the current quantity per `po_line_id` on the supplier's other
        invoices that are not rejected (only those with a matched line count)."""
        others = (
            select(invoice.c.id)
            .where(
                invoice.c.supplier_id == supplier_id,
                invoice.c.id != invoice_id,
                invoice.c.status != InvoiceStatus.REJECTED.value,
                exists().where(
                    invoice_line.c.invoice_id == invoice.c.id,
                    invoice_line.c.po_line_id.is_not(None),
                ),
            )
            .scalar_subquery()
        )
        runs = _runs(
            connection.execute(
                select(
                    extraction_run.c.invoice_id,
                    extraction_run.c.run_id,
                    extraction_run.c.created_at,
                ).where(extraction_run.c.invoice_id.in_(others))
            )
        )
        lines: dict[UUID, list[LineValue]] = defaultdict(list)
        for row in connection.execute(
            select(*_LINE_COLUMNS).where(invoice_line.c.invoice_id.in_(others))
        ):
            lines[row.invoice_id].append(_line(row))
        totals: dict[UUID, Decimal] = defaultdict(Decimal)
        for other, other_runs in runs.items():
            current = current_values(other_runs, (), lines.get(other, []))
            if current is None:
                continue
            for line in current.lines:
                if line.po_line_id is not None and line.quantity is not None:
                    totals[line.po_line_id] += line.quantity
        return dict(totals)

    def _finish(
        self, invoice_id: UUID, supplier_id: UUID, compute: ComputeResult
    ) -> bool:
        with open_connection(self._engine) as connection, connection.begin():
            lock_supplier(connection, supplier_id)
            result = compute(
                self._invoiced_elsewhere(connection, invoice_id, supplier_id),
                self._earlier(connection, invoice_id, supplier_id),
            )
            finish = result.finish
            if isinstance(finish, AdminRouting):
                done = self._invoices.route_in(connection, finish)
            else:
                done = self._invoices.transition_in(connection, finish)
            if not done:
                # The first write changed nothing, so nothing is written (AD-2).
                return False
            if result.matches:
                connection.execute(
                    update(invoice_line)
                    .where(
                        invoice_line.c.id == bindparam("line_id"),
                        invoice_line.c.invoice_id == invoice_id,
                    )
                    .values(
                        po_line_id=bindparam("po_line"),
                        material_id=bindparam("material"),
                    ),
                    [
                        {
                            "line_id": line_id,
                            "po_line": None if match is None else match.po_line_id,
                            "material": None if match is None else match.material_id,
                        }
                        for line_id, match in result.matches.items()
                    ],
                )
            connection.execute(
                update(invoice)
                .where(invoice.c.id == invoice_id)
                .values(po_number=result.po_number)
            )
            return True
