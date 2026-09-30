"""`AdminItemReader` over PostgreSQL (Story 2.9, AD-4, AD-11, AD-18).

`read` is one read-only snapshot: the queued invoice, its open reasons (the latest
`routing_id`, AD-4), its current fields and lines through the one AD-18 rule
(`domain/current_values.py`), its run's page sizes, when `BANK_CHANGED` is open, the
supplier's phone and the masks of each changed bank field, and when `DUPLICATE` is
open, the matching invoice it names (Story 3.3).

Bank values are decrypted only here, in SQL, with the `pgp-private-key` bound as a
parameter (the engine hides parameters from errors and logs, AD-11). The item read
computes only `right(pgp_pub_decrypt(...), 4)`, so no full value ever leaves the
database for it; `reveal` returns one full value, in the same transaction as its
`audit.event` row, which commits first. SQLAlchemy Core with bound parameters
(security.md rule 21).
"""

import asyncio
import logging
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

from sqlalchemy import (
    ColumnElement,
    Connection,
    Engine,
    case,
    exists,
    func,
    literal,
    select,
)
from sqlalchemy.exc import DBAPIError

from invoicing.adapters.key_vault import SecretReadError
from invoicing.adapters.logging import log_event
from invoicing.adapters.postgres.admin_queue import latest_routing
from invoicing.adapters.postgres.engine import open_connection
from invoicing.adapters.postgres.schema import (
    admin_item,
    extraction_page,
    extraction_run,
    invoice,
    invoice_field,
    invoice_line,
    status_history,
)
from invoicing.adapters.postgres.suppliers import (
    supplier,
    supplier_bank,
    write_audit,
)
from invoicing.domain.actions import addable_fields, allowed_actions, shown
from invoicing.domain.current_values import (
    ADMIN_SOURCE,
    CurrentValues,
    FieldValue,
    LineValue,
    RunRow,
    current_values,
)
from invoicing.domain.errors import ServiceUnavailableError
from invoicing.domain.extraction import PageSize, is_bank_field_id
from invoicing.domain.ids import parse_uuid
from invoicing.domain.reasons import ReasonCode
from invoicing.domain.status import InvoiceStatus
from invoicing.domain.validation import INVOICE_TOTAL, bare_bank_field_id
from invoicing.ports.admin_item import (
    AdminItem,
    BankChange,
    DuplicateOf,
    ItemField,
    ItemLine,
    ItemReason,
    RevealWhich,
)

# audit.event action of a bank value shown in full (UX-DR14).
BANK_REVEAL = "bank.reveal"
# UX-DR13: a masked value shows its last 4 characters only.
MASK_LENGTH = 4
# pgcrypto's error class for a wrong key or corrupt ciphertext.
EXTERNAL_ROUTINE_ERROR = "39000"
BANK_UNAVAILABLE = "Bank details can't be shown right now. Try again later."
# The reasons whose panel shows the supplier's phone number (UX-DR13, Story 2.10).
_PHONE_REASONS = frozenset(
    {
        ReasonCode.BANK_CHANGED.value,
        ReasonCode.UNREADABLE.value,
        ReasonCode.UNSUPPORTED_DOCUMENT.value,
    }
)

_logger = logging.getLogger("invoicing.admin_item")

type PrivateKeyProvider = Callable[[], str]


def _decrypted(ciphertext: ColumnElement[Any], private_key: str) -> Any:
    """SQL: the plaintext of `ciphertext` (the key is a bound parameter)."""
    return func.pgp_pub_decrypt(ciphertext, func.dearmor(private_key))


def _mask(ciphertext: ColumnElement[Any], private_key: str) -> Any:
    """SQL: the last 4 characters of the plaintext; the rest never leaves SQL. A
    value of 4 characters or fewer would be shown whole, so it gets '' instead: on
    file, but no digits (only an audited reveal shows it, AD-11)."""
    plaintext = _decrypted(ciphertext, private_key)
    return case(
        (func.length(plaintext) > MASK_LENGTH, func.right(plaintext, MASK_LENGTH)),
        else_=literal(""),
    )


