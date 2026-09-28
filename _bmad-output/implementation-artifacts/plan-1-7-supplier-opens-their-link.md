---
title: 'Story 1.7: Supplier opens their link'
type: 'feature'
ticket: '1-7-supplier-opens-their-link'
created: '2026-09-29'
status: 'built'
baseline_revision: 'd12f25d49989e5605cd39e2632deff143bc23e9e'
route: 'full'
route_source: 'auto'
review: 'thorough'
review_source: 'auto'
lenses_ran: ['blind-hunter', 'edge-case-hunter', 'verification-gap', 'intent-alignment']
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-ocrinvoicing-2026-09-28/EXPERIENCE.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-ocrinvoicing-2026-09-28/DESIGN.md'
  - '{project-root}/docs/standards/coding-style.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** A supplier who opens their personal link gets nothing: there is no link lookup and no upload page. They need to see that the page uploads for their company, a clear message when the link doesn't work, and a page that works while PostgreSQL is stopped and while the app wakes from zero.

**Approach:** Add the read side of the supplier link registry (port + Azure Table adapter resolving `SHA-256(token)` → `supplier_id`, `supplier_name`, revoked), a `GET /api/link` route on `supplier-api` reading `X-Upload-Token`, and the supplier SPA's token handling, Upload home, Link not working and waking-up states. Verify offline with fakes.

## Boundaries & Constraints

**Always:** Token only from the URL fragment (`/u#<token>`), sent as `X-Upload-Token` on every call; never in a URL, log, error or telemetry (AD-6, AD-14). Lookup by `SHA-256(token)` hex in Table `supplierlinks` (PartitionKey/RowKey scheme chosen once and documented for Story 1.6 to write), fields `supplier_id`, `supplier_name`, `issued_at`, `revoked_at`. `supplier-api` touches Table Storage only (no PostgreSQL, AD-6). Revoked, unknown, malformed or missing token → one identical 401 response and one identical page: "This link isn't working. Please contact your buyer at Babaloo." (UX-DR7). Response returns `supplier_name` only (not `supplier_id`). Upload home: "Uploading for **{supplier name}**" with **Take photo** and **Choose file** (UX-DR4), copy from `strings.ts`, per EXPERIENCE.md. Skeleton while loading; after 3 s "Waking up, one moment…" (UX-DR20). Accessibility floor and bundle budget from 1.4 still pass.

**Never:** Issuing or revoking links, the load script, `master` migration (Story 1.6). Upload/camera behaviour behind the buttons (1.8, 1.9) beyond rendering them. Logging the token, its hash or the header. Calling Azure.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Valid link | `GET /api/link` with a token whose hash row exists, `revoked_at` empty | 200 `{"supplier_name": "..."}`; page shows Upload home with the name | — |
| Revoked link | Row exists with `revoked_at` set | 401 `{code: "LINK_NOT_VALID", ...}`; page shows Link not working | Same body/timing class as unknown |
| Unknown link | No row for the hash | Same 401 as revoked | — |
| Missing/malformed token | No header, empty, wrong length or not base64url | Same 401 | No table lookup for malformed tokens |
| No fragment | Page opened at `/u` with no `#token` | Link not working, no API call | — |
| DB stopped | PostgreSQL unreachable | Upload home still works (no PostgreSQL dependency at all) | — |
| Table outage | Table lookup raises a transient error | 503 `{code: "SERVICE_UNAVAILABLE"}`; page shows a retryable error, not Link not working | Token not logged |
| Waking up | `/api/link` slower than 3 s | Skeleton, then "Waking up, one moment…" (live region) until the answer | — |
| Logging | Any request | No log/telemetry record contains the token, its hash or `X-Upload-Token` | — |

</frozen-after-approval>

## Code Map

- `backend/src/invoicing/apps/supplier_api/function_app.py` -- add `GET api/link`; health and SPA catch-all exist; supplier-api never trusts caller correlation ids.
- `backend/src/invoicing/adapters/http.py` (`http_endpoint`, error mapping), `domain/errors.py` (codes) -- add `LINK_NOT_VALID` (401) and `SERVICE_UNAVAILABLE` (503) if missing.
- `backend/src/invoicing/adapters/logging.py` -- allow-list; never add token fields.
- `backend/src/invoicing/ports/` -- new `links.py` (`SupplierLinkRegistry.resolve(token_hash) -> SupplierLink | None`); `adapters/table_links.py` (azure-data-tables, managed identity, async). Story 1.6 will add `issue`/`revoke` to the same port.
- `backend/src/invoicing/apps/supplier_api/settings.py` -- storage account name exists; table name constant `supplierlinks`.
- `infra/modules/env-app` -- supplier-api already has Storage Table Data Contributor on the account (AD-17); no Terraform change expected.
- `web/supplier/src/{App.tsx, strings.ts, api/client.ts}` -- client sends headers; add the token header from the fragment; screens per EXPERIENCE.md "Upload home", "Link not working", waking-up.
- `web/supplier/e2e/a11y.spec.ts` `SCREENS` -- add the new screens.

## Tasks & Acceptance

