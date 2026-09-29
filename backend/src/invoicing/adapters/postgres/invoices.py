"""`InvoiceRepository` over PostgreSQL (AD-2, AD-3, AD-4, AD-5, AD-9).

Each method is one transaction. A method that can't connect raises
`DatabaseOfflineError` (engine.open_connection, AD-7). A transition is `UPDATE ...
WHERE id = :id AND status = :from` plus its `intake.status_history` row; zero rows
changed writes nothing else.
The work runs on a worker thread, so the Functions event loop is never blocked by the
database (coding-style.md rule 11).
"""

import asyncio
import json
from collections.abc import Callable, Collection, Mapping
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    TIMESTAMP,
    ColumnElement,
    Connection,
    Engine,
    and_,
    false,
    func,
    insert,
    literal,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert

from invoicing.adapters.postgres.engine import open_connection
from invoicing.adapters.postgres.schema import (
    admin_item,
    image_hash,
    invoice,
    status_history,
)
from invoicing.domain.ids import new_uuid7
from invoicing.domain.status import InvoiceStatus, Stage
from invoicing.domain.sweep import (
    BACKOFF_STATUSES,
    LEASED_STATUSES,
    sweep_statuses,
)
from invoicing.domain.transitions import AdminRouting, Claim, Transition, claim_from
from invoicing.ports.invoices import (
    InvoiceState,
    NewInvoice,
    QualityFacts,
    StaleInvoice,
    StaleScan,
)

# Ids per `existing` query.
EXISTING_CHUNK = 500

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


def _sweepable(stages: frozenset[Stage]) -> ColumnElement[bool]:
    """The `domain.sweep` map as SQL, from its constants: a status that goes to one of
    `stages`, a claim status only with an expired lease, a backoff status only once
    it is due. `sweep_stage` checks each row again."""
    lease_over = or_(
        invoice.c.claimed_until.is_(None), invoice.c.claimed_until <= func.now()
    )
    due = or_(
        invoice.c.next_attempt_at.is_(None), invoice.c.next_attempt_at <= func.now()
    )
    per_status = []
    for status in sorted(sweep_statuses(stages)):
        condition: ColumnElement[bool] = invoice.c.status == status.value
        if status in LEASED_STATUSES:
            condition = and_(condition, lease_over)
        if status in BACKOFF_STATUSES:
            condition = and_(condition, due)
        per_status.append(condition)
    return or_(false(), *per_status)


