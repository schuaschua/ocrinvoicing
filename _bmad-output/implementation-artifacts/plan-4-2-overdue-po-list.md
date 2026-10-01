---
title: 'Story 4.2: Overdue PO list'
type: 'feature'
ticket: '4-2-overdue-po-list'
created: '2026-09-30'
status: 'built'
route: 'full'
route_source: 'auto'
review: 'thorough'
review_source: 'auto'
lenses_ran: ['blind-hunter', 'edge-case-hunter', 'verification-gap', 'intent-alignment']
review_loop_iteration: 0
baseline_revision: '38e11d8fdac4152a64d6f5b391629a148c7e52b3'
context:
  - '{project-root}/docs/standards/coding-style.md'
  - '{project-root}/docs/standards/security.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Procurement can't see which POs are past their expected date with no invoice, so missing invoices aren't chased (CAP-12, FR12).

**Approach:** Create the analytics refresh job (AD-13), which is the only writer of the new `analytics` schema. It is a `pipeline` timer on weekdays at 01:30, 04:30 and 08:30 UTC. At the first run each day that finds the database up, it rebuilds `analytics.overdue_po` from `PurchasingPort.list_overdue_pos(today, Singapore date)`, dropping every PO that a non-`rejected` invoice has as its current `po_number`. staff-api gets a read-only list API, and `web/staff` gets the Overdue POs screen: POs grouped by supplier, with the date the list was made.

## Boundaries & Constraints

**Always:**
- The overdue rule is AD-13's, word for word: the earliest line `expected_date` is before today's Singapore date, and no invoice whose `status` is not `rejected` has `intake.invoice.po_number` equal to that PO. An invoice waiting in the admin queue counts as invoiced.
- The whole rebuild is one transaction: replace the rows, then record the day's run. A failed run leaves the previous list and its date, and the next timer retries.
- Once-a-day guard: a day with a recorded run does nothing, and two concurrent runs can't both write (lock inside the transaction).
- Stopped database (`DatabaseOfflineError`): log `analytics_refresh.skipped code=DB_OFFLINE` and exit. It catches up at the next run. Today's date comes from an injected clock, so tests never sleep.
- `Surface.OVERDUE_POS` (admin, procurement, finance): 401 when signed out, 403 for any other role, 503 `DB_OFFLINE` through the existing client handling. `platform_auth_trusted` is passed explicitly.
- Grants in the migration (AD-11): `pipeline` gets read/write on `analytics`; `staff-api` gets read only. Role names come from `-x`, never literals. The migration is backward-compatible (new schema only).
- The web app follows the existing screens: strings in `strings.ts`, calls through `api/`, and design tokens only.
- At most **3** new test cases. Grant assertions go into the existing migration test.

**Never:**
- supplier reminders or the `supplierreminders` table (Story 4.3);
- Epic 5 summary tables or alerts;
- any write to `analytics` from staff-api or from any pipeline stage;
- changes to `PurchasingPort` or the simulator's `list_overdue_pos`;
- pushing, deploying or touching Azure (offline session).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| FR12 | PO expected 7 Jan, no invoice; run on 8 Jan (SGT) | Listed under its supplier; list date 8 Jan | — |
| Invoiced | Same PO, an invoice with that `po_number` in any status except `rejected` (e.g. `in_admin_queue`) | Not listed | — |
| Rejected only | Its only invoice is `rejected` | Listed | — |
| Not yet due | Earliest line expected today or later | Not listed | — |
| Catch-up | No run on 8 Jan; first run on 9 Jan | 7 Jan PO listed; a PO expected Sat 10 Jan appears on Mon 12 Jan | — |
| Second run same day | The day's run already recorded | No change | — |
| DB stopped | Timer fires | Skipped, logged `DB_OFFLINE` | Next run catches up |
| Never made | No run yet | API `madeAt: null`; UI says the list is made each weekday morning | — |
| None overdue | Run made, 0 rows | UI "No overdue POs." with the date | — |
| Wrong role | goods_in, management | 403 | — |

</frozen-after-approval>

## Code Map

