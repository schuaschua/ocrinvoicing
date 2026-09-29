---
title: 'Story 1.6: Load suppliers and issue upload links'
type: 'feature'
ticket: '1-6-load-suppliers-and-issue-upload-links'
created: '2026-09-29'
status: 'built'
baseline_revision: 'c32f0afa8276077a6b440656dcaeeac6725a1f5b'
route: 'full'
route_source: 'auto'
review: 'thorough'
review_source: 'auto'
lenses_ran: ['blind-hunter', 'edge-case-hunter', 'verification-gap', 'intent-alignment']
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-ocrinvoicing-2026-09-28/ARCHITECTURE-SPINE.md'
  - '{project-root}/docs/standards/coding-style.md'
  - '{project-root}/docs/standards/security.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Suppliers can't upload yet: there is no supplier master, no bank details on file to compare against (AD-19 `BANK_CHANGED`), and no way to issue the upload links Story 1.7 already reads (Jira OCR-7).

**Approach:** An operator script, run by Dj's user, loads a CSV of synthetic suppliers into a new `master` schema (bank fields as `pgp_pub_encrypt` ciphertext plus an HMAC-SHA256 fingerprint, keys from the environment vault), keeps an append-only `audit.event` log, and issues, replaces or revokes each supplier's link in the `supplierlinks` table, printing a new link once.

## Boundaries & Constraints

**Always:** AD-6 link rules (256-bit base64url token, only `token_hash()` stored, RowKey = hash, PartitionKey = `partition_key()`, link printed once, rows never deleted). AD-11: fingerprint over the value normalised by stripping spaces and hyphens and uppercasing; one `supplier_bank` row per non-empty AD-18 field id; grants only in the Alembic migration (Dj read/write on `master`; staff-api read including ciphertext; pipeline read without the ciphertext column; `audit` INSERT for every writer, SELECT for staff-api, no UPDATE or DELETE for anyone). Refuse `invoicing_prod` without `--allow-prod`. Logs, stdout (other than the one printed link), stderr and `audit.event.detail` never hold a token, token hash, bank value or phone number. Idempotent: a re-run with the same CSV changes nothing and issues no link to a supplier that already has an active one.

**Decisions (Dj, 2026-09-29):** The CSV carries a required `supplier_id` UUID column, the same ids as `backend/seed/sim_purchasing.json`, and rows match on it. A bank field, `phone` or `tax_id` blank in the CSV leaves the stored value unchanged. A load issues a link to every supplier without an active link, including one revoked earlier (remove a supplier from the CSV to keep them revoked). `audit.event` records link issue, replace and revoke (issue added by Dj on review, 2026-09-29), supplier created or updated, and each bank field added or changed, with field ids only, never values.

