---
title: 'Jenkins dev and prod folders, a manual Prod deploy, and a tag sweep'
type: 'feature'
ticket: ''
created: '2026-10-02'
status: 'built'
baseline_revision: 'e0450b7dbd71b4ddbc84fea4a90a0f6126c32834'
route: 'full'
route_source: 'auto'
review: 'thorough'
review_source: 'auto'
lenses_ran: ['blind-hunter', 'edge-case-hunter', 'verification-gap', 'intent-alignment']
review_loop_iteration: 0
context:
  - '{project-root}/docs/standards/terraform.md'
  - '{project-root}/docs/standards/azure.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Prod has no way to deploy. Jenkins has one flat multibranch job, and the CI VM carries only the shared and Dev deploy identities. Azure also creates two App Insights resources per environment (the "Application Insights Smart Detection" action group and the "Failure Anomalies – <appi>" alert rule) without the `application`/`environment` tags.

**Approach:** Put the Jenkins jobs in a folder `ocrinvoicing` with `dev/` and `prod/` subfolders. Add a prod job that Dj starts by hand. It deploys only the `main` commit that dev last deployed, gives Dj an approval step before each Prod Terraform apply, and runs the same steps as dev. Attach the Prod deploy identity (`id-23`) to the VM. After each deploy, a tag sweep copies any resource group tags a resource is missing onto it. Prod keeps sharing PostgreSQL and Document Intelligence with Dev (the terraform.md rule 3 exception is unchanged). Dj approved this on 2026-10-02: Prod is started by hand.

**Decision (Dj, 2026-10-02):** attach Prod's deploy identity to the CI VM and extend the azure.md rule-31 exceptions to Prod. Any process on the VM can get its token through the metadata endpoint (IMDS), so the prod-only guard is enforced in our code, not by Azure. Accepted because only Dj and Claude push. Close before anyone else gets push access or before real data arrives. The plan stays whole: the tag sweep is not split off.

## Boundaries & Constraints

**Always:**
- Jenkins tree: `ocrinvoicing/dev/ocrinvoicing` (multibranch, same behaviour as today), `ocrinvoicing/dev/weekly-scan` (same cron) and `ocrinvoicing/prod/deploy` (pipeline from SCM on `*/main`, `ci/jenkins/Jenkinsfile.prod`, no triggers).
- Prod order: verify the commit → plan prod/foundation → Dj approves (only if it has changes) → apply → migrate prod → plan prod/app → Dj approves (only if it has changes) → apply → deploy prod code → tag sweep prod. Each approval is an `input` with `submitter 'dj'`, a 24 h timeout, and no agent held while it waits. A failed step stops the chain.
- The prod job deploys only if main HEAD equals the last commit the dev chain finished deploying successfully. That commit is recorded at `$JENKINS_HOME/deploy-state/dev-commit` at the end of a successful main build. Every later prod stage checks that the workspace is still on that commit.
- The dev `Jenkinsfile` keeps refusing the `prod` owner and never names Prod. Only `Jenkinsfile.prod` signs in as `prod`, and it signs in as nothing else.
- The tag sweep only adds the resource group tag keys a resource is missing. It never overwrites an existing value and never removes a tag. It runs as the stack owner's deploy identity, for shared and dev at the end of the dev chain and for prod at the end of the prod job.
- Test cap of 200: extend the existing merged tests and add no new test functions.

**Never:** No automatic trigger on the prod job. No changes to Terraform modules or stacks. No `-target`/`import`. Never touch `rg-tfstate-sea` (used by another project) or rg-22/rg-23 (the bootstrap retags those). Never run prod migrations or code deploys before their stack's apply.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected | Error handling |
|---|---|---|---|
| Prod run, main already deployed to dev | main HEAD = dev-commit | Full chain; approvals only for stacks that have changes | — |
| main ahead of dev | HEAD ≠ dev-commit, or no marker | Fails before any sign-in | Message names both commits |
| Approval rejected or times out | input aborted | Chain stops; plans cleaned up | — |
| Untagged Azure-created resource | resource missing `application` | `az tag update --operation merge` with only the missing keys | A failed az call fails the step |
| Fully tagged resource group | every resource has every key | No `tag update` calls | — |
| Old flat jobs on jenkins_home | `jobs/ocrinvoicing` is a multibranch project | ci-vm-remote.sh removes the old `ocrinvoicing` and `ocrinvoicing-weekly-scan` job folders before Jenkins starts | Build history of the old jobs is lost (accepted) |

</frozen-after-approval>

## Code Map

