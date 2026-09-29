"""`AdminQueueReader` over PostgreSQL (Story 2.8, AD-4, AD-8, AD-18).

One read, on one connection: the queued invoices matching the filters, oldest first,
with their open reasons (the `admin_item` rows of the latest `routing_id`, AD-4: a
UUIDv7, so the greatest is the latest), their supplier names and their current
`invoice_total` through the one AD-18 rule (`domain/current_values.py`); the number
matching; and this UTC month's DI pages. SELECT only, SQLAlchemy Core with bound
parameters (security.md rule 21). Bank fields are never read (AD-11).
"""

import asyncio
from collections import defaultdict
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, Connection, Engine, exists, func, select
from sqlalchemy.orm import aliased

from invoicing.adapters.postgres.engine import open_connection
from invoicing.adapters.postgres.extraction import utc_month
from invoicing.adapters.postgres.schema import (
    admin_item,
    di_usage,
    extraction_run,
    invoice,
    invoice_field,
)
from invoicing.adapters.postgres.suppliers import supplier_names
from invoicing.domain.current_values import FieldValue, RunRow, current_values
from invoicing.domain.status import InvoiceStatus
from invoicing.domain.validation import INVOICE_TOTAL
from invoicing.ports.admin_queue import (
    PAGE_SIZE,
    QueueListing,
    QueueQuery,
    QueueRow,
    QueueSupplier,
)


def latest_routing(invoice_id: ColumnElement[Any]) -> Any:
    """SQL: the latest `routing_id` of the invoice `invoice_id` (AD-4)."""
    latest = aliased(admin_item)
    return (
        select(latest.c.routing_id)
        .where(latest.c.invoice_id == invoice_id)
        .order_by(latest.c.routing_id.desc())
        .limit(1)
        .scalar_subquery()
    )


def _conditions(query: QueueQuery) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = [
        invoice.c.status == InvoiceStatus.IN_ADMIN_QUEUE.value
    ]
    if query.supplier_id is not None:
        conditions.append(invoice.c.supplier_id == query.supplier_id)
    if query.reason is not None:
        # Among the open reasons only: an earlier routing's reason is not open.
        conditions.append(
            exists().where(
                admin_item.c.invoice_id == invoice.c.id,
                # Correlated to this admin_item row, which is the invoice's.
                admin_item.c.routing_id == latest_routing(admin_item.c.invoice_id),
                admin_item.c.reason == query.reason.value,
            )
        )
    return conditions


class PostgresAdminQueueReader:
    """The admin queue list, on a worker thread (coding-style.md rule 11)."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    async def read(self, query: QueueQuery) -> QueueListing:
        return await asyncio.to_thread(self._read, query)

    def _read(self, query: QueueQuery) -> QueueListing:
        conditions = _conditions(query)
        with open_connection(self._engine) as connection:
            # One snapshot for every statement below, so the count, the page and its
            # reasons and amounts agree; read-only, since this endpoint never writes.
            connection.execution_options(
                isolation_level="REPEATABLE READ", postgresql_readonly=True
            )
            with connection.begin():
                return self._in_snapshot(connection, query, conditions)

    @staticmethod
    def _in_snapshot(
        connection: Connection,
        query: QueueQuery,
        conditions: list[ColumnElement[bool]],
    ) -> QueueListing:
        total = connection.execute(
            select(func.count()).select_from(invoice).where(*conditions)
        ).scalar_one()
        page = connection.execute(
            select(invoice.c.id, invoice.c.created_at, invoice.c.supplier_id)
            .where(*conditions)
            .order_by(invoice.c.created_at, invoice.c.id)
            .offset(query.offset)
            .limit(PAGE_SIZE)
        ).all()
        pages_used = connection.execute(
            select(di_usage.c.pages).where(di_usage.c.month == utc_month(func.now()))
        ).scalar_one_or_none()
        ids = [row.id for row in page]
        reasons: dict[UUID, list[str]] = defaultdict(list)
        runs: dict[UUID, list[RunRow]] = defaultdict(list)
        totals: dict[UUID, list[FieldValue]] = defaultdict(list)
        if ids:
            for item in connection.execute(
                select(admin_item.c.invoice_id, admin_item.c.reason)
                .where(
                    admin_item.c.invoice_id.in_(ids),
                    admin_item.c.routing_id == latest_routing(admin_item.c.invoice_id),
                )
                .order_by(admin_item.c.id)
            ):
                reasons[item.invoice_id].append(item.reason)
            for run in connection.execute(
                select(
                    extraction_run.c.invoice_id,
                    extraction_run.c.run_id,
                    extraction_run.c.created_at,
                ).where(extraction_run.c.invoice_id.in_(ids))
            ):
                runs[run.invoice_id].append(RunRow(run.run_id, run.created_at))
            for field in connection.execute(
                select(
                    invoice_field.c.id,
                    invoice_field.c.invoice_id,
                    invoice_field.c.field_id,
                    invoice_field.c.run_id,
                    invoice_field.c.source,
                    invoice_field.c.created_at,
                    invoice_field.c.confidence,
                    invoice_field.c.value_number,
                ).where(
                    invoice_field.c.invoice_id.in_(ids),
                    invoice_field.c.field_id == INVOICE_TOTAL,
                )
            ):
                totals[field.invoice_id].append(
                    FieldValue(
                        id=field.id,
                        field_id=field.field_id,
                        run_id=field.run_id,
                        source=field.source,
                        created_at=field.created_at,
                        confidence=field.confidence,
                        value_number=field.value_number,
                    )
                )
        # The supplier filter's options: every queued invoice's supplier, whatever
        # the filters.
        queued = [
            row.supplier_id
            for row in connection.execute(
                select(invoice.c.supplier_id)
                .distinct()
                .where(invoice.c.status == InvoiceStatus.IN_ADMIN_QUEUE.value)
            )
        ]
        names = supplier_names(connection, queued)
        rows = []
        for row in page:
            values = current_values(runs.get(row.id, []), totals.get(row.id, []), ())
            total_field = None if values is None else values.fields.get(INVOICE_TOTAL)
            rows.append(
                QueueRow(
                    invoice_id=row.id,
                    received_at=row.created_at,
                    supplier_id=row.supplier_id,
                    supplier_name=names.get(row.supplier_id),
                    invoice_total=None
                    if total_field is None
                    else total_field.value_number,
                    reasons=tuple(reasons.get(row.id, [])),
                )
            )
        suppliers = sorted(
            (
                QueueSupplier(supplier_id, names.get(supplier_id))
                for supplier_id in queued
            ),
            key=lambda s: (s.name is None, s.name or "", str(s.supplier_id)),
        )
        return QueueListing(
            rows=tuple(rows),
            total=total,
            pages_used=pages_used or 0,
            suppliers=tuple(suppliers),
        )
