---
title: 'Story 2.2: The pipeline never loses an invoice'
type: 'feature'
ticket: '2-2-the-pipeline-never-loses-an-invoice'
created: '2026-09-29'
status: 'built'
baseline_revision: 'b71acd2c805c36934033c1d3008ae803c2a6d55f'
route: 'full'
route_source: 'auto'
review: 'thorough'
review_source: 'auto'
lenses_ran: ['blind-hunter', 'edge-case-hunter', 'verification-gap', 'intent-alignment']
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-ocrinvoicing-2026-09-28/ARCHITECTURE-SPINE.md'
  - '{project-root}/docs/standards/coding-style.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** An invoice can still be lost: consumers burn their retries while PostgreSQL is stopped at night, messages that fail 5 times sit in poison queues unseen, a crash between a commit and an enqueue strands an invoice, an upload whose enqueue failed is never processed, and `uploadkeys` never expire.

**Approach:** Add a DB-wait wrapper for every queue consumer (AD-7), poison-queue triggers that route `PROCESSING_FAILED` under the AD-2 state guard (creating the row from blob metadata when missing), the claim/lease reclaim transitions in the domain and repository (AD-3), a 15-minute sweeper timer (AD-2 status map, orphaned-upload reconcile, `uploadkeys` cleanup, `stuck_invoices` metric), the `poison_message{queue}` metric, and the two metric alert rules in `<env>/app`. Verify offline, with the PostgreSQL 18 container for database behaviour.

## Boundaries & Constraints

**Always:** AD-7: a consumer that can't reach PostgreSQL re-enqueues the same message (same `invoice_id`, `correlation_id`, `first_enqueued_at`, `attempt`) with a 15-minute visibility delay, then completes the original normally so the dequeue count isn't used; timers that find the DB down exit and catch up next run; poison triggers follow the same rule. AD-2 poison guard: route `PROCESSING_FAILED` only when the invoice is in that queue's input state (`q-quality`: `received` or row missing; `q-extract`: `awaiting_extraction` or `extracting` with expired lease; `q-validate`: `awaiting_validation` or `validating` expired; `q-post`: `ready_to_post` or `posting` expired); otherwise acknowledge. Row missing → read the blob's `IntakeBlobMetadata` and pass it to `route_to_admin` (row created there); blob also missing → log a code and acknowledge. Emit `poison_message{queue}` (1.5 metrics helper) on every poison message handled. AD-3 claim: move to a claim state with `claimed_until = now + 10 min`; reclaim allowed only when the lease has expired; a live lease is never taken; zero rows → acknowledge. Sweeper every 15 min (NCRONTAB, UTC): re-enqueue invoices with `status_changed_at` > 1 h old AND > 1 h after `pg_postmaster_start_time()` per the AD-2 map (`received`→`q-quality`; `awaiting_extraction`/expired `extracting`→`q-extract`; `awaiting_validation`/expired `validating`→`q-validate`; `ready_to_post` with `next_attempt_at` null or past / expired `posting`→`q-post`); never touches `in_admin_queue`, `posted`, `rejected`; emits `stuck_invoices` = number re-enqueued. The sweeper also re-enqueues `uploadkeys` rows older than 1 h whose invoice row doesn't exist (the 1.8 orphan-upload deferral) to `q-quality` using the row's `correlation_id` and `created_at`, and deletes rows older than 24 h (AD-6). Alert rules (Terraform, `<env>/app`): `poison_message` total > 0 over 1 h, split by `queue`; `stuck_invoices` > 0; both to the env action group, names per P-16, 5 tags. Logs ids and codes only.