- `Jenkinsfile` -- dev chain. Reuse its helpers `runStep`, `asDeployIdentity`, `planStack`, `applyStack` and `CLEANUP`. After "Deploy code dev", add a stage "Tag sweep" (shared, then dev) and a record of dev-commit. Update the header comment.
- `ci/jenkins/Jenkinsfile.prod` (new) -- prod chain. Copy the helpers with the owner fixed to `prod`, plus `options { skipDefaultCheckout(); disableConcurrentBuilds() }`. The first stage runs `checkout scm` and the marker check, and stores `DEPLOY_COMMIT`.
- `ci/jenkins/casc.yaml` -- add folders, move the jobs into them, add `prod/deploy`, add env `DEPLOY_CLIENT_ID_PROD`, and update the comment about Prod.
- `ci/tag-sweep.sh` (new) -- `ci/tag-sweep.sh <shared|dev|prod>`. Gets the resource group from `terraform -chdir=infra/<env>/foundation output -raw resource_group_name` (after init, using `stack_dir`/`export_arm_context` from `ci/lib.sh`), reads the group's tags, lists the resources, and merges only the missing keys.
- `infra/bootstrap/ci-vm.sh` -- `ATTACHED_OWNERS=(shared dev prod)`. Drop the block that removed the Prod identity. Pass a 6th arg `client_id_prod`. Update the header.
- `infra/bootstrap/ci-vm-remote.sh` -- take 6 args and write `DEPLOY_CLIENT_ID_PROD`. Remove the old flat job folders from the `jenkins_home` volume when `jobs/ocrinvoicing/config.xml` is a multibranch project (`docker run --rm -v jenkins_home:/h busybox`, or exec before the restart).
- `ci/tests/test_jenkins.py` -- extend `_jenkinsfile_guards`: the folder/job layout in casc, the prod stage order, two inputs (Dj only) in the prod file, prod never in the dev `Jenkinsfile` code, dev-commit written and checked, and tag-sweep stages.
- `ci/tests/test_ci_scripts.py` + `ci/tests/fake-bin/{az,terraform}` -- add a `_tag_sweep` part to `test_story_1_2_ci_scripts`. Fakes: terraform `output -raw` prints `$FAKE_TF_OUTPUT`; az answers `group show`/`resource list` from `$FAKE_AZ_SWEEP` JSON and logs `tag update`.
- `infra/scripts/tests/test_bootstrap_scripts.py:361`, `test_bootstrap_matrix.py:143-161` -- now 3 assigns including id-23, no remove, 6 remote args.
- Docs: Story 1.2 in `epics.md` (AC lines 377–379), spine AD-17 lines 429 and 583 (diagram), the `infra/bootstrap/README.md` lines 45 and 67 and step 1c, and the `azure.md` exception rows for rule 31 (lines 130–131).

## Tasks & Acceptance

**Execution:**
- [x] `ci/tag-sweep.sh` + fakes + `_tag_sweep` test part -- the sweep, as specified above.
- [x] `ci/jenkins/Jenkinsfile.prod` -- the prod chain.
- [x] `Jenkinsfile` -- Tag sweep stage and the dev-commit record.
- [x] `ci/jenkins/casc.yaml` -- folders, jobs, prod env.
- [x] `infra/bootstrap/ci-vm.sh`, `ci-vm-remote.sh` -- attach Prod, add the 6th arg, migrate the old jobs.
- [x] Tests in `ci/tests/test_jenkins.py` and `infra/scripts/tests/*` -- updated as in the Code Map.
- [x] Docs as in the Code Map -- also record the revised rule-31 exceptions (Decision above).

**Acceptance Criteria:**
- Given the casc, when Jenkins starts, then the tree is exactly the three jobs under `ocrinvoicing/dev` and `ocrinvoicing/prod`.
- Given `ci-vm.sh --dry-run`, then id-21, id-22 and id-23 are attached and the remote step gets three client ids.
- Given the whole repo, then the test count is still ≤ 200 and `ci/checks.sh lint` and `test` pass.

## Implementation Notes

- The dev chain records the commit in its own stage, "Record dev commit", before "Tag sweep", so a tagging failure never blocks Prod (review fix). Record and verify live in `ci/deploy-state.sh` (atomic write via `.new` + `mv`; test seam `CI_DEPLOY_COMMIT_DIR`, not `CI_DEPLOY_STATE_DIR`, which `code-deploy.sh` already uses), tested as `_deploy_state` in `test_story_1_2_ci_scripts`.
- `ci/tag-sweep.sh` compares tag keys lowercased (Azure keys are case-insensitive). The old-job migration also removes the old jobs' workspaces.
- `ci/tag-sweep.sh` also refuses a foundation output that is not the owner's own group (`rg_name` from `infra/bootstrap/lib.sh`), so it can never sweep `rg-tfstate-sea`, rg-22 or rg-23.
- `ci-vm-remote.sh` removes the old flat jobs with a throwaway container of the freshly built Jenkins image (`--user root --entrypoint sh`), not busybox, so nothing extra is pulled. It also looks for running builds' `@tmp/durable-*` folders up to 5 levels deep, since jobs in folders keep their workspaces deeper than `workspace/*`.
- Root `README.md` lines on Prod were stale too and were updated with the other docs.

## Plan Change Log

