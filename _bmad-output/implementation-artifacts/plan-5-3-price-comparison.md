---
title: 'Story 5.3: Price comparison with price-rise alerts'
type: 'feature'
ticket: '5-3-price-comparison-with-price-rise-alerts'
created: '2026-10-01'
status: 'built'
route: 'full'
route_source: 'auto'
review: 'thorough'
review_source: 'auto'
lenses_ran: ['blind-hunter', 'edge-case-hunter', 'verification-gap', 'intent-alignment']
review_loop_iteration: 0
baseline_revision: 'a0fbd16ec7acd1e0a9734ad3d3ee5d582c02cb7c'
context:
  - '{project-root}/docs/standards/coding-style.md'
  - '{project-root}/docs/standards/security.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Procurement can't compare suppliers' prices for a material, and nobody learns when a supplier raises prices (CAP-14, FR14).

**Approach:**
- The analytics refresh (Story 5.1) gets the AD-20 price-rise rule. Each posted unit price more than 2% above the same supplier's previous posted price for that material raises one `analytics.alert` (kind `price_rise`) with its evidence.
- staff-api serves Price comparison for a material from `analytics.*` only: each supplier's latest unit price and on-time rate, a price history for the chart, and the material's price-rise alerts.
- `web/staff` gets the Price comparison surface and a reusable, accessible Chart component.
- Emails are Story 5.2's job, which sends any alert whose `emailed_at` is empty.

## Boundaries & Constraints

**Always:**
- **Price-rise rule (AD-20).**
  - For each supplier and material, order the posted price points by `invoice_date`, then `invoice_id` (then `line_no`).
  - A point is a rise when its `unit_price` exceeds the previous point's by more than 2%: `(new − prev) / prev > 0.02`, in `Decimal`, where `prev > 0`.
  - Each rise is one alert, with `dedupe_key = price_rise:{invoice_id}:{line_no}`, inserted with ON CONFLICT DO NOTHING. A rerun never duplicates an alert, and a reprocessed invoice whose price is unchanged keeps its alert.
  - `detail` holds `{supplier_id, material_id, pct (2 decimals), previous: {invoice_id, invoice_date, unit_price}, current: {…}}`.
  - Evaluate it inside the 5.1 summary step's transaction, after the price points are written.
  - Alerts are never deleted or updated here (5.2 sets `emailed_at`).
- **Material names.** They are kept in `analytics.material(material_id PK, name)`, refreshed by the job through a new `PurchasingPort.material_names(ids)` (AD-10) for the materials that have price points. Dashboards never read purchasing.
- **`GET api/materials`.** Returns the materials that have posted prices, `{items: [{material_id, name}]}`, sorted by name.
- **`GET api/price-comparison?material_id=`.** Returns `{material_id, name, suppliers: [{supplier_id, supplier_name, latest_unit_price, latest_invoice_date, on_time_rate|null}], history: [{supplier_id, invoice_date, unit_price}] (last 365 days), alerts: [{alert_id, created_at, supplier_id, supplier_name, pct, evidence: [{invoice_id|null, invoice_date, unit_price}]}]}`.
  - Suppliers are sorted by latest price, then by on-time rate descending.
  - Money is a string with 2 decimals, and rates are 4-decimal strings.
  - Read through `ports/dashboards.py`; supplier names come from the master directory.
  - `Surface.PRICE_COMPARISON` (procurement, finance): 401 when signed out, 403 for other roles. An unknown or malformed `material_id` gives 404.
  - Evidence `invoice_id`s are sent only to admin and finance; for others they are null, so rows are read-only (EXPERIENCE.md Evidence list). Only admin and finance can open an invoice anyway.
- **Web.**
  - The Price comparison page has a material picker (Select) and a summary sentence above the chart, for example "EVA soles: lowest latest price S$4.20 from Kowloon Soles."
  - **Chart:** a line chart of price history per supplier, plus a **View as table** toggle. Series are told apart by label and marker shape, not colour alone (UX-DR18, WCAG 1.1.1 and 1.4.1). It uses design tokens only.
  - **Supplier table:** latest price and on-time rate.
  - **Alerts list:** "Price rise: {supplier}, {material} +{n}%", each with its evidence rows. Rows link to `/invoices/{id}` for admin and finance and are plain text otherwise.
  - When there are no materials or no price points, the page shows "No posted invoices yet for this period."
