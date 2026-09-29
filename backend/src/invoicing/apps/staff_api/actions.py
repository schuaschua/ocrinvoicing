"""The admin actions (Story 2.10, AD-3, AD-4, AD-18, UX-DR12):

- `POST api/admin/items/{invoice_id}/correct` `{fields: {field_id: value}, lines:
  [{line_no, <column>: value}]}`: admin rows on the latest run, then `q-validate`.
- `POST .../reextract`: to `awaiting_extraction`, then `q-extract`.
- `POST .../retry-intake`: to `received`, then `q-quality`.
- `POST .../reject` `{reason}`: to `rejected`; the reason (500 characters at most) is
  audited and never logged.

Every body carries the `routing_id` the admin saw (the item's, or null): a newer
routing means the page is stale, answered like another admin's action (409).

Admins only, with `X-Requested-With` (security.md rule 24); anyone else and an unknown
invoice get 404, before anything is read. 409 `CONFLICT` "Already handled by another
admin." when the invoice is no longer queued or its transition changed no rows; 409
`ACTION_NOT_ALLOWED` when its open reasons don't allow the action (the guard the item
read lists). A bank field is refused with 400 before anything is read (AD-11).

The queue message and the corrections blob follow the commit. Neither undoes it when
it fails: the failure is logged with a code, the sweeper re-enqueues a stuck invoice
(AD-2), and a lost corrections blob only costs training data (FR10)."""

import json
import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import azure.functions as func

from invoicing.adapters.http import Endpoint, json_response
from invoicing.adapters.logging import log_event
from invoicing.adapters.principal import (
    NOT_FOUND_MESSAGE,
    StaffHandler,
    staff_endpoint,
)
from invoicing.apps.staff_api.item import invoice_id_of
from invoicing.domain.actions import (
    MAX_REJECT_REASON,
    TARGET_STATUS,
    AdminAction,
    Correction,
)
from invoicing.domain.errors import (
    ConflictError,
    DomainError,
    ErrorCode,
    NotFoundError,
    ValidationFailedError,
)
from invoicing.domain.extraction import is_bank_field_id
from invoicing.domain.ids import new_uuid7, parse_uuid
from invoicing.domain.roles import StaffPrincipal, Surface
from invoicing.domain.status import InvoiceStatus
from invoicing.ports.admin_actions import ActionResult, AdminActions, Outcome
from invoicing.ports.blobs import CorrectionsStore
from invoicing.ports.messages import QueueMessage
from invoicing.ports.queue import QueueName, QueueSender

# A Correct body: a few dozen short values; anything bigger is refused unread.
MAX_BODY = 64 * 1024
MAX_FIELDS = 100
MAX_LINES = 200

# The stage queue each action feeds after its commit (AD-2); Reject feeds none.
NEXT_QUEUE: Mapping[AdminAction, QueueName] = {
    AdminAction.CORRECT: QueueName.VALIDATE,
    AdminAction.REEXTRACT: QueueName.EXTRACT,
    AdminAction.RETRY_INTAKE: QueueName.QUALITY,
}

_logger = logging.getLogger("invoicing.admin_actions")

type Clock = Callable[[], datetime]


def _now() -> datetime:
    return datetime.now(UTC)


def _json(req: func.HttpRequest) -> dict[str, Any]:
    """The body as a JSON object; empty counts as `{}`. Messages never echo it."""
    raw = req.get_body() or b""
    if len(raw) > MAX_BODY:
        raise ValidationFailedError("The request is too big.")
    if not raw.strip():
        return {}
    try:
        body = json.loads(raw)
    # RecursionError: deeply nested JSON is refused like any other malformed body.
    except (ValueError, RecursionError):
        raise ValidationFailedError("The request must be JSON.") from None
    if not isinstance(body, dict):
        raise ValidationFailedError("The request must be a JSON object.")
    return body


