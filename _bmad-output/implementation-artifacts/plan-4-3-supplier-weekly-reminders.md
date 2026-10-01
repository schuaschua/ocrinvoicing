---
title: 'Story 4.3: Suppliers see weekly reminders on their upload page'
type: 'feature'
ticket: '4-3-suppliers-see-weekly-reminders-on-their-upload-page'
created: '2026-10-01'
status: 'built'
route: 'full'
route_source: 'auto'
review: 'thorough'
review_source: 'auto'
lenses_ran: ['blind-hunter', 'edge-case-hunter', 'verification-gap', 'intent-alignment']
review_loop_iteration: 0
baseline_revision: '1b777ab79099bb868b0ad9baa2b922a05e48f9c2'
context:
  - '{project-root}/docs/standards/coding-style.md'
  - '{project-root}/docs/standards/security.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Suppliers only learn that a delivery still needs an invoice when someone chases them (CAP-13, FR13).

**Approach:**
- Extend the Story 4.2 analytics refresh job with a weekly step. At its first successful run of each ISO week (Singapore date), it replaces the `supplierreminders` Table rows with one row per overdue PO from `analytics.overdue_po`, re-checking each PO against `intake` just before writing it (AD-6, AD-13).
- supplier-api gets `GET /api/reminders`, which reads the caller's partition from Table Storage only, so it works while PostgreSQL is stopped.
- Upload home shows the read-only banner "2 deliveries are waiting for an invoice: PO 45012, PO 45019."
- No email is ever sent to a supplier.

## Boundaries & Constraints

**Always:**
- **Weekly guard.** The guard is an `analytics.job_run` row for job `supplier_reminders` whose `run_date` is the Monday of the ISO week. It is written only after every Table write succeeded, so a failed week retries at the next timer.
- **Independent of the overdue result.** The step runs whether the day's overdue rebuild just ran or had already run, as long as the week isn't done.
- **Replace, don't append.** Each supplier's partition ends up exactly equal to that supplier's overdue POs. Rows for POs no longer overdue are deleted, and so are partitions of suppliers with none left.
- **Re-check before writing.** Just before writing a supplier's rows, drop every PO that a non-`rejected` invoice now carries (the Story 2.6 delete is never undone).
- **Keys in the request body.** Table keys travel only in `submit_transaction` bodies, as `adapters/table_reminders.py` does: one transaction per partition, at most 100 operations. Key-scheme rules come from `ports/reminders.py`; a PO number the Table can't hold is skipped and logged by code, never by value.
- **`GET /api/reminders`:**
  - The supplier comes only from the `X-Upload-Token` link (`current_link`). A bad link gives the same 401 `LINK_NOT_VALID`.
  - It returns `{po_numbers: [...]}`, sorted.
  - It never touches PostgreSQL, and a Table outage gives 503 through the existing error mapping.
- **Upload home:**
  - It fetches reminders after the link resolves.
  - Any failure, or an empty list, shows no banner and never blocks uploading.
  - The copy lives in `strings.ts`, with the singular "1 delivery is waiting for an invoice: PO 45012." PO numbers are shown with the existing PO label format.
- **Tests:** at most **3** new test cases.

**Never:**
- supplier emails or any notification channel;
- a supplier choosing or seeing another supplier's rows;
- supplier-api reading PostgreSQL;
- changes to the overdue rule or to Story 4.2's daily list;
- touching Azure.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| First run of the week | Mon, week not done; Alpha overdue PO-45012, PO-45019 | Alpha's partition = those 2 rows; week recorded | — |
| Later run, same week | Week already recorded | No Table writes | — |
| Missed Monday | Monday's runs found the DB stopped; Tue first up | Tuesday writes the week | Monday logged `DB_OFFLINE` |
| No longer overdue | Alpha's old row PO-45001 not in this week's list; Beta has none now | PO-45001 and Beta's rows deleted | — |
| Invoiced between list and write | PO-45019 gets a non-rejected invoice before Alpha's write | PO-45019 not written | — |
| Table write fails | One partition's transaction errors | Week not recorded; next run retries all | Logged `analytics_refresh.reminders_failed code=…` |
| Banner | Supplier with 2 rows opens link | "2 deliveries are waiting for an invoice: PO 45012, PO 45019." | — |
| DB stopped | Same, PostgreSQL stopped | Banner still shown | — |
| Cleanup | validate deleted PO-45012's row (Story 2.6) | Banner lists PO 45019 only | — |
| No reminders / reminders call fails | Empty partition, or 503 | No banner; upload works | Silent |
| Bad link | Unknown token | 401 `LINK_NOT_VALID` | Same as `/api/link` |

