---
title: 'Story 5.1: Analytics refresh builds the summary tables'
type: 'feature'
ticket: '5-1-analytics-refresh-builds-the-summary-tables'
created: '2026-10-01'
status: 'built'
route: 'full'
route_source: 'auto'
review: 'thorough'
review_source: 'auto'
lenses_ran: ['blind-hunter', 'edge-case-hunter', 'verification-gap', 'intent-alignment']
review_loop_iteration: 0
baseline_revision: 'e0450b7dbd71b4ddbc84fea4a90a0f6126c32834'
context:
  - '{project-root}/docs/standards/coding-style.md'
  - '{project-root}/docs/standards/security.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Price comparison, the watchlist, scorecards and the finance month view (5.3–5.6) need supplier figures, and dashboards must never compute them from the invoice tables (AD-13, AD-20, P-10).

**Approach:** The Story 4.2/4.3 analytics refresh job gets a daily summary step, guarded once a day like the overdue list. It writes these `analytics` tables by the AD-20 rules:
- price points from posted invoice lines, using AD-18 current values;
- per-receipt lateness and per-supplier on-time rates over the last 365 days;
- spend per supplier and month;
- flagged and duplicate counts per supplier and month;
- the monthly straight-through share.

The migration also adds `analytics.alert` (with `emailed_at`) for Stories 5.2–5.4. A read-only dashboard repository is the only way staff-api will read these tables.

## Boundaries & Constraints

**Always:**
- **Posted invoices (incremental).** Reprocess every invoice with `posted_at > watermark − 1 hour`, idempotently by `invoice_id`: delete that invoice's rows, then insert. Advance `analytics.watermark(job='summaries')` to the highest `posted_at` processed, all in one transaction. The first run has no watermark and processes everything posted.
  - The lines come through the AD-18 rule (`domain/current_values.current_values`), so a corrected line counts once with its corrected value.
  - **`price_point`:** one row per current line that has a `material_id`: `(invoice_id, line_no) PK, supplier_id, material_id, invoice_date, unit_price, posted_at`.
    - `invoice_date` is the current `invoice_date` field. When it is missing, use `posted_at` as a Singapore date.
    - The currency is the configured `INVOICE_CURRENCY` (SGD).
  - **`invoice_fact`:** `(invoice_id PK, supplier_id, invoice_date, posted_month, total, straight_through)`.
    - `posted_month` is the first day of the Singapore month of `posted_at`.
    - `straight_through` means its `status_history` never includes `in_admin_queue`.
    - `total` is the current `invoice_total`.
- **Derived tables, recomputed in full from `invoice_fact` each run:**
  - `supplier_month(supplier_id, month, spend, posted_count)`, by `posted_month`;
  - `month_summary(month, posted_count, straight_through_count, straight_through_share)`.
- **Flagged and duplicate counts (not limited to posted, AD-20).** Recomputed in full each run into `supplier_month_flags(supplier_id, month, flagged_count, duplicate_count)`, by the Singapore month of the invoice's `created_at`.
  - Flagged: an invoice with at least one `admin_item`.
  - Duplicate: an invoice with an `admin_item` whose reason is `DUPLICATE`.
- **Lateness (recomputed in full each run).**
  - Read through a new `PurchasingPort.receipt_lines(since)`, never SQL on `sim_purchasing` from the job. It returns `receipt_id, po_line_id, supplier_id, material_id, expected_date, received_date` for receipts with `received_date >= today − 365`.
  - `receipt_lateness(receipt_id, po_line_id) PK, supplier_id, material_id, received_date, days_late` stores `received − expected`, so on time is `days_late <= 0`.
  - `supplier_on_time(supplier_id PK, receipts, on_time, on_time_rate, avg_days_late)`. A supplier with no receipts in the window has no row.
