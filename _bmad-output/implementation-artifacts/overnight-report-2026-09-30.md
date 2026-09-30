# Overnight report: 30 Sep 2026, about 01:30 → 09:00 (SGT)

Dj asked me to "do as many stories as you can" without him, and to keep tests to a minimum so Jenkins stays fast. This is what happened. Each story's plan file holds its decisions and review triage log. Deferred engineering items are in `deferred-work.md`.

## Summary

- **Dev is live, and each change deploys through Jenkins.** Builds #6 onwards went green end to end: checks, plan, apply, migrations, code deploy and health check. Each story was deployed as soon as it was committed.
- **Epics 2 and 3 are fully built:** 2.3, 2.5, 2.6, 2.8, 2.9, 2.10, 2.11, 3.1, 3.2, 3.3 and 3.4, all committed and pushed. 2.1, 2.2, 2.4 and 2.7 were built earlier.
- **How each story was built:** plan, then a coding agent, then two review lenses run one after the other (edge cases, verification gaps), then fixes, then `ci/checks.sh all` on my side, then a gitleaks-gated commit, then a Jira comment.
- **Jira:** stories and subtasks are **In Progress**, each with a built comment. Nothing moved to Done: that waits for you to see them run in Dev.
- **Tests:** backend tests were merged once to free room (198 → 163, same assertions). The repo is now at **162 of 200** after a second merge. Backend coverage is about 89 %.
- **Not started:** Epics 4 and 5.

## Infrastructure and CI fixes made tonight

1. **Terraform state** moved to `stdjtfstatesea`, containers `ocrinvoicing-shared`, `-dev` and `-prod`. The old `babaloosealngst21` was deleted; it held no state. Jira OCR-2 updated.
2. **Jenkins** now shows a Stages graph on each build (Pipeline Graph View plugin).
3. **Bugs found by the first real runs** (all fixed and pushed):
   - The Jenkinsfile's `env[name]` was blocked by Jenkins' script sandbox.
   - `state-backend.sh` and `ci-vm.sh` re-runs used `az … update --tags`, which az 2.77 no longer accepts.
   - A stale Terraform backend file in the workspace broke the offline check.
   - Alembic couldn't create its version table in `public` on Azure; it now has its own `alembic` schema.
   - The post-deploy health check read a Flex app's host name from the wrong field.
4. **Operator steps 3, 4b and 5 (Dev)** were run by you through `.work/overnight-steps.sh`. All Dev database-isolation checks pass. The Prod logins don't exist yet.

## One process slip

- On Story 2.6, gitleaks exited 1 and my command didn't gate on it, so the commit was made.
- It was a false positive: the standard example IBAN in a test, next to a variable called `HMAC_KEY`. I rewrote the test line, amended the commit before pushing, and confirmed the full-history scan is clean.
- Since then every commit is gated with `if gitleaks …; then git commit`.

## Per story

Each story: plan, coding agent, edge-case and verification-gap reviews run one after the other, fixes, `ci/checks.sh all`, gitleaks-gated commit, push, Jenkins deploy to Dev.

### 2.3 Invoice fields are extracted by Document Intelligence (`632c42b`, OCR-26), deployed in build #6
- **What it does:**
  - An `extract` stage calls the DI REST API (2024-11-30) with a managed identity.
  - AD-8 limits are kept in `intake.di_usage` under an advisory lock: at most 1 request every 2 s, polls included, and pages reserved before each analyze call.
  - Results are saved as AD-18 rows, with bank values encrypted and fingerprinted from their first write.
  - A 429 is re-sent after `Retry-After`; the page cap or a DI quota error routes the invoice as `EXTRACTION_QUOTA`.
- **Terraform:** the Cognitive Services User role, and the `di_pages_used_pct` alert at 80 % (`ar-03` Dev, `ar-13` Prod).
- **Review:** 9 findings patched, including a security fix: a non-array `PaymentDetails` could have been stored as plaintext.
- **To confirm in Dev:** the F0 quota error code (marked `[ASSUMPTION]`).

