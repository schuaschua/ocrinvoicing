---
name: 'Implementation readiness: OCR Invoice Automation PoC'
type: implementation-readiness
verdict: CONCERNS (re-run 2026-09-28 after correct-course)
created: '2026-09-28'
inputs:
  - _bmad-output/specs/spec-ocr-invoice-automation/SPEC.md
  - _bmad-output/planning-artifacts/ux-designs/ux-ocrinvoicing-2026-09-28/DESIGN.md
  - _bmad-output/planning-artifacts/ux-designs/ux-ocrinvoicing-2026-09-28/EXPERIENCE.md
  - _bmad-output/planning-artifacts/architecture/architecture-ocrinvoicing-2026-09-28/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/epics.md
  - docs/architecture/architecture.md
  - docs/architecture/azure.md
  - docs/standards/terraform.md
  - docs/standards/azure.md
---

# Implementation Readiness: OCR Invoice Automation PoC

**Verdict: FAIL.** A developer could build most of Epic 1 as written. From Story 2.5 onward, they would have to make up business rules and data decisions that nothing records. Sprint tracking (`sprint-status.yaml`) was not generated. Rerun `bmad-sprint-planning` after the fixes; its parser already reads `epics.md` cleanly (5 epics, 34 stories).

Paths used below: **SPEC** = `SPEC.md`, **EXP** = `EXPERIENCE.md`, **S** = `ARCHITECTURE-SPINE.md`, **E** = `epics.md`, **TF** = `docs/standards/terraform.md`, **AZ** = `docs/standards/azure.md`.

## What checks out

- **Coverage:** all 20 CAPs map to stories (E:255-274).
- **Key numbers:** 98% confidence, 4 MB, 2 pages, 30 days, the Document Intelligence caps of 100/400, and the 1/5/15/60-minute backoff agree across SPEC, EXP and E.
- **Reason codes:** the 12 codes match between EXP:88-101 and AD-4.
- **Security:** bank-detail and security rules are consistent in every document.
- **Admin:** the actions in Stories 2.10 and 3.3 match the UX allowed-actions table. The reason labels, pagination and empty state also agree.
- **Epic value:** every epic delivers something users can see.

## Blockers

### B1. Invoice → PO → line → material link is undefined

- **Missing rules for Story 2.5** (E:757): it checks "invoice total vs PO unit price × received quantity". Nothing records:
  - which PO an upload belongs to (no DI `PurchaseOrder` field is named, and no rule covers a missing PO);
  - how invoices with several lines are matched;
  - whether the total includes tax;
  - what tolerance applies.
- **Other stories rest on the same link:**
  - Story 2.6 "matches it to the PO" for reminder cleanup (E:806).
  - Story 4.2 uses "the received invoices" (E:1173).
- **Materials:**
  - `master` holds materials (S:249).
  - No story loads them: the load CSV in Story 1.6 has suppliers only (E:470).
  - Nothing maps an invoice line to a material, or matches the same material across suppliers.
  - CAP-14 to CAP-17 and Stories 5.1 and 5.3–5.5 depend on this (E:1256, 1305, 1327, 1334, 1351).
- **Fix:** `bmad-architecture` (data model and matching rules), then `bmad-correct-course` (stories 1.6, 2.5, 2.6, 4.2, 5.x).

### B2. Extracted-fields data model is missing

- **What has no table:**
  - the extraction result (S:99);
  - the per-field confidence scores and bounding regions (S:200);
  - `admin_item.field_ids[]` (S:137);
  - admin corrections with `source=admin` (S:101);
  - line items.
- **What is not defined:** the field ids, and which DI fields are stored.
- **Stories affected:** 2.3, 2.5, 2.9 and 2.10.
- **Related gaps:**
  - the `audit` schema (S:138, S:252), written by Stories 1.6, 2.9, 2.10 and 3.3;
  - the status history in Story 3.4 (E:1120);
  - per-user settings in Story 2.11 (E:1004), which have no table or owner in AD-11 (S:246-252);
  - the overdue job's table (E:1187), whereas `analytics` is written by the refresh job only (S:289).
- **Fix:** `bmad-architecture` (AD-11 schema table).

### B3. Validation and analytics rules have no criteria

- **Date mismatch** (E:793):
  - `photo_taken_at` "differs from the invoice delivery date";
  - no tolerance in days, no DI field named for "delivery date", and no rule for EXIF local time vs UTC.