- **Money and rates.** Money is `numeric(18,2)` and `Decimal` in Python. Rates are `numeric(5,4)`, rounded half-up.
- **Once a day.** `job_run` records job `summaries` with the Singapore date. The summary step runs after the overdue step, whether that step refreshed or had already run. Its failures are logged as `analytics_refresh.summaries_failed code=…` and leave the day unrecorded, as the Story 4.3 weekly step does. `run()` still returns the overdue code.
- **`analytics.alert`.** Columns: `alert_id uuid PK, kind text, dedupe_key text UNIQUE, supplier_id, material_id NULL, detail jsonb, created_at, emailed_at NULL`. This story creates it and writes nothing to it.
- **Migration `0011_analytics_summaries`.** It is backward-compatible. The pipeline gets the per-table grants it uses (SELECT, INSERT, DELETE; UPDATE only on `watermark` and on `alert` for `emailed_at`). staff-api gets SELECT only. Role names come from `-x`.
- **Dashboard repository.** `ports/dashboards.py` and `adapters/postgres/dashboards.py` give staff-api's read-only access to `analytics.*` only: price points, on-time rates, supplier months, month summaries and alerts. Each method has a short docstring. Later stories add methods, and nothing here is exposed over HTTP yet.
- **Tests.** At most **3** new test cases. Grant assertions go into the existing migration test.

**Never:**
- dashboards or APIs (5.3–5.6);
- price-rise or watchlist rules, or rows in `analytics.alert` (5.3, 5.4);
- email (5.2);
- writes to `analytics` from staff-api;
- reading invoice tables from staff-api for dashboards;
- touching Azure.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| First run | 3 posted invoices, no watermark | Their price points and facts; watermark = max `posted_at` | — |
| Incremental | 1 more posted later | Only it is processed; earlier rows unchanged | — |
| Late commit | Invoice with `posted_at` 30 min before the watermark appears | Picked up by the −1 h overlap, counted once | — |
| Rerun | Same invoice reprocessed | Same rows, no duplicates | — |
| Corrected line | Admin corrected line 2's `unit_price` | Price point uses the corrected value, once | — |
| No material | Line without `material_id` | No price point | — |
| Missed day | No run yesterday | Today processes everything since the watermark | — |
| Straight-through | One posted via the admin queue, one not | Month share 0.5000 | — |
| Flags | Unposted invoice with a `DUPLICATE` item | `flagged_count` 1, `duplicate_count` 1 for its month | — |
| Lateness | Receipt 3 days after expected; one 1 day early | `days_late` 3 and −1; `on_time_rate` 0.5000, `avg_days_late` 1.00 | — |
| Window | Receipt 400 days old | Not counted | — |
| Same day again | `summaries` already ran today | No work | — |
| DB stopped | Timer fires | Whole run `DB_OFFLINE` (existing) | — |
| Step fails | Error in the summary step | `summaries_failed` logged, day unrecorded; overdue result returned | Next run retries |

</frozen-after-approval>

## Code Map

- `backend/src/invoicing/apps/pipeline/analytics_refresh.py` (Stories 4.2 and 4.3): `AnalyticsRefresh.run`, the overdue step, and the weekly reminders step with its own error handling and logging. Add the summary step in the same shape.
- `backend/src/invoicing/adapters/postgres/analytics.py`, `ports/analytics.py`: the `job_run` guard pattern (`OVERDUE_JOB`, `reminders_done`/`record_reminders`), the advisory lock, and the REPEATABLE READ reader. Add the summary writes here, or in a sibling module if it grows past about 300 lines.
- `backend/src/invoicing/adapters/postgres/schema.py`: the `analytics_metadata` tables (`overdue_po`, `job_run`) and the intake tables (`invoice.posted_at`, `status_history`, `admin_item`, `extraction_run`, `invoice_field`, `invoice_line.material_id`). Add the new analytics tables there.
- `backend/src/invoicing/domain/current_values.py`: `current_values(runs, fields, lines)`, `RunRow`, `FieldValue`, `LineValue`. Find the adapter that already loads these rows for one invoice (`grep -rn current_values backend/src/invoicing/adapters`) and reuse its loading for a batch of invoice ids.
- `backend/src/invoicing/domain/dates.py`: `singapore_date`. Put the pure helpers (month start, rate rounding, the lateness aggregate) in `domain/analytics.py`.
- `backend/src/invoicing/ports/purchasing.py`, `adapters/purchasing_sim/adapter.py`: add `receipt_lines(since)`, joining `goods_receipt`, `goods_receipt_line`, `po_line`, `delivery` and `purchase_order`. Also update the purchasing contract test if it enumerates methods.
- `backend/migrations/versions/0010_analytics.py`: the grant and downgrade pattern for `0011`.
- `backend/tests/apps/test_story_4_2_overdue.py`, `test_story_4_3_reminders.py`: the job fixtures, `FakeReminders`, the clock, and how posted invoices and admin items are seeded (see `_validation_seed.py` / `_pipeline_fakes.py`). `tests/migrations/test_migrations.py` has the grant assertions.

