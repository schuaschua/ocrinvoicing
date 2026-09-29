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
  summary: Decide the upload size limit for phone photos (many modern phone JPEGs exceed 4 MB; originals can't be re-encoded without losing EXIF).
  evidence: The 4 MB limit follows DI F0; moving to S0 or a different ingest path changes it. Product decision for Dj.
- source_plan: `_bmad-output/implementation-artifacts/plan-1-9-on-device-photo-quality-check-with-send-anyway.md`
  summary: Calibrate the blur, darkness and edge cut-off thresholds on real supplier photos (device and server together), including invoices on busy backgrounds.
  evidence: All values are `[ASSUMPTION]`; the border-density rule likely flags well-framed pages on textured surfaces.
- source_plan: `_bmad-output/implementation-artifacts/plan-1-9-on-device-photo-quality-check-with-send-anyway.md`
  summary: Decide whether `device_check` needs a third value (e.g. `skipped`) so the server can tell "never checked" from "passed".
  evidence: The page records `passed` when it can't decode or times out; AD-5 defines only passed/overridden.
- source_plan: `_bmad-output/implementation-artifacts/plan-1-9-on-device-photo-quality-check-with-send-anyway.md`
  summary: Update spine AD-6/CAP-3 for the device-only edge cut-off check, the 1024 px analysis copy and the `X-Device-Check` header.
  evidence: Implemented in Story 1.9; the spine describes blur and darkness only.
- source_plan: `_bmad-output/implementation-artifacts/plan-2-1-server-quality-check-creates-the-invoice-record.md`
  summary: Assert the dev/prod app stacks' database wiring (`POSTGRES_HOST/DATABASE/USER`) at root level via an app-settings output.
  evidence: Only the module test checks the mapping.
- source_plan: `_bmad-output/implementation-artifacts/plan-2-2-the-pipeline-never-loses-an-invoice.md`
  summary: Confirm in Azure that OpenTelemetry custom metrics appear under the `azure.applicationinsights` metric namespace with the `queue` dimension, and that both alert rules fire (one test poison message, one stuck invoice in Dev).
  evidence: Unverified (medium): verified offline only; the namespace is marked `[ASSUMPTION]` in `infra/modules/env-app/main.tf` and the rules use `skip_metric_validation`. The steps are the "Pipeline check" in `infra/bootstrap/README.md`.
- source_plan: `_bmad-output/implementation-artifacts/plan-1-1-private-key-vault.md`
  summary: Teach the stateful fake `az` to hold role assignments at several scopes and apply the `--query` scope filter, then test that `remove_role_assignment` and `ensure_role_assignment` touch only the exact scope.
  evidence: The fake echoes one id built from `--scope` and ignores the filter, so a dropped or loosened filter would pass every test (review V2, B8; the casing concern is unverified and would be settled by a live `az role assignment list`).
- source_plan: `_bmad-output/implementation-artifacts/plan-1-1-private-key-vault.md`
  summary: Move the `rg-22` paragraph in `infra/bootstrap/README.md` below the names table, so the App registrations, budget and action group rows render as table rows.
  evidence: Pre-existing at `ef927f0`: the paragraph sits between table rows (review B12).
