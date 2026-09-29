---
title: 'Story 2.8: Admin queue list'
type: 'feature'
ticket: '2-8-admin-queue-list'
created: '2026-09-30'
status: 'built'
route: 'full'
route_source: 'auto'
baseline_revision: '35ba8fbfa5a824a01a3ff4b7721a189f6f243cda'
review: 'thorough'
review_source: 'auto'
lenses_ran: ['edge-case-hunter', 'verification-gap']
review_loop_iteration: 0
context:
  - '{project-root}/docs/standards/coding-style.md'
  - '{project-root}/docs/standards/security.md'
  - '{project-root}/docs/standards/terraform.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Invoices routed to `in_admin_queue` are invisible: the admin's `/queue` surface is a placeholder and staff-api cannot read the database.

**Approach:** Give staff-api its database connection and settings, add `GET /api/admin/queue` (admin only) returning the open-reason invoices oldest first with paging, filters and this month's DI page usage, and build the `/queue` screen in `web/staff`: the table with reason chips, filters, empty state and the 80 % page-cap Alert.

## Boundaries & Constraints

**Always:** admin role only (`Surface.ADMIN_QUEUE`), 401/403 from the existing guards; open reasons = `admin_item` rows of the invoice's latest `routing_id` (AD-4); amount = current `invoice_total` (AD-18 current-value function) as a 2-decimal string plus currency, `null` without a run; sort `invoice.created_at` ascending then `id`; 50 per page; SQL through Core with bound parameters; no field values in logs; UI copy in `strings.ts`, tokens from `index.css`, shadcn Table/Badge/Alert unchanged; API calls only through `src/api/`.

**Never:** the item screen or its 404 (2.9); admin actions (2.10); keyboard shortcuts (2.11); infinite scroll; any write from this endpoint; more than **3** new test cases.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| List | invoices in `in_admin_queue` (and others) | only queued ones: id, received (`created_at`), supplier name, amount+currency, open reason codes; oldest first | — |
| Open reasons | invoice routed twice | chips from the latest `routing_id` only | — |
| No amount | invoice with no extraction run | amount `null`, row still listed | — |
| Paging | 51 queued | page 1 has 50, page 2 has 1, `total` 51 | page < 1 or non-integer → 400 `VALIDATION_FAILED` |
| Filters | `reason=BANK_CHANGED`, `supplier_id=<uuid>` | only matching invoices (reason among open reasons) | unknown reason / bad uuid → 400 |
| Page usage | month pages ≥ 80 % of cap | response carries `{pages_used, page_cap}`; UI Alert "322 of 400 pages used this month." | below 80 % → `null`, no Alert |
| Empty | nothing queued | UI "Nothing waiting. New exceptions appear here automatically." | — |
| Non-admin | finance/goods_in principal | 403 | no data read |
| Signed out | no principal | 401 | — |
| DB down | connection fails | 503 `DB_OFFLINE` (existing mapping) | — |
| Keyboard | table | supplier name is a real link to `/queue/<id>`; clicking elsewhere on the row opens it too | — |

</frozen-after-approval>

## Code Map

