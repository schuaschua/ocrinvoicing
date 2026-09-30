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
- source_plan: `_bmad-output/implementation-artifacts/plan-1-6-load-suppliers-and-issue-upload-links.md`
  summary: On the first Dev deploy, run the supplier load for real (Key Vault RBAC on the two secrets, Entra login, admin-created pgcrypto, `DJ_USER_UPN` pipeline variable, Table SDK scan and merge) and open a printed link on the deployed supplier-api.
  evidence: Unverified (medium): every Azure-facing path of Story 1.6 was tested offline only, against local PostgreSQL and in-process fakes (review I).
- source_plan: `_bmad-output/implementation-artifacts/plan-1-2-ci-cd-on-jenkins.md`
  summary: Test the Jenkins pipeline logic and the VM-side setup by running them (Jenkins Pipeline Unit or jenkinsfile-runner; a ci-vm-remote.sh test with fake docker/install/getent), not only as text.
  evidence: Review V3; stage gating, the approval and the secret-file modes are checked only by regex today.
- source_plan: `_bmad-output/implementation-artifacts/plan-1-2-ci-cd-on-jenkins.md`
  summary: Decide and build how Prod deploys (a second VM or identity policy), then add the Prod stages and restore the Prod criterion.
  evidence: Review B9; the Jenkins pipeline has no Prod path by Dj's decision on 2026-09-29.
- source_plan: `_bmad-output/implementation-artifacts/plan-1-2-ci-cd-on-jenkins.md`
  summary: Keep the CI VM patched: a cadence for Jenkins LTS, plugin and tool pin updates; email on weekly-scan failure; JUnit reports in Jenkins; jenkins_home backup.
  evidence: Reviews B10, B11, B14, E11.
- source_plan: `_bmad-output/implementation-artifacts/plan-1-2-ci-cd-on-jenkins.md`
  summary: Harden branch builds so they can't reach the metadata endpoint (a separate Docker network with IMDS blocked; deploy only from main's job) before anyone else gets push access or before Prod.
  evidence: Reviews B1, B2, E9; accepted for the PoC by Dj on 2026-09-30.
- source_plan: `_bmad-output/implementation-artifacts/plan-2-3-invoice-fields-extracted-by-document-intelligence.md`
  summary: Story 2.5's migration must grant the pipeline login UPDATE (po_line_id, material_id) on intake.invoice_line, the only columns validate fills.
  evidence: AD-18 says validate fills these columns; migration 0005 gives the pipeline SELECT, INSERT only on invoice_line (append-only for DI rows).
- source_plan: `_bmad-output/implementation-artifacts/plan-2-5-validation-confidence-po-match-printed-supplier.md`
  summary: Story 2.10's admin Correct must copy `po_line_id` and `material_id` onto a corrected line row, or other invoices' quantities drop out of the PO expected amount.
  evidence: `_invoiced_elsewhere` counts only current lines with a `po_line_id`; only validate writes it, on the row it matched.
- source_plan: `_bmad-output/implementation-artifacts/plan-2-5-validation-confidence-po-match-printed-supplier.md`
  summary: Story 2.6 should prove the per-supplier advisory lock (hashtextextended(supplier_id::text, 0)) with a concurrent test, covering both the PO quantities (2.5) and the duplicate race (2.6).
  evidence: deleting `lock_supplier(...)` in adapters/postgres/validation.py passes every 2.5 test.
- source_plan: `_bmad-output/implementation-artifacts/plan-2-6-validation-duplicates-dates-bank-changes.md`
  summary: Duplicate check misses a re-photographed copy validated while the earlier copy is still before extraction (no fingerprint yet); consider re-checking or delaying.
  evidence: `_earlier` reads current values, which don't exist before extraction; phash (stored at quality) still catches a resent file.
- source_plan: `_bmad-output/implementation-artifacts/plan-2-6-validation-duplicates-dates-bank-changes.md`
  summary: The earlier-invoice read for duplicates loads all of a supplier's history under the advisory lock; replace with an indexed fingerprint/phash lookup before real volumes.
  evidence: adapters/postgres/validation.py `_earlier` has no window.
- source_plan: `_bmad-output/implementation-artifacts/plan-2-6-validation-duplicates-dates-bank-changes.md`
  summary: A clearer resend of an image-quality-routed original is flagged DUPLICATE; decide the admin UX in 2.9/2.10.
  evidence: the original stays non-rejected in the admin queue with its phash.
- source_plan: `_bmad-output/implementation-artifacts/plan-2-8-admin-queue-list.md`
  summary: Make `platform_auth_trusted` a required argument of `staff_endpoint` (adapters/principal.py) and `me_endpoint` (apps/staff_api/me.py), and test the registered `me` handler with auth untrusted, as 2.8 did for the queue.
  evidence: both default to True, so a wiring slip trusts a forged X-MS-CLIENT-PRINCIPAL when built-in auth is off; pre-existing (Story 2.7), found in the 2.8 review.
- source_plan: `_bmad-output/implementation-artifacts/plan-2-9-admin-item-crop-fields-bank-change.md`
  summary: PDF invoices have no in-app viewer or flag boxes (opened by link); decide on a PDF renderer (e.g. pdf.js with a CSP change) and test Chrome's viewer under the app's CSP.
  evidence: no PDF renderer in web/staff; CSP `default-src 'self'` blocks blob/worker use; page sizes for PDFs are now stored (inches), so boxes are possible once rendered.
- source_plan: `_bmad-output/implementation-artifacts/plan-2-9-admin-item-crop-fields-bank-change.md`
  summary: Invoices extracted before migration 0008 have no page sizes and show no flag boxes; a Re-extract (2.10) restores them.
  evidence: extraction_page is filled only by runs after this story.
- source_plan: `_bmad-output/implementation-artifacts/plan-4-1-goods-in-scans-paper-invoice.md`
  summary: Update AD-10 in the architecture spine to list PurchasingPort's two new methods, list_deliveries and search_deliveries.
  evidence: AD-10 lists five methods; Story 4.1 added two (ports/purchasing.py).
- source_plan: `_bmad-output/implementation-artifacts/plan-4-1-goods-in-scans-paper-invoice.md`
  summary: Decide whether a goods-in scan should record which staff member scanned it (key row, blob metadata or log).
  evidence: Unverified, medium if required. The principal is not stored anywhere; settle it by checking the spine's audit requirements for staff-originated invoices.
