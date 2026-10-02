"""The `analytics` schema over PostgreSQL (Story 4.2, AD-11, AD-13).

`PostgresAnalyticsStore` is the analytics refresh job's writer (the pipeline login,
the schema's only writer), which also serves Story 4.3's weekly reminders: the list,
the invoiced re-check and the weekly guard, and Story 5.1's daily summaries (written
by `analytics_summaries.py`) and Story 5.3's material names, and Story 5.2's alerts
still to email (with the supplier's name, which the pipeline login may read in
master) and their `emailed_at`. `PostgresOverdueReader`
is staff-api's read (SELECT only).
SQLAlchemy Core with bound parameters (security.md rule 21), on a worker thread
(coding-style.md rule 11).
"""

import asyncio
from collections.abc import Collection, Iterable, Mapping, Sequence
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Connection, Engine, delete, exists, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from invoicing.adapters.postgres.analytics_summaries import (
    SUMMARIES_JOB,
    write_summaries,
)
from invoicing.adapters.postgres.engine import open_connection
from invoicing.adapters.postgres.schema import (
    alert,
    invoice,
    job_run,
    material,
    overdue_po,
    price_point,
)
from invoicing.adapters.postgres.suppliers import supplier
from invoicing.domain.alert_email import PendingAlert
from invoicing.domain.status import InvoiceStatus
from invoicing.ports.analytics import OverdueList
from invoicing.ports.purchasing import OverduePo, ReceiptLine

# `analytics.job_run.job` of the overdue list's rebuild.
OVERDUE_JOB = "overdue_po"
# `analytics.job_run.job` of the weekly supplier reminders (Story 4.3); its `run_date`
# is the Monday of the ISO week.
REMINDERS_JOB = "supplier_reminders"
# AD-13: the one advisory lock every overdue rebuild runs under, in this database, so
# two runs can't both write. Any constant works; this is "OVD" in ASCII.
OVERDUE_LOCK_KEY = 0x4F5644
# Story 5.1: the daily summaries' own lock, so two runs never both write them ("SUM").
SUMMARIES_LOCK_KEY = 0x53554D


def _job_ran(connection: Connection, job: str, run_date: date) -> bool:
    return (
        connection.execute(
            select(job_run.c.job).where(
                job_run.c.job == job, job_run.c.run_date == run_date
            )
        ).first()
        is not None
    )