- **Lateness** (E:1327, E:1351): "7+ days late" and "on-time rate" don't say measured against what (the PO expected date, goods received, or the invoice date).
- **Price rise** (E:1310, E:1327): "recent invoices", the rise threshold, and what counts as one "increase" are undefined.
- **Supplier-name match** (E:761, S:140): exact or fuzzy is not stated. An exact match would raise false `SUPPLIER_ID_MISMATCH` flags.
- **LOW_CONFIDENCE** (E:753, S:200) fires on "any extracted field":
  - nothing records which DI fields count;
  - prebuilt-invoice returns many optional fields, so at 98% this likely sinks the 90% straight-through target (SPEC:108).
- **Server readability re-check** (S:170): no algorithm or thresholds.
- **Fix:** `bmad-architecture` (rules in AD-4/AD-9), `bmad-correct-course` (ACs).

### B4. Database identities and grants are undecided

- **What the spine requires:**
  - one Entra database role per app (S:262);
  - Dev identities get no grant on `invoicing_prod` (S:277).
- **Nothing decides:**
  - who runs `pgaadauth_create_principal` (TF:44);
  - which identity deploys the `shared` stack (S:347 has only "one deploy identity per environment");
  - the migration identity for each database (TF:121).
- **Grants:** no story grants roles to `supplier-api`, `staff-api`, `pipeline` or `accounts-sim`. Only the loader (E:489) and `sim_purchasing` (E:738) get grants.
- **Fix:** `bmad-architecture` (AD-11/AD-12/AD-17), `bmad-correct-course` (Epic 1 stories).

### B5. The deploy identity's rights can't cover what the stories ask

- **The rule:** AZ:106 (rule 31) limits the deploy identity to its own resource group, with nothing at subscription scope and no directory rights.
- **The stories need more:**
  - Story 2.7: Terraform creates the Entra app registration and app roles (E:851). That needs directory rights.
  - Story 2.3: an env `pipeline` identity gets a role on the shared DI resource (E:686), which is in another resource group.
  - Story 1.1: the $8 subscription budget (E:334) needs subscription scope.
- **Cross-stack reads:** reads from `shared` conflict with TF:58 and TF:65. The spine records a departure at server level only (S:280).
- **Fix:** `bmad-architecture` (record the exceptions or move these to bootstrap/manual steps).

### B6. Dev auto-apply contradicts the Terraform standard

- **The story:** Story 1.2 "plans and applies `dev` automatically" (E:353).
- **The standard:** TF:102 (rule 26) requires a human-approved saved plan, and TF:115 (rule 33) says "merges to `main` never apply".
- **The gap:** the spine does not record this as a departure (S:347).
- **Fix:** decide which side wins. Either record an exception in AD-17 and `terraform.md` Accepted exceptions, or change Story 1.2.

### B7. The overdue-list schedule is explicitly undecided

- **Story 4.2 note:** "Decide it before building this story" (E:1184).
- **The two sides:** SPEC:55 says daily, while the spine says weekdays only (S:290, S:498).
- **Fix:** Dj decides, then `bmad-correct-course`.

### B8. A must-have story depends on a could-have story

- **The dependency:** Story 5.5 Scorecard (CAP-17, must-have) opens "the supplier page (from Story 4.4)" (E:1349).
- **The problem:** the Suppliers list and page shell exist only in could-have Story 4.4 (E:1235, E:1239). If CAP-19 is dropped, the must-have Suppliers surface (EXP:48) has nowhere to live.
- **Fix:** `bmad-correct-course` (move the page shell into a must-have story).

## Concerns

### C1. The spec and UX lag behind decisions Dj made

- **Send it anyway:**
  - SPEC:28 and EXP:110 ("Babaloo will look at it by hand") promise a check by hand after an override.
  - Dj's adopted decision (S:170, and the architecture memlog) processes an overridden upload normally when it passes the server re-check.
  - There is no reason code for an overridden upload.
- **Link issuing:**
  - SPEC:22 says links are "issued and revoked automatically".
  - The operator-run script (E:480-482, EXP:55) was adopted instead.
  - There is no way to revoke a link without issuing a new one.
  - Re-issue: `--replace-link` flag (E:480) vs "re-running revokes" (S:162).
