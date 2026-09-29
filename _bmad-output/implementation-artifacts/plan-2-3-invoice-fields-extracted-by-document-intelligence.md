---
title: 'Story 2.3: Invoice fields are extracted by Document Intelligence'
type: 'feature'
ticket: '2-3-invoice-fields-are-extracted-by-document-intelligence'
created: '2026-09-30'
status: 'built'
route: 'full'
route_source: 'auto'
baseline_revision: 'cfdcb9711337b26c027fbec065c2f9b020d42639'
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

**Problem:** Invoices stop at `awaiting_extraction`: nothing reads their fields, so validation (2.5/2.6) and the admin queue (2.8–2.10) have no data.

**Approach:** An `extract` queue stage claims the invoice, calls Document Intelligence `prebuilt-invoice` (API 2024-11-30) through one adapter that enforces the per-environment rate limit and page cap in PostgreSQL, maps the result into AD-18 rows (bank values encrypted from the first write), then moves the invoice to `awaiting_validation`. Terraform grants the `pipeline` identity Cognitive Services User on the shared DI and adds the 80 % page alert.

## Boundaries & Constraints

**Always:** AD-3 claim-before-side-effect and save-before-finish; AD-7 re-enqueue (DB down, and DI 429 after `Retry-After`) without using a dequeue; AD-8 one caller, managed identity via the custom subdomain, ≤1 request per 2 s including polls, pages reserved under `pg_advisory_xact_lock` before analyze; AD-11 bank values normalised, `pgp_pub_encrypt` in SQL plus HMAC fingerprint, never plaintext in any row, log or error; AD-18 field ids and row shapes; bound parameters only; no new PyPI dependency (REST over the existing `aiohttp` + `azure-identity`).

**Never:** store the raw DI response; call DI from anywhere but `adapters/document_intelligence.py`; train models; add validation logic (2.5/2.6); touch admin actions (2.10); add more than **one** new test case (repo is at 197 of the 200 cap: `coding-style.md` rule 20 exception).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy path | `q-extract` msg, invoice `awaiting_extraction` | claim → `extracting` (10 min lease); one run, header fields, lines saved; → `awaiting_validation`; `q-validate` enqueued; `di_pages_used_pct` emitted | — |
| Bank fields | DI returns `PaymentDetails[0]` with account/IBAN/SWIFT | `payment[0].bank_account_number` etc. rows hold ciphertext + fingerprint; no plaintext anywhere | — |
| Retry after saved run | run `created_at` > latest entry into `awaiting_extraction` | run reused, DI not called, no pages counted | — |
| Retry with saved Operation-Location | operation saved, no run | resumes polling, no second analyze, no new page reservation | — |
| Re-extract | invoice re-entered `awaiting_extraction` after the last run | DI called again, new run saved | — |
| Claim lost | claim changes 0 rows | message acknowledged, nothing else | — |
| Throttle | last call < 2 s ago | waits the remainder before the request | clock/sleep injected in tests |
| 429 | DI 429 with `Retry-After: n` | same message re-enqueued with delay n, original completed; invoice left `extracting` (lease expires; retry resumes) | no dequeue used |
| Page cap | month pages + needed > cap (Dev 100, Prod 400) | `route_to_admin(EXTRACTION_QUOTA)`; no DI call | — |
| DI quota error | DI 403 with a quota error code | reservation kept; `route_to_admin(EXTRACTION_QUOTA)` | — |
| Other DI/analysis failure | 5xx, failed operation | raise → message retried; poison route (existing) after 5 | code logged, no values |

</frozen-after-approval>

## Code Map