- `backend/src/invoicing/ports/purchasing.py`, `adapters/purchasing_sim/adapter.py` -- `list_overdue_pos(as_of)` and `OverduePo(po_number, supplier_id, expected_date)` already exist. Reuse them unchanged.
- `backend/migrations/versions/0009_sim_accounts.py`, `0001_intake.py` -- the migration and grant pattern (`context.config.attributes["roles"]`, `pipeline_role`, `staff_api_role`, quoted identifiers, a downgrade that revokes). The new migration is `0010_analytics.py`, with `analytics.overdue_po(po_number PK, supplier_id, expected_date)` and `analytics.job_run(job, run_date, finished_at; PK job+run_date)`.
- `backend/src/invoicing/adapters/postgres/schema.py`, `engine.py` (`open_connection`, which raises `DatabaseOfflineError`) -- Core table pattern. Add the analytics tables in their own metadata.
- New `ports/analytics.py` and `adapters/postgres/analytics.py` -- the refresh store (`refresh_overdue(run_date, pos, finished_at)`, which returns False when that day already ran) and the reader (`overdue_list()` gives the rows plus the latest `finished_at`). Check the import-linter contracts in `backend/pyproject.toml`.
- `backend/src/invoicing/apps/pipeline/sweeper.py` and `function_app.py` -- the timer and job-class pattern (`SWEEP_SCHEDULE`, `run_on_startup=False`, `use_monitor=True`, `log_event`). The new file is `apps/pipeline/analytics_refresh.py`, with `REFRESH_SCHEDULE = "0 30 1,4,8 * * 1-5"`.
- `backend/src/invoicing/apps/staff_api/invoices.py` and `function_app.py` -- the endpoint pattern (`staff_endpoint`, `json_response`, `Surface`). The new file is `apps/staff_api/overdue.py`, serving `GET api/overdue-pos`. Supplier names come from `adapters/postgres/suppliers.py` (`PostgresSupplierDirectory` / `supplier_names`).
- `backend/src/invoicing/domain/roles.py` -- `Surface.OVERDUE_POS` already exists. Don't change it.
- `web/staff/src/App.tsx` -- `overdue_pos` renders `SurfacePage` today. Swap in the new screen. `surfaces.ts` already has `/overdue-pos`. See also `strings.ts` (the `nav.overdue_pos` label exists), `api/invoices.ts`, `api/index.ts`, `lib/format.ts`, and `screens/InvoicesScreen.tsx` for the patterns.
- `backend/tests/conftest.py` -- `postgres_server`, `intake_database`, `purchasing_seeded`, `pipeline_engine`, `login_engine`. `tests/apps/test_story_4_1_goods_in.py` shows the staff-api tests. `tests/migrations/test_migrations.py` covers the grants.

## Tasks & Acceptance

**Execution:**
- [x] `backend/migrations/versions/0010_analytics.py` -- create the schema, both tables and the grants, with a downgrade -- AD-11 and AD-13 storage.
- [x] `backend/src/invoicing/ports/analytics.py`, `adapters/postgres/analytics.py` -- the store and the reader. The rebuild runs in one transaction with an advisory lock, and the non-rejected-invoice filter runs in SQL against `intake.invoice` -- keeps it atomic and once a day.
- [x] `backend/src/invoicing/domain/` -- a `singapore_date(now)` helper -- one definition of "today".
- [x] `backend/src/invoicing/apps/pipeline/analytics_refresh.py`, `function_app.py` -- the `AnalyticsRefresh` job class, the timer, and the offline skip -- the AD-13 job, which Stories 4.3 and 5.x will extend.
- [x] `backend/src/invoicing/apps/staff_api/overdue.py`, `function_app.py` -- `GET api/overdue-pos` returns `{madeAt, suppliers:[{supplierId, supplierName, pos:[{poNumber, expectedDate}]}]}`, with suppliers sorted by name and POs by expected date then number -- the grouped list.
- [x] `web/staff/src/api/overdue.ts`, `screens/OverduePosScreen.tsx`, `strings.ts`, `App.tsx` -- the screen shows "As of {date}", a section per supplier, and the empty and never-made states -- CAP-12 UI.
- [x] Tests (≤3 new cases): `backend/tests/apps/test_story_4_2_overdue.py` with `test_story_4_2_refresh_job` (FR12, invoiced/rejected, not due, catch-up and weekend, same-day no-op, DB offline) and `test_story_4_2_overdue_api` (grouping, madeAt, never made, 401/403); `web/staff/src/screens/OverduePosScreen.test.tsx` with one `describe("4.2 …")` case (grouping, date, empty). Add the grant assertions to `test_migrations.py`.

