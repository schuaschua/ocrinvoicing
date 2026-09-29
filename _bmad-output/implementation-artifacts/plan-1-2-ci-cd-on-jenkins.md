---
title: 'Story 1.2 rework: CI/CD on Jenkins'
type: 'refactor'
ticket: '1-2-ci-cd-pipeline-in-azure-devops'
created: '2026-09-29'
status: 'built'
baseline_revision: '9f52a6ea2cbf70f4d2da34952cf6b62837dd5e43'
route: 'full'
route_source: 'auto'
review: 'thorough'
review_source: 'auto'
lenses_ran: ['blind-hunter', 'edge-case-hunter', 'verification-gap', 'intent-alignment']
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/planning-artifacts/sprint-change-proposal-2026-09-29.md'
  - '{project-root}/docs/standards/coding-style.md'
  - '{project-root}/docs/standards/terraform.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Story 1.2's CI/CD is built for Azure DevOps Pipelines, which Dj replaced with Jenkins on a VM (sprint change proposal 2026-09-29, Jira OCR-3). The Azure DevOps org can't be driven from the CLI, and nothing can deploy yet.

**Approach:** Replace the Azure DevOps YAMLs and `ado-setup.sh` with the following, and remove the federated credentials and Azure DevOps inputs from the bootstrap:
- a Jenkins image (Jenkins LTS plus the pinned build tools, with Terraform through the Jenkins Terraform plugin);
- Jenkinsfiles that call the existing `ci/*.sh` scripts;
- `infra/bootstrap/ci-vm.sh`, which uses `az` to create the SSH-only B2s VM, run Jenkins in Docker and attach the shared and Dev deploy identities.

## Boundaries & Constraints

**Always:**
- **Scripts:** the existing `ci/*.sh` scripts stay the single implementation of checks, plan and apply, migrations and code deploy. The Jenkinsfiles only call them.
- **Azure sign-in:** only through the user-assigned deploy identity of the stack's owner. `az login --identity --client-id`, and Terraform through `ARM_USE_MSI`. No Azure secret is stored anywhere.
- **Identities:** only the shared and Dev identities are attached. There are no Prod stages in Jenkins.
- **Stage order** (AD-17): shared foundation, then Dev foundation, migrations, Dev app and code deploy.
- **Plans and approvals:** each stack applies only its own saved, tag-gated plan. The shared stack waits for a Jenkins `input` that only Dj may approve. Dev applies automatically on `main`.
- **PR checks:** Jenkins polls Azure Repos, runs `ci/checks.sh` (lint, test, audit, secrets, terraform) on PR branches, and posts a status to the PR. Merging needs the status, through a branch policy that Dj adds.
- **The Azure DevOps token** is the only secret. It is read from `.work/ado-pat` by `ci-vm.sh`, lives only in Jenkins credentials, and is never logged.
- **VM access:**
  - The NSG allows only SSH from the operator's IP.
  - Jenkins listens on 127.0.0.1 only, reached through an SSH tunnel.
  - The VM is a B2s running Ubuntu LTS, with no auto-shutdown.
- **Pins:** tool versions, the Jenkins image tag and plugins are pinned. `ci-vm.sh` is idempotent and supports `--dry-run`, like the other bootstrap scripts.
- **Test cap:** the repo stays at or under 200 test cases; it is 198 today.

**Decisions at review (Dj, 2026-09-30):** Branch builds run each branch's own Jenkinsfile on the VM that holds the shared and Dev identities, so code in any pushed branch can obtain their tokens and bypass the shared approval. This is accepted for the PoC because only Dj and Claude push, recorded next to the azure.md rule 31 exception; harden before anyone else gets push access or before Prod. The $8 subscription budget is dropped, because the subscription holds Dj's other projects; the resource-group budgets track this project.

**Never:**
- Prod deploys from this VM.
- A public web port.
- Terraform, migrations or app resources created by `ci-vm.sh`.
- Changing the Terraform stacks, the backend or the web apps.
- Running `ci-vm.sh` or any Azure command during implementation. Tests use the fake `az` and `--dry-run`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| VM bootstrap | `ci-vm.sh` with operator IP, SSH public key and `.work/ado-pat` | rg-23, NSG (SSH from that IP only), B2s VM, Jenkins container on 127.0.0.1:8080, token in Jenkins credentials | Missing input or token file → stops before any change |
| Identities not there yet | `id-21`/`id-22` absent | VM and Jenkins are created; a warning names `state-backend.sh`; a re-run attaches them | — |
| Re-run | Everything exists | No create calls; settings re-applied | — |
| PR build | A PR branch | `checks.sh` stages run; a pass or fail status is posted to the PR | Status post fails → build fails |
| Merge to main | Changes in shared and Dev | Plan shared → wait for Dj → apply; then Dev foundation, migrate, app, code with auto-apply | A stack with no changes is skipped (`hasWork=false`) |
| Terraform sign-in | A stage for owner X | `ARM_USE_MSI=true`, `ARM_CLIENT_ID` = X's client id, no OIDC or CLI variables | Client id not configured → the stage fails, naming it |

