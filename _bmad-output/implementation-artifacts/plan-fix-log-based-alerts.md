---
title: 'Fix: pipeline alerts fire on log events, not custom metrics'
type: 'bugfix'
ticket: ''
created: '2026-09-30'
status: 'built'
route: 'full'
route_source: 'auto'
review: 'thorough'
review_source: 'auto'
lenses_ran: ['blind-hunter', 'edge-case-hunter', 'verification-gap', 'intent-alignment']
review_loop_iteration: 0
baseline_revision: '38e11d8fdac4152a64d6f5b391629a148c7e52b3'
context:
  - '{project-root}/docs/standards/terraform.md'
  - '{project-root}/docs/standards/azure.md'
  - '{project-root}/docs/standards/coding-style.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The AD-17 pipeline alerts (`ar-01` poison message, `ar-02` stuck invoices, `ar-03` DI pages at 80%) are metric alerts on OpenTelemetry custom metrics. In Dev, no Python custom metric reaches Application Insights, even with a flush after each metric (PR 5). The same apps' logs and traces do arrive, and a local run of the real exporter sends the metric envelopes. So these alerts can never fire (Stories 1.5, 2.2 and 2.3; walkthrough-dev-2026-09-30.md, follow-up 8).

**Approach (Dj, 2026-09-30, option a):** Replace the three metric alerts with log search alerts (`azurerm_monitor_scheduled_query_rules_alert_v2`) on the `traces` table of the environment's Application Insights. They fire on log events that already arrive:
- **`ar-01`:** any `poison.done` in the last hour, one alert per `queue`.
- **`ar-02`:** a `sweeper.done` whose `requeued` + `orphans` is above 0 in the last 30 minutes.
- **`ar-03`:** `di_pages_used_pct` of at least 80 in the last 6 hours. The extract stage now logs it (`extract.di_usage`) next to the metric.

The names, severities, frequencies, action group and descriptions are unchanged. The custom metrics stay emitted, since they are harmless, but no alert depends on them.

**Decisions (Dj, 2026-09-30, after review):**
- **Sampling.** Telemetry is sampled at 0.5, and logs follow their trace's decision (`enable_trace_based_sampling_for_logs`). So `poison.done`, `sweeper.done` and `extract.di_usage` are logged **outside the trace**, which means always kept; everything else stays sampled. Turning sampling off (1.0) was rejected.
- **Fields.** The alert queries read the fields as columns (`customDimensions.queue`, `.requeued`, `.orphans`, `.pages_used_pct`, which arrive in Dev), not by parsing the message text. This replaces the Always rule on `key=value` text below.

## Boundaries & Constraints

**Always:**
- Queries parse the `key=value` text that `log_event` writes into `message`.
- The rules need no managed identity (same subscription).
- Cost: 3 log rules at 15-minute or slower frequency, about US$1.50 a month, recorded in AD-17 (P-2).
- AD-17, and the acceptance criteria of Stories 1.5, 2.2 and 2.3 in `epics.md`, say "log alert on …" instead of "custom metric".
- `pages_used_pct` is added to the log allow-list; it is a number, not a value from an invoice.

**Never:**
- Deleting the metric emission code.
- A new test case: assertions go into the existing `env_app` run and the existing 2.3 extract test.
- Alerting on anything but these three events.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Poison | one `poison.done code=… queue=q-quality-poison` in the hour | `ar-01` fires for that queue | — |
| Clean sweep | `sweeper.done … requeued=0 … orphans=0` | no alert | — |
| Stuck | `sweeper.done … requeued=2 … orphans=0` | `ar-02` fires | — |
| DI usage | `extract.di_usage pages_used_pct=82.0` | `ar-03` fires | — |
| DI below | `pages_used_pct=40` | no alert | — |

</frozen-after-approval>

## Code Map

- `infra/modules/env-app/main.tf` (lines ~482–590):
  - Today: `local.custom_metrics_namespace` and three `azurerm_monitor_metric_alert` resources (`poison_message`, `stuck_invoices`, `di_pages_used_pct`) using `var.metric_alert_names`, `var.application_insights_id`, `var.action_group_id` and `var.di_monthly_page_cap`.
  - Replace them with `azurerm_monitor_scheduled_query_rules_alert_v2` (scopes = the Application Insights id, `evaluation_frequency` / `window_duration` as today, `criteria { query, time_aggregation_method, metric_measure_column, operator, threshold, dimension }`, `action { action_groups }`).
  - Keep the resource-name keys, so outputs and tests change the least.
