"""`AdminActions` over PostgreSQL (Stories 2.10 and 3.3, AD-3, AD-4, AD-11, AD-18).

Each action is one transaction: the invoice row is locked, the `domain/actions.py`
guard is re-checked on its open reasons (the latest `routing_id`), then the
conditional transition from `in_admin_queue` runs first (`PostgresInvoiceRepository.
transition_in`: zero rows means another admin acted first, and nothing is written),
then the action's rows and its `audit.event` row. Admin rows are always new
`source=admin` rows on the latest run, never updates (AD-18; the grants allow only
INSERT). The audit detail holds ids and the admin's object id, never a field value;
Reject's and Approve's reasons are the only free text, and they are written only
there. Approve's call-back checks are re-checked on the open reasons, before the
transition, and recorded with it (AD-11). SQLAlchemy Core
with bound parameters (security.md rule 21).
"""

import asyncio
from collections.abc import Callable, Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Engine, func, insert, select

from invoicing.adapters.postgres.admin_item import (
    current_of,
    latest_routing_id,
    open_reasons,
    quality_done,
)
from invoicing.adapters.postgres.engine import open_connection
from invoicing.adapters.postgres.invoices import PostgresInvoiceRepository
from invoicing.adapters.postgres.schema import invoice, invoice_field, invoice_line
from invoicing.adapters.postgres.suppliers import write_audit
from invoicing.domain.actions import (
    APPROVE_CHECKS,
    AUDIT_ACTION,
    TARGET_STATUS,
    AdminAction,
    Correction,
    LineEdits,
    allowed_actions,
    checks_missing,
    plan_correction,
)
from invoicing.domain.current_values import ADMIN_SOURCE
from invoicing.domain.ids import new_uuid7
from invoicing.domain.status import InvoiceStatus
from invoicing.domain.transitions import plan_transition
from invoicing.ports.admin_actions import ActionResult, Outcome

# AD-18: an admin correction counts as confidence 1.0.
ADMIN_CONFIDENCE = 1.0


class _Abort(Exception):
    """Roll the transaction back and answer `outcome`."""

    def __init__(self, outcome: Outcome) -> None:
        super().__init__(outcome.value)
        self.outcome = outcome


# An action's own rows; returns its audit detail (plus Correct's `correction`).
type _Work = Callable[[Connection], dict[str, object]]
# An action's own refusal on the open reason codes, before anything is written.
type _Gate = Callable[[list[str]], Outcome | None]