</frozen-after-approval>

## Code Map

- `pipelines/*.yml` (the stage chain, check-then-gate on `hasWork`, saved-plan artifacts) and `infra/bootstrap/ado-setup.sh` (approvals) -- the behaviour to reproduce, then delete.
- `ci/lib.sh:52-85`:
  - `set_output` (`##vso`) becomes a key=value file (`$CI_OUTPUT_FILE`) that Jenkins reads.
  - `export_arm_context` gets an MSI branch for `CI_MSI_CLIENT_ID`. The OIDC/`TF_BUILD` branch and the `AZURESUBSCRIPTION_*`/`tenantId` fallbacks go.
- `ci/migrate.sh:71-72` (`##vso` setsecret) and `ci/install-tools.sh:66-67` (prependpath): drop the ADO bits. The usage text in `terraform-plan.sh`, `terraform-apply.sh`, `migrate.sh` and `code-deploy.sh` names AzureCLI@2; reword it.
- `ci/checks.sh:29,173` (`TF_BUILD` means CI and never skip a11y) and the other `TF_BUILD` uses (`backend/tests/conftest.py:136,262`, `web/*/playwright.config.ts:10`, `ci/tests/test_checks_matrix.py:33-41`): keep the variable as the "running in CI" flag. The Jenkinsfile sets `TF_BUILD=true`.
- `ci/install-tools.sh` + `ci/lib.sh:17-31` pins: reuse them in the Jenkins image (Debian amd64, `CI_TOOLS_DIR=/usr/local/bin`). Also add Python 3.13, Node 22, shellcheck, az CLI, the Docker CLI and the Playwright/Chromium dependencies.
- `infra/bootstrap/state-backend.sh`:
  - Remove: `:19-41` (ADO inputs, `service_connection_name`), `:147-168` (federated credentials) and comments `:5`, `:136`.
  - Keep: identity creation `:137-145` and roles `:175-198`.
- `infra/bootstrap/lib.sh` -- reuse `rg_name`, `resource_name`, `deploy_identity_name`, `STATE_RG`, `LOCATION`, `set_tags`/`TAGS`, `run`, `query`, `exists`, `value_or_placeholder`, `parse_common_args`, `require_env`, `require_tools`, `step`, `log`, `warn` and `die`. The CI resource group is `rg-23`.
- Tests:
  - Delete `ci/tests/test_pipelines.py` (4), `test_ado_setup.py` (2) and `pipeline_model.py`.
  - Rewrite `test_ci_scripts.py:115` (ADO OIDC) for MSI.
  - Keep the CI-agnostic guards from `test_pipelines.py` `repo_guards`: no auto-approve, one `terraform apply` line, operator scripts not called from CI, sha pins.
  - Remove the federated-credential assertions: `infra/scripts/tests/test_bootstrap_scripts.py:130-143`, `test_bootstrap_matrix.py:89-113`, and the devops/fed branches in `fake-bin-stateful/az`.
- Docs: `README.md:13,21,37-43`, `infra/bootstrap/README.md` (the ADO inputs and ADO section, `pipelines/deploy.yml`, tfplan retention), `verify-db-isolation.sh:10`, and `docs/architecture/diagrams/deployment.{model.json,drawio}` (node `ado`).

## Tasks & Acceptance

**Execution:**
- [x] `ci/jenkins/Dockerfile`, `plugins.txt`, `casc.yaml` -- a Jenkins LTS image with the pinned tools and plugins (git, workflow-aggregator, terraform, credentials-binding, configuration-as-code, job-dsl). JCasC sets up:
  - the local admin, whose password is generated on the VM;
  - the Terraform tool 1.16.4;
  - the token credential, read from a mounted secret file;
  - the identity client ids as global environment variables;
  - a multibranch job on the Azure Repos URL, polling every 5 minutes, and the weekly scan job.