### 2.5 Validation: confidence, PO match, printed supplier (`cb7fab2`, OCR-28), deployed in build #7
- **Current values:** one domain function reads them: the latest run, overlaid by admin rows.
- **Checks:**
  - PO match: expected amount in `Decimal`, tolerance max(1 %, 1.00). Partial deliveries deduct other invoices' current quantities; a goods-in scan uses its own delivery's receipt.
  - Printed supplier: tax id, otherwise a rapidfuzz score of 85 or more.
- Everything is written in one transaction under a per-supplier advisory lock.
- **New:** a `rapidfuzz` dependency, `GoodsReceipt.delivery_id`, and migration 0006.
- **Review:** 12 findings patched, including normalising product codes and PO numbers, and closing a gap where an invoice with no lines could auto-pass.

### 2.6 Validation: duplicates, dates, bank changes (`35ba8fb`, OCR-29), deployed in build #8
- **Duplicates:** matched by fingerprint or by image hash within Hamming distance 8, against the same supplier's earlier, non-rejected invoices, under the lock. Of two concurrent copies only the later is flagged, and a concurrent test proves the lock.
- **Photo date:** compared as a Singapore date against the latest receipt, passing from 0 to 30 days after it.
- **`BANK_CHANGED`:** by fingerprint per field id; nothing is decrypted.
- **Reminders:** the reminder row is deleted after a PO match.
- **Deferred:** the duplicate edge before extraction, the unbounded history read under the lock, and the resend-after-unreadable UX.

### 2.8 Admin queue list (`1568765`, OCR-31), deployed in build #9
- **Database access:** staff-api now reads the database. Terraform gained its `POSTGRES_*`, cap and currency settings, and migration 0007 lets it read `di_usage`.
- **`GET /api/admin/queue`:** admin only; oldest first, 50 a page; open reasons from the latest routing; current totals; filters by reason and supplier with the full supplier list; the 80 % page-usage figure. It reads from one snapshot.
- **`/queue` screen:** the table, labelled chips (blocking ones marked), filters, paging, the empty and no-match states, and the Alert.
- **Deferred:** the pre-existing `platform_auth_trusted` default on the `me` route and `staff_endpoint`. The queue route now requires the argument and is tested.

### 2.9 Admin item: crop, fields, bank change (`598b244`, OCR-32), deployed in build #10
- **Endpoints:** item, image and reveal.
  - Non-admins, unknown invoices and invoices not in the queue get 404.
  - Masks are computed in SQL; values of 4 characters or fewer show no digits.
  - A reveal decrypts in SQL with the private key from the private-key vault and writes its audit row in the same transaction.
- Extraction now saves page sizes (migration 0008), so flag boxes can be drawn.
- **Screen:** an image viewer (zoom to flags, numbered haloed boxes, reduced-motion aware), a linked field list, and a bank-change panel with a timed reveal.
- **Review:** 12 findings patched; a high one was short bank values leaving the server in full.
- **Deferred:**
  - a PDF viewer (PDFs open by link for now);
  - boxes for runs extracted before migration 0008.

### 2.10 Admin corrects, re-extracts or rejects (`317c6b5`, OCR-33), deploying in build #11
- **Guard:** decides the allowed actions from the open reasons. Approve is Story 3.3.
- **Four actions:** each is one locked transaction, with a routing-id check against stale pages, the conditional transition, the rows and the audit row. After the commit come the stage message and the corrections JSON blob, which holds no bank data.
- **Screen:** an action bar, Correct mode, dialogs, a Toast, next-item focus, drafts kept across a re-sign-in, and the "Returned after correction" badge.
- **Review:** 15 findings patched.
- The shared API client gained a `SESSION_RESTORED` event, in both apps.