class PostgresAdminActions:
    """The admin actions, on a worker thread (coding-style.md rule 11). `currency` is
    the invoice currency (AD-8), for an amount added where none was read."""

    def __init__(
        self,
        engine: Engine,
        *,
        currency: str,
        new_id: Callable[[], UUID] = new_uuid7,
    ) -> None:
        self._engine = engine
        self._currency = currency
        self._new_id = new_id
        self._invoices = PostgresInvoiceRepository(engine, new_id)

    async def correct(
        self,
        invoice_id: UUID,
        fields: Mapping[str, str],
        lines: LineEdits,
        admin_oid: str,
        routing_id: UUID | None,
    ) -> ActionResult:
        def work(connection: Connection) -> dict[str, object]:
            values = current_of(connection, invoice_id)
            if values is None:
                # Nothing was ever read, so there is no run to correct.
                raise _Abort(Outcome.NOT_ALLOWED)
            correction = plan_correction(values, fields, lines, currency=self._currency)
            self._write_correction(connection, invoice_id, correction)
            return {
                "run_id": str(correction.run_id),
                "field_ids": [f.field_id for f in correction.fields],
                "line_nos": [line.line_no for line in correction.lines],
                "correction": correction,
            }

        return await asyncio.to_thread(
            self._act, AdminAction.CORRECT, invoice_id, admin_oid, routing_id, work
        )

    async def reextract(
        self, invoice_id: UUID, admin_oid: str, routing_id: UUID | None
    ) -> ActionResult:
        return await asyncio.to_thread(
            self._act,
            AdminAction.REEXTRACT,
            invoice_id,
            admin_oid,
            routing_id,
            _no_rows,
        )

    async def retry_intake(
        self, invoice_id: UUID, admin_oid: str, routing_id: UUID | None
    ) -> ActionResult:
        return await asyncio.to_thread(
            self._act,
            AdminAction.RETRY_INTAKE,
            invoice_id,
            admin_oid,
            routing_id,
            _no_rows,
        )

    async def reject(
        self, invoice_id: UUID, reason: str, admin_oid: str, routing_id: UUID | None
    ) -> ActionResult:
        def work(connection: Connection) -> dict[str, object]:
            # UX-DR12: the reason is audited, and never logged.
            return {"reason": reason}

        return await asyncio.to_thread(
            self._act, AdminAction.REJECT, invoice_id, admin_oid, routing_id, work
        )

    async def approve(
        self,
        invoice_id: UUID,
        reason: str,
        checks: Mapping[str, bool],
        admin_oid: str,
        routing_id: UUID | None,
    ) -> ActionResult:
        confirmed = {check: checks.get(check) is True for check in APPROVE_CHECKS}

        def gate(codes: list[str]) -> Outcome | None:
            # AD-11: enforced here, not only by the screen's checklist.
            if checks_missing(codes, confirmed):
                return Outcome.CHECKS_REQUIRED
            return None

        def work(connection: Connection) -> dict[str, object]:
            # UX-DR12: the reason is audited, and never logged.
            return {"reason": reason, "checks": confirmed}

        return await asyncio.to_thread(
            self._act,
            AdminAction.APPROVE,
            invoice_id,
            admin_oid,
            routing_id,
            work,
            gate,
        )

    # --- one transaction ------------------------------------------------------------

    def _act(
        self,
        action: AdminAction,
        invoice_id: UUID,
        admin_oid: str,
        routing_id: UUID | None,
        work: _Work,
        gate: _Gate | None = None,
    ) -> ActionResult:
        try:
            with open_connection(self._engine) as connection, connection.begin():
                return self._in_transaction(
                    connection, action, invoice_id, admin_oid, routing_id, work, gate
                )
        except _Abort as abort:
            # Raised inside the transaction, so everything it wrote is rolled back.
            return ActionResult(abort.outcome)

    def _in_transaction(
        self,
        connection: Connection,
        action: AdminAction,
        invoice_id: UUID,
        admin_oid: str,
        routing_id: UUID | None,
        work: _Work,
        gate: _Gate | None,
    ) -> ActionResult:
        # Locked, so the open reasons can't change under the guard: a routing moves the
        # invoice row too (AD-4).
        head = connection.execute(
            select(
                invoice.c.status,
                invoice.c.accounts_ref,
                invoice.c.correlation_id,
                func.now(),
            )
            .where(invoice.c.id == invoice_id)
            .with_for_update()
        ).one_or_none()
        if head is None:
            return ActionResult(Outcome.NOT_FOUND)
        if head.status != InvoiceStatus.IN_ADMIN_QUEUE.value:
            return ActionResult(Outcome.CONFLICT)
        if latest_routing_id(connection, invoice_id) != routing_id:
            # Routed again since the admin opened it: their page is stale.
            return ActionResult(Outcome.CONFLICT)
        codes = [reason.code for reason in open_reasons(connection, invoice_id)]
        allowed = allowed_actions(
            codes,
            accounts_ref=head.accounts_ref is not None,
            quality_done=quality_done(connection, invoice_id),
        )
        if action not in allowed:
            return ActionResult(Outcome.NOT_ALLOWED)
        refused = None if gate is None else gate(codes)
        if refused is not None:
            return ActionResult(refused)
        plan = plan_transition(
            invoice_id,
            InvoiceStatus.IN_ADMIN_QUEUE,
            TARGET_STATUS[action],
            actor=f"admin:{admin_oid}",
        )
        # AD-3: the conditional transition first; zero rows writes nothing else.
        if not self._invoices.transition_in(connection, plan):
            raise _Abort(Outcome.CONFLICT)
        detail = work(connection)
        correction = detail.pop("correction", None)
        write_audit(
            connection,
            AUDIT_ACTION[action],
            "invoice",
            invoice_id,
            {**detail, "admin_oid": admin_oid},
        )
        return ActionResult(
            Outcome.HANDLED,
            correlation_id=head.correlation_id,
            correction=correction if isinstance(correction, Correction) else None,
            at=head[3],
        )

    def _write_correction(
        self, connection: Connection, invoice_id: UUID, correction: Correction
    ) -> None:
        common: dict[str, Any] = {
            "invoice_id": invoice_id,
            "run_id": correction.run_id,
            "source": ADMIN_SOURCE,
            "confidence": ADMIN_CONFIDENCE,
        }
        if correction.fields:
            connection.execute(
                insert(invoice_field).values(created_at=func.now()),
                [
                    {
                        **common,
                        "id": self._new_id(),
                        "field_id": f.field_id,
                        "value_text": f.value_text,
                        "value_number": f.value_number,
                        "value_date": f.value_date,
                        "currency": f.currency,
                        "page": f.page,
                        "polygon": None if f.polygon is None else list(f.polygon),
                    }
                    for f in correction.fields
                ],
            )
        if correction.lines:
            connection.execute(
                insert(invoice_line).values(created_at=func.now()),
                [
                    {
                        **common,
                        "id": self._new_id(),
                        "line_no": line.line_no,
                        "product_code": line.product_code,
                        "description": line.description,
                        "quantity": line.quantity,
                        "unit": line.unit,
                        "unit_price": line.unit_price,
                        "amount": line.amount,
                        "tax": line.tax,
                        "po_line_id": line.po_line_id,
                        "material_id": line.material_id,
                    }
                    for line in correction.lines
                ],
            )


def _no_rows(connection: Connection) -> dict[str, object]:
    """Re-extract and Retry intake write only their transition and audit entry."""
    return {}