**Never:** Terraform changes. Decrypting anything (staff-api's job, later stories). Calling Azure in tests. Running the load from a Function app. Storing the private key anywhere.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| New supplier | CSV row, no active link | Supplier and bank rows written; link issued and printed once | — |
| Re-run | Same CSV | No changes, no new link | — |
| Bank value changed | New `iban` | That row's ciphertext and fingerprint replaced; audit entry naming `iban` | — |
| Bank value blank | Blank `swift`, one on file | Stored row unchanged | — |
| `--replace-link` | Existing active link | Old link revoked, new one printed, audit entry | Supplier unknown → error, exit 2, nothing changed |
| `--revoke` | Existing active link | Link revoked, none issued, audit entry; Story 1.7 shows Link not working | No active link → error, exit 2 |
| Bad CSV | Missing column, bad UUID, unknown extra column, duplicate id | Nothing written | One-line error naming the row and column, exit 2 |
| Prod | `invoicing_prod` without `--allow-prod` | Refused | Exit 2 |
| Pipeline login | `SELECT ciphertext` from `master.supplier_bank` | Permission denied | — |

</frozen-after-approval>

## Code Map

- `backend/src/invoicing/tools/seed_purchasing.py`, `adapters/purchasing_sim/seed.py`, `backend/tests/tools/test_story_2_4_seed_purchasing.py` -- the operator-tool pattern to copy: argparse, `--allow-prod`, libpq env (PGPASSWORD = Entra token), one transaction, one-line errors and exit 2, `main([...])` tests with `capsys`.
- `backend/migrations/versions/0001_intake.py` (TABLE_GRANTS loop, default privileges, exact downgrade), `migrations/env.py:22-24` (`ROLE_ARGUMENTS`), `ci/migrate.sh:60-76` -- add `dj_role` next to `pipeline_role` and `staff_api_role`.
- `backend/tests/conftest.py:126-218` -- Docker Postgres fixture; add a Dj login to its role list.
- `backend/src/invoicing/ports/links.py` -- `SupplierLinkRegistry` (only `resolve()` today; its docstring promises issue and revoke) and the storage contract; `domain/links.py` -- `TOKEN_BYTES`, `token_hash()`, `parse_token`; `adapters/table_links.py` -- the async reader to extend.
- `adapters/logging.py` -- `ALLOWED_KEYS`, `safe_fields`.
- `infra/bootstrap/database-step5.sh`/`.sql` -- Dj's login and CONNECT; add `CREATE EXTENSION IF NOT EXISTS pgcrypto` here as the admin.
- `infra/bootstrap/lib.sh:63-76` -- `function_app_name <env> supplier-api` (the host is `<name>.azurewebsites.net`); the backend has no naming helper.
- Keep unchanged: the Story 1.7 reader's accepted row shape (`supplier_id` UUID string, non-blank `supplier_name`, ISO or datetime `issued_at`/`revoked_at`).

## Tasks & Acceptance

**Execution:**
- [ ] `backend/src/invoicing/domain/suppliers.py` -- CSV row model, `normalise_bank_value`, `bank_fingerprint(key, value)` (standard library only) -- pure and testable.
- [ ] `backend/migrations/versions/0004_master_audit.py` + `migrations/env.py` + `ci/migrate.sh` + `pipelines/templates/migrate.yml` -- `master` and `audit` schemas, column-level grants (pipeline gets every `supplier_bank` column except `ciphertext`), `CREATE EXTENSION IF NOT EXISTS pgcrypto`, `-x dj_role` from a required `DJ_USER_UPN` pipeline variable.
- [ ] `backend/src/invoicing/ports/links.py`, `adapters/table_links.py` -- add issue, find-active-by-supplier and revoke to the registry and its table adapter.
- [ ] `backend/src/invoicing/tools/load_suppliers.py` (+ a small Key Vault secret reader using `azure-keyvault-secrets` with the operator's Azure CLI credential) -- the script: `--file`, `--host`, `--vault-uri`, `--account`, `--replace-link ID`, `--revoke ID`, `--allow-prod`; DB work in one transaction, then link changes.
- [ ] `infra/bootstrap/database-step5.sql`, `infra/bootstrap/README.md` -- pgcrypto; how to run the load script and set `DJ_USER_UPN`.
- [ ] `backend/tests/**/test_story_1_6_*.py` -- every matrix row, encryption round-trip with a test key pair, one row per field id, normalisation, and a log-redaction test.

**Acceptance Criteria:**
- Given the migration, when downgraded and upgraded again, then the schemas and grants return exactly.
- Given a printed link, when Story 1.7's reader resolves its token, then it returns that supplier, active.

## Implementation Notes

- 2026-09-29: paused mid-implementation for the 200-case test cut (commits `68216a0`, `12dc690`, `7b3e69c`); the partial work was stashed and restored. `test_migrations.py` and `ci/tests/test_ci_scripts.py` were reset to the cut versions, and the Story 1.9 migration test was deleted by the cut, so re-add only what this story needs there, within the budget.

## Design Notes

- Fingerprint: `hmac.new(key.encode(), normalised.encode(), sha256).hexdigest()`, where `key` is the `hmac-key` secret text. Encrypt in SQL: `pgp_pub_encrypt(:value, dearmor(:public_key))`.
- Order: commit the database transaction first, then change links. A failed link write leaves the supplier without an active link, so the next run issues one.
- Actor in `audit.event`: `current_user`.
- Test budget (Dj's 200-case cap, coding-style.md rule 20 exception): at most 12 new test cases for this story. Cover the matrix rows as assertions in a few merged tests; the repo stands at 185 and `ci/checks.sh test` fails above 200.

## Verification

**Commands:**
- `ci/checks.sh all` -- expected: exit 0

## Review Triage Log

Lenses ran one at a time. B = blind-hunter, E = edge-case-hunter, V = verification-gap, I = intent-alignment. Test budget: 3 cases left under the 200 cap.

| # | Finding | Verdict | Evidence | Route |
|---|---|---|---|---|
| B4, I-E | First link issues are not audited | medium | `_change_links` audits only replace/revoke; Dj decided on review to audit issues too | patch (decision recorded) |
| B1 | Any writer can set `audit.event.actor` and `at` | medium | Table-wide INSERT to dj, pipeline, staff-api (0004 `_grants`); `server_default` only applies when omitted | patch: column-level INSERT without `actor`, `at` |
| B3, E2, E3, V-o1 | Replace/revoke audit row is written after the Table writes; "run again" then refuses (`--revoke`) or re-replaces the printed link | medium | `_change_links` writes the audit in a separate transaction after revoke/issue | patch: audit before changing links; failure message names the exact recovery |
| B2 | A lost response on `issue` can leave an active link no one holds; message says "can't be reached" | low | 409 after a retried insert maps to unavailable; the next load issues nothing | patch: failed-issue message tells the operator to run `--replace-link <id>` |
| B5, V-o2 | Table reads run inside the supplier transaction holding `FOR UPDATE` locks | low | `_plan_links` awaits `find_by_supplier` inside `engine.begin()` | patch: check the target inside, plan links after commit |
| B6 | One full table scan per supplier | low | `supplier_id` is not a key; table small; fix is a redesign | reject |
| B7 | Downgrade drops the append-only audit log | medium | `downgrade()` drops `audit.event` | patch: refuse downgrade when `audit.event` has rows |
| B8, E7 | No runbook for already-bootstrapped environments (step 5 re-run for pgcrypto, `DJ_USER_UPN`) before this deploy | medium | README has the pieces, not the order; migration fails without them | patch: README "Before deploying Story 1.6" |
| B9 | No way to clear a phone/tax id or remove a bank field | low | Follows Dj's blank-means-unchanged decision | patch: state the limit and the manual fix in the README |
| B10 | `supplier_id` not checked against the purchasing seed | low | The AC names the source of ids, not a validation; a typo only yields PO_MISMATCH later | reject |
| B11, V1 | `key_vault.read_secrets` untested (EMPTY, error codes, no SDK text) | medium (gap) | Filed evidence: only fakes replace `read_keys` | patch: one test (1 case) |
| B12 | Grant matrix misses dj INSERT on `supplier_bank`, pipeline write refusals, TRUNCATE on master | low | Test-data rows in an existing loop | patch |
| B13 | Prod-refusal test depends on earlier runs | false | The Postgres container is per test session and the case runs once | reject |
| B14a | Ciphertext encrypts the raw value; AD-11/epics say "normalised first" | medium | epics AD-11 line: stored "as `pgp_pub_encrypt` ciphertext plus an HMAC fingerprint, normalised first" | patch: encrypt the normalised value |
| B14b | `new_token()` strips padding with `[:-1]` | low | Works only because 32 bytes give one `=`; direct correction | patch: `.rstrip("=")` |
| B14c | `line_num` is the last physical line of a quoted cell | low | Cosmetic | reject |
| E1 | `csv.Error` (oversized cell) escapes as a traceback, exit 1 | low | `parse_supplier_csv` does not catch it; direct fix | patch |
| E4 | Two concurrent loads can issue two links | low | One operator runs the tool; the fix adds locking | reject |
| E5 | A renamed supplier's active link keeps the old display name | low | The fix adds a merge path | reject |
| E6 | Control characters in a name split the printed link line | low | Small guard in the CSV rules | patch |
| E8 | `strerror` None prints "None" | low | Direct correction | patch |
| V2 | No test that `migrate.yml` passes `DJ_USER_UPN` | medium (gap) | Filed evidence | patch: assertion in the existing pipeline test |
| V3 | `--replace-link` with `--file` for a target without a link untested | medium (gap) | Filed evidence | patch: a case in the existing test |
| V4 | CSV refusal branches and the UTF-8 BOM untested | medium (gap) | Filed evidence | patch: loop entries in `BAD_CSVS` plus a BOM run |
| I | Azure-facing paths (Key Vault RBAC, real Table SDK, Entra login, admin pgcrypto, pipeline variable) untested offline | maybe-false | Needs the first Dev deploy | defer |
