---
title: 'Story 5.5: Supplier scorecard'
type: 'feature'
ticket: '5-5-supplier-scorecard'
created: '2026-10-01'
status: 'built'
route: 'full'
route_source: 'auto'
review: 'thorough'
review_source: 'auto'
lenses_ran: ['blind-hunter', 'edge-case-hunter', 'verification-gap', 'intent-alignment']
review_loop_iteration: 0
baseline_revision: '16e370eebddfa6cbd2d45eff2562136dec22364d'
context:
  - '{project-root}/docs/standards/coding-style.md'
  - '{project-root}/docs/standards/security.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** On a supplier's page, procurement has no evidence for an order decision: how reliably the supplier delivers, and where its prices are heading (CAP-17, FR17).

**Approach:**
- The Scorecard tab on the Story 4.4 supplier page replaces its "coming" note. It shows the supplier's on-time rate (AD-20: on-time receipt lines divided by all receipt lines, last 365 days) and a price trend per material from posted invoices.
- staff-api reads both from `analytics.*` through the dashboard repository.
- Each material's trend uses the Story 5.3 Chart pattern.

## Boundaries & Constraints

**Always:**
- **`GET api/suppliers/{supplier_id}/scorecard`:**
  - Returns `{on_time: {rate, receipts, on_time, avg_days_late} | null, materials: [{material_id, name, change_pct|null, latest_unit_price, points: [{invoice_date, unit_price}]}]}`.
  - Points cover the last 365 days, today included (Singapore date), oldest first.
  - `change_pct` is `(latest − first) / first × 100` within the window, to 2 decimals, and null when there is a single point.
  - Materials are sorted by name.
  - Money is a 2-decimal string. The rate is a 4-decimal string and `avg_days_late` a 2-decimal string.
  - Read through `ports/dashboards.py` only. Material names come from `analytics.material` (Story 5.3).
  - Access is `Surface.SUPPLIER_SCORECARD`. Signed out gets 401. Other roles, and unknown or malformed ids, get 404 (as for 4.4's detail).
- **Web:**
  - **On-time card:** "On time {n}% of {receipts} receipts in the last 12 months" and "On average {d} days late" (or "early"). With no receipts, it shows "No goods received in the last 12 months."
  - **Price trend:** one Chart per material (title = material name). Summary sentences:
    - "{material} up {n}% since {Mon YYYY}"
    - "… down {n}% …"
    - "… unchanged …"
    - "One price so far: S${p}"
  - Every chart has the View as table toggle. Series are told apart by label and marker.
  - With no price points and no receipts, the tab shows "No posted invoices yet for this period."
  - The tab keeps its place in the URL (`?tab=scorecard` is the default, from Story 4.5).
- **Tests:** at most **2** new test cases.

**Never:**
- new analytics tables or job changes (5.1 and 5.3 provide the data);
- reading the invoice or purchasing tables from staff-api;
- touching Azure.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Full | 4 of 5 receipt lines on time; material M 4.00 → 4.24 in the window | rate 0.8000; M `change_pct` 6.00; summary "M up 6% since …" | — |
| One price | Single point | `change_pct` null; "One price so far: S$4.00" | — |
| Old prices only | Points older than 365 days | Material not listed | — |
| No receipts | Supplier has no lateness rows | `on_time` null; the no-receipts line | — |
| Empty | Neither | "No posted invoices yet for this period." | — |
| Unknown supplier | Random id | 404 | Before analytics reads |
| Wrong role | admin | 404 | Before reads |

</frozen-after-approval>

## Code Map

- `backend/src/invoicing/ports/dashboards.py` and `adapters/postgres/dashboards.py` (Stories 5.1 and 5.3): add `scorecard(supplier_id, since)` as one snapshot over `supplier_on_time`, `price_point` and `material`.
- `backend/src/invoicing/apps/staff_api/suppliers.py` (Stories 4.4 and 4.5): add the scorecard endpoint to the same factory, alongside the deliveries one, with the same 404-before-read rule. Add a pure `change_pct` to `domain/analytics.py`.
- `web/staff/src/screens/SupplierScreen.tsx` (4.4 and 4.5 tabs): replace the Scorecard "coming" panel. Use `components/Chart.tsx` (5.3) and `lib/format.ts` (`priceText`, `percentText` and `rateText` from 5.3). `api/suppliers.ts` gets `getSupplierScorecard`. Add the copy to `strings.ts`.
- Tests: the backend pattern is `tests/apps/test_story_4_5_deliveries_api.py` with the 5.1/5.3 fixtures; the web pattern is `screens/SuppliersScreen.test.tsx`.

## Tasks & Acceptance

**Execution:**
- [x] Dashboards: the scorecard read.
- [x] `domain/analytics.py`: `change_pct`.
- [x] `apps/staff_api/suppliers.py` and `function_app.py`: the scorecard route.
- [x] `web/staff`: the Scorecard panel, the API call and the strings.
- [x] Tests (at most 2 new cases):
  - `test_story_5_5_scorecard_api` covers the full, one-price, old, no-receipts, empty, 404 and role rows;
  - one web case covers the on-time card, a chart summary and table toggle, and the empty state.

## Implementation Notes

- `suppliers_endpoints` now takes the `DashboardReader` as its third positional argument and returns four endpoints; the 4.4 and 4.5 tests pass it.
- A material whose `analytics.material` row the refresh job hasn't written yet (a naming failure, retried next run) is left out of the scorecard, as Price comparison leaves it out; points dated after today (Singapore) are left out too.
- Materials sort by name in any case, then name, then id.
- The Deliveries and Scorecard panels share one loading hook (`usePanelData`) and one status view (`PanelStatus`); Deliveries behaves as before.
- A zero average reads "On time on average". The rate never shows 100% unless every receipt was on time, nor 0% unless none was (99.9% / 0.1%).
- Receipts but no prices in the window: the price section shows "No posted invoices yet for this period."
- Review fixes: the rate is rounded half-up and `avg_days_late` goes through the 5.4 `_days` helper; a negative zero is sent as 0.00. Same-day points order by `posted_at`, so the later posted is the latest. The price window has its own `SCORECARD_DAYS`.

## Plan Change Log

## Review Triage Log

### Pass 1 (2026-10-01): high 0, medium 3, low 9, false/rejected 6; lenses run one at a time

| # | Lens | Finding | Verdict | Route | Evidence / action |
|---|---|---|---|---|---|
| 1 | BH, VG | 4.4/4.5 web tests' mocks don't answer `/scorecard`; 4.4 asserts only that the panel exists | medium | patch | Both answer it; 4.4 asserts real content. |
| 2 | VG | Unnamed-material exclusion and future-date cut-off untested | medium | patch | Both added to the existing case. |
| 3 | IA | Receipts but no prices showed no empty text (AC) | medium | patch | "No posted invoices yet for this period." in the price section. |
| 4 | BH | Rate rounded half-even; days via money() | low | patch | Half-up; public `days_text` helper. |
| 5 | BH | `-0.00` leaks; "0 days late" wording | low | patch | Normalised; "On time on average". |
| 6 | EC | 100%/0% shown when not exact | low | patch | `onTimeRateText` caps at 99.9% / floors at 0.1%. |
| 7 | EC | Same-day tie picks by UUID | low | patch | Ordered by posted_at; tested. |
| 8 | BH | `DELIVERY_DAYS` reused for prices | low | patch | `SCORECARD_DAYS`. |
| 9 | BH | Malformed dates render blank month | low | patch | Parser validates YYYY-MM-DD. |
| 10 | BH, IA | No "as of" freshness for the on-time rate | low | defer | With 5.1's deferred `as_of` read. |
| 11 | BH | Scorecard error and 404 states untested | low | defer | 200-case cap. |
| 12 | BH, EC | Unbounded price payload | low | reject | 365-day window at PoC volume. |
| 13 | BH, EC, VG | Zero first price gives "one price" or a 500 | false | reject | Price points require `unit_price > 0` (Story 5.1). |
| 14 | BH | Chart repeats the material name | low | reject | Title, legend and table each need a label. |
| 15 | EC | Empty state when all materials are unnamed | low | reject | Transient until the next refresh names them. |
| 16 | BH | No Jira/epics update in the diff | false | reject | Synced by the orchestrator; no story text changed. |

## Verification

**Commands:**
- `cd backend && uv run pytest tests -q -k "5_5 or 4_5 or 4_4 or 5_1"` -- expected: pass
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run lint-imports` -- expected: clean
- `cd web/staff && npm run lint && npx tsc --noEmit && npx vitest run` -- expected: pass
- `ci/checks.sh test` -- expected: ≤ 200 cases
