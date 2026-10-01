---
title: 'Story 5.2: Staff alert emails'
type: 'feature'
ticket: '5-2-staff-alert-emails'
created: '2026-10-01'
status: 'built'
route: 'full'
route_source: 'auto'
review: 'thorough'
review_source: 'auto'
lenses_ran: ['blind-hunter', 'edge-case-hunter', 'verification-gap', 'intent-alignment']
review_loop_iteration: 0
baseline_revision: '94ac92c584b3f2e799c7476844972c507ec7242c'
context:
  - '{project-root}/docs/standards/coding-style.md'
  - '{project-root}/docs/standards/security.md'
  - '{project-root}/docs/standards/terraform.md'
  - '{project-root}/docs/standards/azure.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Price-rise and watchlist alerts (Stories 5.3 and 5.4) sit in `analytics.alert`, so staff only learn of them by checking dashboards (AD-16).

**Approach:**
- `shared/foundation` gains ACS Email with Dj's custom domain.
- `<env>/app` gives `pipeline` the custom `ACS Email Sender` role.
- The analytics refresh sends each un-emailed, non-backfilled alert through one `EmailPort` adapter, throttled per environment. It addresses the per-role recipients and includes a deep link, then sets `emailed_at`.
- Everything stays switched off until Dj sets his domain (`email_custom_domain`) and the app's sender settings. Merging this story changes nothing in Azure, and no email goes out, until then.

## Boundaries & Constraints

**Always:**
- **Terraform, `shared/foundation`.** Each resource has `count` gated on `var.email_custom_domain != ""`; the default `""` means nothing is created:
  - a Communication Services resource with local auth/access keys off, data location "Asia Pacific";
  - an Email Communication Service;
  - a user-managed custom domain (`email_custom_domain`).
  - The domain link (association) has a separate gate: `var.email_domain_link_enabled` (default `false`). Dj turns it on only after the DNS records are verified.
  - Outputs: the ACS endpoint, the domain's verification DNS records (for Dj to add by hand), and the sender address `alerts@<domain>`. Each output is null when the feature is off.
  - Naming comes from `modules/naming`. Tags and the provider follow `terraform.md`.