**Never:** Extraction, validation or posting logic. Changing AD-2/AD-3 semantics. Calling Azure.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| DB down, consumer | `quality` message, DB connection fails | Same message re-enqueued with 15-min visibility; original completes | Enqueue failure → raise (host retry) |
| DB down, timer | Sweeper, DB down | Exits with a code, no enqueues | — |
| DB down, poison | Poison trigger, DB down | Re-enqueued to the poison queue with 15-min delay | — |
| Poison, input state | `q-quality-poison`, invoice `received` | `route_to_admin([PROCESSING_FAILED])`; metric emitted | — |
| Poison, moved on | Invoice already `awaiting_extraction` | Acknowledge only; metric emitted | — |
| Poison, row missing | No invoice row, blob exists | Row created from metadata and routed | — |
| Poison, row and blob missing | Neither exists | Code logged, acknowledged | — |
| Poison, expired claim | `extracting` with expired lease on `q-extract-poison` | Routed | Live lease → acknowledge |
| Lease reclaim | `extracting`, lease expired | Claim succeeds with a new lease | Live lease → zero rows, acknowledge |
| Sweeper map | One invoice per mapped state, all stale | Each re-enqueued to its queue; `stuck_invoices` = count | — |
| Sweeper leaves alone | `in_admin_queue`, `posted`, `rejected`, fresh rows, `ready_to_post` with future `next_attempt_at`, live leases | Not enqueued | — |
| Just restarted | Stale rows but DB started < 1 h ago | Nothing enqueued, metric 0 | — |
| Orphan upload | `uploadkeys` row > 1 h, no invoice row | `q-quality` message with the row's ids | — |
| Old keys | `uploadkeys` rows > 24 h | Deleted | Delete failures logged, continue |

</frozen-after-approval>

## Code Map

- `backend/src/invoicing/apps/pipeline/{function_app.py, quality.py, settings.py, host.json}` -- `quality` trigger, `StageFailed(code)`; add poison triggers for the four `*-poison` queues and the sweeper timer.
- `backend/src/invoicing/domain/{status.py, transitions.py}` -- statuses, edges, `FINAL_TARGETS`, `route_to_admin`; add claim/reclaim planning and per-queue input states and the sweeper map.
- `backend/src/invoicing/adapters/postgres/{invoices.py, engine.py, schema.py}` -- repository; add claim, sweeper query (with `pg_postmaster_start_time()`), status-by-id; detect "database unreachable" errors (psycopg `OperationalError` on connect) as a distinct exception.
- `backend/src/invoicing/adapters/{queue.py, metrics.py, blob_images.py, table_upload_keys.py}` -- sender (`visibility_timeout`), `emit_metric`, blob read with metadata, key store; add list-old and delete to the key store.
- `backend/src/invoicing/ports/{messages.py, queue.py, invoices.py, upload_keys.py}` -- `QueueMessage` (keep fields on re-enqueue), port additions.
- `infra/modules/env-app/` -- add the two `azurerm_monitor_metric_alert` rules on the env Application Insights (custom metrics namespace), action group from foundation outputs; tests.
- `_bmad-output/implementation-artifacts/deferred-work.md` -- 2.1 (poison routing, lease reclaim) and 1.8 (orphan uploads, 24 h expiry) deferrals are closed here.

## Tasks & Acceptance

**Execution:**
- [ ] `backend/src/invoicing/domain/{status.py, transitions.py, sweep.py}` -- claim/reclaim planning, poison input states, sweeper map; unit tests.
- [ ] `backend/src/invoicing/adapters/postgres/*` + ports -- claim, stale-invoice query, database-unreachable detection; integration tests (incl. `pg_postmaster_start_time()` guard via a clock/offset seam).
- [ ] `backend/src/invoicing/apps/pipeline/{dbwait.py, poison.py, sweeper.py, function_app.py}` -- DB-wait wrapper applied to `quality` and poison triggers; poison handler; sweeper timer; metrics.
- [ ] `backend/src/invoicing/adapters/table_upload_keys.py` + port -- list rows older than a cutoff, delete; tests.
- [ ] `infra/modules/env-app` (+ dev/prod roots) -- alert rules; terraform tests.
- [ ] `backend/tests/**` -- `test_story_2_2_*` for every matrix row.

**Acceptance Criteria:**
- Given `ci/checks.sh all`, when it runs with Docker, then it exits 0.

## Design Notes

"Database unreachable" = failure to connect (psycopg `OperationalError` at connect, or the Entra token call failing), not a query error. The sweeper reads `pg_postmaster_start_time()` in SQL by default; the repository takes an optional start-time override so the integration test can simulate "just restarted" (a fresh test container is also a real just-restarted case).

## Verification

**Commands:**
- `ci/checks.sh all` -- expected: exit 0

## Implementation Notes

- Implemented by a coding subagent (2026-09-29). `dbwait.py` (AD-7 re-enqueue 900 s), `poison.py` (AD-2 guard, row from metadata, `poison_message{queue}`), `sweeper.py` (AD-2 map, orphan reconcile with blob check, 24 h key delete, `stuck_invoices`), claim/reclaim in domain + repository (no caller until 2.3+), `DatabaseOfflineError` only on connect failure, two metric alerts `ar-01/02`, `ar-11/12`.