- **Chart component.** `components/Chart.tsx` is reusable by 5.5 and 5.6. It is inline SVG, with no new npm dependency. It takes `{title, summary, series: [{label, points: [{x, y}]}], format}`, and its table view lists every point.
- **Tests.** At most **3** new test cases. The existing axe screens get a Price comparison screen with no new case if that fits, otherwise one case.

**Never:**
- sending email (5.2);
- watchlist rules (5.4);
- dashboards reading invoice tables or `sim_purchasing`;
- a new charting library;
- touching Azure.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Rise | Supplier A material M: 4.00 then 4.10 (+2.5%) | 1 alert, pct 2.50 | — |
| Not a rise | 4.00 then 4.08 (+2.0% exactly) | No alert | — |
| Same date | Two invoices on one date | Ordered by `invoice_id` | — |
| Rerun | Refresh runs again | No duplicate alert | ON CONFLICT |
| First price | Only one point | No alert | — |
| Comparison | M with suppliers A (4.10, 0.80) and B (3.90, null) | B first, then A; rates as given | — |
| Evidence roles | procurement vs finance | `invoice_id` null for procurement; set for finance | — |
| Empty | No price points | "No posted invoices yet for this period." | — |
| Bad material | Unknown id | 404 | — |
| Wrong role | management | 403 | Before reads |
| Chart a11y | Toggle | Table lists every point; series have text labels and distinct markers | — |

</frozen-after-approval>

## Code Map

- **Story 5.1 (built just before):** `apps/pipeline/analytics_refresh.py` (summary step), `adapters/postgres/analytics*.py` (`price_point`, `supplier_on_time`, `alert` and its `dedupe_key`), `ports/dashboards.py` / `adapters/postgres/dashboards.py` (add methods here), and `domain/analytics.py` (add the pure price-rise function).
- **Migration:** `0012_price_comparison` for `analytics.material` (pipeline SELECT, INSERT, DELETE; staff-api SELECT), following `0011`.
- **Purchasing:** `ports/purchasing.py` and `adapters/purchasing_sim/adapter.py` (the `material` table) get `material_names(ids)`.
- **staff-api:** endpoint pattern in `apps/staff_api/suppliers.py` and `invoices.py`. The supplier names come from `PostgresSupplierDirectory.names`. `Surface.PRICE_COMPARISON` already exists in `domain/roles.py`. Wire it in `function_app.py`.
- **web/staff:** `App.tsx` swaps the `price_comparison` placeholder; `surfaces.ts` already has the route. Also `strings.ts`, `api/`, `components/ui/` (`select` if present), `lib/format.ts`, and `index.css` tokens.
- **Accessibility:** `web/staff/e2e/` screens for the axe check (see how other screens register).
- **Tests:** backend `tests/apps/test_story_5_1_*`; web `screens/*.test.tsx`.

## Tasks & Acceptance

**Execution:**
- [x] `domain/analytics.py` gains `price_rises(points)`, a pure function; the summary step stores alerts and refreshes material names.
- [x] `0012_price_comparison` migration and `schema.py`.
- [x] `PurchasingPort.material_names` and its sim implementation.
- [x] `ports/dashboards.py` / the adapter get the comparison reads; `apps/staff_api/price_comparison.py` and `function_app.py`.
- [x] `web/staff/src/components/Chart.tsx`, `api/priceComparison.ts`, `screens/PriceComparisonScreen.tsx`, `strings.ts`, `App.tsx`, and the e2e axe screen.
- [x] Tests (at most 3 new cases):
  - `test_story_5_3_price_rises`, a domain test covering the threshold, the order and the first price;
  - `test_story_5_3_price_comparison`, covering the job storing alerts with no duplicates, the API order, evidence by role, 404, 403 and empty;
  - one web case covering the chart summary, the table toggle, markers and labels, the alerts and the empty state.

**Acceptance Criteria:**
- Given the chart, when shown, then a one-sentence summary sits above it and the table view lists every plotted value.

## Implementation Notes

