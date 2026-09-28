---
title: 'Story 1.4: React web app skeletons'
type: 'feature'
ticket: '1-4-react-web-app-skeletons'
created: '2026-09-29'
status: 'built'
baseline_revision: 'fe4b9607c5f2c1bb9789d716b9932fd9c2b1e336'
route: 'full'
route_source: 'auto'
review: 'thorough'
review_source: 'auto'
lenses_ran: ['blind-hunter', 'edge-case-hunter', 'verification-gap', 'intent-alignment']
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-ocrinvoicing-2026-09-28/DESIGN.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-ocrinvoicing-2026-09-28/EXPERIENCE.md'
  - '{project-root}/docs/standards/coding-style.md'
  - '{project-root}/docs/standards/security.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `web/supplier` and `web/staff` are empty stubs, and the Function apps don't serve them. Every screen story needs both SPAs scaffolded on the agreed tokens, strings module and API client, served from their API app's origin with security headers, and held to the accessibility and bundle-size floors in CI.

**Approach:** Scaffold both apps (Vite + React + TypeScript + Tailwind + shadcn/ui) with tokens as CSS variables, one strings module, one `src/api/` client, lint rules, Vitest tests, an automated axe + layout check, and a bundle-size check; add an SPA-serving route to `supplier-api` and `staff-api`; wire everything into `ci/checks.sh` and the code deploy. Verify offline.

## Boundaries & Constraints

**Always:** Versions from the spine Stack table (React 19.3.0, Vite 8.3.1, TypeScript 6.0.3), all dependencies pinned exactly with committed `package-lock.json`. Node 22. Each app: `<html lang="en">`, a "Babaloo" text header, tokens from DESIGN.md as CSS variables (UX-DR1: `success`, `warning`, `flag`, `flag-fill`, `flag-halo`, `confidence-low`, `destructive #B91C1C`, `tap-min 48px`, `supplier-gutter`, `body-supplier` 16px, `numeric` tabular figures, 2px focus ring with 2px offset). One strings module per app with the 12 AD-4 reason labels and the status labels exactly as EXPERIENCE.md words them (UX-DR2). One API client in `src/api/`: sends `X-Requested-With: XMLHttpRequest`, emits a session-expired event on 401 and an offline event on 503 `DB_OFFLINE` (UX-DR3). Scripts `lint`, `format:check`, `typecheck`, `test` (Vitest with `@vitest/coverage-v8`), `build`, plus the a11y check (1.2 contract). Web coverage ≥ 60%. Supplier JS ≤ 150 KB gzipped (UX-DR22). Security headers per security.md rule 25 and `Cache-Control: no-store` on API responses; the SPA shell may be cached only with revalidation.

**Never:** Screens or business rules (later stories), inline scripts (CSP self), `dangerouslySetInnerHTML`, direct `fetch` outside `src/api/`, hard-coded colours, CORS, calls to Azure.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| API call | Any client call | Request carries `X-Requested-With: XMLHttpRequest`, same-origin credentials | — |
| Session expired | API returns 401 | `session-expired` event fired; call rejects | — |
| DB offline | API returns 503 with `code: DB_OFFLINE` | `offline` event fired; call rejects | Other 503s are ordinary errors |
| Error body | Non-2xx with `{code, message, correlation_id}` | Typed error with code and correlation id | Non-JSON body → generic error |
| Hard-coded colour | A component uses `#fff`, `rgb()` or a Tailwind arbitrary colour | Lint fails | — |
| Direct fetch | A component calls `fetch` | Lint fails | Allowed only in `src/api/` |
| Accessibility | Built app shell at 320px and desktop | axe finds no WCAG 2.2 AA violations; no horizontal scroll at 320px; interactive targets ≥ 48px | Violation fails the check |
| Bundle size | Supplier build | Gzipped JS ≤ 150 KB, else the check fails naming the size | — |
| SPA route | `GET /` or an unknown client path on supplier-api/staff-api | `index.html` with security headers | `/api/*` never falls through to the SPA |
| Static asset | `GET /assets/<hashed>.js` | File with the right content type | Path traversal (`..`) → 404 |
| Coverage floor | A web app whose tests cover < 60% | `ci/checks.sh test` fails naming the % (1.2 deferral) | — |

