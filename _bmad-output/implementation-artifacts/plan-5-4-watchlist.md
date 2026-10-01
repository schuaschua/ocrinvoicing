---
title: 'Story 5.4: Supplier watchlist with ranked alternatives'
type: 'feature'
ticket: '5-4-supplier-watchlist-with-ranked-alternatives'
created: '2026-10-01'
status: 'built'
route: 'full'
route_source: 'auto'
review: 'thorough'
review_source: 'auto'
lenses_ran: ['blind-hunter', 'edge-case-hunter', 'verification-gap', 'intent-alignment']
review_loop_iteration: 0
baseline_revision: '8d7344c8f254dab77c975c09acf2e6a69bff8b6e'
context:
  - '{project-root}/docs/standards/coding-style.md'
  - '{project-root}/docs/standards/security.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Management and procurement don't learn which suppliers are getting worse, or who could replace them (CAP-15, CAP-16, FR15, FR16).

**Approach:**
- The analytics refresh adds the three AD-20 watchlist rules after the price-rise step (Story 5.3). It keeps `analytics.watchlist` (one row per supplier and rule, with evidence) and raises one `analytics.alert` (kind `watchlist`) when a supplier is newly added under a rule. Story 5.2 emails it later.
- staff-api serves the Watchlist from `analytics.*`: entries with evidence, plus the ranked alternatives for each material involved.
- `web/staff` gets the Watchlist surface, which is management's landing page.

## Boundaries & Constraints

**Always:**
- **Rules (AD-20).** Each is evaluated on the run date (Singapore time) and recomputed in full each run.
  - **`price_rises`:** 3 or more `price_rise` alerts for the supplier, whose current invoice date is in the last 365 days. The evidence is those rises.
  - **`late`:** `supplier_on_time.avg_days_late >= 7.00` (AD-20 lateness, last 365 days). The evidence is the supplier's late receipt lines, at most 20, the latest first.
  - **`price_gap`:** for some material, the supplier's latest price is at least 5% above the lowest latest price for that material among suppliers who posted it in the last 90 days, using `(latest − lowest) / lowest >= 0.05` in `Decimal`. The supplier must itself have posted that material in the last 90 days. The evidence is the material, both prices, and the cheapest supplier.
- **Storage.** `analytics.watchlist(supplier_id, rule) PK, first_added_on, evidence jsonb`. Each run replaces the rows. `first_added_on` is kept while the pair stays listed, and resets when a pair drops off and later comes back.
- **Alerts.** When a pair is newly listed (absent in the previous run), insert one alert with kind `watchlist`, `dedupe_key = watchlist:{supplier_id}:{rule}:{first_added_on}`, and `detail` `{supplier_id, rule, evidence}`. ON CONFLICT DO NOTHING, so a rerun never duplicates it.
- **Alternatives (CAP-16).** For each material in an entry, the other suppliers with a posted price for it in the last 90 days, ranked by latest price ascending, then on-time rate descending (nulls last), then name. Computed at read time from `price_point` and `supplier_on_time`, which are both `analytics.*`.
- **`GET api/watchlist`.**
  - Returns `{entries: [{supplier_id, supplier_name, rules: [{rule, first_added_on, evidence: [...]}], alternatives: [{material_id, material_name, suppliers: [{supplier_id, supplier_name, latest_unit_price, on_time_rate|null}]}]}]}`, sorted by the most recent `first_added_on`, then by name.
  - Evidence invoice ids are sent only to admin and finance. Watchlist's roles are procurement and management, so they are null for both, and rows are read-only.
  - `Surface.WATCHLIST`: 401 when signed out, 403 for other roles.
  - Money is a 2-decimal string and rates are 4-decimal strings.
- **Web.**
  - The Watchlist page has one card per supplier showing its rules in plain words, for example "3 price rises in the last 12 months", "On average 8 days late" and "EVA soles 6% above the cheapest supplier".
  - Each card has its evidence list and an Alternatives list per material.
  - With no price points at all, the page shows "No posted invoices yet for this period." With price points but no entries, it shows "No suppliers on the watchlist."
- **Rules location.** The rules are pure functions in `domain/analytics.py`.
- **Migration** `0013_watchlist`: the pipeline gets SELECT, INSERT and DELETE; staff-api gets SELECT.
- **Tests.** At most **3** new test cases.

