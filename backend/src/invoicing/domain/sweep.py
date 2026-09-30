"""The sweeper's rules (AD-2, AD-6): which stuck invoice goes back to which stage, and
how long upload keys live.

The sweeper runs every 15 minutes. It re-enqueues an invoice whose `status_changed_at`
is more than an hour old, once the database itself has been up for more than an hour
(so messages that waited out a stopped database, AD-7, drain first). A duplicate
message is harmless: the next claim changes zero rows (AD-3).

The repository's scan is built from these constants (`sweep_statuses`,
`LEASED_STATUSES`, `BACKOFF_STATUSES`, `STALE_AFTER`), and `sweep_stage` decides each
row again, so the SQL and the rule can't drift.
"""

from datetime import datetime, timedelta

from invoicing.domain.status import InvoiceStatus, Stage, lease_expired

_S = InvoiceStatus

# AD-2: how old a status, and the database's uptime, must be before a sweep.
STALE_AFTER = timedelta(hours=1)
# AD-6: an upload key replays a retried upload for 24 hours, then the sweeper deletes it.
UPLOAD_KEY_TTL = timedelta(hours=24)
# At most this many invoices, and this many upload keys, per sweep; the rest wait for
# the next run 15 minutes later.
SWEEP_LIMIT = 500

# The stages whose queue has a consumer today. Sweeping to a queue nobody reads would
# pile messages up and keep `stuck_invoices` above 0, so each stage story adds its
# stage here when it adds the consumer (2.3 extract, 2.5 validate, 3.2 post). The sweep
# only enqueues: it never touches `post_failures` (AD-3).
CONSUMED_QUEUES: frozenset[Stage] = frozenset(
    {Stage.QUALITY, Stage.EXTRACT, Stage.VALIDATE, Stage.POST}
)

# The AD-2 map. `in_admin_queue`, `posted` and `rejected` are absent: an admin owns
# the first, the others are final, so the sweeper never touches them.
SWEEP_MAP: dict[InvoiceStatus, Stage] = {
    _S.RECEIVED: Stage.QUALITY,
    _S.AWAITING_EXTRACTION: Stage.EXTRACT,
    _S.EXTRACTING: Stage.EXTRACT,
    _S.AWAITING_VALIDATION: Stage.VALIDATE,
    _S.VALIDATING: Stage.VALIDATE,
    _S.READY_TO_POST: Stage.POST,
    _S.POSTING: Stage.POST,
}
# Claim statuses: swept only once their lease has expired.
LEASED_STATUSES: frozenset[InvoiceStatus] = frozenset(
    {_S.EXTRACTING, _S.VALIDATING, _S.POSTING}
)
# Swept only once `next_attempt_at` is empty or past (AD-3 posting backoff).
BACKOFF_STATUSES: frozenset[InvoiceStatus] = frozenset({_S.READY_TO_POST})


def sweep_statuses(
    stages: frozenset[Stage] = CONSUMED_QUEUES,
) -> frozenset[InvoiceStatus]:
    """The statuses a sweep reads: those whose target stage is in `stages`."""
    return frozenset(status for status, stage in SWEEP_MAP.items() if stage in stages)


def sweep_stage(
    status: InvoiceStatus,
    *,
    claimed_until: datetime | None,
    next_attempt_at: datetime | None,
    now: datetime,
    stages: frozenset[Stage] = CONSUMED_QUEUES,
) -> Stage | None:
    """The stage whose queue a stale invoice in `status` goes back to (AD-2), or None
    when the sweeper leaves it alone: a live lease, a posting backoff still running, a
    status it never touches, or a stage with no consumer yet."""
    stage = SWEEP_MAP.get(status)
    if stage is None or stage not in stages:
        return None
    if status in LEASED_STATUSES and not lease_expired(claimed_until, now):
        return None
    if (
        status in BACKOFF_STATUSES
        and next_attempt_at is not None
        and next_attempt_at > now
    ):
        return None
    return stage


def upload_key_expired(created_at: datetime, now: datetime) -> bool:
    """An upload key older than 24 hours is deleted (AD-6)."""
    return now - created_at > UPLOAD_KEY_TTL