</frozen-after-approval>

## Code Map

- `web/supplier/package.json`, `web/staff/package.json` -- stubs from 1.1; replace with the full scaffold.
- `ci/checks.sh`, `ci/lib.sh` -- web is "scaffolded" once `package.json` has scripts; then `lint`, `format:check`, `typecheck` and Vitest with coverage ≥ 60% are required; `npm audit --omit=dev` runs per app. Add the a11y and bundle-size checks here.
- `ci/tests/test_checks_matrix.py` -- add the deferred web coverage-floor fixture test.
- `ci/code-deploy.sh` -- already builds `web/<app>` into the zip's `static/` (1.3); keep in step with the build output folder.
- `backend/src/invoicing/adapters/http.py` -- `SECURITY_HEADERS`, `http_endpoint`; reuse for the SPA route.
- `backend/src/invoicing/apps/{supplier_api,staff_api}/function_app.py` -- add the SPA route.
- `shared/quality/`, `shared/quality-thresholds.json` -- Vite alias `@shared` target for later stories (1.9); configure the alias now.
- DESIGN.md Colors/Typography/Layout, EXPERIENCE.md reason-label and status-label tables -- source of tokens and copy.

## Tasks & Acceptance

**Execution:**
- [ ] `web/{supplier,staff}/` -- Vite + React + TS + Tailwind + shadcn/ui scaffold (components.json, `cn` util, Button), `index.html` with `lang="en"`, app shell with "Babaloo" header, tokens CSS, `@shared` alias, ESLint (typescript-eslint, react-hooks, no-restricted fetch, no hard-coded colours), Prettier, strict tsconfig, pinned deps + lock.
- [ ] `web/*/src/strings.ts`, `web/*/src/api/` -- strings (reason + status labels) and client with events; Vitest tests for every API matrix row and the label tables.
- [ ] `web/*/e2e/` or `ci/` a11y check -- Playwright + `@axe-core/playwright` against `vite preview`: axe WCAG 2.2 AA, 320px reflow, 48px targets; wired into `ci/checks.sh` (tools installed in CI).
- [ ] `ci/checks.sh` + `ci/lib.sh` -- a11y and supplier bundle-size (≤ 150 KB gzip) checks; tests for failure paths.
- [ ] `backend/src/invoicing/adapters/static.py` + both `function_app.py` -- SPA route serving `static/` (index fallback, content types, no traversal, security headers, `/api/*` excluded); backend tests.
- [ ] `ci/tests/test_checks_matrix.py` -- web coverage < 60% fixture fails.

**Acceptance Criteria:**
- Given both apps, when `ci/checks.sh all` runs, then lint, typecheck, tests with ≥ 60% coverage, a11y and bundle-size checks pass.
- Given `ci/code-deploy.sh --build-only dev`, when it runs, then the supplier-api and staff-api zips contain the built SPA and the backend serves it in tests.

## Design Notes

Playwright runs Chromium only, installed by `npx playwright install --with-deps chromium` in CI; locally the check skips with a clear message when browsers are missing, and fails under `TF_BUILD`. The SPA route is a catch-all anonymous route registered after `/api/*` routes; Functions reserves `/api`, so the catch-all uses `route_prefix` handling as the host requires (e.g. `host.json` `extensions.http.routePrefix: ""` with explicit `api/` on API routes) — keep `/api/health` unchanged.

## Verification

**Commands:**
- `ci/checks.sh all` -- expected: exit 0
- `ci/code-deploy.sh --build-only dev` -- expected: zips contain `static/index.html`

## Implementation Notes

