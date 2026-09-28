---
title: 'Story 2.7: Staff sign in and see only their surfaces'
type: 'feature'
ticket: '2-7-staff-sign-in-and-see-only-their-surfaces'
created: '2026-09-29'
status: 'built'
baseline_revision: '419fb13b0f564057e2a6ebb2f374f47d67f618eb'
route: 'full'
route_source: 'auto'
review: 'thorough'
review_source: 'auto'
lenses_ran: ['blind-hunter', 'edge-case-hunter', 'verification-gap', 'intent-alignment']
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-ocrinvoicing-2026-09-28/EXPERIENCE.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-ocrinvoicing-2026-09-28/ARCHITECTURE-SPINE.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Anyone who can reach `staff-api` gets the same empty shell; there is no sign-in, no role model and no per-role navigation. Staff need Entra sign-in with assignment required, a sidebar and landing page per role, and the API must enforce roles itself.

**Approach:** Terraform built-in auth (auth v2) on `staff-api` pointing at the bootstrap's `staff-api` app registration (ID tokens, no secret, `SameSite=Lax`, unauthenticated API calls get 401, browser navigation redirects to login); a domain role model + route guard reading the `X-MS-CLIENT-PRINCIPAL` header; `GET /api/me`; the staff SPA shell with role-filtered sidebar (Sheet below 1024 px), landing by role order, access-denied redirect, session-expired dialog, offline notice, waking-up state, unique titles and focus on `h1`. Surfaces are placeholders until their stories. Verify offline.

## Boundaries & Constraints

**Always:** Roles `admin`, `finance`, `procurement`, `management`, `goods_in` (AD-14); a user with several roles sees the union; landing = first role in that order (UX-DR8). Surfaces and routes per EXPERIENCE.md's staff surface table, never under `admin/` or `runtime/` (1.4 decision: e.g. `/queue`). The API trusts only the built-in auth principal header (`X-MS-CLIENT-PRINCIPAL`, base64 JSON claims) — it's injected by the platform and stripped from client requests; roles come from `roles` claims. Every staff route except `/api/health` requires a principal (401 otherwise) and checks its role in the domain layer (403 → the SPA shows "You don't have access to that page." after redirecting home). `GET /api/me` returns `{name, roles}` only (no oid/email in logs). `DB_OFFLINE` 503 mapping already exists (1.3); the SPA shows the full-page offline notice with working hours (UX-DR20); 401 shows "Your session ended. Sign in again to continue." dialog linking to `/.auth/login/aad`. Skeleton rows, then "Waking up, one moment…" after 3 s. Titles "<Surface> – Babaloo", focus to `h1` on route change. Terraform: `azapi` for `authsettingsV2` where azurerm lacks it for Flex (with a comment), `requireAuthentication`, `unauthenticatedClientAction` = `RedirectToLoginPage` for pages and 401 for `X-Requested-With` calls (AD-14), `openIdIssuer` single tenant, client id from a variable fed by the bootstrap output, token store off; README operator step for the redirect URI (AD-17 step 8). Accessibility floor and drift guard between apps still pass.

**Never:** Real surface content (2.8+, 3.x, 4.x, 5.x). A client secret. Trusting role claims from anywhere but the platform header. Calling Azure.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| No principal | API call without the header | 401 `UNAUTHENTICATED` | — |
| Malformed principal | Header not base64/JSON | 401 | Logged by code only |
| `/api/me` | Principal with roles admin+finance | `{name, roles:["admin","finance"]}` | — |
| Role guard | finance user calls an admin-only route | 403 `FORBIDDEN` | — |
| No known role | Principal with no app roles | `/api/me` returns empty roles; SPA shows a "no access" page | — |
| Sidebar union | admin+goods_in | Both roles' surfaces, landing on admin home | — |
| Route outside roles | goods_in user opens `/queue` | Redirect home + inline Alert | — |
| 401 in SPA | Any call 401 | Session-ended dialog | — |
| 503 DB_OFFLINE | Any call | Full-page offline notice | — |
| Waking up | `/api/me` slow | Skeleton, then waking-up text after 3 s | — |
| Narrow viewport | < 1024 px | Sidebar becomes a Sheet | — |
| Route change | Navigate | Unique title, focus on `h1` | — |

</frozen-after-approval>

## Code Map