- **Alerts.** `write_summaries` calls `_price_rise_alerts` right after `_posted`, in the same transaction. It reads every `analytics.price_point`, runs `domain.analytics.price_rises` and inserts with `ON CONFLICT (dedupe_key) DO NOTHING`, using a uuid7 `alert_id` and the server default for `created_at`. `detail` values are JSON strings (`pct` "2.50", prices "4.10", ISO dates).
- **Material names.** These are not written inside the summary transaction, because purchasing is read before a writing transaction (AD-10) and new materials only appear once that transaction has written their points. Instead, `AnalyticsRefresh._material_names` runs at every run whose summary step got through, whether it wrote now or earlier that day. It calls `store.priced_materials()`, then `purchasing.material_names(ids)`, then `store.replace_materials(names)`. A failure logs `analytics_refresh.materials_failed` and the next run retries. Materials purchasing doesn't know get no row, so they aren't listed and their comparison returns 404.
- **API.** `DashboardReader` gains `materials()` and `price_comparison(material_id)`, each read in one REPEATABLE READ, read-only snapshot. The endpoint picks each supplier's latest point and keeps the history from today minus 364 days (Singapore date, injected clock), the same window as lateness. Ties on latest price and rate are broken by supplier name, then id. A missing `material_id` returns 404, like an unknown or malformed one.
- **Web.** No `select` exists in `components/ui`, so the picker is a native `<select>` styled like InvoicesScreen's. Chart `points.y` is a number used only to position marks. The table and the axis text format it back to 2 decimals, which round-trips the server's strings. Series colours come from token CSS variables. The eslint colour rule forbids literal `fill`/`stroke` values, so fixed fills use the `fill-background` and `stroke-border` classes. Each series also gets its own marker shape (circle, square, triangle, …) and dash pattern.
- **Tests.** There are 3 new cases plus 1 new axe screen (the plan allows one), for 177 of 200 in total. Existing cases were extended with no new case: the 5.1 test now expects only `price_rise` alerts (its data contains rises), the migration test covers `analytics.material` grants, and the purchasing contract covers `material_names`.

## Plan Change Log

## Review Triage Log

### Pass 1 (2026-10-01): high 1, medium 4, low 11, false/rejected 6; lenses run one at a time

| # | Lens | Finding | Verdict | Route | Evidence / action |
|---|---|---|---|---|---|
| 1 | BH, EC, IA | First run queues every historical rise for email | high | patch | History rises stored with `emailed_at` set and `backfilled: true`; only rises posted in the run's window wait for 5.2. Tested. |
| 2 | BH | Material not in the URL; 5.2's email must deep-link (EXPERIENCE.md) | medium | patch | `?material_id=` read and replaced. Tested. |
| 3 | BH | Chart x axis by index distorts trends | medium | patch | Time-proportional for dates. Tested. |
| 4 | BH, IA | Suppliers ranked by latest-ever price, outside the chart window | medium | patch | Only suppliers with a point in the window, at their window-latest price. |
| 5 | VG | Material-name failure path and same-day retry untested | medium | patch | Added to the integration test. |
| 6 | BH, EC | Two lines of one invoice compared as a rise | low | patch | Compared only with the previous invoice's last point. |
| 7 | BH, EC | Unnamed material vanishes and 404s | low | patch | Fallback name; `materials_unnamed` logged. |
| 8 | BH, EC | Retry stuck on a removed material; contradictory empty text | low | patch | `chosen` reset; "No prices in the last 12 months for this material." |
| 9 | BH | Range lines unlabelled; destructive and muted used as series colours | low | patch | Labelled; neutral tokens. |
| 10 | VG | No-rate tie order, history boundary, material switch untested | low | patch | All asserted in existing cases. |
| 11 | BH | 5.1 test comment contradicts its assertion; a 3-decimal price in the domain test | low | patch | Fixed. |
| 12 | IA | Axe never checks the chart's table view | low | defer | Needs an extra Playwright case under the cap. |
| 13 | BH | Alerts list unbounded | low | defer | Bound when alerts grow (5.4/5.2). |
| 14 | VG | "Newest first" order of alerts untested | low | defer | 5.4 creates more alerts. |
| 15 | BH, EC | Stale evidence after a back-dated or corrected invoice | low | reject | Alerts are immutable records of the rise as found; AD-20 order. |
| 16 | BH | Full `price_point` scan each run | low | reject | PoC volume. |
| 17 | BH, EC | Series styles repeat beyond 12 suppliers; id-suffix labels | low | reject | Text labels and the table view still distinguish them. |
| 18 | EC | Rise after a 0.00 price never alerted | false | reject | Price points require `unit_price > 0` (Story 5.1). |
| 19 | EC, IA | Supplier names read from master, not analytics | false | reject | The plan names the master directory for names. |
| 20 | IA | Extra scope: `analytics.material`, `api/materials` | false | reject | Both are in the plan. |

## Verification

**Commands:**
- `cd backend && uv run pytest tests -q -k "5_3 or 5_1 or migrations or contract"`: should pass.
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run lint-imports`: should be clean.
- `cd web/staff && npm run lint && npx tsc --noEmit && npx vitest run`: should pass.
- `ci/checks.sh test`: should stay at or under 200 cases, with the axe checks green.
