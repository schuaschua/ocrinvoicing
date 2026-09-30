"""The `post` stage (Story 3.2, AD-3, AD-10, AD-18), fed by `q-post`.

1. Claim `ready_to_post -> posting` with a 10-minute lease (or reclaim an expired
   one), only once `next_attempt_at` is empty or past. Zero rows: a message that came
   before `next_attempt_at` goes back to `q-post` with the remaining delay; any other
   is only acknowledged (AD-2).
2. An `accounts_ref` saved by an earlier try is reused: the accounts system is not
   called again (AD-3 save-before-finish).
3. Otherwise post the AD-18 current values through `AccountsPort` (one call, never
   retried) and save the `accounts_ref` under `invoice_id`.
4. `posting -> posted`, with `posted_at` equal to that history row's `at`.

- An accounts error (HTTP, timeout, unreachable, or a document the contract refuses):
  one transaction moves `posting -> ready_to_post`, counts `post_failures`, sets
  `next_attempt_at` 1, 5, 15 or 60 minutes ahead and releases the lease; the handler
  then sends the message back with that delay and the original is completed, so no
  dequeue is used. The 5th failure, counted from `post_failures` and never from the
  message's `attempt`, routes `ACCOUNTS_API_ERROR` with the error's status and code.
- Any other failure ends the lease and is raised with a code, so the host retries
  the message and, after 5 tries, the poison trigger routes `PROCESSING_FAILED`.
- A stopped database is waited out (dbwait.py, AD-7).

Logs hold ids, codes and timings only, never a field value (security.md rule 31).
"""

import logging
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum

from opentelemetry.trace import SpanKind
from pydantic import ValidationError

from invoicing.adapters.logging import log_event
from invoicing.adapters.telemetry import correlation_span
from invoicing.apps.pipeline.quality import StageFailed, failure_code
from invoicing.domain.errors import DatabaseOfflineError
from invoicing.domain.posting import PostRetry, post_backoff
from invoicing.domain.reasons import ReasonCode
from invoicing.domain.status import (
    CLAIM_STATUS,
    InvoiceStatus,
    Stage,
    requeue_after_redelivery,
)
from invoicing.domain.transitions import (
    AdminReason,
    AdminRouting,
    plan_claim,
    plan_transition,
    route_to_admin,
)
from invoicing.ports.accounts import (
    AccountsError,
    AccountsPort,
    InvoiceToPost,
    PostingRepository,
)
from invoicing.ports.invoices import InvoiceRepository
from invoicing.ports.messages import QueueMessage
from invoicing.ports.queue import STAGE_QUEUES, QueueName, QueueSender
from invoicing.ports.validation import ValidationRepository

ACTOR = "pipeline:post"
INVOICE_NOT_FOUND = "INVOICE_NOT_FOUND"
NO_EXTRACTION_RUN = "NO_EXTRACTION_RUN"
# Logged when the accounts system answered a reference the invoice row could not keep.
REF_NOT_SAVED = "REF_NOT_SAVED"

_logger = logging.getLogger("invoicing.pipeline.post")


class PostAction(StrEnum):
    """What the stage did with a message."""

    POSTED = "posted"
    REUSE = "reuse"
    RETRY = "retry"
    EARLY = "early"
    ROUTE = "route"
    ACK = "ack"


@dataclass(frozen=True)
class PostOutcome:
    """The stage's result: what it did, the delay before `q-post` sees the message
    again (a retry or an early message), and the accounts error of a failure."""

    action: PostAction
    enqueue: QueueName | None = None
    delay_seconds: int = 0
    error: AccountsError | None = None


@dataclass(frozen=True)
class PostDependencies:
    """What the stage reaches outside itself; tests pass fakes for the queue and, in
    unit tests, the accounts system."""

    invoices: InvoiceRepository
    postings: PostingRepository
    validations: ValidationRepository
    accounts: AccountsPort
    queue: QueueSender
    # The configured invoice currency (DI reports none for SGD, AD-8).
    currency: str


def _redelivered(status: InvoiceStatus | None) -> PostOutcome:
    """AD-2: the stage already ran (or the invoice moved on): only acknowledge."""
    following = requeue_after_redelivery(Stage.POST, status)
    return PostOutcome(
        PostAction.ACK, None if following is None else STAGE_QUEUES[following]
    )


async def _not_claimed(message: QueueMessage, deps: PostDependencies) -> PostOutcome:
    state = await deps.invoices.state(message.invoice_id)
    if (
        state is not None
        and state.status is InvoiceStatus.READY_TO_POST
        and state.next_attempt_at is not None
        and state.next_attempt_at > state.now
    ):
        # AD-3: too early. Back on the queue for the rest of the wait.
        remaining = (state.next_attempt_at - state.now).total_seconds()
        return PostOutcome(PostAction.EARLY, delay_seconds=max(1, math.ceil(remaining)))
    return _redelivered(None if state is None else state.status)


