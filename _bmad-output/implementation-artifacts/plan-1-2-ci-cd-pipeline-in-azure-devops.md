---
title: 'Story 1.2: CI/CD pipeline in Azure DevOps'
type: 'chore'
ticket: '1-2-ci-cd-pipeline-in-azure-devops'
created: '2026-09-29'
status: 'built'
baseline_revision: '4eac5dd02c1267c3f66b3727c8f6bfc516a09c48'
route: 'full'
route_source: 'auto'
review: 'thorough'
review_source: 'auto'
lenses_ran: ['blind-hunter', 'edge-case-hunter', 'verification-gap', 'intent-alignment']
review_loop_iteration: 0
context:
  - '{project-root}/docs/standards/terraform.md'
  - '{project-root}/infra/bootstrap/README.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Nothing checks pull requests or deploys the Terraform stacks. Story 1.2 needs a PR build that blocks bad merges, a gated deploy pipeline (Dev automatic, `shared` and Prod after approval), a weekly dependency scan, and a migration step placed per AD-17.

**Approach:** Azure DevOps YAML pipelines under `pipelines/` that call repo scripts under `ci/` (so every check also runs locally), plus an operator script that creates the ADO service connections, environments, pipelines and branch policy. Verify offline: run `ci/` checks on this repo, structural tests on the YAML, and dry-run tests of the operator script.

## Boundaries & Constraints

**Always:** Workload-identity-federation service connections only, named `azure-shared`, `azure-dev`, `azure-prod` (Story 1.1 federated credentials). Every Terraform apply uses a saved `tfplan` from the same run; `check_tags.py` runs on `terraform show -json` of every plan before apply. Stack order per AD-17: `shared/foundation` → `dev/foundation` → Dev migrations → `dev/app` (when it exists) → Dev code deploy (when it exists) → `prod/foundation` → Prod migrations → `prod/app` → Prod code deploy. Dev applies automatically on merge to `main`; `shared` and `prod` apply only through ADO environments `shared` and `prod` that carry an approval check. Pinned tool versions (Terraform 1.16.4, Python 3.13, Node 22). Coverage thresholds: backend ≥ 80%, web ≥ 60%. Migrations: `alembic upgrade head` as the env deploy identity with an Entra token, no firewall rule, never at app start.

**Never:** Call Azure or ADO from this session. `-auto-approve`, `terraform apply` without a saved plan, stored secrets or PATs in YAML, GitHub Actions. Operator steps (AD-17 steps 1, 3, 4b, 5, 8) inside the pipeline. Lowering thresholds to pass.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Clean PR | Repo as committed | `ci/checks.sh all` exits 0 | — |
| Lint/format failure | A Python or Terraform file badly formatted | Check exits non-zero naming the tool | — |
| Coverage below threshold | Tests pass, coverage < floor | Exits non-zero with the measured % | — |
| Not scaffolded yet | `backend/` or `web/*` has no tests (before 1.3/1.4) | That test check prints "skipped: no tests yet" and passes; lint/audit still run | Once any test file exists, thresholds apply |
| Secret committed | gitleaks finds a secret | Exits non-zero | — |
| No infra change | Plan has no changes | Apply job skipped, no approval requested | — |
| Untagged resource in plan | `check_tags.py` fails | Apply for that stack does not run | Stage fails |
| No migrations yet | `backend/migrations/env.py` absent | Migration step prints "no migrations" and passes | — |
| Operator script missing input | `ADO_ORG`/`ADO_PROJECT` unset | Exit 1 naming it, no change | — |

</frozen-after-approval>

## Code Map

- `infra/bootstrap/lib.sh` -- reuse `parse_common_args`, `require_env`, `run`, `exists`, dry-run and naming helpers for the new operator script; deploy identity names `id-21/22/23`, state RG `rg-22`.
- `infra/bootstrap/README.md` -- add the ADO step to the run order; its tag-gate section says the pipeline runs `check_tags.py` after every plan.
- `infra/scripts/check_tags.py` -- the tag gate to call per plan.
- `infra/scripts/tests/` -- fake `az` patterns (`fake-bin`, `fake-bin-stateful`) to reuse for the new script's tests.
- `infra/{shared,dev,prod}/foundation` -- existing roots; `infra/<env>/app` does not exist yet (Story 1.3).
- `backend/pyproject.toml` (no deps yet), `web/*/package.json` (stubs) -- checks must pass on these today.
- `.gitleaks.toml` -- allowlist already in place; gitleaks must pass on the repo.

## Tasks & Acceptance

