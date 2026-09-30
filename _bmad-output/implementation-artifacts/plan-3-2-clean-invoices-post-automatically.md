---
title: 'Story 3.2: Clean invoices post automatically'
type: 'feature'
ticket: '3-2-clean-invoices-post-automatically'
created: '2026-09-30'
status: 'built'
route: 'full'
route_source: 'auto'
baseline_revision: '58ad6e492f980ac0e7badf4906cdb08b1aeb0704'
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

**Problem:** Invoices that pass every check stop at `ready_to_post`; nothing sends them to the accounts system, so clean invoices still need keying.

**Approach:** Add the `post` pipeline stage and an `AccountsPort` whose one adapter (`adapters/accounts_xml/`) builds the invoice XML with 3.1's builder and posts it to `ACCOUNTS_BASE_URL` with the pipeline's managed-identity token. The stage claims with the `next_attempt_at` gate, saves `accounts_ref` before `posted`, and on accounts errors backs off 1/5/15/60 minutes from `post_failures`, routing `ACCOUNTS_API_ERROR` on the 5th failure (AD-3, AD-10).

## Boundaries & Constraints

**Always:** claim `ready_to_post → posting` only when `next_attempt_at` is null or past; an early message is re-enqueued with the remaining delay and acknowledged; `accounts_ref` saved under `invoice_id` before the move to `posted`, and `posted_at` = that `status_history` row's `at` (one transaction); a retry that finds `accounts_ref` never calls the accounts system; the adapter never retries; on an accounts error, one transaction moves `posting → ready_to_post`, increments `post_failures`, sets `next_attempt_at` (1, 5, 15, 60 min for failures 1–4), releases the lease, then re-enqueues with that delay; the 5th failure (from `post_failures`, never `QueueMessage.attempt`) routes `ACCOUNTS_API_ERROR` with the API error code/status in `detail` (no document, no values); `post_failures` resets to 0 when entering `ready_to_post` from `validating` or `in_admin_queue`; the token only goes to `ACCOUNTS_BASE_URL`'s origin; posted values come from the AD-18 current values (never rounded — the builder refuses bad values, which is an accounts-side error path, not a crash); no field values in logs; the sweeper re-enqueues a stale `ready_to_post`/`posting` invoice respecting `next_attempt_at` and never touching `post_failures`.

**Never:** Approve (3.3); search (3.4); a real on-premises adapter; changes to accounts-sim beyond what 3.1 built; more than **3** new test cases.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Post | `ready_to_post`, `next_attempt_at` null | claim → `posting`; XML from current values posted; `accounts_ref` saved; → `posted`, `posted_at` = history `at` | — |
| Early message | `next_attempt_at` in the future | same message re-enqueued with the remaining delay; no claim, no call | — |
| Saved ref | retry after `accounts_ref` saved (e.g. crash before the move) | no accounts call; → `posted` | — |
| Accounts error 1–4 | 5xx / 4xx / timeout / 429 | one transaction: `posting → ready_to_post`, `post_failures`+1, `next_attempt_at` +1/5/15/60 min, lease released; re-enqueued with that delay | message completed (no dequeue used) |
| 5th failure | `post_failures` reaches 5 | `route_to_admin(ACCOUNTS_API_ERROR)` with `{status, code}` in detail; never poisoned | — |
| Builder refuses | current values break the XSD | treated as an accounts error (code `XML_INVALID`) → same backoff/routing | — |
| Reset | invoice enters `ready_to_post` from `validating` or `in_admin_queue` | `post_failures` = 0 | — |
| Lost delayed message | invoice stuck in `ready_to_post` with `next_attempt_at` past | sweeper re-enqueues `q-post`; `post_failures` unchanged | — |
| End to end | clean upload → quality → extract (fake DI) → validate → post against accounts-sim in-process | reaches `posted` with an `accounts_ref`, no human action | — |

</frozen-after-approval>

## Code Map

