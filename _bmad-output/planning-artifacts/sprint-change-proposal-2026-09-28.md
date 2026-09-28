---
name: 'Sprint Change Proposal: align stories, spec and UX with the adopted architecture spine'
type: sprint-change-proposal
workflow: bmad-correct-course (batch mode)
status: approved and applied (Dj, 2026-09-28; D-1..D-5 at recommended defaults)
created: '2026-09-28'
trigger: implementation-readiness FAIL, followed by the bmad-architecture spine update (AD-1 to AD-20 all ADOPTED)
inputs:
  - _bmad-output/planning-artifacts/implementation-readiness.md
  - _bmad-output/planning-artifacts/architecture/architecture-ocrinvoicing-2026-09-28/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/architecture/architecture-ocrinvoicing-2026-09-28/reviews/review-update-adversary.md
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/specs/spec-ocr-invoice-automation/SPEC.md
  - _bmad-output/planning-artifacts/ux-designs/ux-ocrinvoicing-2026-09-28/EXPERIENCE.md
targets:
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/specs/spec-ocr-invoice-automation/SPEC.md
  - _bmad-output/planning-artifacts/ux-designs/ux-ocrinvoicing-2026-09-28/EXPERIENCE.md
---

# Sprint Change Proposal: align stories, spec and UX with the adopted spine

Paths used below: **S** = `ARCHITECTURE-SPINE.md`, **E** = `epics.md`, **SPEC** = `SPEC.md`, **EXP** = `EXPERIENCE.md`, **IR** = `implementation-readiness.md`, **ADV** = `reviews/review-update-adversary.md`. The spine is the source of truth: wherever a story disagrees with it, the story changes.

## 1. Issue Summary

- **What happened.** The implementation-readiness gate failed (IR, 8 blockers B1–B8 and 11 concerns C1–C11). `bmad-architecture` then updated the spine. All ADs (AD-1 to AD-20) are now ADOPTED, and three new ADs close the data, validation and analytics gaps: AD-18 (extraction data model), AD-19 (validation rules) and AD-20 (analytics rules). The update also absorbed every delta proposed by ADV (U-1 to U-16).
- **The problem.** `epics.md`, `SPEC.md` and `EXPERIENCE.md` were written before that update. They now contradict or trail the spine in about 50 places. Some of these errors are unsafe if built as written:
  - Story 1.7 puts the link token in the URL path, so it would be logged.
  - Story 2.3 stores bank values in plain text until Story 2.6.
  - Story 2.2's sweeper would re-queue invoices waiting for an admin.
  - Story 2.5 compares the tax-inclusive total with cumulative receipts, so every second invoice against a PO would fail.
- **Category.** Misalignment after a requirements and architecture clarification. This is not a technical failure and needs no strategic pivot.
- **Evidence.** IR "Progress" and "Suggested order of fixes", step 3. ADV "Stories that contradict the spine". Line-by-line comparison of E, SPEC and EXP against S (section 4).

## 2. Impact Analysis

### 2.1 Epic impact

| Epic | Impact | Summary |
| --- | --- | --- |
| Epic 1 | Moderate | Stories 1.1, 1.2 and 1.3 take the AD-17 step table: bootstrap app registrations and budget, DI F0 and ACS in `shared/foundation`, the operator RBAC and database steps, queues in `<env>/foundation`, and the recorded dev auto-apply departure. Story 1.5 drops the log-cap alert and moves pipeline alerts to custom metrics. Stories 1.6–1.9 take AD-6: fragment token, `supplier_name`, `--revoke`, per-field bank rows, upload write order, and the "Send it anyway" outcome. |
| Epic 2 | High (ACs rewritten) | Stories 2.1–2.6 take AD-2, AD-3, AD-4, AD-18 and AD-19: status map, lease reclaim, `routing_id`, field and line rows, bank encryption at extract, checked fields, PO match with tolerance, fuzzy name, per-field bank fingerprint, and the goods-received date check. Stories 2.7–2.11: bootstrap app registration, operator redirect step, open reasons, Retry intake, the Reject guard, restored edits, and `localStorage`. |
| Epic 3 | Moderate | Story 3.1: `invoice-v1.xsd`, own app registration, `pipeline` identity only. Story 3.2: `post_failures`, `next_attempt_at` claim, `ACCOUNTS_BASE_URL`. Story 3.3: the `a` shortcut and open reasons. |
| Epic 4 | Moderate (one story added) | Story 4.2 is decided (weekdays), built by the analytics refresh job with the AD-13 "invoiced" rule. Story 4.3: partition replace and re-check. **New must-have Story 4.4** (Suppliers list and page shell), so the could-have becomes Story 4.5 (B8). Story 4.1 reuses the shared quality module and the AD-6 idempotency order. |
| Epic 5 | Moderate | Story 5.1 takes the AD-20 inputs and the straight-through share, and extends the refresh job. Story 5.2: per-environment throttles and `emailed_at`. Stories 5.3–5.5: AD-20 thresholds, the "No data yet" state, alerts and evidence on Price comparison. |

- No epic becomes obsolete, and no new epic is needed. Epic order stays the same.
- One story is inserted: Story 4.4. The could-have story is renumbered from 4.4 to 4.5.
- Story 4.2 now creates the analytics refresh job and the `analytics` schema, which Story 5.1 extends. This removes the old gap where a separate "overdue job" wrote to `analytics`.

### 2.2 Artifact conflicts

- **SPEC:**
  - CAP-1: link issuing departs from P-8.
  - CAP-3: an overridden upload is processed normally if it passes.
  - CAP-4: only the checked fields count.
  - CAP-5: pre-tax amount, tolerance, quantity not yet invoiced.
  - CAP-7: the photo date is compared with the goods-received date.
  - CAP-10: training is deferred.
  - CAP-12: the list is made each weekday.
  - The confidence constraint changes to match CAP-4.
- **EXP:**
  - the link format (`/u#<token>`);
  - `--replace-link` and `--revoke`;
  - the "Send it anyway" copy and outcome;
  - a Retry intake action, and the Reject guard once an accounts reference exists;
  - the shortcut setting stored in `localStorage`;
  - Flow 3's duplicated CAP-10 note and its "total matched the PO" line;
  - supplier search;
  - the bank-change panel when no value is on file.
- **Architecture:** no change needed, except one Structural Seed line if D-2 is accepted (`shared/quality/`).
- **DESIGN.md:** no conflict found.

### 2.3 Technical impact

- **Schema work moves earlier.**
  - The `intake` migration in Story 2.1 gains the full AD-3 invoice row and `status_history`.
  - Story 2.3 adds `extraction_run`, `invoice_field` and `invoice_line`.
  - Every schema-creating migration carries its AD-11 grants (Stories 1.6, 2.1, 2.4, 3.1 and 4.2).
- **Operator steps enter Story 1.1:** AD-17 steps 3 and 5. Step 8 enters Story 2.7. The pipeline in Story 1.2 runs steps 6, 7 and 9 in the AD-17 order.
- **Alert rules on custom metrics** are created in the stories that emit them (2.2 and 2.3), not in Story 1.5. Creating a metric alert before its metric exists may need metric validation skipped in Terraform; the developer should check this during Story 2.2.
- **Test impact:** many new test cases are named in the Tasks lines: tolerance edges, partial deliveries, the SWIFT vs account-number comparison, stale reasons, and lease reclaim. No completed code is affected, because no story has been built.

### 2.4 Checklist status

| Id | Item | Status | Note |
| --- | --- | --- | --- |
| 1.1 | Triggering story | [x] | No single story. The trigger is the readiness FAIL plus the spine update; the stories most affected are 1.7, 2.3, 2.2 and 2.5 (ADV table). |
| 1.2 | Core problem | [x] | Artifacts written before the spine update now contradict it (misunderstanding or clarification of requirements). |
| 1.3 | Evidence | [x] | IR B1–B8 and C1–C11; ADV contradiction table; the OLD quotes in section 4. |
| 2.1 | Current epic | [x] | No epic is in progress. Every epic can be completed with edited ACs. |
| 2.2 | Epic-level changes | [x] | ACs changed in Epics 1–5; one story added in Epic 4 (4.4) and one renumbered (4.5). |
| 2.3 | Remaining epics | [x] | Dependencies fixed: DI F0 moves to 1.1, the `a` shortcut moves to 3.3, 5.2 uses fixtures and 5.1's `alert` table, 5.5 depends on the new must-have 4.4, and 4.2 creates the refresh job used by 4.3 and 5.1. |
| 2.4 | Obsolete or new epics | [N/A] | None. |
| 2.5 | Epic order | [x] | Unchanged. |
| 3.1 | PRD (SPEC) conflicts | [x] | 8 SPEC edits (S-01 to S-08). The MVP is still achievable; CAP-10's success line is restated as deferred, as already decided. |
| 3.2 | Architecture conflicts | [x] | The spine is authoritative and needs no edits. D-2 may add one Structural Seed line. |
| 3.3 | UX conflicts | [x] | 10 EXP edits (X-01 to X-10). |
| 3.4 | Other artifacts | [!] | Jira project OCR must mirror the story edits and the 4.4/4.5 renumber. `sprint-status.yaml` does not exist yet. Terraform, CI and monitoring are covered through Stories 1.1, 1.2, 1.5, 2.2 and 2.3. |
| 4.1 | Option 1: Direct Adjustment | Viable | Effort Medium, risk Low. |
| 4.2 | Option 2: Rollback | Not viable | Nothing has been built. |
| 4.3 | Option 3: MVP review | Not viable | Not needed: scope is unchanged, and CAP-19 stays could-have. |
| 4.4 | Path selected | [x] | Option 1, Direct Adjustment. |
| 5.1 | Issue summary | [x] | Section 1. |
| 5.2 | Epic and artifact impact | [x] | Section 2. |
| 5.3 | Path and rationale | [x] | Section 3. |
| 5.4 | MVP impact and plan | [x] | The MVP is unaffected. Plan in section 5. |
| 5.5 | Handoff plan | [x] | Section 5. |
| 6.1 | Checklist complete | [x] | |
| 6.2 | Proposal accurate | [x] | Every OLD quote was checked by script to occur exactly once in its target file. |
| 6.3 | Approval | [!] | Pending: Dj approves, and settles D-1 to D-5. |
| 6.4 | sprint-status.yaml | [N/A] | Not generated yet. The rerun of `bmad-sprint-planning` creates it. |
| 6.5 | Next steps | [!] | After approval (section 5). |

## 3. Recommended Approach

- **Direct Adjustment (Option 1).** Apply the string replacements in section 4 to the three artifacts, mirror the story changes in Jira (OCR), then rerun `bmad-sprint-planning`.
- **Why.** The spine already holds every decision, so this is transcription, not redesign. No code exists, so nothing needs to be rolled back. Scope and MVP are unchanged. The one structural change, the Suppliers shell becoming a must-have story, removes a must-have → could-have dependency without adding scope, because the Suppliers surface is already must-have in EXP.
- **Alternatives considered.**
  - Fold the Suppliers shell into Story 5.5. This avoids a renumber, but Story 4.5 (could-have) would then depend on a later epic (D-4).
  - Leave the spec wording loose and rely on the spine. Rejected: IR C1 requires the SPEC and EXP copy to match, and readiness reruns will compare them.
- **Effort:** Medium. There are about 70 replacements; the Story 2.5 and 2.6 AC rewrites are the largest.
- **Risk:** Low. Every NEW text cites its AD, and the OLD quotes were verified by script.
- **Timeline:** about half a day to apply and sync Jira, then a readiness rerun. There is no impact on the sprint timeline, because no sprint has started.

## 4. Detailed Change Proposals

Format: each entry gives the id, the target, the OLD text (verbatim, for a string replacement), the NEW text and the rationale. Ids starting with `E-` target `epics.md`, `S-` target `SPEC.md` and `X-` target `EXPERIENCE.md`. Apply them in order within a file. Where NEW says *(delete)*, remove the OLD text and the blank line after it.

### 4.1 epics.md: Requirements Inventory

#### E-01 · FR1 (CAP-1) · Functional Requirements

**OLD:**
```text
- **FR1 (CAP-1):** A supplier submits an invoice photo or PDF from their phone through a personal upload link, and the link identifies the supplier. An upload is recorded against the link's supplier, whatever supplier ID is printed on the invoice. The supplier can't edit extracted data. Links are issued and revoked automatically.
```
**NEW:**
```text
- **FR1 (CAP-1):** A supplier submits an invoice photo or PDF from their phone through a personal upload link, and the link identifies the supplier. An upload is recorded against the link's supplier, whatever supplier ID is printed on the invoice. The supplier can't edit extracted data. Links are issued and revoked only by the operator-run supplier load script (`--replace-link`, `--revoke`), an accepted departure from P-8 (AD-6).
```
**Rationale:** AD-6 "Links" (P-8 departure); IR C1.

#### E-02 · FR3 (CAP-3) · Functional Requirements

**OLD:**
```text
- **FR3 (CAP-3):** A blurred, dark or cropped photo is refused before submission with a retake prompt. After 2 refusals, the supplier may send it anyway, and it is checked by hand in the admin queue.
```
**NEW:**
```text
- **FR3 (CAP-3):** A blurred, dark or cropped photo is refused before submission with a retake prompt. After 2 refusals, the supplier may send it anyway. The server re-checks it with the same thresholds: if it passes, it is processed normally, and if it fails, it goes to the admin queue as `UNREADABLE` (AD-6).
```
**Rationale:** AD-6 "Checks" (overridden uploads); IR C1.

#### E-03 · FR4 (CAP-4) · Functional Requirements

**OLD:**
```text
- **FR4 (CAP-4):** Invoice fields are extracted from any supplier layout, handwriting included, without per-supplier setup. Each field carries a confidence score, and any field below 98% sends the invoice to the admin queue.
```
**NEW:**
```text
- **FR4 (CAP-4):** Invoice fields are extracted from any supplier layout, handwriting included, without per-supplier setup. Each field carries a confidence score, and any checked field (AD-18) below 98% sends the invoice to the admin queue. Other fields are stored but not checked, an accepted departure from P-9.
```
**Rationale:** AD-18 "Checked fields"; IR B3 (LOW_CONFIDENCE), C1 (CAP-4).

#### E-04 · FR5 (CAP-5) · Functional Requirements

**OLD:**
```text
- **FR5 (CAP-5):** An invoice whose amount differs from the PO price × received quantity goes to the admin queue, not to the accounts system.
```
**NEW:**
```text
- **FR5 (CAP-5):** An invoice whose pre-tax sub-total differs from the PO price × the quantity received and not yet invoiced, by more than the larger of 1% and 1.00 (AD-19), goes to the admin queue, not to the accounts system.
```
**Rationale:** AD-19 "PO match"; IR B1.

