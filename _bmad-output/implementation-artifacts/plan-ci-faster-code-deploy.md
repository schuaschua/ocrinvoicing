---
title: 'CI: faster code deploy (parallel publish, skip unchanged apps)'
type: 'chore'
ticket: ''
created: '2026-09-30'
status: 'built'
route: 'oneshot'
route_source: 'auto'
review: 'quick'
review_source: 'auto'
lenses_ran: ['quick']
review_loop_iteration: 0
baseline_revision: '38e11d8fdac4152a64d6f5b391629a148c7e52b3'
context:
  - '{project-root}/docs/standards/coding-style.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** On `main`, "Deploy code dev" takes about 12 minutes of a roughly 15-minute build (737 s in build #24). `ci/code-deploy.sh` publishes the four Function apps one after another, each a `config-zip` with a remote build and a restart. It republishes all four even when only one app's code changed. Dj asked for a faster deploy (2026-09-30), and told me to do everything I could overnight, which I take as approval of this plan.

**Approach:**
- **Publish in parallel.** Publish the apps side by side and wait for all of them.
- **Skip unchanged apps.** An app whose package contents hash the same as its last successful deploy to that environment is not republished. The hashes are kept in `main`'s workspace (`.work/ci/code-deploy-state/<env>`), written only after the health checks pass.
- **Keep the rest.** The health checks, the published-app list in the fixed app order, and the error messages stay as they are.

</frozen-after-approval>

## Implementation Notes

Oneshot: `ci/code-deploy.sh` plus assertions in the existing `test_story_1_3_code_deploy`.

- `ci/code-deploy.sh`:
  - `package_hash` hashes every file's path and content, independent of zip timestamps.
  - Apps whose hash matches `$CI_DEPLOY_STATE_DIR/<app>.sha256` are skipped. The default location is `.work/ci/code-deploy-state/<env>`, in `main`'s kept workspace.
  - The rest publish as background jobs, each with its own log, printed after all finish.
  - Failures are reported together. The published list keeps the fixed app order.
  - Hashes are written only after the HTTP health checks pass.
- Finding while testing: every package holds the whole `invoicing` back end, so any back-end change republishes all four. The skip helps when only infra, CI, docs or one web app changes (then only that API republishes). The parallel publish is what speeds up a back-end change.
- `ci/tests/test_ci_scripts.py`: each `_deploy` run gets a fresh state folder. The existing test gains a skip check (a second run publishes nothing; a back-end change republishes all four).

## Review Triage Log

Quick lens, 9 findings: 4 patched as bugs, 2 patched as tests or docs, 2 rejected, 1 handled.

- **Patched:**
  - **Stale skips.** A skip trusted only the local hash. Now `CI_DEPLOY_ALL=1` (set by the Jenkinsfile when `dev/app` changed) republishes all, and any failed publish or health check deletes every record.
  - **Parallel az profile.** The parallel `az` jobs shared one profile. Each job now gets its own copy of `AZURE_CONFIG_DIR`, deleted afterwards because it holds tokens.
  - **Name lookups.** A failed lookup could orphan running publishes. All names are now looked up before the first job starts.
  - **Messages.** They are back to "publishing … failed; already published: …", and the lists print "none" when empty.
  - **Tests.** They cover `CI_DEPLOY_ALL`, the failed publish (`FAKE_AZ_FAIL_NAME`) and the records deleted on failure, and the docstring is updated.
- **Rejected (low):**
  - Publish output appears only after all jobs finish. It is still printed, and the stage rarely aborts mid-publish.
  - No test proves the publishes run in parallel. Timing-based tests would be flaky.
- **Handled:** no Jira key. The PR is titled OCR-3 (Story 1.2 CI/CD).