async def _failed(
    message: QueueMessage, error: AccountsError, deps: PostDependencies
) -> PostOutcome:
    invoice_id = message.invoice_id
    posting = CLAIM_STATUS[Stage.POST]

    def decide(failures: int) -> PostRetry | AdminRouting:
        delay = post_backoff(failures)
        if delay is None:
            # AD-10: the API error's status and code only, never a document value.
            detail = {"status": error.status, "code": error.code}
            return route_to_admin(
                invoice_id,
                [AdminReason(ReasonCode.ACCOUNTS_API_ERROR, detail=detail)],
                posting,
                actor=ACTOR,
            )
        return PostRetry(
            plan_transition(invoice_id, posting, InvoiceStatus.READY_TO_POST, ACTOR),
            delay,
        )

    decided = await deps.postings.fail(invoice_id, decide)
    if decided is None:
        return _redelivered(await deps.invoices.status(invoice_id))
    if isinstance(decided, AdminRouting):
        return PostOutcome(PostAction.ROUTE, error=error)
    return PostOutcome(
        PostAction.RETRY,
        delay_seconds=math.ceil(decided.delay.total_seconds()),
        error=error,
    )


async def post(message: QueueMessage, deps: PostDependencies) -> PostOutcome:
    """Steps 1-4 for one parsed message. Raises storage errors, and `StageFailed`
    for an invoice with nothing to post, for a host retry, with the lease ended."""
    invoice_id = message.invoice_id
    claim = plan_claim(invoice_id, Stage.POST, ACTOR)
    if not await deps.invoices.claim(claim):
        return await _not_claimed(message, deps)
    finish = plan_transition(
        invoice_id, CLAIM_STATUS[Stage.POST], InvoiceStatus.POSTED, ACTOR
    )
    try:
        state = await deps.postings.state(invoice_id)
        if state is None:
            raise StageFailed(INVOICE_NOT_FOUND, Stage.POST)
        action = PostAction.REUSE
        if state.accounts_ref is None:
            loaded = await deps.validations.load(invoice_id)
            if loaded is None or loaded.values is None:
                raise StageFailed(NO_EXTRACTION_RUN, Stage.POST)
            try:
                accounts_ref = await deps.accounts.post_invoice(
                    InvoiceToPost(
                        invoice_id=invoice_id,
                        supplier_id=state.supplier_id,
                        po_number=state.po_number,
                        currency=deps.currency,
                        values=loaded.values,
                    )
                )
            except AccountsError as error:
                return await _failed(message, error, deps)
            # AD-3: saved before the finish, so a retry never posts again.
            if not await deps.postings.save_ref(invoice_id, accounts_ref):
                # The accounts system holds the invoice but this row moved on: logged
                # so the reference is never lost silently (it is an id, not a value).
                log_event(
                    _logger,
                    "post.orphan_ref",
                    level=logging.ERROR,
                    invoice_id=invoice_id,
                    accounts_ref=accounts_ref,
                    code=REF_NOT_SAVED,
                )
                return _redelivered(await deps.invoices.status(invoice_id))
            action = PostAction.POSTED
        if await deps.postings.finish(finish):
            return PostOutcome(action)
        return _redelivered(await deps.invoices.status(invoice_id))
    except DatabaseOfflineError:
        raise
    except Exception:
        # The host retries this message now: let that retry reclaim (AD-3).
        await deps.invoices.release_claim(claim)
        raise


type PostHandler = Callable[[str | bytes], Awaitable[PostOutcome]]


def post_handler(deps: PostDependencies) -> PostHandler:
    """The `q-post` message handler: parse, post, then send the message back after
    the commit for a retry or an early message. A failure is raised as `StageFailed`
    with a code, so the host retries the message (`maxDequeueCount` 5).
    `DatabaseOfflineError` is raised as it is, for the AD-7 wait (dbwait.py)."""

    async def handle(body: str | bytes) -> PostOutcome:
        try:
            message = QueueMessage.from_json(body)
        except ValidationError:
            log_event(
                _logger,
                "post.malformed_message",
                level=logging.ERROR,
                code="MALFORMED_MESSAGE",
            )
            raise StageFailed("MALFORMED_MESSAGE", Stage.POST) from None

        with correlation_span(
            "pipeline.post",
            message.correlation_id,
            kind=SpanKind.CONSUMER,
            invoice_id=message.invoice_id,
            stage=Stage.POST,
            attempt=message.attempt,
        ):
            started = time.perf_counter()
            try:
                outcome = await post(message, deps)
                if outcome.action is PostAction.RETRY:
                    # The same ids and first enqueue time; `attempt` is informational.
                    await deps.queue.send(
                        QueueName.POST,
                        message.model_copy(update={"attempt": message.attempt + 1}),
                        delay_seconds=outcome.delay_seconds,
                    )
                elif outcome.action is PostAction.EARLY:
                    await deps.queue.send(
                        QueueName.POST, message, delay_seconds=outcome.delay_seconds
                    )
            except DatabaseOfflineError:
                raise
            except Exception as error:  # noqa: BLE001  # re-raised as StageFailed
                code = failure_code(error)
                log_event(
                    _logger,
                    "post.failed",
                    level=logging.ERROR,
                    invoice_id=message.invoice_id,
                    code=code,
                    attempt=message.attempt,
                )
                raise StageFailed(code, Stage.POST) from None
            done: dict[str, object] = {
                "invoice_id": message.invoice_id,
                "code": outcome.action,
                "duration_ms": round((time.perf_counter() - started) * 1000),
            }
            if outcome.error is not None:
                done["reason"] = outcome.error.code
                if outcome.error.status is not None:
                    done["http_status"] = outcome.error.status
            if outcome.delay_seconds:
                done["queue"] = QueueName.POST
            level = logging.WARNING if outcome.error is not None else logging.INFO
            log_event(_logger, "post.done", level=level, **done)
        return outcome

    return handle
