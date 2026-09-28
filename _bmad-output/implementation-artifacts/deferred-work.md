- source_plan: `_bmad-output/implementation-artifacts/plan-1-1-repository-and-terraform-foundation.md`
  summary: Decide whether the env deploy identity (Key Vault Secrets Officer) and Dj's load-script user (Secrets User on the vault) should be able to read `pgp-private-key`.
  evidence: AD-17 grants both roles vault-wide; only `staff-api` needs the private key (AD-11). Raise with Dj alongside the open bank-crypto questions before 1.6/2.3.
- source_plan: `_bmad-output/implementation-artifacts/plan-1-1-repository-and-terraform-foundation.md`
  summary: Add diagnostic settings (Key Vault AuditEvent, PostgreSQL, DI, ACS) to the environment Log Analytics workspace.
  evidence: No diagnostic settings exist in 1.1; azure.md rule 15. Belongs with Story 1.5 monitoring.
- source_plan: `_bmad-output/implementation-artifacts/plan-1-1-repository-and-terraform-foundation.md`
  summary: Execute `database-step5.sql` against a real PostgreSQL 18 (container with a `pgaadauth_create_principal` stub) and assert CONNECT isolation.
  evidence: Unverified (medium): only fakes run today. Would also settle whether PG 16+ lets the Entra admin `GRANT deploy_login TO CURRENT_USER`.
- source_plan: `_bmad-output/implementation-artifacts/plan-1-1-repository-and-terraform-foundation.md`
  summary: Confirm azurerm updates to `azurerm_communication_service` do not reset `disableLocalAuth` set by `azapi_update_resource`.
  evidence: Unverified (medium): settle with a live plan/apply after a tag change.
- source_plan: `_bmad-output/implementation-artifacts/plan-1-1-repository-and-terraform-foundation.md`
  summary: Run `check_tags.py` against real `terraform show -json` output of all three roots in the pipeline.
  evidence: Only synthetic fixtures today; pipeline wiring is Story 1.2.
- source_plan: `_bmad-output/implementation-artifacts/plan-1-2-ci-cd-pipeline-in-azure-devops.md`
  summary: Add a fixture test proving the web 60% Vitest coverage floor fails the `test` check.
  evidence: Only a source-text check pins `WEB_COVERAGE_MIN=60`; no web app has Vitest until Story 1.4.