class PostgresInvoiceRepository:
    """The `intake` invoice tables, through SQLAlchemy Core with bound parameters."""

    def __init__(
        self,
        engine: Engine,
        new_id: Callable[[], UUID] = new_uuid7,
        *,
        database_started_at: datetime | None = None,
    ) -> None:
        self._engine = engine
        self._new_id = new_id
        # Test seam only: stands in for pg_postmaster_start_time() in `stale`, so a
        # test can make a fresh container look long-running (AD-2 restart guard).
        self._database_started_at = database_started_at

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

    async def state(self, invoice_id: UUID) -> InvoiceState | None:
        return await asyncio.to_thread(self._state, invoice_id)

    async def claim(self, claim: Claim) -> bool:
        return await asyncio.to_thread(self._in_transaction, self._claim, claim)

    async def release_claim(self, claim: Claim) -> bool:
        return await asyncio.to_thread(self._in_transaction, self._release, claim)

    async def stale(
        self, stale_after: timedelta, *, stages: frozenset[Stage], limit: int
    ) -> StaleScan:
        return await asyncio.to_thread(self._stale, stale_after, stages, limit)

    async def existing(self, invoice_ids: Collection[UUID]) -> frozenset[UUID]:
        if not invoice_ids:
            return frozenset()
        return await asyncio.to_thread(self._existing, list(invoice_ids))

    # --- one transaction each ---------------------------------------------------------

    def _in_transaction(self, work: Callable[..., bool], *args: Any) -> bool:
        try:
            with open_connection(self._engine) as connection, connection.begin():
                return work(connection, *args)
        except _Discard:
            # Raised inside the transaction, so everything it wrote is rolled back.
            return False

    def transition_in(self, connection: Connection, plan: Transition) -> bool:
        """Run `plan` inside the caller's transaction, ending any lease: the target is
        a waiting status (Story 2.3 saves a run with it, AD-3 save-before-finish)."""
        return self._transition(connection, plan, None, {"claimed_until": None})

    def _release(self, connection: Connection, claim: Claim) -> bool:
        released = connection.execute(
            update(invoice)
            .where(
                invoice.c.id == claim.invoice_id,
                invoice.c.status == claim.claim_status.value,
            )
            .values(claimed_until=func.now())
            .returning(invoice.c.id)
        ).first()
        return released is not None

    def _status(self, invoice_id: UUID) -> InvoiceStatus | None:
        with open_connection(self._engine) as connection:
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
        conditions = [
            invoice.c.id == plan.invoice_id,
            invoice.c.status == plan.from_status.value,
        ]
        if plan.require_expired_lease:
            # AD-2: a live claim is never taken (a missing lease counts as expired).
            conditions.append(
                or_(
                    invoice.c.claimed_until.is_(None),
                    invoice.c.claimed_until <= func.now(),
                )
            )
        changed = connection.execute(
            update(invoice).where(*conditions).values(values).returning(invoice.c.id)
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

    def _state(self, invoice_id: UUID) -> InvoiceState | None:
        with open_connection(self._engine) as connection:
            row = connection.execute(
                select(
                    invoice.c.status,
                    invoice.c.claimed_until,
                    func.now(),
                    invoice.c.next_attempt_at,
                ).where(invoice.c.id == invoice_id)
            ).first()
        if row is None:
            return None
        return InvoiceState(InvoiceStatus(row[0]), row[1], row[2], row[3])

    def _claim(self, connection: Connection, claim: Claim) -> bool:
        # The row is locked, so the check and the update see the same lease (AD-3).
        row = connection.execute(
            select(
                invoice.c.status,
                invoice.c.claimed_until,
                invoice.c.next_attempt_at,
                func.now(),
            )
            .where(invoice.c.id == claim.invoice_id)
            .with_for_update()
        ).first()
        if row is None:
            return False
        from_status = claim_from(
            claim,
            InvoiceStatus(row[0]),
            claimed_until=row[1],
            next_attempt_at=row[2],
            now=row[3],
        )
        if from_status is None:
            return False
        values: dict[str, Any] = {"claimed_until": func.now() + claim.lease}
        if from_status is not claim.claim_status:
            values["status"] = claim.claim_status.value
            values["status_changed_at"] = func.now()
        connection.execute(
            update(invoice)
            .where(
                invoice.c.id == claim.invoice_id,
                invoice.c.status == from_status.value,
            )
            .values(values)
        )
        # A reclaim renews the lease only: the status did not change, so there is no
        # history row (AD-3 history records status changes).
        if from_status is not claim.claim_status:
            self._history(
                connection,
                claim.invoice_id,
                from_status,
                claim.claim_status,
                claim.actor,
            )
        return True

    def _stale(
        self, stale_after: timedelta, stages: frozenset[Stage], limit: int
    ) -> StaleScan:
        started = (
            literal(self._database_started_at, TIMESTAMP(timezone=True))
            if self._database_started_at is not None
            else func.pg_postmaster_start_time()
        )
        with open_connection(self._engine) as connection:
            now, settled = connection.execute(
                select(func.now(), started < func.now() - stale_after)
            ).one()
            if not settled:
                return StaleScan(now=now, settled=False, invoices=())
            rows = connection.execute(
                select(
                    invoice.c.id,
                    invoice.c.correlation_id,
                    invoice.c.status,
                    invoice.c.claimed_until,
                    invoice.c.next_attempt_at,
                    invoice.c.created_at,
                )
                .where(
                    _sweepable(stages),
                    # now() is the transaction's start, the same as above.
                    invoice.c.status_changed_at < func.now() - stale_after,
                )
                # Oldest first (ix_invoice_status_changed), so a capped sweep is fair.
                .order_by(invoice.c.status_changed_at, invoice.c.id)
                .limit(limit)
            ).all()
        return StaleScan(
            now=now,
            settled=True,
            invoices=tuple(
                StaleInvoice(
                    invoice_id=row[0],
                    correlation_id=row[1],
                    status=InvoiceStatus(row[2]),
                    claimed_until=row[3],
                    next_attempt_at=row[4],
                    created_at=row[5],
                )
                for row in rows
            ),
        )

    def _existing(self, invoice_ids: list[UUID]) -> frozenset[UUID]:
        found: set[UUID] = set()
        with open_connection(self._engine) as connection:
            # Bounded IN lists, however many ids the sweeper passes.
            for start in range(0, len(invoice_ids), EXISTING_CHUNK):
                chunk = invoice_ids[start : start + EXISTING_CHUNK]
                found.update(
                    connection.execute(
                        select(invoice.c.id).where(invoice.c.id.in_(chunk))
                    ).scalars()
                )
        return frozenset(found)

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