- `backend/src/invoicing/apps/pipeline/extract.py`, `validate.py`, `function_app.py` -- stage patterns (claim, outcome, handler, enqueue after commit, `release_claim`, `wait_for_database`); `post_poison` trigger exists; `validate.py` enqueues `q-post`.
- `backend/src/invoicing/domain/status.py`, `transitions.py` -- `Stage.POST`, `CLAIM_STATUS`, `FINAL_TARGETS`; `plan_claim` needs the `next_attempt_at` gate for POST.
- `backend/src/invoicing/adapters/postgres/invoices.py` -- `_claim`, `transition_in`, `release_claim`; add the post-specific claim condition, failure/backoff write and the `post_failures` reset on transitions into `ready_to_post` from `validating`/`in_admin_queue` (used by 2.5 validate and later Approve).
- `backend/src/invoicing/adapters/postgres/schema.py` -- `invoice.post_failures`, `next_attempt_at`, `accounts_ref`, `posted_at`.
- `backend/src/invoicing/domain/current_values.py`, `adapters/postgres/validation.py` (`load`) -- current values for the XML.
- `backend/src/invoicing/adapters/accounts_xml/contract.py` -- `build_invoice_xml`, `XmlInvalidError`, result parsing; add the HTTP adapter here (`adapters/accounts_xml/client.py`), reusing `adapters/document_intelligence.py`'s `HttpTransport`/`AiohttpTransport` pattern and token-origin check.
- `backend/src/invoicing/apps/accounts_sim/*`, `adapters/postgres/sim_accounts.py` -- the in-process target for the end-to-end test.
- `backend/src/invoicing/domain/sweep.py` (`CONSUMED_QUEUES`), `apps/pipeline/sweeper.py`, `adapters/postgres/invoices.py` `_stale` -- add POST with the `next_attempt_at` rule.
- `backend/src/invoicing/apps/pipeline/settings.py`, `infra/modules/env-app/main.tf` (`app_specific_settings.pipeline`: `ACCOUNTS_BASE_URL` = accounts-sim host, `ACCOUNTS_AUDIENCE` = `api://<accounts_sim_client_id>`), tftest asserts; `adapters/postgres/engine.py` `POOL_SIZE` +1.
- Tests: `tests/apps/test_story_2_3_extract.py`, `test_story_2_5_validate.py`, `test_story_3_1_accounts_sim.py`, `_pipeline_fakes.py`, `_validation_seed.py`.

## Tasks & Acceptance

**Execution:**
- [x] `ports/accounts.py` (`AccountsPort.post_invoice(invoice) -> accounts_ref`, `AccountsError(status, code)`), `adapters/accounts_xml/client.py`, factory wiring in `apps/pipeline/function_app.py`.
- [x] Post claim gate, failure/backoff transaction, saved-ref path, `post_failures` reset, sweeper POST support.
- [x] `apps/pipeline/post.py` + trigger + settings + Terraform settings.
- [x] Tests (≤ 3 new cases): one DB stage test (post, early message, saved ref, failures 1–4 backoff and 5th routing, builder refusal, reset, sweeper recovery keeps the count); one end-to-end test chaining the real handlers from a clean upload to `posted` against accounts-sim in-process (fake DI, fake queue, fake blobs).

**Acceptance Criteria:**
- Given `ci/checks.sh all`, then it passes with ≤ 200 test cases.

## Implementation Notes

- **Ports and domain:** `ports/accounts.py` holds `AccountsPort`, `AccountsError(status, code)`, `InvoiceToPost` (ids, current PO, configured currency, AD-18 current values) and `PostingRepository` (`state`, `save_ref`, `finish`, `fail`). `domain/posting.py` holds the 1/5/15/60 ladder (`post_backoff`, `MAX_POST_FAILURES` 5), `PostRetry` and the reset rule (`resets_post_failures`).
- **Adapter:** `adapters/accounts_xml/client.py` maps current values to `AccountsInvoice` (a missing value is `XmlInvalidError`), builds with `build_invoice_xml`, and posts to `{ACCOUNTS_BASE_URL}/invoices` with a token for `{ACCOUNTS_AUDIENCE}/.default`, via the DI adapter's `HttpTransport` (no redirects). Every failure is one `AccountsError`: builder refusal `XML_INVALID` (status None), `TIMEOUT`, `UNREACHABLE`, an HTTP error with the body's `code` when it looks like a code (else `HTTP_<status>`), or `BAD_RESULT`. `contract.py` gained `parse_result` (defused, reference must be a short code).
- **Store:** `adapters/postgres/posting.py`. `fail` locks the row, counts, then either `transition_in(posting -> ready_to_post, post_failures, next_attempt_at = now() + delay, lease cleared)` or `route_in` plus `post_failures = 5`. `finish` sets `posted_at = now()` in the history row's transaction. `PostgresInvoiceRepository._transition` resets `post_failures` to 0 **and clears `next_attempt_at`** on `validating/in_admin_queue -> ready_to_post` (clearing the backoff too is an unattended addition, so an approved invoice is never held by an old wait). `transition_in` takes extra columns.
- **Stage:** `apps/pipeline/post.py`. The claim gate already existed (`claim_from`); a refused claim reads `state()` and re-enqueues an early message unchanged with the remaining delay (ceil, at least 1 s). A retry is re-enqueued with `attempt + 1` (informational). The routing's `detail` is `{status, code}` only. Validate's line read now includes `description` and `material_id` (posted with each line).
- **Wiring:** `post` trigger on `q-post`; `CONSUMED_QUEUES` includes POST; `POOL_SIZE` 9; settings `ACCOUNTS_BASE_URL` (`https://<accounts-sim function app>.azurewebsites.net/api`, from the app name, since the module output would be a cycle) and `ACCOUNTS_AUDIENCE` (`api://<accounts_sim_client_id>`), asserted in the env-app, Dev and Prod tftests.
- **Tests:** 2 new cases in `tests/apps/test_story_3_2_post.py` (stage matrix; end to end with accounts-sim in-process), plus assertions in `test_function_apps.py`. `ci/checks.sh all` passes, 184 test cases.
- **Review fixes:** `total_tax` and a line's `description` are optional in `invoice-v1.xsd` (minOccurs 0) and left out when None. A token failure or timeout (30 s) is `UNREACHABLE` and backs off. Reading an error body also tolerates a `RecursionError`. `parse_result` matches `<result>`/`<accounts_ref>` by local name. A reference `save_ref` could not keep is logged as `post.orphan_ref` (`accounts_ref` is now an allowed log key). The stage test covers each case; a malformed `ACCOUNTS_AUDIENCE` stops the app.