- `backend/src/invoicing/domain/status.py`, `transitions.py` -- `Stage.EXTRACT`, `CLAIM_STATUS`, `FINAL_TARGETS`, `plan_claim`, `plan_transition`, `route_to_admin`, `AdminReason`: reuse, don't change.
- `backend/src/invoicing/domain/sweep.py` -- add `Stage.EXTRACT` to `CONSUMED_QUEUES` (comment asks for it).
- `backend/src/invoicing/domain/reasons.py` -- `ReasonCode.EXTRACTION_QUOTA` exists.
- `backend/src/invoicing/domain/suppliers.py` -- `BANK_FIELD_IDS`, `normalise_bank_value`, `bank_fingerprint`: reuse.
- `backend/src/invoicing/ports/invoices.py` -- `InvoiceRepository.claim/transition/route_to_admin/state`.
- `backend/src/invoicing/ports/queue.py` -- `QueueName.EXTRACT/VALIDATE`, `QueueSender.send(..., delay_seconds=)` for 429.
- `backend/src/invoicing/ports/metrics.py` -- `MetricName.DI_PAGES_USED_PCT` exists (0–100).
- `backend/src/invoicing/adapters/postgres/invoices.py`, `schema.py` -- repository and Core tables; add new tables to `schema.py`.
- `backend/src/invoicing/adapters/postgres/suppliers.py` -- `BankKeys`, `_upsert_bank` (pattern: `func.pgp_pub_encrypt(normalised, func.dearmor(public_key))`).
- `backend/src/invoicing/adapters/key_vault.py` -- `read_secrets(vault_uri, names, credential)`; secret names `pgp-public-key`, `hmac-key` (constants in `tools/load_suppliers.py`).
- `backend/src/invoicing/apps/pipeline/quality.py` -- stage pattern to copy (`*_handler`, `StageFailed`, `correlation_span`, enqueue after commit, re-raise `DatabaseOfflineError`, `log_event`).
- `backend/src/invoicing/apps/pipeline/function_app.py` -- wire `extract` trigger with `wait_for_database(QueueName.EXTRACT, ...)`; `extract_poison` already exists.
- `backend/src/invoicing/apps/pipeline/settings.py` -- add `di_endpoint`, `invoice_currency` (default `SGD`), `di_monthly_page_cap`.
- `backend/src/invoicing/adapters/postgres/engine.py` -- `POOL_SIZE` +1 for the new stage (comment says so).
- `backend/migrations/versions/0004_master_audit.py` -- latest; new `0005_extraction.py`, `down_revision="0004_master_audit"`; copy `_roles()`/`_grants()` style; field/line/run tables append-only (REVOKE UPDATE from pipeline/staff_api), `di_usage` and `di_operation` S/I/U for pipeline only.
- `backend/tests/conftest.py` -- extend the `pipeline_engine` TRUNCATE list and `APP_ONLY_SETTINGS["pipeline"]`.
- `backend/tests/apps/_pipeline_fakes.py` -- `FakeQueue`, `FakeMetrics`, `invoice_id`; `backend/tests/_pgp.py` `make_test_key_pair()`.
- `infra/modules/env-app/main.tf` -- `listed_role_assignments` (add `pipeline/cognitive/di`), `app_specific_settings.pipeline` (DI endpoint, currency, cap), new `azurerm_monitor_metric_alert.di_pages_used_pct` like `poison_message`; header comment says these come in 2.3.
- `infra/modules/env-app/variables.tf` -- widen `metric_alert_names` validation; add `document_intelligence_id`, `document_intelligence_endpoint`, `di_monthly_page_cap`.
- `infra/modules/naming/main.tf` -- `metric_alert_order` add `di_pages_used_pct` (ar-03 dev, ar-13 prod).
- `infra/{dev,prod}/foundation/outputs.tf` -- pass through `document_intelligence_id/endpoint` from `terraform_remote_state.shared`; `infra/{dev,prod}/app/main.tf` pass them plus cap (dev 100, prod 400) to `module "app"`.
- `infra/modules/env-app/tests/env_app.tftest.hcl`, `infra/dev/app/tests/app.tftest.hcl` -- extend existing runs' asserts; add no `run` block.

## Tasks & Acceptance