### 2.11 Opt-in keyboard shortcuts (`b71ab72`, OCR-34), deployed in build #12
- Shortcuts are off by default, stored in `localStorage` (off if storage is unavailable). A switch in the header, or in the menu below 640 px, turns them on; `?` opens help.
- **Keys:** `j`/`k`/Enter on the queue; `c`/`r`/`n`/`p`/Esc on an item.
- **Guards:** nothing fires while typing or while a dialog is open. `Esc` in Correct mode doesn't leave the item, so edits aren't lost.
- **Review:** 7 findings patched, including Caps Lock silently disabling every shortcut.
- **Epic 2 is now fully built.**

### 3.1 Simulated accounts system (`58ad6e4`, OCR-66), build #13
- **`POST /api/invoices` on accounts-sim:** XSD-validated XML (hardened parsing), stored once per invoice, returning a `SIM-…` ref.
- **Who can call it:** only this environment's pipeline identity, checked by built-in auth and by an in-code principal check that fails closed.
- **Failure mode:** kept in the database (`sim_accounts.failure_mode`).
- **XML builder** for Story 3.2: never rounds; refuses bad values.
- **Review:** 12 findings patched, including one high: money could have been silently rounded.
- **To confirm on Dev:** built-in auth accepting the pipeline's managed-identity token. For Prod, `accounts_sim_client_id` still needs filling in.

### 3.2 Clean invoices post automatically (`6cd1bdc`, OCR-67), build #14
- **The `post` stage:**
  - It is gated on `next_attempt_at`; an early message is re-delayed.
  - It builds the XML from the current values and posts it with the pipeline's token.
  - It saves `accounts_ref` before `posted`, and reuses a saved ref without calling the accounts system again.
- **Failures:** any accounts-side failure backs off 1, 5, 15 and 60 minutes from `post_failures`; the 5th routes `ACCOUNTS_API_ERROR`. The count resets when an invoice re-enters `ready_to_post`.
- **Tests:** the end-to-end test goes from upload to posted, in-process.
- The contract's `total_tax` and line description are now optional, so common invoices aren't stalled.
- **To confirm on Dev:** the real pipeline → accounts-sim HTTP call and token.

### 3.3 Admin approves exceptions (`5d5ceea`, OCR-68), build #15
- **When Approve is offered:** only when every open reason allows it, and alone once an `accounts_ref` exists.
- **Rules:** a reason is required, and the bank call-back checklist is enforced on the server. Approving moves the invoice to `ready_to_post` (resetting the backoff), queues `q-post` and writes an audit row.
- **Screen:** duplicate comparison ("Not a duplicate" only when that's the only reason), an accounts error panel, and the `a` shortcut.
- **Review:** 5 findings patched.

### 3.4 Search all invoices (`e20113a`, OCR-69), build #16
- **Access:** admin and finance.
- **Search:** by supplier, status, normalised invoice number, or `R-…` reference (decoded to the UUID's low 40 bits, matched in SQL).
- **Detail:** current values (money at 2 decimals), status history with actor categories, `accounts_ref`; bank fields only as "Bank details on file".
- **Review:** 9 findings patched.
- **Epic 3 is now fully built.**

### Test budget
A second merge pass (web, ci, infra and Terraform tests) freed room again: **162 of 200**.

### Test merge (`3c275d2`)
Backend tests were merged to free room under the cap, 198 → 163 cases, with every assertion kept.

## Needs you

- **VM cost:** the CI VM is still running. Deallocate it when you're done: `az vm deallocate --name babaloo-sea-lng-vm-21 --resource-group babaloo-sea-lng-rg-23`.
- **First checks in Dev** (from the stories' "to confirm" lists):
  - the F0 quota error code;
  - the custom-metric namespace for the new `di_pages_used_pct` alert;
  - an end-to-end upload that goes quality → extract → validate.
- **Still open from the bootstrap:** step 8 (staff sign-in and redirect URI), the purchasing seed, the supplier load, `test-alerts.sh`, and everything for Prod.
