"""`InvoiceRepository` over PostgreSQL (AD-3, AD-4, AD-5, AD-9).

Each method is one transaction. A transition is `UPDATE ... WHERE id = :id AND status
= :from` plus its `intake.status_history` row; zero rows changed writes nothing else.
The work runs on a worker thread, so the Functions event loop is never blocked by the
database (coding-style.md rule 11).
"""

import asyncio
import json
from collections.abc import Callable, Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Engine, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from invoicing.adapters.postgres.schema import (
    admin_item,
    image_hash,
    invoice,
    status_history,
)
from invoicing.domain.ids import new_uuid7
from invoicing.domain.status import InvoiceStatus
from invoicing.domain.transitions import AdminRouting, Transition
from invoicing.ports.invoices import NewInvoice, QualityFacts

_UINT64 = 1 << 64
_INT64_MAX = (1 << 63) - 1


def signed_phash(phash: int) -> int:
    """An unsigned 64-bit hash as the signed `bigint` PostgreSQL stores; the bits are
    unchanged, so Hamming distances stay the same (AD-9)."""
    if not 0 <= phash < _UINT64:
        raise ValueError("phash must be an unsigned 64-bit integer")
    return phash - _UINT64 if phash > _INT64_MAX else phash


def unsigned_phash(stored: int) -> int:
    """The unsigned 64-bit hash of a stored `bigint`."""
    return stored + _UINT64 if stored < 0 else stored


class _Discard(Exception):
    """Roll back the current transaction: the conditional transition changed nothing."""


def _json_default(value: object) -> str:
    # Ids, amounts (exact, as text: coding-style.md rule 4) and timestamps.
    if isinstance(value, UUID | Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    raise TypeError(f"{type(value).__name__} can't be stored in admin_item.detail")


def json_detail(detail: Mapping[str, object]) -> dict[str, Any]:
    """An admin item's `detail` as JSON values: UUIDs and Decimals as strings,
    dates and timestamps as ISO 8601."""
    converted: dict[str, Any] = json.loads(
        json.dumps(dict(detail), default=_json_default)
    )
    return converted


class PostgresInvoiceRepository:
    """The `intake` invoice tables, through SQLAlchemy Core with bound parameters."""

    def __init__(self, engine: Engine, new_id: Callable[[], UUID] = new_uuid7) -> None:
        self._engine = engine
        self._new_id = new_id

    async def status(self, invoice_id: UUID) -> InvoiceStatus | None:
        return await asyncio.to_thread(self._status, invoice_id)

    async def insert_if_absent(self, invoice: NewInvoice) -> bool:
        return await asyncio.to_thread(self._in_transaction, self._insert, invoice)

    async def transition(
        self, plan: Transition, *, quality: QualityFacts | None = None
    ) -> bool:
        return await asyncio.to_thread(
            self._in_transaction, self._transition, plan, quality
        )

    async def route_to_admin(
        self,
        routing: AdminRouting,
        *,
        metadata: NewInvoice | None = None,
        quality: QualityFacts | None = None,
    ) -> bool:
        return await asyncio.to_thread(
            self._in_transaction, self._route, routing, metadata, quality
        )

    # --- one transaction each ---------------------------------------------------------

    def _in_transaction(self, work: Callable[..., bool], *args: Any) -> bool:
        try:
            with self._engine.begin() as connection:
                return work(connection, *args)
        except _Discard:
            # Raised inside the transaction, so everything it wrote is rolled back.
            return False

    def _status(self, invoice_id: UUID) -> InvoiceStatus | None:
        with self._engine.connect() as connection:
            value = connection.execute(
                select(invoice.c.status).where(invoice.c.id == invoice_id)
            ).scalar_one_or_none()
        return None if value is None else InvoiceStatus(value)

    def _insert(self, connection: Connection, new: NewInvoice) -> bool:
        meta = new.metadata
        created = connection.execute(
            pg_insert(invoice)
            .values(
                id=meta.invoice_id,
                correlation_id=new.correlation_id,
                source=meta.source.value,
                supplier_id=meta.supplier_id,
                delivery_id=meta.delivery_id,
                content_type=meta.content_type.value,
                device_check=meta.device_check.value,
                status=InvoiceStatus.RECEIVED.value,
                status_changed_at=func.now(),
                post_failures=0,
                created_at=func.now(),
            )
            .on_conflict_do_nothing(index_elements=[invoice.c.id])
            .returning(invoice.c.id)
        ).first()
        if created is None:
            return False
        self._history(
            connection, meta.invoice_id, None, InvoiceStatus.RECEIVED, new.actor
        )
        return True

    def _transition(
        self,
        connection: Connection,
        plan: Transition,
        quality: QualityFacts | None,
        extra: dict[str, Any] | None = None,
    ) -> bool:
        values: dict[str, Any] = {
            "status": plan.to_status.value,
            "status_changed_at": func.now(),
            **(extra or {}),
        }
        if quality is not None:
            values["photo_taken_at"] = quality.photo_taken_at
        changed = connection.execute(
            update(invoice)
            .where(
                invoice.c.id == plan.invoice_id,
                invoice.c.status == plan.from_status.value,
            )
            .values(values)
            .returning(invoice.c.id)
        ).first()
        if changed is None:
            return False
        self._history(
            connection, plan.invoice_id, plan.from_status, plan.to_status, plan.actor
        )
        if quality is not None and quality.phash is not None:
            connection.execute(
                pg_insert(image_hash)
                .values(
                    invoice_id=plan.invoice_id,
                    phash=signed_phash(quality.phash),
                    created_at=func.now(),
                )
                .on_conflict_do_nothing(index_elements=[image_hash.c.invoice_id])
            )
        return True

    def _route(
        self,
        connection: Connection,
        routing: AdminRouting,
        metadata: NewInvoice | None,
        quality: QualityFacts | None,
    ) -> bool:
        if not routing.items:
            raise ValueError("a routing needs at least one admin item")
        if metadata is not None:
            if metadata.metadata.invoice_id != routing.transition.invoice_id:
                raise ValueError("the metadata is for another invoice")
            self._insert(connection, metadata)
        # An invoice waiting for an admin holds no lease (AD-3).
        if not self._transition(
            connection, routing.transition, quality, {"claimed_until": None}
        ):
            # The routing is discarded as a whole, including a row created above.
            raise _Discard
        connection.execute(
            insert(admin_item).values(created_at=func.now()),
            [
                {
                    "id": item.id,
                    "invoice_id": item.invoice_id,
                    "routing_id": item.routing_id,
                    "run_id": item.run_id,
                    "reason": item.reason.value,
                    "field_ids": list(item.field_ids),
                    "detail": json_detail(item.detail),
                }
                for item in routing.items
            ],
        )
        return True

    def _history(
        self,
        connection: Connection,
        invoice_id: UUID,
        from_status: InvoiceStatus | None,
        to_status: InvoiceStatus,
        actor: str,
    ) -> None:
        connection.execute(
            insert(status_history).values(
                id=self._new_id(),
                invoice_id=invoice_id,
                from_status=None if from_status is None else from_status.value,
                to_status=to_status.value,
                actor=actor,
                at=func.now(),
            )
        )
