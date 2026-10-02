---
title: 'Story 5.6: Finance month view'
type: 'feature'
ticket: '5-6-finance-month-view'
created: '2026-10-01'
status: 'built'
route: 'full'
route_source: 'auto'
review: 'thorough'
review_source: 'auto'
lenses_ran: ['blind-hunter', 'edge-case-hunter', 'verification-gap', 'intent-alignment']
review_loop_iteration: 0
baseline_revision: '40d72f21564a2b7ebab102bc156717c8cbe6e171'
context:
  - '{project-root}/docs/standards/coding-style.md'
  - '{project-root}/docs/standards/security.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** At month end, finance re-keys supplier figures by hand: spend, price creep, flagged and duplicate invoices. Nobody sees whether the system meets its 90% straight-through target (CAP-18, FR18, NFR19).

**Approach:**
- staff-api serves a month view from `analytics.*`:
  - per supplier: spend, the price-rise alerts in that month, flagged count and duplicate count;
  - in the header: that month's straight-through share against the 90% target, read from Story 5.1's `month_summary`.
- `web/staff` gets the Finance month surface. It is the landing page for finance.

## Boundaries & Constraints

**Always:**
- **`GET api/finance-month?month=YYYY-MM`.** When `month` is missing, use the latest month that has data; otherwise use the current Singapore month.
  - **Response:** `{month, months: [YYYY-MM…] (newest first, months with any data), straight_through: {share|null, posted_count, straight_through_count, target: "0.9000"}, suppliers: [{supplier_id, supplier_name, spend, posted_count, price_rises, flagged_count, duplicate_count}]}`.
  - **Sources (Story 5.1 rules):**
    - Spend and posted count: `supplier_month`, by posted month.
    - Flags: `supplier_month_flags`, by received month.
    - Price rises: count the `price_rise` alerts whose current invoice date (`detail.current.invoice_date`) falls in the month.
    - The straight-through share: `month_summary`.
  - A supplier appears if it has any of these in the month.
  - **Sort:** by spend descending, then name.
  - **Formats:** money is a 2-decimal string; rates are 4-decimal strings.
  - **Access:** read through `ports/dashboards.py` only. `Surface.FINANCE_MONTH` (finance, management). Signed out gets 401, other roles 403. A malformed `month` gets 400 `VALIDATION_FAILED`, and the message never echoes the value.
- **Web:**
  - A month picker (Select from `months`, kept in the URL as `?month=`).
  - A header line: "{n}% posted without an admin (target 90%)". It reads as met or not met in words, not colour alone. "No posted invoices yet" when the share is null.
  - A supplier table: spend, price-creep alerts, flagged, duplicates.
  - A Chart (the Story 5.3 Chart pattern) of the monthly straight-through share for the available months, against the 90% target, with a summary sentence and a View as table toggle.
  - When there are no months with data: "No posted invoices yet for this period."
- **Tests:** at most **2** new test cases.

**Never:**
- new analytics tables or job changes;
- invoice-table reads from staff-api;
- CSV export (not asked for);
- touching Azure.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| September | A: spend 120.00, 2 posted, 1 rise, 1 flagged; B: 40.00, 1 duplicate; share 0.6667 of 3 | A then B; header 67% (target 90%, not met) | — |
| Flags only | C has only a flagged, unposted invoice | C listed with spend 0.00 | — |
| Default month | No `month` | Latest month with data | — |
| Empty month | Month with no data | Empty suppliers; share null | — |
| No data at all | Nothing posted or flagged | "No posted invoices yet for this period." | — |
| Bad month | `2026-13` or `x` | 400 | Not echoed |
| Wrong role | procurement | 403 | Before reads |
| Landing | Finance signs in | Lands on Finance month | — |

</frozen-after-approval>

## Code Map

- `backend/src/invoicing/ports/dashboards.py` and `adapters/postgres/dashboards.py`:
  - `supplier_months` (spend merged with flags) and `month_summaries` already exist (Story 5.1), as does `alerts`.
  - Add `finance_month(month)` and `data_months()` as one snapshot read.
- `backend/src/invoicing/apps/staff_api/price_comparison.py` (Story 5.3) shows the endpoint, formatting and role patterns.
  - The new endpoint goes in `apps/staff_api/finance_month.py`, wired in `function_app.py`.
  - `Surface.FINANCE_MONTH` already exists, and finance's landing page is already `FINANCE_MONTH` in `roles.py`.
