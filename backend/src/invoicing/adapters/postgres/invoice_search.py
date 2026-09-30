"""`InvoiceSearchReader` over PostgreSQL (Story 3.4, AD-3, AD-11, AD-18).

Each call is one read-only snapshot. Current values come through the one AD-18 rule
(`domain/current_values.py`, via `current_of` for a detail). A supplier reference
matches the invoice id's low 40 bits in SQL (`substring(uuid_send(id) from 12 for
5)`); an invoice number is narrowed in SQL on any stored row, then kept only when the
AD-18 current value matches, so a corrected number is found by its new value only.
Bank ciphertexts are never selected (AD-11). SELECT only, SQLAlchemy Core with bound
parameters (security.md rule 21).
"""

import asyncio
from collections import defaultdict
from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import (
    ColumnElement,
    Connection,
    Engine,
    LargeBinary,
    func,
    or_,
    select,
    type_coerce,
)

from invoicing.adapters.postgres.admin_item import current_of
from invoicing.adapters.postgres.engine import open_connection
from invoicing.adapters.postgres.schema import (
    extraction_run,
    invoice,
    invoice_field,
    invoice_line,
    status_history,
)
from invoicing.adapters.postgres.suppliers import supplier, supplier_names
from invoicing.domain.actions import shown
from invoicing.domain.current_values import (
    ADMIN_SOURCE,
    CurrentValues,
    FieldValue,
    RunRow,
    current_values,
)
from invoicing.domain.extraction import is_bank_field_id
from invoicing.domain.reference import REFERENCE_BYTES, parse_reference
from invoicing.domain.validation import (
    INVOICE_NUMBER,
    INVOICE_TOTAL,
    normalise_invoice_number,
)
from invoicing.ports.invoice_search import (
    PAGE_SIZE,
    DetailField,
    DetailLine,
    HistoryEntry,
    InvoiceDetail,
    SearchListing,
    SearchQuery,
    SearchRow,
    SearchSupplier,
)

# `uuid_send` gives the 16 bytes; the reference is the last 5 (from byte 12, 1-based).
_REFERENCE_START = 16 - REFERENCE_BYTES + 1
# The SQL twin of `normalise_invoice_number`, for narrowing only: the Python rule
# decides.
_NOT_ALPHANUMERIC = "[^0-9A-Z]"


def _reference_of(id_column: ColumnElement[UUID]) -> ColumnElement[bytes]:
    return type_coerce(
        func.substring(func.uuid_send(id_column), _REFERENCE_START, REFERENCE_BYTES),
        LargeBinary,
    )


def _current(
    connection: Connection, ids: list[UUID], field_ids: Iterable[str]
) -> dict[UUID, CurrentValues]:
    """The AD-18 current values of `field_ids` (no lines) of each invoice in `ids`
    that has a run."""
    if not ids:
        return {}
    runs: dict[UUID, list[RunRow]] = defaultdict(list)
    for run in connection.execute(
        select(
            extraction_run.c.invoice_id,
            extraction_run.c.run_id,
            extraction_run.c.created_at,
        ).where(extraction_run.c.invoice_id.in_(ids))
    ):
        runs[run.invoice_id].append(RunRow(run.run_id, run.created_at))
    fields: dict[UUID, list[FieldValue]] = defaultdict(list)
    for row in connection.execute(
        select(
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
            invoice_field.c.currency,
        ).where(
            invoice_field.c.invoice_id.in_(ids),
            invoice_field.c.field_id.in_(list(field_ids)),
        )
    ):
        fields[row.invoice_id].append(
            FieldValue(
                id=row.id,
                field_id=row.field_id,
                run_id=row.run_id,
                source=row.source,
                created_at=row.created_at,
                confidence=row.confidence,
                value_text=row.value_text,
                value_number=row.value_number,
                value_date=row.value_date,
                currency=row.currency,
            )
        )
    result: dict[UUID, CurrentValues] = {}
    for invoice_id in ids:
        values = current_values(
            runs.get(invoice_id, []), fields.get(invoice_id, []), ()
        )
        if values is not None:
            result[invoice_id] = values
    return result


