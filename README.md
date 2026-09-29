# OCR Invoice Automation PoC

Suppliers upload invoice photos or PDFs by link; Azure Document Intelligence reads them, the pipeline validates them against purchase orders and goods received, exceptions go to an admin queue, and clean invoices post to the accounts system. The architecture is in `_bmad-output/planning-artifacts/architecture/` (spine) and `docs/architecture/`; the rules are in `docs/standards/`.

## Layout

```text
backend/     Python 3.13 Azure Functions (v2 model): src/invoicing/{domain,ports,adapters,apps}, migrations/, tests/
web/         supplier/ and staff/: Vite + React + TypeScript single-page apps, each served by its API app
             from the same origin (client routes must not start with api/, admin/ or runtime/)
shared/      quality-thresholds.json and the client-side photo quality check (quality/)
infra/       Terraform and operator scripts (terraform.md)
  bootstrap/   operator scripts for AD-17 steps 1 (with the CI VM, ci-vm.sh), 3, 4b and 5; see infra/bootstrap/README.md
  modules/     naming (P-16 names, P-17 tags), env-foundation and env-app
  shared/      foundation: PostgreSQL, Document Intelligence F0, ACS Email (both environments)
  dev/, prod/  foundation: identities, storage, Key Vault, monitoring, budget per environment;
               app: the four Flex Function apps, their plans, settings and runtime roles
  scripts/     check_tags.py (P-17 tag gate) and its tests
ci/          checks.sh (the branch checks, runnable locally) and the deploy-stage scripts (code-deploy.sh builds
             one zip per Function app; --build-only builds without publishing); jenkins/ (the Jenkins image,
             plugins, configuration as code and the weekly-scan Jenkinsfile); tests/ for the CI
Jenkinsfile  the CI/CD pipeline Jenkins runs for every branch
docs/        architecture, standards, governance and costing
```

## Infrastructure at a glance

- One subscription, region `southeastasia`, resource groups `babaloo-sea-lng-rg-21` (shared), `-rg-01` (dev) and `-rg-11` (prod).
- Terraform state in Dj's existing account `stdjtfstatesea` (group `rg-tfstate-sea`, Entra auth only; Dj, 2026-09-30); one container per stack owner (`ocrinvoicing-shared`, `-dev`, `-prod`), keys `foundation.tfstate` and (dev, prod) `app.tfstate`. The deploy identities live in the bootstrap-only group `babaloo-sea-lng-rg-22`.
- Apply order and operator steps: `infra/bootstrap/README.md`.

## Checks (offline, no Azure access needed)

```sh
ci/checks.sh all      # or one of: lint, test, audit, secrets, terraform
```

The same script runs in Jenkins on every branch (`Jenkinsfile`), so a green local run means a green branch build. It needs `uv`, `terraform`, `gitleaks`, `shellcheck` and Node 22. The web a11y check (Playwright + axe) needs Chromium for each app: run `npx playwright install chromium` in `web/supplier` and in `web/staff` (they pin the same Playwright, so the second run finds it installed); without it the check is skipped locally, while Jenkins installs it and never skips. Reports go to `.work/ci/`.

The Terraform tests use mock providers; the script tests run every bootstrap script with `--dry-run` against fake `az`/`psql`/`gpg` binaries that fail if called, and `ci/tests` checks the Jenkinsfiles and the Jenkins image (AD-17 stage order, Dj's approval on `shared`, no Prod stage, saved plans, pinned tools).

## CI/CD (Jenkins on the CI VM)

The code lives in Azure Repos (`example-org/ocrinvoicing`). Jenkins runs in Docker on one small VM (`infra/bootstrap/ci-vm.sh`; SSH from Dj's IP only, the UI through an SSH tunnel) and polls it every 5 minutes:

- every branch: `ci/checks.sh` (lint, test, audit, secrets, terraform), with the result posted as the status `jenkins/checks` on the branch's pull request; a branch policy on `main` requires it;
- `main`: the checks, then the AD-17 chain from saved, tag-gated plans: `shared/foundation` after Dj approves, then `dev/foundation`, Dev migrations, `dev/app` and the Dev code deploy, applied automatically. Each stage signs in as its stack's deploy identity attached to the VM; no Azure secret is stored. Only the shared and Dev identities are on the VM, so there are no Prod stages (Dj, 2026-09-29);
- `ci/jenkins/Jenkinsfile.weekly`: the dependency audit every Monday.

Setup, first run and the branch policy: `infra/bootstrap/README.md`, steps 1b and 1c.
