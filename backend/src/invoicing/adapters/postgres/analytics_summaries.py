"""The analytics refresh job's daily summary writes (Story 5.1, AD-13, AD-20), inside
the transaction `PostgresAnalyticsStore.refresh_summaries` opens under its lock.

Posted invoices are processed incrementally: every invoice with `posted_at` after the
watermark minus 1 hour (all of them on the first run) has its `price_point` and
`invoice_fact` rows deleted and written again, so a rerun or an overlap never counts
one twice, and a late commit is still picked up. Everything else is recomputed in
full from `invoice_fact`, `intake` and the receipts passed in. Story 5.3 then stores
each AD-20 price rise as one `alert`, once by its `dedupe_key`: an alert is never
updated or deleted here (Story 5.2 stamps `emailed_at`), and a rise posted before the
run's window is stored already marked emailed (`detail.backfilled`). The rules are
`domain/analytics.py`'s. SQLAlchemy Core with bound parameters (security.md rule 21).
"""

from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Connection,
    Table,
    any_,
    delete,
    func,
    insert,
    select,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert

from invoicing.adapters.postgres.schema import (
    admin_item,
    alert,
    invoice,
    invoice_fact,
    month_summary,
    price_point,
    receipt_lateness,
    status_history,
    supplier_month,
    supplier_month_flags,
    supplier_on_time,
    watermark,
)
from invoicing.adapters.postgres.validation import current_values_of, id_array
from invoicing.domain.analytics import (
    PRICE_RISE,
    InvoiceFact,
    PricePoint,
    PriceRise,
    days_late,
    month_summaries,
    on_time_rates,
    posted_summary,
    price_rises,
    supplier_flags,
    supplier_months,
)
from invoicing.domain.ids import new_uuid7
from invoicing.domain.reasons import ReasonCode
from invoicing.domain.status import InvoiceStatus
from invoicing.domain.validation import INVOICE_DATE, INVOICE_TOTAL
from invoicing.ports.purchasing import ReceiptLine

# `analytics.job_run.job` and `analytics.watermark.job` of the daily summaries.
SUMMARIES_JOB = "summaries"
# AD-20: a transaction that committed late may carry a `posted_at` up to this much
# before the watermark; reprocessing that hour again keeps it from being skipped.
OVERLAP = timedelta(hours=1)


def _replace(connection: Connection, table: Table, rows: Iterable[Any]) -> None:
    """Replace every row of `table` with `rows` (dataclasses named like its columns)."""
    connection.execute(delete(table))
    values = [vars(row) for row in rows]
    if values:
        connection.execute(insert(table), values)


def _watermark(connection: Connection) -> datetime | None:
    held: datetime | None = connection.execute(
        select(watermark.c.posted_at).where(watermark.c.job == SUMMARIES_JOB)
    ).scalar()
    return held


def _posted(connection: Connection, held: datetime | None) -> None:
    """Rewrite the price points and facts of the invoices posted since the watermark
    `held` (minus the overlap)."""
    query = select(invoice.c.id, invoice.c.supplier_id, invoice.c.posted_at).where(
        invoice.c.posted_at.is_not(None)
    )
    if held is not None:
        query = query.where(invoice.c.posted_at > held - OVERLAP)
    posted = connection.execute(query).all()
    if not posted:
        return
    ids = [row.id for row in posted]
    # AD-20: straight-through means the invoice never went to the admin queue.
    routed: set[UUID] = set(
        connection.execute(
            select(status_history.c.invoice_id).where(
                status_history.c.invoice_id == any_(id_array(ids)),
                status_history.c.to_status == InvoiceStatus.IN_ADMIN_QUEUE.value,
            )
        ).scalars()
    )
    # AD-18: the current values, so a corrected line counts once, as corrected.
    values = current_values_of(connection, ids, (INVOICE_DATE, INVOICE_TOTAL))
    facts: list[InvoiceFact] = []
    points: list[PricePoint] = []
    for row in posted:
        fact, invoice_points = posted_summary(
            row.id,
            row.supplier_id,
            row.posted_at,
            row.id not in routed,
            values.get(row.id),
        )
        facts.append(fact)
        points.extend(invoice_points)
    connection.execute(
        delete(price_point).where(price_point.c.invoice_id == any_(id_array(ids)))
    )
    connection.execute(
        delete(invoice_fact).where(invoice_fact.c.invoice_id == any_(id_array(ids)))
    )
    connection.execute(insert(invoice_fact), [vars(fact) for fact in facts])
    if points:
        connection.execute(insert(price_point), [vars(point) for point in points])
    latest: datetime = max(row.posted_at for row in posted)
    upsert = pg_insert(watermark).values(job=SUMMARIES_JOB, posted_at=latest)
    connection.execute(
        upsert.on_conflict_do_update(
            index_elements=[watermark.c.job],
            # Only forward, whatever was processed.
            set_={
                "posted_at": func.greatest(
                    watermark.c.posted_at, upsert.excluded.posted_at
                )
            },
        )
    )


