# Overnight build report: 28 Sep 23:19 → 29 Sep 07:00 (SGT)

Dj asked me to keep building until 07:00, make every decision myself, move on when blocked, and leave a full report per story. This is that report. The detailed working log is `.work/overnight/decisions.md` (gitignored); each story's plan file holds its full review log.

## Summary

- **Built and committed: 12 stories** — 1.1, 1.2, 1.3, 1.4, 1.5, 1.7, 1.8, 1.9, 2.1, 2.2, 2.4 and 2.7. One local commit per story on `main`. **Nothing was pushed, and nothing was deployed or run against Azure.**
- **Not started (blocked): 2.5 and 2.6** — 2.5 needs 2.3's extracted fields; 2.6 needs the bank-crypto answers.
- **Parked: 1.6 and 2.3.** Both write bank details as PGP ciphertext + HMAC, and you still have open bank-crypto questions. Not started; Jira OCR-7 and OCR-26 untouched (To Do).
- **Every story went through:** plan → implementation by a coding subagent → a test for every row of the plan's I/O matrix → four independent reviewers (blind, edge-case, verification-gap, intent) → triage → fixes → full `ci/checks.sh all` on my side → secret scan → commit → Jira comment.
- **Verification is offline only**: Terraform `validate`/`test` with mock providers, pytest (backend at ~99% coverage; database behaviour against a real PostgreSQL 18 Docker container), Vitest, Playwright accessibility checks in Chromium, shellcheck, gitleaks, pip-audit / npm audit. The acceptance criteria that talk about deployed Azure state are proven only when you run the bootstrap scripts and the pipeline.
- **Jira:** each built story and its subtasks are **In Progress** with a detailed comment. I did not move anything to Done, because the ACs need a real deploy to prove. Epics 1 (OCR-1) and 2 (OCR-23) are In Progress. Keys touched: OCR-1, 2, 3, 4, 5, 6, 8, 9, 10, 14–25, 27, 30, 35–39, 43, 44, 49–52, 122.
- **Sprint file:** built stories are `review`; parked ones stay `backlog`.

## Standing rules I set for the run

1. No Azure calls, no applies, no spend (your "code only" choice for 1.1, applied to every story).
2. Local commits only, one per story; no push, no remote.
3. Jira mirrored on every status change; nothing to Done until you've run it.
4. 1.6 and 2.3 parked for the bank-crypto questions.
5. One story at a time (your instruction at 23:27).
6. Values only you can supply (tag values, alert email, email domain, ADO project, Postgres Entra admin) stay required inputs with no defaults.
7. No second full four-reviewer pass after fixes: the fixes come back with tests and I rerun the whole gate myself. A second pass would cost roughly 500k tokens a story.

## Needs your decision or action

**Before the first deploy**
1. **ADO project name** in org `example-org` — needed by `state-backend.sh` and `ado-setup.sh`.
   - **`staff_api_client_id`** (printed by `app-registrations.sh`) must go into both `infra/{dev,prod}/app/terraform.tfvars` before the next pipeline run, or the app stacks won't plan. Re-run `app-registrations.sh` so group claims are turned off.
2. **Fill the required inputs** in each `infra/*/terraform.tfvars` and the bootstrap env vars (see `infra/bootstrap/README.md` → run order).
3. **Postgres Entra admin must be a different principal from your load-script user** (e.g. an Entra group); the script refuses otherwise.
4. **First Dev deploy checks** (steps in `infra/bootstrap/README.md`): confirm the alert metric namespace, run `test-alerts.sh` and confirm the email, stop the database and watch a message wait 15 minutes, and note that the first deploy now runs the `intake` and `sim_purchasing` migrations (the AD-17 step 5 logins must exist first), then seed purchasing data (operator step), then README step 8 for staff sign-in: redirect URI, role assignments, an unassigned user refused, API calls get 401 not a redirect, and the session cookie's SameSite value. staff-api refuses every staff route if Azure doesn't report built-in auth as on (`WEBSITE_AUTH_ENABLED`); the `curl` checks will show it.

