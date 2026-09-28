# Review: rubric and reconcile, updated ARCHITECTURE-SPINE (AD-1 to AD-20)

- Reviewer: independent (rubric + reconcile), second pass after the implementation-readiness update
- Date: 2026-09-28
- Spine: `ARCHITECTURE-SPINE.md` (612 lines, `updated: 2026-09-28`). Line numbers below are spine lines (`S:n`) unless another file is named.
- Inputs: `implementation-readiness.md` (IR), `SPEC.md`, `docs/architecture/architecture.md` + `azure.md` (P-1 to P-20), `docs/standards/{terraform,azure,security}.md`, `.memlog.md` (ML).
- Accepted and not re-flagged: P-2 (~$11-12/month, S:310), P-13 shared PostgreSQL server (S:309), P-19 risk-based MFA (S:341), terraform.md rules 3, 26, 33, 31-34 and azure.md rule 31 (all recorded in the standards' Accepted exceptions tables).

## Verdict

**Nearly ready; fix five rule-level issues before `bmad-correct-course`.** The update closes every architecture blocker from the readiness report (B1-B6) and C2, C4, C5, C9-XML, C10 and C11 in substance, and the new AD-18/19/20 remove most "make up a rule" gaps. What remains: one rule that forces a wrong result (AD-20 "posted only" vs CAP-18 duplicate counts), one unnamed principle departure (P-9 narrowed to checked fields), spine-wide "ADOPTED" claims for items the memlog still marks "to confirm with Dj", a throttle/page-cap rule that is not enforceable once Flex scales out, and a handful of medium data-model and infra gaps (invoice columns, field currency across runs, orphaned uploads, runtime-role list, app registration per environment, code-deploy path).

## Findings summary

| # | Severity | Where | Finding |
| --- | --- | --- | --- |
| R1 | High | AD-20 S:464, AD-13 S:318 vs CAP-18 | "Computes from posted invoices only" and a `posted_at` watermark make CAP-18's flagged and duplicate counts impossible (duplicates are rejected, never posted) |
| R2 | High | AD-18 S:432-437 vs P-9, CAP-4 | Only "checked fields" trigger `LOW_CONFIDENCE`; P-9 and CAP-4 say *any* field. The departure is not named |
| R3 | High | S:26 vs ML:97 | Spine says every AD is ADOPTED ("Dj settled it"); the memlog's last entry marks several closures `[DISTILL, Claude; to confirm with Dj]` |
| R4 | Medium | AD-8 S:211-212, AD-2 S:95, azure.md rule 20 | The 1-request-per-2-s throttle and page cap are per process; Flex scales the `extract` function out, and no instance ceiling or atomic page reservation is set |
| R5 | Medium | AD-18 S:430 | "Newest row wins per field/line" is not scoped to the current run: after re-extract, fields or lines missing from the new run keep stale values from the old one |
| R6 | Medium | AD-3/AD-5/AD-13 (B2 residual) | `intake.invoice` columns are never listed; `posted_at` (the analytics watermark), `supplier_id`, `source`, `delivery_id`, resolved PO, `photo_taken_at`, `accounts_ref` are implied only |
| R7 | Medium | AD-6 S:176-180 | Idempotent retry returns the stored `invoice_id` without re-enqueueing; a failed enqueue after the key/blob write orphans the upload, and the sweeper can't see it (no DB row) |
| R8 | Medium | AD-13 S:319, AD-10 S:247-248 | The overdue rule is undefined: PO-level vs line-level `expected_date`, and which invoice states count as "received" |
| R9 | Medium | AD-11 S:273-279 vs P-7 | The symmetric pgcrypto key must be held by `pipeline` (it encrypts extracted bank fields) and `pipeline` has read on `intake`, so "admin only" is enforced by code discipline, not by access |
| R10 | Medium | AD-14 S:337, AD-17 S:386 | One app registration: unclear whether per environment. If shared, Dev and Prod accept each other's tokens and share role assignments (P-13). `accounts-sim` built-in auth has no registration at all; redirect URIs have no owner |
| R11 | Medium | AD-17 S:389, S:392 vs azure.md rule 9 | Runtime roles per identity are not listed (Storage Queue/Blob/Table, Key Vault Secrets User, Monitoring Metrics Publisher, ACS), so step 3's and step 7's conditioned RBAC Administrator can't be written; the loader's (Dj's user) storage and Key Vault rights are missing |
| R12 | Medium | AD-17 (delivery) | How code reaches the Flex apps (package deploy, Flex deployment storage container, identity, rollback, smoke check) is not decided |
| R13 | Low-Med | AD-6 S:175 vs P-8 | P-8 says links are "issued and revoked automatically"; an operator-run script is a departure, not named (IR C1 covers only the SPEC side) |
| R14 | Low-Med | AD-17 S:396 vs security.md rule 34; AD-14 S:344 vs azure.md rule 12 | Dev auto-apply also departs from security.md rule 34; anonymous-at-platform `supplier-api` needs an azure.md rule 12 accepted exception. Neither is named / recorded |
| R15 | Low-Med | CAP-19, S:591 | "Invoice delivery date" has no source (DI has no delivery-date field, ML:76); CAP-19 builders will invent one |
| R16 | Low | various | Smaller gaps, listed at the end |

---

## Job 1: rubric

### 1.1 Does it fix the real divergence points, and miss none?

Fixed well (all new or tightened in this update):

- Hand-off and recovery: claim-first with leases, zero-row redelivery, sweeper state→queue map, posting backoff that releases the lease (S:80-93, S:105-111).
- Admin entry: one `route_to_admin`, one reason catalogue, `admin_item` shape, all reasons at once (S:145-152).
- Extracted data model: runs, fields, lines, field ids, checked fields (S:425-437).
- Validation criteria: PO match, tolerance, photo-date window, tax-id/fuzzy name, bank fingerprint (S:444-458).
- Analytics criteria: unit price, rise, watchlist, lateness, alternatives, straight-through share (S:465-473).
- Identity and grants per login, CONNECT revoked from PUBLIC, grants in migrations (S:280-293).
- Stack ownership of every major resource (S:384-392).

Remaining divergence points (see findings):

- **R1** CAP-18 counts vs "posted only".
- **R5** current-value scope across runs.
- **R6** `intake.invoice` shape (two builders will add `posted_at`, `po_number`, `supplier_id` differently; the analytics job and the post stage must agree on `posted_at`).
- **R8** overdue definition (the refresh job builder and the Story 4.2/CAP-13 builder must agree).
- **R15** CAP-19 invoice delivery date.
- **R10** app registration per environment and for `accounts-sim`.

### 1.2 Is every AD Rule enforceable, and does it prevent its stated divergence?

- **AD-8 (R4).** "At most 1 request every 2 seconds in each environment" (S:211) is enforced in `adapters/document_intelligence.py`, which is per process. `batchSize 1` / `newBatchThreshold 0` (S:95) limit concurrency per instance only; Flex Consumption scales queue-triggered functions out per function, and no `maximumInstanceCount` is set (azure.md rule 20 also asks for compute ceilings in the architecture). Likewise the page cap in `intake.di_usage` (S:212) needs an atomic reserve-before-call (`UPDATE … SET pages = pages + :n WHERE pages + :n <= cap RETURNING`), else concurrent extracts overshoot. Fix: set the `pipeline` app's maximum instance count to the lowest allowed value and verify it yields one `extract` instance, or move the throttle to shared state (e.g. a DB row with next-allowed timestamp), and state the atomic page reservation. The 429 fallback (S:199) keeps this graceful, hence Medium.
- **AD-11 P-7 (R9).** "Readable only by the admin role" relies on `pipeline` never calling `pgp_sym_decrypt`, although it holds the key and `intake` read. Either name that as accepted, or use `pgp_pub_encrypt` with only the public key in `pipeline`, private key only for `staff-api`. The `master` "no ciphertext columns" grant (S:284) is then real protection rather than symbolic.
- **AD-14 CSRF (low).** S:339 says the page sends `X-Requested-With`; the rule should say `staff-api` **rejects** any non-GET without it (security.md rule 24 is about the server requiring it). Also verify that built-in auth lets you set the session cookie to `SameSite=Lax` (S:338); if the platform fixes it, record what it is.
- **AD-11 audit (low).** "every app, INSERT only" (S:271) contradicts "`supplier-api` has no database login" (S:290) and the `accounts-sim` grant row (S:286). Say which apps write audit.
- **AD-2 posting attempts (low).** The 5-failure count for `ACCOUNTS_API_ERROR` (S:246) is carried in the message `attempt` (S:79); a sweeper-created message (S:90) starts again, so the limit can be exceeded. Persist the attempt count on the invoice, or say the sweeper copies it.
- All other Rules name a single owner, a single file or a single function and are checkable in review or with the import-linter.

### 1.3 Could anything under Deferred let two units diverge?

- **More than one currency (S:598).** No rule says what happens when an invoice arrives in another currency: `validate` has no reason for it, and AD-20 assumes SGD (S:465). Add "a non-SGD `currency` raises `PO_MISMATCH` (or a new reason)", or units will each decide. Low-Med.
- Custom-model training (S:596), production link (S:597), S0 move (S:599), ACS replacement (S:600), DB automation (S:601), HA (S:602), screens (S:603): each is behind one seam or is configuration only. No divergence risk.

### 1.4 Is every dimension decided, deferred or open?

| Dimension | State | Gap |
| --- | --- | --- |
| Compute, hosting, region | Decided (AD-1, AD-14) | No instance ceilings (R4, azure.md rule 20) |
| Messaging, state machine, errors | Decided (AD-2 to AD-4, AD-7) | R7 orphaned upload |
| Data model | Mostly (AD-11, AD-18) | R5, R6; `intake.image_hash`, `intake.di_usage`, `analytics.*` column shapes are left to builders (acceptable: single writer) |
| Business rules | Decided (AD-19, AD-20) | R1, R8, R15 |
| Security and identity | Decided (AD-6, AD-11, AD-14) | R9, R10, R13, R14; HMAC/pgcrypto key rotation effect not documented (security.md rule 11) |
| Environments | Decided (AD-12, AD-17) | R10 (shared registration?); P-13 "no real data in Dev" has no rule for the Dev supplier load (synthetic suppliers only) |
| Infra / IaC | Decided (AD-17 table) | R11 runtime roles; diagnostic settings for shared PG/DI/ACS have no workspace (azure.md rule 15: shared RG has none); state storage RG and name (azure.md rule 29 vs P-16) not stated; how P-17 "missing tag is not deployed" is enforced |
| Delivery / CI-CD | Mostly (S:395-403) | R12 code deploy path; destroy/replace guard of terraform.md rule 33 has no ADO equivalent named |
| Operations | Mostly (S:307-308, S:408-414) | "stuck" is undefined for the `stuck_invoices` metric (S:413); no per-supplier upload rate limit on the public `supplier-api` (a single link can burn the shared F0 quota) |
| Backup / recovery | Decided (S:303, S:354) | Table Storage (`supplierlinks`) has no backup under P-12; losing it forces re-issuing every link. Say it is accepted |
| Cost | Stated per AD | AD-17's "$0.30 for metric alerts" (S:415) conflicts with ML:94 "$0.10 per alerted series": 4 poison queues + 2 metrics per env x 2 envs = ~12 series (~$1.20), plus any log-search alert for the log cap. Total likely ~$12-13 |

### 1.5 Does it cover every CAP?

All 20 appear in `binds` (S:11) and the map (S:575-592). Coverage issues:

- **CAP-3:** "Send it anyway ... checked by hand" (SPEC:28) vs processed normally (S:183). Dj's decision (ML:71); SPEC change is in IR C1 for correct-course. OK.
- **CAP-4:** see R2.
- **CAP-10:** deferred behind seams (S:596). SPEC success line still expects learning (IR C1). OK.
- **CAP-12:** S:319 says "CAP-12 reads 'each weekday'", but SPEC:54 still says "A daily overdue list" until correct-course runs. Low; the wording should say "will read".
- **CAP-18:** see R1. Also "monthly spend" has no rule for which date buckets it (`invoice_date` or `posted_at`). Low.
- **CAP-19:** see R15.
- **CAP-2:** goods-in scan limits (type, size, pages) are stated only for `supplier-api` (S:176). Say they apply to `staff-api` goods-in too. Low.

---

## Job 2: reconcile

### 2.1 Readiness findings owned by the architecture

| Finding | Status | Evidence (spine lines) | Residual |
| --- | --- | --- | --- |
| **B1** Invoice → PO → line → material | CLOSED | PO source and ownership S:445; line match S:446; pre-tax tolerance S:447; failures S:448; purchasing owns materials S:248-249; line → `po_line_id`/`material_id` S:429 | R8 (overdue "received"); partial invoicing against a PO with several deliveries compares with *all* receipts so far (S:447), which will false-flag per-delivery invoices (Low) |
| **B2** Extracted-fields data model | CLOSED in substance | `extraction_run` S:425; `invoice_field` S:426-428; `invoice_line` S:429; current value S:430; field ids S:431; `admin_item.field_ids` S:150; audit S:271; status history S:106; per-user settings in localStorage S:343; overdue table owned by refresh job S:319 | R5, R6 |
| **B3** Validation and analytics criteria | CLOSED | Date S:449-452; lateness S:471; price rise S:466; watchlist S:467-470; supplier name S:453-455; LOW_CONFIDENCE fields S:432-437; readability re-check S:183 (thresholds `[ASSUMPTION]`) | R2 (P-9 departure unnamed) |
| **B4** DB identities and grants | CLOSED | Logins and grants S:280-289; no `supplier-api` login S:290; CONNECT revoked S:291; operator creates principals S:292, S:390; shared deploy identity S:386-387; migration identity S:288, S:391 | Operator must also grant the env deploy identity CREATE on its database so it can "own the schemas" (implied, Low) |
| **B5** Deploy identity rights | CLOSED | App registration + budget in bootstrap S:386; conditioned RBAC Admin on DI/ACS S:388, S:392; departures S:404; cross-stack reads S:394; azure.md Accepted exceptions row 31 recorded | R10 (redirect URIs need directory rights; who adds them?), R11 (role list for the condition) |
| **B6** Dev auto-apply | CLOSED | S:396-397; terraform.md Accepted exceptions (26, 33) | R14: also departs from security.md rule 34, not named |
| **C2** Sweeper re-queues wrong invoices | CLOSED | Map S:85-90; never `in_admin_queue` S:92; backoff releases lease, skips future `next_attempt_at` S:90, S:111 | R7 (pre-row uploads invisible to the sweeper) |
| **C4** Supplier name without PG; token in logs | CLOSED | `supplier_name` in `supplierlinks` S:173; fragment + `X-Upload-Token` S:172; never in logs S:344, S:484 | none |
| **C5** Poison alert mechanism | CLOSED | Custom metrics S:409-414 | cost figure (see 1.4) |
| **C6** Every resource in one stack; recipients; throttle state | PARTLY | Stack table S:384-392; recipients S:366; per-env throttle with no shared state S:364 | `accounts-sim`'s Entra registration, Flex deployment storage, diagnostic settings for shared resources, redirect URIs, state storage account placement are unassigned (R10, R12, 1.4) |
| **C9** Accounts XML contract | CLOSED | One adapter, `invoice-v1.xsd` is the contract S:242; sim validates against it S:243; switch by config S:244 | XSD content authored in Story 3.1; both sides read the same file, so no divergence |
| **C9** (other architecture items) | CLOSED | Straight-through share S:473; one accounts adapter S:242; RG names on P-16 S:405 | none |
| **C10** Decisions with no story (architecture side) | CLOSED | Per-app roles and ciphertext grant S:284-285; Dev no Prod grant S:291; `uploadkeys` cleanup S:93; lease reclaim S:88-90, S:108; materials from purchasing S:248, supplier formats deferred S:596 | Stories themselves are correct-course work |
| **C11** Unconfirmed decisions | PARTLY | All ADs tagged ADOPTED S:26; "review fix" tags gone | R3: ML:97 items still "to confirm with Dj" |

### 2.2 Memlog decisions that did not land, or that the spine contradicts

| Memlog | Spine | Issue |
| --- | --- | --- |
| ML:97 `[DISTILL, Claude; to confirm with Dj]`: `--revoke`, multi-role users see all surfaces, lateness definition, straight-through definition, duplicate fingerprint ignores rejected, `shared/quality-thresholds.json`, new AD-18/19/20 | S:26 "Every AD is [ADOPTED]: Dj settled it"; S:175, S:340, S:471, S:473, S:228, S:566 | **R3.** Spine asserts adoption the memlog does not record. Either get Dj's confirmation and log it, or tag these lines `[PROPOSED]` |
| ML:94 alerts "about $0.10/month per alerted series" | S:415 "about $0.30 a month" | Cost understated vs memlog pricing (see 1.4) |
| ML:25 "Departs from P-13 isolation at server level only" | S:309 same wording | Now inaccurate: DI F0 (S:209), ACS (S:365) and possibly the app registration (S:337) are also shared. architecture.md departures list PG and DI but not ACS. AD-8 and AD-16 don't say "departs from P-13" (Low) |
| ML:76 DI has no delivery-date field | CAP-19 row S:591 | Constraint not carried to CAP-19 (R15) |
| ML:37 "extract function max instances 1 and concurrency 1" | S:95 per-instance settings only | The instance ceiling was dropped when the review fix changed the mechanism (R4) |

No other memlog decision is missing; superseded entries (ML:33-37, 42, 43, 45, 56, 67) are correctly replaced by later ones.

### 2.3 Departures from principles or standards that the spine does not name

| Source | Rule | Spine | Named? |
| --- | --- | --- | --- |
| P-9 (architecture.md:83) | "Any extracted field below 98% confidence goes to the admin queue" | Only checked fields (S:432-437) | **No (R2)** |
| P-8 (architecture.md:77) | Links "issued and revoked automatically" | Operator-run script (S:175) | **No (R13)** |
| P-7 (architecture.md:71) | Readable only by admin role | Symmetric key held by `pipeline` (S:273-275) | No; arguably within P-7 for services, but should be stated (R9) |
| P-13 | Environments isolated | ACS shared (S:365); app registration possibly shared (S:337) | Partly: terraform.md exception 3 names ACS; spine and architecture.md do not |
| security.md rule 34 | Human-approved pipeline apply for every change | Dev auto-apply (S:396) | **No (R14)**; only terraform.md 26/33 named |
| azure.md rule 12 | `AllowAnonymous` at the edge is an accepted exception | `supplier-api` anonymous (S:62, S:344) | Only security.md rule 4 named; azure.md rule 12 not recorded (R14) |
| azure.md rule 9 | List runtime roles in the project copy | Only Cognitive Services User (S:209) | **No (R11)** |
| azure.md rule 20 | Compute ceilings recorded in the architecture | None | **No (R4)** |
| security.md rule 11 | Document key rotation effect | Terraform-generated keys (S:389) | No (Low): rotating the HMAC key invalidates every fingerprint |
| security.md Accepted exceptions | Table must list accepted gaps | S:400-403 replace rules 10, 28, 30 | Named in spine; not yet copied into security.md's table (correct-course / housekeeping) |

---

## Details for the medium findings

- **R1 (High).** AD-20 opens "The refresh job computes these from posted invoices only" (S:464) and AD-13 makes the job incremental "from a `posted_at` watermark" (S:318). CAP-18 needs "counts of flagged and duplicate invoices" (SPEC:72); a duplicate is normally rejected (S:116) and never gets `posted_at`. Fix: let the refresh job also read `intake.admin_item`/`status_history` from a second watermark (`created_at`), and restrict "posted only" to price, lateness and spend rules.
- **R2 (High).** The checked-field subset (ML:87, adopted ML:96) is a sensible decision to protect the 90% target, but it narrows P-9 and CAP-4's success line. Add "Departs from P-9 ('any extracted field')" to AD-18 and add the row to architecture.md Accepted departures; carry to SPEC CAP-4 in correct-course.
- **R5.** Rule S:430 should read: current value = newest `source=admin` row for the current run, else the current run's DI row; the current run is the invoice's newest `extraction_run`. Lines likewise. Otherwise `validate` and the admin screen may scope differently, and missing-field → confidence 0 (S:437) never fires when an older run has the field.
- **R6.** List `intake.invoice{id, supplier_id, source, delivery_id, po_number (resolved), status, status_changed_at, claimed_until, next_attempt_at, photo_taken_at, accounts_ref, posted_at, correlation_id, created_at}` or equivalent, with the writer of each column (quality inserts; validate sets `po_number`; post sets `accounts_ref`, `posted_at`).
- **R7.** In AD-6, order the steps as: conditional insert of `uploadkeys` → blob write → enqueue → mark key complete; a retry whose key is not complete re-does the blob write (overwrite) and enqueue. Or let the sweeper also scan `uploadkeys` rows older than 1 hour with no DB row.
- **R8.** Define: a PO is overdue on day D when its earliest (or latest; pick one) open line `expected_date` < D and no non-rejected invoice has `po_number` = that PO. State whether an invoice waiting in the admin queue counts as received.
- **R10.** Say "one app registration per environment for `staff-api`" (or accept sharing and name the P-13 departure), who registers each environment's redirect URI (bootstrap after the app exists, or predictable host names), and how `accounts-sim` authenticates callers (its own registration, or built-in auth with allowed client applications = the `pipeline` identity).
- **R11.** Add a runtime-role table: per identity, the data-plane roles and scopes. This is what step 3's and step 7's RBAC Administrator condition must allow. Include Dj's user for the load script (Table Data Contributor on `supplierlinks`, Key Vault Secrets User for the keys) or say the script gets them another way.
- **R12.** Decide: Flex package deploy from ADO (`func`/`az functionapp deploy`), the deployment storage container (which account, which identity), that the SPA build is packaged in the same artifact, rollback (redeploy previous artifact), and the post-deploy smoke check (terraform.md apply order step 7).

## Low findings

- AD-11 audit writers contradict S:290 (see 1.2).
- AD-14 server must reject non-GET without `X-Requested-With`; verify cookie `SameSite` is settable.
- Posting attempt count lost when the sweeper re-enqueues (1.2).
- Non-SGD invoices (1.3).
- `stuck_invoices` undefined (S:413).
- Per-supplier upload rate limit on `supplier-api`.
- Table Storage not covered by P-12 backups.
- PG migration role needs CREATE on its database; `pgcrypto` `CREATE EXTENSION` needs a privileged role on Flexible Server; say who runs it (operator step or migration).
- Stack table lacks Pillow, pydantic-settings, import-linter, Terraform and provider versions (terraform.md rule 9 wants the version table in the architecture).
- `pipeline` package must include `shared/quality-thresholds.json` from outside `backend/` (S:566); say how the build copies it.
- CAP-12 wording at S:319 (SPEC not yet changed).
- Partial-delivery invoicing vs "received so far" (B1 residual).