- [x] `Jenkinsfile` (repo root) and `ci/jenkins/Jenkinsfile.weekly`:
  - on PRs, the checks stages plus a status post (`ci/ado-status.sh`, which uses the token from the credential and never echoes it);
  - on `main`, the checks, then the AD-17 deploy chain for shared (plan, `input` for Dj, apply) and Dev (auto);
  - a weekly cron for `checks.sh audit`.
- [x] `ci/lib.sh`, `ci/*.sh` -- the output file, MSI sign-in and ADO wording, as in the Code Map.
- [x] `infra/bootstrap/ci-vm.sh` -- the matrix rows. Inputs:
  - `ARM_SUBSCRIPTION_ID`;
  - `CI_SSH_SOURCE_IP`;
  - `CI_SSH_PUBLIC_KEY_FILE`;
  - `ADO_ORG`/`ADO_PROJECT` (the repo URL);
  - `.work/ado-pat`.

  It creates or updates the tagged rg-23, VNet/subnet, NSG, public IP, NIC and VM (Ubuntu LTS, B2s). Docker and Jenkins come up through cloud-init or `az vm run-command`, with the Jenkins port bound to 127.0.0.1 and `jenkins_home` on a named volume. It attaches `id-21` and `id-22` if they exist, and copies the token into the Jenkins secret file over SSH.
- [x] Remove `pipelines/`, `infra/bootstrap/ado-setup.sh`, and the state-backend federated credentials and ADO inputs. Update the READMEs, including a "Push to Azure Repos" step and the Jenkins first-run steps (SSH tunnel, admin password, add the branch policy), plus the diagrams.
- [x] Tests -- at most 4 new cases in total:
  - the `ci-vm.sh` dry-run and stateful matrix;
  - the Jenkinsfile guards (stage order, `input` only on shared, no Prod, no auto-approve, `checks.sh` subcommands);
  - MSI sign-in in `test_ci_scripts.py`.

**Acceptance Criteria:**
- Given `ci/checks.sh all`, when it runs, then it exits 0 and the test-case line is at most 200.
- Given `docker build ci/jenkins`, when it runs locally, then the image builds and `terraform version`, `az version`, `uv --version`, `node --version` and `gitleaks version` work inside it.

## Implementation Notes

- 2026-09-29: plan auto-approved at Checkpoint 1 (no Open Questions; Dj authorised auto-approval for overnight work). About 2,000 tokens, kept whole as for Story 1.6.
- 2026-09-29, implementation:
  - The image's build context is `ci/jenkins` (the AC's `docker build ci/jenkins`), so it can't read `ci/lib.sh`: the tool pins are repeated as Dockerfile `ARG`s and `ci/tests/test_jenkins.py` checks they equal `ci/lib.sh`. `install-tools.sh` stays for Linux hosts (its ADO temp variable became `CI_TEMP_DIR`).
  - Pinned: Jenkins 2.568.3 LTS (by digest), the six plugins plus their whole resolved dependency set, Node 22.23.3, shellcheck 0.11.0, Docker CLI 29.8.1, az CLI 2.90.0 (pip in a venv: Microsoft has no Debian 13 apt build and uv refuses its pre-release pins), Python 3.13 from Debian 13.
  - The Jenkins container runs with `--network host` (Jenkins bound to 127.0.0.1:8080 by `JENKINS_OPTS`), because the backend tests publish their PostgreSQL container on the host's 127.0.0.1.
  - `ci/checks.sh` installs Playwright's Chromium without `--with-deps`: the system libraries are baked into the image and the jenkins user can't run apt.
  - The deploy identity's `az login --identity` runs in the Jenkinsfile (per-owner `AZURE_CONFIG_DIR`); `ci/lib.sh` only sets the Terraform variables from `CI_MSI_CLIENT_ID`.
  - The VM set-up after creation runs over SSH (`ci-vm-remote.sh`); cloud-init only installs Docker.
  - 2026-09-30, after review: the Terraform tool's home is the image's `/usr/local/bin` (no plugin download); `agent none` with per-stage agents and a stage-level `input`, so the approval holds no executor; the weekly cron only in `casc.yaml`; `ci-vm-remote.sh` recreates the container only when the image or settings changed and refuses while a build runs; `ci-vm.sh` starts a deallocated VM, forgets a new VM's old host key and accepts cloud-init exit 2; the subscription budget is dropped from `budget-and-roles.sh`; the branch-trust risk is recorded in `azure.md`.
  - Verified locally: the image builds and the tools answer; Jenkins starts with `casc.yaml` (jobs, Terraform tool, credential created) and its declarative linter accepts both Jenkinsfiles.

