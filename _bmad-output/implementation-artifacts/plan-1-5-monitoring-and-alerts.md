---
title: 'Story 1.5: Monitoring and alerts'
type: 'feature'
ticket: '1-5-monitoring-and-alerts'
created: '2026-09-29'
status: 'built'
baseline_revision: 'aa596a6131bdc1bbcb21bb920d480343839c4f89'
route: 'full'
route_source: 'auto'
review: 'thorough'
review_source: 'auto'
lenses_ran: ['blind-hunter', 'edge-case-hunter', 'verification-gap', 'intent-alignment']
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-ocrinvoicing-2026-09-28/ARCHITECTURE-SPINE.md'
  - '{project-root}/docs/standards/azure.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The apps send no telemetry, custom metrics can't be emitted or alerted on by dimension, the subscription budget bypasses the action group, and nothing proves an alert reaches Dj. Later stories (2.2, 2.3) need a metrics helper and dimension alerting in place to add their alert rules.

**Approach:** Add OpenTelemetry export to Application Insights in every app (Entra auth, sampling, one trace per `correlation_id`), a metrics helper in the `invoicing` package, dimension alerting on each Application Insights, Key Vault audit diagnostics, a `shared` action group used by the `shared` and subscription budgets, and an operator alert-test script. Verify offline.

## Boundaries & Constraints

**Always:** `azure-monitor-opentelemetry` (pinned) configured once per app from its settings; Entra auth (`APPLICATIONINSIGHTS_AUTHENTICATION_STRING`, local auth stays off); sampling on; every log/span carries `correlation_id` so one request or message is one trace (AD-17, security.md rule 33); the 1.3 allow-list stays the only way fields reach telemetry (no values, tokens or headers). Metrics helper `emit_metric(name, value, dimensions)` in `adapters/metrics.py` behind a `MetricsPort`, dimensions allow-listed. Application Insights "alerting on custom metric dimensions" on (`CustomMetricsOptedInType=WithDimensions` via azapi where azurerm lacks it, with a comment). Key Vault `AuditEvent` diagnostic setting to the env workspace. `shared/foundation` gets action group `ag-21` (email Dj) and its RG budget uses it; `budget-and-roles.sh` attaches `ag-21` to the $8 subscription budget when given its id. No log-cap alert (AD-17). Names/tags per P-16/P-17.

**Never:** Alert rules for `poison_message`, `stuck_invoices`, `di_pages_used_pct` (Stories 2.2, 2.3). Metrics or logs carrying field values, bank data, tokens or headers. Calling Azure.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Telemetry on | App starts with App Insights settings | Exporter configured once with Entra credential and the configured sampling ratio | Missing connection string → app still starts, telemetry off, one warning (no value logged) |
| One trace per correlation id | HTTP request with `X-Correlation-Id` | Spans/logs carry `correlation_id` attribute equal to the header | — |
| Metric emitted | `emit_metric("poison_message", 1, {"queue": "q-extract"})` | Counter recorded with dimension `queue` | Unknown dimension key or non-scalar value → dropped (not raised) |
| Metric name | Name not in the allow-list | Rejected with `ValueError` at call site | — |
| Subscription budget | `SHARED_ACTION_GROUP_ID` set | Budget notification has `contactGroups=[id]` plus the email | Unset → email only, warning printed |
| Alert test | `test-alerts.sh --dry-run` | Prints the action-group test-notification call per action group | Missing input → exit 1 naming it |

</frozen-after-approval>

## Code Map

