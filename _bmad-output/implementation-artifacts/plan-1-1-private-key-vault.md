---
title: 'Story 1.1 follow-up: PGP private key readable only by staff-api'
type: 'refactor'
ticket: '1-1-repository-and-terraform-foundation'
created: '2026-09-29'
status: 'built'
baseline_revision: 'ef927f06572915203e63f140919b3defd3aa96e9'
route: 'full'
route_source: 'auto'
review: 'thorough'
review_source: 'auto'
lenses_ran: ['blind-hunter', 'edge-case-hunter', 'verification-gap', 'intent-alignment']
review_loop_iteration: 0
context:
  - '{project-root}/infra/bootstrap/README.md'
  - '{project-root}/docs/standards/azure.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `pgp-private-key` sits in each environment's Key Vault, where the env deploy identity (Key Vault Secrets Officer, and Contributor on the RG) and Dj's load-script user (vault-wide Secrets User) can read it. Dj decided only the environment's `staff-api` identity may read it (Jira OCR-129).

**Approach:** Move the private key to a separate private-key vault per environment in the bootstrap-only RG `babaloo-sea-lng-rg-22` (`babaloo-sea-lng-kv-22` Dev, `kv-23` Prod), created by the bootstrap scripts and managed by no Terraform stack; the operator stores the key there (step 4b) and grants the env `staff-api` identity Key Vault Secrets User on that secret after `<env>/foundation` exists; staff-api gets a setting with that vault's URI; the load-script user's Key Vault role narrows to the two secrets it needs; Terraform stops granting runtime roles on `pgp-private-key` in the env vault. Verify offline.

## Boundaries & Constraints

**Always:** Private-key vault: RBAC mode, purge protection, public network as today, 5 P-17 tags, soft delete; created idempotently by `state-backend.sh` (or a new bootstrap script) in `rg-22`; no deploy identity, pipeline identity or Dj's user has any data or management role on it (the operator who runs step 4b does so as an Owner and holds Secrets Officer only for that step, documented). `pgp-step4b.sh` writes `pgp-public-key` to the env vault and `pgp-private-key` to the private-key vault (private first, as today), then grants the env `staff-api` identity Key Vault Secrets User scoped to the `pgp-private-key` secret. `database-step5.sh`: Dj's user gets Secrets User on only `pgp-public-key` and `hmac-key` (secret scope). `infra/modules/env-app`: staff-api keeps per-secret roles on `pgp-public-key` and `hmac-key` in the env vault and no longer gets a role on an env-vault `pgp-private-key`; new app setting `PGP_PRIVATE_KEY_VAULT_URI` for staff-api (value from the naming convention, not a secret). Backend staff-api settings accept the new setting (required URI https validation like `KEY_VAULT_URI`). The env deploy identity's conditioned RBAC Administrator must not be able to grant anything on `rg-22` (it has none today; keep it that way and test). README step 4b and run order updated; migration note for environments where the key was already stored in the env vault (move it, then delete and purge the old secret). Idempotent, dry-run-able, tested like the other bootstrap scripts.

**Never:** Terraform managing the private-key vault or its secrets. Any runtime role on the private key for `pipeline`, `supplier-api` or `accounts-sim`. Calling Azure.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Bootstrap run | `state-backend.sh` | `kv-22`, `kv-23` exist in `rg-22` with tags, RBAC, purge protection | Re-run: no create calls |
| Step 4b, new env | Both keys absent | Private key → private-key vault, public key → env vault, staff-api granted Secrets User on the private secret | staff-api identity missing → stop before writing, naming the step to run first |
| Step 4b, re-run | Both present | Nothing to do | One present, one absent → stop (as today) |
| Step 4b, legacy | Private key found in the env vault | Stop with instructions to move it (no silent copy) | — |
| Step 5 | Dj's user | Secrets User on `pgp-public-key` and `hmac-key` only; no vault-wide role | — |
| Terraform | env-app plan | No role for any identity on an env-vault `pgp-private-key`; staff-api has `PGP_PRIVATE_KEY_VAULT_URI` | — |
| Settings | staff-api without / with a bad URI | Start-up fails naming the setting | — |

</frozen-after-approval>

## Code Map

- `infra/bootstrap/{lib.sh, state-backend.sh, pgp-step4b.sh, database-step5.sh, README.md}` -- naming helpers (`key_vault_name`, `STATE_RG=rg-22`), step 4b secret writes, step 5 role grants.
- `infra/scripts/tests/{test_bootstrap_scripts.py, test_bootstrap_matrix.py, fake-bin-stateful/az}` -- dry-run and stateful tests to extend.
- `infra/modules/env-app/main.tf` + tests -- staff-api per-secret Key Vault roles and app settings (1.3); remove the private-key role, add the URI setting.
- `infra/modules/naming` -- add private-key vault names (22/23) if names are built there too; keep `lib.sh` and the naming module in step (agreement test exists).
- `backend/src/invoicing/apps/staff_api/settings.py`, `apps/common.py` -- add `PGP_PRIVATE_KEY_VAULT_URI`; conftest per-app settings.

## Tasks & Acceptance

**Execution:**
- [x] Bootstrap: private-key vaults in `rg-22`; step 4b split + staff-api grant + legacy guard; step 5 per-secret grants; README.
- [x] Terraform env-app: drop env-vault private-key roles; add staff-api setting; naming; tests.
- [x] Backend: staff-api setting + tests.