## Plan Change Log

## Review Triage Log

**Pass 1 (2026-09-29): blind-hunter, edge-case-hunter, verification-gap, intent-alignment.** Counts: high 2, medium 14, low 6, false 0, maybe-false 1.

| # | Finding | Verdict | Route | Evidence / action |
|---|---------|---------|-------|-------------------|
| 1 | Sweeper re-enqueues to `q-extract`/`q-validate`/`q-post`, which have no consumer yet; `stuck_invoices` alert fires forever (intent b, B2, E4) | high | patch | Sweep only statuses whose queue has a consumer (`CONSUMED_QUEUES`, today `q-quality`); later stories extend it. |
| 2 | Orphan upload with bad metadata loops re-enqueue → poison every 15 min for 24 h (B3, E3, claim) | high | patch | Recover each orphan once: mark the key row (`recovered_at`, ETag-conditional) and skip marked rows. |
| 3 | AD-7 wait unbounded for permanent faults (identity, DNS) (B4) | medium | patch | Stop waiting when `now − first_enqueued_at` > 8 days (beyond the 7-day auto-restart): raise so the message poisons. |
| 4 | `poison_message` counted per retry; failing poison messages end in unwatched `*-poison-poison` (B5, E1, E2, claim) | medium | patch | Emit once on the final outcome; on the 5th failed attempt log `POISON_ABANDONED` at ERROR, emit, and acknowledge (invoice left for the sweeper). |
| 5 | Post poison routes an invoice waiting on a scheduled retry (E5) | medium | patch | Not an input state while `next_attempt_at` is in the future. |
| 6 | Pool size 2 exhausted by 6 concurrent functions → spurious failures (E6) | medium | patch | Pool sized to the pipeline's concurrent functions (6), timeout mapped to a retryable error. |
| 7 | Sweep aborts on a non-offline query error: no deletes, no metric (E8) | medium | patch | Each step isolated; log a code, continue, still emit. |
| 8 | Requeued stale invoices reset `first_enqueued_at` (B7) | low | patch | Use the invoice's `created_at`. |
| 9 | Unbounded stale scan and key listing; huge `IN` list (B8) | medium | patch | `LIMIT` per pass (rest next run); chunk `existing`. |
| 10 | Key delete without ETag can remove a re-created key (B9) | medium | patch | Carry the ETag; conditional delete. |
| 11 | Two clocks (DB vs app) for staleness (B10) | low | patch | Use the scan's DB `now` for the key cutoff and expiry. |
| 12 | `is_stale`/`NEVER_SWEPT` only used by tests (B11) | low | patch | Build the SQL from the domain constants or remove them. |
| 13 | Poison path downloads the whole blob for metadata (B12) | low | patch | Metadata-only read. |
| 14 | Sweeper run results barely visible (B13) | low | patch | Log requeued, orphans, deleted and failure counts on `sweeper.done`. |
| 15 | Poison lease guard on routing unpinned (VG1) | medium | patch | Test a lease renewed between read and route for extract/validate/post. |
| 16 | Deleting an already-gone key tested only with a fake exception (VG2) | low | patch | Wire-level test with the real batch 404 response (or the SDK's `TableTransactionError`). |
| 17 | Alert metric namespace assumed; `skip_metric_validation` hides mistakes (B6, intent e) | medium | defer | Verify on the first Dev deploy (runbook step in `infra/bootstrap/README.md`). |
| 18 | Host completion / visibility delay / pooled-connection behaviour only simulated (intent c) | medium (unverified) | defer | Confirm on Dev: stop the server, upload, check the 15-min re-enqueue. |
| 19 | Claim/reclaim has no production caller yet (intent a, B11 part) | low | reject | Stages that claim arrive with 2.3+; covered by repository tests. |
| 20 | Unbounded re-enqueue of the same invoice (B1) | maybe-false | reject | With row 1, only consumed queues are swept; duplicates are harmless (AD-2) and each ends in a state change or the poison path. |
| 21 | `created_at` stored as a string never matches the filter (E7) | low | reject | This project's writer stores `Edm.DateTime` (Story 1.8). |
| 22 | Root-stack alert wiring and DB settings not asserted at root level | low | reject | Covered by the 2.1 deferral. |