def _evidence(point: PricePoint) -> dict[str, str]:
    return {
        "invoice_id": str(point.invoice_id),
        "invoice_date": point.invoice_date.isoformat(),
        "unit_price": str(point.unit_price),
    }


def _alert_row(rise: PriceRise, held: datetime | None, at: datetime) -> dict[str, Any]:
    current = rise.current
    detail: dict[str, Any] = {
        "supplier_id": str(current.supplier_id),
        "material_id": str(current.material_id),
        "pct": str(rise.pct),
        "previous": _evidence(rise.previous),
        "current": _evidence(current),
    }
    # A rise posted before this run's window (all of them on a first run) is history:
    # stored for the page, but marked emailed so Story 5.2 never mails a backlog.
    backfilled = held is None or current.posted_at <= held - OVERLAP
    if backfilled:
        detail["backfilled"] = True
    return {
        "alert_id": new_uuid7(),
        "kind": PRICE_RISE,
        "dedupe_key": rise.dedupe_key,
        "supplier_id": current.supplier_id,
        "material_id": current.material_id,
        "detail": detail,
        "emailed_at": at if backfilled else None,
    }


def _price_rise_alerts(
    connection: Connection, held: datetime | None, at: datetime
) -> None:
    """AD-20 (Story 5.3): one alert per price rise over every price point, after this
    run's points are written; `held` is the watermark this run started from. ON
    CONFLICT DO NOTHING: a rerun, or a reprocessed invoice whose price is unchanged,
    keeps the alert it had."""
    points = [
        PricePoint(**row._asdict())
        for row in connection.execute(
            select(
                price_point.c.invoice_id,
                price_point.c.line_no,
                price_point.c.supplier_id,
                price_point.c.material_id,
                price_point.c.invoice_date,
                price_point.c.unit_price,
                price_point.c.posted_at,
            )
        )
    ]
    rows = [_alert_row(rise, held, at) for rise in price_rises(points)]
    if rows:
        connection.execute(
            pg_insert(alert).on_conflict_do_nothing(index_elements=["dedupe_key"]),
            rows,
        )


def write_summaries(
    connection: Connection, receipts: Sequence[ReceiptLine], at: datetime
) -> None:
    """Every summary write of one run, in the caller's transaction; `at` is the run's
    time."""
    held = _watermark(connection)
    _posted(connection, held)
    _price_rise_alerts(connection, held, at)

    facts = [
        InvoiceFact(**row._asdict())
        for row in connection.execute(
            select(
                invoice_fact.c.invoice_id,
                invoice_fact.c.supplier_id,
                invoice_fact.c.invoice_date,
                invoice_fact.c.posted_month,
                invoice_fact.c.total,
                invoice_fact.c.straight_through,
            )
        )
    ]
    _replace(connection, supplier_month, supplier_months(facts))
    _replace(connection, month_summary, month_summaries(facts))

    # AD-20: the one input not limited to posted invoices.
    duplicate = func.bool_or(admin_item.c.reason == ReasonCode.DUPLICATE.value)
    flagged = connection.execute(
        select(invoice.c.supplier_id, invoice.c.created_at, duplicate)
        .join(admin_item, admin_item.c.invoice_id == invoice.c.id)
        .group_by(invoice.c.id)
    ).all()
    _replace(
        connection,
        supplier_month_flags,
        supplier_flags((row[0], row[1], bool(row[2])) for row in flagged),
    )

    connection.execute(delete(receipt_lateness))
    if receipts:
        connection.execute(
            insert(receipt_lateness),
            [
                {
                    "receipt_id": line.receipt_id,
                    "po_line_id": line.po_line_id,
                    "supplier_id": line.supplier_id,
                    "material_id": line.material_id,
                    "received_date": line.received_date,
                    "days_late": days_late(line.expected_date, line.received_date),
                }
                for line in receipts
            ],
        )
    _replace(
        connection,
        supplier_on_time,
        on_time_rates(
            (line.supplier_id, days_late(line.expected_date, line.received_date))
            for line in receipts
        ),
    )