## Design Notes

- **Docker socket.** The Jenkins container gets `/var/run/docker.sock` so that the backend tests can start PostgreSQL containers. That makes Jenkins root-equivalent on the VM, which is acceptable on a single-purpose, SSH-only VM. Record it in the README.
- **Client ids.** `ci-vm.sh` reads the identities' client ids (`az identity show --query clientId`) and writes them into the JCasC environment. They are not secrets.
- **Token scopes.** Pushing the repo needs Code *Read & write*. Jenkins needs Code Read and Code Status. Dj's token is created with Read & write and Status.

## Verification

**Commands:**
- `ci/checks.sh all` -- expected: exit 0, at most 200 test cases
- `docker build -t ocr-jenkins ci/jenkins` -- expected: builds; the tools answer inside the image

## Review Triage Log

Lenses ran one at a time. B = blind-hunter, E = edge-case-hunter, V = verification-gap, I = intent-alignment.

| # | Finding | Verdict | Route |
|---|---|---|---|
| B1, B2, E9, V-o1 | Any branch's Jenkinsfile or test code can use the shared and Dev identities through the metadata endpoint, bypassing the shared approval; per-stack isolation is only convention | high | Dj accepted it for the PoC (decision above): record it as a documented exception; README statement corrected |
| B6, I | The deploy stages use Terraform downloaded by the plugin with no checksum | medium | patch: point the plugin's Terraform tool at the image's checksum-verified `/usr/local/bin/terraform` (no download) |
| B5, E7 | The `shared` input holds an executor for up to 24 h and blocks the chain | medium | patch: `agent none` at the top level with per-stage agents; the input runs without an executor |
| E2 | Re-running `ci-vm.sh` does `docker rm -f` mid-deploy | medium | patch: recreate the container only when the image or config changed, and refuse while builds run |
| E3 | `ci-vm.sh` on a deallocated VM times out on ssh | medium | patch: start the VM first when it isn't running |
| E4 | A recreated VM changes its host key, and ssh refuses | low | patch: drop the known_hosts entry when the VM was just created |
| E5 | `cloud-init status --wait` exit 2 (degraded) stops the setup | low | patch: accept exit code 2 |
| E6, E8 | `post` cleanup and the status post can fail and mask the result | low | patch: make the cleanup tolerant; catch status-post failures |
| B3, E1 | A branch built before its PR opens never gets a status | medium | patch: document "Build Now" after opening a PR (poll-only Jenkins can't see new PRs) |
| B4 | A status stuck on pending after a restart | low | patch: README recovery step (rebuild the branch) |
| V1 | The `CI_OUTPUT_FILE` hasWork contract is untested | medium (gap) | patch: assertions in the existing tag-gate and migrate tests |
| V2, B12 | `ci/ado-status.sh` is never run by a test | medium (gap) | patch: one new test with a fake curl |
| V3 | The Jenkinsfile and the VM-side setup are only checked as text | medium (gap) | defer: needs a Jenkins test harness |
| B8 | Story 1.2's criteria still say Prod applies after approval | medium | patch: criterion says Prod has no Jenkins stage until Dj decides (epics and Jira) |
| B9 | No Prod deploy path is tracked | low | defer |
| B10 | A failed weekly scan alerts nobody; the cron is defined twice | low | patch: keep one cron definition; document; email alert deferred |
| B11 | No patching plan for the Jenkins image and plugins | low | defer |
| B13 | The README push step puts the token on a command line | medium | patch: pass it through `GIT_CONFIG_*` environment variables or a credential helper |
| B14 | B2s memory with 2 executors; no `jenkins_home` backup | low | patch: document; set `numExecutors: 2` (kept, with `agent none`) |
| B15 | The admin-password note is misleading | low | patch: say to change it in the secret file |
| B7 | `plugins.txt` missing from the diff | false | Left out of the review diff on purpose (size); it is in the tree and will be committed |
| E10, V-o2 | The PostgreSQL token is no longer masked | low | reject: never printed; no Jenkins credential to mask |
| E11 | No JUnit report in the Jenkins UI | low | defer |
| V-o3 | Group 1000 (the VM admin) can read the secrets | false | The admin already has sudo, so it can read them anyway |
| I | Scope narrowed to shared and Dev; an extra token integration; operational success unproven | false | These follow Dj's decisions; a live run is the first-deploy step |
