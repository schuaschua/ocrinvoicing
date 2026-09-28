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
- source_plan: `_bmad-output/implementation-artifacts/plan-1-3-python-functions-api-skeleton.md`
  summary: Isolate Functions host keys per app (per-app host storage or Key Vault secret storage) instead of the shared `azure-webjobs-secrets` container.
  evidence: Every app identity holds Blob Data Owner on the shared host containers, so a compromised app could read or overwrite another app's master key. Accepted for the PoC overnight.
- source_plan: `_bmad-output/implementation-artifacts/plan-1-3-python-functions-api-skeleton.md`
  summary: Update the spine AD-17 runtime-role table with Storage Blob Data Owner on `azure-webjobs-hosts`/`azure-webjobs-secrets` for every app, and per-secret Key Vault roles.
  evidence: Implemented in `infra/modules/env-app` as a platform requirement; the spine still lists only the original roles.
- source_plan: `_bmad-output/implementation-artifacts/plan-1-3-python-functions-api-skeleton.md`
  summary: Share one manifest of required app settings between `infra/modules/env-app` and the pydantic settings classes, and test both against it.
  evidence: Both sides hard-code their own key lists today; a drift would only show at start-up in Azure.
