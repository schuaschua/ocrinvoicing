---
title: 'Sprint Change Proposal: CI/CD on Jenkins instead of Azure DevOps Pipelines'
date: '2026-09-29'
author: Dj (decisions), Claude (analysis)
status: 'approved'
scope: 'moderate'
---

# Sprint Change Proposal: CI/CD on Jenkins

## 1. Issue summary

**Trigger.** Story 1.2 (CI/CD) can't be set up as designed. The Azure DevOps org `example-org` doesn't recognise Dj's Entra guest identity from the CLI ("Identity 19e200c3… has not been materialized"). Service connections and pipelines can't be created, and the org id can't be read. Dj prefers to run Terraform and CI on a small VM with Jenkins for the PoC.

**Kind of change:** a strategic change to delivery tooling. No product requirement changes.

**Decisions (Dj, 2026-09-29):**
- **Scope:** Jenkins runs all CI/CD: PR checks (`ci/checks.sh`), Terraform plan and apply per stack, migrations and the code deploy. Azure DevOps Pipelines is no longer used.
- **Code:** code and Terraform modules stay in Azure Repos (`example-org/ocrinvoicing`).
- **Host:** one small Ubuntu VM runs Jenkins in Docker. Terraform is installed through the Jenkins Terraform plugin (tool installer), and the build tools are pinned in the Jenkins image. `az` commands in a new bootstrap script create the VM and its network.
- **Access:** SSH only. The NSG allows SSH from Dj's IP, the Jenkins UI is reached through an SSH tunnel, and there is no public web port.
- **Azure sign-in:** the existing per-stack user-assigned deploy identities are attached to the VM. No Azure secrets are stored, and the AD-17 deploy-identity rights don't change. Federated credentials are no longer needed.
- **Identities on the VM:** only the shared and Dev deploy identities, so nothing on the VM can reach Prod. Prod gets a separate decision later.
- **PR gating:** Jenkins polls Azure Repos and posts a status to each PR. An Azure Repos branch policy requires that status before a merge. One ADO personal access token (Code read, Status write) is kept in Jenkins credentials; it is the only stored secret.
- **Environments:** Dev only for now.

## 2. Impact analysis

- **Epics:**
  - Epic 1 stays completable. Story 1.2 is reworked (see 4.3). Story 1.1's bootstrap gains the VM script, and the deploy identities lose their federated credentials.
  - No epic becomes obsolete, none is added, and the order doesn't change.
  - Stories 1.3, 2.2 and 2.3 and the migration steps say "the pipeline" meaning delivery. Their wording stays and now means the Jenkins job.