#### E-05 · FR7 (CAP-7) · Functional Requirements

**OLD:**
```text
- **FR7 (CAP-7):** When the photo-taken date doesn't match the invoice delivery date, the invoice goes to the admin queue, and the supplier is not notified. A PDF or scan with no photo date also goes to the admin queue.
```
**NEW:**
```text
- **FR7 (CAP-7):** When the photo was taken before the PO's latest goods-received date or more than 30 days after it, the invoice goes to the admin queue, and the supplier is not notified. A PDF or scan with no photo date also goes to the admin queue.
```
**Rationale:** AD-19 "Photo date"; IR B3, C1 (CAP-7).

#### E-06 · FR12 (CAP-12) · Functional Requirements

**OLD:**
```text
- **FR12 (CAP-12):** A daily overdue list shows POs past their expected date with no invoice, grouped by supplier. An invoice is overdue the day after the expected date. Whether the list runs daily or on weekdays only is open until this is built.
```
**NEW:**
```text
- **FR12 (CAP-12):** An overdue list, made each weekday, shows POs past their expected date with no invoice, grouped by supplier. A PO is overdue the day after its expected date, and one due at the weekend appears on Monday's list (AD-13).
```
**Rationale:** AD-13 "Overdue list"; IR B7 (Dj decided weekdays).

#### E-07 · FR14 (CAP-14) · Functional Requirements

**OLD:**
```text
- **FR14 (CAP-14):** Finance and procurement compare suppliers' unit prices for the same material side by side. A rise against a supplier's own recent invoices triggers an alert naming the supplier, the material and the invoices.
```
**NEW:**
```text
- **FR14 (CAP-14):** Finance and procurement compare suppliers' unit prices for the same material side by side. A posted unit price more than 2% above the supplier's previous posted price for that material (AD-20) triggers an alert naming the supplier, the material and the invoices.
```
**Rationale:** AD-20 "Price rise"; IR B3.

#### E-08 · NFR8 (P-8) · NonFunctional Requirements

**OLD:**
```text
- **NFR8 (P-8):** Upload links are unguessable, per supplier, and issued and revoked automatically.
```
**NEW:**
```text
- **NFR8 (P-8):** Upload links are unguessable (256 random bits) and per supplier. They are issued and revoked by the operator-run load script, an accepted departure from P-8 (AD-6).
```
**Rationale:** AD-6; IR C1.

#### E-09 · NFR9 (P-9) · NonFunctional Requirements

**OLD:**
```text
- **NFR9 (P-9):** Document Intelligence is the only AI, starting with its prebuilt invoice model. The confidence threshold is 98%.
```
**NEW:**
```text
- **NFR9 (P-9):** Document Intelligence is the only AI, starting with its prebuilt invoice model. The confidence threshold is 98% on the AD-18 checked fields only, an accepted departure from P-9.
```
**Rationale:** AD-18 "Checked fields" (P-9 departure); IR B3.

#### E-10 · Additional Requirements · Infrastructure (AD-17)

**OLD:**
```text
- **Infrastructure (AD-17):**
  - One subscription with resource groups `shared`, `dev` and `prod`.
  - Terraform stacks run in order: `shared/foundation` (PostgreSQL B1ms PG 18 with `invoicing_dev` and `invoicing_prod`, and DI F0 with a custom subdomain) → `<env>/foundation` → `<env>/app`.
  - Azure DevOps pipelines authenticate with workload identity federation, using a separate deploy identity per environment. Prod and `shared` apply only after manual approval.
```
**NEW:**
```text
- **Infrastructure (AD-17):**
  - One subscription with three resource groups (`shared`, `dev` and `prod`), named per P-16.
  - Every resource belongs to one step of the AD-17 step table: 1. `infra/bootstrap/` (operator: state, resource groups, deploy identities, two Entra app registrations per environment, the `ACS Email Sender` role, the $8 subscription budget) → 2. `shared/foundation` (PostgreSQL B1ms PG 18 with `invoicing_dev` and `invoicing_prod`, DI F0 with a custom subdomain, ACS Email and its domain) → 3. operator RBAC step → 4. `<env>/foundation` → 5. operator database step → 6. migrations → 7. `<env>/app` → 8. operator redirect-URI step → 9. code deploy.
  - Azure DevOps pipelines authenticate with workload identity federation, using a separate deploy identity per stack owner. Dev applies its saved plan automatically on merge, an accepted departure from `terraform.md` rules 26 and 33. Prod and `shared` apply only after manual approval.
```
**Rationale:** AD-17 step table, "Names", "Repo and pipeline"; IR B5, B6, C6, C9 (P-16 names).

#### E-11 · Additional Requirements · Messaging (AD-2)

**OLD:**
```text
  - A sweeper timer re-enqueues invoices idle for more than 1 h.
  - Each `*-poison` queue has a trigger that calls `route_to_admin(PROCESSING_FAILED)`.
```
**NEW:**
```text
  - A sweeper timer runs every 15 minutes and re-enqueues stranded invoices by the AD-2 status map, never `in_admin_queue`. It also deletes `uploadkeys` rows older than 24 h.
  - Each `*-poison` queue has a trigger that calls `route_to_admin(PROCESSING_FAILED)`, only while the invoice is still in that queue's input state or in its claim state with an expired lease.
```
**Rationale:** AD-2 "Recovery" and "Ordinary failures"; IR C2, C10.

#### E-12 · Additional Requirements · State machine (AD-3)

**OLD:**
```text
  - Admin actions are Correct, Approve, Re-extract and Reject.
```
**NEW:**
```text
  - Admin actions are Correct, Approve, Re-extract, Retry intake and Reject. Reject is refused once `accounts_ref` exists.
  - Posting failures are counted in `intake.invoice.post_failures`, and the post claim respects `next_attempt_at`.
```
**Rationale:** AD-3 "Admin actions" and "Posting backoff".

#### E-13 · Additional Requirements · Admin queue (AD-4)

**OLD:**
```text
  - The printed-ID check uses `VendorTaxId` and `VendorName`.
```
**NEW:**
```text
  - The printed-supplier check compares `vendor_tax_id` with the master `tax_id` when both exist, and otherwise requires a rapidfuzz token-set similarity of 85 or more between `vendor_name` and the supplier's name (AD-19).
  - An invoice's open reasons are the `admin_item` rows of its latest `routing_id`.
```
**Rationale:** AD-19 "Printed supplier", AD-4 "Open reasons"; IR B3.

#### E-14 · Additional Requirements · Extraction (AD-8)

**OLD:**
```text
  - Confidence and bounding regions are stored for every field.
```
**NEW:**
```text
  - Results are stored as AD-18 rows (`extraction_run`, `invoice_field`, `invoice_line`) with confidence, page and polygon. The raw DI result is not stored.
```
**Rationale:** AD-8 "Output", AD-18; IR B2.

#### E-15 · Additional Requirements · Data and security (AD-11)

**OLD:**
```text
  - Bank details use pgcrypto plus an HMAC fingerprint, normalised first, and only the admin role can decrypt.
  - Each app has its own database role, with Entra-only auth.
```
**NEW:**
```text
  - Bank details are stored per bank field id as `pgp_pub_encrypt` ciphertext plus an HMAC fingerprint, normalised first, from their first write (the `extract` stage). Only `staff-api` holds the private key, and only the admin role sees plaintext.
  - Each environment has the AD-11 database logins (the `pipeline`, `staff-api` and `accounts-sim` identities, Dj's user, the deploy identity), with Entra-only auth. `supplier-api` has none. Each login can connect only to its own environment's database, and every schema grant is an Alembic migration.
```
**Rationale:** AD-11 "Where bank details are protected" and "Database logins"; IR B4, C3, C10.

#### E-16 · Additional Requirements · Email (AD-16)

**OLD:**
```text
- **Email (AD-16):** an `EmailPort` over ACS Email with a verified custom domain, throttled to 30 per minute and 100 per hour. Emails go to staff alerts only.
```
**NEW:**
```text
- **Email (AD-16):** an `EmailPort` over ACS Email with a verified custom domain. It throttles per environment with no shared state: Dev at most 5 a minute and 20 an hour, Prod at most 25 a minute and 80 an hour. Recipients come from `ALERT_RECIPIENTS_<ROLE>`. Emails go to staff alerts only.
```
**Rationale:** AD-16; ADV table (5.2); IR C6.

#### E-17 · Additional Requirements · Monitoring (AD-17)

**OLD:**
```text
- **Monitoring (AD-17):**
  - Log Analytics capped at 0.08 GB/day.
  - Alerts on budget, the log cap, poison queues, stuck invoices and DI pages at 80%.
```
**NEW:**
```text
- **Monitoring (AD-17):**
  - Log Analytics capped at 0.08 GB/day, with no separate log-cap alert (Dj's decision).
  - Alerts on the budgets and on the Application Insights custom metrics `poison_message{queue}`, `stuck_invoices` and `di_pages_used_pct` (80%), with alerting on custom metric dimensions turned on.
```
**Rationale:** AD-17 "Alerts"; IR C5.

#### E-18 · Additional Requirements · Supplier load script

**OLD:**
```text
- **Supplier load script:** an operator-run script that loads suppliers through the application code, encrypting bank details and printing each new link once.
```
**NEW:**
```text
- **Supplier load script:** an operator-run script, run as Dj's user, that loads suppliers through the application code. It encrypts each bank field, stores `supplier_name` with each link for display, prints each new link once, and supports `--replace-link` and `--revoke`.
```
**Rationale:** AD-6 "Links", AD-11; IR C1, C4.

#### E-19 · UX-DR5 · UX Design Requirements

**OLD:**
```text
  - **Send it anyway. Babaloo will look at it by hand.** appears after 2 failures.
```
**NEW:**
```text
  - **Send it anyway** appears after 2 failures. The server re-checks the upload, and it is processed normally if it passes.
```
**Rationale:** AD-6 "Checks"; IR C1. The copy follows open decision D-1.

#### E-20 · UX-DR8 · UX Design Requirements

**OLD:**
```text
  - the sidebar shows only the role's surfaces;
```
**NEW:**
```text
  - the sidebar shows only the surfaces of the user's roles (the combined set for a user with several roles);
```
**Rationale:** AD-14 ("sees the surfaces of all of them"); EXP Navigation by role; IR C8.

### 4.2 epics.md: Epic 1 stories

#### E-21 · Story 1.1 · AC (repository layout)

**OLD:**
```text
**Then** it contains `backend/`, `web/supplier/`, `web/staff/` and `infra/` (with `bootstrap/`, `modules/`, `shared/`, `dev/` and `prod/`) per `terraform.md`
```
**NEW:**
```text
**Then** it contains `backend/`, `web/supplier/`, `web/staff/`, `shared/` (with `quality-thresholds.json`) and `infra/` (with `bootstrap/`, `modules/`, `shared/`, `dev/` and `prod/`) per `terraform.md` and the spine's Structural Seed
```
**Rationale:** Spine Structural Seed (`shared/quality-thresholds.json`); IR C7 (Story 4.1).

#### E-22 · Story 1.1 · AC (bootstrap)

**OLD:**
```text
**Given** `infra/bootstrap/state-backend.sh` has been run once by an operator with Owner rights
**When** it finishes
**Then** the Terraform state storage exists with Entra auth, shared-key access disabled and versioning on
**And** the resource groups `shared`, `dev` and `prod` exist with the 5 P-17 tags, and the resource providers are registered
```
**NEW:**
```text
**Given** the `infra/bootstrap/` scripts have been run once by an operator with Owner rights (AD-17 step 1)
**When** they finish
**Then** the Terraform state storage exists with Entra auth, shared-key access disabled and versioning on
**And** the three resource groups exist, named per P-16 (`babaloo-sea-lng-rg-<nn>`: Dev `0x`, Prod `1x`, shared `2x`), with the 5 P-17 tags, and the resource providers are registered
**And** the deploy identities for `dev`, `prod` and `shared` exist with their federated credentials, each holding only the rights in AD-17 "Deploy identity rights"
**And** each environment has two Entra app registrations: `staff-api` (app roles `admin`, `finance`, `procurement`, `management` and `goods_in`, "assignment required", ID-token issuance on) and `accounts-sim`
**And** the custom role `ACS Email Sender` (the email send action only) and the $8 subscription budget alert exist
```
**Rationale:** AD-17 step 1, "Names", "Deploy identity rights"; AD-14; IR B5, C9 (P-16 resource-group names).

#### E-23 · Story 1.1 · AC (shared/foundation)

**OLD:**
```text
**Then** PostgreSQL Flexible Server B1ms runs PostgreSQL 18 with 32 GB, a 7-day local backup, Entra-only auth and `pgcrypto` allow-listed
**And** it holds the databases `invoicing_dev` and `invoicing_prod`, and its name follows `babaloo-sea-lng-<type>-2x` (AD-12, AD-17)
```
**NEW:**
```text
**Then** PostgreSQL Flexible Server B1ms runs PostgreSQL 18 with 32 GB, a 7-day local backup, Entra-only auth and `pgcrypto` allow-listed
**And** it holds the databases `invoicing_dev` and `invoicing_prod`, and its name follows `babaloo-sea-lng-<type>-2x` (AD-12, AD-17)
**And** one Document Intelligence F0 resource exists in `southeastasia` with a custom subdomain (AD-8)
**And** ACS Email exists with Dj's verified custom domain (the DNS records are added by hand), and the `shared` resource-group budget exists

**Given** the operator RBAC step in the bootstrap README (AD-17 step 3)
**When** it is done
**Then** each environment's deploy identity holds RBAC Administrator on the DI and ACS resources, conditioned to assigning only the runtime roles those resources need
```
**Rationale:** AD-17 steps 2–3; IR C7 (DI F0 belongs to `shared/foundation`), B5 (cross-resource-group role assignment).

#### E-24 · Story 1.1 · AC (env foundation and operator database step)