- **Terraform, `<env>/app`.** Assign the custom role `ACS Email Sender` to the `pipeline` identity on the ACS resource, only when shared has created ACS (read through the existing shared-state wiring).
  - Pass these as app settings: `EMAIL_ACS_ENDPOINT`, `EMAIL_SENDER_ADDRESS`, `STAFF_APP_BASE_URL` (the staff app's own URL, from `<env>/app`), and `ALERT_RECIPIENTS_FINANCE`, `ALERT_RECIPIENTS_PROCUREMENT`, `ALERT_RECIPIENTS_MANAGEMENT`.
  - The recipient values come from env tfvars variables and default to empty.
  - Add assertions to the existing `terraform test` runs; no new run blocks unless the cap allows.
- **Bootstrap.**
  - `infra/bootstrap/rbac-step3.sh` gets its ACS part: RBAC Administrator on the ACS resource for each environment's deploy identity, conditioned to assigning only `ACS Email Sender`. It is skipped with a message when ACS doesn't exist yet.
  - The bootstrap README gets the email-domain DNS step: set `email_custom_domain`, apply, add the output records at the registrar, wait for verification, set `email_domain_link_enabled = true`, apply, set the app settings.
- **Python.**
  - `ports/email.py` (`EmailPort.send(to, subject, text, html)`) and `adapters/email.py`, the only sender (AD-16). The adapter uses the ACS SDK `azure-communication-email`, pinned exactly in the lock file, with the managed identity.
  - **Throttle:** in-process, with no shared state.
    - Dev: at most 5 a minute and 20 an hour.
    - Prod: at most 25 a minute and 80 an hour.
    - Chosen by `APP_ENVIRONMENT`; `local` uses Dev's limits.
    - Time comes from an injected clock, so tests never sleep.
    - When the limit is reached, the dispatch stops for this run and the remaining alerts wait for the next one.
  - **Dispatch:** a new step in the analytics refresh job, after the summaries.
    - It picks alerts with `emailed_at IS NULL`, oldest first, and sends one email per alert to the union of its kind's recipient roles (bcc, sender as to):
      - `price_rise` goes to finance and procurement;
      - `watchlist` goes to procurement and management.
    - After each successful send it sets `emailed_at`. The pipeline login already has UPDATE on `emailed_at` only.
    - A send failure logs `email.failed code=<type>` and leaves the alert for the next run.
    - With no recipients configured for a kind, it logs `email.no_recipients kind=…` and leaves the alert.
    - With the feature off (no endpoint or sender), it logs `email.disabled` once per run and sends nothing.
    - Failures never fail the refresh run. The whole step has its own handling, like the weekly step.
- **Content (UX-DR23, EXPERIENCE.md).**
  - Subjects:
    - "Price rise: {supplier}, {material} +{n}%"
    - "{supplier} added to the watchlist: {rule words}"
  - The body is a few plain sentences plus a deep link:
    - price rise: `{STAFF_APP_BASE_URL}/price-comparison?material_id={id}`;
    - watchlist: `{STAFF_APP_BASE_URL}/watchlist#supplier-{id}`.
  - Never include bank details, link tokens, invoice images or invoice ids; the evidence is on the page.
  - Supplier and material names come from master and `analytics.material`.
  - Content building is a pure function in `domain/alert_email.py`.
- **Settings.** Every new setting is optional and read through `PipelineSettings` (rule 12). Recipients are comma-separated email lists, validated at start-up, and the values are never logged.
- **Tests.** At most **3** new test cases. Terraform assertions go inside the existing runs.

**Never:**
- emails to suppliers (AD-6);
- sending outside `adapters/email.py`;
- shared throttle state (no table, no blob);
- turning the feature on (Dj does that with his domain);
- a real ACS call in tests;
- touching Azure from this session.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Send | 1 `price_rise`, recipients set, feature on | 1 email: subject, deep link, bcc finance+procurement; `emailed_at` set | — |
| Already emailed | `emailed_at` set (incl. backfilled) | Not sent again | — |
| Throttled | Dev, 7 pending in one minute | 5 sent and marked; 2 wait; next run sends them | — |
| Hourly cap | Dev, 20 sent this hour | No more until the hour rolls | — |
| Send fails | Adapter raises | `email.failed`; alert stays; run result unchanged | Retried next run |
| No recipients | `watchlist` with no procurement/management lists | `email.no_recipients`; alert stays | — |
| Disabled | No endpoint/sender | `email.disabled`; nothing sent | — |
| Content | Any alert | No bank digits, link tokens or invoice ids in subject or body | — |
| Terraform off | `email_custom_domain = ""` | Plan creates no ACS resources and no role assignment | — |
| Terraform on | Domain set, link off | ACS + email service + domain; no association | — |

</frozen-after-approval>

## Code Map

- **Infrastructure:**
  - `infra/shared/foundation/` (`main.tf`, `variables.tf`, `outputs.tf`, `tests/`): where the shared resources and their tests live. See `prod/foundation` for the email-related variables and outputs already grepped.
  - `infra/modules/env-app/main.tf` has the comment line 4 ("The ACS Email Sender assignment (5.2) is added later") and the `role_assignments` map pattern. App settings are wired there too.
  - `infra/dev/app`, `infra/prod/app` (tfvars, tests).
  - `infra/bootstrap/rbac-step3.sh` (the DI part is the pattern for the conditioned RBAC admin), `budget-and-roles.sh` (the custom role "ACS Email Sender"), `lib.sh` (`ACS_EMAIL_SENDER_ROLE_NAME`), `README.md`.
  - `infra/scripts/tests/test_bootstrap_scripts.py` has the fake-az tests for bootstrap scripts.
- **Python:**
  - `backend/src/invoicing/apps/pipeline/analytics_refresh.py`: the steps and their own error handling (4.3 weekly, 5.1 summaries). Add `_send_alerts`.
  - `apps/pipeline/settings.py`, `apps/common.py`: the settings patterns and validators.
  - `apps/pipeline/function_app.py`: the wiring.
  - `ports/dashboards.py` or `ports/analytics.py`: read pending alerts and mark sent, from the pipeline side.
  - `domain/analytics.py`: rule words from Story 5.4.
  - `analytics.alert` columns are in `adapters/postgres/schema.py` (5.1).
- **Dependencies:** `backend/pyproject.toml` and `uv.lock`, pinned exactly (`security.md` rule 27). Check for an existing `azure-identity` aio credential pattern in `adapters/document_intelligence.py`.
- **Tests:** the patterns are in `backend/tests/apps/test_story_4_3_reminders.py` (job step with fakes) and `test_story_5_3_*` / `test_story_5_4_*` (alerts).

## Tasks & Acceptance

**Execution:**
- [x] Terraform `shared/foundation`: gated ACS, email service, domain and link, plus outputs and test assertions.
- [x] Terraform `env-app` and `dev`/`prod` app: gated role assignment, app settings, variables and test assertions.
- [x] Bootstrap: the ACS part of `rbac-step3.sh` and the README DNS step, with an assertion in the existing bootstrap script test.
- [x] Python: `ports/email.py`, `adapters/email.py` with the throttle, `domain/alert_email.py`, the settings, the dispatch step and the wiring.
- [x] Tests (at most 3 new cases):
  - `test_story_5_2_throttle`: a pure test with the clock;
  - `test_story_5_2_dispatch`: a fake `EmailPort` against real Postgres alerts, covering send, already emailed, throttled then next run, failure, no recipients, disabled and the content rules.

**Acceptance Criteria:**
- Given the default tfvars, when `terraform plan` runs for shared and both environments, then no Communication resource and no ACS role assignment is planned.

## Implementation Notes

- **AVM first.** The Email Communication Service and its domain (and the `alerts` sender) use `Azure/avm-res-communication-emailservice/azurerm` 0.3.0 (Available in the AVM index). Communication Services has no AVM module and `azurerm_communication_service` (4.81.0) has no `disableLocalAuth` (and would keep the access keys in state), so it is an `azapi_resource` (`Microsoft.Communication/communicationServices@2025-05-01`). No provider was added; the lock files are unchanged.
- **The domain link** is the ACS resource's own `linkedDomains`, gated on `email_domain_link_enabled`, not a separate `azurerm_communication_service_email_domain_association`: an azapi PUT of the ACS resource without `linkedDomains` would drop a link another resource made, so one resource owns it (terraform.md rule 2). The `alerts` sender username is created only with the link (after DNS verification).
- **Names.** `acs` (CAF) and `ecs` (no CAF abbreviation for Email Communication Services) in `modules/naming`, shared only: `babaloo-sea-lng-acs-21`, `babaloo-sea-lng-ecs-21`; `lib.sh` mirrors `acs-21`.
- **Shared-state wiring.** `shared` outputs `communication_service_id`, `email_acs_endpoint`, `email_domain_verification_records` and `email_sender_address`; `<env>/foundation` passes the first, second and fourth through as `email` (with `try`, so an older shared state reads as off); `<env>/app` reads them from there, as it does DI.
- **Gate on the link.** `email_sender_address` is null until the domain is linked, and `<env>/app` assigns `ACS Email Sender` only when it is set. So the deploy chain that first creates ACS (shared, then dev/foundation, then dev/app, without a pause) never tries the assignment before `rbac-step3.sh` has given the deploy identity the right to; the README orders the steps that way.
- **Python.** `ports/email.py` (`EmailPort`, `EmailThrottledError`); `adapters/email.py` holds `AcsEmail` (the only sender: bcc recipients, the sender as `to`), `SendThrottle` (sliding minute and hour windows, injected clock) and `ThrottledEmail` (the two as one port). The dispatch is `apps/pipeline/alert_emails.py`, called by `AnalyticsRefresh._send_alerts` with its own error handling (`analytics_refresh.emails_failed`), after the summaries, also on the overdue-failure path. `email.disabled` also covers a missing `STAFF_APP_BASE_URL` (no deep link possible). A failed send continues with the next alert; a throttled one stops the run's dispatch (`email.throttled`). Log keys `kind` and `alert_id` were added to the allow-list.
- **Review fixes (2026-10-01).** Invalid alerts are skipped (`email.invalid`), and only kinds with recipients are read (`detail.backfilled` is excluded too). Alerts over 14 days old are marked without a send (`email.stale`). Only successful sends take a throttle slot, and 3 failures in a row stop the run. ACS's 429 stops the run. A full minute waits through an injected sleeper, up to 10 minutes per run. A failed mark stops the run (`email.mark_failed`; delivery is at least once). The adapter waits 60 s for ACS, checks for `Succeeded`, sends 49 recipients per message and keeps one client. The watchlist link is `/watchlist?supplier=<id>`, and the staff app reads it. The README gained the mailbox, role-check, propagation and switch-off notes. There are 2 more terraform runs (`email_domain_linked`, dev/app `acs_without_linked_domain`).
- **Tests.** 3 new cases (5 after the review fixes): `test_story_5_2_throttle`, `test_story_5_2_dispatch` and the terraform run `email_domain_set_link_off`; the off path and the on path for the role and settings are assertions in the existing runs (shared, both app roots, env-app module). The settings validation is a new row in the existing function-apps test. Repo total 193 of 200.

## Plan Change Log

## Review Triage Log

### Pass 1 (2026-10-01): high 2, medium 9, low 9, false/rejected 4; lenses run one at a time

| # | Lens | Finding | Verdict | Route | Evidence / action |
|---|---|---|---|---|---|
| 1 | BH, EC | One malformed alert aborts every run (content built outside the try; non-dict detail; NULL material; NaN pct) | high | patch | Per-alert `InvalidAlertError` → `email.invalid`, batch continues; tested. |
| 2 | BH, EC | Failed sends use throttle slots; an always-failing head alert blocks the rest | high | patch | Slot released on failure; 3 consecutive failures stop the run; tested. |
| 3 | BH, EC | Kinds without recipients fill the 100-alert batch | medium | patch | Query only sendable kinds; tested. |
| 4 | BH, EC | Throttle stops the run: ≤5 per run in Dev | medium | patch | Waits for the next minute (injected sleeper) up to the hour cap or 10 min; tested. |
| 5 | BH | ACS 429 treated as a plain failure | medium | patch | Mapped to throttled; run stops; tested. |
| 6 | BH, EC | Stale backlog floods at switch-on | medium | patch | Alerts over 14 days old marked without sending (`email.stale`); tested. |
| 7 | BH, EC | `mark_emailed` failure after a send aborts and re-sends | medium | patch | `email.mark_failed`, stop; at-least-once documented; tested. |
| 8 | BH, EC | No timeout or status check on the ACS poller; 50-recipient limit | medium | patch | 60 s `wait_for`, non-Succeeded raises; Bcc chunks of 49. |
| 9 | BH | `#supplier-` fragment lost across built-in-auth sign-in | medium | patch | Email links `/watchlist?supplier=<id>`; screen supports it; tested. |
| 10 | VG, IA | Settings off/on handoff and function_app wiring untested | medium | patch | conftest carries the six keys as ""; off and on asserted. |
| 11 | VG, BH | Bcc-only message shape untested (privacy) | medium | patch | Pure `acs_message`; shape asserted. |
| 12 | VG | `late` and `price_gap` wording, escaping, de-duplication untested | low | patch | All asserted in the dispatch test. |
| 13 | VG, IA | Terraform partial states (domain set but unlinked; linked) untested | low | patch | Runs `email_domain_linked` and `acs_without_linked_domain`. |
| 14 | IA | Backfilled alerts excluded only via `emailed_at` | low | patch | Explicit `backfilled` exclusion too. |
| 15 | BH, EC | README: To-address bounces, switch-off apply order, 403 on first run, role actions | low | patch | Steps 6–8 and switch-off order documented. |
| 16 | BH | Custom role may not allow a data-plane send | low | defer | Needs real Azure; README step 8 verifies before relying on it; spine open question. |
| 17 | VG | Overdue-failure path and DB_OFFLINE code with emails on untested | low | defer | Pending alerts retry next run. |
| 18 | VG, IA | rbac-step3 "ACS not yet" skip path untested | low | defer | Fake az lacks `resource show`; check by hand once. |
| 19 | EC, IA | In-memory throttle resets on recycle or scale-out | low | reject | AD-16: no shared state; pipeline is single-instance (AD-17). |
| 20 | EC, IA | First `<env>/app` apply after merge adds six blank settings and restarts the pipeline | low | reject | Nothing is created and nothing sends; recorded in the PR. |
| 21 | IA | Recipients from config, not Entra role members | false | reject | AD-16: `ALERT_RECIPIENTS_<ROLE>`. |
| 22 | BH | Deep-link routes not tied to web/staff | false | reject | `/price-comparison?material_id=` (5.3) and `/watchlist?supplier=` (5.4 + this story) exist and are tested there. |

## Verification

**Commands:**
- `cd backend && uv run pytest tests -q -k "5_2 or 5_3 or 5_4 or function_apps"` -- expected: pass
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run lint-imports && uv run pip-audit` -- expected: clean
- `ci/checks.sh lint && ci/checks.sh test` -- expected: green, ≤ 200 cases (terraform fmt, validate, tflint, test included)