## Plan Change Log

## Review Triage Log

Pass 1 (2026-09-30, unattended). Lenses one at a time: edge-case-hunter, verification-gap; plus the implementer's risk 1. Verdicts: high 0, medium 9, low 3, false 3.

| # | Lens | Finding | Verdict | Route | Evidence |
|---|------|---------|---------|-------|----------|
| I1 | implementer | Contract requires `total_tax` and a description per line; invoices without them wait ~81 min then land in the admin queue | medium | patch | common on real invoices; make both optional (minOccurs 0) in invoice-v1.xsd and the builder |
| E1/V-other | both | Token failure is outside the try: skips the backoff, poisons as PROCESSING_FAILED | medium | patch | wrap `get_token` (with a timeout) into `AccountsError(UNREACHABLE)` |
| E2 | edge | Accounts stored the invoice but `save_ref` finds it no longer posting: ref lost | low | patch | log `post.orphan_ref` with the ref; accounts-sim is idempotent, so a later re-post returns the same ref |
| E3 | edge | Saved ref + routed + corrected → reuse posts stale values | false | reject | with `accounts_ref` no Correct is offered (2.10 guard); only Approve (3.3) |
| E4 | edge | Foreign currency posted as SGD | false | reject | currency is configuration (AD-8), the same everywhere |
| E5 | edge | Namespaced `<result>` from a real system → BAD_RESULT | low | patch | compare local names |
| E6 | edge | Deeply nested JSON error body → RecursionError escapes | low | patch | catch it |
| E7 | edge | Sweeper and delayed messages requeue each other | false | reject | both wait for `next_attempt_at`; the second claim fails and is acknowledged |
| V1 | gap | Non-accounts failure path (release_claim + StageFailed) never exercised | medium | patch | without the release, retries are swallowed |
| V2 | gap | UNREACHABLE and BAD_RESULT mappings, `parse_result` rejection unverified | medium | patch | a reset or garbage 2xx would skip the ladder |
| V3 | gap | Error-code filter keeping free text out of admin_item detail untested | medium | patch | security.md rule 31 |
| V4 | gap | `ACCOUNTS_AUDIENCE` pattern unverified | medium | patch | one tuple in the malformed-settings list |
| V5 | gap | Line mapping (description, unit_price) only partly asserted | medium | patch | assert the full posted line |

## Design Notes

Decisions made unattended (Dj asleep, 2026-09-30):
- **Token scope** `api://<accounts_sim_client_id>/.default` via `ACCOUNTS_AUDIENCE`, sent only to `ACCOUNTS_BASE_URL`'s origin (like the DI adapter).
- **Every accounts-side failure counts** (HTTP errors, timeouts, the builder refusing a document), so a broken invoice ends in the admin queue after 5 tries instead of the poison queue.
- **Backoff table** 1, 5, 15, 60 minutes for failures 1–4; the 5th routes.
- **End to end runs in-process** (the accounts-sim handler behind a transport fake) — the real HTTP hop is checked on the first Dev deploy.

## Verification

**Commands:**
- `ci/checks.sh all` -- expected: all checks pass, test cases ≤ 200.