**Execution:**
- [x] `ci/checks.sh` (+ `ci/lib.sh` if useful) -- subcommands `lint`, `test`, `audit`, `secrets`, `terraform`, `all`: ruff format/check + mypy on `backend/` when it has code; ESLint/Prettier/tsc and Vitest with coverage per web app when scaffolded; pytest with coverage ≥ 80% (backend) and Vitest ≥ 60% (web); `pip-audit`, `npm audit --omit=dev`; `gitleaks`; `terraform fmt -check`, `validate`, `test` per root and module; `pytest infra/scripts/tests`.
- [x] `backend/pyproject.toml` -- add a `dev` dependency group (ruff, mypy, pytest, pytest-cov, pip-audit) pinned, ruff/mypy/coverage config per coding-style.md §1; refresh `uv.lock`.
- [x] `pipelines/pr.yml` -- PR trigger on `main`, runs `ci/checks.sh all` jobs in parallel; publishes test and coverage results.
- [x] `pipelines/deploy.yml` + `pipelines/templates/terraform-stack.yml`, `migrate.yml`, `code-deploy.yml` -- trigger on merge to `main`; per stack: plan job (`plan -out=tfplan -detailed-exitcode`, `show -json` → `check_tags.py`, publish artifact) then deployment job in its environment applying that artifact only when changes exist; AD-17 order; app and code-deploy stages no-op until their folders exist; one run at a time (exclusive lock on environments).
- [x] `pipelines/weekly-scan.yml` -- weekly schedule on `main` (always runs), `ci/checks.sh audit`, fails on findings.
- [x] `infra/bootstrap/ado-setup.sh` + README section -- idempotent `az devops`/`az pipelines` script: WIF service connections `azure-{shared,dev,prod}` bound to the deploy identities, environments `shared`/`dev`/`prod` with an approval check (Dj) on `shared` and `prod` and exclusive lock on all, the three pipelines, branch policy on `main` (PR build required; gitleaks inside it), `--dry-run`/`--help`.
- [x] `ci/tests/` (pytest) -- structural tests on the YAML (triggers, stage order, `dependsOn`, service connection per stage, environments, no `-auto-approve`, apply uses the saved plan, tag gate before apply, migration before app) and `ado-setup.sh` dry-run/missing-input tests with fake `az`.

**Acceptance Criteria:**
- Given this repo, when `ci/checks.sh all` runs locally, then it exits 0.
- Given `pipelines/*.yml`, when the structural tests run, then they pass and would fail on a stage-order swap, a missing approval environment or an apply without a saved plan.
- Given `ado-setup.sh --dry-run`, when run with fake inputs, then it prints every planned ADO call and calls nothing.

## Design Notes

`main` is the integration branch (AD-17: Dev applies on merge to `main`); PRs target it. Approval checks live on ADO environments, not in YAML, so the operator script creates them. Hosted `ubuntu-latest` agents; Terraform installed from the pinned release zip with checksum. Before 1.3/1.4 the backend and web test checks skip only when no test files exist, so the gate switches on by itself.

## Verification

**Commands:**
- `ci/checks.sh all` -- expected: exit 0
- `uv run --with pytest --with pyyaml pytest ci/tests infra/scripts/tests` -- expected: pass
- `shellcheck ci/*.sh infra/bootstrap/*.sh` -- expected: clean

## Implementation Notes

- Implemented by a coding subagent (2026-09-29). Beyond the plan: shellcheck added to `lint`; `ci/install-tools.sh` pins Terraform 1.16.4, gitleaks 8.30.1, uv 0.11.8 by SHA-256; each gated step is a `_check` stage (no environment) plus a deployment stage; `ado-setup.sh` needs `ADO_APPROVER`, stops if a connection exists with a different binding; `CHECKS_ROOT` test seam in `ci/checks.sh`.
- Contracts for later stories: `ci/code-deploy.sh` fails once `infra/<env>/app` exists until Story 1.3 implements the deploy; `backend/migrations/env.py` reads the standard `PG*` variables; each web app provides `lint`, `format:check`, `typecheck` scripts and Vitest with `@vitest/coverage-v8` (Story 1.4).

## Plan Change Log

## Review Triage Log

**Pass 1 (2026-09-29): blind-hunter, edge-case-hunter, verification-gap, intent-alignment.** Counts: high 2, medium 14, low 9, false 1, maybe-false 1.

