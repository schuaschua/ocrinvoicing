# OCR Invoice Automation PoC

Suppliers upload invoice photos or PDFs by link; Azure Document Intelligence reads them, the pipeline validates them against purchase orders and goods received, exceptions go to an admin queue, and clean invoices post to the accounts system. The architecture is in `_bmad-output/planning-artifacts/architecture/` (spine) and `docs/architecture/`; the rules are in `docs/standards/`.

## Layout

```text
backend/     Python 3.13 Azure Functions (v2 model): src/invoicing/{domain,ports,adapters,apps}, migrations/, tests/
web/         supplier/ and staff/: Vite + React + TypeScript single-page apps, each served by its API app
             from the same origin (client routes must not start with api/, admin/ or runtime/)
shared/      quality-thresholds.json and the client-side photo quality check (quality/)
infra/       Terraform and operator scripts (terraform.md)
  bootstrap/   operator scripts for AD-17 steps 1, 3, 4b and 5 and the Azure DevOps setup; see infra/bootstrap/README.md
  modules/     naming (P-16 names, P-17 tags), env-foundation and env-app
  shared/      foundation: PostgreSQL, Document Intelligence F0, ACS Email (both environments)
  dev/, prod/  foundation: identities, storage, Key Vault, monitoring, budget per environment;
               app: the four Flex Function apps, their plans, settings and runtime roles
  scripts/     check_tags.py (P-17 tag gate) and its tests
ci/          checks.sh (the PR checks, runnable locally) and the deploy-stage scripts (code-deploy.sh builds
             one zip per Function app; --build-only builds without publishing); tests/ for the pipelines
pipelines/   Azure DevOps YAML: pr.yml, deploy.yml, weekly-scan.yml and templates/
docs/        architecture, standards, governance and costing
```

## Infrastructure at a glance

- One subscription, region `southeastasia`, resource groups `babaloo-sea-lng-rg-21` (shared), `-rg-01` (dev) and `-rg-11` (prod).
- Terraform state in `babaloosealngst21` (Entra auth only) in the bootstrap-only group `babaloo-sea-lng-rg-22`, together with the deploy identities; one container per stack owner, keys `foundation.tfstate` and (dev, prod) `app.tfstate`.
- Apply order and operator steps: `infra/bootstrap/README.md`.

## Checks (offline, no Azure access needed)

```sh
ci/checks.sh all      # or one of: lint, test, audit, secrets, terraform
```

The same script runs in the PR build (`pipelines/pr.yml`), so a green local run means a green PR build. It needs `uv`, `terraform`, `gitleaks`, `shellcheck` and Node 22. The web a11y check (Playwright + axe) needs Chromium for each app: run `npx playwright install chromium` in `web/supplier` and in `web/staff` (they pin the same Playwright, so the second run finds it installed); without it the check is skipped locally, while the PR build installs it and never skips. Reports go to `.work/ci/`.

The Terraform tests use mock providers; the script tests run every bootstrap script with `--dry-run` against fake `az`/`psql`/`gpg` binaries that fail if called, and `ci/tests` checks the pipeline YAML (AD-17 stage order, approval environments, saved plans, tag gate).

## Pipelines (Azure DevOps)

`pipelines/pr.yml` (PR build, required by the branch policy on `main`), `pipelines/deploy.yml` (every merge to `main`: Terraform in the AD-17 order, migrations, code deploy; `shared` and Prod after approval) and `pipelines/weekly-scan.yml` (dependency audit every Monday). `infra/bootstrap/ado-setup.sh` creates them with their service connections, environments and branch policy; see `infra/bootstrap/README.md`.
