---
title: 'Story 3.4: Search all invoices'
type: 'feature'
ticket: '3-4-search-all-invoices'
created: '2026-09-30'
status: 'built'
route: 'full'
route_source: 'auto'
baseline_revision: '5d5ceeaddb2977b917e12fb5c5bf188c3681bb0c'
review: 'thorough'
review_source: 'auto'
lenses_ran: ['edge-case-hunter', 'verification-gap']
review_loop_iteration: 0
context:
  - '{project-root}/docs/standards/coding-style.md'
  - '{project-root}/docs/standards/security.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Finance can't find an invoice or see where it is without asking the admins, so supplier and audit questions stall.

**Approach:** Add a staff-api invoice search and detail API for admin and finance (the `invoices` surface), and build the `/invoices` screen: search by supplier, invoice number, status or supplier reference (`R-…`), 50 per page, status labels (never codes); a detail view with the current field values (AD-18), the status history and the accounts reference, never images or bank digits for finance.

## Boundaries & Constraints

**Always:** roles admin and finance only (`Surface.INVOICES`); any other role refused (403 on search, 404 on detail, like the queue/item pair); one read snapshot; bound parameters; the `R-` reference is derived from the UUIDv7's low 40 bits (`domain/reference.py`) — search decodes it and matches `substring(uuid_send(id) from 12 for 5)`, and the result list shows each row's reference; invoice number searched on the current value (AD-18), normalised like the duplicate check (uppercase, alphanumerics); statuses returned as codes and shown as labels via `statusLabel` (incl. "Re-checking" after correction); detail: current fields (bank fields shown only as "Bank details on file" — no mask, no digits, for every role here), lines, status history (from/to/at/actor category, not raw actor ids), `accounts_ref`, `posted_at`; no image endpoint for this surface; 50 per page; no field values in logs.

**Never:** editing anything; admin actions (they live on the item screen); exports; more than **3** new test cases.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Search | supplier and/or status and/or invoice number and/or `R-…` | matching invoices newest first, 50 per page, with received, supplier, invoice number, total, status, reference | bad status / uuid / reference format → 400 |
| Reference | `R-7Q4KXM2D` (any case, spaces trimmed) | invoices whose id's low 40 bits match (can be more than one) | — |
| Invoice number | `inv-001` | matches current `invoice_number` "INV 001" | — |
| Labels | any status | shown as Processing / Checking / Re-checking / Posting / Posted / In admin queue / Rejected | unknown status → "Processing" |
| Detail | open a result | current fields, lines, status history, accounts reference | unknown id → 404 |
| Bank fields | invoice with `payment[n].*` rows | "Bank details on file" only | — |
| Other roles | goods_in, procurement, management | search 403, detail 404 | nothing read |
| Signed out | — | 401 | — |

</frozen-after-approval>

## Code Map

- `backend/src/invoicing/apps/staff_api/queue.py`, `item.py`, `function_app.py` -- endpoint/route patterns (the SPA catch-all stays last), `staff_endpoint(..., surface=...)` with required `platform_auth_trusted`, `hide_from_others` for 404.
- `backend/src/invoicing/adapters/postgres/admin_queue.py` -- snapshot read pattern, supplier names, current totals via `current_values`; `adapters/postgres/admin_item.py` `_current`/fields and lines reading.
- `backend/src/invoicing/domain/reference.py` -- `supplier_reference`, `ALPHABET`, `PREFIX`; add a `parse_reference` returning the 5 low bytes.
- `backend/src/invoicing/domain/validation.py` -- invoice-number normalisation used by the duplicate check.
- `backend/src/invoicing/domain/roles.py` -- `Surface.INVOICES` = admin, finance.
- `backend/src/invoicing/domain/extraction.py` -- `is_bank_field_id`.
- `web/staff/src/surfaces.ts` (`invoices` → `/invoices`), `App.tsx`, `screens/QueueScreen.tsx` (table/filter/paging pattern), `strings.ts` (`statusLabel`, `statusLabels`), `api/queue.ts` pattern, shadcn table/badge.
- Tests: `backend/tests/apps/test_story_2_8_admin_queue.py` (style), `web/staff/src/screens/QueueScreen.test.tsx`, `e2e/screens.ts`.

## Tasks & Acceptance