def _queued(invoice_id: UUID) -> list[ColumnElement[bool]]:
    return [
        invoice.c.id == invoice_id,
        invoice.c.status == InvoiceStatus.IN_ADMIN_QUEUE.value,
    ]


def latest_routing_id(connection: Connection, invoice_id: UUID) -> UUID | None:
    """The invoice's latest `routing_id` (AD-4), None when it was never routed."""
    value: UUID | None = connection.execute(
        select(admin_item.c.routing_id)
        .where(admin_item.c.invoice_id == invoice_id)
        .order_by(admin_item.c.routing_id.desc())
        .limit(1)
    ).scalar_one_or_none()
    return value


def open_reasons(connection: Connection, invoice_id: UUID) -> list[ItemReason]:
    return [
        ItemReason(row.reason, tuple(row.field_ids), dict(row.detail or {}))
        for row in connection.execute(
            select(admin_item.c.reason, admin_item.c.field_ids, admin_item.c.detail)
            .where(
                admin_item.c.invoice_id == invoice_id,
                admin_item.c.routing_id == latest_routing(admin_item.c.invoice_id),
            )
            .order_by(admin_item.c.id)
        )
    ]


def quality_done(connection: Connection, invoice_id: UUID) -> bool:
    """Whether the quality stage ever completed: the invoice once moved from `received`
    to `awaiting_extraction` (Story 2.10: no image hash or photo date alone tells a PDF
    that passed from one that never ran)."""
    return bool(
        connection.execute(
            select(
                exists().where(
                    status_history.c.invoice_id == invoice_id,
                    status_history.c.from_status == InvoiceStatus.RECEIVED.value,
                    status_history.c.to_status
                    == InvoiceStatus.AWAITING_EXTRACTION.value,
                )
            )
        ).scalar_one()
    )


def _bank_field_ids(reasons: Iterable[ItemReason]) -> tuple[str, ...]:
    """The changed bank fields named by an open `BANK_CHANGED` (AD-19)."""
    return tuple(
        field_id
        for reason in reasons
        if reason.code == ReasonCode.BANK_CHANGED.value
        for field_id in reason.field_ids
        if is_bank_field_id(field_id)
    )


def _duplicate_id(reasons: Iterable[ItemReason]) -> UUID | None:
    """The matching invoice an open `DUPLICATE` names (`check_duplicate`'s detail
    `invoice_id`), None without one."""
    for reason in reasons:
        if reason.code == ReasonCode.DUPLICATE.value:
            value = reason.detail.get("invoice_id")
            return parse_uuid(value) if isinstance(value, str) else None
    return None


def _duplicate_of(connection: Connection, invoice_id: UUID) -> DuplicateOf | None:
    """The matching invoice's comparison facts; never a bank value (AD-11)."""
    head = connection.execute(
        select(
            invoice.c.created_at,
            invoice.c.content_type,
            supplier.c.name,
        )
        .select_from(
            invoice.outerjoin(supplier, supplier.c.id == invoice.c.supplier_id)
        )
        .where(invoice.c.id == invoice_id)
    ).one_or_none()
    if head is None:
        return None
    values = current_of(connection, invoice_id, INVOICE_TOTAL)
    total = None if values is None else values.fields.get(INVOICE_TOTAL)
    return DuplicateOf(
        invoice_id=invoice_id,
        received_at=head.created_at,
        content_type=head.content_type,
        supplier_name=head.name,
        invoice_total=None if total is None else shown(total),
        currency=None if total is None else total.currency,
    )


def _polygon(value: object) -> tuple[float, ...] | None:
    if not isinstance(value, list) or not all(
        isinstance(point, int | float) and not isinstance(point, bool)
        for point in value
    ):
        return None
    return tuple(float(point) for point in value)