**OLD:**
```text
**Then** the environment has:
- a storage account (LRS, 7-day soft delete) with containers `images` and `corrections`, a 30-day lifecycle delete rule, and the tables `supplierlinks`, `uploadkeys` and `supplierreminders`;
- a Key Vault;
- a Log Analytics workspace (0.08 GB/day cap, 30-day retention) and Application Insights;
- the RG budget (alerts at 90%, 100% and 110%, plus the 110% forecast);
- all names following P-16 with Dev `0x` and Prod `1x`.

**And** a subscription budget alert fires at $8
**And** a resource missing any of the 5 tags fails the plan
```
**NEW:**
```text
**Then** the environment has:
- the four user-assigned app identities (`supplier-api`, `staff-api`, `pipeline` and `accounts-sim`);
- a storage account (LRS, 7-day soft delete) with containers `images` and `corrections`, a 30-day lifecycle delete rule, the queues `q-quality`, `q-extract`, `q-validate` and `q-post`, and the tables `supplierlinks`, `uploadkeys` and `supplierreminders`;
- a Key Vault holding the PGP key pair and the HMAC key generated by Terraform, with the deploy identity as Key Vault Secrets Officer on this vault only;
- a Log Analytics workspace (0.08 GB/day cap, 30-day retention), Application Insights (sampling on) and an action group that emails Dj;
- the RG budget (alerts at 90%, 100% and 110%, plus the 110% forecast);
- all names following P-16 with Dev `0x` and Prod `1x`.

**And** the stack reads the `shared/foundation` outputs through `terraform_remote_state`, the departure recorded in AD-17
**And** a resource missing any of the 5 tags fails the plan

**Given** the operator database step in the bootstrap README (AD-17 step 5), run once per environment as the PostgreSQL Entra admin
**When** it finishes
**Then** that environment's AD-11 logins exist (the `pipeline`, `staff-api` and `accounts-sim` identities, Dj's user and the deploy identity), created with `pgaadauth_create_principal`
**And** the environment's deploy identity owns its database, `CONNECT` is revoked from `PUBLIC`, and only that environment's logins are granted `CONNECT`
**And** a test shows that a Dev login can't connect to `invoicing_prod`
**And** Dj's user holds Key Vault Secrets User and Storage Table Data Contributor on that environment's vault and storage account, for the load script
```
**Rationale:** AD-17 steps 4–5, "Monitoring"; AD-11 "Database logins"; AD-12. The $8 budget moves to the bootstrap (E-22). IR B4, B5, C6, C10 (Dev with no grant on `invoicing_prod`).

#### E-25 · Story 1.2 · AC (deploy)