**Execution:**
- [ ] `backend/src/invoicing/domain/links.py` -- token format check (43-char base64url, 256 bits) and `token_hash()`; framework-free.
- [ ] `backend/src/invoicing/ports/links.py`, `adapters/table_links.py` -- registry port + Table adapter; key scheme documented in the port docstring.
- [ ] `backend/src/invoicing/apps/supplier_api/function_app.py` -- `GET api/link` via `http_endpoint`; identical 401 for all invalid cases; 503 on table errors.
- [ ] `backend/tests/**` -- `test_story_1_7_*` for every matrix row, incl. a check that no captured log/span contains the token or hash, and that the supplier-api import graph has no PostgreSQL driver.
- [ ] `web/supplier/src/**` -- fragment token reader (reads `location.hash` once; token held in memory only), client header, Upload home, Link not working, skeleton + waking-up; Vitest per screen and state; a11y SCREENS updated.

**Acceptance Criteria:**
- Given `ci/checks.sh all`, when it runs, then it exits 0 with the new tests and the supplier bundle still ≤ 150 KB gzip.

## Design Notes

PartitionKey = first 2 hex chars of the hash, RowKey = full hash (spreads load, single-point lookups). The page keeps the token in memory only; it does not write it to storage.

## Verification

**Commands:**
- `ci/checks.sh all` -- expected: exit 0

## Implementation Notes

- Implemented by a coding subagent (2026-09-29). Registry read side (`ports/links.py`, `adapters/table_links.py`, azure-data-tables 12.7.0), filtered query instead of a point read so the hash never appears in an SDK-logged URL path; `GET /api/link` with one identical 401 `LINK_NOT_VALID`; 503 `SERVICE_UNAVAILABLE` on table errors; supplier SPA screens Upload home, Link not working, Loading (skeleton → "Waking up" at 3 s), LinkError (retryable). Shared web files kept in step with `web/staff`.

## Plan Change Log

## Review Triage Log

**Pass 1 (2026-09-29): blind-hunter, edge-case-hunter, verification-gap, intent-alignment.** Counts: high 0, medium 10, low 11, false 1, maybe-false 0.

| # | Finding | Verdict | Route | Evidence / action |
|---|---------|---------|-------|-------------------|
| 1 | `/api/link` that never answers leaves "Waking up" forever (B, E1, intent) | medium | patch | Client timeout (20 s) ends in the retryable LinkError with Try again. |
| 2 | Corrupt registry row → unplanned 500 (B, E8) | medium | patch | Adapter logs a code (no hash) and raises `ServiceUnavailableError`; route test. |
| 3 | Permanent auth/config table errors look transient (E7) | low | patch | Same 503 to the supplier; distinct logged code for ops. |
| 4 | `issued_at`/`revoked_at` stored as ISO strings by 1.6 would break every resolve (E9) | medium | patch | Accept `datetime` or ISO string. |
| 5 | Padded `supplier_name`, missing `supplier_id` give opaque errors (E10) | low | patch | Strip name; explicit error for missing id. |
| 6 | 200 body without a string `supplier_name` renders an empty name (E2) | medium | patch | Treat as generic error. |
| 7 | 401 `LINK_NOT_VALID` dispatches `SESSION_EXPIRED` (E4, VG other) | medium | patch | Shared client skips the event for `LINK_NOT_VALID`; test in the shared client test. |
| 8 | Invalid token kept after a 401 (E5) | low | patch | Clear it. |
| 9 | Pasting a new link into the same tab is ignored (B2, E6) | medium | patch | Reload on `hashchange`. |
| 10 | Loading screen has no heading/title; LinkError title mismatch and double announcement; live region inside `aria-busy` (B6, B7, B8, E11, E12) | medium | patch | Title per state, `aria-busy` on the skeleton only, no focused heading inside the alert. |
| 11 | 503 lacks `Retry-After`; 401 lacks `WWW-Authenticate` (B10) | low | patch | Add both. |
| 12 | Shared client test doesn't cover `setUploadToken` (B11) | low | patch | Add to the shared `client.test.ts`. |
| 13 | `skeleton.tsx` in neither shared nor app-specific list (B12) | low | patch | List as supplier-only. |
| 14 | "PostgreSQL stopped" test name overstates it (B13) | low | patch | Rename; the import test is the guarantee. |
| 15 | e2e token not canonical base64url (B14) | low | patch | Use a canonical synthetic token. |
| 16 | supplier-api registry construction args never asserted (VG1) | medium | patch | Assert account and client id; assert the credential's client id. |
| 17 | Comments claim the token is "memory only" / "never in a URL" (B1, claim) | low | patch | Correct the comments. Decision: keep the fragment so reload/bookmark work; it never reaches the server. |
| 18 | 56px capture-button minimum not checked when rendered (VG2) | low | defer | Add with Story 1.8 when the buttons are wired. |
| 19 | "Waking up" can't show during a host cold start because the same app serves the page (intent a) | medium | defer | Architecture limit (AD-14 accepts a few seconds' first load); raised to Dj. |
| 20 | Upload buttons do nothing yet (B9) | low | reject | Stories 1.8/1.9 wire them before suppliers use the page. |
| 21 | StrictMode double request in dev (E13) | low | reject | Dev only; aborted request filtered. |
| 22 | Unexpected client exceptions shown as generic (E3) | low | reject | Correct user outcome. |
| 23 | No Jira/status change in the diff (B last) | false | reject | Status and Jira are handled by the build workflow outside the diff. |