- **Product:** `SPEC.md` has no conflict (CI/CD isn't a product requirement), and the MVP is unchanged. UX is not affected.
- **Architecture:**
  - Principles: P-20 and context row 15 (`docs/architecture/azure.md`).
  - AD-17: step 1, "Repo and pipeline", the approvals, the GitHub-rule replacements and the deployment diagram.
- **Standards:** the `terraform.md` exception row for rules 31–34. `azure.md` gets a new accepted exception for the long-lived CI VM holding the deploy identities.
- **Code:**
  - `pipelines/*.yml` and `infra/bootstrap/ado-setup.sh` are replaced by `Jenkinsfile`s and `infra/bootstrap/ci-vm.sh` (VM, NSG, identities, Docker, Jenkins).
  - `ci/*.sh` stays: Jenkins calls the same scripts.
  - `state-backend.sh` drops the federated credentials and the `ADO_ORG_ID` input.
  - `ci/tests` pipeline-model tests become Jenkinsfile tests, within the 200-test-case cap.
- **Risks:**
  - The VM is a long-lived host holding deploy identities: any job on it can use the shared and Dev identities.
  - The VM must be patched.
  - The ADO personal access token is a stored secret with an expiry.
  - Cost: a B2s VM (2 vCPU, 4 GB) is roughly $30–40 a month at list price if always on. Dj deallocates it when not in use. No auto-shutdown for now: it runs overnight while work continues, and a schedule is added later (Dj, 2026-09-29).
- **Jira:** OCR-3 (Story 1.2) is rewritten and moved back to In Progress. OCR-127 (create the ADO project) stays Done, since the repo still lives there.

## 3. Recommended approach

**Direct adjustment.** Rework Story 1.2 and extend Story 1.1's bootstrap. No rollback: the checks scripts, Terraform stacks and bootstrap scripts are reused as they are. Effort is about one story.

The main risk is Jenkins-on-VM operations: patching, and the long-lived identities. For a Dev-only PoC with SSH-only access, it is acceptable.

## 4. Detailed change proposals

### 4.1 Principles (`docs/architecture/azure.md`)

- **Row 15, OLD:** `CI/CD: Azure DevOps Pipelines.`
  **NEW:** `CI/CD: Jenkins in Docker on one VM, running Terraform (code in Azure Repos) (Dj, 2026-09-29).`
- **P-20 rule, OLD:** `… and Azure DevOps Pipelines for CI/CD.`
  **NEW:** `… and Jenkins (in Docker on one Azure VM, code in Azure Repos) for CI/CD (Dj, 2026-09-29).`
- **Change log:** add a row: `2026-09-29 | P-20, row 15 | CI/CD moves to Jenkins on a VM | Dj, sprint change proposal 2026-09-29`.

### 4.2 Architecture spine, AD-17

- **Step 1 row:**
  - Replace "deploy identities … with federated credentials" with "deploy identities for `dev`, `prod` and `shared` (no federated credentials)".
  - Add a step `1c. infra/bootstrap/ci-vm.sh | operator with Owner, az CLI | the CI VM (Ubuntu, B2s: 2 vCPU, 4 GB, in resource group babaloo-sea-lng-rg-23), its NSG (SSH from the operator's IP only, no web port), Docker and Jenkins; attaches the shared and Dev deploy identities`.
- **"Repo and pipeline", OLD:** `The code lives in Azure Repos. Azure DevOps Pipelines runs Terraform through workload-identity-federation service connections, one deploy identity per stack owner.`
  **NEW:** `The code lives in Azure Repos. Jenkins, in Docker on the CI VM, runs the checks, Terraform, migrations and the code deploy. Each stage signs in as its stack's user-assigned deploy identity attached to the VM (\`az login --identity --client-id\`). Terraform comes from the Jenkins Terraform plugin, pinned. Only the shared and Dev identities are attached (Dj, 2026-09-29).`
- **Approvals:** "Prod and `shared` apply a saved plan only after a manual approval" stays. The approval is a Jenkins `input` step, restricted to Dj.
- **PR gating (new bullet):** `Jenkins polls Azure Repos, runs ci/checks.sh on each PR and posts a status; a branch policy on main requires that status. The ADO personal access token for polling and status is the only stored secret, in Jenkins credentials.`
- **GitHub replacements:**
  - Rule 10 (OIDC) becomes "met by managed identities, with no stored Azure credentials".
  - Rule 30 becomes "gitleaks as a required PR status under branch policy".
  - The Dependabot replacement stays.
- **Diagram:** `ado[Azure DevOps Pipelines + Terraform]` becomes `ci[Jenkins + Terraform on the CI VM]`.

### 4.3 `epics.md`

- **NFR18, OLD:** `The approved services are PostgreSQL Flexible Server, Document Intelligence and Azure DevOps Pipelines.`
  **NEW:** `… and Jenkins on one VM for CI/CD (Dj, 2026-09-29).`
- **Infrastructure note (line 92), OLD:** `Azure DevOps pipelines authenticate with workload identity federation, …`
  **NEW:** `Jenkins on the CI VM authenticates with the per-stack deploy identities attached to the VM; Dev applies its saved plan automatically on merge, …` (the rest unchanged).
- **Story 1.2**, retitled "CI/CD on Jenkins". The acceptance criteria change as follows:
  - **PR build:**
    - "When the PR build runs" becomes "When Jenkins builds the PR (polling Azure Repos)".
    - "a failing check blocks the merge through branch policy" becomes "Jenkins posts the result as a PR status, and a branch policy on `main` requires it to merge".
  - **Deploy:**
    - "it authenticates only through workload-identity-federation service connections, one deploy identity per stack owner" becomes "each stage signs in only as its stack's user-assigned deploy identity attached to the CI VM; no Azure secret is stored; only the shared and Dev identities are attached (Dj, 2026-09-29)".
    - The Dev auto-apply, the manual approval for shared and Prod (now a Jenkins input step), and the operator steps are unchanged.
  - **New criterion:** **Given** the CI VM bootstrap (`ci-vm.sh`) **When** it runs **Then**:
    - the VM runs Jenkins in Docker, with Terraform installed through the Jenkins Terraform plugin and the build tools pinned;
    - its NSG allows only SSH from the operator's IP, and Jenkins is reached through an SSH tunnel;
    - it is a B2s (2 vCPU, 4 GB) with no auto-shutdown for now (added later), and Dj deallocates it when not in use (Dj, 2026-09-29).
  - **Unchanged:** the weekly scan (now a Jenkins cron) and the migrations criterion.
  - **Tasks:**
    - The ADO-project task stays (the repo lives there).
    - Add: create the ADO personal access token (Code read, Status write) and the branch policy.
    - Add: replace `pipelines/*.yml` and `ado-setup.sh` with `Jenkinsfile`s and `ci-vm.sh`.

### 4.4 Standards

- **`terraform.md` exception, rules 31–34, OLD:** `Azure Repos and Azure DevOps Pipelines instead of GitHub Actions: workload identity federation service connections replace GitHub OIDC; ADO environments with approvals replace GitHub Environments.`
  **NEW:** `Azure Repos and Jenkins (Docker on one VM) instead of GitHub Actions: user-assigned deploy identities attached to the VM replace GitHub OIDC; Jenkins input steps restricted to Dj replace GitHub Environments; a PR status required by branch policy replaces required checks (Dj, 2026-09-29).`
- **`azure.md`, new accepted exception, rule 31:** `The deploy identities for shared and dev are attached to a long-lived CI VM (Jenkins), so any job on it can use them; SSH-only access, only Dj's IP, Prod not attached. Approved by Dj (owner), 2026-09-29. Close by: end of PoC or before Prod is deployed from it.`

### 4.5 Sprint status and Jira

- `sprint-status.yaml`: `1-2-ci-cd-pipeline-in-azure-devops` goes back to `in-progress`.
- **OCR-3:** new summary "1.2 CI/CD on Jenkins" and the rewritten description. Moved to In Progress. Subtasks are updated per the new tasks.

## 5. Implementation handoff

- **Scope:** moderate. It is an architecture change agreed by Dj; the architect edits are listed above, and then a developer builds the reworked Story 1.2.
- **Order:**
  1. Apply the document edits and sync Jira.
  2. Build Story 1.2 (`bmad-build`), within the 200-test-case cap.
  3. Run the Dev setup:
     - bootstrap scripts;
     - `ci-vm.sh`;
     - Jenkins jobs;
     - shared and Dev foundation from Jenkins;
     - steps 4b and 5;
     - migrations;
     - Dev app and code deploy.

     Each step that creates billable resources waits for Dj's go-ahead.
- **Success criteria:**
  - A PR to `main` is checked by Jenkins and blocked on failure.
  - A merge applies Dev from a saved plan.
  - The Jenkins UI is reachable only through the SSH tunnel.
  - No Azure secret is stored anywhere.

## Approval

Approved by Dj, 2026-09-29, with a B2s VM that Dj deallocates when not in use (no auto-shutdown for now; it runs overnight while work continues, and a schedule comes later).