**Execution:**
- [x] `backend/migrations/versions/0005_extraction.py` + `adapters/postgres/schema.py` -- `extraction_run`, `invoice_field` (value_text/number/date, currency, confidence, page, polygon jsonb, source, bank_ciphertext bytea, bank_fingerprint), `invoice_line`, `di_usage(month PK, pages, last_call_at)`, `di_operation(invoice_id PK, operation_location, created_at)`; CHECKs, grants -- AD-18/AD-8/AD-11.
- [x] `backend/src/invoicing/ports/extraction.py` -- `ModelSelector` (default `prebuilt-invoice`), `DocumentAnalyzer` port, `ExtractionRepository` port, result dataclasses (fields, lines, pages) -- domain stays framework-free.
- [x] `backend/src/invoicing/domain/extraction.py` -- pure mapping of DI JSON to AD-18 field ids/rows (snake_case, `InvoiceId`→`invoice_number`, `line[n].x`, `payment[n].bank_account_number|iban|swift`), line confidence = min of checked fields, currency from settings.
- [x] `backend/src/invoicing/adapters/document_intelligence.py` -- REST analyze + poll with `Operation-Location`; token for `https://cognitiveservices.azure.com/.default`; PG-backed throttle and page reservation (`pg_advisory_xact_lock`), injectable clock/sleep; 429 → `DiThrottled(retry_after)`, quota 403 → `DiQuotaExceeded`.
- [x] `backend/src/invoicing/adapters/postgres/extraction.py` -- save run+fields+lines in one transaction with the final transition; bank rows encrypted in SQL; `latest_run_since_entry`, `saved_operation`.
- [x] `backend/src/invoicing/apps/pipeline/extract.py` + `function_app.py`, `settings.py`, `engine.py`, `domain/sweep.py` -- the stage per the matrix; keys read once from Key Vault; emits `di_pages_used_pct`.
- [x] `infra/...` (Code Map list) -- role assignment, settings, alert (threshold 80, `var.action_group_id`), outputs pass-through, naming.
- [x] `backend/tests/apps/test_story_2_3_extract.py` -- **one** test against the PG container with a fake DI covering, as sequential assertions: happy path + AD-18 ids + no plaintext bank value in any column, reuse on retry, resumed polling, Re-extract calls DI again, 429 re-enqueue, page cap, throttle wait. Terraform asserts added to existing runs.

**Acceptance Criteria:**
- Given `ci/checks.sh all`, when run, then it passes with ≤ 200 test cases and backend coverage ≥ 80 %.
- Given `<env>/app` planned, then the `pipeline` identity has Cognitive Services User on the DI id and `ar-03`/`ar-13` alert at 80 % of the cap.

## Implementation Notes

Implemented 2026-09-30 (unattended). Choices the plan left open, and small departures:

