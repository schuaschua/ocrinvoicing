"""The sweeper (AD-2, AD-6): a `pipeline` timer every 15 minutes (UTC), separate from
the AD-13 schedule. It recovers invoices stranded between a commit and an enqueue.

1. Read the invoices whose status changed more than an hour ago, once the database
   has been up for more than an hour (`pg_postmaster_start_time()`), and re-enqueue
   each to its stage by the AD-2 map (`domain.sweep`). `in_admin_queue`, `posted`
   and `rejected` are never touched; live leases and running posting backoffs are
   left alone.
   Only stages with a consumer are swept (`CONSUMED_QUEUES`), at most `SWEEP_LIMIT`
   invoices a run, each with its own ids and `created_at` as `first_enqueued_at`.
2. Reconcile orphaned uploads (the Story 1.8 deferral): an `uploadkeys` row older
   than an hour whose invoice row doesn't exist is an upload whose `q-quality`
   enqueue was lost. When its blob exists it is enqueued again, with the row's
   `correlation_id` and `created_at`, and the row is marked `recovered_at` (an
   ETag-conditional write), so each orphan is recovered once. Without a blob nothing
   can be processed, and a supplier retry within 24 hours replays the upload.
3. Delete `uploadkeys` rows older than 24 hours (AD-6), each only if unchanged since
   it was listed (its ETag). Ages are measured on the database's clock.
4. Emit `stuck_invoices`, the number re-enqueued (AD-17 alerts when above 0), and log
   the counts on `sweeper.done`.

Each step, and each invoice or key within it, fails on its own: the failure is logged
by a code and counted, and the sweep goes on.

A duplicate message is harmless: the next claim changes zero rows (AD-3). A sweep that
finds the database stopped exits with a code and catches up at its next run (AD-7).
"""

import logging
from collections.abc import Awaitable
from dataclasses import dataclass

from invoicing.adapters.logging import log_event, log_unsampled_event
from invoicing.domain.errors import DatabaseOfflineError, ServiceUnavailableError
from invoicing.domain.sweep import (
    CONSUMED_QUEUES,
    STALE_AFTER,
    SWEEP_LIMIT,
    sweep_stage,
    upload_key_expired,
)
from invoicing.ports.blobs import ImageReader
from invoicing.ports.invoices import InvoiceRepository, StaleScan
from invoicing.ports.messages import QueueMessage
from invoicing.ports.metrics import MetricName, MetricsPort
from invoicing.ports.queue import STAGE_QUEUES, QueueName, QueueSender
from invoicing.ports.upload_keys import AgedUploadKey, AgedUploadKeys

# NCRONTAB (seconds first), UTC: every 15 minutes (AD-2, AD-1 timers use UTC).
SWEEP_SCHEDULE = "0 */15 * * * *"

_logger = logging.getLogger("invoicing.pipeline.sweeper")


@dataclass
class SweepResult:
    """What one sweep did. `code` is `swept`, or `DB_OFFLINE` when it exited early."""

    code: str
    requeued: int = 0
    orphans: int = 0
    deleted: int = 0
    failures: int = 0