</frozen-after-approval>

## Code Map

- `backend/src/invoicing/apps/pipeline/analytics_refresh.py` (Story 4.2) -- `AnalyticsRefresh.run`: add the weekly step after the overdue refresh. `singapore_date` is in `domain/dates.py`. Log with `log_event`.
- `backend/src/invoicing/adapters/postgres/analytics.py`, `ports/analytics.py` -- add: read the current `overdue_po` rows; "is this PO invoiced" (the same non-rejected SQL as 4.2's purge); the weekly `job_run` check and record (job `supplier_reminders`, the Monday date). Reuse `job_run` and `OVERDUE_JOB`'s pattern. No migration is needed: the pipeline already has SELECT and INSERT on `job_run`.
- `backend/src/invoicing/ports/reminders.py`, `adapters/table_reminders.py` -- the key scheme and the transaction pattern. Add `replace_all(rows_by_supplier)` for the job (list the table, then one transaction per partition to delete stale rows and upsert current ones) and `list_for(supplier_id)` for supplier-api. `FakeReminders` in `backend/tests/apps/_pipeline_fakes.py` or equivalent.
- `backend/src/invoicing/apps/pipeline/function_app.py` -- `reminders` (`TableReminderStore`) already exists; pass it to `AnalyticsRefresh`.
- `backend/src/invoicing/apps/supplier_api/link.py` (`current_link`, `UPLOAD_TOKEN_HEADER`), `function_app.py` (route pattern, before the SPA catch-all), `upload.py` -- the pattern for the new `apps/supplier_api/reminders.py`.
- `infra/modules/env-foundation/main.tf` -- the `supplierreminders` table already exists, and both apps hold Storage Table Data Contributor. No infra change.
- `web/supplier/src/screens/UploadHome.tsx`, `App.tsx`, `api/link.ts`, `api/client.ts`, `strings.ts` -- add `api/reminders.ts` and the banner (read-only, `role="status"`). The supplier JS budget is 150 KB gzipped (`ci/lib.sh`).
- `backend/tests/apps/test_supplier_link.py`, `web/supplier/src/screens/UploadHome.test.tsx` -- test patterns. `backend/tests/apps/test_story_4_2_overdue.py` has the job fixtures.

## Tasks & Acceptance

**Execution:**
- [x] `ports/analytics.py`, `adapters/postgres/analytics.py` -- overdue rows read, invoiced re-check, weekly guard -- the job's DB side.
- [x] `ports/reminders.py`, `adapters/table_reminders.py` -- `replace_all` and `list_for`, with keys in transaction bodies -- the Table side.
- [x] `apps/pipeline/analytics_refresh.py`, `function_app.py` -- the weekly step and its logging -- CAP-13 writer.
- [x] `apps/supplier_api/reminders.py`, `function_app.py` -- `GET /api/reminders` -- the supplier's read.
- [x] `web/supplier/src/api/reminders.ts`, `screens/UploadHome.tsx`, `strings.ts` -- the banner -- FR13 UI.
- [x] Tests (≤3 new cases):
  - `test_story_4_3_weekly_reminders` covers the job rows of the matrix, with fakes for the Table store and Postgres for intake.
  - `test_story_4_3_reminders_api` covers the link, the sort, 401, 503, and no DB use.
  - One `describe("4.3 …")` web case covers the banner (plural and singular), none when empty or failed, and the upload still working.

**Acceptance Criteria:**
- Given the whole change, when searched, then no code path sends email or any message to a supplier.
- Given supplier-api, when the reminders route runs, then it constructs no PostgreSQL engine.

## Implementation Notes

- **Re-check timing.** `replace_all(rows_by_supplier, still_owed)` takes an async callback (the job's, backed by `AnalyticsStore.invoiced`) and calls it for each partition immediately before that partition's transaction(s), and again before a retry, so a PO invoiced after the listing is never written. There is no up-front batch check. The adapter holds no business rule: it only keeps what the callback returns.
- **Stale-row race.** A Table transaction fails whole when it deletes a row that is already gone (the validate stage deleting it between the listing and the write). `TableReminderStore` then re-reads that partition (a `$filter` query), re-checks it through `still_owed` and retries once, instead of failing the week. Within a partition, upserts go first and stale deletes last, so a reader or a failure part-way never sees too few rows.
- **Weekly guard.** `record_reminders` uses `INSERT … ON CONFLICT DO NOTHING` (INSERT privilege only), so two concurrent runs both writing the same rows is harmless. The week's Monday is `today - weekday()` on the Singapore date.
- **Failure codes.** The weekly step runs after the overdue result is settled and is handled on its own: any failure logs `analytics_refresh.reminders_failed` with `code=DB_OFFLINE`, the `ServiceUnavailableError` code (`SERVICE_UNAVAILABLE`), or the exception's type name, leaves the week unrecorded, and `run()` still returns the overdue code. The adapter also logs `reminders.unavailable code=<TRANSIENT|AUTH_FAILED|…>`.
- **Key rules.** `storable()` moved to `ports/reminders.py` (forbidden characters, control characters, 1 KiB limit) and is shared by `delete` and `replace_all`; skipped PO numbers are logged as `reminders.key_skipped code=UNSTORABLE_PO_NUMBER count=n`.
- **Web.** The reminders are fetched in `App` once the link resolves (once per visit) and passed to `UploadHome`. `poLabel` is copied into the supplier `strings.ts` with the staff app's format. The 1.7/1.8 App tests' fetch counts went up by one (the reminders call), and `e2e/screens.ts` stubs `/api/reminders` (Upload home's a11y screen now shows the banner); no new test cases there. The `role="status"` region is always rendered (empty, with no banner styling, when there are no reminders) so the text is announced when it arrives.
- **Tests.** 3 new cases: `test_story_4_3_weekly_reminders` runs the real `TableReminderStore` over an in-memory table (transaction rules enforced) with Postgres for purchasing, `intake` and `analytics`; `test_story_4_3_reminders_api` patches `Engine.__init__` to prove no engine is built; one `describe("4.3 …")` in `App.test.tsx`. `FakeReminders` gained `replace_all` for the Story 4.2 tests, which now pass it. Total 171 / 200.

## Plan Change Log

## Review Triage Log

### Pass 1 (2026-10-01): high 1, medium 2, low 7, false 3; lenses run one at a time (Dj: no parallel agents)

| # | Lens | Finding | Verdict | Route | Evidence / action |
|---|---|---|---|---|---|
| 1 | BH, EC, IA | Re-check ran once before all writes; the retry re-upserted, so a validate delete could be undone | high | patch | Departed from the frozen "just before writing a supplier's rows". `replace_all` now takes `still_owed`, called per partition and before the retry; the test lands the invoice after the listing. |
| 2 | BH, EC, IA | Weekly-step failures reported as the run's `DB_OFFLINE`, or escaped `run()` | medium | patch | The step handles its own errors (`reminders_failed code=…`); `run()` returns the overdue code. |
| 3 | BH | Multi-chunk partition deleted before upserting | low | patch | Upserts first, stale deletes last. |
| 4 | BH | `role="status"` mounted already filled | medium | patch | The status line is always rendered and filled when reminders arrive. |
| 5 | VG | Rejected-invoice rule of the re-check unpinned | low | patch | Assertion added to the job test. |
| 6 | BH, VG | Listing failure path untested | low | patch | The fake can fail its listing; asserted. |
| 7 | BH | `replace_all` docstring wrong about its return | low | patch | Corrected. |
| 8 | — | Lint: blind `except Exception` without a reason (found in the full run) | low | patch | `# noqa: BLE001` with its reason, as in the sweeper. |
| 9 | BH | No alert when a week's reminders fail | low | defer | Same as 4.2's deferred failed-run alert. |
| 10 | VG | 512-unit key limit untested | low | defer | The fake has no length rule; PO numbers are short. |
| 11 | VG | Malformed `/api/reminders` body untested on the web | low | defer | The server shape is pinned by the API test. |
| 12 | BH | Table roles for supplier-api and pipeline | false | reject | Both hold Storage Table Data Contributor on the account (`infra/modules/env-app/main.tf`). |
| 13 | BH, EC | `poLabel` mangles "POL-…" | false | reject | Identical to the staff app's existing formatter; not this change. |
| 14 | BH, EC | Banner stale after an upload in the same visit; no length cap; no lock between weekly runs; e2e marker; Cache-Control; no email assertion | low | reject | The AC says "next opens the link"; runs are 3 h apart; `/api/link` uses the same headers; no email code exists. |

## Design Notes

The week is keyed on the ISO week's Monday (Singapore date) in the existing `job_run`, so no migration is needed. The step reads the list the day's run just made instead of re-reading purchasing, so the reminders and the Overdue POs page always agree.

## Verification

**Commands:**
- `cd backend && uv run pytest tests/apps -q -k "4_3 or 4_2 or supplier or function_apps"` -- expected: pass (Docker Postgres)
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run lint-imports` -- expected: clean
- `cd web/supplier && npm run lint && npx tsc --noEmit && npx vitest run` -- expected: pass
- `ci/checks.sh test` -- expected: ≤ 200 cases; supplier JS budget passes
