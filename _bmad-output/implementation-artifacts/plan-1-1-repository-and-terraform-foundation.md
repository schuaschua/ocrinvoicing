---
title: 'Story 1.1: Repository and Terraform foundation'
type: 'chore'
ticket: '1-1-repository-and-terraform-foundation'
created: '2026-09-28'
status: 'built'
baseline_revision: 'NO_VCS'
route: 'full'
route_source: 'auto'
review: 'thorough'
review_source: 'auto'
lenses_ran: ['blind-hunter', 'edge-case-hunter', 'verification-gap', 'intent-alignment']
review_loop_iteration: 1
context:
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-ocrinvoicing-2026-09-28/ARCHITECTURE-SPINE.md'
  - '{project-root}/docs/standards/terraform.md'
  - '{project-root}/docs/standards/azure.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The repo holds only planning docs. Every later story needs the repository layout, Terraform state, the three resource groups, deploy identities, and the `shared` and `<env>` foundation stacks (AD-17 steps 1–5) to exist as code.

**Approach:** Write the repo skeleton, the idempotent `az` bootstrap scripts, the operator-step runbook, and three Terraform roots (`infra/shared/foundation`, `infra/dev/foundation`, `infra/prod/foundation`) over shared modules. Verify offline with `terraform fmt`/`validate`/`test` (mock providers) and script tests.

## Boundaries & Constraints

**Always:** Names per P-16 `babaloo-sea-lng-<type>-<nn>` (Dev 01–09, Prod 11–19, shared 21–29; storage drops hyphens), built in one `locals` naming block per root. All 5 P-17 tags (`owner`, `costCentre`, `environment`, `application`, `dataClassification`) on every RG and taggable resource via one `local.tags`. Region `southeastasia` from a variable default. AVM modules first, versions pinned exactly, `enable_telemetry = true`; `azapi` only where `azurerm` lacks the resource, with a comment. Backend `azurerm` with `use_azuread_auth = true`, key `<stack>.tfstate`. Managed identity only; Key Vault RBAC mode; `disableLocalAuth`/shared-key off wherever Azure allows. Exact values from story 1.1 ACs and AD-11/12/15/17 (B1ms, PG 18, 32 GB, 7-day backup, LRS, 7-day soft delete, 30-day lifecycle, 0.08 GB/day cap, 30-day retention, budget thresholds 90/100/110 + 110 forecast).

**Never:** Apply, run the bootstrap, or call Azure from this session. No provisioners, `null_resource` or `terraform_data` scripts. No secrets, subscription IDs or tenant IDs in committed files. Terraform never manages the PGP secrets. No `<env>/app` stack, Function apps, runtime role assignments, pipelines (1.2) or metric alerts (1.5). No backend/web code beyond empty package skeletons.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Bootstrap re-run | Resources already exist | Script skips or updates each, exits 0 | `set -euo pipefail`; clear message naming the failed step |
| Missing input | Required env var (e.g. `ARM_SUBSCRIPTION_ID`, ADO org) unset | Script stops before any change | Exit 1 naming the variable |
| Tag gate | Plan JSON with a taggable resource lacking one of the 5 tags | `check-tags` exits 1 listing resource + missing keys | — |
| Tag gate pass | All taggable resources carry the 5 tags | exits 0 | — |
| Cross-env DB | Dev login connects to `invoicing_prod` | Connection refused | Operator test script reports PASS/FAIL |

## Decisions (Dj, 2026-09-28)

- **Code only.** Write and verify offline; Dj runs the bootstrap scripts and applies later. Nothing in this session calls Azure.
- **Inputs are required variables.** Tag values, alert email, ACS custom domain and Azure DevOps org/project are Terraform variables and script inputs with no defaults; Dj fills `terraform.tfvars` before the first apply. Tests supply fake values.
- **Git.** `git init` on `main` with no remote before implementation; Dj connects Azure Repos later.
- **Scope.** Keep the full plan (about 2,200 tokens); implement in stages.

</frozen-after-approval>

## Code Map

Greenfield: only `docs/`, `_bmad-output/`, `.gitignore` (ignores `.work/`, `docs/costing/token_usage/`) exist. Reuse nothing; do not touch `docs/` or `_bmad*`.