- `backend/src/invoicing/adapters/logging.py` (`log_event`, `safe_fields`, `custom_dimensions`) -- fields become span/log attributes through the exporter; keep allow-list.
- `backend/src/invoicing/adapters/http.py` (`http_endpoint`) -- set `correlation_id` on the current span.
- `backend/src/invoicing/apps/common.py` + per-app `function_app.py` -- configure telemetry once at start from settings.
- `infra/modules/env-app/main.tf` -- already sets `APPLICATIONINSIGHTS_AUTHENTICATION_STRING` and Monitoring Metrics Publisher; add connection string/sampling settings if missing.
- `infra/modules/env-foundation/main.tf` -- `module.application_insights`, `module.log_analytics`, `azurerm_monitor_action_group.this`, Key Vault module.
- `infra/shared/foundation/main.tf` -- budget currently emails only; add `ag-21`.
- `infra/bootstrap/budget-and-roles.sh` (+ tests) -- subscription budget JSON.
- `infra/modules/naming` -- action-group names.

## Tasks & Acceptance

**Execution:**
- [x] `backend/src/invoicing/adapters/telemetry.py` + app start-up -- configure Azure Monitor OTel once (Entra credential, sampling ratio from settings); correlation id on spans; tests with in-memory exporters.
- [x] `backend/src/invoicing/ports/metrics.py`, `adapters/metrics.py` -- `MetricsPort` + OTel implementation with allow-listed names (`poison_message`, `stuck_invoices`, `di_pages_used_pct`) and dimensions; tests.
- [x] `infra/modules/env-foundation` -- AI dimension alerting (azapi), Key Vault `AuditEvent` diagnostic setting; tests.
- [x] `infra/shared/foundation` -- action group `ag-21`, budget uses it; output its id; tests.
- [x] `infra/bootstrap/budget-and-roles.sh` -- optional `SHARED_ACTION_GROUP_ID` → `contactGroups`; `infra/bootstrap/test-alerts.sh` -- sends a test notification through each action group (`az monitor action-group test-notifications create`); README step "check Dj received it"; tests.

**Acceptance Criteria:**
- Given `ci/checks.sh all`, when it runs, then it exits 0 with the new tests.
- Given the Terraform tests, when they run, then every environment has dimension alerting on and Key Vault audit logs to its workspace, and all budgets notify through an action group.

## Design Notes

PostgreSQL, DI and ACS live in `shared`, which has no workspace (azure.md rule 14: one per environment); their diagnostic settings stay deferred (1.1 deferral) rather than adding a third workspace.

## Verification

**Commands:**
- `ci/checks.sh all` -- expected: exit 0
- `uv run --with pytest --with pyyaml pytest ci/tests infra/scripts/tests` -- expected: pass

## Implementation Notes

- Implemented by a coding subagent (2026-09-29). `azure-monitor-opentelemetry` 1.8.10 with OTel 1.44.0 pinned; only the `invoicing` logger exported; trace id derived from the correlation id so one id is one trace across apps; allow-listed fields become log attributes; metrics allow-list `poison_message` (counter, `queue` dimension), `stuck_invoices`, `di_pages_used_pct` (gauges); `CustomMetricsOptedInType=WithDimensions` via `azapi_update_resource`; Key Vault `AuditEvent` diagnostics; `ag-21` for shared + subscription budgets (`SHARED_ACTION_GROUP_ID`); `test-alerts.sh`.

## Plan Change Log

## Review Triage Log

**Pass 1 (2026-09-29): blind-hunter, edge-case-hunter, verification-gap, intent-alignment.** Counts: high 2, medium 13, low 9, false 1, maybe-false 1.