## Review Triage Log

Pass 1 (2026-10-02). Lenses ran one at a time: Dj's rule against running subagents in parallel. Counts: high 0, medium 3, low 9, false 9, maybe-false 0.

| # | Lens | Finding | Verdict | Route | Evidence / action |
|---|---|---|---|---|---|
| 1 | blind, edge | A tag-sweep failure blocks the dev-commit record, so Prod can't deploy what Dev ran | medium | patch | `Record dev commit` runs after `Tag sweep`; a cosmetic az failure would block Prod. Move the record before the sweep |
| 2 | verif-gap | The commit gate (record/verify/onDeployCommit) is only text-tested | medium | patch | Logic is inline Groovy. Move the record and the compare into `ci/deploy-state.sh` with a state-dir seam, called from both Jenkinsfiles and run in the merged test |
| 3 | blind, edge | Old workspaces stay on the disk after the old jobs are removed | medium | patch | About 5 GB per main workspace on a 61 GB disk that filled once (2026-09-30). Remove `workspace/ocrinvoicing_*` and `ocrinvoicing-weekly-scan*` in the same guarded block |
| 4 | edge | Tag-key presence check is case-sensitive, while the merge is not | low | patch | Direct correction: compare keys lowercased |
| 5 | blind | The dev main chain and the Prod job can run at once (shared plugin cache, memory) | low | patch | Two executors already allow concurrent terraform. Add a README note: don't start Prod while a main build runs |
| 6 | blind | The dev-commit file can be written by any build on the VM; not stated in the risk notes | low | patch | It's weaker than the accepted Prod-token exposure, but still name it in the README Identities paragraph |
| 7 | blind | "No backup" README text is stale; first run fails with "none recorded" until main deploys | low | patch | Doc line |
| 8 | intent | README detail still says main runs "the checks, then" | low | patch | Stale since 2026-09-30 (main skips checks); correct the line |
| 9 | blind | casc test slices `prod_job` to the end of the file | low | patch | Bound the slice to the job block |
| 10 | verif-gap | ci-vm-remote.sh job migration and running-build guard are never executed | low | defer | Needs root and a real Docker volume. Text-order test added; README note to check the restart log |
| 11 | blind, edge, intent | Tag sweep fights Terraform-managed tags | false | reject | Checked live 2026-10-02: every resource in rg-01 and rg-21 already has every group key with the same value. `check_tags.py` gates all Terraform plans on the full tag set |
| 12 | blind | Prod migrations and code deploy have no approval | false | reject | Intent: approval for each Prod Terraform apply; Dj starting the job by hand covers migrations and code |
| 13 | blind | A rejected prod/app approval leaves the DB migrated with old code | false | reject | Migrations are expand-only (coding-style rule 29); the same order as AD-17 for Dev; re-run the job |
| 14 | blind, edge | Lightweight script vs checkout may be on different commits | low | reject | A window of seconds, only if a merge lands right then; the fix adds pinning complexity |
| 15 | blind | tfvars client ids are out of scope | false | reject | Dj ran app-registrations for this Prod setup in this session; Prod can't deploy without them |
| 16 | blind | Tag-sweep tests cover only dev; a group with no tags exits quietly | low | reject | `rg_name` is shared lib code covered by the bootstrap tests; groups always carry tags (state-backend.sh) |
| 17 | blind, intent | Jira sync not shown | false | reject | OCR-3 updated by the implementer on 2026-10-02 |
| 18 | blind | No alert when a Prod run fails | low | reject | Dj starts and watches each run |
| 19 | edge | A tab or newline in a tag value breaks the parse | false | reject | Tag values are fixed P-17 values (`naming` module, bootstrap) with no whitespace |
| 20 | edge | The weekly job stays if only it remains | low | reject | Both jobs are created and removed together; the partial state isn't reachable |
| 21 | intent | Sweep scope F1 vs F2 (all resources and keys) | false | reject | Plan Boundaries: "only adds the resource group tag keys a resource is missing"; F1 is the plan's reading |
| 22 | intent | Gate B1 (refuse) vs B2 (pin) | false | reject | Plan Boundaries pick B1: "deploys only if main HEAD equals the last commit" |

## Design Notes

Why the marker file: the controller is the only node (`numExecutors: 2`, no agents), so both jobs see `$JENKINS_HOME`. A file avoids cross-job API calls, which would need sandbox approval. Why `skipDefaultCheckout`: a non-multibranch job's `checkout scm` would fetch whatever main is at that moment. The prod job checks out once and reuses its workspace, the same way the dev chain already shares saved plans between stages.

## Verification

**Commands:**
- `uv run --project backend pytest ci/tests infra/scripts/tests -q` -- expected: all pass.
- `ci/checks.sh lint` -- expected: pass (shellcheck covers the new script).
- `python3 -c` count of collected tests (`pytest --collect-only -q`) plus Vitest/Playwright -- expected: total ≤ 200.