- `backend/src/invoicing/apps/staff_api/function_app.py`, `me.py` -- route pattern (`@app.route(route="api/...")`, endpoint built at load); SPA catch-all stays last.
- `backend/src/invoicing/apps/staff_api/settings.py` -- add `postgres_host/database/user` (types like `apps/pipeline/settings.py`), `di_monthly_page_cap: int = Field(gt=0)`, `invoice_currency` (default SGD).
- `backend/src/invoicing/apps/pipeline/function_app.py` (lines ~56-61) -- engine wiring to mirror (`postgres_engine(..., password=entra_token_provider(identity))`); `adapters/postgres/engine.py` `open_connection` maps connect failure to `DatabaseOfflineError`; use a small pool.
- `backend/src/invoicing/adapters/principal.py` -- `staff_endpoint(handler, surface=Surface.ADMIN_QUEUE, ...)`; `domain/roles.py`; `domain/errors.py` (`ValidationFailedError`).
- `backend/src/invoicing/adapters/http.py` -- `json_response`, error shape.
- `backend/src/invoicing/adapters/postgres/schema.py` -- `invoice`, `admin_item`, `extraction_run`, `invoice_field`, `di_usage`; `adapters/postgres/validation.py` (`_runs`, `_field`) row-building example; `domain/current_values.py`.
- `backend/src/invoicing/adapters/postgres/suppliers.py` -- `supplier_names(connection, ids)`.
- `backend/src/invoicing/adapters/postgres/extraction.py` -- `utc_month()`.
- `backend/migrations/versions/0006_validation.py` -- latest; new `0007_staff_queue.py` grants staff role SELECT on `intake.di_usage` (downgrade revokes).
- `infra/modules/env-app/main.tf` (`app_specific_settings.staff_api`), `variables.tf`, `infra/{dev,prod}/app/*`, their tftests -- add staff-api `POSTGRES_*`, `DI_MONTHLY_PAGE_CAP`, `INVOICE_CURRENCY` settings like pipeline's.
- `backend/tests/conftest.py` -- `APP_ONLY_SETTINGS["staff_api"]`, `login_engine(server, server.staff_api, db)`; `tests/apps/test_staff_me.py` (`header(*roles)`, `load_app`); `tests/apps/_validation_seed.py`.
- `web/staff/src/api/client.ts`, `api/me.ts` -- API client pattern; add `api/queue.ts`.
- `web/staff/src/App.tsx`, `surfaces.ts` (`admin_queue` → `/queue`, `admin_item` → `/queue/:invoiceId`), `screens/SurfacePage.tsx`, `router.ts` (pathname only) -- render the queue screen for `admin_queue`.
- `web/staff/src/strings.ts` (`reasonLabels`, add queue copy), `index.css` tokens; add shadcn `components/ui/table.tsx`, `badge.tsx`, `alert.tsx`. Blocking chips (`BANK_CHANGED`, `SUPPLIER_ID_MISMATCH`) use the destructive variant with an icon (DESIGN.md).
- `web/staff/e2e/screens.ts`, `e2e/a11y.spec.ts` -- the existing 2.7 admin screen must stub `/api/admin/queue`; `ci/tests/test_web_apps_in_step.py` staff-only file list.

## Tasks & Acceptance

**Execution:**
- [x] staff-api settings + engine + Terraform settings and tftest asserts (no new `run` blocks).
- [x] `backend/src/invoicing/ports/admin_queue.py` + `adapters/postgres/admin_queue.py` -- one read: queued invoices with latest-routing reasons, supplier names, current `invoice_total`, total count, filters, paging; and this month's `di_usage.pages`.
- [x] `backend/src/invoicing/apps/staff_api/queue.py` + route -- parse/validate query (`page`, `reason`, `supplier_id`), respond `{items:[{invoice_id, received_at, supplier_id, supplier_name, amount, currency, reasons}], page, page_size, total, page_usage}`.
- [x] `backend/migrations/versions/0007_staff_queue.py`.
- [x] `web/staff`: `api/queue.ts`, `screens/QueueScreen.tsx` (table, reason chips with labels, age, filters, pagination controls, empty state, page-cap Alert, row click + supplier link), wired in `App.tsx`; strings; shadcn Table/Badge/Alert.
- [x] Tests (≤ 3 new cases): one backend DB test `tests/apps/test_story_2_8_admin_queue.py` (list/order/latest routing/no amount/paging/filters/page usage/403/401/400); one Vitest `QueueScreen.test.tsx` (rows render in API order with labels, filter change refetches, empty state, Alert, link + row click); a11y: extend the existing 2.7 admin screen stub with a populated queue, no new Playwright case.

**Acceptance Criteria:**
- Given `ci/checks.sh all`, then it passes with ≤ 200 test cases, backend ≥ 80 % and web ≥ 60 % coverage, and the a11y check passes.

## Implementation Notes