**Acceptance Criteria:**
- Given `ci/checks.sh all`, when it runs, then it exits 0.

## Verification

**Commands:**
- `ci/checks.sh all` -- expected: exit 0

## Decisions

- **Old private key stays recoverable for 7 days (Dj, 2026-09-29).** The env vaults' purge protection makes Azure refuse the purge in the migration. The deleted `pgp-private-key` stays recoverable by Secrets Officers on the env vault until the 7-day soft-delete retention ends. Accepted.
- **No audit logging on `kv-22`/`kv-23` (Dj, 2026-09-29).** The private-key vaults get no diagnostic settings, so private-key reads are not sent to Log Analytics. Accepted; no follow-up.

## Review Triage Log

Lenses ran one at a time (Dj's rule: no parallel subagents). B = blind-hunter, E = edge-case-hunter, V = verification-gap, I = intent-alignment.

| # | Finding | Verdict | Evidence | Route |
|---|---|---|---|---|
| B1 | README move: "check the copy" compares a tag copied from the source, so it never checks the key itself | medium | `fpr` is read from the env secret and written as the new tag; comparing tags proves only the copy of the tag | patch (group 1) |
| E5 | README move deletes the env copy without checking the moved key | medium | Same snippet: nothing stops before `secret delete` if download or set produced a bad copy | patch (group 1) |
| B2 | README runs a purge that always fails; the list-deleted check fails for 7 days | low | Purge is refused under purge protection; the check wording reads as immediate. Direct correction | patch (group 1) |
| B3 | README `umask 077` persists in the operator's shell; `rm -P` does no overwrite on APFS | low | Snippet is pasted into an interactive shell. Direct correction: run it in a subshell | patch (group 1) |
| E6 | Same as B3 (`umask` persists) | low | Same snippet | patch (group 1) |
| B4 | Key move is manual and has no tests | low | The plan and intent chose a README migration note; the fix is a new script, not a direct correction | reject |
| B5 | Auto dev deploy cuts staff-api off from the key | false | Nothing has been deployed or run against Azure yet, and no backend code reads the private key, so no environment can lose access | reject |
| B6 | No script checks effective access to the private key later | low | The operator is the subscription Owner, who can always grant themself access; the fix is a new script | reject |
| I1 | Effective access (operator, Owner, inherited roles) is not enforced, only script and Terraform output | low | Same as B6; the intent asked for offline verification | reject |
| B7 | RBAC Administrator test covers only two scripts | false | Only `state-backend.sh` and `rbac-step3.sh` assign `ROLE_RBAC_ADMIN` (grep of `infra/bootstrap/*.sh`) | reject |
| B8 | Exact-scope filter in `remove_role_assignment` is untested and case-sensitive | maybe-false | The casing matches: the old assignment was created with the same `rg_scope` string. The fake cannot model several scopes | defer (with V2) |
| V2 | Exact-scope filter is invisible to the fake `az` | medium (gap) | Filed evidence: the fake ignores `--query`; `ensure_role_assignment` has the same pattern from before | defer |
| B9 | `key_vault_uri` in `lib.sh` is dead code | low | Only the parity test calls it (grep). Direct deletion | patch (group 2) |
| V-o1 | Same as B9 | low | Same | patch (group 2) |
| B10 | staff-api requires a setting nothing reads yet | false | By design (matrix row "Settings"): Terraform always supplies it, and decryption arrives with a later story | reject |
| V-o2 | Same as B10 | false | Same | reject |
| I2 | staff-api's read of the key is shown only as a role grant | false | Decryption is not built yet; the intent asks only for the setting and the grant | reject |
| E8 | Settings do not reject `PGP_PRIVATE_KEY_VAULT_URI == KEY_VAULT_URI` | low | Only reachable if set outside Terraform, which validates it; the fix adds a validator | reject |
| B11 | No audit logging or alerts on the new vaults | false | Dj decided no logging (Decisions, 2026-09-29) | reject |
| B12 | README names table is split by the `rg-22` paragraph | low | Pre-existing at `ef927f0` (same layout) | defer |
| B13 | `state-backend.sh` header comment reflowed badly | low | One 120-character line, then a short one. Direct correction | patch (group 3) |
| V1 | dev/prod app root tests never check the URI given to staff-api | medium (gap) | Filed evidence: the root asserts check only the naming output and role scopes | patch (group 4) |
| E7 | Dev given the prod vault URI (or the reverse) is not caught | medium | Same root cause as V1: nothing ties the URI to the environment in the root tests | patch (group 4) |
| E1 | Soft-deleted `kv-22` name blocks create | false | No script deletes the vaults; create fails loudly on an unshown path | reject |
| E2 | Soft-deleted `pgp-private-key` in `kv-22` blocks the first write | false | Fails loudly on the first write, before anything is stored; the trap removes the local copies | reject |
| E3 | Private write succeeds, public write fails; re-runs stop | false | Designed: the script stops and asks for a manual fix, as before this change | reject |
| E4 | Empty principalId for staff-api | false | A user-assigned identity has its principalId at creation; the lookup fails loudly if it is missing | reject |
| E9 | Dj may keep broader roles on the env vault (RG scope, or step 4b's Officer role) | low | No script creates those; README step 4b tells the operator to remove the Officer roles; the fix adds branches | reject |
