---
title: 'Story 2.9: Admin item shows the crop, fields and bank-change details'
type: 'feature'
ticket: '2-9-admin-item-shows-the-crop-fields-and-bank-change-details'
created: '2026-09-30'
status: 'built'
route: 'full'
route_source: 'auto'
baseline_revision: '1568765464ebad6178b91384063daa13a6e112b2'
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

**Problem:** From the queue an admin cannot open an invoice: there is no item screen, so they cannot see which part of the invoice is in doubt or what bank details changed.

**Approach:** Add admin-only item endpoints to staff-api (item facts with current fields, flags, regions and masked bank changes; a same-origin image stream; an audited reveal of one bank value) and the `/queue/:invoiceId` screen: an image viewer zoomed to the flagged regions, the field list linked to its boxes, and the bank-change panel with timed reveal. Extraction now keeps each page's size so boxes can be drawn.

## Boundaries & Constraints

**Always:** admin only; for any non-admin, an unknown invoice, or one not in `in_admin_queue`, item endpoints answer 404 (never 403, so existence isn't revealed); current values via `current_values` (AD-18); flagged fields = `field_ids` of the latest `routing_id` (AD-4); bank values decrypted only in staff-api's SQL with the `pgp-private-key` read from the private-key vault, never logged, never cached beyond the process's key; by default only a mask (last 4 characters) leaves the server; a full value only through the reveal endpoint, which writes `audit.event` (`action=bank.reveal`, entity invoice, `detail {field_id, which, admin_oid}`, no values) in the same transaction; images served same-origin with `Cache-Control: no-store`; UI copy in `strings.ts`, tokens from `index.css`, no animation under `prefers-reduced-motion`.

**Never:** admin actions (2.10); keyboard shortcuts (2.11); a PDF renderer (PDFs show an "Open the PDF" link and the field list, no boxes); client-side decryption; storing revealed values in browser storage; more than **4** new test cases.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Open item | admin, queued invoice with run | reasons (codes, detail), fields (id, value, confidence, page, polygon, flagged), lines, page sizes, content type, supplier name/phone (only if `BANK_CHANGED`), bank changes | — |
| Viewer | image with flagged regions and page sizes | opens zoomed to the first flagged box; Previous/Next cycle flagged boxes; Show whole invoice; zoom in/out and pan buttons; numbered boxes with white halo; selected box 4px | reduced motion: no zoom animation |
| Field ↔ box | select a field / a box | the matching box / field is highlighted and announced | fields without region: no box |
| Confidence | value < 0.98 | badge "Confidence 91%" (announced); admin rows count 1.0 | — |
| No page sizes | run extracted before this story | fields shown, no boxes, whole image | — |
| PDF | `application/pdf` | "Open the PDF" link to the stream; field list; no boxes | — |
| Image deleted | blob not found (30-day rule) | placeholder "Image deleted after 30 days"; fields still shown | image endpoint 404 `IMAGE_DELETED` |
| Bank changed | `BANK_CHANGED` with `payment[n].iban` etc. | panel: supplier phone on file; per field: on-file mask or "No account on file", new mask ("account ending 4821") | decrypt/key failure → 503, no value |
| Reveal | admin taps Show (new or on-file) | POST reveal → full value, audit row committed; shown until Hide, leaving the item, or 30 s; at 20 s announced warning with Keep showing (restarts the 30 s); hide announced | audit write fails → no value returned |
| Non-admin / not queued / unknown | any item, image or reveal call | 404 | nothing read, nothing decrypted |
| Signed out | no principal | 401 | — |

</frozen-after-approval>

## Code Map

- `backend/src/invoicing/apps/staff_api/function_app.py`, `queue.py` -- endpoint/route pattern; engine; SPA catch-all stays last (a test asserts it).
- `backend/src/invoicing/adapters/principal.py`, `domain/roles.py` (`Surface.ADMIN_ITEM`), `domain/errors.py` (`NotFoundError`), `domain/ids.parse_uuid`.
- `backend/src/invoicing/ports/admin_queue.py`, `adapters/postgres/admin_queue.py` -- port/adapter and `_latest_routing()`, snapshot read; `adapters/postgres/suppliers.py` (`supplier`, `supplier_bank`, `audit.event` table, `write_audit`).
- `backend/src/invoicing/domain/current_values.py` -- extend `FieldValue` with optional `page`, `polygon` (keep existing callers working).
- `backend/src/invoicing/domain/validation.py` -- `bare_bank_field_id`, `check_bank` (field ids in `BANK_CHANGED`).
- `backend/src/invoicing/adapters/document_intelligence.py` (~line 200-210) -- keep `result.pages[]` `pageNumber/width/height/unit`; `ports/extraction.py` `Analysis`; `adapters/postgres/extraction.py` `_save_run` writes them.
- `backend/migrations/versions/0007_staff_queue.py` -- latest; new `0008_extraction_pages.py`: `intake.extraction_page(run_id, page, width, height, unit)` append-only (pipeline INSERT/SELECT, staff SELECT).
- `backend/src/invoicing/ports/blobs.py`, `adapters/blob_images.py` -- `BlobImageStore.with_managed_identity`, `ImageNotFoundError`; staff-api already has blob access to `images`.
- `backend/src/invoicing/adapters/key_vault.py` -- `read_secrets`, `BankKeysLoader` pattern; add `PRIVATE_KEY_SECRET = "pgp-private-key"` and a lazy private-key loader using `pgp_private_key_vault_uri`.
- `backend/src/invoicing/adapters/static.py` `_file_response` -- binary response pattern.
- `web/staff/src/App.tsx` (~line 173), `surfaces.ts` (`/queue/:invoiceId`), `router.ts`, `screens/QueueScreen.tsx`, `api/queue.ts`, `api/client.ts`, `strings.ts`, `index.css` (`--flag`, `--flag-fill`, `--flag-halo`, `--confidence-low`), `components/ui/*`, `e2e/screens.ts`.
- Tests: `backend/tests/apps/test_story_2_8_admin_queue.py` (style, fixtures, `header`, `_Spy`), `tests/_pgp.py` `make_test_key_pair`, `tests/adapters/test_blob_images_adapter.py` (blob fake), `web/staff/src/screens/QueueScreen.test.tsx`.

## Tasks & Acceptance

**Execution:**
- [x] Page sizes: DI adapter keeps page sizes; `Analysis.pages_info`; `_save_run` writes `extraction_page`; migration 0008.
- [x] `ports/admin_item.py` + `adapters/postgres/admin_item.py` -- one snapshot read of the item (404 unless queued), and `reveal(invoice_id, field_id, which, admin_oid, private_key)` (decrypt + audit in one transaction); masks computed in SQL (`right(pgp_pub_decrypt(...), 4)`), never full values in the item read.
- [x] `apps/staff_api/item.py` + routes: `GET api/admin/items/{id}`, `GET api/admin/items/{id}/image`, `POST api/admin/items/{id}/bank/reveal` (`{field_id, which: "new"|"on_file"}`); non-admin → 404; custom header check as other non-GET routes require.
- [x] `web/staff`: `api/item.ts`; `screens/ItemScreen.tsx` with `ImageViewer`, `FieldList`, `BankChangePanel`, `MaskedValue` (timer, Keep showing, announcements via a live region); wired for `admin_item` in `App.tsx`; strings.
- [x] Tests (≤ 4 new cases): one backend DB test (item body, 404s incl. non-admin with nothing read, image stream + deleted, mask, reveal writes audit and returns value, audit failure returns nothing, page sizes saved by extract); one Vitest for the viewer/field list (zoom-to-first, prev/next, whole, selection both ways, reduced motion, deleted placeholder, PDF link); one Vitest for the bank panel/reveal (mask, Show, 20 s warning, Keep showing, 30 s hide, Hide announced) with fake timers; a11y: one new item screen in `e2e/screens.ts` if within budget, else extend an existing one.

**Acceptance Criteria:**
- Given `ci/checks.sh all`, then it passes with ≤ 200 test cases, coverage floors met and a11y green.

## Implementation Notes

- The private key is not a `reveal` argument: `PostgresAdminItemReader` takes a lazy provider (`PrivateKeyLoader`, synchronous and thread-safe, called on the worker thread only when a bank value is decrypted), so the item read can load it only when `BANK_CHANGED` is open.
- `StaffPrincipal` gains `oid` (the Entra object id claim) for the audit detail's `admin_oid`; `/api/me` still returns name and roles only.
- `staff_endpoint` gains `hide_from_others` (non-admin -> 404) and now refuses any non-GET call without `X-Requested-With: XMLHttpRequest` (403), after the role check.
- The item body carries `image_available` (a blob HEAD), so the deleted placeholder and the PDF link don't depend on a failed image load; `<img onError>` shows "The image couldn't be loaded." for other failures.
- New error code `IMAGE_DELETED` (404). Decrypt or key failures answer 503 `SERVICE_UNAVAILABLE` with no value.
- Keep showing reveals again (a second audit entry, EXPERIENCE.md "+30 s, audited again") and restarts the 30 s.
- Box numbers are drawn by CSS (`content: attr(data-number)`): the viewport clips the zoomed image on purpose, and the a11y check counts clipped text. The lines table container is a focusable, labelled region (`Table scrollLabel`), since it has nothing focusable inside at 320px.
- Page sizes saved by extract are asserted in `test_story_2_3_extract` (no new case); `extraction_page` joins the migration test's refused-UPDATE list and `truncate_intake`.
- New test cases: 4 (1 pytest, 2 Vitest, 1 Playwright).

## Plan Change Log

## Review Triage Log

Pass 1 (2026-09-30, unattended). Lenses one at a time: edge-case-hunter, verification-gap. The orchestrator also read the reveal and decrypt paths. Verdicts: high 1, medium 9, low 2, false 5.

| # | Lens | Finding | Verdict | Route | Evidence |
|---|------|---------|---------|-------|----------|
| E1 | edge | A bank value of 4 characters or fewer is sent whole as its "mask", unaudited | high | patch | `right(plaintext, 4)` returns the whole value; AD-11 / plan: only masks leave the server by default |
| E2 | edge | Duplicate bank field ids → duplicate panel entries | false | reject | `route_to_admin` de-duplicates reasons and `check_bank` yields each field id once |
| E3 | edge | Reveal with no `oid` audits without naming the admin | medium | patch | `admin_oid` may be None; refuse the reveal (404, nothing decrypted) without it |
| E4 | edge | Key Vault slow while the loader lock is held | low | reject | one read per process, cached |
| E5 | edge | Rotated/wrong cached key → 503 until restart | false | reject | a new key pair cannot decrypt existing ciphertext; rotation needs re-encryption anyway |
| E6 | edge | Blob `exists` failure fails the whole item | false | reject | mapped to 503 by design (storage down) |
| E7 | edge | 401/DB_OFFLINE leaves the item screen on its skeleton with no retry | medium | patch | no refetch after the shell recovers |
| E8 | edge | "Flag 1 of N" when no box is selected | low | patch | index −1 shown as 1 |
| E9 | edge | A Keep-showing reveal in flight when the 30 s hide fires re-shows the value | medium | patch | response not ignored after hide |
| E10 | edge | (claim) short values leave the server | high | patch (E1) | same as E1 |
| E11 | edge | (claim) `reveal` signature differs from plan | false | reject | recorded deviation: key provider injected in the constructor |
| V1 | gap | `PrivateKeyLoader` cache and repr untested | medium | patch | only a fake key is used |
| V2 | gap | `page_sizes` filtering only tested on a valid page | medium | patch | a bad or duplicate page would roll back the whole extraction save |
| V3 | gap | staff-api INSERT and DELETE on `extraction_page` not refused in tests | medium | patch | only UPDATE is in `REFUSED` |
| V4 | gap | Short `oid` claim never exercised | medium | patch | audit could record null admin |
| V5 | gap | MaskedValue reveal-failure branch untested | medium | patch | a 503 reveal could stick on loading |

## Design Notes

Decisions made unattended (Dj asleep, 2026-09-30):
- **Page sizes are new data**: DI returns page width/height/unit (pixels for images, inches for PDFs) and 2.3 dropped them; runs before this story have none and show no boxes.
- **No PDF renderer** (pdf.js is large and the CSP forbids workers/blobs); PDFs are opened by link. Deferred.
- **Decrypt in SQL** with the private key as a bound parameter over TLS, matching how encryption is done; statement logging on Azure is off by default. The key is read lazily once per process.
- **Masks leave the server by default** (last 4); only the reveal returns a full value, and only after its audit row is written in the same transaction.
- **404 for non-admins on item endpoints** (story 2.8's AC), unlike the queue's 403.

## Verification

**Commands:**
- `ci/checks.sh all` -- expected: all checks pass, test cases ≤ 200.