def current_of(
    connection: Connection, invoice_id: UUID, field_id: str | None = None
) -> CurrentValues | None:
    """The invoice's AD-18 current values (only `field_id` and no lines when given),
    lines with every column (Story 2.10 writes a corrected line whole). Never reads a
    bank ciphertext."""
    runs = [
        RunRow(row.run_id, row.created_at)
        for row in connection.execute(
            select(extraction_run.c.run_id, extraction_run.c.created_at).where(
                extraction_run.c.invoice_id == invoice_id
            )
        )
    ]
    field_filter = [] if field_id is None else [invoice_field.c.field_id == field_id]
    fields = [
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
            bank_fingerprint=row.bank_fingerprint,
            currency=row.currency,
            page=row.page,
            polygon=_polygon(row.polygon),
        )
        for row in connection.execute(
            select(
                invoice_field.c.id,
                invoice_field.c.field_id,
                invoice_field.c.run_id,
                invoice_field.c.source,
                invoice_field.c.created_at,
                invoice_field.c.confidence,
                invoice_field.c.value_text,
                invoice_field.c.value_number,
                invoice_field.c.value_date,
                invoice_field.c.bank_fingerprint,
                invoice_field.c.currency,
                invoice_field.c.page,
                invoice_field.c.polygon,
            ).where(invoice_field.c.invoice_id == invoice_id, *field_filter)
        )
    ]
    lines: list[LineValue] = []
    if field_id is None:
        lines = [
            LineValue(
                id=row.id,
                line_no=row.line_no,
                run_id=row.run_id,
                source=row.source,
                created_at=row.created_at,
                confidence=row.confidence,
                product_code=row.product_code,
                description=row.description,
                quantity=row.quantity,
                unit_price=row.unit_price,
                amount=row.amount,
                po_line_id=row.po_line_id,
                unit=row.unit,
                tax=row.tax,
                material_id=row.material_id,
            )
            for row in connection.execute(
                select(
                    invoice_line.c.id,
                    invoice_line.c.line_no,
                    invoice_line.c.run_id,
                    invoice_line.c.source,
                    invoice_line.c.created_at,
                    invoice_line.c.confidence,
                    invoice_line.c.product_code,
                    invoice_line.c.description,
                    invoice_line.c.quantity,
                    invoice_line.c.unit_price,
                    invoice_line.c.amount,
                    invoice_line.c.po_line_id,
                    invoice_line.c.unit,
                    invoice_line.c.tax,
                    invoice_line.c.material_id,
                ).where(invoice_line.c.invoice_id == invoice_id)
            )
        ]
    return current_values(runs, fields, lines)


def _item_field(row: FieldValue, flagged: frozenset[str]) -> ItemField:
    bank = is_bank_field_id(row.field_id)
    return ItemField(
        field_id=row.field_id,
        # AD-11: a bank field has no plaintext column; its mask is in the bank panel.
        value=None if bank else shown(row),
        currency=row.currency,
        # AD-18: an admin correction counts as confidence 1.0.
        confidence=1.0 if row.source == ADMIN_SOURCE else row.confidence,
        page=row.page,
        polygon=row.polygon,
        flagged=row.field_id in flagged,
        bank=bank,
    )


def _item_line(line: LineValue) -> ItemLine:
    return ItemLine(
        line_no=line.line_no,
        confidence=1.0 if line.source == ADMIN_SOURCE else line.confidence,
        product_code=line.product_code,
        description=line.description,
        quantity=line.quantity,
        unit_price=line.unit_price,
        amount=line.amount,
    )