| # | Finding | Verdict | Route | Evidence / action |
|---|---------|---------|-------|-------------------|
| 1 | Synthetic parent is hard-coded SAMPLED, so a ParentBased sampler keeps every trace: sampling is bypassed (B4) | high | patch | Decide the sampled flag with a trace-id ratio on the derived trace id (deterministic per correlation id). Keep the synthetic parent (documented orphan parent). |
| 2 | Functions host also exports worker logs from every logger and its own requests: duplicates and allow-list bypass (B5, E7) | high | patch | `host.json` `telemetryMode: OpenTelemetry` in all four apps; `invoicing` logger level INFO (E6) and no propagation when telemetry is on. |
| 3 | Anonymous callers choose the trace id / sampling via `X-Correlation-Id` (B3, E2) | medium | patch | supplier-api (anonymous) ignores the caller header and always generates; staff-api keeps honouring it. |
| 4 | Nil UUID correlation id breaks one-id-one-trace (E1) | low | patch | Treat nil as absent. |
| 5 | `configure_azure_monitor` exception stops the app at import (E4) | medium | patch | Catch, log `telemetry.failed` with a code only, continue without telemetry. |
| 6 | Malformed authentication string silently falls back / raw `ValueError` (B7, E5) | medium | patch | Raise `SettingsError` naming the setting. |
| 7 | Correlation id not unbound after the span is untested (VG1) | medium | patch | Test normal exit, exception exit and nesting. |
| 8 | Caller's dropped `correlation_id` blocks the bound one (E3) | low | patch | Fill from the bound id when the caller's value was dropped. |
| 9 | Flat `extra=` fields could clash with `LogRecord` attributes (B6, VG other) | medium | patch | Test that allowed keys never overlap `LogRecord` attributes. |
| 10 | `test-alerts.sh` emails the command-line address, not the group's stored receiver; stops midway after sending; duplicate stacks (B1, B2, E12) | medium | patch | Read `emailReceivers` from each group and send to those; check all groups first; de-duplicate. |
| 11 | azurerm full PUT on Application Insights can reset `CustomMetricsOptedInType` (B8, E13) | medium | patch | Re-run the azapi update when the component changes (`replace_triggered_by` via a `terraform_data` of the component's inputs). |
| 12 | Retention comment now sits above the Key Vault block (B9, E14) | low | patch | Move it back. |
| 13 | Request span lacks method/route attributes (B12) | low | patch | Add `http.request.method`, `http.route`/`url.path`. |
| 14 | `SHARED_ACTION_GROUP_ID` segments accept quotes/spaces into JSON (B13, E11) | medium | patch | Restrict to `[A-Za-z0-9._()-]+`. |
| 15 | Metric value overflow raises `OverflowError`; `di_pages_used_pct` unbounded; lazy recorder not thread-safe (E8, B14, E9) | low | patch | `ValueError` on overflow; bound 0–100; lock the lazy init. |
| 16 | Tests reach the real exporter when the dev env exports telemetry settings (E10) | medium | patch | `conftest` removes the three telemetry variables. |
| 17 | Existing-budget "no notifications" branch untested (VG3) | low | patch | Fake-az knob + test. |
| 18 | Resource `sampling_percentage` (50) plus SDK 0.5 may stack to 25% (VG other, intent R4) | maybe-false | patch | Remove the doubt: resource sampling 100 (no ingestion sampling), app ratio from its own variable (0.5). |
| 19 | Queue-side correlation propagation not implemented (B11) | medium | defer | No queue triggers yet; Stories 2.1/2.2 wrap handlers in `correlation_span` from `QueueMessage.correlation_id`. |
| 20 | Caller-supplied id precedence over bound id unpinned (VG2) | low | defer | No caller passes a different id yet. |
| 21 | Alert rules moved to 2.2/2.3 without planning change (B10) | false | reject | epics.md Story 1.5 note already assigns them to 2.2/2.3. |
| 22 | Terraform tests echo their own inputs (dimension flag, KV diag) (B8 part, intent) | low | reject | Mock-provider limit; real proof is the first apply. |
| 23 | Subscription budget stays email-only until the operator re-runs with the id (E15, intent R5) | low | reject | Bootstrap-owned by AD-17; README run order + warning cover it. |
| 24 | `emit_metric` before `configure_telemetry` untested (B14 part) | low | reject | OTel proxy meter handles late providers. |
| 25 | Real exporter / inbox never exercised (intent) | — | reject | "Verify offline" by design; `test-alerts.sh` is the operator proof. |
