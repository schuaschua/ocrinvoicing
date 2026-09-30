---
title: 'Invoices: one search box for invoice number, supplier or reference'
type: 'feature'
ticket: '3-4-search-all-invoices'
created: '2026-09-30'
status: 'built'
route: 'full'
route_source: 'auto'
review: 'thorough'
review_source: 'auto'
lenses_ran: ['blind-hunter', 'edge-case-hunter', 'verification-gap', 'intent-alignment']
review_loop_iteration: 0
baseline_revision: '3a47e9362ccbcefae5e0eeda368b672fc7ee27f1'
context:
  - '{project-root}/docs/standards/coding-style.md'
  - '{project-root}/docs/standards/security.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Invoices surface (Story 3.4) searches through three separate controls: a supplier dropdown, an invoice-number box and a reference box. In the Dev walkthrough (walkthrough-dev-2026-09-30.md, follow-up 2), Dj typed a reference, a PO and a supplier name into the invoice-number box and found nothing. A finance user would do the same.

**Approach:** Replace the three controls with **one search box** next to the Status dropdown. staff-api gets a free-text `q` that matches an invoice when `q` is its supplier reference (with or without `R-`, any case), or its invoice number (normalised as today), **or** is contained in its supplier's master name (any case). The existing `supplier_id`, `invoice_number` and `reference` parameters stay, so nothing else breaks. Story 3.4's criteria are unchanged: search by supplier, number, status or reference.

## Boundaries & Constraints

**Always:**
- `q` is 1 to 64 characters after trimming; otherwise 400.
- Status, paging (50) and role checks (admin, finance) work as today.
- The supplier-name match is a bound `ILIKE` on `master.supplier.name` with wildcards escaped.
- The reference match reuses `parse_reference`.
- The number match reuses `normalise_invoice_number` and `_number_matches`.
- User text comes from `strings.ts`; the box is labelled, with a hint, at 48 px.
- Everything else on the screen (table, detail, empty states) is unchanged.
- No search text in logs.

**Never:**
- PO-number search (not in Story 3.4).
- Removing the old parameters.
- More than **1** new test case: add assertions to the existing `test_story_3_4_invoice_search` and the InvoicesScreen Vitest case.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Reference | `q=R-XMWWGRDQ`, `xmwwgrdq` | that invoice | — |
| Number | `q=INV-A-240916`, `inv a 240916` | invoices with that normalised number | — |
| Supplier | `q=alpha` | every invoice of suppliers whose name contains "alpha" | — |
| Combined | `q` plus `status=posted` | the intersection | — |
| No match | `q=zzz` | empty list, "No invoices match this search." | — |
| Bad | empty after trimming, over 64 characters | — | 400 `VALIDATION_FAILED`, the page's bad-search message |
| Wildcards | `q=%` | only names that contain a literal "%" | — |

</frozen-after-approval>

## Code Map

- `backend/src/invoicing/apps/staff_api/invoices.py`:
  - `_query()` parses the params (lines 61–106), `MAX_INVOICE_NUMBER = 64`, `parse_reference`, `normalise_invoice_number`.
  - Add `q`.
- `backend/src/invoicing/ports/invoice_search.py` (the `SearchQuery` dataclass): add `text: str | None`, keeping its fields' defaults.
- `backend/src/invoicing/adapters/postgres/invoice_search.py`:
  - `_conditions()` (about line 187) ANDs the filters. Add one OR group for `text`: `_reference_of(id) == ref`, `id IN _number_matches(...)`, and `supplier_id IN (SELECT id FROM master.supplier WHERE name ILIKE …)`.
  - Reuse `supplier_names` and the `supplier` table from `adapters/postgres/suppliers.py`, and `icontains(..., autoescape=True)` as in `PostgresSupplierDirectory._matching`.
- `web/staff/src/api/invoices.ts`: `InvoiceQuery` (line 34) and `searchInvoices` gain `text`, sent as `q`.
- `web/staff/src/screens/InvoicesScreen.tsx`:
  - The form (lines 190–275): remove the supplier `<select>`, number and reference inputs.
  - Add one search input, with a hint, and keep the Status select. The form stays top-aligned.
  - The `suppliers` state goes if it is no longer used.
- `web/staff/src/strings.ts` `invoices.filters`: `search` label ("Invoice number, supplier or reference") and `searchHint` ("Like INV-1042, Alpha or R-7Q4KXM2D"). Drop the unused keys, and reword `badSearch`.
- Tests:
  - `backend/tests/apps/test_story_3_4_invoice_search.py` (single merged test, line 158).
  - `web/staff/src/screens/InvoicesScreen.test.tsx` (single `it`, line 87).
  - `web/staff/e2e/screens.ts` if its Invoices screen fills the old fields.

## Tasks & Acceptance

**Execution:**
- [x] `ports/invoice_search.py`, `adapters/postgres/invoice_search.py` -- `SearchQuery.text` and the OR condition -- one query, bound parameters.
- [x] `apps/staff_api/invoices.py` -- parse and validate `q` -- 400 on empty or too long.
- [x] `web/staff/src/api/invoices.ts`, `InvoicesScreen.tsx`, `strings.ts` -- one box plus Status -- the walkthrough finding.
- [x] Tests -- matrix rows as assertions in the two existing cases; update e2e screen data if needed.

**Acceptance Criteria:**
- Given `ci/checks.sh all`, then it passes with at most 200 test cases, and the a11y check passes on the Invoices screen.

## Review Triage Log

Four lenses (blind, edge-case, verification-gap, intent-alignment), about 22 findings after de-duplication. 9 patched, 8 rejected, the rest intent notes.

- Patched (low/medium):
  - The button offset only applies from `sm`.
  - The hint is generic (no test-data name).
  - `badSearch` is generic, because the box can't send a refused search.
  - The web 400 case is a defensive mock with an ordinary value.
  - "No match" is asserted with the box alone.
  - Paging keeps `q`.
  - `MAX_SEARCH_TEXT` is separate from `MAX_INVOICE_NUMBER`.
  - The backend asserts a 64-character `q` returns 200, and `q` plus `supplier_id` returns the intersection.
  - The EXPERIENCE.md Invoices row matches the screen.
- Rejected (low):
  - The number scan runs on every search. It is the existing invoice-number search, filtered by `field_id`, and cheap at PoC volume; skipping it adds branching.
  - The unused `suppliers` payload: the Intent keeps the API unchanged.
  - An empty `?q=` dropped by the host, and `strip` versus `trim` differences: the screen never sends either.
  - No log assertion: no logging was added.
  - `_number_matches` passes an in-list: this is pre-existing.
  - Invoices without a master supplier can't be found by name: the Intent says master name.
  - Plan bookkeeping: handled here.
- Intent notes (not defects; the Intent excludes them), for Dj:
  - A PO number in the box finds nothing.
  - A partial invoice number finds nothing.
  - Exact supplier picking is gone from the screen; the API keeps `supplier_id`.

## Verification

**Commands:**
- `ci/checks.sh all` -- expected: all checks pass.

**Manual checks (after the Dev deploy):**
- On Invoices, `R-XMWWGRDQ`, `INV-A-240916` and `alpha` each find Alpha's posted invoice.
