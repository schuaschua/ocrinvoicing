---
title: 'Story 1.3: Python Functions API skeleton'
type: 'feature'
ticket: '1-3-python-functions-api-skeleton'
created: '2026-09-29'
status: 'built'
baseline_revision: '74f64900c887169413e3c98d97cc849f3513228a'
route: 'full'
route_source: 'auto'
review: 'thorough'
review_source: 'auto'
lenses_ran: ['blind-hunter', 'edge-case-hunter', 'verification-gap', 'intent-alignment']
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-ocrinvoicing-2026-09-28/ARCHITECTURE-SPINE.md'
  - '{project-root}/docs/standards/coding-style.md'
  - '{project-root}/docs/standards/terraform.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** There is no back-end code and no Function apps. Every later story needs the `invoicing` package layers, four Flex Consumption apps per environment with their identities and runtime roles, shared conventions (settings, error shape, safe logging, queue messages), and a working code deploy.

**Approach:** Build the hexagonal `backend/src/invoicing/` skeleton with the four app entry points, cross-cutting helpers and tests; add the `<env>/app` Terraform stack (module + dev/prod roots) with the Flex apps and AD-17 runtime roles; implement `ci/code-deploy.sh` packaging and publishing. Verify offline: pytest with ≥ 80% coverage, `terraform test` with mocks, `ci/checks.sh all`.

## Boundaries & Constraints

**Always:** Python 3.13, Functions v2 decorator model, dependencies pinned in `uv.lock` (versions from the spine Stack table where listed). Layering per spine: `domain` imports nothing outside itself (no framework, ORM, HTTP or Azure SDK); `ports` → domain; `adapters` → ports, domain; `apps` → all. One `pydantic-settings` object per app; no `os.environ` elsewhere. Errors as `{code, message, correlation_id}`; codes from `domain/errors.py`. Logs carry ids, codes and timings only. `QueueMessage{invoice_id, correlation_id, first_enqueued_at, attempt}` in `ports/messages.py`, sent as plain JSON through `azure-storage-queue` with managed identity. `pipeline` `host.json`: `batchSize` 1, `newBatchThreshold` 0, `extensions.queues.messageEncoding` `none`. Flex apps: one plan each, on-demand only, 2,048 MB, max instances 1 (`pipeline`) / 10 (others), user-assigned identity from `<env>/foundation`, names per P-16, 5 tags. Runtime roles exactly per AD-17 at the narrowest scope, none at subscription scope. `GET /api/health` on `supplier-api` and `staff-api` returns 200 with the app version.

**Never:** Call Azure. Business logic, database code or migrations (`backend/migrations/env.py` must not be created; later stories own schemas). Built-in auth config (Story 2.7, OCR-49), the DI Cognitive Services User assignment (2.3, OCR-40), the `ACS Email Sender` assignment (5.2, OCR-107), metric alerts (1.5). Secrets in app settings.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Health | `GET /api/health` on supplier-api / staff-api | 200 `{"status":"ok","version":"<pkg version>"}` | — |
| Unhandled error | A handler raises an unexpected exception | 500 `{code:"INTERNAL_ERROR", message, correlation_id}`; no stack trace in body | Logged with correlation id and code only |
| Domain error | Handler raises a domain error with code X | Mapped HTTP status, body `{code:X, message, correlation_id}` | — |
| Correlation id | Request carries `X-Correlation-Id` / none | Echoed / new UUIDv7 generated, returned in header and body | Invalid header value → new id |
| Missing setting | A required env var is absent at start | App fails fast naming the setting (not its value) | — |
| Log redaction | Log call with a token/header/value field | Only allow-listed keys (ids, codes, timings) are emitted | — |
| Domain import rule | `domain/` imports `azure`, `pydantic`, `sqlalchemy`, `requests`, `httpx` … | Import-lint test fails | — |
| Queue send | Producer sends a `QueueMessage` | Plain JSON text with exactly the 4 fields (ISO 8601 UTC time) | — |

</frozen-after-approval>

## Code Map