- **CAP-10:** its success line (SPEC:49) expects training to take effect, but the epics defer training (E:35, EXP:245).
- **Fix:** `bmad-correct-course` (update SPEC and EXP copy).

### C2. The sweeper's rules re-queue the wrong invoices

- **The rule:** the sweeper re-enqueues any "non-terminal, unclaimed" invoice more than 1 hour old (S:82).
- **Waiting admin items:** `in_admin_queue` is non-terminal (S:122), so items waiting for an admin would be re-enqueued.
- **Missing mapping:** there is no mapping from state to queue.
- **Double queueing:** a `posting` invoice in a 15 or 60-minute backoff (S:229) outlives its 10-minute lease (S:96), so it could be enqueued twice.

### C3. Bank details are plaintext between Story 2.3 and Story 2.6

Story 2.3 stores every field, including the raw DI result (E:692). Encryption arrives only in Story 2.6 (E:803). AD-11 requires encryption at rest (S:254).

### C4. The upload path needs the supplier name without PostgreSQL

- **The need:** Story 1.7 shows "Uploading for {supplier name}" without touching PostgreSQL (E:503-504).
- **The gap:** `supplierlinks` stores only `supplier_id, issued_at, revoked_at` (S:160).
- **Token in logs:** how the token travels from `/u/<token>` to `GET /api/link` (E:523) is undecided. If it is in the URL path, platform request logging records it, which breaks "never appears in logs" (S:314).

### C5. The poison-queue alert has no mechanism

Storage queue metrics are account-level only, so "any `*-poison` queue longer than 0" (S:360, E:455) needs a custom mechanism. None is decided.

### C6. Not every resource is assigned to a stack

- **The rule:** TF:57 requires the architecture to assign each resource to one stack.
- **The gap:** the spine names the stacks only (S:346). Queues, tables, Key Vault, the app registration and ACS are unplaced.
- **Also missing:** the source of the email recipients, and where the cross-environment throttle (S:333) keeps its state.

### C7. Story ordering and forward dependencies

- **DI F0:** it sits in `shared/foundation` (S:346), but Story 1.1 leaves it out (E:320-323). Story 2.3 adds it.
- **Story 2.11:** the `a` shortcut is "available once Approve exists" (E:996), which is Story 3.3.
- **Story 5.2:** it needs `analytics.alert` rows (E:1283), which only Stories 5.3 and 5.4 create.
- **Story 4.1:** it reuses the Story 1.9 module in a second SPA (E:1149), but the seed has no shared package (S:453-455).

### C8. UX states and details with no story

- restoring unsaved Correct edits after a session expires (EXP:164), where Story 2.7 only shows the dialog (E:837-839);
- the staff app "waking up" state (EXP:157), which only the supplier page covers (Story 1.7);
- "No data yet" on every analytics surface (EXP:170), which only Story 5.6 has;
- a combined sidebar for users with several roles (EXP:54), vs "their role's surfaces" (E:829);
- price-rise alerts shown on the Price comparison page (EXP:50), where Story 5.3 only emails them;
- evidence rows that link for admin and finance and are read-only for others (EXP:120), missing from Story 5.4;
- supplier search in Flow 5 (EXP:255), missing from Story 4.4.

### C9. Unrecorded contracts and metrics

- **Accounts XML schema:** the "agreed" schema in Story 3.1 (E:1022) is not recorded anywhere, and the real API is deferred (spine Q9).
- **Straight-through share:** Story 5.6 shows it (E:1370), but Story 5.1's metrics (E:1256) don't produce it.
- **Accounts adapters:** the spine has two (S:449), while Story 3.x has one "XML adapter" (E:1068).
- **Resource-group names:** `shared/dev/prod` (S:345, E:318) vs P-16 naming for every Azure resource (`docs/architecture/azure.md:20`).

### C10. Spine decisions with no implementing story

- per-app database roles, and "only `staff-api` may SELECT ciphertext" (S:263);
- Dev having no grant on `invoicing_prod` (S:277);
- cleaning up expired `uploadkeys` rows (Table Storage has no TTL, S:167);
- reclaiming expired leases (S:97);
- loading `master` materials and supplier formats (S:249).

### C11. Unconfirmed decisions Epics 1 and 2 build on