- `ARCHITECTURE-SPINE.md` AD-11 (logins/grants), AD-12 (server), AD-15 (retention), AD-17 (step table, deploy identity rights, names, tags) -- source of every value.
- `docs/architecture/azure.md` P-16/P-17 -- naming and tag keys.
- `docs/standards/terraform.md` directory tree + rules 1–25 -- layout and file set; its Accepted exceptions (rule 3 remote state, 26/33, 36, 31–34 ADO) apply.
- `docs/standards/azure.md` rules 1–31 + Accepted exceptions (13 firewall open, 31 extra RBAC).

## Tasks & Acceptance

**Execution:**
- [ ] `backend/`, `web/supplier/`, `web/staff/`, `shared/quality-thresholds.json`, `shared/quality/`, `README.md`, `.gitignore` -- skeleton per spine Structural Seed; minimal `pyproject.toml` + `uv.lock` in `backend/`, `package.json` + `package-lock.json` per web app; thresholds JSON with `[ASSUMPTION]` values -- AC 1.
- [ ] `infra/bootstrap/lib.sh`, `state-backend.sh`, `app-registrations.sh`, `budget-and-roles.sh`, `rbac-step3.sh`, `pgp-step4b.sh`, `database-step5.sh` + `database-step5.sql`, `verify-db-isolation.sh`, `README.md` -- idempotent `az`/`psql` scripts for AD-17 steps 1, 3, 4b, 5; README lists run order and inputs -- ACs 2, 4, 6, 7.
- [ ] `infra/modules/naming/` -- takes `environment`, `number_base`; outputs names per type and the validated 5-tag map -- single source for P-16/P-17.
- [ ] `infra/shared/foundation/*` -- PostgreSQL (AVM), `invoicing_dev`/`invoicing_prod`, Entra admin, open firewall rule, `azure.extensions=PGCRYPTO`; DI F0 with custom subdomain; ACS + Email service + custom domain; RG budget -- AC 3.
- [ ] `infra/modules/env-foundation/` + `infra/dev/foundation/*`, `infra/prod/foundation/*` -- 4 UAMIs, storage (containers, queues, tables, lifecycle, soft delete), Key Vault + `random_password` HMAC secret + Secrets Officer for deploy identity, Log Analytics, App Insights, action group, RG budget; `data.tf` remote state of `shared` -- AC 5.
- [ ] `infra/scripts/check_tags.py` + `infra/scripts/tests/` -- reads `terraform show -json` output, fails on missing tags; pytest with fixture plans -- AC 5 "missing tag fails the plan".
- [ ] `infra/**/tests/*.tftest.hcl` -- `terraform test` with `mock_provider` asserting names, tags, SKUs, retention values.

**Acceptance Criteria:**
- Given the repo, when listed, then the AC 1 folders, `.gitignore`, `README.md` and lock files (`uv.lock`, `package-lock.json`, `.terraform.lock.hcl` per root) exist.
- Given each root, when `terraform init -backend=false && terraform validate && terraform test` run, then all pass.
- Given `shellcheck`-clean bootstrap scripts, when run with `--dry-run`, then each prints its planned `az` calls without calling Azure.

## Design Notes

Numbering within a type counts up from the environment base: Dev UAMIs `id-01..04` in the order `supplier-api`, `staff-api`, `pipeline`, `accounts-sim`, mapped in the naming module; no extra role tag, since only the 5 P-17 tags are used. Deploy identities live in a **bootstrap-only RG `babaloo-sea-lng-rg-22`** (shared range, created and managed only by `infra/bootstrap/`; no Terraform stack and no deploy identity holds Contributor on it): deploy identities `id-21` (shared), `id-22` (dev), `id-23` (prod). State lives in Dj's existing account `stdjtfstatesea` (`rg-tfstate-sea`), containers `ocrinvoicing-shared`, `-dev`, `-prod` (Dj, 2026-09-30; was `babaloosealngst21` in `rg-22`). The shared stack's RG `rg-21` holds only `shared/foundation` resources. The naming module returns no app-identity names for `shared`.

## Verification