- `backend/src/invoicing/adapters/http.py` (`http_endpoint`, error mapping, `trust_caller_correlation_id`), `domain/errors.py` -- add `UNAUTHENTICATED` 401, `FORBIDDEN` 403.
- `backend/src/invoicing/apps/staff_api/{function_app.py, settings.py}` -- add `api/me`; staff-api honours caller correlation ids.
- `infra/modules/env-app/main.tf` + `infra/{dev,prod}/app` -- staff-api site; add auth settings; client id variable (bootstrap `app-registrations.sh` creates `babaloo-sea-lng-staff-api-<env>`).
- `infra/bootstrap/README.md` -- step 8 redirect URI.
- `web/staff/src/{App.tsx, strings.ts, api/client.ts}` -- shell exists with session/offline notices (1.4); extend to router, sidebar, dialog, landing; keep shared files identical with `web/supplier` where listed in the drift guard.
- `web/staff/e2e/screens.ts` -- add shell states.

## Tasks & Acceptance

**Execution:**
- [x] `backend/src/invoicing/domain/roles.py` + `adapters/principal.py` -- role enum, surface→roles map, guard; principal header parsing; tests.
- [x] `backend/src/invoicing/apps/staff_api/{function_app.py, me.py}` -- `GET /api/me` with the guard; tests for every API row.
- [x] `infra/modules/env-app` + roots + README -- built-in auth v2; tests.
- [x] `web/staff/src/**` -- router, role-filtered sidebar/Sheet, landing, access-denied alert, session dialog, offline page, waking-up, titles/focus; Vitest; e2e screens.

**Acceptance Criteria:**
- Given `ci/checks.sh all`, when it runs, then it exits 0.

## Verification

**Commands:**
- `ci/checks.sh all` -- expected: exit 0

## Implementation Notes

- Implemented by a coding subagent (2026-09-29). `domain/roles.py`, `adapters/principal.py` (`X-MS-CLIENT-PRINCIPAL`), `GET /api/me`, `authsettingsV2` via azapi on staff-api (no secret, token store off, `/api/health` excluded), `staff_api_client_id` variable, staff SPA shell (in-house router, native `<dialog>` for the session dialog and Sheet), README step 8. `UNAUTHORIZED` renamed `UNAUTHENTICATED`.

## Plan Change Log

## Review Triage Log

**Pass 1 (2026-09-29, time-boxed before the 06:50 stop): blind-hunter, edge-case-hunter, verification-gap (report not received in time), intent-alignment.** Counts: high 2, medium 12, low 8.

| # | Finding | Verdict | Route | Evidence / action |
|---|---------|---------|-------|-------------|
| 1 | Principal header trusted even if built-in auth is off; `auth_typ` unchecked (B1) | high | patch | Fail closed in Azure unless `WEBSITE_AUTH_ENABLED`; require `auth_typ == aad`. |
| 2 | Expired session answered with a 302 → CORS failure, not the session dialog (E8, intent) | high | patch | `redirect: "manual"`, opaque redirect = 401. |
| 3 | 16 KB principal cap vs users in many groups (B2) | medium | patch | No group claims on the registration; 64 KB cap. |
| 4 | Not-allowed alert survives reload/back; stale on same-path click (B3, E4, E5) | medium | patch | One-shot flag. |
| 5 | Later 401 closed with Esc leaves no sign-in path (B4) | medium | patch | Switch to signed-out. |
| 6 | Open Sheet traps the page when widened ≥ 1024 px; native close leaves React open (B5, E1) | medium | patch | Close on media-query change; handle `onClose`. |
| 7 | No user name or sign-out (B6) | medium | patch | Name + `/.auth/logout` link. |
| 8 | Alerts mounted already filled may not be announced (B7) | medium | patch | Persistent live region. |
| 9 | `WWW-Authenticate: Bearer` wrong and shared; web tests use old code (B9, B10) | low | patch | Drop the header; update tests. |
| 10 | Session lifetime unpinned (B12) | low | patch | `cookieExpiration` 8 h fixed; test. |
| 11 | Route guards bypass `SURFACE_ROLES`; empty role set → 403 for all (B15, E9) | medium | patch | `surface=`; refuse empty sets at wiring. |
| 12 | `returnTo` starting `//`; `TimeoutError` message; `RecursionError` → 500 (E7, E3, E10) | low | patch | Guards. |
| 13 | SignedOut title vs h1; mixed test (B14) | low | patch | Match; split. |
| 14 | README: no unassigned-user check; `/api/me` DB-free; required client id (B8, B11, B13, E11) | low | patch | README notes. `staff_api_client_id` stays required (Dj fills tfvars before the next pipeline run). |
| 15 | SameSite=Lax not set; XHR 401 vs redirect assumed (intent, E12, E13) | medium | defer | Platform has no SameSite setting; both confirmed on the first Dev deploy (README step 8). |
| 16 | DB_OFFLINE with a non-503 status (E2) | low | reject | Backend maps DB_OFFLINE to 503 only. |
| 17 | Query string dropped on landing redirect (E6) | low | reject | No surface uses query strings yet. |