**OLD:**
```text
**Then** it authenticates only through workload-identity-federation service connections, one deploy identity per environment
**And** it plans and applies `dev` automatically, then waits for manual approval before applying `shared` and `prod`
```
**NEW:**
```text
**Then** it authenticates only through workload-identity-federation service connections, one deploy identity per stack owner (`shared`, `dev` and `prod`)
**And** it applies `dev` from a saved plan automatically on merge to `main`, the accepted departure from `terraform.md` rules 26 and 33 and `security.md` rule 34 recorded in AD-17
**And** it applies `shared` and `prod` from a saved plan only after manual approval
**And** the operator steps (AD-17 steps 1, 3, 5 and 8) stay outside the pipeline, in the bootstrap README
```
**Rationale:** AD-17 "Repo and pipeline"; IR B6 (Dj's decision recorded).

#### E-26 · Story 1.2 · AC (migrations)

**OLD:**
```text
**Then** Alembic migrations run as a pipeline step before the app deploy, never at app start
```
**NEW:**
```text
**Then** Alembic `upgrade head` runs as a pipeline step, as the environment's deploy identity, after `<env>/foundation` and before `<env>/app` and the code deploy (AD-17 steps 6, 7 and 9), never at app start
**And** every schema grant is part of a migration (AD-11)
```
**Rationale:** AD-17 step 6, AD-11; IR B4.

#### E-27 · Story 1.3 · AC (apps and roles)

**OLD:**
```text
**Then** four Flex apps exist (one plan each, on-demand only), each with its own user-assigned identity
**And** each app gets only the roles it needs, with none subscription-scoped
```
**NEW:**
```text
**Then** four Flex apps exist (one plan each, on-demand only, 2,048 MB instance memory), each using its user-assigned identity from `<env>/foundation`
**And** the maximum instance count is 1 for `pipeline` and 10 for each other app (AD-17 compute ceilings)
**And** each identity gets exactly the runtime roles in the AD-17 table, at the narrowest scope, with none subscription-scoped
```
**Rationale:** AD-17 step 7, "Runtime roles", "Compute ceilings"; AD-2.

#### E-28 · Story 1.3 · AC (pipeline host.json)

**OLD:**
```text
**Then** `host.json` has `batchSize` 1 and `newBatchThreshold` 0 for queues
**And** the queues `q-quality`, `q-extract`, `q-validate` and `q-post` exist
```
**NEW:**
```text
**Then** `host.json` has `batchSize` 1, `newBatchThreshold` 0 and `extensions.queues.messageEncoding` set to `none`
**And** every producer sends `QueueMessage` as plain JSON text through the `azure-storage-queue` SDK (AD-2); the queues themselves come from `<env>/foundation` (Story 1.1)
```
**Rationale:** AD-2 "Message encoding"; AD-17 step 4 (queues belong to `<env>/foundation`); IR C6.

#### E-29 · Story 1.5 · AC (alerts)

**OLD:**
```text
**Then** every app sends traces to that environment's Application Insights, with sampling on and one trace per `correlation_id`
**And** alerts to Dj fire when:
- the Log Analytics daily cap reaches 90%;
- any `*-poison` queue is longer than 0;
- a budget threshold is crossed.
```
**NEW:**
```text
**Then** every app sends traces to that environment's Application Insights, with sampling on and one trace per `correlation_id`
**And** a metrics helper in the `invoicing` package emits Application Insights custom metrics with dimensions, and alerting on custom metric dimensions is turned on (AD-17)
**And** alerts to Dj fire through the action group when a resource-group budget threshold or the $8 subscription budget is crossed

**Note:** the pipeline alerts use custom metrics emitted by later stories: `poison_message{queue}` and `stuck_invoices` (Story 2.2) and `di_pages_used_pct` (Story 2.3). Each of those stories adds its own alert rule. There is no separate log-cap alert (Dj's decision, AD-17).
```
**Rationale:** AD-17 "Alerts" (storage queue metrics have no per-queue breakdown; no log-cap alert); IR C5. This also removes a forward dependency on the poison triggers in Story 2.2 (C7).

#### E-30 · Story 1.6 · AC (load)

**OLD:**
```text
**Given** a CSV of synthetic suppliers (name, phone, bank details, `VendorTaxId`)
**When** the operator runs the supplier load script against Dev
**Then** the suppliers are created or updated in `master` through the application code (the first `master` migration)
**And** bank details are stored as `pgp_sym_encrypt` ciphertext plus an HMAC fingerprint, normalised first, with both keys in Key Vault (AD-11)
```
**NEW:**
```text
**Given** a CSV of synthetic suppliers (name, phone, `tax_id`, and one column per AD-18 bank field id: `bank_account_number`, `iban` and `swift`)
**When** the operator runs the supplier load script against Dev as Dj's user
**Then** the suppliers are created or updated in `master.supplier{id, name, tax_id, phone}` through the application code (the first `master` migration)
**And** each non-empty bank value is stored as one `master.supplier_bank{supplier_id, field_id, ciphertext, fingerprint}` row, with `pgp_pub_encrypt` ciphertext plus an HMAC-SHA256 fingerprint, normalised first (spaces and hyphens stripped, uppercase), using the public key and the HMAC key from Key Vault (AD-11)
**And** the migration grants `master` per AD-11: read/write for Dj's user, read including ciphertext for `staff-api`, and read without the ciphertext column for `pipeline`
**And** it creates `audit.event(id, at, actor, action, entity, entity_id, detail)`, with `INSERT` only for every login that writes it and `SELECT` for `staff-api`
```
**Rationale:** AD-11 `master` row and "Database logins"; AD-18 bank field ids (ADV U-1); IR B4, C10 ("only `staff-api` may SELECT ciphertext").

#### E-31 · Story 1.6 · AC (new link)

**OLD:**
```text
**Then** it creates a 256-bit random token and stores only its SHA-256 hash in `supplierlinks` with `supplier_id` and `issued_at`
**And** it prints the full link once, and never again
```
**NEW:**
```text
**Then** it creates a 256-bit random token (base64url) and stores only its SHA-256 hash in `supplierlinks` with `supplier_id`, `supplier_name` (for display on the upload page) and `issued_at`
**And** it prints the full link `https://<supplier-api host>/u#<token>` once, and never again (AD-6)
```
**Rationale:** AD-6 "Links"; IR C4.

#### E-32 · Story 1.6 · AC (revoke)

**OLD:**
```text
**Given** an existing supplier with `--replace-link`
**When** the script runs
**Then** it sets `revoked_at` on the old link, issues and prints a new link, and writes an audit entry
```
**NEW:**
```text
**Given** an existing supplier with `--replace-link`
**When** the script runs
**Then** it sets `revoked_at` on the old link, issues and prints a new link, and writes an audit entry

**Given** an existing supplier with `--revoke`
**When** the script runs
**Then** it sets `revoked_at` on the supplier's link without issuing a new one, and writes an audit entry
**And** that link then accepts no uploads and shows Link not working (Story 1.7)
```
**Rationale:** AD-6 ("`--revoke` revokes it without issuing another"); IR C1.

#### E-33 · Story 1.6 · Tasks

**OLD:**
```text
- Terraform: Key Vault secrets for the pgcrypto and HMAC keys; the database role for the loader identity.
- Python: `master` migration; `SupplierLinkRegistry` port and table adapter; the load script; `audit` append-only table.
- Tests: `test_story_1_6_*` for encryption, fingerprint normalisation, link issue and revoke, and log redaction.
```
**NEW:**
```text
- Prerequisites (Story 1.1): the PGP key pair and HMAC key in Key Vault; Dj's user login, Key Vault Secrets User and Storage Table Data Contributor from the operator database step (AD-17 step 5). This story has no Terraform.
- Python: `master` migration with its grants; `SupplierLinkRegistry` port and table adapter; the load script (`--replace-link`, `--revoke`); `audit` append-only table and grants.
- Tests: `test_story_1_6_*` for encryption, one row per bank field id, fingerprint normalisation, link issue, replace and revoke, `pipeline` refused on the ciphertext column, and log redaction.
```
**Rationale:** AD-17 steps 4–5 (keys generated in `<env>/foundation`, Dj's user granted by the operator); IR B4.

#### E-34 · Story 1.7 · AC (open link)

**OLD:**
```text
**Given** a valid, unrevoked link
**When** the supplier opens `…/u/<token>`
**Then** Upload home shows "Uploading for **{supplier name}**" with **Take photo** and **Choose file** (UX-DR4)
**And** `supplier-api` resolves the supplier from `supplierlinks` by the token hash, without touching PostgreSQL
```
**NEW:**
```text
**Given** a valid, unrevoked link
**When** the supplier opens `…/u#<token>`
**Then** the page reads the token from the URL fragment, which the browser never sends to the server, and sends it in the `X-Upload-Token` header on every call (AD-6)
**And** Upload home shows "Uploading for **{supplier name}**" with **Take photo** and **Choose file** (UX-DR4)
**And** `supplier-api` resolves `supplier_id` and `supplier_name` from `supplierlinks` by the token hash, without touching PostgreSQL
```
**Rationale:** AD-6 "Links" (fragment token, `X-Upload-Token`, `supplier_name`); ADV table (1.7, High); IR C4.

#### E-35 · Story 1.7 · AC (logging)

**OLD:**
```text
**Given** any request
**When** it is logged
**Then** the token never appears
```
**NEW:**
```text
**Given** any request
**When** it is logged
**Then** the token never appears, because no URL sent to the server carries it and the `X-Upload-Token` header is never logged (AD-14)
```
**Rationale:** AD-14 "Supplier upload"; Conventions "Logging".

#### E-36 · Story 1.7 · Tasks

**OLD:**
```text
- Python: `GET /api/link` (returns supplier display name only); the link lookup through the registry port.
```
**NEW:**
```text
- Python: `GET /api/link`, reading the token from `X-Upload-Token` and returning `supplier_name` only; the link lookup through the registry port.
```
**Rationale:** AD-6; IR C4.

#### E-37 · Story 1.8 · AC (upload order and retry)

**OLD:**
```text
**Then** it creates a UUIDv7 `invoice_id`
**And** it writes the bytes to `images/<invoice_id>` with `IntakeBlobMetadata` (`source=link`, `supplier_id`, `content_type`, `uploaded_at`, `device_check`)
**And** it stores `key → invoice_id` in `uploadkeys` for 24 h and enqueues `QueueMessage` on `q-quality`, all without PostgreSQL (AD-6)

**Given** a retry with the same `Idempotency-Key`
**When** it arrives
**Then** the same `invoice_id` and reference are returned, and no second blob or message is created
```
**NEW:**
```text
**Then** it checks the `X-Upload-Token`, creates a UUIDv7 `invoice_id`, and inserts `Idempotency-Key → invoice_id` into `uploadkeys` if absent; if the key already exists, the stored `invoice_id` is used
**And** it then writes the original bytes to `images/<invoice_id>` with `IntakeBlobMetadata` (`source=link`, `supplier_id`, `content_type`, `uploaded_at`, `device_check`), unless the blob already exists
**And** it then enqueues `QueueMessage` on `q-quality` and returns the `invoice_id` and reference, in that order and all without PostgreSQL (AD-6)

**Given** a retry with the same `Idempotency-Key` within 24 hours
**When** it arrives
**Then** the same `invoice_id` and reference are returned, the blob write (if missing) and the enqueue are replayed, and no second invoice is created
**And** a first attempt that died after writing the key is completed by the retry
```
**Rationale:** AD-6 "Uploads" (key, then blob, then enqueue; a retry replays steps 2 and 3; a duplicate message is harmless, AD-2). ADV U-7.

#### E-38 · Story 1.8 · Tasks (tests)

**OLD:**
```text
- Tests: `test_story_1_8_*` for the happy path, retry idempotency, size and type rejection, and the DB-stopped case; Vitest for the screens.
```
**NEW:**
```text
- Tests: `test_story_1_8_*` for the happy path, retry idempotency, a crash after each of the three steps, size and type rejection, and the DB-stopped case; Vitest for the screens.
```
**Rationale:** AD-6 write order.

#### E-39 · Story 1.9 · AC (thresholds)

**OLD:**
```text
**Then** blur, darkness and edge-cut-off checks run on the device in about 2 s or less (UX-DR5)
```
**NEW:**
```text
**Then** blur, darkness and edge-cut-off checks run on the device in about 2 s or less (UX-DR5), using the thresholds in `shared/quality-thresholds.json`, which the server `quality` stage also reads (AD-6)
```
**Rationale:** AD-6 "Checks" (one thresholds file); IR B3 (server re-check criteria).

#### E-40 · Story 1.9 · AC (send anyway)

**OLD:**
```text
**Then** **Send it anyway. Babaloo will look at it by hand.** appears as a secondary action
**And** sending uploads with `device_check=overridden` and shows the normal Received screen (FR3)
```
**NEW:**
```text
**Then** **Send it anyway** appears as a secondary action
**And** sending uploads with `device_check=overridden` and shows the normal Received screen; the server re-check then processes it normally if it passes, or routes it `UNREADABLE` if it fails (FR3, AD-6)
```
**Rationale:** AD-6 "Checks"; IR C1. The copy follows D-1.

#### E-41 · Story 1.9 · Tasks (shared module)

**OLD:**
```text
- React: quality-check module (blur, luminance, edge detection), Check & send states, and the send-anyway flow.
```
**NEW:**
```text
- React: quality-check module (variance of the Laplacian for blur, mean luminance for darkness, edge detection) in `shared/quality/`, beside `shared/quality-thresholds.json`, so `web/staff` can import it for Story 4.1; Check & send states; the send-anyway flow.
```
**Rationale:** AD-6 measures; IR C7 (Story 4.1 reuse needs a shared location). The location follows D-2.

### 4.3 epics.md: Epic 2 stories

#### E-42 · Story 2.1 · AC (row creation)

**OLD:**
```text
**Then** it inserts `intake.invoice` from `IntakeBlobMetadata` with `INSERT … ON CONFLICT (id) DO NOTHING`, with status `received`, `status_changed_at` and `claimed_until` (the first `intake` migration; AD-3, AD-5)
```
**NEW:**
```text
**Then** it inserts `intake.invoice` from `IntakeBlobMetadata` with `INSERT … ON CONFLICT (id) DO NOTHING`, with status `received` and the AD-3 columns (the first `intake` migration, which also creates `status_history` and grants `intake` per AD-11; AD-3, AD-5)
**And** every transition writes an `intake.status_history` row `{invoice_id, from_status, to_status, actor, at}` in the same transaction
```
**Rationale:** AD-3 "The invoice row" and "Transitions"; AD-11; IR B2 (status history), B4.

#### E-43 · Story 2.1 · AC (image checks)

**OLD:**
```text
**Then** the stage applies the EXIF orientation, re-checks readability, saves `photo_taken_at` from EXIF `DateTimeOriginal` (or null), and stores a 64-bit phash in `intake.image_hash`
```
**NEW:**
```text
**Then** the stage applies the EXIF orientation and re-checks readability with the page's measures (variance of the Laplacian and mean luminance, computed with Pillow) and the thresholds in `shared/quality-thresholds.json`
**And** it saves `photo_taken_at` from EXIF `DateTimeOriginal`, read as Singapore time unless `OffsetTimeOriginal` gives an offset (or null), and stores a 64-bit phash in `intake.image_hash` (AD-6, AD-9, AD-19)
```
**Rationale:** AD-6 "Checks"; AD-19 "Photo date"; IR B3 (server re-check, EXIF time zone).

#### E-44 · Story 2.1 · AC (route_to_admin)

**OLD:**
```text
**Then** `domain.route_to_admin(invoice_id, [UNREADABLE])` moves it to `in_admin_queue` and writes one `intake.admin_item` row in the same transaction (AD-4)
```
**NEW:**
```text
**Then** `domain.route_to_admin(invoice_id, [UNREADABLE], from_status)` moves it to `in_admin_queue` by conditional transition and, in the same transaction, writes one `intake.admin_item` row `{id, invoice_id, routing_id, run_id?, reason, field_ids[], detail, created_at}`, with one UUIDv7 `routing_id` per call (AD-4)
**And** a `device_check=overridden` upload that passes the re-check is processed like any other (AD-6)
```
**Rationale:** AD-4 "One way in"; AD-6; ADV U-3 and U-5.

#### E-45 · Story 2.1 · AC (redelivery)

**OLD:**
```text
**Given** a redelivered message whose transition changes zero rows while the invoice is already in the target state
**When** it is processed
**Then** the next stage is re-enqueued and the message acknowledged, with no duplicate row (AD-2)
```
**NEW:**
```text
**Given** a redelivered message whose transition changes zero rows
**When** it is processed
**Then** the stage reads the status: if it is the stage's final target (`awaiting_extraction` for quality), the next stage is re-enqueued; otherwise the message is only acknowledged. Either way, no duplicate row is created (AD-2)
**And** extract, validate and post use the same per-stage rule, with final targets `awaiting_validation`, `ready_to_post` or `in_admin_queue`, and `posted`
```
**Rationale:** AD-2 (zero-row handling per stage); ADV U-10.

#### E-46 · Story 2.1 · Tasks

**OLD:**
```text
- Python: `intake` migration (`invoice`, `admin_item`, `image_hash`); domain state machine and `route_to_admin`; reasons catalogue; the `quality` function.
```
**NEW:**
```text
- Python: `intake` migration (`invoice` with every AD-3 column, `status_history`, `admin_item` with `routing_id`, `image_hash`) and its AD-11 grants; domain state machine with lease reclaim, and `route_to_admin(invoice_id, reasons, from_status, metadata?)`; reasons catalogue; the `quality` function reading `shared/quality-thresholds.json`.
```
**Rationale:** AD-3, AD-4, AD-11; IR B2, B4, C10 (lease reclaim).

#### E-47 · Story 2.2 · AC (poison)

**OLD:**
```text
**Then** the poison trigger calls `route_to_admin(PROCESSING_FAILED)`, creating the invoice row if it is missing
**And** the trigger follows the same database-wait rule
```
**NEW:**
```text
**Then** the poison trigger calls `route_to_admin(PROCESSING_FAILED)` only when the invoice is still in that queue's input state, or in its claim state with an expired lease; otherwise it acknowledges the poison message (AD-2, AD-4)
**And** when the invoice row is missing, it passes the blob's `IntakeBlobMetadata`, so `route_to_admin` creates the row
**And** it emits the custom metric `poison_message{queue}`, and an alert to Dj fires when that is more than 0 in an hour (AD-17)
**And** the trigger follows the same database-wait rule
```
**Rationale:** AD-2 "Ordinary failures"; AD-4; AD-17 "Alerts"; ADV U-5, U-13; IR C5.

#### E-48 · Story 2.2 · AC (sweeper)

**OLD:**
```text
**Given** a non-terminal, unclaimed invoice whose `status_changed_at` is more than 1 hour old
**When** the sweeper timer runs (weekdays 01:30, 04:30 and 08:30 UTC)
**Then** it re-enqueues that invoice's next stage and logs it
**And** Dj gets a stuck-invoice alert
```
**NEW:**
```text
**Given** an invoice whose `status_changed_at` is more than 1 hour old and more than 1 hour after the database last started (`pg_postmaster_start_time()`)
**When** the sweeper timer runs (every 15 minutes, separately from the AD-13 schedule)
**Then** it re-enqueues the invoice by the AD-2 status map:
- `received` → `q-quality`;
- `awaiting_extraction`, or `extracting` with an expired lease → `q-extract`;
- `awaiting_validation`, or `validating` with an expired lease → `q-validate`;
- `ready_to_post` whose `next_attempt_at` is empty or past, or `posting` with an expired lease → `q-post`.

**And** it never touches `in_admin_queue`, `posted` or `rejected`
**And** it emits `stuck_invoices`, and an alert to Dj fires when that is more than 0 (AD-17)

**Given** an invoice in `extracting`, `validating` or `posting` whose 10-minute lease has expired
**When** a message for that stage arrives
**Then** the stage reclaims it with a conditional transition that requires the expired lease, and a live lease is never taken over (AD-3)

**Given** `uploadkeys` rows older than 24 hours
**When** the sweeper runs
**Then** it deletes them (AD-2, AD-6)
```
**Rationale:** AD-2 "Recovery" (15 minutes, status map, database start time, `uploadkeys` cleanup); AD-3 "Claim first" (reclaim); AD-13 (the sweeper is not one of its jobs). ADV table (2.2), U-11; IR C2, C10.

#### E-49 · Story 2.2 · Tasks

**OLD:**
```text
- Python: DB-wait decorator for consumers; poison triggers; sweeper timer.
- Terraform: stuck-invoice alert rule.
- Tests: `test_story_2_2_*` with the database unreachable, poison routing, and the sweeper picking up a stranded invoice.
```
**NEW:**
```text
- Python: DB-wait decorator for consumers; poison triggers with the state guard; sweeper timer (status map, `uploadkeys` cleanup); lease reclaim; the `poison_message` and `stuck_invoices` metrics.
- Terraform: the `poison_message` and `stuck_invoices` alert rules in `<env>/app`.
- Tests: `test_story_2_2_*` with the database unreachable, poison routing and its guard, each status-map row, `in_admin_queue` left alone, no stuck count right after a database start, lease reclaim, and `uploadkeys` cleanup.
```
**Rationale:** as E-47 and E-48.

#### E-50 · Story 2.3 · AC (DI role)

**OLD:**
```text
**Given** the `shared/foundation` stack
**When** it is applied
**Then** one Document Intelligence F0 resource exists in `southeastasia` with a custom subdomain
**And** each environment's `pipeline` identity has Cognitive Services User on it
```
**NEW:**
```text
**Given** the shared DI F0 resource (Story 1.1) and the conditioned RBAC Administrator from the operator step (AD-17 step 3)
**When** `<env>/app` is applied
**Then** that environment's `pipeline` identity has Cognitive Services User on the DI resource
```
**Rationale:** AD-17 steps 2, 3 and 7; IR C7 (DI F0 moves to Story 1.1), B5.

#### E-51 · Story 2.3 · AC (extract output)

**OLD:**
```text
**And** `adapters/document_intelligence.py` calls `prebuilt-invoice` on API `2024-11-30` through the `ModelSelector` port (default `prebuilt-invoice`)
**And** it stores every field with `confidence` and `boundingRegions`, then moves the invoice to `awaiting_validation` and enqueues `q-validate` (AD-8)
```
**NEW:**
```text
**And** `adapters/document_intelligence.py` calls `prebuilt-invoice` on API `2024-11-30` through the `ModelSelector` port (default `prebuilt-invoice`), saving the `Operation-Location` against `invoice_id` before polling
**And** it maps the result into one `intake.extraction_run` row, one `intake.invoice_field` row per header field and one `intake.invoice_line` row per line, with the AD-18 field ids, `confidence`, `page`, `polygon` and `currency` from `INVOICE_CURRENCY` (SGD), and it drops the raw DI result (AD-8, AD-18)
**And** every bank field (`payment[<n>].bank_account_number`, `.iban` and `.swift`) is stored from its first write as `pgp_pub_encrypt` ciphertext plus an HMAC fingerprint, normalised first, and never as plaintext (AD-11)
**And** it then moves the invoice to `awaiting_validation` and enqueues `q-validate`
```
**Rationale:** AD-8 "Polling", "Output", "Currency"; AD-18 "Runs", "Header fields", "Lines", "Field ids"; AD-11 ("from its first write (the `extract` stage)"). ADV table (2.3, High); IR B2, C3.

#### E-52 · Story 2.3 · AC (retry and Re-extract)

**OLD:**
```text
**Given** a retry after the extraction was already saved
**When** it runs
**Then** the saved result is reused, DI is not called again, and no pages are counted twice
```
**NEW:**
```text
**Given** a retry after an extraction run was saved since the invoice last entered `awaiting_extraction` (from `status_history`)
**When** it runs
**Then** the saved run is reused, DI is not called again, and no pages are counted twice
**And** a retry that finds a saved `Operation-Location` resumes polling instead of analysing again

**Given** an admin Re-extract
**When** extraction runs
**Then** DI is called again and a new run is saved, because earlier runs are older than the latest entry into `awaiting_extraction` (AD-3)
```
**Rationale:** AD-3 "Save the result before finishing"; AD-8 "Polling"; ADV U-2, U-14.

#### E-53 · Story 2.3 · AC (rate)

**OLD:**
```text
**Then** it sends at most 1 request every 2 s in each environment
```
**NEW:**
```text
**Then** it sends at most 1 request every 2 s in each environment, keeping the last call time in `intake.di_usage` under `pg_advisory_xact_lock`, so the limit holds across restarts and redeploys (AD-8)
```
**Rationale:** AD-8 "Rate"; ADV U-14.

#### E-54 · Story 2.3 · AC (quota)

**OLD:**
```text
**Then** the invoice is routed with `EXTRACTION_QUOTA`
**And** at 80% of the cap Dj gets an alert
```
**NEW:**
```text
**Then** the invoice is routed with `EXTRACTION_QUOTA`
**And** pages are reserved in `intake.di_usage` under the same lock before each analyze call, so two instances can't both pass the cap
**And** the stage emits `di_pages_used_pct`, and at 80% of the cap Dj gets an alert (AD-17)
```
**Rationale:** AD-8 "Page caps"; AD-17 "Alerts"; IR C5.

#### E-55 · Story 2.3 · Tasks

**OLD:**
```text
- Terraform: DI F0 with custom subdomain; role assignments; DI-pages alert.
- Python: DI adapter with rate limiter; `ModelSelector` port; `extract` function; `di_usage` migration.
- Tests: `test_story_2_3_*` with a faked DI for the happy path, reuse on retry, 429, the quota cap and throttling.
```
**NEW:**
```text
- Terraform: the `pipeline` Cognitive Services User assignment and the `di_pages_used_pct` alert in `<env>/app` (the DI resource is in Story 1.1).
- Python: DI adapter with the PostgreSQL-backed rate limiter and page reservation; `ModelSelector` port; `extract` function; bank-field encryption and fingerprinting; migrations for `extraction_run`, `invoice_field`, `invoice_line` and `di_usage`.
- Tests: `test_story_2_3_*` with a faked DI for the happy path, AD-18 field ids, no plaintext bank value in any row, reuse on retry, Re-extract calling DI again, resumed polling after a 429, the quota cap and throttling.
```
**Rationale:** as E-50 to E-54; IR B2, C3.

#### E-56 · Story 2.4 · AC (seed)

**OLD:**
```text
**Then** synthetic POs (lines, unit prices, expected dates), deliveries and goods receipts exist for the loaded suppliers
```
**NEW:**
```text
**Then** synthetic materials, POs (lines with `po_line_id`, `material_id`, `supplier_product_code`, unit price, quantity and expected date), deliveries and goods receipts exist for the loaded suppliers
**And** the seed includes the same material bought from several suppliers, and a PO delivered in parts, so CAP-5, CAP-14 to CAP-17 and partial deliveries can be tested
**And** materials live only in `sim_purchasing`: purchasing owns them, and nothing loads them into `master` (AD-10)
```
**Rationale:** AD-10 "Purchasing owns materials"; AD-11 (`sim_purchasing` holds materials); IR B1, C10 (no `master` materials load).

#### E-57 · Story 2.4 · AC (port)

**OLD:**
```text
**Then** it offers `get_po`, `get_receipts`, `get_delivery`, `list_overdue_pos` and `get_delivery_dates`, reading only `sim_purchasing` through its own database role (AD-10)
**And** the adapter is selected by setting, and no other module imports it
```
**NEW:**
```text
**Then** it offers `get_po`, `get_receipts`, `get_delivery`, `list_overdue_pos` and `get_delivery_dates` (AD-10)
**And** `get_po(po_number)` returns the supplier and the lines, each with `po_line_id`, `material_id`, `material_name`, `supplier_product_code`, `unit_price`, `quantity` and `expected_date`
**And** `get_receipts(po_number)` returns each receipt's `received_date` and the received quantity per `po_line_id`
**And** only `adapters/purchasing_sim/` reads `sim_purchasing`, enforced by an import-linter rule, with no per-adapter database role
**And** the adapter is selected by `PURCHASING_ADAPTER`, and no other module imports it
```
**Rationale:** AD-10 "Purchasing port"; ADV table (2.4); IR B1.

#### E-58 · Story 2.4 · Tasks

**OLD:**
```text
- Python: `sim_purchasing` migration and seed; the port and simulation adapter; DB role grants.
```
**NEW:**
```text
- Python: `sim_purchasing` migration (with `SELECT` for the `pipeline` and `staff-api` logins, AD-11) and seed; the port and simulation adapter; the import-linter contract.
```
**Rationale:** AD-10, AD-11; IR B4.

#### E-59 · Story 2.5 · AC (checks)

**OLD:**
```text
**Given** any extracted field below 0.98 confidence (corrected fields count as 1.0)
**When** it is checked
**Then** `LOW_CONFIDENCE` is recorded with the field ids

**Given** an invoice total that differs from the PO unit price × received quantity, calculated with `Decimal`
**When** it is checked
**Then** `PO_MISMATCH` is recorded with the expected and actual amounts in `detail` (FR5)

**Given** `VendorTaxId` or `VendorName` disagreeing with the supplier master
**When** it is checked
**Then** `SUPPLIER_ID_MISMATCH` is recorded (FR1, P-5)

**Given** one or more reasons
**When** validation completes
**Then** `route_to_admin` writes them all under one `run_id`
```
**NEW:**
```text
**Given** the invoice's current values
**When** any check reads them
**Then** they come from one domain function: the rows of the latest `extraction_run`, overlaid by the `source=admin` rows carrying that `run_id`, with the newest row winning per field or line (AD-18)

**Given** a checked field below 0.98 confidence, or missing (counted as 0):
- `vendor_name`, `invoice_number`, `invoice_date`, `sub_total` and `invoice_total`;
- for every line, `product_code`, `quantity`, `unit_price` and `amount`;
- `purchase_order`, for supplier uploads;
- `vendor_tax_id`, when DI returns it.

**When** it is checked
**Then** `LOW_CONFIDENCE` is recorded with those field ids, and other DI fields and bank fields are never checked for confidence (AD-18; admin corrections count as 1.0)

**Given** the invoice's PO (the extracted `purchase_order`, or the delivery's PO for a goods-in scan)
**When** it is checked under the per-supplier `pg_advisory_xact_lock`
**Then** each line is matched to a PO line by `product_code = supplier_product_code`, filling `po_line_id` and `material_id`
**And** `PO_MISMATCH` is recorded, with the expected and actual amounts in `detail`, when the pre-tax `sub_total` is not within the larger of 1% and 1.00 of the expected amount, in `Decimal` (FR5, AD-19)
**And** the expected amount is the sum, over the matched lines, of the PO unit price × the quantity still to invoice. For a supplier upload, that is the quantity received so far (`get_receipts`) minus the current quantities on other non-rejected invoices matched to the same `po_line_id`. For a goods-in scan, it is the quantity received on that delivery.
**And** a missing or unknown PO, another supplier's PO, an unmatched line, or a PO with no receipt also records `PO_MISMATCH`
**And** the matched PO is saved as the invoice's `po_number`