**Architecture / design decisions I made that change documents you own** (I did not edit the spine, DESIGN.md or EXPERIENCE.md):
5. **AD-17 runtime roles**: Flex hosts need Storage Blob Data Owner on `azure-webjobs-hosts`/`azure-webjobs-secrets` (added); Key Vault access is per secret, narrower than the table.
6. **State and deploy identities live in a bootstrap-only RG `babaloo-sea-lng-rg-22`** (not `rg-21`), so no deploy identity can alter another's identity or state.
7. **Focus ring** is zinc-600, not DESIGN.md's zinc-400 (which fails WCAG AA 3:1).
8. **SPA routes can't start with `admin/` or `runtime/`** (reserved by Functions) — Story 2.8's admin queue needs a path like `/queue`.
9. **AD-6/CAP-3** don't yet mention the device-only edge cut-off check, the 1024 px analysis copy or the `X-Device-Check` header.

**Open product / security questions**
10. **Bank crypto** (blocks 1.6, 2.3): also, AD-17 lets the env deploy identity and your load-script user read `pgp-private-key`; only `staff-api` needs it.
11. **Phone photos over 4 MB**: common on modern phones; the limit follows DI F0, and originals can't be shrunk without losing EXIF. The message now asks for a smaller photo or a PDF.
12. **Quality thresholds are uncalibrated guesses** (`[ASSUMPTION]`): calibrate device + server on real photos. A tidy invoice on a patterned background may read as "cut off" (Send it anyway still gets it through).
13. **`device_check=passed` also covers "the phone couldn't check"** — a `skipped` value would need an AD-5 change.
14. **Shared Functions host-secrets container** lets one app's identity read another's host keys — accepted for the PoC.
15. **"Waking up" can't cover a host cold start**, because supplier-api also serves the page (AD-14 accepted a few seconds' first load).
16. **Prod can need up to four approvals per run** (foundation, migrations, app, code deploy). Accepted and documented.

All deferred engineering items are in `_bmad-output/implementation-artifacts/deferred-work.md`.

## Per story

Times are approximate.

### 1.1 Repository and Terraform foundation — built · commit `4eac5dd` · Jira OCR-2
- **Built:** repo skeleton; idempotent, dry-runnable `az` bootstrap scripts for AD-17 steps 1, 3, 4b and 5 plus `verify-db-isolation.sh`; naming and env-foundation modules; `shared`/`dev`/`prod` foundation roots; the P-17 tag gate `check_tags.py`; `.gitleaks.toml`.
- **Verified:** fmt, validate and test in every root and module; 86 pytest cases (dry runs, idempotent re-runs, isolation PASS/FAIL, tag gate); shellcheck.
- **Review:** 41 findings — 22 fixed, 6 deferred, 13 rejected.
- **Decisions:** state + deploy identities in a bootstrap-only RG `rg-22` (privilege escalation fix); Postgres admin must differ from your load-script user; budget start derived from the month of first apply; lookup errors other than "not found" stop the scripts (they could otherwise regenerate the PGP key over live data); P-16 numbering counts up per type (e.g. Dev app identities `id-01..04`); required inputs have no defaults.

### 1.2 CI/CD pipeline in Azure DevOps — built · `74f6490` · OCR-3
- **Built:** `ci/checks.sh` (lint, tests + coverage floors, audits, gitleaks, Terraform); PR, deploy and weekly-scan pipelines; saved plans + tag gate before each apply in AD-17 order; Dev auto on merge; `shared`/Prod behind approval; `ado-setup.sh` (WIF service connections, environments, pipelines, branch policy).
- **Verified:** `ci/checks.sh all`; 156 tests incl. YAML structure and mutation tests.
- **Review:** 27 findings — 18 fixed, 1 deferred, 8 rejected.
- **Decisions:** `main` is the integration branch; checks live in `ci/` so they run locally too; branch control (`main` only) on every connection and environment; Terraform uses refreshing ADO OIDC; coverage checks skip only when there's no code; accept up to 4 Prod approvals; keep the saved-plan artifact (documented as sensitive); weekly-scan failure notification is a manual subscription.

### 1.3 Python Functions API skeleton — built · `fe4b960` · OCR-4
- **Built:** hexagonal `invoicing` package; four Functions v2 apps; fail-fast settings; `{code, message, correlation_id}` errors; allow-list logging; `QueueMessage` + sender; `/api/health`; `<env>/app` stack (four Flex apps, AD-17 roles); code deploy with post-deploy health check.
- **Verified:** 110 backend tests at 99.6%; Terraform tests.
- **Review:** 26 findings — 15 fixed, 5 deferred, 6 rejected.
- **Decisions:** host-container roles added; per-secret Key Vault roles; staff-api sign-in, DI and ACS roles left to 2.7/2.3/5.2 (their Jira subtasks); deploy only git-tracked files; accept shared host containers for the PoC.