**Execution:**
- [x] `domain/reference.py` `parse_reference`.
- [x] `ports/invoice_search.py` + `adapters/postgres/invoice_search.py` -- search (filters, paging, total) and detail (fields without bank values, lines, history, accounts ref).
- [x] `apps/staff_api/invoices.py` + routes `GET api/invoices`, `GET api/invoices/{id}`.
- [x] Web: `api/invoices.ts`, `screens/InvoicesScreen.tsx` (search form, table with labels and reference, paging, empty state), `screens/InvoiceDetailScreen.tsx` (`/invoices/:invoiceId` surface or in-screen detail), strings.
- [x] Tests (≤ 3 new cases): one DB app test (each filter, reference incl. case/spaces, number normalisation, paging, detail, bank fields never valued, other roles 403/404, 401); one Vitest (labels incl. Re-checking, search → results, detail); a11y: extend an existing screen or add one within budget.

**Acceptance Criteria:**
- Given `ci/checks.sh all`, then it passes with ≤ 200 test cases and the a11y check.

## Implementation Notes

- Detail is its own web route, `invoice_detail` at `/invoices/:invoiceId` (nav: false, admin and finance), so Back works; staff-api guards both endpoints with `Surface.INVOICES` (no new backend surface).
- `status` takes comma-separated AD-3 codes; the web's status filter offers one option per label (e.g. "Processing" sends `received,awaiting_extraction,extracting`), derived from `statusLabels`.
- `reference` accepts the `R-` prefix or not. `invoice_number` is narrowed in SQL on any stored row (`regexp_replace(upper(...))`), then kept only when the AD-18 current value (`current_values`) normalises equal, so the one current-value rule stays in Python.
- Detail drops bank fields from `fields` entirely and sends `bank_on_file: bool`; history `actor` is `quality`/`extract`/`validate`/`post`, `admin` or `system`.
- Tests: 4 new cases (`test_story_3_4_invoice_search`, Vitest "3.4 search all invoices", a11y screens "3.4 finance searches all invoices" and "3.4 invoice detail with bank details on file"); detail routing is asserted inside the existing App.test "redirects a route outside the user's roles".
- Review fixes: detail money fields and line unit price/amount go out at 2 decimals (ROUND_HALF_UP, falling back to the plain string on `InvalidOperation`); supplier options kept in their own state; detail Try again resets to loading; the empty-page redirect only moves to an earlier page.

## Plan Change Log

## Review Triage Log

Pass 1 (2026-09-30, unattended). Lenses one at a time: edge-case-hunter, verification-gap. Verdicts: high 0, medium 6, low 5, false 1.

| # | Lens | Finding | Verdict | Route | Evidence |
|---|------|---------|---------|-------|----------|
| E1 | edge | Unicode upper-casing differs between SQL and Python for rare characters | low | reject | invoice numbers are OCR'd Latin text; a narrowing miss needs characters like ß or ﬁ |
| E2 | edge | Invoice number stored as a number, not text | low | reject | DI types `InvoiceId` as a string; mapped to `value_text` |
| E3 | edge | Non-UUIDv7 ids in a reference search show no reference | false | reject | every invoice id is a UUIDv7 (`new_uuid7`) |
| E4 | edge | A huge misread total → InvalidOperation → the page 500s | low | patch | guard the quantize |
| E5 | edge | After a search error the supplier options vanish but the hidden supplier still filters | medium | patch | keep the last supplier list |
| E6 | edge | Try again keeps the old error on screen | low | patch | show loading |
| V1 | gap | `/invoices/:invoiceId` never exercised through the app shell; no a11y check of the detail | medium | patch | App test + one a11y screen (one new case) |
| V2 | gap | Supplier options only checked unfiltered | medium | patch | mirror 2.8's assertion |
| V3 | gap | Frontend paging and the past-the-end clamp unexercised | medium | patch | assertions in the existing Vitest |
| V4 | gap | Currency fallback never taken | low | patch | one seeded row with NULL currency |
| V5 | gap | Detail money not in the 2-decimal format ("SGD 1248.5"); the test fixture hides it | medium | patch | coding-style rule 4 |

## Design Notes

Decisions made unattended (Dj asleep, 2026-09-30):
- **Reference search decodes to bytes and matches in SQL**; it may return several invoices (references aren't unique), which the list shows with supplier and date.
- **Bank fields show "Bank details on file" for admins too on this surface**; masks and reveals stay on the admin item screen.
- **Status history shows actor categories** (pipeline stage, admin, system), not raw identities.
- **Newest first** for search results (the queue is oldest first because it is a work list).

## Verification

**Commands:**
- `ci/checks.sh all` -- expected: all checks pass, test cases ≤ 200.