- **Lease ended on a 429 and on any other failure** (`InvoiceRepository.release_claim`, new): with a live 10-minute lease the re-enqueued message (after `Retry-After`) or the host's own retry would find the claim held and be acknowledged, so the invoice would wait for the sweeper. Ending the lease (status stays `extracting`) lets the retry reclaim at once (AD-3 "an expired lease may be reclaimed"), and makes the matrix's "retried; poison route after 5" reachable. `status.py`/`transitions.py` unchanged.
- **Final transition ends the lease** (`PostgresInvoiceRepository.transition_in`, used by `save_run`), so `awaiting_validation` holds no stale lease. The reuse path finishes with the existing `transition`, which leaves it (harmless: `awaiting_validation` is an input status).
- **Months and times**: the page month is the database's UTC month (`date_trunc('month', timezone('UTC', now()))`); the throttle's `last_call_at` comes from the injected clock, so tests move time without sleeping. A reservation's month is re-derived on resume from `di_operation.created_at`; its size from the content type (`pages_to_reserve`), so `di_operation` keeps exactly the planned columns.
- **Reservation given back** (review fix): when the analyze call or saving its `Operation-Location` fails (429, 5xx, bad location), the reserved pages are subtracted again under the lock (floor 0; `last_call_at` kept). A DI quota 403 keeps its reservation, as the matrix says. Only a process crash between reservation and save can still over-count, towards the cap, never past it.
- **Dead operations forgotten** (review fix): a resumed operation that DI reports as expired (404) or failed/canceled is deleted from `di_operation` (`ExtractionRepository.forget_operation`; 0005 grants the pipeline DELETE on that table only), so the next retry analyses afresh.
- **PaymentDetails** is stored only through `payment[<n>].*`; a non-array PaymentDetails is skipped. A currency, number or date field whose value doesn't parse gets confidence 0 (AD-18: missing), which also feeds the line minimum.
- **Field ids**: `line[<n>]` counts from 1 (= `invoice_line.line_no`, like PO lines); `payment[<n>]` from 0, as the matrix gives it. Other DI lists flatten the same way (`<name>[<n>].<field>`).
- **Numbers**: extracted numbers are unconstrained `numeric` (exact, never rounded on write); confidence is `double precision`. DI JSON is parsed with `parse_float=Decimal`.
- **Bank keys** are read from Key Vault on the first run that holds a bank value and kept (`BankKeysLoader`), so the app starts without Key Vault. The secret-name constants moved from `tools/load_suppliers.py` to `adapters/key_vault.py` (the loader and the script share them).
- **Quota 403 detection**: an error code in `QUOTA_CODES` or "quota" in DI's code/message. `[ASSUMPTION]` in the adapter: confirm the exact F0 code on the first quota error in Dev.
- **Grants** are explicit in 0005: each new table first loses what 0001's default privileges gave, then gets its own (`di_usage`/`di_operation`: pipeline S/I/U, nothing for staff-api).
- `StageFailed` now names its stage (default `quality`), and `failure_code` is public so `extract` reuses it.
- **Tests**: one new case (`test_story_2_3_extract_stage`: happy path with throttle wait and ≥ 2 s spacing, AD-18 ids, bank ciphertext decrypts to the normalised value, no plaintext in any intake row or log, claim lost, reuse, Re-extract, 429 re-enqueue, resumed polling, other failure, DI quota 403, page cap). Asserts added to existing tests only: pipeline `extract` trigger (`test_function_apps`), append-only statements (`test_migrations` REFUSED), and the Terraform runs of `env-app`, `dev/app`, `prod/app`, `dev/foundation`, `prod/foundation` (the last four needed the DI values in their mocked remote state anyway). Review fixes added assertions only: `test_story_1_6_key_vault` (`BankKeysLoader` reads once), `test_migrations` (the AD-11 bank checks refuse both bad rows), `test_pipeline_sweeper` (a stale `awaiting_extraction` goes to `q-extract`), and the 2.3 test (dead operation forgotten, 429 on analyze gives pages back, 1-page PDF reserves 2 and settles at 1, non-array PaymentDetails not stored, unparsed amount confidence 0). Repo total 198 of 200.
- `infra/bootstrap/README.md` names the new alert rules (`ar-03` Dev, `ar-13` Prod).

## Plan Change Log

## Review Triage Log

Pass 1 (2026-09-30, unattended). Lenses run one at a time (Dj: one agent at a time): edge-case-hunter, verification-gap. Blind-hunter and intent-alignment skipped; the orchestrator read the adapter, stage and repository against the intent. Verdicts: high 1, medium 7, low 6, false 2.