def _correction_request(
    body: Mapping[str, Any],
) -> tuple[dict[str, str], dict[int, dict[str, str | None]]]:
    """The validated `{fields, lines}` shape. A bank field is refused here, before
    anything is read (AD-11); the values are checked by the domain."""
    fields_in = body.get("fields", {})
    lines_in = body.get("lines", [])
    if not isinstance(fields_in, dict) or len(fields_in) > MAX_FIELDS:
        raise ValidationFailedError("fields must be an object of field values.")
    if not isinstance(lines_in, list) or len(lines_in) > MAX_LINES:
        raise ValidationFailedError("lines must be a list of lines.")
    fields: dict[str, str] = {}
    for field_id, value in fields_in.items():
        if is_bank_field_id(field_id):
            raise ValidationFailedError("Bank fields can't be corrected.")
        if not isinstance(value, str):
            raise ValidationFailedError("Each field value must be text.")
        fields[field_id] = value
    lines: dict[int, dict[str, str | None]] = {}
    for line in lines_in:
        if not isinstance(line, dict):
            raise ValidationFailedError("Each line must be an object.")
        line_no = line.get("line_no")
        if (
            not isinstance(line_no, int)
            or isinstance(line_no, bool)
            or line_no < 1
            or line_no in lines
        ):
            raise ValidationFailedError("Each line needs its own line_no.")
        values = {k: v for k, v in line.items() if k != "line_no"}
        if not all(v is None or isinstance(v, str) for v in values.values()):
            raise ValidationFailedError("Each line value must be text or null.")
        lines[line_no] = values
    return fields, lines


def _routing_id(body: Mapping[str, Any]) -> UUID | None:
    """The routing the admin saw (the item's `routing_id`); required, may be null."""
    if "routing_id" not in body:
        raise ValidationFailedError("routing_id is required.")
    value = body["routing_id"]
    if value is None:
        return None
    routing_id = parse_uuid(value) if isinstance(value, str) else None
    if routing_id is None:
        raise ValidationFailedError("routing_id must be a UUID or null.")
    return routing_id


def _reject_reason(body: Mapping[str, Any]) -> str:
    reason = body.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ValidationFailedError("A reason is required.")
    if len(reason.strip()) > MAX_REJECT_REASON:
        raise ValidationFailedError(
            f"The reason can be at most {MAX_REJECT_REASON} characters."
        )
    return reason.strip()


def _checked(result: ActionResult) -> ActionResult:
    if result.outcome is Outcome.NOT_FOUND:
        raise NotFoundError(NOT_FOUND_MESSAGE)
    if result.outcome is Outcome.CONFLICT:
        raise ConflictError(ErrorCode.CONFLICT)
    if result.outcome is Outcome.NOT_ALLOWED:
        raise ConflictError(ErrorCode.ACTION_NOT_ALLOWED)
    return result


def correction_json(
    invoice_id: UUID,
    correction: Correction,
    admin_oid: str,
    at: datetime,
) -> bytes:
    """The raw correction for training (FR10): `{invoice_id, run_id, admin_oid, at,
    fields, lines}`. Bank fields can't be corrected, so none can appear (AD-11)."""
    return json.dumps(
        {
            "invoice_id": str(invoice_id),
            "run_id": str(correction.run_id),
            "admin_oid": admin_oid,
            "at": at.astimezone(UTC).isoformat(),
            "fields": {f.field_id: f.wire_value for f in correction.fields},
            "lines": [
                {
                    "line_no": line.line_no,
                    "product_code": line.product_code,
                    "description": line.description,
                    "quantity": _text(line.quantity),
                    "unit": line.unit,
                    "unit_price": _text(line.unit_price),
                    "amount": _text(line.amount),
                    "tax": _text(line.tax),
                }
                for line in correction.lines
            ],
        }
    ).encode()


def _text(value: object) -> str | None:
    return None if value is None else str(value)