class PostgresAnalyticsStore:
    """`AnalyticsStore`: the pipeline login's writes to `analytics`."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    async def refresh_overdue(
        self, run_date: date, pos: Sequence[OverduePo], finished_at: datetime
    ) -> bool:
        return await asyncio.to_thread(self._refresh, run_date, list(pos), finished_at)

    def _refresh(
        self, run_date: date, pos: list[OverduePo], finished_at: datetime
    ) -> bool:
        with open_connection(self._engine) as connection, connection.begin():
            connection.execute(
                select(func.pg_advisory_xact_lock(OVERDUE_LOCK_KEY))
            ).scalar()
            # Read after the lock: a run that finished while this one waited is seen.
            if _job_ran(connection, OVERDUE_JOB, run_date):
                return False
            connection.execute(delete(overdue_po))
            if pos:
                connection.execute(
                    insert(overdue_po),
                    [
                        {
                            "po_number": po.po_number,
                            "supplier_id": po.supplier_id,
                            "expected_date": po.expected_date,
                        }
                        for po in pos
                    ],
                )
            # AD-13: invoiced means any invoice that is not rejected has the PO as its
            # current po_number, checked here, in the writing transaction, so an
            # invoice that arrived after purchasing was read still counts.
            connection.execute(
                delete(overdue_po).where(
                    exists().where(
                        invoice.c.po_number == overdue_po.c.po_number,
                        invoice.c.status != InvoiceStatus.REJECTED.value,
                    )
                )
            )
            connection.execute(
                insert(job_run).values(
                    job=OVERDUE_JOB, run_date=run_date, finished_at=finished_at
                )
            )
        return True

    async def overdue_pos(self) -> list[OverduePo]:
        return await asyncio.to_thread(self._overdue_pos)

    def _overdue_pos(self) -> list[OverduePo]:
        with open_connection(self._engine) as connection:
            rows = connection.execute(
                select(
                    overdue_po.c.po_number,
                    overdue_po.c.supplier_id,
                    overdue_po.c.expected_date,
                )
            ).all()
        return [
            OverduePo(
                po_number=row.po_number,
                supplier_id=row.supplier_id,
                expected_date=row.expected_date,
            )
            for row in rows
        ]

    async def invoiced(self, po_numbers: Iterable[str]) -> set[str]:
        return await asyncio.to_thread(self._invoiced, sorted(set(po_numbers)))

    def _invoiced(self, po_numbers: list[str]) -> set[str]:
        if not po_numbers:
            return set()
        # The same rule as the rebuild's purge above (AD-13).
        with open_connection(self._engine) as connection:
            found: set[str] = set(
                connection.execute(
                    select(invoice.c.po_number).where(
                        invoice.c.po_number.in_(po_numbers),
                        invoice.c.status != InvoiceStatus.REJECTED.value,
                    )
                ).scalars()
            )
        return found

    async def reminders_done(self, week: date) -> bool:
        return await asyncio.to_thread(self._reminders_done, week)

    def _reminders_done(self, week: date) -> bool:
        with open_connection(self._engine) as connection:
            return _job_ran(connection, REMINDERS_JOB, week)

    async def record_reminders(self, week: date, finished_at: datetime) -> None:
        await asyncio.to_thread(self._record_reminders, week, finished_at)

    def _record_reminders(self, week: date, finished_at: datetime) -> None:
        # Two runs at once may both write the same rows; the first record stands.
        with open_connection(self._engine) as connection, connection.begin():
            connection.execute(
                pg_insert(job_run)
                .values(job=REMINDERS_JOB, run_date=week, finished_at=finished_at)
                .on_conflict_do_nothing(index_elements=["job", "run_date"])
            )

    async def summaries_done(self, run_date: date) -> bool:
        return await asyncio.to_thread(self._summaries_done, run_date)

    def _summaries_done(self, run_date: date) -> bool:
        with open_connection(self._engine) as connection:
            return _job_ran(connection, SUMMARIES_JOB, run_date)

    async def refresh_summaries(
        self, run_date: date, receipts: Sequence[ReceiptLine], finished_at: datetime
    ) -> bool:
        return await asyncio.to_thread(
            self._refresh_summaries, run_date, list(receipts), finished_at
        )

    def _refresh_summaries(
        self, run_date: date, receipts: list[ReceiptLine], finished_at: datetime
    ) -> bool:
        with open_connection(self._engine) as connection, connection.begin():
            connection.execute(
                select(func.pg_advisory_xact_lock(SUMMARIES_LOCK_KEY))
            ).scalar()
            # Read after the lock, as the overdue rebuild does.
            if _job_ran(connection, SUMMARIES_JOB, run_date):
                return False
            write_summaries(connection, receipts, finished_at, run_date)
            connection.execute(
                insert(job_run).values(
                    job=SUMMARIES_JOB, run_date=run_date, finished_at=finished_at
                )
            )
        return True

    async def priced_materials(self) -> set[UUID]:
        return await asyncio.to_thread(self._priced_materials)

    def _priced_materials(self) -> set[UUID]:
        with open_connection(self._engine) as connection:
            return set(
                connection.execute(
                    select(price_point.c.material_id).distinct()
                ).scalars()
            )

    async def replace_materials(self, names: Mapping[UUID, str]) -> None:
        await asyncio.to_thread(self._replace_materials, dict(names))

    def _replace_materials(self, names: dict[UUID, str]) -> None:
        with open_connection(self._engine) as connection, connection.begin():
            connection.execute(delete(material))
            if names:
                connection.execute(
                    insert(material),
                    [{"material_id": key, "name": name} for key, name in names.items()],
                )

    async def pending_alerts(
        self, kinds: Collection[str], limit: int
    ) -> list[PendingAlert]:
        return await asyncio.to_thread(self._pending_alerts, sorted(kinds), limit)

    def _pending_alerts(self, kinds: list[str], limit: int) -> list[PendingAlert]:
        if not kinds:
            return []
        with open_connection(self._engine) as connection:
            rows = connection.execute(
                select(
                    alert.c.alert_id,
                    alert.c.kind,
                    alert.c.supplier_id,
                    supplier.c.name.label("supplier_name"),
                    alert.c.material_id,
                    alert.c.detail,
                )
                .select_from(
                    alert.outerjoin(supplier, supplier.c.id == alert.c.supplier_id)
                )
                .where(
                    alert.c.emailed_at.is_(None),
                    alert.c.kind.in_(kinds),
                    # Backfilled alerts are stored emailed; this also keeps out any
                    # that weren't (5.3/5.4 history is never mailed).
                    func.coalesce(alert.c.detail["backfilled"].astext, "") != "true",
                )
                .order_by(alert.c.created_at, alert.c.alert_id)
                .limit(limit)
            ).all()
            # Tolerant per row: a detail that isn't a JSON object reads as empty,
            # and the email step skips the alert as invalid.
            details = {
                row.alert_id: row.detail if isinstance(row.detail, dict) else {}
                for row in rows
            }
            wanted = {row.material_id for row in rows if row.material_id is not None}
            for detail in details.values():
                evidence = detail.get("evidence")
                for item in evidence if isinstance(evidence, list) else ():
                    if isinstance(item, dict) and "material_id" in item:
                        try:
                            wanted.add(UUID(str(item["material_id"])))
                        except ValueError:
                            continue
            names: dict[UUID, str] = (
                {
                    found.material_id: found.name
                    for found in connection.execute(
                        select(material.c.material_id, material.c.name).where(
                            material.c.material_id.in_(sorted(wanted))
                        )
                    )
                }
                if wanted
                else {}
            )
        return [
            PendingAlert(
                alert_id=row.alert_id,
                kind=row.kind,
                supplier_id=row.supplier_id,
                supplier_name=row.supplier_name,
                material_id=row.material_id,
                detail=details[row.alert_id],
                material_names=names,
            )
            for row in rows
        ]

    async def mark_emailed(self, alert_id: UUID, at: datetime) -> None:
        await asyncio.to_thread(self._mark_emailed, alert_id, at)

    def _mark_emailed(self, alert_id: UUID, at: datetime) -> None:
        # AD-13: the pipeline login may UPDATE `emailed_at` and nothing else on alert.
        with open_connection(self._engine) as connection, connection.begin():
            connection.execute(
                update(alert)
                .where(alert.c.alert_id == alert_id, alert.c.emailed_at.is_(None))
                .values(emailed_at=at)
            )

    async def mark_stale(self, created_before: datetime, at: datetime) -> int:
        return await asyncio.to_thread(self._mark_stale, created_before, at)

    def _mark_stale(self, created_before: datetime, at: datetime) -> int:
        with open_connection(self._engine) as connection, connection.begin():
            result = connection.execute(
                update(alert)
                .where(
                    alert.c.emailed_at.is_(None), alert.c.created_at < created_before
                )
                .values(emailed_at=at)
            )
        return result.rowcount


class PostgresOverdueReader:
    """`OverdueReader`: staff-api's SELECT on `analytics`."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    async def overdue_list(self) -> OverdueList:
        return await asyncio.to_thread(self._read)

    def _read(self) -> OverdueList:
        with open_connection(self._engine) as connection:
            # One snapshot, so the rows and their date agree; read-only.
            connection.execution_options(
                isolation_level="REPEATABLE READ", postgresql_readonly=True
            )
            with connection.begin():
                made_at = connection.execute(
                    select(func.max(job_run.c.finished_at)).where(
                        job_run.c.job == OVERDUE_JOB
                    )
                ).scalar()
                rows = connection.execute(
                    select(
                        overdue_po.c.po_number,
                        overdue_po.c.supplier_id,
                        overdue_po.c.expected_date,
                    ).order_by(overdue_po.c.expected_date, overdue_po.c.po_number)
                ).all()
        return OverdueList(
            made_at=made_at,
            pos=tuple(
                OverduePo(
                    po_number=row.po_number,
                    supplier_id=row.supplier_id,
                    expected_date=row.expected_date,
                )
                for row in rows
            ),
        )