- Implemented by a coding subagent (2026-09-29). Tailwind 4.3.3; Tailwind default palette removed (token colours only); Button ≥ 48px at every size; custom ESLint rules (no hard-coded colours, no fetch/XHR outside `src/api/`, no `dangerouslySetInnerHTML`); `vite preview` sends the CSP for the a11y run; `routePrefix: ""` with `api/health` and a last-registered `{*path}` SPA catch-all; jsdom pinned 29.1.1 (Node 22.19 here).
- Overnight decision: focus ring darkened to zinc-600 for WCAG 2.2 AA non-text contrast (DESIGN.md's inherited zinc-400 is ~2.5:1).

## Plan Change Log

## Review Triage Log

**Pass 1 (2026-09-29): blind-hunter, edge-case-hunter, verification-gap, intent-alignment.** Counts: high 1, medium 10, low 9, false 1, maybe-false 0.

| # | Finding | Verdict | Route | Evidence / action |
|---|---------|---------|-------|-------------------|
| 1 | With `routePrefix ""`, the host reserves `admin/*` and `runtime/*`, so SPA deep links there never reach the catch-all (B1) | high | patch | Tests use `admin/queue` only because they call the handler directly. Client routes must avoid those prefixes: document, test, change the test path; Story 2.8 must not use `/admin/...`. |
| 2 | `_is_api` is case-sensitive; `/API/unknown` gets 200 index.html (VG other, B2, E1) | medium | patch | Compare lower-cased; add cases. |
| 3 | Client routes with a dotted last segment get a 404 (B3, E2) | medium | patch | Treat as asset only for known extensions or `assets/`. |
| 4 | Directory paths get the shell (E3) | low | patch | 404 when the candidate is a directory. |
| 5 | Success path of `apiRequest` throws raw `SyntaxError` on non-JSON 2xx (B4, E4) | medium | patch | Map to `ApiError(generic)`. |
| 6 | Custom abort / timeout reported as a network failure (B5, E5) | medium | patch | Rethrow `signal.reason` when aborted. |
| 7 | Nothing shows the session-expired / offline notices (B6) | medium | patch | UX-DR3 maps them to the dialog/notice. Staff shell subscribes and renders them in live regions; supplier keeps the events (its 401 copy is Story 1.7's). |
| 8 | Preview CSP is a hand copy of the backend CSP; no parity test (VG1, B7) | medium | patch | One source (`shared/security-headers.json`) read by `http.py` and both vite configs, plus a test. |
| 9 | The two web apps are near-verbatim copies with no drift guard (B8) | medium | patch | Add a CI check that the shared files stay identical. |
| 10 | a11y target check flags inline text links and sr-only skip links; scroll-padding `auto` passes as NaN (B9, E7, E8) | medium | patch | Exempt inline text links and visually hidden unfocused elements; treat NaN as a failure; add negative tests for scroll padding and text spacing. |
| 11 | No test that a failing `a11y` script fails `checks.sh test`; failed `npm ci` cascades; failed Playwright install gives a misleading second error (B10, B12, E10) | low | patch | Add the test; gate later steps on `npm ci`; stop after a failed install. |
| 12 | Hard-coded named colours slip past the lint rule via quoted keys, JSX expressions, unlisted props (E9) | medium | patch | Widen the rule; tests. |
| 13 | `statusLabel` returns `undefined` for an unknown status (E6) | low | patch | Fall back to a neutral label. |
| 14 | `bundle_size` needs system `python3`, undocumented; README Chromium step names only `web/supplier` (B11, B14) | low | patch | Run through `uv run python`; fix README. |
| 15 | "Registered last" test/comment implies registration order decides routing (B10 part) | low | patch | Fix the comment: literal routes win by precedence; keep the order test as a guard. |
| 16 | Focus ring below 3:1 (implementer risk) | medium | patch | Overnight decision: `ring` = zinc-600. |
| 17 | a11y runs against `vite preview`, not the Functions static path (intent audit, B7 part) | medium | reject | Offline scope; CSP parity is closed by row 8; the static adapter has its own tests. |
| 18 | No ETag/Last-Modified; no HEAD; blocking `resolve()`/`is_file()` (B13) | low | reject | Small shell; health probes use `/api/health`. |
| 19 | `assets/%00.js` case proves nothing (B10 part) | low | reject | Traversal is covered by the other cases. |
| 20 | `package-lock.json` not in the diff (B14, intent) | false | reject | Both exist; my diff excluded lock files. |