- `infra/modules/env-app/tests/env_app.tftest.hcl`: update the existing alert assertions (they reference `azurerm_monitor_metric_alert.*`).
- `infra/modules/env-app/outputs.tf` and the `infra/{dev,prod}/app` roots: check for references to the metric alert resources.
- `backend/src/invoicing/apps/pipeline/extract.py` `_emit_usage` (line ~111): also `log_event(_logger, "extract.di_usage", pages_used_pct=…)`.
- `backend/src/invoicing/adapters/logging.py` `ALLOWED_KEYS`: add `pages_used_pct`.
- `backend/tests/apps/test_story_2_3_extract.py`: assert the log event in the existing test.
- Docs:
  - `_bmad-output/planning-artifacts/architecture/architecture-ocrinvoicing-2026-09-28/ARCHITECTURE-SPINE.md` lines 446–449 (AD-17 alerts and cost).
  - `_bmad-output/planning-artifacts/epics.md` lines 160, 496, 724, 736, 748, 792 and 795.
  - `infra/bootstrap/README.md` alert check paragraph (line ~320).

## Design Notes

- **Cost.** `ar-01` splits by `queue`, so it is billed per monitored time series: one per poison queue that has logged `poison.done`, on top of the rule's base price. Recorded in AD-17.
- **`ar-03` resolves itself.** With auto-mitigation on and a 6-hour window, `ar-03` resolves after 6 hours with no `extract.di_usage`, even while usage stays at 80% or more, and fires again on the next extraction. Recorded in AD-17.
- **Sampling.** `poison.done`, `sweeper.done` and `extract.di_usage` go through `log_unsampled_event`, which logs with no active span, so trace-based log sampling keeps them.

## Tasks & Acceptance

**Execution:**
- [x] `infra/modules/env-app/main.tf` + tftest -- three log alerts replace the metric alerts -- they can fire in Dev.
- [x] `extract.py`, `logging.py`, the 2.3 test -- log `extract.di_usage` -- `ar-03` has a source.
- [x] Spine, epics, README -- the log alerts, cost -- documents match the code.

**Acceptance Criteria:**
- Given `ci/checks.sh all`, then it passes with at most 200 test cases.
- Given the Dev deploy, when a malformed message reaches `q-quality-poison`, then `ar-01` fires within about 20 minutes and emails the action group.

## Review Triage Log

Four lenses, about 20 findings. 2 were decided by Dj; the rest were patched or documented.

- **Decided by Dj:**
  - **Sampling:** with trace-based log sampling at 0.5, about half of `poison.done`, `sweeper.done` and `extract.di_usage` records would be dropped. They are now logged outside any trace (`log_unsampled_event`).
  - **Queries:** they read `customDimensions`, not the message text.
- **Patched:**
  - A `poison.done` log test on the routed and malformed paths.
  - Dev and prod root tests bind each rule to its event and measure column.
  - A `coalesce` so a missing field can't null the `stuck` sum.
  - Story 1.5's criterion (line 493) and the foundation's custom-metric wording updated.
  - Per-time-series billing for `ar-01`, and the 6-hour auto-resolve of `ar-03`, documented in AD-17.
  - The `ar-02` description names the `sweeper.done` fields.
- **Deferred:**
  - Renaming `metric_alerts` / `metric_alert_names`, which now hold log alerts. Kept to limit churn.
  - The spine's total monthly cost line, not updated for the extra ~$1.20.
- **Verified against real Dev data** (`--offset 1d`):
  - The `ar-01` query finds the 06:07 poison event with `queue = q-quality-poison`.
  - The `ar-02` query reads 69 sweeps: `stuck` is 0 each time, with no nulls.
  - `ar-03` has no source events until this deploys.
- **Local `ci/checks.sh all`:** failed only on the environment, with load average about 12 on the Mac:
  - the backend test PostgreSQL container dropped its connections;
  - the 2.7 App test's 5 s timeout, known to flake under load.

  The tests for the files changed here passed on their own, and the Terraform checks passed. The PR's Jenkins branch build must be green before merging.

## Verification

**Commands:**
- `ci/checks.sh all` -- expected: all checks pass.

**Manual checks (after the Dev deploy):**
- The poison test (temporary queue role, then one message): `ar-01` fires and the email arrives. That also completes Stories 1.5 and 2.2.