**Never:**
- sending email (Story 5.2);
- manual watchlist edits;
- reading invoice or purchasing tables from staff-api;
- touching Azure.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| 3 rises | 3 rise alerts within 365 days | Listed under `price_rises`; 1 watchlist alert | — |
| 2 rises | 2 within 365, 1 older | Not listed | — |
| Late | `avg_days_late` 7.00 | Listed under `late` | — |
| Not late | 6.99 | Not listed | — |
| Price gap | M: A 4.20, B 4.00 (both within 90 days) | A listed (+5.00%) | — |
| Stale cheap | B's last M price 100 days ago | B not counted as lowest | — |
| Rerun | Same state | No new alert; `first_added_on` unchanged | — |
| Re-listed | A dropped off one run, back later | New `first_added_on`; new alert | — |
| Alternatives | M by A, B, C | B, C ranked by price, then rate | — |
| Empty | No price points | "No posted invoices yet for this period." | — |
| Wrong role | finance | 403 | Before reads |

</frozen-after-approval>

## Code Map

- `backend/src/invoicing/domain/analytics.py` holds the Story 5.1 and 5.3 pure rules (including `price_rises`). Add `watchlist_rules(...)` and `alternatives(...)`.
- `backend/src/invoicing/adapters/postgres/analytics_summaries.py` and `analytics.py` are the summary step (5.1) and the alert insert (5.3, `dedupe_key`). Add the watchlist step in the same transaction, after the price rises.
- `backend/src/invoicing/ports/dashboards.py` and `adapters/postgres/dashboards.py` are the read methods; add the watchlist and alternatives reads.
- `backend/migrations/versions/0012_*` (Story 5.3) is the pattern for `0013_watchlist`.
- `backend/src/invoicing/apps/staff_api/price_comparison.py` (Story 5.3) is the endpoint pattern, the role-gated evidence and the money/rate formatting. Add the new endpoint in `apps/staff_api/watchlist.py` and wire it in `function_app.py`.
- `web/staff/src/screens/PriceComparisonScreen.tsx` (5.3) is the evidence-list pattern. `App.tsx` swaps the `watchlist` placeholder for the new screen. `surfaces.ts` already has the route and management's landing page.
- Tests: `backend/tests/apps/test_story_5_3_*` and `test_story_5_1_*` for fixtures; web tests sit next to the screens.

## Tasks & Acceptance

**Execution:**
- [x] `domain/analytics.py`: the rules and the alternatives ranking.
- [x] `0013_watchlist` migration and `schema.py`.
- [x] Summary step: maintain the watchlist and raise its alerts.
- [x] Dashboards reads and `apps/staff_api/watchlist.py`.
- [x] `web/staff`: `api/watchlist.ts`, `screens/WatchlistScreen.tsx`, `strings.ts`, `App.tsx`.
- [x] Tests, at most 3 new cases:
  - `test_story_5_4_rules`: thresholds, windows and ranking (pure);
  - `test_story_5_4_watchlist`: the job maintains rows and alerts, rerun and re-listed, plus the API order, roles and empty state;
  - one web case: cards, rule wording, alternatives and the empty states.

## Implementation Notes