**Given** the printed supplier
**When** it is checked
**Then** if the invoice has `vendor_tax_id` and the supplier has `tax_id`, the two must be equal after normalising (uppercase, no spaces or punctuation)
**And** otherwise the normalised `vendor_name` (casefolded, with punctuation and legal suffixes such as "Pte Ltd" removed) must reach a rapidfuzz token-set similarity of 85 or more with the supplier's name
**And** a failure records `SUPPLIER_ID_MISMATCH` (FR1, P-5, AD-19)

**Given** one or more reasons
**When** validation completes
**Then** `route_to_admin(invoice_id, reasons, from_status=validating)` writes them all under one new `routing_id`, each item carrying the extraction `run_id` (AD-4, AD-18)
**And** if that transition changes zero rows because another worker finished first, the result is discarded
```
**Rationale:** AD-18 "Current value" and "Checked fields"; AD-19 "PO match" and "Printed supplier"; AD-4 `routing_id`; AD-3 `po_number`. ADV table (2.5), U-3, U-6; IR B1, B3.

#### E-60 · Story 2.5 · Tasks

**OLD:**
```text
- Python: `validate` function framework and the three checks; money helpers.
- Tests: `test_story_2_5_*` for each check alone and combined, `Decimal` rounding, and all passing.
```
**NEW:**
```text
- Python: `validate` function framework; the current-value domain function; the three checks; money helpers.
- Tests: `test_story_2_5_*` for each check alone and combined, the checked-field list, a missing checked field, the tolerance edges, a second invoice against a PO delivered in parts, tax-id vs fuzzy name match, `Decimal` rounding, and all passing.
```
**Rationale:** as E-59.

#### E-61 · Story 2.6 · AC (duplicates and date)

**OLD:**
```text
**Given** an invoice whose fingerprint `(supplier_id, normalised invoice_number, total, invoice_date)` matches another invoice, or whose phash is within Hamming distance 8 of the same supplier's hashes
**When** validation runs under `pg_advisory_xact_lock(supplier_id)`
**Then** `DUPLICATE` is recorded with the matching invoice id, and the invoice never matches itself (AD-9)

**Given** two copies validated at the same time
**When** both run
**Then** exactly one of them is flagged `DUPLICATE`

**Given** a `photo_taken_at` that differs from the invoice delivery date
**When** it is checked
**Then** `DATE_MISMATCH` is recorded
```
**NEW:**
```text
**Given** an invoice whose fingerprint `(supplier_id, normalised invoice_number, invoice_total, invoice_date)` matches, or whose phash is within Hamming distance 8 of, one of the same supplier's invoices that is not `rejected` and comes earlier in `invoice_id` (UUIDv7) order
**When** validation runs under `pg_advisory_xact_lock(supplier_id)`
**Then** `DUPLICATE` is recorded with the matching invoice id, and the invoice never matches itself (AD-9)

**Given** two copies validated at the same time
**When** both run
**Then** exactly one of them, the later in `invoice_id` order, is flagged `DUPLICATE`

**Given** a rejected invoice and a clear resend of it
**When** the resend is validated
**Then** it is not flagged `DUPLICATE` against the rejected one

**Given** a `photo_taken_at` (EXIF `DateTimeOriginal`, Singapore time unless `OffsetTimeOriginal` gives an offset) and the PO's latest goods-received date
**When** it is checked
**Then** `DATE_MISMATCH` is recorded if the photo date is before that goods-received date or more than 30 days after it (AD-19)
**And** with no matched PO or receipt, `PO_MISMATCH` already covers it
```
**Rationale:** AD-9 (earlier, non-rejected invoices only); AD-19 "Photo date". ADV table (2.6), U-12; IR B3.

#### E-62 · Story 2.6 · AC (bank and reminders)

**OLD:**
```text
**Given** extracted bank details
**When** they are normalised and fingerprinted
**Then** the extracted bank fields are stored encrypted and fingerprinted like the master
**And** a fingerprint that differs from the supplier master records `BANK_CHANGED`, and the invoice never auto-posts (FR8, P-7)

**Given** an invoice that has arrived for a PO
**When** validation matches it to the PO
**Then** that PO's row in `supplierreminders` is deleted
```
**NEW:**
```text
**Given** extracted bank fields, already encrypted and fingerprinted by the `extract` stage (Story 2.3)
**When** they are checked
**Then** each is compared by fingerprint with the supplier's `master.supplier_bank` value for the same field id, and nothing is decrypted
**And** a field whose fingerprint differs, or for which the supplier has no value on file, records `BANK_CHANGED`, and the invoice never auto-posts (FR8, P-7, AD-19)

**Given** an invoice matched to a PO
**When** validation completes
**Then** the `supplierreminders` row with `PartitionKey=supplier_id` and `RowKey=po_number` is deleted (AD-6)
```
**Rationale:** AD-11 (encryption at the first write, field-by-field comparison); AD-19 "Bank details"; AD-6 "Reminders" (entity keys). ADV table (2.3 vs 2.6), U-1, U-15; IR B1, C3.

#### E-63 · Story 2.6 · Tasks

**OLD:**
```text
- Python: fingerprint and phash checks; date check; bank fingerprint check; encryption of extracted bank fields; reminder-row cleanup.
- Tests: `test_story_2_6_*` including the concurrent-duplicate race, self-match exclusion, missing photo date, and bank normalisation (spaces, hyphens, case).
```
**NEW:**
```text
- Python: fingerprint and phash checks; date check; bank fingerprint check per field id; reminder-row cleanup.
- Tests: `test_story_2_6_*` including the concurrent-duplicate race, self-match and rejected-invoice exclusion, the 0-day and 30-day date edges, EXIF offsets, missing photo date, a SWIFT code never compared with an account number, a bank field missing from the master, and bank normalisation (spaces, hyphens, case).
```
**Rationale:** Encryption moves to Story 2.3 (IR C3); AD-19.

#### E-64 · Story 2.7 · AC (sign-in and sidebar)

**OLD:**
```text
**Then** built-in auth redirects them to Entra login and sets a `SameSite=Lax` session cookie
**And** the sidebar shows only their role's surfaces
```
**NEW:**
```text
**Then** built-in auth redirects them to Entra login (ID tokens only, no client secret) and sets a `SameSite=Lax` session cookie (AD-14)
**And** the sidebar shows only the surfaces of their roles, the combined set for a user with several roles
```
**Rationale:** AD-14 "Staff sign-in"; IR C8 (combined sidebar).

#### E-65 · Story 2.7 · AC (waking up)

**OLD:**
```text
**Then** the full-page offline notice with working hours shows (UX-DR20)
```
**NEW:**
```text
**Then** the full-page offline notice with working hours shows (UX-DR20)

**Given** `staff-api` has scaled to zero
**When** the staff app loads
**Then** skeleton rows show, and after 3 s "Waking up, one moment…" (UX-DR20)
```
**Rationale:** EXP State Patterns "App waking up" (both surfaces); IR C8.

#### E-66 · Story 2.7 · Tasks (Terraform)

**OLD:**
```text
- Terraform: app registration, app roles, built-in auth on `staff-api`.
```
**NEW:**
```text
- Terraform: built-in auth on `staff-api` in `<env>/app`, pointing at the `staff-api` app registration created by the bootstrap (Story 1.1), with ID-token login and no client secret.
- Operator: register the redirect URI `https://<staff-api host>/.auth/login/aad/callback` on the app registration once the app exists (AD-17 step 8, bootstrap README).
```
**Rationale:** AD-17 steps 1, 7 and 8; AD-14; IR B5 (the deploy identity has no directory rights).

#### E-67 · Story 2.8 · AC (open reasons)

**OLD:**
```text
**Then** a table shows received, supplier, amount, reason chips (with labels, not codes) and age, sorted oldest first and paginated at 50 (UX-DR9)
```
**NEW:**
```text
**Then** a table shows received, supplier, amount, reason chips (with labels, not codes) and age, sorted oldest first and paginated at 50 (UX-DR9)
**And** the reason chips are the invoice's open reasons: the `admin_item` rows of its latest `routing_id` only (AD-4)
```
**Rationale:** AD-4 "Open reasons"; ADV U-3.

#### E-68 · Story 2.9 · AC (field list)

**OLD:**
```text
**Then** each field shows its value, a confidence badge below 98% (announced as "Confidence 91%") and its flag state
```
**NEW:**
```text
**Then** each field shows its current value (the AD-18 current-value rule), a confidence badge below 98% (announced as "Confidence 91%") and its flag state; the flagged fields are the `field_ids` of the open reasons
**And** flag boxes and crops are drawn from each row's `page` and `polygon`
```
**Rationale:** AD-18 "Current value", `polygon`; AD-4; IR B2.

#### E-69 · Story 2.9 · AC (bank-change panel)

**OLD:**
```text
**Then** the bank-change panel shows the supplier's phone number on file and the old and new accounts masked ("account ending 4821") (UX-DR13)
```
**NEW:**
```text
**Then** the bank-change panel shows the supplier's phone number on file and, for each changed bank field, the value on file (or that none is on file) and the new value, masked ("account ending 4821") (UX-DR13, AD-19)
```
**Rationale:** AD-19 "Bank details" (per field id, or no value on file); ADV U-1. The copy follows D-5.

#### E-70 · Story 2.10 · AC (allowed actions)

**OLD:**
```text
**Then** only the actions allowed by the reasons table and the multi-reason rule show (UX-DR12):
- Correct if any reason allows it;
- Re-extract only if every reason allows it;
- Reject always.
```
**NEW:**
```text
**Then** only the actions allowed by the reasons table and the multi-reason rule for the invoice's open reasons (latest `routing_id`) show, and the server applies the same guard (UX-DR12, AD-4):
- Correct if any reason allows it;
- Re-extract only if every reason allows it;
- Retry intake only for `PROCESSING_FAILED` when the quality stage never completed;
- Reject always, unless the invoice has an `accounts_ref`.
```
**Rationale:** AD-3 "Admin actions"; AD-4 "Open reasons"; ADV U-3, U-5, U-13.

#### E-71 · Story 2.10 · AC (Correct)

**OLD:**
```text
**Then** the corrected values are saved with `source=admin` and confidence 1.0
**And** the raw correction is written as JSON to the `corrections` container, with no bank plaintext (FR10, AD-15)
**And** the invoice moves to `awaiting_validation`, `q-validate` is enqueued, and the Toast "Sent for re-check" shows
**And** bank fields are never editable
```
**NEW:**
```text
**Then** the corrected values are saved as new `source=admin` rows with confidence 1.0, carrying the latest `run_id` and never updating a DI row; a corrected line is written as a complete line row, copying every uncorrected column (AD-18)
**And** those rows and the move to `awaiting_validation` are one transaction
**And** after the commit, `q-validate` is enqueued, the raw correction is written as JSON to the `corrections` container with no bank plaintext (FR10, AD-15), and the Toast "Sent for re-check" shows
**And** bank fields are never editable