def _corrected(connection: Connection, current: dict[UUID, CurrentValues]) -> set[UUID]:
    """The invoices whose current run holds an admin row (Story 2.10: "Re-checking")."""
    if not current:
        return set()
    pairs: set[tuple[UUID, UUID]] = set()
    for table in (invoice_field, invoice_line):
        pairs.update(
            (row.invoice_id, row.run_id)
            for row in connection.execute(
                select(table.c.invoice_id, table.c.run_id)
                .distinct()
                .where(
                    table.c.invoice_id.in_(list(current)),
                    table.c.source == ADMIN_SOURCE,
                )
            )
        )
    return {
        invoice_id
        for invoice_id, values in current.items()
        if (invoice_id, values.run_id) in pairs
    }


def _number_matches(connection: Connection, number: str) -> list[UUID]:
    """The invoices whose AD-18 current `invoice_number` normalises to `number`."""
    candidates: list[UUID] = list(
        connection.execute(
            select(invoice_field.c.invoice_id)
            .distinct()
            .where(
                invoice_field.c.field_id == INVOICE_NUMBER,
                func.regexp_replace(
                    func.upper(invoice_field.c.value_text), _NOT_ALPHANUMERIC, "", "g"
                )
                == number,
            )
        ).scalars()
    )
    current = _current(connection, candidates, (INVOICE_NUMBER,))
    matches = []
    for invoice_id, values in current.items():
        row = values.fields.get(INVOICE_NUMBER)
        text = None if row is None else shown(row)
        if text is not None and normalise_invoice_number(text) == number:
            matches.append(invoice_id)
    return matches


def _text_matches(connection: Connection, text: str) -> ColumnElement[bool]:
    """The one-box search: the invoice's supplier reference, its normalised invoice
    number, or a supplier whose master name contains `text` (any case)."""
    matches: list[ColumnElement[bool]] = [
        invoice.c.supplier_id.in_(
            select(supplier.c.id).where(
                # A bound parameter with LIKE's wildcards escaped.
                supplier.c.name.icontains(text, autoescape=True)
            )
        )
    ]
    reference = parse_reference(text)
    if reference is not None:
        matches.append(
            _reference_of(invoice.c.id) == type_coerce(reference, LargeBinary)
        )
    number = normalise_invoice_number(text)
    if number:
        matches.append(invoice.c.id.in_(_number_matches(connection, number)))
    return or_(*matches)


def _conditions(
    connection: Connection, query: SearchQuery
) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []
    if query.supplier_id is not None:
        conditions.append(invoice.c.supplier_id == query.supplier_id)
    if query.statuses:
        conditions.append(
            invoice.c.status.in_(sorted(status.value for status in query.statuses))
        )
    if query.reference is not None:
        conditions.append(
            _reference_of(invoice.c.id) == type_coerce(query.reference, LargeBinary)
        )
    if query.invoice_number is not None:
        conditions.append(
            invoice.c.id.in_(_number_matches(connection, query.invoice_number))
        )
    if query.text is not None:
        conditions.append(_text_matches(connection, query.text))
    return conditions