**Acceptance Criteria:**
- Given the job ran today, when staff-api reads `analytics`, then it can SELECT but not INSERT, UPDATE or DELETE.
- Given an admin, procurement or finance user, when they open Overdue POs, then the POs show grouped by supplier with the date the list was made.
- Given the seeded simulator, when the job runs, then only the purchasing adapter reads `sim_purchasing` (no direct SQL on it from the job).

## Implementation Notes

- `singapore_date` lives in `domain/dates.py`; goods-in's `_today` now uses it too (one definition of "today").
- The rebuild inserts purchasing's POs, then deletes those a non-`rejected` invoice names (`EXISTS` on `intake.invoice`), then records `job_run`, all under `pg_advisory_xact_lock(0x4F5644)`; the guard is read after the lock. `madeAt` is the latest `finished_at` of job `overdue_po`, read in the same REPEATABLE READ snapshot as the rows.
- The `pipeline` pool grows from 9 to 10 connections, one for the new timer (engine.py's one-per-function rule).
- The API wire is camelCase, as this plan specifies; other staff-api routes are snake_case.
- Tests use the seeded simulation's September dates instead of the matrix's January ones: Fri 25 Sep, then Mon 28 Sep (weekend), then Wed 30 Sep (missed Tuesday). An unknown supplier sorts last with a null name.
- (orchestrator) The API's wire names were switched to snake_case (`made_at`, `supplier_id`, `supplier_name`, `pos[].po_number`, `expected_date`), matching every other staff-api route; `web/staff/src/api/overdue.ts` maps them to camelCase like `api/invoices.ts`. The plan's camelCase shape was a planning slip (coding-style.md rule 3).

## Plan Change Log

## Review Triage Log

### Pass 1 (2026-10-01): high 0, medium 2, low 6, false 5, maybe-false 0; lenses run one at a time (Dj: no parallel agents)

| # | Lens | Finding | Verdict | Route | Evidence / action |
|---|---|---|---|---|---|
| 1 | BH, EC, IA | "As of" date in the browser's time zone | medium | patch | Viewer west of UTC-1:30 saw the previous day. Now formatted in Asia/Singapore; web test uses 17:30Z. |
| 2 | VG, IA | `analytics_refresh` timer binding untested | medium | patch | Asserts added to the Story 2.2 function-app test (schedule, runOnStartup, useMonitor). |
| 3 | BH | Pipeline grants wider than used (UPDATE; DELETE on job_run) | low | patch | Per-table grants; test_migrations checks UPDATE and job_run DELETE are refused. |
| 4 | VG | App route to the screen untested | low | patch | Block added to the existing 2.7 App test. |
| 5 | BH | `supplier_name` loosely parsed | low | patch | Only string or null accepted. |
| 6 | BH | Positional INSERTs in tests | low | patch | Columns named. |
| 7 | BH, VG | Screen error/retry path untested | low | defer | 200-case cap; fold into the 4.2 web test later. |
| 8 | BH | No structured log on a failed run | low | defer | Host logs the exception; no alert on a stale list. |
| 9 | BH | Exact PO string match | false | reject | validate stores the purchasing PO's own `po_number` (validate.py:155, 182). |
| 10 | EC | In-flight invoice (po_number NULL) leaves PO listed | false | reject | AD-13 rule is the current `po_number`; next day's run drops it; asserted as intended. |
| 11 | EC | No lock_timeout on the advisory lock | false | reject | The lock is held only for one short transaction; the host's function timeout bounds it. |
| 12 | BH | Purchasing read on already-ran days; finished_at taken before the lock; POOL_SIZE; run() re-raise untested; stale-list flag | low | reject | Negligible cost or seconds of skew; fixes add branches; the "As of" date already shows staleness. |
| 13 | EC, IA | Plan says camelCase; D2 per-job exclusivity; E5 roles | false | reject | Plan note records snake_case; exclusivity is by login (AD-11); roles are EXPERIENCE.md's. |

## Design Notes

"Computed from the last successful run" needs no watermark: each run recomputes from purchasing as of today, so a missed day or a weekend is covered by the next run. Purchasing is read before the write transaction (the adapter opens its own connection), and the invoice filter runs inside it, so an invoice that arrives between the two is still honoured.

## Verification

**Commands:**
- `cd backend && uv run pytest tests/apps/test_story_4_2_overdue.py tests/migrations -q` -- expected: pass (Docker Postgres)
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run lint-imports` -- expected: clean
- `cd web/staff && npm run lint && npx tsc --noEmit && npx vitest run` -- expected: pass
- `ci/checks.sh` test-case count -- expected: ≤ 200