| # | Lens | Finding | Verdict | Route | Evidence |
|---|------|---------|---------|-------|----------|
| E1 | edge | Pages reserved before the analyze POST leak when the POST fails (429, 5xx, bad location); retries reserve again | medium | patch | `analyze` calls `_acquire(needed)` then `_start`; no release path; reconcile only in `_save_run` |
| E2 | edge | Save of Operation-Location fails after 202, retry analyses twice | low | reject | needs a DB failure in the ms after the POST; fix (in-memory retry) adds complexity |
| E3 | edge | Expired (404) or failed saved operation is polled on every retry, never re-analysed | medium | patch | `saved_operation` returns it on each retry; nothing clears it; realistic after an overnight DB stop (op expires in 24 h) |
| E4 | edge | Succeeded result without analyzeResult/documents saves an empty run | low | reject | a non-invoice image still returns `pages`; missing `analyzeResult` on success is not a documented DI shape |
| E5 | edge | Instance clock skew stalls or breaks the 2 s spacing | low | reject | Azure hosts are NTP-synced; wait is clamped to 2 s |
| E6 | edge | Poll loop outlives the 10-minute lease under concurrency | false | reject | `host.json` batchSize 1, one instance per function (AD-2): 60 polls ≈ 2 min |
| E7 | edge | Sweeper re-enqueues during Retry-After | low | reject | the DB throttle still spaces DI calls; the duplicate is acknowledged by the claim |
| E8 | edge | Reservation month derived from `di_operation.created_at` at a month boundary | low | reject | a window of milliseconds at UTC midnight on the 1st; drift of ≤ 2 pages |
| E9 | edge | `PaymentDetails` not typed `array` is saved as plaintext `payment_details` text | high | patch | `map_invoice` sends non-array fields to `_field_row(field_id_for(...))`; `payment_details` is not a bank field id, so the DB check does not catch it (AD-11) |
| E10 | edge | Typed value that fails to parse keeps DI's confidence | medium | patch | `_field_row` keeps `confidence` when `value_number`/`value_date` is None; AD-18 counts a missing checked field as 0 |
| E11 | edge | Validate cannot fill `invoice_line.po_line_id/material_id` (pipeline has SELECT, INSERT only) | medium | defer | AD-18 says validate fills them; that grant belongs to Story 2.5's migration |
| E12 | edge | `line[n].x` field ids never emitted | false | reject | lines are `invoice_line` rows (AD-18); `line[n].x` ids name them for reasons and are derived from `line_no` |
| E13 | edge | Reconcile runs only on a saved run | medium | patch (with E1) | same root cause as E1 |
| E14 | edge | Docstring claims cross-instance limit despite instance clocks | low | reject | see E5 |
| V1 | gap | PDF reserve-2-then-reconcile never exercised | medium | patch | every test invoice is JPEG with 1 page, so `_reconcile` returns early |
| V2 | gap | `BankKeysLoader` untested | medium | patch | no test builds it; secret swap or lost cache would pass |
| V3 | gap | AD-11 bank checks in 0005 never exercised | medium | patch | no refused-insert assertion |
| V4 | gap | `Stage.EXTRACT` in `CONSUMED_QUEUES` not pinned | medium | patch | sweeper tests monkeypatch or seed only `received` |
| V5 | gap | `release_claim` raising masks the original error | low | reject | only when the DB is down, where `DatabaseOfflineError` is the right outcome (AD-7) |

## Design Notes

Decisions made unattended (Dj asleep, 2026-09-30):
- **REST, not the DI SDK**: the adapter must own every request (throttle, polling, saved `Operation-Location`); the SDK's poller hides requests. No new dependency.
- **Page reservation**: F0 analyses at most the first 2 pages, so reserve 2 for a PDF and 1 for an image, then reconcile to the result's page count in the same transaction as the run.
- **`di_operation` table** (not a column on `invoice`): keeps `invoice` unchanged; reused only if created after the latest entry into `awaiting_extraction`, like runs.
- **DI values reach `<env>/app` through `<env>/foundation` outputs**, which already read the shared state; no second remote state in the app stack.
- **Test budget**: one merged test; this leaves 2 cases for the rest of Epic 2, so later stories must merge or replace tests.

## Verification

**Commands:**
- `ci/checks.sh all` -- expected: all checks pass, test cases ≤ 200.
