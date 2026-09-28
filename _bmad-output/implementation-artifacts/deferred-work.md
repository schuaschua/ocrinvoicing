- source_plan: `_bmad-output/implementation-artifacts/plan-1-1-repository-and-terraform-foundation.md`
  summary: Decide whether the env deploy identity (Key Vault Secrets Officer) and Dj's load-script user (Secrets User on the vault) should be able to read `pgp-private-key`.
  evidence: AD-17 grants both roles vault-wide; only `staff-api` needs the private key (AD-11). Raise with Dj alongside the open bank-crypto questions before 1.6/2.3.
- source_plan: `_bmad-output/implementation-artifacts/plan-1-1-repository-and-terraform-foundation.md`
  summary: Add diagnostic settings for PostgreSQL, DI and ACS (Key Vault AuditEvent was done in Story 1.5).
  evidence: azure.md rule 15. They live in `shared`, which has no workspace (rule 14: one per environment); Story 1.5 kept them deferred rather than adding a third workspace (plan-1-5 Design Notes). Revisit if Dj wants a shared workspace or to send them to Prod's.
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
- source_plan: `_bmad-output/implementation-artifacts/plan-1-8-supplier-sends-a-photo-or-pdf-and-gets-a-reference.md`
  summary: Sweeper (Story 2.2) reconciles `uploadkeys` rows older than 1 h whose blob exists but no invoice row, and re-enqueues them; it also deletes rows older than 24 h.
  evidence: If the blob write succeeds but the enqueue fails and the supplier never retries, the original is never processed; the invoice-row sweep can't see it because the row is created later by the quality stage.
- source_plan: `_bmad-output/implementation-artifacts/plan-1-8-supplier-sends-a-photo-or-pdf-and-gets-a-reference.md`
  summary: Decide the upload size limit for phone photos (many modern phone JPEGs exceed 4 MB; originals can't be re-encoded without losing EXIF).
  evidence: The 4 MB limit follows DI F0; moving to S0 or a different ingest path changes it. Product decision for Dj.