- `web/staff`:
  - `App.tsx`: swap the `finance_month` placeholder for the new screen.
  - Reuse `components/Chart.tsx`, `lib/format.ts`, `strings.ts` and the `api/` pattern.
  - `App.test.tsx` checks finance's landing page; extend its mock as was done for suppliers.
- Tests: `backend/tests/apps/test_story_5_1_*`, `test_story_5_3_*` fixtures.

## Tasks & Acceptance

**Execution:**
- [x] Dashboards: `finance_month` and `data_months`.
- [x] `apps/staff_api/finance_month.py` and `function_app.py`.
- [x] `web/staff`: `api/financeMonth.ts`, `screens/FinanceMonthScreen.tsx`, `strings.ts`, `App.tsx`.
- [x] Tests (at most 2 new cases):
  - `test_story_5_6_finance_month_api`: September, flags only, default month, empty month, no data, bad month, role;
  - one web case: header wording against the target, the table, the month switch updating the URL, the chart summary and table, and the empty state.

## Implementation Notes

- `data_months()` is folded into `DashboardReader.finance_month(month, current)`: one REPEATABLE READ snapshot returns the shown month, the months with data (union of `supplier_month`, `supplier_month_flags`, `month_summary` and the price-rise alerts' invoice-date months), the supplier rows, the rises per supplier, the month's summary and every month's summary.
- The response carries one field beyond the frozen shape: `history: [{month, share}]` (oldest first), every month's straight-through share from `month_summary`. The web Chart of the monthly share needs it, and fetching each month separately would cost one request per month.
- A supplier with only a price rise in the month (no spend or flags) is listed at 0.00 with zero counts.
- Web: a malformed `?month=` in the URL (400 `VALIDATION_FAILED`) falls back to the latest month and clears the parameter. The header percentage is whole (0.6667 reads 67%), but never reads as the target while below it (0.8950 reads 89.5%, not 90%). The met/not-met wording compares the server's share and target strings; no figure is computed.

## Plan Change Log

## Review Triage Log

### Pass 1 (2026-10-01): high 0, medium 4, low 11, false/rejected 6; lenses run one at a time

| # | Lens | Finding | Verdict | Route | Evidence / action |
|---|---|---|---|---|---|
| 1 | BH, EC | `9999-12` overflows the next-month date, giving 500 | medium | patch | Years 2000–2100 only; month arithmetic; tested. |
| 2 | BH, EC | One malformed alert date fails every request | medium | patch | SQL pattern guard; unparsable rows skipped; tested. |
| 3 | EC | Near-target share shows "90%" next to "Target not met" (header and chart table) | medium | patch | One `shareText` guard everywhere; tested at 0.8960. |
| 4 | VG | Rise-only month and rise-only supplier never exercised | medium | patch | June case asserted. |
| 5 | BH | A mistyped future invoice date can become the default month | low | patch | Months and default capped at the current Singapore month. |
| 6 | BH | `history` unbounded | low | patch | Last 24 months ending at the shown month. |
| 7 | BH | Positional zero row; unnamed suppliers sort first | low | patch | Keyword arguments; unnamed last. |
| 8 | VG | Equal-spend name order, URL start month, bad-month fallback untested | low | patch | All added to the existing cases. |
| 9 | EC | Month reset drops other query params | low | patch | Only `month` is set or deleted. |
| 10 | BH | Rows don't link to the supplier page | low | patch | Links to `/suppliers/{id}`. |
| 11 | BH, IA | Three month bases unexplained on screen | low | patch | One-line note under the table. |
| 12 | BH | Header 67% vs chart table 66.7% | low | patch | Same formatter (whole percent with the guard). |
| 13 | IA | No export: finance may still re-key from the screen | low | reject | Not in the story's ACs; raised with Dj as a possible follow-up. |
| 14 | BH | No totals row | low | reject | Not in the ACs. |
| 15 | BH | No index on the JSONB rise date | low | reject | PoC volume. |
| 16 | EC | Skeleton stays on 401 or DB_OFFLINE | false | reject | The shell's session dialog or offline page takes over. |
| 17 | EC | Plan names a `data_months` method | false | reject | Folded into the one snapshot read; recorded in Implementation Notes. |
| 18 | BH | No Jira record in the diff | false | reject | Synced by the orchestrator. |

## Verification

**Commands:**
- `cd backend && uv run pytest tests -q -k "5_6 or 5_1 or 5_3"`: should pass.
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run lint-imports`: should be clean.
- `cd web/staff && npm run lint && npx tsc --noEmit && npx vitest run`: should pass.
- `ci/checks.sh test`: at most 200 cases.