- `backend/pyproject.toml`, `backend/uv.lock` -- add runtime deps (azure-functions, pydantic 2.13.5, pydantic-settings, azure-identity, azure-storage-queue, uuid7 helper if needed) and keep the dev group from 1.2; mypy strict applies to `invoicing.domain`.
- `backend/src/invoicing/{domain,ports,adapters,apps}/` -- empty packages from 1.1; add apps `supplier_api`, `staff_api`, `pipeline`, `accounts_sim`.
- `ci/checks.sh` -- backend with code now requires tests and ≥ 80% coverage (1.2 contract).
- `ci/code-deploy.sh` -- currently fails once `infra/<env>/app` exists; this story implements it (packaging per app, SPA build included when `web/<app>` is scaffolded, publish to the app's Flex deployment container with the deploy identity).
- `pipelines/templates/code-deploy.yml`, `ci/tests/test_pipelines.py` -- keep structure tests green.
- `infra/modules/env-foundation/outputs.tf`, `infra/{dev,prod}/foundation/outputs.tf` -- identities, storage account, Key Vault, App Insights ids to read via `terraform_remote_state`.
- `infra/modules/naming` -- names for plans (`asp`), function apps (`func`), deployment containers.

## Tasks & Acceptance

**Execution:**
- [x] `backend/src/invoicing/domain/errors.py`, `domain/ids.py` -- error base + codes (`INTERNAL_ERROR`, `VALIDATION_FAILED`, `NOT_FOUND`, `DB_OFFLINE`, …) and UUIDv7 helper; framework-free.
- [x] `backend/src/invoicing/ports/messages.py`, `ports/queue.py` -- `QueueMessage` model + `QueueSender` Protocol.
- [x] `backend/src/invoicing/adapters/queue.py`, `adapters/logging.py`, `adapters/http.py` -- storage-queue sender (managed identity, JSON text), allow-list log helper, HTTP helpers (correlation id, error mapping, response).
- [x] `backend/src/invoicing/apps/<app>/{function_app.py, settings.py, host.json}` ×4 -- entry points; health routes on supplier-api/staff-api; pipeline has no HTTP routes (placeholder timer or none as needed to start); per-app `Settings`.
- [x] `backend/tests/**` -- tests for every matrix row plus import-lint (AST scan of `domain/`, and ports/adapters direction), host.json values; coverage ≥ 80%.
- [x] `infra/modules/env-app/` + `infra/{dev,prod}/app/` -- 4 Flex plans/apps, deployment containers, app settings (no secrets), runtime role assignments per AD-17 (minus DI/ACS), `terraform test` with mocks asserting counts, memory, max instances, identities, role scopes, no subscription scope.
- [x] `ci/code-deploy.sh` + tests -- build one zip per app, publish; dry-run testable with fakes.

**Acceptance Criteria:**
- Given the backend, when `ci/checks.sh all` runs, then lint, mypy, tests with ≥ 80% coverage and terraform checks pass.
- Given `infra/dev/app`, when `terraform test` runs, then it proves 4 apps, one plan each, 2,048 MB, max instances 1/10, the right identity per app and only AD-17 roles.

## Design Notes

Each app's deploy package is flat: `function_app.py` + `host.json` at the root, the `invoicing` package, and `requirements.txt` from `uv export --no-dev`; Flex does the remote build. `pipeline` needs at least one function to start; use the AD-2 sweeper's timer as an inert stub only if the host requires it, otherwise no functions.

## Verification

**Commands:**
- `ci/checks.sh all` -- expected: exit 0
- `uv run --with pytest --with pyyaml pytest ci/tests infra/scripts/tests` -- expected: pass

## Implementation Notes

- Implemented by a coding subagent (2026-09-29): 83 backend tests, 100% coverage; `ci/checks.sh all` exit 0. UUIDv7 from the standard library; no sweeper stub (host starts with zero functions); Key Vault roles per secret (pipeline: public key + HMAC; staff-api: all three); storage roles at account scope for a service where AD-17 names no container/queue; correlation id always in the response header, in the body only for errors.
- Overnight decision: each app identity gets Storage Blob Data Owner on `azure-webjobs-hosts` and `azure-webjobs-secrets` (created in env-foundation) so Flex hosts can start; beyond the AD-17 table, spine update pending.

## Plan Change Log

## Review Triage Log

**Pass 1 (2026-09-29): blind-hunter, edge-case-hunter, verification-gap, intent-alignment.** Counts: high 0, medium 12, low 9, false 2, maybe-false 0.

| # | Finding | Verdict | Route | Evidence / action |
|---|---------|---------|-------|-------------------|
| 1 | Apps may start before their role assignments exist (B4) | medium | patch | No `depends_on` from `module.function_apps` to the role assignments. Add it. |
| 2 | Deploy reports success without checking the apps started (B5) | medium | patch | Add a post-deploy `GET /api/health` (retry, version match) for supplier-api/staff-api. |
| 3 | `host_name` output is the resource URI; output descriptions wrong; mock lacks `host_containers` (B16, E12) | medium | patch | Output `defaultHostName`, fix descriptions, extend mocks, assert it. |
| 4 | Async credential never closed (B7, E2) | medium | patch | Keep and close the credential in `close()`; test it. |
| 5 | Empty/ill-typed required settings pass fail-fast (B11, E1) | medium | patch | `min_length=1`, UUID client id, https vault URI, storage-name pattern. |
| 6 | No `Cache-Control: no-store` on API responses (B12) | medium | patch | staff-api will return bank details; add to security headers + test. |
| 7 | Malformed `web/*/package.json` silently ships without SPA (B14, E7) | medium | patch | Die when the file exists but does not parse. |
| 8 | Untracked local files (e.g. `local.settings.json`, `.env`) packaged (E9) | medium | patch | Package only git-tracked files of the `invoicing` package. |
| 9 | Stale `dist/` can be packaged (E8) | medium | patch | `rm -rf dist` before the build. |
| 10 | Handler returning a non-`HttpResponse` escapes the error shape (E4) | low | patch | Stamp headers inside the try; non-response → `INTERNAL_ERROR`. |
| 11 | `QueueMessage.attempt` accepts `true`/`"3"` (E6) | low | patch | `strict=True`. |
| 12 | `delay_seconds` above 7 days not rejected (B8, E3) | low | patch | Raise `ValueError` above 604,800 s. |
| 13 | Control characters in allowed log values (E5) | low | patch | Require `isprintable()`. |
| 14 | Domain-error log line not asserted (VG1) | low | patch | Add `caplog` assertion. |
| 15 | Partial deploy leaves no record of which apps were published (E10) | low | patch | Log the published apps and list them on failure. |
| 16 | Shared `azure-webjobs-secrets`/`hosts` lets one app's identity read another's host keys (B1) | medium | defer | Accepted for the PoC (needs a compromised app); per-app host storage or Key Vault secret storage later. Raised to Dj. |
| 17 | Host-container roles depart from AD-17; spine not updated (B3, E13) | medium | defer | Architecture document owned by Dj/architect; recorded for the spine update. |
| 18 | Log `custom_dimensions` not exported without an exporter (B9) | medium | defer | Telemetry exporter and sampling are Story 1.5. |
| 19 | SPA packaged but no route serves it (B13) | medium | defer | Serving the SPA is Story 1.4's AC. |
| 20 | Terraform app settings vs pydantic classes not cross-checked (VG2) | medium | defer | Needs a shared settings manifest; sides match today. |
| 21 | Deploy container gets Owner rather than Contributor (B2) | false | reject | AD-17 specifies Storage Blob Data Owner on its own deployment container. |
| 22 | Deploy identity lacks rights to publish (B6) | false | reject | The env deploy identity is Contributor on the env RG (Story 1.1). |
| 23 | Allowed-key values not pattern-checked (B10 part) | low | reject | Adds per-key validators; row 13 handles injection. |
| 24 | Zips stored uncompressed; top-level dotfiles skipped (B15) | low | reject | No functional impact today. |
| 25 | `<env>/app` applied before foundation re-applied (E11) | low | reject | The pipeline applies foundation first. |
| 26 | Readings vs live Azure surface (intent audit) | — | reject | Descriptive; matches "verify offline". |
