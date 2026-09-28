# Bond

## Basics
- **Name:** Dj
- **Call them:** Dj
- **Language:** English

## Money
- **Reporting currency:** USD (the kit's default). Every estimate and the rate card use it.
- **Azure pricing region:** southeastasia (spine AD-1)
- **Cloud price basis:** Azure retail list prices (pay-as-you-go) unless Dj gives a discount or reservation to apply, with its source.
- **Actual cloud spend:** Dj (2026-09-28): "grab the Azure cost mgmt on your own". Subscription Babaloo (9a3aef0a-...), az CLI logged in. Solution not deployed yet; Cost Management query hit 429 twice on 2026-09-28. Subscription also holds unrelated lab RGs, so filter on babaloo-sea-lng-* RGs.
- **Horizon:** Not yet discovered (default 5 years).

## Workspace
- **Token ledger:** the org config's `token_usage_folder` (default `docs/costing/token_usage/`, gitignored).
- **Cost estimates:** the org config's `cost_estimates_folder` (default `docs/costing/`): `<name>.estimate.json` (the model) and `<name>.xlsx` (the workbook). Gitignore choice not yet discovered.
- **Jira project key:** OCR

## BMad Artifacts
Ground truth for what gets built, read-only to me. Found 2026-09-28: SPEC `_bmad-output/specs/spec-ocr-invoice-automation/SPEC.md`, spine `_bmad-output/planning-artifacts/architecture/architecture-ocrinvoicing-2026-09-28/ARCHITECTURE-SPINE.md`, `_bmad-output/planning-artifacts/epics.md`, UX in `ux-designs/`. Not yet confirmed by Dj.
- Spec / PRD: `_bmad-output/specs/` and `_bmad-output/planning-artifacts/`
- Architecture spine: `_bmad-output/planning-artifacts/architecture/<name>/ARCHITECTURE-SPINE.md`
- Epics and stories, sprint status: `_bmad-output/planning-artifacts/`, `_bmad-output/implementation-artifacts/`

## Things They've Asked Me to Remember
None yet.

## Things to Avoid
Long question lists; Dj answers in terse shorthand (per Da Vinci).
