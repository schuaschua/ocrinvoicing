---
title: 'Story 4.5: Delivery dates on the supplier page (could-have)'
type: 'feature'
ticket: '4-5-delivery-dates-on-the-supplier-page-could-have'
created: '2026-10-01'
status: 'built'
route: 'full'
route_source: 'auto'
review: 'thorough'
review_source: 'auto'
lenses_ran: ['blind-hunter', 'edge-case-hunter', 'verification-gap', 'intent-alignment']
review_loop_iteration: 0
baseline_revision: '9a3f534a57a7a818fa664e35d53468aa4dbc98e7'
context:
  - '{project-root}/docs/standards/coding-style.md'
  - '{project-root}/docs/standards/security.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Procurement can't see where a supplier's delays come from: the PO's promised date, the delivery date, and the date the goods were received (CAP-19, FR19, could-have).

**Approach:**
- The supplier page from Story 4.4 gets a Deliveries tab next to Scorecard.
- staff-api serves that supplier's deliveries from the purchasing port. Each delivery shows its promised, delivered and received dates and the gaps between them in days.
- The gaps are computed in the domain, never in the browser.

## Boundaries & Constraints

**Always:**
- **Data source.** Purchasing data is reached only through `PurchasingPort` (AD-10).
  - Add one port method, `supplier_delivery_dates(supplier_id, since)`. It returns each delivery of the supplier's POs dated `since` or later, newest first, then by PO number and delivery number, with the same three dates as `get_delivery_dates`.
  - Implement it in the sim adapter, reusing `_delivery_dates`' promised-date rule.
  - Promised is the earliest `expected_date` of the lines that delivery received; while the delivery has no receipt, it is the earliest of all the PO's lines.
  - "Delivery date on the invoice" is purchasing's `delivery_date` for that delivery: the date the delivery that the invoice is scanned against happened (`DeliveryDates.delivered_date`).
- **Gaps.** A pure domain function computes them in days:
  - `delivered − promised`: positive means late;
  - `received − delivered`;
  - `received − promised`.
  - A gap is null when a date is missing.
- **`GET api/suppliers/{supplier_id}/deliveries`:**
  - Covers the last 365 days (Singapore date via `domain/dates.py`), at most 200 rows.
  - Returns `{items: [{po_number, delivery_no, promised_date, delivered_date, received_date, days_late, days_to_receive, days_overall}], truncated}`.
  - Uses `Surface.SUPPLIER_SCORECARD`: 401 when signed out, 404 for other roles, and 404 for an unknown or malformed supplier id (checked against `master.supplier`).
- **Web.**
  - A second tab, "Deliveries", in 4.4's tablist with real tab switching. Arrow keys move between tabs, and the selected tab is reflected in the URL: `/suppliers/{id}?tab=deliveries`.
  - A table with the PO label, delivery number, the three dates, and the three gaps. Positive late days are worded as "{n} days late", 0 as "On time", negative as "{n} days early", and null as "—".
  - An empty state, "No deliveries in the last 12 months.", and the "could-have" text is not shown to users.
  - Strings live in `strings.ts`, and snake_case is mapped in `api/`.
- **Tests:** at most **3** new test cases.

**Never:**
- invoice-table reads for this tab;
- scorecard numbers (Story 5.5);
- writes of any kind;
- a new database grant (staff-api already reads `sim_purchasing` and `master`);
- touching Azure.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Late, received | promised 1 Sep, delivered 4 Sep, received 5 Sep | `days_late` 3, `days_to_receive` 1, `days_overall` 4 | — |
| Early | promised 10 Sep, delivered 8 Sep | `days_late` −2 ("2 days early") | — |
| Not received | No goods receipt | `received_date` null, `days_to_receive` and `days_overall` null | — |
| Partial receipt | Delivery received only line 2 (expected later than line 1) | Promised = line 2's expected date | — |
| Window | Delivery older than 365 days | Not listed | — |
| Cap | More than 200 deliveries | First 200, `truncated` true | — |
| No deliveries | Supplier with none | Empty items; UI empty state | — |
| Unknown supplier | Random id | 404 | Before purchasing is read |
| Wrong role | admin, goods_in | 404 | Before anything is read |
| Tab switch | Click or arrow to Deliveries | URL `?tab=deliveries`; table loads; back to Scorecard keeps the shell | — |

</frozen-after-approval>

## Code Map

- `backend/src/invoicing/ports/purchasing.py`: `DeliveryDates`, `get_delivery_dates`. Add `SupplierDelivery` (`po_number`, `delivery_no`, plus `DeliveryDates`) and `supplier_delivery_dates`.
- `backend/src/invoicing/adapters/purchasing_sim/adapter.py`: `_delivery_dates`. Its promised-date subqueries are `po_earliest` and `received_earliest`. Generalise by joining `purchase_order` on `supplier_id` with `delivery_date >= since`, `LIMIT 201` to detect truncation. Update the fake or contract in `backend/tests/contracts/purchasing_contract.py` if it lists the port's methods.
- `backend/src/invoicing/domain/dates.py`: `singapore_date`. The new pure gap function goes in `domain/deliveries.py`.
- `backend/src/invoicing/apps/staff_api/suppliers.py` (Story 4.4): add the deliveries endpoint to the same factory, and wire it in `function_app.py` before the SPA catch-all. `purchasing_port(settings.purchasing_adapter, engine)` is already built there for goods-in.
- `web/staff/src/screens/SupplierScreen.tsx` and `api/suppliers.ts` (Story 4.4): the tablist and the API module. Use `lib/format.ts` and the `poLabel` in `strings.ts`.
- Test patterns: `backend/tests/apps/test_story_4_4_suppliers_api.py` and `test_story_2_4_purchasing_adapter.py` (sim seed with deliveries and receipts); `web/staff/src/screens/SuppliersScreen.test.tsx`.

