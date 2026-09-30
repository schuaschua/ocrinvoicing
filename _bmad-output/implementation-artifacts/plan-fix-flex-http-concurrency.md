---
title: 'Fix: Flex HTTP apps take one request per instance, so page loads start several cold instances'
type: 'bugfix'
ticket: ''
created: '2026-09-30'
status: 'built'
route: 'oneshot'
route_source: 'auto'
review: 'quick'
review_source: 'auto'
lenses_ran: ['quick']
review_loop_iteration: 0
baseline_revision: '761c4987a383f9d92c8f6d53512a8483ccd3ee0d'
context:
  - '{project-root}/docs/standards/terraform.md'
  - '{project-root}/docs/standards/azure.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `supplier-api` and `staff-api` set no HTTP per-instance concurrency, and for Python on Flex Consumption the default is 1 request per instance. Every parallel request of a page load (the HTML, JS, CSS and `/api/link`) needs its own instance, and each one is cold, so pages take 6–10 s (walkthrough-dev-2026-09-30.md, follow-up 1). Dj decided not to add always-ready instances.

**Approach:** Set `functionAppConfig.scaleAndConcurrency.triggers.http.perInstanceConcurrency` in `infra/modules/env-app`: **8 on `supplier-api`**, which uses no PostgreSQL, only table, blob and queue storage (AD-6), and **4 on `staff-api`**, matching its PostgreSQL pool (`STAFF_POOL_SIZE = 4`), so a busy instance never waits for a connection. One instance then serves most of a page load. Record the values in the AD-17 compute ceilings.

**Decision (Dj, 2026-09-30, after review):** supplier-api 8 and staff-api 4. The first draft said "8 for both, below the pool of 9", but 9 is the pipeline's pool, staff-api's is 4, and supplier-api has no pool. Raising `STAFF_POOL_SIZE` to 8 was rejected: up to 10 instances x 8 connections on the shared B1ms server.

</frozen-after-approval>

## Implementation Notes

Oneshot: about 30 lines of Terraform, assertions added to the existing `env_app` test run, and one sentence in the spine.

- AVM `avm-res-web-site` 0.23.0 is the latest release and has no input for `scaleAndConcurrency.triggers`.
- The value is set by an `azapi_resource_action` PATCH on each site, as terraform.md rule 2 prescribes for patching a resource that someone else owns. A PATCH sends only this field. An `azapi_update_resource` would GET and PUT the whole site, which re-sends `siteConfig` fields that FC1 rejects (ARM 51021).
- The module's `ignore_body_changes.web_sites` lists `properties.functionAppConfig.scaleAndConcurrency.triggers`, so the module's own PUTs keep the setting.

## Review Triage Log

Quick lens, 3 findings: 2 medium, 1 false.

- Medium (fixed, with Dj's decision): the "below the pool of 9" premise was wrong. 9 is the pipeline's pool, staff-api's is 4 (`STAFF_POOL_SIZE`), and supplier-api has no pool. Dj chose supplier-api 8 and staff-api 4, and the Intent, code, test and spine are corrected.
- Medium (patched): `azapi_update_resource` on the site would GET and PUT the whole site, re-sending `siteConfig` fields that FC1 rejects (51021), and the rule-2 citation was about a PATCH. Now `azapi_resource_action` with method PATCH, carrying this field only.
- False: "walkthrough-dev-2026-09-30.md is not in the project". It is committed in PR #4 (branch `chore/dev-walkthrough-2026-09-30`) and lands on `main` with it.

## Plan Change Log

- **2026-09-30, Dev build #20 failed.** The PATCH carried only `scaleAndConcurrency.triggers`, and Azure answered `400 Site.FunctionAppConfig.Runtime is invalid. Runtime name and version must be provided.` (51021).
  - Flex replaces `functionAppConfig` as a whole. Nothing was changed on either site.
  - The PATCH now carries the whole `functionAppConfig`: the deployment storage, the runtime, `siteUpdateStrategy` and the scale limits, with the module's values plus the triggers. The values were checked against both sites' live config.
  - The env-app test asserts those fields.
  - KEEP: supplier-api 8, staff-api 4, and the module's `ignore_body_changes` for the triggers path.

## Verification

**Commands:**
- `ci/checks.sh terraform` -- expected: fmt, validate and `terraform test` pass for `infra/modules/env-app` and both env roots.
- `ci/checks.sh all` -- expected: all checks pass with at most 200 test cases.

**Manual checks (after the Dev deploy):**
- `az rest` GET shows `triggers.http.perInstanceConcurrency` = 8 on `babaloo-sea-lng-func-01` and 4 on `-02`. The rest of the site is unchanged: app settings, identity, `functionAppConfig` runtime and scale.
- After 10 minutes idle, the supplier link loads in one cold start (about 5–8 s), then fast.