**Commands:**
- `terraform fmt -check -recursive infra` -- expected: no diff
- `for r in infra/shared/foundation infra/dev/foundation infra/prod/foundation; do terraform -chdir=$r init -backend=false && terraform -chdir=$r validate && terraform -chdir=$r test; done` -- expected: all pass
- `uv run --with pytest pytest infra/scripts/tests` -- expected: pass
- `bash -n infra/bootstrap/*.sh` and each script `--dry-run` -- expected: exit 0

## Implementation Notes

- Implemented by a coding subagent (2026-09-28/29). Beyond the plan: azurerm pinned to 4.81.0 (AVM modules need <5.0); ACS `disableLocalAuth` via `azapi_update_resource`; `email_domain_link_enabled` (default false) because Azure won't link an unverified domain; `require_secure_transport` applied as its own resource after `azure.extensions`; assumed names `budget-22`, `babaloo-sea-lng-{staff-api,accounts-sim}-<env>` app registrations, service connections `azure-{shared,dev,prod}`, secret `hmac-key`; `[ASSUMPTION]` tfvars: budgets $12 shared / $2 dev / $2 prod, App Insights sampling 50%.
- Matrix audit added stateful fakes (`infra/scripts/tests/fake-bin-stateful/`) and `test_bootstrap_matrix.py`; the re-run test found `state-backend.sh` always ran `az group create` (fixed to show → update/create).

## Plan Change Log

- **2026-09-29, review loop 1.** Finding: the shared deploy identity (`id-21`) is Contributor on `rg-21`, which also held the state account and the dev/prod deploy identities, so it could add federated credentials to `id-22`/`id-23` or rewrite any stack's state (privilege escalation). Amended: Design Notes move state + deploy identities to a bootstrap-only RG `rg-22`. Known-bad state avoided: any deploy identity with write access to another's identity or state. KEEP: everything else in the implementation (skeleton, scripts, modules, roots, tests, tag gate). Applied in place rather than by full re-derivation (overnight-run decision, to avoid re-writing ~4,000 correct lines).

## Review Triage Log

**Pass 1 (2026-09-29): blind-hunter, edge-case-hunter, verification-gap, intent-alignment.** Counts: high 3, medium 22, low 10, false 5, maybe-false 2 (rows below; descriptive intent notes in row 41).