## Tasks & Acceptance

**Execution:**
- [x] `ports/purchasing.py`, `adapters/purchasing_sim/adapter.py`: `supplier_delivery_dates`.
- [x] `domain/deliveries.py`: the gap function.
- [x] `apps/staff_api/suppliers.py`, `function_app.py`: the deliveries route.
- [x] `web/staff/src/api/suppliers.ts`, `screens/SupplierScreen.tsx`, `strings.ts`: the Deliveries tab with tab switching.
- [x] Tests (at most 3 new cases):
  - `test_story_4_5_gaps`, a pure, parametrised-free domain test covering the matrix gap rows;
  - `test_story_4_5_deliveries_api`, covering the adapter against the seed, the window, the cap, 404s and roles;
  - one web case for the tab switch, the table wording and the empty state.

**Acceptance Criteria:**
- Given the backlog, when Story 4.5 is listed, then it stays marked could-have (no change to `epics.md` needed).

## Implementation Notes

- The port keeps the plan's `supplier_delivery_dates(supplier_id, since)` signature; the 200 cap is `SUPPLIER_DELIVERIES_MAX` in `ports/purchasing.py`, and the adapter returns at most cap + 1 rows (`LIMIT 201`) so the endpoint can set `truncated`.
- `_delivery_dates` and the new query share one select (`_DELIVERY_DATES`) with the promised-date rule as correlated subqueries, so the two can't drift.
- `suppliers_endpoints` now takes the purchasing port and an optional `clock` and returns three endpoints; the 4.4 test was updated to match.
- Web wording: `days_late` and `days_overall` read "{n} day(s) late" / "On time" / "{n} day(s) early" (singular for 1); `days_to_receive` reads "{n} day(s)"; null is "—". When `truncated`, the tab shows "Showing the newest 200 deliveries." Tab switches use `replaceState` (via `navigate(..., {replace: true})`), so Back doesn't step through tabs.

## Plan Change Log

## Review Triage Log

### Pass 1 (2026-10-01): high 0, medium 2, low 9, false/rejected 9; lenses run one at a time

| # | Lens | Finding | Verdict | Route | Evidence / action |
|---|---|---|---|---|---|
| 1 | BH, EC | Window spanned 366 days | low | patch | `today − (365 − 1)`; boundary test adjusted. |
| 2 | VG | Singapore date never pinned (UTC would pass) | medium | patch | Test-owned delivery on the UTC `since` day asserted excluded. |
| 3 | VG, BH | Truncated notice and error/retry untested | medium | patch | Added to the existing 4.5 web case. |
| 4 | EC | Deliveries 404 showed a retry that can't succeed | low | patch | Not-found state, no retry. |
| 5 | BH, EC | Dangling `aria-controls` on the unselected tab | low | patch | Only on the selected tab. |
| 6 | BH, EC | `truncated` parsed loosely | low | patch | Must be a boolean. |
| 7 | BH | Cap test didn't pin which 200 | low | patch | The 200th row asserted. |
| 8 | BH, VG | Contract test lacks the new port method | low | defer | Only the sim exists; add with the real adapter. |
| 9 | VG | Same-day ordering untested | low | defer | Add a same-day pair to the cap fixture later. |
| 10 | BH | Loading not announced to screen readers | low | defer | With 4.4's live-region item. |
| 11 | BH, EC | Future-dated deliveries included | low | reject | The plan says "dated `since` or later". |
| 12 | EC, BH | Panel stays loading on 401 or DB_OFFLINE | false | reject | The shell's session dialog or offline page takes over, as on every screen. |
| 13 | EC | Tab change drops other query params; back/forward | low | reject | No other params exist; replace navigation is intended. |
| 14 | BH | Negative days-to-receive wording | low | reject | Only on a data error in purchasing. |
| 15 | BH | No index for the query | low | reject | Seed-sized sim. |
| 16 | BH | Line too long | false | reject | `ruff check` passes. |
| 17 | BH | Raw ISO dates | false | reject | Staff screens show YYYY-MM-DD (coding-style.md rule 5). |
| 18 | BH | 4.4 test builds an unused purchasing port | low | reject | Required by the shared factory. |
| 19 | IA | No per-supplier delay summary; "delivery date on the invoice" | false | reject | The intent asks for per-delivery rows; the date source is the plan's documented choice (raised with Dj). |

## Verification

**Commands:**
- `cd backend && uv run pytest tests -q -k "4_5 or 4_4 or 2_4 or function_apps or contract"`: should pass (Docker Postgres).
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run lint-imports`: should be clean.
- `cd web/staff && npm run lint && npx tsc --noEmit && npx vitest run`: should pass.
- `ci/checks.sh test`: should stay at or under 200 cases.