class PostgresInvoiceSearchReader:
    """Invoice search and detail, on a worker thread (coding-style.md rule 11)."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    async def search(self, query: SearchQuery) -> SearchListing:
        return await asyncio.to_thread(self._search, query)

    async def detail(self, invoice_id: UUID) -> InvoiceDetail | None:
        return await asyncio.to_thread(self._detail, invoice_id)

    def _search(self, query: SearchQuery) -> SearchListing:
        with open_connection(self._engine) as connection:
            # One snapshot, so the count, the page and its values agree; read-only.
            connection.execution_options(
                isolation_level="REPEATABLE READ", postgresql_readonly=True
            )
            with connection.begin():
                return self._search_in(connection, query)

    @staticmethod
    def _search_in(connection: Connection, query: SearchQuery) -> SearchListing:
        conditions = _conditions(connection, query)
        total = connection.execute(
            select(func.count()).select_from(invoice).where(*conditions)
        ).scalar_one()
        page = connection.execute(
            select(
                invoice.c.id,
                invoice.c.created_at,
                invoice.c.supplier_id,
                invoice.c.status,
            )
            .where(*conditions)
            .order_by(invoice.c.created_at.desc(), invoice.c.id.desc())
            .offset(query.offset)
            .limit(PAGE_SIZE)
        ).all()
        current = _current(
            connection, [row.id for row in page], (INVOICE_NUMBER, INVOICE_TOTAL)
        )
        corrected = _corrected(connection, current)
        # The supplier filter's options: every invoice's supplier, whatever the
        # filters.
        known: list[UUID] = list(
            connection.execute(select(invoice.c.supplier_id).distinct()).scalars()
        )
        names = supplier_names(connection, known)
        rows = []
        for row in page:
            values = current.get(row.id)
            number = None if values is None else values.fields.get(INVOICE_NUMBER)
            amount = None if values is None else values.fields.get(INVOICE_TOTAL)
            rows.append(
                SearchRow(
                    invoice_id=row.id,
                    received_at=row.created_at,
                    supplier_id=row.supplier_id,
                    supplier_name=names.get(row.supplier_id),
                    invoice_number=None if number is None else shown(number),
                    invoice_total=None if amount is None else amount.value_number,
                    currency=None if amount is None else amount.currency,
                    status=row.status,
                    after_correction=row.id in corrected,
                )
            )
        suppliers = sorted(
            (
                SearchSupplier(supplier_id, names.get(supplier_id))
                for supplier_id in known
            ),
            key=lambda s: (s.name is None, s.name or "", str(s.supplier_id)),
        )
        return SearchListing(rows=tuple(rows), total=total, suppliers=tuple(suppliers))

    def _detail(self, invoice_id: UUID) -> InvoiceDetail | None:
        with open_connection(self._engine) as connection:
            connection.execution_options(
                isolation_level="REPEATABLE READ", postgresql_readonly=True
            )
            with connection.begin():
                return self._detail_in(connection, invoice_id)

    @staticmethod
    def _detail_in(connection: Connection, invoice_id: UUID) -> InvoiceDetail | None:
        head = connection.execute(
            select(
                invoice.c.created_at,
                invoice.c.supplier_id,
                invoice.c.status,
                invoice.c.accounts_ref,
                invoice.c.posted_at,
            ).where(invoice.c.id == invoice_id)
        ).one_or_none()
        if head is None:
            return None
        # Never selects a bank ciphertext; bank fields are dropped below (AD-11).
        values = current_of(connection, invoice_id)
        fields: list[DetailField] = []
        lines: tuple[DetailLine, ...] = ()
        bank_on_file = False
        if values is not None:
            for field_id in sorted(values.fields):
                row = values.fields[field_id]
                if is_bank_field_id(field_id):
                    bank_on_file = True
                    continue
                fields.append(
                    DetailField(field_id, shown(row), row.currency, row.value_number)
                )
            lines = tuple(
                DetailLine(
                    line_no=line.line_no,
                    product_code=line.product_code,
                    description=line.description,
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                    amount=line.amount,
                )
                for line in values.lines
            )
        history = tuple(
            HistoryEntry(row.from_status, row.to_status, row.at, row.actor)
            for row in connection.execute(
                select(
                    status_history.c.from_status,
                    status_history.c.to_status,
                    status_history.c.at,
                    status_history.c.actor,
                )
                .where(status_history.c.invoice_id == invoice_id)
                .order_by(status_history.c.at, status_history.c.id)
            )
        )
        corrected = (
            False
            if values is None
            else bool(_corrected(connection, {invoice_id: values}))
        )
        return InvoiceDetail(
            invoice_id=invoice_id,
            received_at=head.created_at,
            supplier_id=head.supplier_id,
            supplier_name=supplier_names(connection, [head.supplier_id]).get(
                head.supplier_id
            ),
            status=head.status,
            after_correction=corrected,
            accounts_ref=head.accounts_ref,
            posted_at=head.posted_at,
            fields=tuple(fields),
            lines=lines,
            bank_on_file=bank_on_file,
            history=history,
        )