**Given** unsaved Correct edits when an API call returns 401
**When** the admin signs in again from the session-expired dialog
**Then** the unsaved edits are restored (UX-DR20)
```
**Rationale:** AD-3 "Correct"; AD-18 "Current value"; EXP State Patterns "Session expired". ADV U-2; IR B2, C8.

#### E-72 · Story 2.10 · AC (returned after correction)

**OLD:**
```text
**Then** it is marked "Returned after correction" with its new reasons
```
**NEW:**
```text
**Then** it is marked "Returned after correction", showing only the reasons of its latest routing (AD-4)
```
**Rationale:** AD-4 "Open reasons"; ADV U-3.

#### E-73 · Story 2.10 · AC (Retry intake)

**OLD:**
```text
**Given** **Re-extract**, allowed only for `EXTRACTION_QUOTA` and `PROCESSING_FAILED`
**When** the admin uses it
**Then** the invoice moves to `awaiting_extraction` and `q-extract` is enqueued
```
**NEW:**
```text
**Given** **Re-extract**, allowed only for `EXTRACTION_QUOTA` and `PROCESSING_FAILED`
**When** the admin uses it
**Then** the invoice moves to `awaiting_extraction` and `q-extract` is enqueued

**Given** `PROCESSING_FAILED` on an invoice whose quality stage never completed (no `image_hash` row and no `photo_taken_at` decision)
**When** the admin uses **Retry intake**
**Then** the invoice moves to `received` and `q-quality` is enqueued, so it goes through the full quality stage (AD-3)
```
**Rationale:** AD-3 "Retry intake"; ADV U-13. The presentation follows D-3.

#### E-74 · Story 2.10 · AC (Reject guard)

**OLD:**
```text
**Then** the invoice moves to `rejected` and the reason is audited
```
**NEW:**
```text
**Then** the invoice moves to `rejected` and the reason is audited
**And** Reject is refused, and not offered, once the invoice has an `accounts_ref`; such an invoice can only be Approved, which re-posts it idempotently (AD-3)
```
**Rationale:** AD-3 "Reject"; ADV U-5.

#### E-75 · Story 2.10 · Tasks (tests)

**OLD:**
```text
- Tests: `test_story_2_10_*` for each action, the multi-reason matrix, the concurrent-admin race, and that corrections hold no bank plaintext.
```
**NEW:**
```text
- Tests: `test_story_2_10_*` for each action including Retry intake, the multi-reason matrix on open reasons only, Reject refused once `accounts_ref` exists, a complete corrected line row, the concurrent-admin race, edits restored after a 401, and that corrections hold no bank plaintext.
```
**Rationale:** as E-70 to E-74.

#### E-76 · Story 2.11 · AC (setting and `a` key)

**OLD:**
```text
**Given** the per-user setting is on
**When** the admin presses keys
**Then** `j`/`k` move between rows and `Enter` opens an item in the queue
**And** in an item, `c`, `a` (available once Approve exists) and `r` open the same dialogs as the buttons, and `n`/`p` step through flagged regions
```
**NEW:**
```text
**Given** the setting is on in this browser
**When** the admin presses keys
**Then** `j`/`k` move between rows and `Enter` opens an item in the queue
**And** in an item, `c` and `r` open the same dialogs as the buttons, and `n`/`p` step through flagged regions (`a` for Approve is added by Story 3.3)
```
**Rationale:** AD-14 (`localStorage`, no server profile); ADV table (2.11); IR C7 (the `a` shortcut depends on Story 3.3).

#### E-77 · Story 2.11 · Tasks

**OLD:**
```text
- Python: per-user setting stored with the user profile.
```
**NEW:**
```text
- React: the setting is stored in the browser's `localStorage` and falls back to off when storage is unavailable; the server keeps no user profile (AD-14).
```
**Rationale:** AD-14; ADV table (2.11); IR B2 (per-user settings had no table).

### 4.4 epics.md: Epic 3 stories

#### E-78 · Story 3.1 · AC (auth and contract)

**OLD:**
```text
**Given** the `accounts-sim` app with built-in auth
**When** it is called with a managed-identity token over TLS
**Then** `POST /api/invoices` accepts an invoice XML document, validates it against the agreed schema, stores it in `sim_accounts` and returns an `accounts_ref` (AD-10, P-6)
```
**NEW:**
```text
**Given** the `accounts-sim` app with built-in auth on its own app registration (created by the bootstrap, Story 1.1), accepting only its own environment's `pipeline` identity through `allowedPrincipals.identities`
**When** it is called with that identity's managed-identity token over TLS
**Then** `POST /api/invoices` accepts an invoice XML document, validates it against `adapters/accounts_xml/invoice-v1.xsd` (the contract), stores it in `sim_accounts` and returns an `accounts_ref` (AD-10, P-6)
```
**Rationale:** AD-10 "Accounts port"; AD-17 step 1. ADV U-9; IR C9 (XSD contract).

#### E-79 · Story 3.1 · AC (refused callers)

**OLD:**
```text
**Given** an unauthenticated call
**When** it arrives
**Then** it gets 401
```
**NEW:**
```text
**Given** an unauthenticated call
**When** it arrives
**Then** it gets 401

**Given** a signed-in human user, or any identity other than its own environment's `pipeline` (including the other environment's)
**When** it calls `accounts-sim`
**Then** the call is refused
```
**Rationale:** AD-10 ("refuses human users"); ADV U-9.

#### E-80 · Story 3.1 · Tasks

**OLD:**
```text
- Terraform: built-in auth on `accounts-sim`; role for the `pipeline` identity.
- Python: `sim_accounts` migration, XML schema, endpoint, failure mode.
```
**NEW:**
```text
- Terraform: built-in auth on `accounts-sim` in `<env>/app`, with `allowedPrincipals.identities` set to the environment's `pipeline` identity.
- Python: `sim_accounts` migration (read/write for the `accounts-sim` login only, AD-11), `invoice-v1.xsd` in `adapters/accounts_xml/`, endpoint, failure mode.
```
**Rationale:** AD-10, AD-11, AD-17 runtime roles (`accounts-sim` has none); IR B4, C9.

#### E-81 · Story 3.2 · AC (claim and save)

**OLD:**
```text
**Then** it claims `ready_to_post → posting` and calls `AccountsPort.post_invoice`, where only the adapter builds the XML
**And** it saves `accounts_ref` under `invoice_id` before moving to `posted` (AD-3, AD-10)
```
**NEW:**
```text
**Then** it claims `ready_to_post → posting` only when `next_attempt_at` is empty or past, and calls `AccountsPort.post_invoice`, where only the one adapter `adapters/accounts_xml/` builds the XML, valid against `invoice-v1.xsd`
**And** it saves `accounts_ref` under `invoice_id` before moving to `posted`, and `posted_at` equals the `at` of that `status_history` row (AD-3, AD-10)

**Given** a `q-post` message that arrives before `next_attempt_at`
**When** the stage runs
**Then** it re-enqueues the message with the remaining delay
```
**Rationale:** AD-3 "Posting backoff", "The invoice row"; AD-10 (one adapter). ADV U-4; IR C9 (one accounts adapter).

#### E-82 · Story 3.2 · AC (failures and setting)

**OLD:**
```text
**Then** the adapter doesn't retry; the stage re-enqueues with delays of 1, 5, 15 and 60 minutes, carrying `attempt`
**And** on the 5th failure it calls `route_to_admin(ACCOUNTS_API_ERROR)` with the API error in `detail`, never reaching the poison queue

**Given** the simulation adapter is selected by `ACCOUNTS_ADAPTER=sim`
```
**NEW:**
```text
**Then** the adapter doesn't retry. In one transaction, the stage moves the invoice `posting → ready_to_post`, increments `post_failures`, sets `next_attempt_at` 1, 5, 15 or 60 minutes ahead and releases the lease; it then re-enqueues with that delay (AD-3)
**And** on the 5th failure, decided from `post_failures` and never from `QueueMessage.attempt`, it calls `route_to_admin(ACCOUNTS_API_ERROR)` with the API error in `detail`, never reaching the poison queue
**And** `post_failures` resets when the invoice enters `ready_to_post` from `validating` or `in_admin_queue`

**Given** `ACCOUNTS_BASE_URL` points at this environment's `accounts-sim`
```
**Rationale:** AD-3 "Posting backoff"; AD-10 ("changes only `ACCOUNTS_BASE_URL` and the auth settings"). ADV table (3.2), U-4.

#### E-83 · Story 3.2 · Tasks

**OLD:**
```text
- Python: `AccountsPort`, XML adapter, `post` function with backoff.
- Tests: `test_story_3_2_*` end to end from upload to posted, retries into `ACCOUNTS_API_ERROR`, and reuse of the saved `accounts_ref`.
```
**NEW:**
```text
- Python: `AccountsPort`, the one `adapters/accounts_xml/` adapter, `post` function with the `post_failures` backoff.
- Tests: `test_story_3_2_*` end to end from upload to posted, retries into `ACCOUNTS_API_ERROR`, a lost delayed message recovered by the sweeper without resetting the count, an early message re-delayed, and reuse of the saved `accounts_ref`.
```
**Rationale:** as E-81 and E-82.

#### E-84 · Story 3.3 · AC (open reasons and `a` shortcut)

**OLD:**
```text
**Given** a mix of reasons where one doesn't allow Approve
**When** the actions render
**Then** Approve is not offered
```
**NEW:**
```text
**Given** a mix of open reasons (latest `routing_id`) where one doesn't allow Approve
**When** the actions render
**Then** Approve is not offered, and the server refuses it too (AD-4)

**Given** single-key shortcuts are on (Story 2.11)
**When** the admin presses `a` in an item where Approve is offered
**Then** the Approve dialog opens, the same as the button
```
**Rationale:** AD-4 "Open reasons"; IR C7 (`a` shortcut after Story 3.3).

#### E-85 · Story 3.4 · AC (detail)

**OLD:**
```text
**Then** it shows the extracted fields, the status history and the accounts reference
```
**NEW:**
```text
**Then** it shows the current extracted field values (AD-18), the status history from `intake.status_history` and the accounts reference
```
**Rationale:** AD-3, AD-18; IR B2 (status history had no table).

### 4.5 epics.md: Epic 4 stories

#### E-86 · Story 4.1 · AC (goods-in send)

**OLD:**
```text
**Given** a delivery is chosen and a photo passes the on-device check (the Story 1.9 module)
**When** they tap **Send**
**Then** `staff-api` looks up the supplier with `PurchasingPort.get_delivery(delivery_id)` and writes the blob with `source=goods_in`, `delivery_id` and the supplier, then enqueues `q-quality` (AD-5)
```
**NEW:**
```text
**Given** a delivery is chosen and a photo passes the on-device check (the shared quality-check module from Story 1.9, with `shared/quality-thresholds.json`)
**When** they tap **Send**
**Then** `staff-api` looks up the supplier with `PurchasingPort.get_delivery(delivery_id)` and writes the blob with `source=goods_in`, `delivery_id` and the supplier, then enqueues `q-quality` (AD-5)
**And** it follows the AD-6 `Idempotency-Key` order (the key in `uploadkeys`, then the blob if missing, then the enqueue), so a retry never creates a second invoice
```
**Rationale:** AD-6 ("Goods-in uploads through `staff-api` follow the same rule"); IR C7 (shared module).

#### E-87 · Story 4.2 · AC (overdue job)

**OLD:**
```text
**Given** the weekday timers (01:30, 04:30 and 08:30 UTC)
**When** the first run of the day finds the database up
**Then** the overdue job computes, from `PurchasingPort.list_overdue_pos` and the received invoices, every PO overdue since the day after its expected date
**And** it catches up from its last successful run, so no PO is missed (AD-13)
```
**NEW:**
```text
**Given** the weekday timers (01:30, 04:30 and 08:30 UTC)
**When** the first run of the day finds the database up
**Then** the analytics refresh job, created here as the only writer of `analytics` (AD-13), writes `analytics.overdue_po` from `PurchasingPort.list_overdue_pos`
**And** a PO is overdue when its earliest line `expected_date` is before today (Singapore date) and no invoice that is not `rejected` has it as its current `po_number` (AD-19); unlike AD-20, "invoiced" here does not wait for posting
**And** a PO expected at the weekend appears on Monday's list, and the list is computed from the last successful run, so no PO is missed
```
**Rationale:** AD-13 "Overdue list"; AD-11 (`analytics` written only by the refresh job). ADV U-15; IR B1, B2 (overdue table owner).

#### E-88 · Story 4.2 · Note

**OLD:**
```text
**Note:** whether the list is made daily or on weekdays only is still open (spec memlog). Decide it before building this story.
```
**NEW:**
```text
(delete)
```
**Rationale:** Dj decided on weekdays (IR "Decisions taken", B7; AD-13). ADV table (4.2).

#### E-89 · Story 4.2 · Tasks

**OLD:**
```text
- Python: overdue job and table; list API.
```
**NEW:**
```text
- Python: `analytics` schema migration (read/write for `pipeline`, read for `staff-api`, AD-11); the refresh job timer with its once-a-day guard; `analytics.overdue_po`; list API.
```
**Rationale:** AD-11, AD-13; IR B2, B4.

#### E-90 · Story 4.3 · AC (weekly write)

**OLD:**
```text
**When** the reminder job runs at the first successful run of each ISO week
**Then** it writes one row per overdue PO to `supplierreminders` (AD-6, AD-13)
```
**NEW:**
```text
**When** the analytics refresh job reaches its first successful run of each ISO week
**Then** it replaces the supplier's partition in `supplierreminders` (`PartitionKey=supplier_id`, `RowKey=po_number`) with one row per overdue PO (AD-6, AD-13)
**And** it re-checks each PO against `intake` just before writing its row, so a delete by `validate` is not undone
```
**Rationale:** AD-13 "Supplier reminders"; AD-6 "Reminders"; ADV U-15.

#### E-91 · Story 4.3 · Tasks

**OLD:**
```text
- Python: reminder job; `GET /api/reminders` in `supplier-api`, reading from the table.
```
**NEW:**
```text
- Python: the weekly reminder step in the refresh job; `GET /api/reminders` in `supplier-api`, reading the supplier's partition identified by the `X-Upload-Token`.
```
**Rationale:** AD-6, AD-13.

#### E-92 · Story 4.4 → new must-have Story 4.4, could-have renumbered 4.5 · Header and first AC

**OLD:**
```text
### Story 4.4: Supplier page with delivery dates (could-have)