- **AD-3:** no tag at all (S:87).
- **AD-2 and AD-8:** carry "review fix", which is not a defined tag (S:25, S:69, S:188).
- **[ASSUMPTION] decisions:**
  - AD-4: reason catalogue and `route_to_admin`, used by Stories 1.4 and 2.1-2.10.
  - AD-6: link and token design, `uploadkeys` and the upload path, used by Stories 1.6-1.9.
  - AD-9: phash, used by Stories 2.1 and 2.6.
  - AD-11: schemas and bank encryption, used by Stories 1.6 and 2.x.
  - AD-13: timer times, used by the Story 2.2 sweeper.
  - AD-14 beyond hosting: auth, roles and `X-Requested-With`, used by Stories 1.4 and 2.7.
  - AD-17 beyond Terraform and the repo: names, tags, alerts and workload identity federation, used by Stories 1.1, 1.2 and 1.5.

## Decisions taken (Dj, 2026-09-28)

- **B6:** Dev keeps applying automatically on merge. Record it as a departure in AD-17 and under Accepted exceptions in `terraform.md` (rules 26 and 33). Prod and `shared` keep the manual approval.
- **B7:** the overdue-PO list is built on weekdays only, as in the spine. Update SPEC:55 and remove the note in Story 4.2.
- **C11:** review the [ASSUMPTION] decisions one by one during the architecture update, fixing the gaps found here, then mark each one ADOPTED.

## Progress

- **2026-09-28, step 2 done.** `bmad-architecture` updated the spine: B1–B6, C2, C4–C6, C9 (XML contract) and the architecture side of C10/C11 are closed by AD-2 to AD-20, and every AD is now ADOPTED. P-8 and P-9 departures were added to `docs/architecture/architecture.md`; exceptions were added to `docs/standards/terraform.md` and `azure.md`.
- **For `bmad-correct-course`:** the stories that now contradict the spine are listed in `architecture-ocrinvoicing-2026-09-28/reviews/review-update-adversary.md` ("Stories that contradict the spine"). The most important are Story 1.7 (token in the URL fragment, not the path) and Story 2.3 (bank fields encrypted at extract). The spec also needs CAP-1 (P-8), CAP-3 ("Send it anyway"), CAP-4 (checked fields), CAP-7 (goods-received date) and CAP-12 ("each weekday") reworded.

## Suggested order of fixes

1. **Dj decides:** B6 (dev auto-apply), B7 (overdue schedule), and whether the [ASSUMPTION] decisions in C11 are adopted.
2. **`bmad-architecture` (update):** B1–B5, C2, C4–C6, and the XML contract in C9.
3. **`bmad-correct-course`:** carry the changes into SPEC, EXP, `epics.md` and the Jira project OCR. This covers B8, C1, C3, C7, C8, C10 and the rest of C9.
4. **`bmad-sprint-planning`:** rerun it to pass the gate and generate `sprint-status.yaml`.

## Re-run 2026-09-28 (after the sprint change proposal): CONCERNS

B1–B8 and C1–C11 are closed in the files. New findings from the re-run:

| # | Severity | Finding | State |
| --- | --- | --- | --- |
| 1 | High | Migrations and the load script couldn't reach PostgreSQL (firewall rights) | **Closed:** firewall opened for the PoC (Dj), AD-17 step 2, accepted exceptions azure.md 13/11 and terraform.md 36 |
| 2 | High | Terraform can't generate the OpenPGP key pair | **Closed:** operator step 4b (`gpg` offline, stored in Key Vault), AD-17 |
| 3 | Medium | `PurchasingPort` lacks delivery listing, bulk receipts and a receipt→delivery link (Stories 2.5 goods-in, 4.1, 5.x) | Open: `bmad-architecture` (AD-10) before Story 2.4 |
| 4 | Medium | Watchlist has no lifecycle (leave rule, recompute, alert key) | Open: Dj decides, then AD-20 |
| 5 | Medium | An approved bank change never reaches `master`, so the next invoice flags again | Open: Dj decides, then correct-course |
| 6 | Low | `invoice-v1.xsd` elements unrecorded | Open: `bmad-architecture` |
| 7 | Low | Retry-intake guard misfires for PDFs | Open: `bmad-architecture` (AD-3) |
| 8 | Low | Invoice delivery date (could-have Story 4.5) has no source | Open: `bmad-architecture` |

Dj proceeded with the concerns open: none blocks Epic 1. `sprint-status.yaml` was generated (5 epics, 35 stories, Jira key OCR).
