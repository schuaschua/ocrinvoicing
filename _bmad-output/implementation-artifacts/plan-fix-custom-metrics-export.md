---
title: 'Fix: custom metrics never reach Application Insights'
type: 'bugfix'
ticket: ''
created: '2026-09-30'
status: 'built'
route: 'oneshot'
route_source: 'auto'
review: 'quick'
review_source: 'auto'
lenses_ran: ['quick']
review_loop_iteration: 0
baseline_revision: '761c4987a383f9d92c8f6d53512a8483ccd3ee0d'
context:
  - '{project-root}/docs/standards/coding-style.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The AD-17 custom metrics (`poison_message`, `stuck_invoices`, `di_pages_used_pct`) never reach Application Insights in Dev, so alerts `ar-01`/`ar-02`/`ar-03` can never fire (Stories 1.5, 2.2, 2.3; walkthrough-dev-2026-09-30.md follow-up 8). Flex Consumption runs each function group on short-lived instances that stop soon after an invocation. The OpenTelemetry metric reader exports only every 60 s, so the process ends before any metric is sent. Traces and logs, exported every few seconds, do arrive.

**Approach:** After recording a metric, flush the meter provider, so the value is exported during the invocation that produced it. The metrics are rare events: one per poison message, one per sweep every 15 minutes, one per extraction. A bounded flush costs little and does not depend on how long the instance lives.

</frozen-after-approval>

## Implementation Notes

Oneshot: one adapter change plus assertions in the existing adapter test (about 30 lines).

- The evidence for the root cause is in the Dev App Insights data for the pipeline host role (`babaloo-sea-lng-func-03`): "Function group target is function:sweeper / quality", and "Stopped the listener" 81 times in 24 h.
- Pipeline spans and logs arrive under the role `pipeline`, but `customMetrics` holds only the host's `dotnet.*` metrics.
- A local probe showed the exporter turns all three metrics into envelopes, so their shape is not the problem.
- Changed `backend/src/invoicing/adapters/metrics.py`:
  - `OpenTelemetryMetrics` takes an optional `flush`. The default is `_flush_global_provider`, which calls the global meter provider's `force_flush(timeout_millis=5000)`; the no-op provider has none.
  - `emit_metric` flushes after recording. A failing flush is logged as `metrics.flush_failed` (code = the metric) and never raised.
- Test: assertions added to the existing `test_story_1_5_poison_message_is_a_counter_with_its_queue`, so there is no new test case. Each emit calls the flush once, and a raising flush does not propagate.

## Review Triage Log

Quick lens, 9 findings: 1 medium, 6 low, 2 false.

- Medium (patched): the real flush path was untested. Now a real `MeterProvider` with a 60 s `PeriodicExportingMetricReader` shows the metric exported at once.
- Low (patched): the comment claimed a 5 s bound, but the exporter ignores the deadline and uses its 10 s network timeout. Comment corrected.
- Low (patched): a failed export returns False and doesn't raise, so `metrics.flush_failed` missed it. Now logged on False as well as on an exception.
- Low (patched): the failure log wasn't asserted. `caplog` now checks both failure paths.
- Low (patched): the test name no longer fit. Renamed `test_story_1_5_poison_message_counter_and_each_metric_exported_at_once`.
- Low (rejected): the flush blocks the event loop. Each pipeline function runs alone on its instance with `batchSize` 1, so nothing waits on it; an async port would change `MetricsPort`. The trade-off is documented in the code.
- Low (rejected): `# noqa: BLE001` is dead because ruff doesn't select BLE. It matches the existing `sweeper.py` pattern and is cosmetic.
- False: the `test-invoices` binaries in the diff are untracked scratch files and aren't committed; only this fix's files are staged.
- False (handled): the Jira key. The PR is titled OCR-6 (Story 1.5) and names 2.2/2.3.

## Verification

**Commands:**
- `cd backend && uv run pytest -q tests/adapters/test_metrics_adapter.py` -- expected: passes, including the flush assertion.
- `ci/checks.sh all` -- expected: all checks pass with at most 200 test cases.

**Manual checks (after the Dev deploy):**
- Put one malformed message on `q-quality`. Within 20 minutes, `customMetrics | where name == 'poison_message'` shows it, alert `babaloo-sea-lng-ar-01` fires, and Dj receives the email.