class PostgresAdminItemReader:
    """Admin items, on a worker thread (coding-style.md rule 11). `private_key` is
    called only when a bank value must be decrypted."""

    def __init__(self, engine: Engine, private_key: PrivateKeyProvider) -> None:
        self._engine = engine
        self._private_key = private_key

    async def read(self, invoice_id: UUID) -> AdminItem | None:
        return await asyncio.to_thread(self._read, invoice_id)

    async def content_type(self, invoice_id: UUID) -> str | None:
        return await asyncio.to_thread(self._content_type, invoice_id)

    async def duplicate_content_type(self, invoice_id: UUID) -> tuple[UUID, str] | None:
        return await asyncio.to_thread(self._duplicate_content_type, invoice_id)

    async def reveal(
        self,
        invoice_id: UUID,
        field_id: str,
        which: RevealWhich,
        admin_oid: str,
    ) -> str | None:
        return await asyncio.to_thread(
            self._reveal, invoice_id, field_id, which, admin_oid
        )

    # --- bank decryption ------------------------------------------------------------

    def _key(self) -> str:
        try:
            return self._private_key()
        except SecretReadError as error:
            log_event(
                _logger,
                "bank.key_unavailable",
                level=logging.ERROR,
                code=error.code,
            )
            raise ServiceUnavailableError(BANK_UNAVAILABLE) from None

    @contextmanager
    def _decrypting(self, invoice_id: UUID) -> Iterator[None]:
        """A wrong key or corrupt ciphertext becomes 503 with no value; the database's
        error text is never logged or chained."""
        try:
            yield
        except DBAPIError as error:
            if getattr(error.orig, "sqlstate", None) != EXTERNAL_ROUTINE_ERROR:
                raise
            log_event(
                _logger,
                "bank.decrypt_failed",
                level=logging.ERROR,
                invoice_id=invoice_id,
                code="DECRYPT_FAILED",
            )
            raise ServiceUnavailableError(BANK_UNAVAILABLE) from None

    # --- one transaction each ---------------------------------------------------------

    def _content_type(self, invoice_id: UUID) -> str | None:
        with open_connection(self._engine) as connection:
            value: str | None = connection.execute(
                select(invoice.c.content_type).where(*_queued(invoice_id))
            ).scalar_one_or_none()
        return value

    def _duplicate_content_type(self, invoice_id: UUID) -> tuple[UUID, str] | None:
        with open_connection(self._engine) as connection:
            queued = connection.execute(
                select(invoice.c.id).where(*_queued(invoice_id))
            ).scalar_one_or_none()
            if queued is None:
                return None
            # Only the invoice an open DUPLICATE names: the item image rule (queued
            # invoices only) is unchanged for every other invoice.
            other = _duplicate_id(open_reasons(connection, invoice_id))
            if other is None:
                return None
            content_type: str | None = connection.execute(
                select(invoice.c.content_type).where(invoice.c.id == other)
            ).scalar_one_or_none()
        return None if content_type is None else (other, content_type)

    def _read(self, invoice_id: UUID) -> AdminItem | None:
        with open_connection(self._engine) as connection:
            # One snapshot, so the reasons, fields and masks agree; read-only.
            connection.execution_options(
                isolation_level="REPEATABLE READ", postgresql_readonly=True
            )
            with connection.begin(), self._decrypting(invoice_id):
                return self._in_snapshot(connection, invoice_id)

    def _in_snapshot(
        self, connection: Connection, invoice_id: UUID
    ) -> AdminItem | None:
        head = connection.execute(
            select(
                invoice.c.created_at,
                invoice.c.content_type,
                invoice.c.supplier_id,
                invoice.c.accounts_ref,
            ).where(*_queued(invoice_id))
        ).one_or_none()
        if head is None:
            return None
        reasons = open_reasons(connection, invoice_id)
        flagged = frozenset(f for reason in reasons for f in reason.field_ids)
        values = current_of(connection, invoice_id)
        pages: tuple[PageSize, ...] = ()
        fields: tuple[ItemField, ...] = ()
        lines: tuple[ItemLine, ...] = ()
        if values is not None:
            pages = tuple(
                PageSize(row.page, row.width, row.height, row.unit)
                for row in connection.execute(
                    select(
                        extraction_page.c.page,
                        extraction_page.c.width,
                        extraction_page.c.height,
                        extraction_page.c.unit,
                    )
                    .where(extraction_page.c.run_id == values.run_id)
                    .order_by(extraction_page.c.page)
                )
            )
            fields = tuple(
                _item_field(values.fields[field_id], flagged)
                for field_id in sorted(values.fields)
            )
            lines = tuple(_item_line(line) for line in values.lines)
        master = connection.execute(
            select(supplier.c.name, supplier.c.phone).where(
                supplier.c.id == head.supplier_id
            )
        ).one_or_none()
        bank_ids = _bank_field_ids(reasons)
        changes: tuple[BankChange, ...] = ()
        if bank_ids:
            changes = self._bank_changes(connection, head.supplier_id, bank_ids, values)
        codes = [reason.code for reason in reasons]
        call_back = any(code in _PHONE_REASONS for code in codes)
        duplicate_id = _duplicate_id(reasons)
        actions = allowed_actions(
            codes,
            accounts_ref=head.accounts_ref is not None,
            quality_done=quality_done(connection, invoice_id),
        )
        return AdminItem(
            invoice_id=invoice_id,
            received_at=head.created_at,
            content_type=head.content_type,
            supplier_id=head.supplier_id,
            supplier_name=None if master is None else master.name,
            # UX-DR13: the number to call back when the bank details changed, or to ask
            # for the invoice again when it can't be read (Story 2.10).
            supplier_phone=master.phone if call_back and master is not None else None,
            reasons=tuple(reasons),
            fields=fields,
            lines=lines,
            pages=pages,
            bank_changes=changes,
            allowed_actions=tuple(action.value for action in actions),
            routing_id=latest_routing_id(connection, invoice_id),
            addable_fields=addable_fields(values),
            duplicate_of=None
            if duplicate_id is None
            else _duplicate_of(connection, duplicate_id),
        )

    def _bank_changes(
        self,
        connection: Connection,
        supplier_id: UUID,
        bank_ids: tuple[str, ...],
        values: CurrentValues | None,
    ) -> tuple[BankChange, ...]:
        key = self._key()
        rows = {} if values is None else values.fields
        row_ids = {
            rows[field_id].id: field_id for field_id in bank_ids if field_id in rows
        }
        new: dict[str, str] = {}
        if row_ids:
            for row in connection.execute(
                select(
                    invoice_field.c.id, _mask(invoice_field.c.bank_ciphertext, key)
                ).where(
                    invoice_field.c.id.in_(list(row_ids)),
                    invoice_field.c.bank_ciphertext.is_not(None),
                )
            ):
                new[row_ids[row[0]]] = row[1]
        on_file: dict[str, str] = {
            row[0]: row[1]
            for row in connection.execute(
                select(
                    supplier_bank.c.field_id, _mask(supplier_bank.c.ciphertext, key)
                ).where(
                    supplier_bank.c.supplier_id == supplier_id,
                    supplier_bank.c.field_id.in_(
                        sorted({bare_bank_field_id(f) for f in bank_ids})
                    ),
                )
            )
        }
        return tuple(
            BankChange(
                field_id=field_id,
                on_file=on_file.get(bare_bank_field_id(field_id)),
                new=new.get(field_id),
            )
            for field_id in bank_ids
        )

    def _reveal(
        self,
        invoice_id: UUID,
        field_id: str,
        which: RevealWhich,
        admin_oid: str,
    ) -> str | None:
        with (
            open_connection(self._engine) as connection,
            connection.begin(),
            self._decrypting(invoice_id),
        ):
            supplier_id = connection.execute(
                select(invoice.c.supplier_id).where(*_queued(invoice_id))
            ).scalar_one_or_none()
            if supplier_id is None:
                return None
            if field_id not in _bank_field_ids(open_reasons(connection, invoice_id)):
                return None
            value: str | None
            if which is RevealWhich.NEW:
                values = current_of(connection, invoice_id, field_id)
                row = None if values is None else values.fields.get(field_id)
                if row is None:
                    return None
                value = connection.execute(
                    select(
                        _decrypted(invoice_field.c.bank_ciphertext, self._key())
                    ).where(
                        invoice_field.c.id == row.id,
                        invoice_field.c.bank_ciphertext.is_not(None),
                    )
                ).scalar_one_or_none()
            else:
                value = connection.execute(
                    select(_decrypted(supplier_bank.c.ciphertext, self._key())).where(
                        supplier_bank.c.supplier_id == supplier_id,
                        supplier_bank.c.field_id == bare_bank_field_id(field_id),
                    )
                ).scalar_one_or_none()
            if value is None:
                return None
            # UX-DR14: every reveal is audited, ids only, never the value (AD-11). A
            # failed write rolls back and raises, so the value is never returned.
            write_audit(
                connection,
                BANK_REVEAL,
                "invoice",
                invoice_id,
                {"field_id": field_id, "which": which.value, "admin_oid": admin_oid},
            )
        return value