| # | Finding | Verdict | Route | Evidence / action |
|---|---------|---------|-------|-------------------|
| 1 | Manual run on any branch uses `azure-prod`/`azure-shared` in `_check` stages with no gate (B1) | high | patch | `_check` stages have no environment; `trigger` limits CI only. Add branch control (`refs/heads/main` only) on the 3 connections and 3 environments in `ado-setup.sh`. |
| 2 | Coverage floor bypassed by deleting all tests while code exists (B6, E1, E2) | high | patch | `run_test` skips whenever no test files exist. Skip only when backend has no code / web app not scaffolded; otherwise fail. |
| 3 | Output-variable paths (`plan.tf.hasChanges`, `detect.detect.hasWork`) only substring-checked; `##vso` branch of `set_output` never run (VG1) | medium | patch | A step rename would skip every deploy with a green run. Resolve paths against compiled jobs/steps; test `set_output` with `TF_BUILD=True`. |
| 4 | PR `test` job lacks terraform/gitleaks, so 3 matrix tests skip in CI (VG2, B7, E12) | medium | patch | Install `[uv, terraform, gitleaks]` in the test job; skips fail under `TF_BUILD`. |
| 5 | `ci/migrate.sh` real path untested (VG3) | medium | patch | Add a migrations-dir seam and fake `az`/`uv`; assert PG* vars per env. |
| 6 | Static `ARM_OIDC_TOKEN` can expire in a long apply (B5, E7) | medium | patch | Use azurerm's ADO service-connection OIDC refresh (`ARM_ADO_PIPELINE_SERVICE_CONNECTION_ID`, `ARM_OIDC_REQUEST_TOKEN=$(System.AccessToken)`, `ARM_OIDC_REQUEST_URL`). |
| 7 | Next step proceeds when a gated stage is Skipped for a reason other than "no changes" (B3) | maybe-false | patch | Unclear whether a timed-out approval ends Skipped; chain on the `_check` output (no changes) or the gated stage Succeeded instead of result `Skipped`. |
| 8 | `_check`-stage chaining conditions untested (B13) | medium | patch | Add chaining checks + mutation test (e.g. `always()`). |
| 9 | `tfplan` artifact holds sensitive values (B2) | medium | patch | Needed across stages. Document the risk, keep retention short, rely on branch control (row 1). |
| 10 | `ci/install-tools.sh` untested (B9) | medium | patch | Test checksum mismatch, unknown tool, platform guard, prepend-path with fake `curl`. |
| 11 | WIF issuer/subject not read back after connection create (E8) | medium | patch | Die unless the subject equals `sc://$ADO_ORG/$ADO_PROJECT/<connection>`. |
| 12 | Environment lookup by `name=` not exact (E9) | medium | patch | Exact-match query. |
| 13 | Weekly scan failure notifies nobody (B12) | medium | patch | README manual step: subscribe Dj to failed builds of `ocrinvoicing-weekly-scan`. |
| 14 | `run_audit` stale requirements / misleading skip after failed export (B11, E4) | low | patch | `rm -f` before export; skip only when export succeeded with no pins. |
| 15 | Prod can need up to 4 approvals per run (B4) | low | patch | Accepted; document in README. |
| 16 | `pytest`/`pyyaml` for CI tests unpinned (B8 part) | low | patch | Pin versions in `ci/lib.sh`. |
| 17 | `install-tools.sh` mktemp without mkdir (E6) | low | patch | `mkdir -p` first. |
| 18 | Fake `az` returns a GUID for pipeline id, making invalid JSON (VG other) | low | patch | Return an integer id. |
| 19 | Web 60% floor pinned only by source text (VG4) | medium | defer | No web tests until Story 1.4; carry the fixture test there. |
| 20 | `uv.lock` missing from diff (B10) | false | reject | Present on disk; my diff excluded `*.lock`. |
| 21 | Overlapping manual runs can plan concurrently (E13) | low | reject | A stale saved plan fails safely at apply; locks cover applies. |
| 22 | JSON bodies built by heredoc interpolation (E10) | low | reject | Inputs are org/project/UPN; adds complexity. |
| 23 | Malformed `package.json` treated as unscaffolded (E3) | low | reject | Unlikely; build/lint fails elsewhere. |
| 24 | Paths with spaces word-split (E5) | low | reject | Repo paths have no spaces. |
| 25 | `pipeline_model.py` accepts a mapping under a conditional (E11) | low | reject | Test helper only. |
| 26 | Node 22.x / Python 3.13 minor versions float (B8 part) | low | reject | Hosted tool cache; majors pinned per plan. |
| 27 | Readings vs runtime ADO surface (intent audit) | — | reject | Descriptive; matches "verify offline". Real-ADO checks are Dj's first run. |