@dataclass(frozen=True)
class Sweeper:
    """The sweep and its dependencies; `run` is the timer's body."""

    invoices: InvoiceRepository
    upload_keys: AgedUploadKeys
    images: ImageReader
    queue: QueueSender
    metrics: MetricsPort

    async def run(self) -> SweepResult:
        """One sweep (steps 1-4)."""
        result = SweepResult("swept")
        try:
            scan = await self.invoices.stale(
                STALE_AFTER, stages=CONSUMED_QUEUES, limit=SWEEP_LIMIT
            )
        except DatabaseOfflineError:
            log_event(
                _logger, "sweeper.skipped", level=logging.WARNING, code="DB_OFFLINE"
            )
            return SweepResult("DB_OFFLINE")
        except Exception as error:  # noqa: BLE001  # logged; the metric is still emitted
            self._step_failed("sweeper.stale_failed", error, result)
            return self._finish(result)
        await self._step(
            "sweeper.stale_failed", self._requeue_stale(scan, result), result
        )
        await self._step(
            "sweeper.upload_keys_failed", self._upload_keys(scan, result), result
        )
        return self._finish(result)

    async def _step(
        self, event: str, work: Awaitable[None], result: SweepResult
    ) -> None:
        try:
            await work
        except Exception as error:  # noqa: BLE001  # one failed step never stops the sweep
            self._step_failed(event, error, result)

    def _step_failed(self, event: str, error: Exception, result: SweepResult) -> None:
        result.failures += 1
        code = (
            "DB_OFFLINE"
            if isinstance(error, DatabaseOfflineError)
            else type(error).__name__
        )
        log_event(_logger, event, level=logging.ERROR, code=code)

    def _finish(self, result: SweepResult) -> SweepResult:
        stuck = result.requeued + result.orphans
        self.metrics.emit_metric(MetricName.STUCK_INVOICES, stuck)
        log_unsampled_event(
            _logger,
            "sweeper.done",
            level=logging.WARNING if stuck or result.failures else logging.INFO,
            code=result.code,
            requeued=result.requeued,
            orphans=result.orphans,
            deleted=result.deleted,
            failures=result.failures,
        )
        return result

    async def _requeue_stale(self, scan: StaleScan, result: SweepResult) -> None:
        for stale in scan.invoices:
            stage = sweep_stage(
                stale.status,
                claimed_until=stale.claimed_until,
                next_attempt_at=stale.next_attempt_at,
                now=scan.now,
                stages=CONSUMED_QUEUES,
            )
            if stage is None:
                continue
            # The invoice's own trace, first enqueued when it was created.
            message = QueueMessage(
                invoice_id=stale.invoice_id,
                correlation_id=stale.correlation_id,
                first_enqueued_at=stale.created_at,
                attempt=1,
            )
            if await self._send(
                STAGE_QUEUES[stage], message, result, status=stale.status
            ):
                result.requeued += 1

    async def _upload_keys(self, scan: StaleScan, result: SweepResult) -> None:
        # The database's clock, like the invoice scan.
        now = scan.now
        aged = await self.upload_keys.older_than(now - STALE_AFTER, SWEEP_LIMIT)
        if not aged:
            return
        existing = await self.invoices.existing([i.value.invoice_id for i in aged])
        for item in aged:
            current: AgedUploadKey | None = item
            orphaned = item.value.invoice_id not in existing
            if orphaned and item.recovered_at is None:
                # Just after a restart, uploads that waited out the stop (AD-7) have
                # not been processed yet: leave them for a later sweep.
                if not scan.settled:
                    continue
                current = await self._recover_upload(item, scan, result)
            if current is not None and upload_key_expired(item.value.created_at, now):
                await self._delete(current, result)

    async def _recover_upload(
        self, item: AgedUploadKey, scan: StaleScan, result: SweepResult
    ) -> AgedUploadKey | None:
        """The key as it now stands (marked when the upload was enqueued again), or
        None to keep it untouched for the next sweep."""
        entry = item.value
        try:
            has_blob = await self.images.exists(entry.invoice_id)
        except ServiceUnavailableError:
            # Logged by the adapter with its code.
            result.failures += 1
            return None
        if not has_blob:
            log_event(
                _logger,
                "sweeper.upload_without_blob",
                level=logging.WARNING,
                invoice_id=entry.invoice_id,
                code="IMAGE_NOT_FOUND",
            )
            return item
        # The upload's own ids and time, as supplier-api would have sent them (AD-6).
        message = QueueMessage(
            invoice_id=entry.invoice_id,
            correlation_id=entry.correlation_id,
            first_enqueued_at=entry.created_at,
            attempt=1,
        )
        # Enqueued before it is marked: a failed mark only means a duplicate message
        # next sweep (harmless, AD-2), never a lost upload.
        if not await self._send(
            QueueName.QUALITY, message, result, code="ORPHANED_UPLOAD"
        ):
            return None
        result.orphans += 1
        try:
            return await self.upload_keys.mark_recovered(item, scan.now)
        except ServiceUnavailableError:
            result.failures += 1
            return None

    async def _send(
        self,
        queue: QueueName,
        message: QueueMessage,
        result: SweepResult,
        **fields: object,
    ) -> bool:
        try:
            await self.queue.send(queue, message)
        except Exception as error:  # noqa: BLE001  # one failed send never stops the sweep
            result.failures += 1
            log_event(
                _logger,
                "sweeper.enqueue_failed",
                level=logging.ERROR,
                queue=queue,
                invoice_id=message.invoice_id,
                code=type(error).__name__,
            )
            return False
        log_event(
            _logger,
            "sweeper.requeued",
            level=logging.WARNING,
            queue=queue,
            invoice_id=message.invoice_id,
            correlation_id=message.correlation_id,
            **fields,
        )
        return True

    async def _delete(self, item: AgedUploadKey, result: SweepResult) -> None:
        try:
            if await self.upload_keys.delete(item):
                result.deleted += 1
        except ServiceUnavailableError:
            # Logged by the adapter with its code; never the key itself.
            result.failures += 1
            log_event(
                _logger,
                "sweeper.delete_failed",
                level=logging.WARNING,
                invoice_id=item.value.invoice_id,
                code="DELETE_FAILED",
            )