As a procurement user (Wei Ling),
I want to see each delivery's promised, invoiced and received dates,
So that I know where delays come from.

**Acceptance Criteria:**

**Given** a procurement, finance or management user
**When** they open Suppliers and choose a supplier
**Then** a supplier page opens, with a Deliveries tab
```
**NEW:**
```text
### Story 4.4: Suppliers list and supplier page

As a procurement user (Wei Ling),
I want to find a supplier and open its page,
So that the scorecard and the delivery dates have one place to live.

**Acceptance Criteria:**

**Given** a procurement, finance or management user
**When** they open Suppliers
**Then** the suppliers from `master` show in a table paginated at 50, with a search by supplier name (Flow 5)
**And** Suppliers is procurement's landing page (UX-DR8)

**Given** a supplier is chosen
**When** its page opens
**Then** a supplier page shell opens, with a tab area for the Scorecard (Story 5.5) and, when built, Deliveries (Story 4.5)

**Given** any other role
**When** it calls the suppliers API
**Then** the request is refused

**Tasks:**
- Python: suppliers list and search API (reads `master.supplier`, no bank columns).
- React: Suppliers list with search, supplier page shell.
- Tests: `test_story_4_4_*` for search, paging and role enforcement.

### Story 4.5: Delivery dates on the supplier page (could-have)

As a procurement user (Wei Ling),
I want to see each delivery's promised, invoiced and received dates,
So that I know where delays come from.

**Acceptance Criteria:**

**Given** a procurement, finance or management user on a supplier page (Story 4.4)
**When** they open the Deliveries tab
**Then** it lists that supplier's deliveries
```
**Rationale:** IR B8 (the must-have Suppliers surface, EXP IA, must not depend on could-have CAP-19); IR C8 (supplier search in Flow 5 had no story). Story 5.5's "(from Story 4.4)" now points at a must-have story and needs no edit. The approach follows D-4.

#### E-93 · Story 4.5 (formerly 4.4) · Tasks

**OLD:**
```text
- Python: suppliers list API; delivery dates API via `PurchasingPort.get_delivery_dates`.
- React: Suppliers list, supplier page shell, Deliveries tab.
- Tests: `test_story_4_4_*` for the gap calculations.
```
**NEW:**
```text
- Python: delivery dates API via `PurchasingPort.get_delivery_dates`.
- React: Deliveries tab.
- Tests: `test_story_4_5_*` for the gap calculations.
```
**Rationale:** The list and shell moved to Story 4.4 (E-92).

### 4.6 epics.md: Epic 5 stories

#### E-94 · Story 5.1 · AC (refresh)

**OLD:**
```text
**Given** the `analytics` schema migration
**When** the refresh job runs at the first successful weekday run
**Then** it updates the summary tables incrementally from a `posted_at` watermark: unit prices per supplier and material, on-time rates, monthly spend, and flagged and duplicate counts (AD-13, P-10)
**And** it is the only writer of `analytics.*`
```
**NEW:**
```text
**Given** the analytics refresh job from Story 4.2
**When** it runs at the first successful weekday run
**Then** it updates the summary tables per AD-20 (AD-13, P-10):
- unit prices per supplier and material, from posted invoice lines read through the AD-18 current-value rule, by `material_id`, in SGD;
- on-time rates;
- monthly spend;
- flagged and duplicate counts per supplier and month;
- the monthly straight-through share: posted invoices whose `status_history` never includes `in_admin_queue`, divided by all posted invoices.

**And** it reprocesses from its `posted_at` watermark minus 1 hour, idempotently by `invoice_id`, so a late commit is never skipped
**And** it recomputes lateness and on-time rates in full over the last 365 days: for each goods receipt, `received_date` minus the PO line's `expected_date`, on time when that is 0 or less
**And** its migration adds `analytics.alert` with `emailed_at`, used by Stories 5.2 to 5.4
**And** it is the only writer of `analytics.*`
```
**Rationale:** AD-20 "Inputs", "Lateness", "Straight-through share", "Flagged and duplicate counts"; AD-13. ADV U-16; IR B3, C7 (5.2 needs alert rows), C9 (straight-through share).

#### E-95 · Story 5.1 · Tasks

**OLD:**
```text
- Python: `analytics` migration; refresh job; read-only dashboard repository.
- Tests: `test_story_5_1_*` for incremental refresh, catch-up and idempotency.
```
**NEW:**
```text
- Python: summary-table and `analytics.alert` migrations; the summary steps in the refresh job; read-only dashboard repository.
- Tests: `test_story_5_1_*` for incremental refresh, catch-up, idempotency, the trailing window, a corrected line counted once, lateness, and the straight-through share.
```
**Rationale:** As E-94. The schema and job now come from Story 4.2.

#### E-96 · Story 5.2 · AC (ACS, throttle, emailed_at)

**OLD:**
```text
**Given** ACS Email with a verified custom domain owned by Dj
**When** Terraform applies
**Then** the email resource and domain are configured, and the `pipeline` identity can send mail (AD-16)

**Given** an alert raised in `analytics.alert`
**When** the email adapter sends it
**Then** it goes only through `EmailPort`, throttled to 30 per minute and 100 per hour across both environments
**And** it uses the defined subject and a deep link, and never includes bank details or link tokens (UX-DR23)

**Given** an alert already emailed
**When** the refresh runs again
**Then** it is not sent twice
```
**NEW:**
```text
**Given** ACS Email with a verified custom domain owned by Dj (in `shared/foundation`, Story 1.1)
**When** `<env>/app` applies
**Then** the `pipeline` identity holds the custom `ACS Email Sender` role on ACS and can send mail (AD-16, AD-17)
**And** recipients come from the per-environment, per-role setting `ALERT_RECIPIENTS_<ROLE>`

**Given** a row in `analytics.alert` whose `emailed_at` is empty (from a test fixture until Stories 5.3 and 5.4 raise real alerts)
**When** the email adapter sends it
**Then** it goes only through `EmailPort`, throttled per environment with no shared state: Dev at most 5 a minute and 20 an hour, Prod at most 25 a minute and 80 an hour (AD-16)
**And** it uses the defined subject and a deep link, and never includes bank details or link tokens (UX-DR23)
**And** `emailed_at` is set once it is sent

**Given** an alert already emailed
**When** the refresh runs again
**Then** it is not sent twice, and an alert that was throttled or interrupted before sending is sent at a later run
```
**Rationale:** AD-16; AD-17 steps 1–3 and 7; AD-20 (`emailed_at`). ADV table (5.2), U-16; IR C6 (recipients, throttle state), C7.

#### E-97 · Story 5.2 · Tasks (Terraform)

**OLD:**
```text
- Terraform: ACS Email, domain verification records.
```
**NEW:**
```text
- Terraform: the `ACS Email Sender` assignment for `pipeline` in `<env>/app` (ACS and the domain are in Story 1.1).
```
**Rationale:** AD-17 steps 2 and 7.

#### E-98 · Story 5.3 · AC (price rise, alerts on page, no data)

**OLD:**
```text
**Given** a supplier's unit price that rises against its own recent invoices
**When** the refresh runs
**Then** a price-rise alert names the supplier, the material and the invoices, and is emailed to finance and procurement: "Price rise: {supplier}, {material} +{n}%"
```
**NEW:**
```text
**Given** a posted unit price more than 2% above the same supplier's previous posted price for that material, where "previous" is ordered by `invoice_date`, then `invoice_id` (AD-20)
**When** the refresh runs
**Then** one price-rise alert is stored in `analytics.alert`, naming the supplier, the material and the invoices, and is emailed to finance and procurement: "Price rise: {supplier}, {material} +{n}%"
**And** each rise counts once toward the watchlist (Story 5.4)

**Given** price-rise alerts for a material
**When** Price comparison opens for it
**Then** the alerts show on the page with their evidence list, whose rows link to the invoice for admin and finance and are read-only for other roles

**Given** no posted invoices for the period
**When** Price comparison opens
**Then** it shows "No posted invoices yet for this period."
```
**Rationale:** AD-20 "Price rise"; EXP IA (Price comparison "plus price-rise alerts"), Evidence list, "No data yet". IR B3, C8.

#### E-99 · Story 5.4 · AC (rules)

**OLD:**
```text
**Given** a supplier with 3 or more price increases within a year, an average of 7 or more days late, or prices 5% or more above the cheapest supplier of the same material
```
**NEW:**
```text
**Given** a supplier with 3 or more price rises (Story 5.3) in the last 365 days, an average of 7 or more days late over the last 365 days (AD-20 lateness), or a latest price 5% or more above the lowest latest price for the same material among suppliers who posted in the last 90 days
```
**Rationale:** AD-20 "Watchlist"; IR B3.

#### E-100 · Story 5.4 · AC (evidence, alternatives, no data)

**OLD:**
```text
**Then** it shows the evidence list, and below it the alternatives already invoicing the same materials, ranked by price then on-time rate (FR16)
```
**NEW:**
```text
**Then** it shows the evidence list, whose rows link to the invoice for admin and finance and are read-only for other roles
**And** below it, the alternatives: other suppliers with a posted price for the same material in the last 90 days, ranked by latest price, then by on-time rate (FR16, AD-20)

**Given** no posted invoices for the period
**When** Watchlist opens
**Then** it shows "No posted invoices yet for this period."
```
**Rationale:** AD-20 "Alternatives"; EXP Evidence list, "No data yet". IR C8.

#### E-101 · Story 5.5 · AC (scorecard)

**OLD:**
```text
**Then** it shows the on-time rate and the price trend per material, derived from posted invoices through `analytics.*` (FR17)
**And** its charts follow the Chart pattern
```
**NEW:**
```text
**Then** it shows the on-time rate (on-time goods receipts divided by all receipts, AD-20) and the price trend per material from posted invoices, read through `analytics.*` (FR17)
**And** its charts follow the Chart pattern

**Given** no posted invoices for the period
**When** the Scorecard tab opens
**Then** it shows "No posted invoices yet for this period."
```
**Rationale:** AD-20 "Lateness"; EXP "No data yet". IR B3, C8.

#### E-102 · Story 5.6 · AC (straight-through share)

**OLD:**
```text
**And** the header shows the share of invoices posted without an admin against the 90% target (NFR19)
```
**NEW:**
```text
**And** the header shows the share of invoices posted without an admin against the 90% target (NFR19), read from the monthly straight-through share that Story 5.1 computes
```
**Rationale:** AD-20 "Straight-through share"; IR C9.

### 4.7 SPEC.md

#### S-01 · CAP-1 · success

**OLD:**
```text
  - **success:** An upload via supplier A's link is recorded as supplier A regardless of the supplier ID printed on the invoice; the supplier has no way to edit extracted data. Links are issued and revoked automatically.
```
**NEW:**
```text
  - **success:** An upload via supplier A's link is recorded as supplier A regardless of the supplier ID printed on the invoice; the supplier has no way to edit extracted data. Links are issued and revoked by an operator-run supplier load script: `--replace-link` revokes a supplier's link and issues a new one, and `--revoke` revokes it without issuing another. Each new link is printed once, for Dj to send to the supplier. This departs from P-8 ("issued and revoked automatically"), as Dj accepted (AD-6).
```
**Rationale:** AD-6 "Links"; IR C1.

#### S-02 · CAP-3 · success

**OLD:**
```text
  - **success:** A blurred, dark or cropped photo is refused before submission with a retake prompt; a clear photo is accepted. After 2 refusals the supplier may send it anyway, and it is checked by hand in the admin queue.
```
**NEW:**
```text
  - **success:** A blurred, dark or cropped photo is refused before submission with a retake prompt; a clear photo is accepted. After 2 refusals the supplier may send it anyway; the server re-checks it with the same thresholds, processes it normally if it passes, and sends it to the admin queue if it fails.
```
**Rationale:** AD-6 "Checks"; IR C1 (there is no reason code for an overridden upload that passes).

#### S-03 · CAP-4 · success

**OLD:**
```text
  - **success:** An invoice in a layout never seen before is extracted without per-supplier setup; each field carries a confidence score, and any field below 98% sends the invoice to the admin queue.
```
**NEW:**
```text
  - **success:** An invoice in a layout never seen before is extracted without per-supplier setup; each field carries a confidence score, and any checked field below 98% sends the invoice to the admin queue. The checked fields are the supplier name, invoice number, invoice date, sub-total and total; each line's product code, quantity, unit price and amount; the PO number on supplier uploads; and the supplier tax ID when it is printed. Other fields are stored but not checked (AD-18).
```
**Rationale:** AD-18 "Checked fields" (P-9 departure); IR B3, C1.

#### S-04 · CAP-5 · success

**OLD:**
```text
  - **success:** An invoice whose amount differs from PO price × received quantity lands in the admin queue, not the accounts system.
```
**NEW:**
```text
  - **success:** An invoice whose pre-tax amount differs from PO price × the received quantity not yet invoiced, by more than the larger of 1% and 1.00, lands in the admin queue, not the accounts system (AD-19).
```
**Rationale:** AD-19 "PO match"; IR B1.

#### S-05 · CAP-7 · intent and success

**OLD:**
```text
  - **intent:** The photo-taken date is checked against the invoice delivery date.
  - **success:** A mismatch lands in the admin queue; the supplier is not notified. A PDF or scan with no photo-taken date also lands in the admin queue as an exception.
```
**NEW:**
```text
  - **intent:** The photo-taken date is checked against the PO's latest goods-received date.
  - **success:** A photo taken before the goods were received, or more than 30 days after, lands in the admin queue; the supplier is not notified. A PDF or scan with no photo-taken date also lands in the admin queue as an exception.
```
**Rationale:** AD-19 "Photo date"; IR B3, C1 (CAP-7).

#### S-06 · CAP-10 · success

**OLD:**
```text
  - **success:** A field corrected on a supplier's invoice is extracted correctly on that supplier's next invoice of the same format.
