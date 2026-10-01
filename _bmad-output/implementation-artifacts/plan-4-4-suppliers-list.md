---
title: 'Story 4.4: Suppliers list and supplier page'
type: 'feature'
ticket: '4-4-suppliers-list-and-supplier-page'
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

**Problem:** Procurement, finance and management have no place to find a supplier, and the scorecard (5.5) and deliveries (4.5) have no page to live on (Flow 5).

**Approach:**
- staff-api gets a suppliers list and search API over `master.supplier`, with no bank columns, plus a single-supplier lookup.
- `web/staff` replaces the Suppliers and supplier-page placeholders with:
  - a searchable list paginated at 50;
  - a supplier page shell with a tab area. It shows a Scorecard tab now, with a "coming" note until Story 5.5, and leaves room for Deliveries (Story 4.5).

## Boundaries & Constraints

**Always:**
- **Access:** `Surface.SUPPLIERS` and `Surface.SUPPLIER_SCORECARD` (procurement, finance, management). Signed out gets 401. Any other role gets 403 on the list and 404 on a single supplier, before anything is read (security.md rule 5). `platform_auth_trusted` is passed explicitly.
- **`GET api/suppliers?page=&q=`:**
  - Returns `{items: [{supplier_id, name}], page, page_size: 50, total}`, sorted by name (case-insensitive), then by id.
  - `q` is 1–64 characters after trimming and matches names containing it, in any case, with LIKE wildcards escaped.
  - `page` is a whole number from 1. Anything else gives 400 `VALIDATION_FAILED`, and the message never echoes the value.
- **`GET api/suppliers/{supplier_id}`:** returns `{supplier_id, name}`. Unknown or malformed ids give 404.
- **Never exposed:** `tax_id`, `phone` or anything in `supplier_bank`. Only `master.supplier.id` and `name` are read.
- **Web:**
  - Wire fields are snake_case, mapped in `web/staff/src/api/`.
  - Strings live in `strings.ts`.
  - The search box submits on Enter or a button and resets to page 1.
  - Each row links to `/suppliers/{id}`.
  - Empty and no-match states have their own copy.
  - The page shell has a heading with the supplier name, a "Back to suppliers" link, and a tab list with Scorecard selected. Its panel says the scorecard is coming. Unknown ids show a not-found state.
  - It reuses the InvoicesScreen paging and the layout patterns.
- **Tests:** at most **3** new test cases.

**Never:**
- a supplier admin or edit screen (EXPERIENCE.md: no supplier master surface);
- scorecard numbers (5.5) or delivery dates (4.5);
- new database grants (staff-api already reads `master`);
- touching Azure.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| List | procurement, page 1 | First 50 suppliers by name, total | — |
| Page 2 | 51+ suppliers | The rest, page 2 | — |
| Search | `q=soles` | Names containing "soles", any case; `%` and `_` literal | — |
| Bad query | `page=0`, `q` over 64 chars or blank | 400 `VALIDATION_FAILED` | Value not echoed |
| No bank data | Any response | Only `supplier_id`, `name` | — |
| One supplier | Known id | `{supplier_id, name}` | Unknown or malformed → 404 |
| Wrong role | admin, goods_in | 403 list, 404 single | Before any read |
| Landing | procurement signs in | Lands on Suppliers | — |
| Page shell | Row clicked | Supplier page, Scorecard tab with the "coming" note | Unknown id → not-found state |

</frozen-after-approval>

## Code Map

- `backend/src/invoicing/apps/staff_api/invoices.py`: the pattern for query validation (`_PAGE`, `MAX_SEARCH_TEXT`), paging (`PAGE_SIZE`), `staff_endpoint`, `json_response`, and 404 versus 403. The new file is `apps/staff_api/suppliers.py`. Wire it in `function_app.py` before the SPA catch-all.
- `backend/src/invoicing/ports/suppliers.py`, `adapters/postgres/suppliers.py`:
  - `PostgresSupplierDirectory` and the `supplier` table hold only `id` and `name`.
  - Add `page(text, page) -> (rows, total)` and `get_name(id)`, following the `ilike(..., autoescape=True)` pattern.