| # | Finding | Verdict | Route | Evidence / action |
|---|---------|---------|-------|-------------------|
| 1 | Shared deploy identity can alter state + other deploy identities (implementer risk 1) | high | bad_plan | Design Notes put them in `rg-21` where `id-21` is Contributor. Plan amended; fix applied in place. |
| 2 | `exists()` treats any lookup error (403, throttling) as absent; `pgp-step4b.sh` could regenerate over live keys (E1, E2) | high | patch | `lib.sh` `exists()` is `"$@" >/dev/null 2>&1`. Only NotFound means absent; other errors die. |
| 3 | PGP "both exist / only one exists" guards untested (V1) | high | patch | No test runs those branches; add matrix cases. |
| 4 | App id re-read with `az ad app list` right after create; `[0]` hides duplicates (B6, E3) | medium | patch | Take `appId` from create output; die on >1 match. |
| 5 | `az ad sp update` right after `sp create` (E4) | medium | patch | Retry `sp show` until visible. |
| 6 | Role-assignment lookup via `--assignee` hits Graph lag (E5) | medium | patch | Use `--assignee-object-id`. |
| 7 | `az provider register` without `--wait` (E7) | medium | patch | Add `--wait`. |
| 8 | Existing federated credential never updated when ADO values change (E8) | medium | patch | ADO project name still unknown, so a re-run with new values is likely. Update when issuer/subject differ. |
| 9 | GRANT/ALTER/REVOKE ownership not transactional (B4, E9) | medium | patch | Wrap in BEGIN/COMMIT. |
| 10 | `PG_ADMIN_USER` defaults to Dj's load-script user, so the load script runs as server admin (B3) | medium | patch | Make it required; die if equal to `DJ_USER_UPN`; README: separate admin principal. |
| 11 | Public PGP key stored before private (B7) | medium | patch | Store private first; tag both with the key fingerprint. |
| 12 | `plan.json` not gitignored while README says to write it (B8, E14) | medium | patch | Ignore `plan.json`/`*.plan.json`; README writes under `.work/`. |
| 13 | Tag gate passes on unknown tags and skips `emailServices/domains` (B9) | medium | patch | Fail on unknown tags; allow-list taggable child types. |
| 14 | `verify-db-isolation.sh` PASSes PUBLIC check for a missing database (E10) | medium | patch | FAIL when the database does not exist. |
| 15 | Budget start date hard-coded `2026-10-01` (E11) | medium | patch | Azure rejects past start dates on create; derive from `time_static` month start with `ignore_changes`. |
| 16 | RBAC-admin condition content never asserted (V2) | medium | patch | Add condition-content test. |
| 17 | Subscription budget / `ACS Email Sender` content never asserted (V3) | medium | patch | Add dry-run content test. |
| 18 | Adding a missing app role path never run (V4) | medium | patch | Add partial-roles matrix test. |
| 19 | PG Entra-only auth + storage policies asserted on locals only (V5) | medium | patch | Assert module resource attributes. |
| 20 | `lib.sh` names mirror naming module with no agreement test | low | patch | Add name-agreement test (kv/st names). |
| 21 | Naming module shared identities collide with deploy ids (E16) | low | patch | Return no app-identity names for `shared`. |
| 22 | `.env.example` would be ignored (E18) | low | patch | Add `!.env.example`. |
| 23 | Deploy identity (Secrets Officer) and Dj's user (Secrets User) can read `pgp-private-key` (B1, B2) | medium | defer | Both roles are set by AD-17; an architecture decision. Raised to Dj with the bank-crypto questions. |
| 24 | Key Vault / PG / DI / ACS diagnostic settings missing (B11) | medium | defer | Monitoring belongs to Story 1.5. |
| 25 | `database-step5.sql` never executed against PostgreSQL (V6, I2) | medium (unverified) | defer | Needs a PG container with a `pgaadauth_create_principal` stub; the live `verify-db-isolation.sh` run is the gate. |
| 26 | PG 16+ may refuse `GRANT deploy_login TO CURRENT_USER` (B4 part) | maybe-false | defer | Settle by running step 5 on the PG 18 server. |
| 27 | azurerm full PUT on ACS may reset `disableLocalAuth` (E13) | maybe-false | defer | Settle by a plan after a tag change on a live ACS. |
| 28 | Tag gate not run against real `terraform show -json` of these roots (I3) | medium | defer | Wiring is Story 1.2; mocks cannot emit plan JSON. |
| 29 | `accounts-sim` registration has no app role / assignment required (B5) | false | reject | AD-10 restricts callers with built-in auth `allowedPrincipals.identities` in `<env>/app`. |
| 30 | Subscription budget has one alert; shared budget lacks contacts (B10) | false | reject | AD-12 specifies one $8 alert; shared budget has `contact_emails = [var.alert_email]`. |
| 31 | No Log Analytics 90% cap alert | false | reject | AD-17: no separate log-cap alert (Dj's decision). |
| 32 | ACS domain verified only after a manual step (I6) | false | reject | AC says DNS records are added by hand. |
| 33 | Lock files missing from diff (I7) | false | reject | They exist; the staged diff filtered out `*lock*` files. |
| 34 | Tag values could differ between bootstrap and tfvars (I5) | low | reject | Operator input; Terraform re-tags the imported RG on apply. |
| 35 | `alert_email` has no format validation (B13) | low | reject | Adds guards; low everyday impact. |
| 36 | `postgres` database still CONNECT-able by PUBLIC (B14) | low | reject | Azure maintenance needs it; no data there. |
| 37 | Scope-casing mismatch in assignment count (E6) | low | reject | Scopes built from lowercase names; not shown to occur. |
| 38 | Local operator apply with ServicePrincipal type (E12) | low | reject | Applies run only in the pipeline (terraform.md rule 26). |
| 39 | Malformed plan JSON gives a traceback (E15) | low | reject | Still exits non-zero; input comes from `terraform show`. |
| 40 | Disabled existing app role never re-enabled (E17) | low | reject | Unlikely; adds a branch. |
| 41 | Tests assert inputs, not deployed state (I1, I4) | — | reject | Descriptive; matches the "code only, verify offline" decision. Specific gaps in rows 16–19, 25. |