## Tasks & Acceptance

**Execution:**
- [x] `backend/migrations/versions/0011_analytics_summaries.py` and `schema.py`: the tables, `alert`, `watermark` and grants.
- [x] `ports/purchasing.py`, `adapters/purchasing_sim/adapter.py`: `receipt_lines(since)`.
- [x] `domain/analytics.py`: the pure helpers.
- [x] `ports/analytics.py`, `adapters/postgres/analytics.py` (or `analytics_summaries.py`): the incremental posted-invoice step and the full recomputes.
- [x] `apps/pipeline/analytics_refresh.py`, `function_app.py`: the summary step.
- [x] `ports/dashboards.py`, `adapters/postgres/dashboards.py`: the read-only repository.
- [x] Tests (at most 3 new cases):
  - `test_story_5_1_incremental_summaries` covers first run, incremental, late commit, rerun, corrected line, no material, missed day, straight-through, flags and same day;
  - `test_story_5_1_lateness` covers lateness, window and rates;
  - optionally `test_story_5_1_dashboard_reads`, showing staff-api reads through the repository only.

**Acceptance Criteria:**
- Given the job, when it writes, then it writes only to `analytics.*`, and only the pipeline login can.
- Given staff-api, when it reads dashboard data, then it uses `ports/dashboards.py`, which touches only `analytics.*`.

## Implementation Notes

- **Store shape.** The summary step lives on the existing `AnalyticsStore` (`summaries_done`, `refresh_summaries`), so `AnalyticsRefresh`'s constructor and the pipeline wiring are unchanged. `PostgresAnalyticsStore.refresh_summaries` takes its own advisory lock (`SUMMARIES_LOCK_KEY`), rechecks `job_run` under it and delegates the writes to the new `adapters/postgres/analytics_summaries.py`.
- **Step order.** The summary step runs after the overdue step and the weekly reminders step, each failure-isolated.
- **AD-18 batch loading.** The new public `current_values_of(connection, ids, field_ids)` in `adapters/postgres/validation.py` reuses that module's column lists and row mappers; never a bank ciphertext.
- **Interpretations.** `receipts`/`on_time` count receipt lines (the `receipt_lateness` PK). `avg_days_late` counts early receipts as negative days, is `numeric(8,2)`. A current line with a material but no `unit_price` has no price point. `unit_price` and `total` are stored as `numeric(18,2)` (rounded half-up). `invoice_fact.total` is nullable (summed as 0). `supplier_month_flags` holds only supplier months with at least one flagged invoice. No currency column: the plan's column list has none, and AD-20 is SGD only.
- **Grants.** `alert` gets `SELECT, INSERT, UPDATE (emailed_at)` for the pipeline (column-level), `watermark` `SELECT, INSERT, UPDATE`; the rest `SELECT, INSERT, DELETE`. staff-api SELECT on all nine.
- **Dashboard repository.** `DashboardReader` methods: `price_points(since)`, `on_time_rates()`, `supplier_months(since)` (spend merged with flags), `month_summaries(since)`, `alerts(since)`. Not wired into staff-api's `function_app.py` (no HTTP yet).
- **Tests.** 2 new cases (`test_story_5_1_incremental_summaries`, `test_story_5_1_lateness`); the dashboard read and "only `analytics` tables" check are folded into the first. `receipt_lines` assertions were added to the existing purchasing contract case, and the grant assertions to the existing migration case. Suite total 173/200.