- `HostName`, `PgName` and `CurrencyCode` moved from `apps/pipeline/settings.py` to `apps/common.py`, so staff-api's settings don't import another app.
- Latest routing = greatest `routing_id` (UUIDv7, AD-4), in SQL; the reason filter's subquery is correlated to the `admin_item` row (a subquery correlated to `invoice` two levels up did not correlate).
- `currency` is `null` whenever `amount` is `null`.
- Review fixes: the response also carries `suppliers` (every queued invoice's supplier, ignoring the filters, by name), which the supplier filter's options come from; the read runs in one REPEATABLE READ read-only transaction; `queue_endpoint`'s `platform_auth_trusted` has no default; an empty page past the end jumps back to the last page; Previous/Next are disabled while loading; a 401 or `DB_OFFLINE` shows no local error (the shell's screens take over).
- While another page or filter loads, the last answer stays on screen (`aria-busy` on the table), so the pagination buttons keep focus.
- `App.test.tsx`'s `signedInAs` now answers `/api/admin/queue` with an empty queue (no new case).

## Plan Change Log

## Review Triage Log

Pass 1 (2026-09-30, unattended). Lenses one at a time: edge-case-hunter, verification-gap. Verdicts: high 1, medium 7, low 4, false 5.

| # | Lens | Finding | Verdict | Route | Evidence |
|---|------|---------|---------|-------|----------|
| E1 | edge | Count, page, reasons and runs read in separate statements without one snapshot | low | patch | a concurrent routing between statements mismatches total/rows; REPEATABLE READ on the read connection is a one-line fix |
| E2 | edge | Pool exhaustion blocks 30 s then 500 | low | reject | one or two admins; pool 4 |
| E3 | edge | Queued invoice without admin_item rows shows no chips | false | reject | `route_to_admin` always writes at least one item (it refuses an empty reason list) |
| E4 | edge | Duplicate reason codes in one routing → duplicate React keys | false | reject | `route_to_admin` de-duplicates by reason |
| E5 | edge | Page > 1 returns no items while total > 0: stranded on "Nothing waiting" | medium | patch | the last item on the last page is resolved, or Next overshoots |
| E6 | edge | Next stays enabled while the next page loads | low | patch | stale `data.page`; disable while loading |
| E7 | edge | page_size 0 → NaN pages | false | reject | server always sends 50 |
| E8 | edge | Supplier filter offers only suppliers already seen | medium | patch | options accumulate from loaded rows; the API returns the queue's distinct suppliers instead (response gains `suppliers`) |
| E9 | edge | 401/503 render a second error under the shell's own screen | low | patch | the client already raises SESSION_EXPIRED/OFFLINE events; skip the local error for them |
| E10 | edge | Currency from config, not invoice_field | false | reject | AD-8: currency is configuration; extract writes the same value |
| E11 | edge | NaN / huge Numeric → 500 | low | reject | DI numbers parse as finite Decimals into numeric columns |
| E12 | edge | Rows without open reasons | false | reject | see E3 |
| V1 | gap | Registered route's `platform_auth_trusted` wiring unverified; default True | high | patch | dropping the argument serves a forged principal when built-in auth is off; make it required and call the registered handler with auth untrusted → 401 AUTH_DISABLED |
| V2 | gap | 80 % boundary not pinned | medium | patch | 319 and 322 don't catch `>` vs `>=`; use 320 |
| V3 | gap | Error state and Try again untested | medium | patch | every mocked queue answer is 200 |
| V4 | gap | "No match" empty state untested | medium | patch | filtered empty answer never mocked |
| V5 | gap | Blocking chip marking unasserted | medium | patch | no assertion on "Blocking:" text |

## Design Notes

Decisions made unattended (Dj asleep, 2026-09-30):
- **"received" is `invoice.created_at`** (no separate column); age is shown relative to it.
- **Filters are reason and supplier** as the story says (EXPERIENCE.md mentions age; sort already covers it).
- **Filter/page state lives in the screen**, not the URL (the router tracks the pathname only).
- **403 for non-admins on the queue API**; the per-item 404 belongs to 2.9's item route.
- **Page usage is returned only at ≥ 80 %**, so the client never computes the threshold.

## Verification

**Commands:**
- `ci/checks.sh all` -- expected: all checks pass, test cases ≤ 200.