```
**NEW:**
```text
  - **success:** Every admin correction is stored for learning (for 30 days, P-11), behind a model-selection seam. Training custom models from the corrections is deferred (architecture Deferred, Q10b); until it is built, a corrected field is not guaranteed to read correctly on the supplier's next invoice.
```
**Rationale:** Spine Deferred (CAP-10), AD-8, AD-15; E FR10; IR C1 (CAP-10).

#### S-07 · CAP-12 · intent and success

**OLD:**
```text
  - **intent:** A daily overdue list shows POs past their expected date with no invoice received, grouped by supplier.
  - **success:** A PO expected 7 Jan with no invoice appears on the 8 Jan list under its supplier.
```
**NEW:**
```text
  - **intent:** An overdue list, made each weekday, shows POs past their expected date with no invoice received, grouped by supplier.
  - **success:** A PO expected 7 Jan with no invoice appears on the next weekday's list (8 Jan, when that is a weekday) under its supplier.
```
**Rationale:** AD-13 "Overdue list"; IR B7 (Dj's decision), C1 (CAP-12 "each weekday").

#### S-08 · Constraints · confidence threshold

**OLD:**
```text
- OCR confidence threshold is 98% per field; below it, the invoice goes to the admin queue.
```
**NEW:**
```text
- OCR confidence threshold is 98% per checked field (CAP-4); below it, the invoice goes to the admin queue.
```
**Rationale:** AD-18; keeps the constraint consistent with S-03.

### 4.8 EXPERIENCE.md

#### X-01 · Information Architecture · Supplier upload page table

**OLD:**
```text
| Upload home | The personal link `…/u/<token>` | Shows who the upload is for, any reminders, and the Take photo / Choose file actions |
```
**NEW:**
```text
| Upload home | The personal link `…/u#<token>` (the token sits in the URL fragment, which never reaches the server; AD-6) | Shows who the upload is for, any reminders, and the Take photo / Choose file actions |
```
**Rationale:** AD-6 "Links"; ADV table (1.7); IR C4.

#### X-02 · Information Architecture · Suppliers row

**OLD:**
```text
| Suppliers | procurement, finance, management | Sidebar; procurement's landing page | Supplier list |
```
**NEW:**
```text
| Suppliers | procurement, finance, management | Sidebar; procurement's landing page | Supplier list, with a search by supplier name (Flow 5) |
```
**Rationale:** Flow 5 step 1; IR C8. Pairs with E-92.

#### X-03 · Information Architecture · Not a surface: supplier master

**OLD:**
```text
- **Not a surface: supplier master.** There is no supplier admin screen (Dj's decision). An operator-run script loads suppliers through the application code (AD-11). It prints each new link once for Dj to send to the supplier on WhatsApp or SMS, and re-running it for a supplier replaces the link (AD-6).
```
**NEW:**
```text
- **Not a surface: supplier master.** There is no supplier admin screen (Dj's decision). An operator-run script loads suppliers through the application code (AD-11). It prints each new link once for Dj to send to the supplier on WhatsApp or SMS. `--replace-link` revokes a supplier's link and issues a new one, and `--revoke` revokes it without issuing another (AD-6). This departs from P-8, as Dj accepted.
```
**Rationale:** AD-6; IR C1 (there was no way to revoke without re-issuing).

#### X-04 · Component Patterns · Quality check

**OLD:**
```text
After 2 failures on the same upload, a secondary option appears: **Send it anyway. Babaloo will look at it by hand.** It sends the photo marked as overridden, and the supplier sees the normal Received screen (Dj's decision, for accessibility).
```
**NEW:**
```text
After 2 failures on the same upload, a secondary option appears: **Send it anyway**. It sends the photo marked as overridden, and the supplier sees the normal Received screen (Dj's decision, for accessibility). The server re-checks it with the same thresholds: it is processed normally if it passes, and goes to the admin queue as Photo unreadable if it fails (AD-6).
```
**Rationale:** AD-6 "Checks"; IR C1. The copy follows D-1.

#### X-05 · Component Patterns · Bank-change panel

**OLD:**
```text
| Bank-change panel | Admin item, reason `BANK_CHANGED` | Shows the supplier's phone number on file, the old account (masked) and the new account (masked), with a **Show** control; each use is logged to audit.
```
**NEW:**
```text
| Bank-change panel | Admin item, reason `BANK_CHANGED` | Shows the supplier's phone number on file and, for each changed bank field, the account on file (masked, or "No account on file" when the master has none for that field) and the new account (masked), with a **Show** control; each use is logged to audit.
```
**Rationale:** AD-19 "Bank details" (per field id; a field with no master value raises `BANK_CHANGED`); ADV U-1. The copy follows D-5.

#### X-06 · Allowed actions by reason · Processing failed row

**OLD:**
```text
| Monthly page limit reached, Processing failed | Re-extract, Reject | |
```
**NEW:**
```text
| Monthly page limit reached, Processing failed | Re-extract, Reject | For Processing failed before the server quality check completed, **Retry intake** is shown in place of Re-extract; it sends the upload through the quality check again (AD-3). |
```
**Rationale:** AD-3 "Retry intake"; ADV U-13. The presentation follows D-3.

#### X-07 · Allowed actions by reason · multi-reason rule (Reject)

**OLD:**
```text
- **Reject** is always offered.
```
**NEW:**
```text
- **Reject** is always offered, except once the invoice has reached the accounts system (it has an accounts reference). Then only **Approve** is offered, which re-posts it safely (AD-3).
```
**Rationale:** AD-3 "Reject"; ADV U-5.

#### X-08 · Interaction Primitives · shortcut setting

**OLD:**
```text
  - **Single-key shortcuts are off by default** (2.1.4). A per-user setting turns them on, and `?` opens a help dialog listing them.
```
**NEW:**
```text
  - **Single-key shortcuts are off by default** (2.1.4). A setting turns them on; it is kept in this browser (`localStorage`), not on the server (AD-14). `?` opens a help dialog listing them.
```
**Rationale:** AD-14 (no server profile); ADV table (2.11).

#### X-09 · Flow 3 · steps 2–4

**OLD:**
```text
2. `InvoiceTotal` shows "91%" with its box on the image around a scrawled "1,248.50".
3. She presses `c`, changes the total to 1,246.50, and taps **Save and re-check**.
4. **Climax:** the item leaves the queue with "Sent for re-check". A minute later, Invoices shows it as "Posted": the corrected total matched the PO.
```
**NEW:**
```text
2. The invoice total shows "91%" with its box on the image around a scrawled "1,248.50".
3. She presses `c`, changes the total to 1,246.50, and taps **Save and re-check**.
4. **Climax:** the item leaves the queue with "Sent for re-check". A minute later, Invoices shows it as "Posted": every check passed after the correction.
```
**Rationale:** AD-18 field ids (`invoice_total`, not the DI name `InvoiceTotal`); AD-19 compares the pre-tax `sub_total` with the PO, not the total, so "the corrected total matched the PO" was wrong.

#### X-10 · Flow 3 · CAP-10 note

**OLD:**
```text
**Note:** the correction is saved for CAP-10 (learning from corrections), which the architecture defers. Until CAP-10 is built, the supplier's next invoice isn't guaranteed to read correctly. The correction is saved for learning from corrections (CAP-10), which the architecture defers. The promise that the next invoice reads correctly holds only once that is built.
```
**NEW:**
```text
**Note:** the correction is saved for learning from corrections (CAP-10), whose training the architecture defers. Until that is built, the supplier's next invoice isn't guaranteed to read correctly.
```
**Rationale:** IR C1 (CAP-10 training deferred). This also removes the duplicated sentence.

## 5. Implementation Handoff

- **Scope classification: Moderate.** The backlog changes (one story inserted, one renumbered, ACs rewritten across all five epics) need PO or developer coordination, but no replan. The architecture is settled.
- **Who does what:**
  - **Dj (approver):** approves this proposal and settles D-1 to D-5 (the defaults are applied if he says nothing).
  - **PO / `bmad-correct-course` apply step, or a developer agent:** applies E-01 to E-102, S-01 to S-08 and X-01 to X-10 as exact string replacements, in order.
    - Each OLD must match once; stop and report if one doesn't.
    - Then check that `epics.md` still parses as 5 epics and 35 stories (34 plus the new 4.4).
  - **`bmad-architecture` (only if D-2 is accepted):** add `shared/quality/` to the Structural Seed next to `quality-thresholds.json`.
  - **Jira project OCR:** mirror the story edits, add Story 4.4 (must-have), and rename the old 4.4 to 4.5 (could-have).
  - **`bmad-sprint-planning`:** rerun the readiness gate, then generate `sprint-status.yaml`.
- **Success criteria:**
  1. Every OLD string was replaced exactly once, and no text in `epics.md`, `SPEC.md` or `EXPERIENCE.md` contradicts the ADV "Stories that contradict the spine" table.
  2. Every IR blocker and concern maps to a closing entry in the traceability table below, or to "closed by spine".
  3. The `bmad-sprint-planning` readiness gate returns PASS, and `sprint-status.yaml` is generated with 5 epics and 35 stories.

## Open decisions for Dj

- **D-1. "Send it anyway" button copy.** The old copy promised a check by hand, which no longer happens. **Recommended default:** "**Send it anyway**" with no second sentence (E-19, E-40, X-04).
- **D-2. Where the client quality-check code shared by both SPAs lives.** **Recommended default:** `shared/quality/` next to `shared/quality-thresholds.json`, imported by `web/supplier` and `web/staff` through a Vite alias; `bmad-architecture` adds one line to the Structural Seed (E-41, E-86).
- **D-3. How AD-3's "Retry intake" appears to admins.** **Recommended default:** for Processing failed where the quality stage never completed, a **Retry intake** button replaces Re-extract, with no keyboard shortcut (E-70, E-73, X-06).
- **D-4. Where the Suppliers list and page shell live.** **Recommended default:** a new must-have Story 4.4, with the could-have renumbered to 4.5 (E-92, E-93). The alternative is to fold the shell into Story 5.5, which avoids the renumber but leaves the could-have depending on a later epic.
- **D-5. Bank-change panel copy when the master has no value for that bank field.** **Recommended default:** "No account on file" (E-69, X-05).

## Readiness traceability

| IR id | Closed by |
| --- | --- |
| B1 PO / line / material link | Spine AD-10, AD-19. E-04, E-56, E-57, E-59, E-62 (reminder cleanup by PO), E-87 (Story 4.2 "invoiced"), E-94, E-98 to E-101; S-04. Materials are owned by purchasing (E-56), so nothing loads them into `master`. |
| B2 Extracted-fields data model | Spine AD-3, AD-4, AD-11, AD-14, AD-18. E-14, E-42, E-46, E-51, E-55, E-59, E-68, E-71, E-77 (settings in `localStorage`), E-85, E-87/E-89 (overdue table written by the refresh job). |
| B3 Validation and analytics criteria | Spine AD-6 (server re-check), AD-18, AD-19, AD-20. E-03, E-05, E-07, E-09, E-13, E-39, E-43, E-59, E-61, E-94, E-98, E-99, E-101; S-03, S-05, S-08. |
| B4 Database identities and grants | Spine AD-11, AD-17 steps 5–6. E-15, E-24 (operator database step, Dev can't reach Prod), E-26, E-30, E-33, E-42, E-46, E-58, E-80, E-89. |
| B5 Deploy identity rights | Spine AD-17 step table and "Deploy identity rights". E-10, E-22 (bootstrap app registrations and budget), E-23 (operator RBAC step), E-50, E-66, E-96, E-97. |
| B6 Dev auto-apply | Spine AD-17 (recorded departure) plus the `terraform.md` exception. E-10, E-25. |
| B7 Overdue schedule | Dj decided weekdays; spine AD-13. E-06, E-87, E-88; S-07. |
| B8 Must-have depends on could-have | E-92, E-93 (new must-have Story 4.4; could-have becomes 4.5). |
| C1 SPEC and UX lag Dj's decisions | S-01, S-02, S-03, S-05, S-06, S-07; X-03, X-04, X-10; E-01, E-02, E-08, E-18, E-19, E-32, E-40. |
| C2 Sweeper re-queues the wrong invoices | Spine AD-2, AD-3. E-11, E-48, E-49. |
| C3 Plaintext bank fields between 2.3 and 2.6 | Spine AD-11. E-51, E-55, E-62, E-63. |
| C4 Supplier name without PostgreSQL; token in logs | Spine AD-6, AD-14. E-31, E-34, E-35, E-36; X-01. |
| C5 Poison alert mechanism | Spine AD-17 (App Insights custom metrics). E-17, E-29, E-47, E-48, E-54. |
| C6 Resources not assigned to stacks | Spine AD-17 step table, AD-16 (recipients, per-environment throttle). E-10, E-22, E-23, E-24, E-28, E-96. |
| C7 Ordering and forward dependencies | DI F0 in 1.1: E-23, E-50. `a` shortcut after 3.3: E-76, E-84. 5.2 needs alert rows: E-94, E-96. 4.1 shared module: E-21, E-41, E-86 (D-2). Pipeline alerts moved out of 1.5: E-29. |
| C8 UX states with no story | Session restore: E-71. Staff waking up: E-65. "No data yet": E-98, E-100, E-101. Combined sidebar: E-20, E-64. Price-rise alerts on Price comparison: E-98. Evidence rows by role: E-98, E-100. Supplier search: E-92, X-02. |
| C9 Unrecorded contracts and metrics | XSD `invoice-v1.xsd`: E-78, E-80, E-81. Straight-through share: E-94, E-102. One accounts adapter: E-81, E-83. P-16 resource-group names: E-10, E-22. |
| C10 Spine decisions with no story | Per-app roles and ciphertext SELECT: E-24, E-30. Dev with no grant on Prod: E-24. `uploadkeys` cleanup: E-48. Lease reclaim: E-46, E-48. `master` materials: closed by spine (AD-10, purchasing owns materials) and E-56. Supplier formats: closed by spine (deferred with CAP-10). |
| C11 Unconfirmed decisions | Closed by spine: every AD is `[ADOPTED]`, and the "review fix" tags are gone. The remaining inline `[ASSUMPTION]` values (quality thresholds, Hamming distance 8, database up-hours) are calibration values, tracked under the spine's "To test early". |

**Not closed by this proposal:** none of the IR items. Three follow-ups sit outside the three target files: the Jira OCR sync, the one-line spine seed addition if D-2 is accepted, and the `sprint-status.yaml` generation (the readiness rerun).