- **API additions beyond the frozen shape (additive only).** `GET api/watchlist` also returns a top-level `has_price_points` (the page can't otherwise tell its two empty states apart: management has no access to `api/materials`), and each rule carries `avg_days_late` (2-decimal string on `late`, null otherwise) for the "On average N days late" wording. Evidence items carry `material_name` from `analytics.material`.
- **Evidence shapes.** Stored (jsonb list): `price_rises` copies each rise alert's `{material_id, pct, previous, current}`, latest first; `late` is `{receipt_id, material_id, received_date, days_late}`, ≤ 20, latest first; `price_gap` is `{material_id, invoice_id, invoice_date, unit_price, lowest_unit_price, cheapest_supplier_id, pct}`. The API flattens rises to `invoice_*`/`previous_*` fields and adds names; `invoice_id`s are gated on `Surface.INVOICES` roles (always null for procurement/management).
- **Inputs.** `price_rises` reads `analytics.alert` (kind `price_rise`) and filters on the rising invoice's date; `late` reads this run's `supplier_on_time` and `receipt_lateness`, so the watchlist step runs last in `write_summaries` (still after the price rises). `write_summaries` gained a `run_date` argument (the Singapore run date the job already guards on).
- **Alternatives** (`domain.alternatives`) take the material's points of the last 90 days, exclude the listed supplier, rank by latest price, on-time rate (nulls last), name (casefold), id. The materials of an entry are those in its evidence, in order of first appearance (late lines included).
- **No backfill** for watchlist alerts (unlike 5.3's rises): the plan doesn't ask for it, so a first run's listings are alerted and left for Story 5.2 to email.
- **Existing tests touched (no new cases).** `test_story_5_1_incremental_summaries` asserted only `price_rise` alerts exist; its data now also yields a price-gap listing, so it accepts `watchlist` too. `test_migrations` lists `analytics.watchlist` in the grants checks. `e2e/screens.ts`' "sidebar Sheet" screen (at `/watchlist`) gets an `/api/watchlist` stub, since the page now calls it; the populated page was also checked once against the a11y floor at 320px with the Sheet closed (passed, not committed as a case).

## Plan Change Log

## Review Triage Log

### Pass 1 (2026-10-01): high 1, medium 3, low 9, false/rejected 8; lenses run one at a time

| # | Lens | Finding | Verdict | Route | Evidence / action |
|---|---|---|---|---|---|
| 1 | BH, EC, IA | First run alerts the whole existing watchlist for email | high | patch | Backfilled (`emailed_at` set) when no earlier summaries run, as in 5.3; tested. |
| 2 | BH | Alternatives may be watchlisted suppliers, unmarked | medium | patch | `watchlisted` flag and badge. |
| 3 | EC | Late supplier's alternatives limited to the 20 shown materials | medium | patch | Materials from all late lines in the window; tested. |
| 4 | VG | Invoice links never tested for a user who can open invoices | medium | patch | management+finance API and web link asserted. |
| 5 | BH | Days late formatted through money/percent helpers | low | patch | `daysText` and a server days helper. |
| 6 | BH | Null `avg_days_late` blanks the page | low | patch | Accepts null; fallback line. |
| 7 | EC | Unknown rule blanks the page | low | patch | Skipped. |
| 8 | BH | Card anchor claimed for email links but not scrolled | low | patch | Hash scrolls and focuses; tested. |
| 9 | BH | CHECK constraint missing from schema.py | low | patch | Added. |
| 10 | BH | 5.1 test depends on 5.4 thresholds | low | patch | Filtered to `price_rise`. |
| 11 | VG | a11y screen ready before data | low | patch | Waits for stubbed supplier text. |
| 12 | BH | 503 and error/retry untested | low | defer | 200-case cap. |
| 13 | BH | Populated Watchlist has no own e2e screen | low | defer | Covered behind the Sheet; extra case over budget. |
| 14 | BH | `late` rule uses an unwindowed average | false | reject | `supplier_on_time` is 5.1's 365-day window. |
| 15 | BH | No minimum receipts for `late` | low | reject | AD-20 sets none. |
| 16 | BH | All price-rise alerts loaded each run | low | reject | PoC volume. |
| 17 | EC | Stale price-rise alerts count toward 3 rises | low | reject | Alerts are immutable records (5.3). |
| 18 | EC | Alternatives window uses the staff-api clock | low | reject | Same Singapore day as the run in practice. |
| 19 | BH | Raw ISO dates; long multi-material heading | low | reject | YYYY-MM-DD across staff screens; rare. |
| 20 | IA | Per-pair alerts; names from master; threshold not trend | false | reject | As the plan and AD-20 define. |
| 21 | BH | 5.2 doesn't email watchlist alerts yet | false | reject | Story 5.2 (planned) sends both kinds. |

## Verification

Run 2026-10-01: all four commands pass; `ci/checks.sh test` reports 180 cases (limit 200). Playwright a11y (9 staff screens) passes against a fresh build.

**Commands:**
- `cd backend && uv run pytest tests -q -k "5_4 or 5_3 or 5_1 or migrations"` -- expected: pass
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run lint-imports` -- expected: clean
- `cd web/staff && npm run lint && npx tsc --noEmit && npx vitest run` -- expected: pass
- `ci/checks.sh test` -- expected: ≤ 200 cases