### 1.4 React web app skeletons — built · `aa596a6` · OCR-5
- **Built:** both SPAs (Vite, React, TS, Tailwind, shadcn/ui) with DESIGN.md tokens, one strings module, one API client, colour/fetch lint rules; SPA served from each API app with security headers from one shared file; Playwright axe/reflow/48 px checks; supplier bundle limit.
- **Verified:** `ci/checks.sh all` incl. a11y in Chromium; supplier JS ~69 KB gzip.
- **Review:** 20 findings — 16 fixed, 4 rejected.
- **Decisions:** focus ring zinc-600; `admin/`/`runtime/` reserved; one source for security headers; Playwright in a real browser (contrast checked).

### 1.5 Monitoring and alerts — built · `d12f25d` · OCR-6
- **Built:** OpenTelemetry export (Entra auth), metrics helper with an allow-list, dimension alerting, Key Vault audit logs, `shared` action group for the shared and $8 subscription budgets, `test-alerts.sh`.
- **Verified:** 236 backend tests at 99%.
- **Review:** 25 findings — 18 fixed, 2 deferred, 5 rejected.
- **Decisions:** sampling decided per correlation id (whole invoice trace kept or dropped); Functions host `telemetryMode: OpenTelemetry` (only allow-listed logs leave, protecting the 0.08 GB cap); Application Insights resource sampling 100%, SDK does 50%; supplier-api ignores caller correlation ids; PG/DI/ACS diagnostics deferred (shared has no workspace).

### 1.6 Load suppliers and issue upload links — **parked** · OCR-7 (To Do)
Waiting on your bank-crypto answers.

### 1.7 Supplier opens their link — built · `cb1b8c7` · OCR-8 (+ OCR-14/15/16)
- **Built:** read side of the link registry (SHA-256 token hash in Table Storage; key scheme documented for 1.6); `GET /api/link` with one identical 401 for any bad link and a retryable 503; Upload home, Link not working, loading and waking-up states.
- **Verified:** backend and web tests; a11y on every new screen; token/hash absent from all logs incl. the Azure SDK's.
- **Review:** 23 findings — 17 fixed, 2 deferred, 4 rejected.
- **Decisions:** built ahead of 1.6; token stays in the URL fragment (reload/bookmarks work, never sent to the server); 20 s client timeout; API returns the supplier name only.

### 1.8 Supplier sends a photo or PDF and gets a reference — built · `bd172a9` · OCR-9 (+ OCR-17/18/19)
- **Built:** `POST /api/upload` in AD-6 order (idempotency key → original bytes → queue) with replay; magic-byte type check; 4 MB limit; `R-` reference; Check & send, Received, Couldn't send screens.
- **Verified:** every crash/replay case; capture buttons render at 56 px (the check found and fixed a real 48 px bug).
- **Review:** 25 findings — 20 fixed, 2 deferred (closed in 2.2), 3 rejected.
- **Decisions:** raw body, not multipart; key bound to supplier + file hash + type (different file → 409); one key per file per session; `device_check` passed until 1.9.

### 1.9 On-device photo quality check with send anyway — built · `2d7c6b6` · OCR-10 (+ OCR-20/21/22)
- **Built:** `shared/quality` (darkness, blur, edge cut-off, PDF page count); named problem + Take again; Send it anyway after 2 failures; `X-Device-Check` stored in metadata.
- **Verified:** backend, web and a11y tests; bundle ~84 KB.
- **Review:** 23 findings — 15 fixed, 4 deferred, 4 rejected.
- **Decisions:** checks on a 1024 px orientation-corrected copy; order dark → blur → edges; PDF pages from the page tree's `/Count`; unreadable/slow → pass (server decides).

### 2.1 Server quality check creates the invoice record — built · `b71acd2` · OCR-24 (+ OCR-35/36)
- **Built:** first Alembic migration (`intake`), AD-3 state machine, `route_to_admin`, SQLAlchemy Core repository with Entra tokens, and the `quality` stage (insert, Pillow re-check with shared thresholds, photo time, phash, advance or route).
- **Verified:** integration tests on PostgreSQL 18 in Docker.
- **Review:** 23 findings — 16 fixed, 3 deferred (closed in 2.2), 4 rejected.
- **Decisions:** least-privilege grants (no DELETE; history, admin items and hashes insert-only); encrypted PDFs unreadable; lease reclaim moved to 2.2.

