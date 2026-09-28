# OCR Invoice Automation PoC

Suppliers upload invoice photos or PDFs by link; Azure Document Intelligence reads them, the pipeline validates them against purchase orders and goods received, exceptions go to an admin queue, and clean invoices post to the accounts system. The architecture is in `_bmad-output/planning-artifacts/architecture/` (spine) and `docs/architecture/`; the rules are in `docs/standards/`.

## Layout

```text
backend/     Python 3.13 Azure Functions (v2 model): src/invoicing/{domain,ports,adapters,apps}, migrations/, tests/
web/         supplier/ and staff/: Vite + React + TypeScript single-page apps, each served by its API app
shared/      quality-thresholds.json and the client-side photo quality check (quality/)
infra/       Terraform and operator scripts (terraform.md)
  bootstrap/   operator scripts for AD-17 steps 1, 3, 4b and 5; see infra/bootstrap/README.md
  modules/     naming (P-16 names, P-17 tags) and env-foundation
  shared/      foundation: PostgreSQL, Document Intelligence F0, ACS Email (both environments)
  dev/, prod/  foundation: identities, storage, Key Vault, monitoring, budget per environment
  scripts/     check_tags.py (P-17 tag gate) and its tests
docs/        architecture, standards, governance and costing
```

## Infrastructure at a glance

- One subscription, region `southeastasia`, resource groups `babaloo-sea-lng-rg-21` (shared), `-rg-01` (dev) and `-rg-11` (prod).
- Terraform state in `babaloosealngst21` (Entra auth only) in the bootstrap-only group `babaloo-sea-lng-rg-22`, together with the deploy identities; one container per stack owner, key `foundation.tfstate`.
- Apply order and operator steps: `infra/bootstrap/README.md`.

## Checks (offline, no Azure access needed)

```sh
terraform fmt -check -recursive infra
for r in infra/shared/foundation infra/dev/foundation infra/prod/foundation; do
  terraform -chdir=$r init -backend=false && terraform -chdir=$r validate && terraform -chdir=$r test
done
for m in infra/modules/naming infra/modules/env-foundation; do
  terraform -chdir=$m init -backend=false && terraform -chdir=$m test
done
uv run --with pytest pytest infra/scripts/tests
```

The Terraform tests use mock providers; the script tests run every bootstrap script with `--dry-run` against fake `az`/`psql`/`gpg` binaries that fail if called.