- (orchestrator, after review) The overdue step's non-offline errors no longer skip the weekly and summary steps: they are logged as `analytics_refresh.overdue_failed` and re-raised at the end. The lateness window is 364 days back (365 inclusive). Only lines with a material and `unit_price > 0` become price points. Batch id filters bind one array parameter (`id_array`).

## Plan Change Log

## Review Triage Log

### Pass 1 (2026-10-01): high 0, medium 4, low 9, false/rejected 9; lenses run one at a time

| # | Lens | Finding | Verdict | Route | Evidence / action |
|---|---|---|---|---|---|
| 1 | BH, EC | Batch ids in `IN (...)` exceed the 65,535-parameter limit on a large backlog | medium | patch | One `ARRAY(Uuid)` bind (`id_array`) everywhere. |
| 2 | BH, EC, IA | Overdue-step error skipped the summaries | medium | patch | Logged `overdue_failed`, later steps run, error re-raised; tested. |
| 3 | VG | Unparseable typed `invoice_date` fallback untested; a regression stalls all summaries | medium | patch | inv8 with "14/09/2026" asserted. |
| 4 | VG | Posted invoice without a total untested | medium | patch | inv8 has no total; counts and spend asserted. |
| 5 | EC | Discount/credit lines became price points | low | patch | `unit_price > 0` only; asserted. |
| 6 | EC | Lateness window spanned 366 days | low | patch | 364 days back; edge receipt asserted excluded. |
| 7 | BH | Positional VALUES and a hard-coded table count in tests | low | patch | Named columns; tables listed. |
| 8 | BH | `alert` unique constraint unnamed; schema.py lacked server defaults | low | patch | `uq_alert_dedupe_key`; defaults mirrored. |
| 9 | EC | Mid-month `since` dropped that month | low | patch | Normalised to the month's first day. |
| 10 | BH | No "as of" date for dashboards | low | defer | Dashboards (5.3–5.6) can add it from `job_run`. |
| 11 | BH | No test that a failure after `_posted` rolls everything back | low | defer | One transaction by construction. |
| 12 | BH | No unit tests for `domain/analytics.py` | low | defer | 200-case cap; covered via integration. |
| 13 | VG | Summaries lock re-check untested | low | defer | Same pattern as the tested overdue rebuild. |
| 14 | VG | `price_points(since)` filter never observed | low | defer | Story 5.3 pins it. |
| 15 | BH | Unit prices rounded to 2 decimals | false | reject | Purchasing stores PO unit prices at numeric(18,2); the price-rise comparison is like for like. |
| 16 | IA | Lateness per receipt line, not per receipt | low | reject | The plan's documented design (`receipt_lateness` PK receipt + PO line). |
| 17 | BH | `invoice_fact` never pruned if an invoice stops being posted | false | reject | `posted` is terminal (AD-3). |
| 18 | VG, IA | Edits to invoices posted before the watermark ignored | false | reject | AD-20's incremental rule; asserted as intended. |
| 19 | EC | Posting committed over 1 h after `posted_at` | low | reject | AD-20's 1-hour overlap is the accepted bound. |
| 20 | BH | Missing indexes; unbounded full recomputes | low | reject | PoC volume. |
| 21 | EC | NaN or huge values roll back the day | low | reject | Values come from Decimal columns of bounded scale. |
| 22 | IA | Weekday-only runs; staff-api not enforced to read only `analytics` | false | reject | AD-13 weekday timers; staff-api's intake read grant is AD-11 by design, and dashboards go through `ports/dashboards.py`. |

## Design Notes

**Month choices.**
- Spend and the straight-through share use the posted month, because both are about posted invoices.
- Flags use the received month (`created_at`), because flagged invoices may never be posted.

**Incremental and full.** The incremental part is limited to what depends on posted invoices. Everything derived from it, plus lateness and flags, is cheap at PoC volume and recomputed in full. That keeps idempotency trivial.

## Verification

**Commands:**
- `cd backend && uv run pytest tests -q -k "5_1 or 4_2 or 4_3 or migrations or contract"`: should pass (Docker Postgres).
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run lint-imports`: should be clean.
- `ci/checks.sh test`: should stay at or under 200 cases.