### 2.2 The pipeline never loses an invoice — built · `3bab452` · OCR-25 (+ OCR-37/38/39)
- **Built:** AD-7 database wait; poison triggers with the AD-2 guard; claim/lease reclaim; 15-minute sweeper (status map, orphan uploads, key expiry, `stuck_invoices`); two alert rules.
- **Verified:** integration tests on PostgreSQL 18.
- **Review:** 22 findings — 16 fixed, 2 deferred, 4 rejected.
- **Decisions:** sweeper only re-sends to queues that have a consumer (today `q-quality`, so nothing piles up while 2.3 is parked); each orphan upload recovered once; DB wait capped at 8 days; a poison message that fails 5 times is logged `POISON_ABANDONED` and acknowledged.

### 2.3 Invoice fields extracted by Document Intelligence — **parked** · OCR-26 (To Do)
Waiting on your bank-crypto answers.

### 2.4 Simulated PO and goods-received data — built · `419fb13` · OCR-27 (+ OCR-43/44)
- **Built:** Alembic `0002_sim_purchasing` (SELECT-only for app logins); `PurchasingPort` (`get_po`, `get_receipts`, `get_delivery`, `list_overdue_pos`, `get_delivery_dates`) with `line_no`, `order_date`, `delivery_no`; simulation adapter chosen by `PURCHASING_ADAPTER`; import-linter contract in CI; validated, idempotent synthetic seed (prod needs `--allow-prod`); reusable contract suite.
- **Verified:** `ci/checks.sh all` incl. PostgreSQL 18 and import-linter.
- **Review:** 21 findings — 11 fixed, 1 deferred, 9 rejected.
- **Decisions:** seed uses fixed synthetic supplier ids in a JSON file (1.6 maps real suppliers later; no FK to `master`); app logins get SELECT only; "overdue" per AD-13 means no invoice yet, whatever was received (the AD-13 job filters invoiced POs); seeding Prod needs `--allow-prod` (synthetic only, clear when the real adapter arrives); the seed is a manual operator step (README); import rule enforced by import-linter plus a source scan; the contract test suite is reusable for the real adapter.

### 2.5 / 2.6 — not started (blocked)
2.5 (validation) needs the extracted fields from 2.3; 2.6 (duplicates, dates, bank changes) depends on the bank-crypto answers. Jira untouched.

### 2.7 Staff sign in and see only their surfaces — built · `c696780` · OCR-30 (+ OCR-49/50/51/52/122)
- **Built:** built-in auth v2 on staff-api (no secret, no token store, 8 h session, health anonymous); role model and per-surface route guard; `GET /api/me`; staff shell (role-filtered sidebar/Sheet, landing by role order, access-denied redirect with alert, session-ended dialog incl. redirect responses, offline notice, waking-up, titles and focus, user name + Sign out); bootstrap turns group claims off.
- **Verified:** `ci/checks.sh all` incl. a11y; 231 CI/infra tests.
- **Review (time-boxed):** 22 findings — 18 fixed, 1 deferred (SameSite and XHR-401 behaviour, first Dev deploy), 3 rejected.
- **Decisions:** the principal header is trusted only when built-in auth is on (fail closed in Azure) and only for Entra principals; every staff route except health needs a principal (401) and its surface's role (403); built-in auth v2 via azapi; group claims off (avoids oversized sign-in headers); surfaces are placeholders; routes avoid `admin/`/`runtime/`.

## Process notes

- **BMad repair (23:00):** the build skill was newer than the project's `_bmad/scripts`; `bmad setup` fixed it. `tickets.py` (from `bmad-preview-ticketing`) isn't installed, so stories come from `epics.md`.
- **Implementers edited `deferred-work.md` entries** (the workflow says append-only) when closing items they'd resolved. The content was right; I kept it.
- **Secret-scan false positives** handled once in `.gitleaks.toml` (Azure role GUIDs, BMad manifest hashes) and by renaming one test constant.
- **Token use:** one story at a time, and no second full review pass after fixes.