- `backend/src/invoicing/domain/roles.py`: `Surface.SUPPLIERS` and `SUPPLIER_SCORECARD` exist, and `LANDING_SURFACE[PROCUREMENT] = SUPPLIERS`.
- `web/staff/src/App.tsx`: `suppliers` and `supplier_scorecard` render `SurfacePage` today; swap them for the new screens. `itemIdFrom(path)` reads the id. Also `surfaces.ts` (routes exist), `screens/InvoicesScreen.tsx` (list, paging, search pattern), `InvoiceDetailScreen.tsx` (detail and back link), `strings.ts`, and `components/ui/` (shadcn; use a Tabs component if present, else an accessible tablist).
- Test patterns: `backend/tests/apps/test_story_3_4_invoice_search.py` and `web/staff/src/screens/InvoicesScreen.test.tsx`. `App.test.tsx` already checks procurement lands on Suppliers.

## Tasks & Acceptance

**Execution:**
- [x] `ports/suppliers.py`, `adapters/postgres/suppliers.py`: the page/search and name lookup.
- [x] `apps/staff_api/suppliers.py`, `function_app.py`: both routes.
- [x] `web/staff/src/api/suppliers.ts`, `screens/SuppliersScreen.tsx`, `screens/SupplierScreen.tsx`, `strings.ts`, `App.tsx`: the list and the page shell.
- [x] Tests (at most 3 new cases):
  - `test_story_4_4_suppliers_api` covers search, paging, escaping, no bank fields, 400, 401/403/404, and the single-supplier lookup;
  - one web case for the list (search, paging, link);
  - one web case for the page shell (tabs, not found).

**Acceptance Criteria:**
- Given the API responses, when inspected, then no key other than `supplier_id`, `name`, `items`, `page`, `page_size` and `total` appears.

## Implementation Notes

## Plan Change Log

## Review Triage Log

### Pass 1 (2026-10-01): high 0, medium 2, low 10, false/rejected 6; lenses run one at a time

| # | Lens | Finding | Verdict | Route | Evidence / action |
|---|---|---|---|---|---|
| 1 | VG, IA | Routed app never shown to render the new screens (heading checks pass with SurfacePage) | medium | patch | App.test.tsx mocks /api/suppliers and asserts the row, the name heading and the Scorecard tab. |
| 2 | VG | Detail 200 for procurement and finance unproven | medium | patch | Both asserted with the exact body. |
| 3 | BH, EC | Total and rows read in two statements | low | patch | One REPEATABLE READ read-only snapshot. |
| 4 | EC | NUL in `q` gives 500 | low | patch | 400 `VALIDATION_FAILED`; asserted. |
| 5 | BH, EC | `page_size` 0 makes the page count Infinity | low | patch | Non-positive page size is a broken response. |
| 6 | BH, EC | Success callbacks lack the aborted check | low | patch | Both screens return early when aborted. |
| 7 | BH | Pager used the queue's strings and label | low | patch | `strings.suppliers.pagination`. |
| 8 | BH | `plainClick` exported from a screen | low | patch | Moved to `lib/links.ts`. |
| 9 | BH, EC | Test fragility: unscoped wildcard search, 400 reads, re-run seeding | low | patch | Scoped, asserted, pre-delete and finally. |
| 10 | VG, BH | Past-end clamp and error/retry states untested | low | defer | Cap; fold into the list test later. |
| 11 | BH | Search/page result not announced to screen readers | low | defer | Same as InvoicesScreen; fix both together. |
| 12 | BH | Search and page not kept in the URL | low | reject | Not in the intent; InvoicesScreen behaves the same. |
| 13 | BH | No trigram or sort index | low | reject | PoC-sized master. |
| 14 | BH | 64 hard-coded in the web maxLength | low | reject | Server is authoritative; cosmetic. |
| 15 | BH | List and detail gated by different surfaces | false | reject | Both surfaces have the same roles in EXPERIENCE.md and roles.py. |
| 16 | EC | Empty-state copy when items empty but total > 0 | low | reject | Only reachable mid-race; the clamp refetches. |
| 17 | BH | Tracking files and Jira not in the diff | false | reject | Plan and sprint status are committed with the story; Jira synced by the orchestrator. |

## Verification

**Commands:**
- `cd backend && uv run pytest tests/apps -q -k "4_4 or function_apps"`: should pass (Docker Postgres).
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run lint-imports`: should be clean.
- `cd web/staff && npm run lint && npx tsc --noEmit && npx vitest run`: should pass.
- `ci/checks.sh test`: should stay at or under 200 cases.