def action_endpoints(
    actions: AdminActions,
    queue: Callable[[], QueueSender],
    corrections: Callable[[], CorrectionsStore],
    *,
    platform_auth_trusted: bool,
    clock: Clock = _now,
) -> tuple[Endpoint, Endpoint, Endpoint, Endpoint]:
    """(correct, reextract, retry-intake, reject). `queue` and `corrections` are
    called after a commit only. `platform_auth_trusted` has no default: the wiring
    must always pass the setting (AD-14: fail closed)."""

    async def after_commit(
        action: AdminAction, invoice_id: UUID, result: ActionResult
    ) -> None:
        next_queue = NEXT_QUEUE.get(action)
        if next_queue is not None and result.correlation_id is not None:
            try:
                await queue().send(
                    next_queue,
                    QueueMessage.first(invoice_id, result.correlation_id, clock()),
                )
            except DomainError as error:
                # AD-2: the invoice waits in its new status; the sweeper sends it on.
                log_event(
                    _logger,
                    "admin_action.enqueue_failed",
                    level=logging.ERROR,
                    invoice_id=invoice_id,
                    queue=next_queue,
                    code=error.code,
                )

    def respond(
        action: AdminAction, invoice_id: UUID, correlation_id: UUID
    ) -> func.HttpResponse:
        status: InvoiceStatus = TARGET_STATUS[action]
        return json_response(
            {"invoice_id": str(invoice_id), "status": status.value},
            status=200,
            correlation_id=correlation_id,
        )

    def admin_of(principal: StaffPrincipal) -> str:
        if not principal.oid:
            # Every action's audit entry names the admin; without an object id there
            # is nobody to name, so nothing is read or written.
            raise NotFoundError(NOT_FOUND_MESSAGE)
        return principal.oid

    async def correct(
        req: func.HttpRequest, correlation_id: UUID, principal: StaffPrincipal
    ) -> func.HttpResponse:
        invoice_id = invoice_id_of(req)
        body = _json(req)
        fields, lines = _correction_request(body)
        routing_id = _routing_id(body)
        oid = admin_of(principal)
        result = _checked(
            await actions.correct(invoice_id, fields, lines, oid, routing_id)
        )
        await after_commit(AdminAction.CORRECT, invoice_id, result)
        if result.correction is not None:
            try:
                await corrections().put(
                    invoice_id,
                    new_uuid7(),
                    correction_json(
                        invoice_id, result.correction, oid, result.at or clock()
                    ),
                )
            except DomainError as error:
                # FR10: training data only; the correction itself is committed.
                log_event(
                    _logger,
                    "admin_action.correction_blob_failed",
                    level=logging.ERROR,
                    invoice_id=invoice_id,
                    code=error.code,
                )
        return respond(AdminAction.CORRECT, invoice_id, correlation_id)

    async def reextract(
        req: func.HttpRequest, correlation_id: UUID, principal: StaffPrincipal
    ) -> func.HttpResponse:
        invoice_id = invoice_id_of(req)
        routing_id = _routing_id(_json(req))
        result = _checked(
            await actions.reextract(invoice_id, admin_of(principal), routing_id)
        )
        await after_commit(AdminAction.REEXTRACT, invoice_id, result)
        return respond(AdminAction.REEXTRACT, invoice_id, correlation_id)

    async def retry_intake(
        req: func.HttpRequest, correlation_id: UUID, principal: StaffPrincipal
    ) -> func.HttpResponse:
        invoice_id = invoice_id_of(req)
        routing_id = _routing_id(_json(req))
        result = _checked(
            await actions.retry_intake(invoice_id, admin_of(principal), routing_id)
        )
        await after_commit(AdminAction.RETRY_INTAKE, invoice_id, result)
        return respond(AdminAction.RETRY_INTAKE, invoice_id, correlation_id)

    async def reject(
        req: func.HttpRequest, correlation_id: UUID, principal: StaffPrincipal
    ) -> func.HttpResponse:
        invoice_id = invoice_id_of(req)
        body = _json(req)
        reason = _reject_reason(body)
        routing_id = _routing_id(body)
        _checked(
            await actions.reject(invoice_id, reason, admin_of(principal), routing_id)
        )
        return respond(AdminAction.REJECT, invoice_id, correlation_id)

    def guarded(handler: StaffHandler) -> Endpoint:
        return staff_endpoint(
            handler,
            surface=Surface.ADMIN_ITEM,
            platform_auth_trusted=platform_auth_trusted,
            hide_from_others=True,
        )

    return guarded(correct), guarded(reextract), guarded(retry_intake), guarded(reject)
