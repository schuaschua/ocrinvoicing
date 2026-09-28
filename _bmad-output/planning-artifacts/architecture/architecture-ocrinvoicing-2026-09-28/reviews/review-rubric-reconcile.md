# Review: rubric and reconcile, ARCHITECTURE-SPINE (OCR Invoice Automation PoC)

- Reviewer: independent (rubric + reconcile)
- Date: 2026-09-28
- Inputs: `ARCHITECTURE-SPINE.md`, `.memlog.md`, `SPEC.md`, `docs/architecture/architecture.md` (P-1 to P-15), `docs/architecture/azure.md` (P-16 to P-20), `docs/standards/{azure,security,terraform,coding-style}.md`
- Accepted as user-approved and not flagged: P-2 departure (~$11-12/month, AD-12), P-13 departure (shared PostgreSQL server, AD-12; shared DI F0, AD-8). Both are named in the spine.

## Verdict

**Needs revision before epics.** The paradigm, layering, port boundaries, and most ADs are sound. All 20 capabilities are mapped. The spine does fix most of the real divergence points. But the pipeline's error and hand-off paths (AD-2, AD-3, AD-4, AD-10) have holes that let invoices get stranded or be routed differently by different stages. The shared DI F0 quota is counted per environment, so the count is wrong (AD-8). P-7 covers only the supplier master and leaves out extracted data (AD-11). Operations and monitoring are mostly undecided. None of these needs a paradigm change. Each can be fixed with a rule edit.

## Findings summary

| # | Severity | Where | Finding |
| --- | --- | --- | --- |
| F1 | High | AD-2, AD-3 | A crash between the status UPDATE and the enqueue strands the invoice forever |
| F2 | High | AD-2, AD-3, AD-4 | `PROCESSING_FAILED` and the `q-admin` sink have no transitions or owner, and it is unclear who writes `admin_item` for stage-level reasons |
| F3 | High | AD-10 vs AD-2 | Accounts retries are defined twice (5 in the adapter and 5 dequeues), so a failed post can end as `PROCESSING_FAILED` instead of `ACCOUNTS_API_ERROR` |
| F4 | High | AD-8 | The shared F0 quota (500 pages, 1 TPS) is counted and throttled per environment. Dev + Prod together can reach 1,000 pages and 2 TPS |
| F5 | High | AD-11 vs P-7 | Bank details in extracted fields, correction JSON, and image crops are not protected. P-7 applies to "extracted invoice data and the admin queue" too |
| F6 | Medium | AD-11 vs AD-13 | `analytics` has two writers (the refresh job and the post stage), which breaks AD-11's single-writer rule. CAP-14 alert ownership and de-duplication are undefined |
| F7 | Medium | AD-6 vs AD-16 | The supplier page shows reminders, but `supplier-api` never touches PostgreSQL. There is no defined store for reminders |
| F8 | Medium | AD-13 vs CAP-12 | The "daily" overdue list runs Monday to Friday only. This departure from the spec is not named. A timer that misses the DB-up slot skips a day, or a whole week for reminders |
| F9 | Medium | AD-3 / AD-4 | Admin **Correct** triggers full re-validation, but corrected fields have no confidence rule, so `LOW_CONFIDENCE` can loop forever. The duplicate check can match the invoice against itself |
| F10 | Medium | AD-9 / AD-4 | Race on duplicates: two copies validated at the same time both pass the fingerprint check |
| F11 | Medium | AD-6 / AD-14 | The upload contract has no size, type, or page limits (F0: 4 MB, first 2 pages only). HEIC and PDF handling for phash and EXIF is undefined |
| F12 | Medium | Operations (missing) | There are no alerts, no DB-up window, and no start/stop automation. Standards azure.md rules 17 and 18 (RG budgets, log-cap alert) were dropped |
| F13 | Medium | AD-17, security.md, terraform.md | Repo host and replacements for the GitHub-specific rules are undecided. The shared stack has no approval gate. One deploy identity could reach both environments |
| F14 | Medium | P-15, P-20, P-12 | Storage redundancy and PG geo-backup are not stated (GRS would break P-15). SWA's resource region may not be `southeastasia` (P-20). There is no recovery for blob or Table data (P-12) |
| F15 | Medium | AD-5 / AD-6, CAP-2 | For goods-in, it is unclear who resolves the supplier from `delivery_id` and when. Doing it at upload needs PostgreSQL |
| F16 | Medium | Deferred (CAP-10) | The deferral leaves the model-selection seam open, so extract and correction code can diverge |
| F17 | Low | various | Smaller gaps: listed under Low findings below |

---

## Task A: good-spine checklist

### A1. Does it fix the real divergence points for the epics?

The spine fixes these well:
- One state column with conditional UPDATEs (AD-3).
- A thin claim-check message (AD-2).
- One reason catalogue (AD-4).
- Supplier identity set once (AD-5).
- Ports with one adapter each and config-selected (AD-10).
- Single-writer schemas (AD-11).
- Canonical ids, money, dates, and errors (Consistency Conventions).

It misses or leaves ambiguous these divergence points:
- **Stage-to-stage hand-off atomicity** (F1). The stage that updates status and the stage that consumes the next message can disagree after a crash.
- **Who routes to the admin queue, and how** (F2). Is `q-admin` a stage that every stage enqueues to? Or only a poison sink? And who writes `intake.admin_item` for `UNREADABLE`, `EXTRACTION_QUOTA` and `ACCOUNTS_API_ERROR`? The quality, extract and post epics will each answer this differently.
- **Retry ownership for accounts posting** (F3).
- **Who enqueues after admin actions.** Correct needs a `q-validate` message and Approve needs a `q-post` message. The Structural Seed shows `staff-api -> q`, but no rule says that the actor making a transition must also enqueue the next stage's message.
- **Required-field set for the 98% threshold.** DI `prebuilt-invoice` returns many optional fields. "Any field below 0.98" (AD-8) with no field list means each developer picks a set. The SPEC says "any field", so either bind a canonical list in `domain/` or confirm with Dj that every returned field (including line items) counts. This choice decides whether the 90% straight-through target can be reached.
- **Invoice-to-PO and line-to-material linkage.** CAP-5 needs the PO. CAP-14 to CAP-17 need "same material". Nothing says how an invoice finds its PO (extracted PO number? the delivery?), or how an invoice line maps to `master.materials`. The validate epic and the analytics epic will each invent a mapping.
- **Quality thresholds shared by client and server** (CAP-3). The device check and the `quality` stage can drift. Put the thresholds in one published config.
- **Alert de-duplication and recipients** (F6, AD-16). Nothing sets who receives CAP-14 and CAP-15 mail, or how repeat alerts are suppressed.

### A2. Is every AD Rule enforceable, and does it prevent its stated divergence?

| AD | Enforceable? | Prevents its divergence? | Notes |
| --- | --- | --- | --- |
| AD-1 | Yes | Yes | On Flex, max instance count is **per app** (and `host.json` queue batch size is app-wide). "The `extract` function runs with max instances 1" (AD-8) therefore caps the whole `pipeline` app. Either state that the whole app is capped, or give `extract` its own app. Also verify the minimum allowed `maximumInstanceCount` on Flex before binding it. |
| AD-2 | Yes | Partly | See F1 and F3. "The `q-admin` sink routes poisoned items" is unclear: each queue has its own `-poison` queue, so a sink needs a trigger on 4 poison queues. |
| AD-3 | Yes (SQL pattern) | Partly | The diagram lacks `PROCESSING_FAILED` transitions from `received`, `awaiting_extraction`, `awaiting_validation` and `ready_to_post`. It also lacks the case where the row does not exist yet (quality stage poisoned before insert). The "zero rows = duplicate, ack" rule strands invoices (F1). |
| AD-4 | Yes | Partly | It does not say whether single-reason stages (quality, extract, post) write `admin_item` with a crop/fields payload. |
| AD-5 | Yes (no UPDATE path; a DB trigger could enforce it) | Yes | Suggest a DB trigger or column grant so the rule is mechanically enforced. |
| AD-6 | Yes | Yes | Missing: one active link per supplier (does reissue revoke the old one?), the delivery channel for the link, and upload limits (F11). |
| AD-7 | Yes | Yes | Re-enqueue creates a new message with a fresh TTL, so "7 days covers a weekend" is not really the limit. That is harmless, but state that the loop is unbounded while the DB is down. |
| AD-8 | Yes | **No** for the shared quota (F4) | |
| AD-9 | Yes | Partly | Race (F10). phash on PDFs needs a rasterizer, which is not in the Stack (F11). |
| AD-10 | Yes | Partly | Double retry (F3). Idempotency on `invoice_id` is an assumption about the real accounts API. Add it to Q9 as a must-verify item. |
| AD-11 | Yes (DB grants) | Partly | P-7 scope (F5). Two writers on `analytics` (F6). HMAC input normalisation is not fixed (spacing and leading zeros in account numbers will cause false `BANK_CHANGED`). |
| AD-12 | Operational (manual) | Partly | No DB-up window is defined, yet AD-13 depends on one (F12). |
| AD-13 | Yes | Partly | Weekday-only daily list (F8). A timer that "exits and runs at the next slot" loses a week for reminders. |
| AD-14 | Partly | Partly | "Every route checks its role" has no role-to-route matrix, so two developers will guard finance and procurement views differently. Add a small matrix (admin, finance, procurement, management, goods_in → views and actions). |
| AD-15 | Yes | Yes | Side effect: an admin item older than 30 days loses its image, so CAP-9 cannot show the crop. State the fallback. |
| AD-16 | Yes | Yes | Recipients and de-duplication are undefined. P-15 residency is open, which the spine names. |
| AD-17 | Partly | Partly | P-17's "a resource missing any tag is not deployed" has no enforcement mechanism (Azure Policy deny, or a plan check in the pipeline). The shared stack has no gate (F13). |

### A3. Could anything under Deferred let two units diverge?

- **CAP-10 custom models (F16): yes.** The Deferred section leaves the extract-side seam open. Without a decided seam, the correction UI epic and the extract epic will build incompatible shapes. Fix this now, even though training waits on Q10b:
  - `ExtractionPort.extract(blob_ref, model_id)`;
  - a `master.supplier_extraction_model(supplier_id, layout_key, model_id)` lookup that defaults to `prebuilt-invoice`;
  - a schema for the correction JSON: canonical field id, old value, new value, bounding region, `invoice_id`, `supplier_id`.

  Also note that the correction JSON is deleted at 30 days (AD-15). Any training set therefore has to be built within that window. This constrains Q10b, so say so.
- **Q9 production link:** safe, confined to adapters.
- **S0 move:** safe (configuration), provided the page cap is a setting (F4).
- **"Production retention and HA … covered by P-11 and P-12":** mislabelled. P-12 (RTO/RPO 24h) is a **PoC** rule, not a deferral, and the spine does not show how blob and Table data meet it (F14).
- **Screen layouts:** safe.

### A4. Coverage of the 20 SPEC capabilities

All 20 capabilities appear in the map. Weakly served:
- **CAP-2:** supplier resolution timing (F15).
- **CAP-3:** server-side `UNREADABLE` cannot prompt a retake. That is acceptable, but name it.
- **CAP-7:** EXIF stripping is open and named. HEIC is not addressed.
- **CAP-10:** deferred with the seam open (F16).
- **CAP-12:** "daily" departure (F8).
- **CAP-13:** reminder display store (F7).
- **CAP-14:** price-rise alert has no owner (F6).
- **CAP-15:** recipients are undefined.
- **CAP-17 / CAP-19:** on-time rate needs goods-received dates from `PurchasingPort` inside the analytics refresh. That is allowed through the port, but the analytics refresh is not listed as a `PurchasingPort` consumer.

### A5. Is every dimension decided, deferred, or open?

| Dimension | Status | Gap |
| --- | --- | --- |
| Compute, messaging, data, identity | Decided | See findings |
| Deployment and environments | Mostly decided (AD-17) | Repo host, ADO replacements for the GitHub rules, shared-stack approval, and per-environment deploy identities are all undecided (F13). How the SWA deployment token is obtained is unstated (it must not be a pipeline variable, per P-18). Fetch it at run time through the WIF connection. |
| Infrastructure | Decided | Storage redundancy and PG geo-backup are unstated (F14). SWA region vs P-20 needs verifying. The Stack table lacks Terraform, azurerm/AVM, MSAL, pydantic-settings, azure-functions, azure-identity and storage SDK versions (terraform.md rule 9 wants a version table). |
| Operations and monitoring | **Mostly undecided** | Only App Insights, a log cap, and a $8 subscription budget exist. Nothing covers alerts, the DB-up window or start/stop automation, a stuck-invoice sweeper, or a runbook (F12). |
| Security | Mostly decided | Gaps: P-7 scope (F5), upload limits (F11), security headers on SWA (security.md rule 25, through `staticwebapp.config.json`), and the accepted-exceptions records for security.md rule 4 and azure.md rule 12. |
| Testing seams | Undecided | coding-style.md rule 23 requires an injected clock and fakes. Timers, overdue logic and the 30-day and weekly rules all need a `Clock` port. Name it in `ports/`. |

---

## Task B: reconcile against inputs

### Principles

| Principle | Status in spine | Issue |
| --- | --- | --- |
| P-1 PaaS only | Honoured | None |
| P-2 $10 ceiling | Departure named (approved) | The budget alert is subscription-level $8 only. azure.md rule 17 (RG budgets at 90/100/110% plus forecast) is in the memlog but dropped from the spine. Every AD should state its cost: AD-3, AD-5, AD-7 and AD-13 omit it. They are trivially $0, but P-2 says "every AD". |
| P-3 event-driven, failed step goes to admin queue after retries | Partly | F1, F2, F3 |
| P-4 adapter per external system | Honoured | Analytics refresh access to PO/GRN must go through `PurchasingPort` too; make that explicit. |
| P-5 identity from link or delivery | Honoured | F15 (timing for goods-in) |
| P-6 TLS + authenticated caller | Honoured | PG firewall "allow Azure services" follows the baseline. Fine. |
| P-7 bank details encrypted, admin-only | **Handled wrongly (partial)** | F5 |
| P-8 upload links | Mostly | One active link per supplier and the link delivery channel are not decided. "Supplier master events" is not defined (who or what emits them). |
| P-9 DI only, 98% | Honoured | The required-field set is not decided (A1). |
| P-10 analytics from pre-computed views | Honoured in intent | Two writers (F6). CAP-18's "counts of flagged and duplicate invoices" must also come from `analytics.*`, not `intake.admin_item`. State that. |
| P-11 1-month retention by platform | Honoured | The crop disappears for admin items older than 30 days (A2). |
| P-12 RTO/RPO 24h | **Dropped for blob and Table** | F14. Only the PG 7-day backup is stated. The Deferred section mislabels P-12 as deferred. |
| P-13 two environments, gated | Departures named (approved) | F13: the shared stack holding the Prod DB is applied without a gate, and a single ADO identity could reach both DBs. The shared F0 means Dev tests eat Prod's quota (F4). |
| P-14 single region | Honoured | None |
| P-15 residency | Partly | ACS is open and named. **Unnamed:** storage account redundancy (GRS/RA-GRS replicates to East Asia), PG geo-redundant backup, and the SWA resource location (F14). |
| P-16 naming | Honoured | The departure from standards naming is named. Check that global-uniqueness collisions are acceptable (`babaloosealngst01`). |
| P-17 tags | Stated | No enforcement mechanism for "not deployed if missing" (A2). |
| P-18 MI + Key Vault | Honoured | The SWA deployment token must be fetched at run time, not stored as a pipeline variable (A5). |
| P-19 Entra + MFA + roles | Honoured | Role-to-route matrix missing (A2). |
| P-20 approved services, all in `southeastasia` | **Possibly broken, unnamed** | Static Web Apps resource regions are a limited set that may not include `southeastasia`. Verify. If it is not available there, either name the departure (the static content is served globally and holds no data) or host the SPAs as Storage static websites in `southeastasia`. |

### SPEC constraints and quiet requirements

- **"A daily overdue list" (CAP-12):** the spine runs it on weekdays only, and the departure is not named (F8).
- **"The supplier is not notified" (CAP-7):** this is a quiet anti-fraud requirement. No supplier-facing surface (the upload response, the reminders page, or email) should ever reveal check outcomes. Add it as a rule on `supplier-api` and AD-16. The upload response is always "received".
- **"Failed calls retry, then go to the admin queue with the API error" (CAP-11):** broken by the double-retry ambiguity (F3).
- **"No invoice longer than 2 pages" and DI F0 limits:** not enforced at upload (F11).
- **"Supplier master holds bank details and phone" (Assumptions):** the spine assumes `staff-api` owns `master`. In the target state, the supplier master may live on-premises (accounts system). Add it to Open Questions or Q9 (is the supplier master a third external system behind a port?).
- **"90% straight-through" (Success signal):** there is no metric to measure it. Add an `analytics` STP-rate figure. The per-field 98% rule across all DI fields threatens this target (A1). Record it as a risk.
- **"Links issued and revoked automatically":** the trigger and delivery channel are undefined (P-8 row).

### Standards (docs/standards) departures

The spine names these departures: GitHub OIDC replaced by ADO WIF; P-16 naming and P-17 tags replacing the standard ones; terraform.md rule 3 "share nothing" (shared stack); security.md rule 4 (anonymous `supplier-api`).

These are not named or not handled:
- **azure.md rule 12:** `AllowAnonymous` at the edge must be an accepted exception. Record it with security.md rule 4.
- **azure.md rules 17 and 18:** RG budgets and the 90% log-cap alert.
- **azure.md rule 13:** the migration runner's temporary firewall rule. ADO hosted agents need the same pattern as terraform.md rule 36.
- **azure.md rule 7:** runtime identities should be user-assigned. The spine says "managed identity" without the type.
- **security.md rules 10, 28, 30 and terraform.md rules 31-35:** these are GitHub-specific (Dependabot, secret scanning, `workflow_dispatch`, destroy workflow). Once the repo host is decided, state the ADO substitutes and the manual-deploy-only and destroy-guard equivalents.
- **security.md rule 25:** security headers for the SPAs and APIs.
- **coding-style.md rule 23:** test seams (Clock, DI fake, accounts fake). Only the adapters are implied.
- **Accepted-exceptions tables:** none of the named departures are recorded in the standards' accepted-exceptions tables, which the baselines require ("never weaken silently").

---

## Detailed findings and fixes

### F1 (High): Stranded invoices after a partial hand-off (AD-2, AD-3)

AD-2 says: "change status, then enqueue next". AD-3 says: "zero rows changed means duplicate; ack and do nothing". Suppose the function crashes after the UPDATE commits and before the enqueue. The redelivered message then finds zero rows, acks, and never enqueues the next stage. The invoice sits in `awaiting_*` forever.

**Fix.** Two changes to AD-3:
- On zero rows, read the current status. If it equals this transition's `to`, re-enqueue the next stage's message and then ack. This is safe because every consumer is idempotent.
- Add a `pipeline` sweeper timer that re-enqueues invoices sitting in a non-terminal, non-admin state for more than N hours while the DB is up.

### F2 (High): The admin-queue path is under-specified (AD-2, AD-3, AD-4)

Nothing says:
- which component writes `intake.admin_item` for `UNREADABLE`, `EXTRACTION_QUOTA` and `ACCOUNTS_API_ERROR`;
- which transitions `PROCESSING_FAILED` performs, from which states;
- what happens when the quality stage poisons before the row exists.

**Fix.** Declare one domain function, `route_to_admin(invoice_id, from_status, reasons[], evidence)`, that every stage calls in-process. It performs the state transition and inserts the `admin_item` row in one transaction.

Define the `q-admin` sink as a trigger on **each** `*-poison` queue. It:
- creates a minimal `received` row if none exists (from blob metadata);
- then transitions `any non-terminal → in_admin_queue` with `PROCESSING_FAILED`.

Add these transitions to the state diagram. Also state that the actor of a transition enqueues the next stage: the `staff-api` enqueues `q-validate` on Correct and `q-post` on Approve.

### F3 (High): Double retry for accounts posting (AD-10 vs AD-2)

AD-10 has "5 retries with backoff" and AD-2 has `maxDequeueCount` 5. If the adapter retries in-process and then throws, the queue retries 5 more times, and the poison sink labels the invoice `PROCESSING_FAILED` instead of `ACCOUNTS_API_ERROR`. CAP-11 then fails.

**Fix.** The post stage catches `AccountsError` and never throws for it:
- On attempts 1 to 4 (from `dequeue_count`, or an attempt counter in the message), re-enqueue with exponential visibility delay.
- On attempt 5, route to admin with `ACCOUNTS_API_ERROR` and the API error.

The adapter does not retry. Only unexpected errors reach the poison queue.

### F4 (High): The shared F0 quota and rate are tracked per environment (AD-8)

`intake.di_usage` lives in `invoicing_dev` and in `invoicing_prod` separately, and each counts to 500. The F0 quota (500 pages) and 1 TPS limit belong to the single shared resource. Each environment's `extract` also throttles to 1 rps independently, so combined traffic reaches 2 rps.

**Fix.**
- Add a per-environment setting `DI_MONTHLY_PAGE_CAP` (for example Dev 100, Prod 400; the sum must not exceed 500).
- Map DI's quota-exceeded response to `EXTRACTION_QUOTA`.
- Handle 429 by re-enqueuing with a delay that honours `Retry-After`, without burning dequeue count.
- State that the throttle is per environment and that 429 backoff is the cross-environment guard.
- Also fix AD-1 and AD-8 wording: max instances is app-wide on Flex (see A2).

### F5 (High): P-7 covers only the master (AD-11)

P-7 applies to "the supplier master, **extracted invoice data** and the admin queue". The extracted bank-detail fields in `intake` are not encrypted, and finance and procurement (and analytics) can read them. The raw correction JSON (AD-15) and the photo crop can also expose them.

**Fix.**
- Store extracted `payment_details` / bank fields with the same pgcrypto + HMAC scheme, in a column that only the admin role may read.
- The validate stage compares only HMACs.
- Correction JSON for bank fields holds only the HMAC or ciphertext.
- Image and crop endpoints are admin-only, or bank regions are masked for non-admin roles.
- Fix the HMAC input normalisation (strip spaces and punctuation, upper-case) in `domain/`.

### F6 (Medium): Two writers on analytics; CAP-14 alert owner (AD-11 vs AD-13)

**Fix.** Either drop the post-stage incremental update (the daily refresh is enough for P-10), or list the post stage as a second writer calling the same refresh function. Assign the price-rise alert (CAP-14) and the watchlist alert (CAP-15) to the refresh job. De-duplicate through an `analytics.alert` table with a unique key `(rule, supplier_id, material_id, period)`. Name the recipients (Entra app-role members, or a configured distribution list).

### F7 (Medium): Supplier page reminders need a store (AD-6 vs AD-16)

**Fix.** The CAP-13 timer writes each active reminder to a Table (`supplierreminders`, partitioned by `supplier_id`). `supplier-api` reads it with the link check. It remains PG-free.

### F8 (Medium): Daily list on weekdays only, and missed slots (AD-13)

**Fix.**
- Name the departure from CAP-12's "daily" (Monday's list covers the weekend), or schedule weekend runs when the DB is up.
- Make timers run hourly inside the DB-up window, with a `job_run(job, period)` guard so each job runs once per period and catches up after a late DB start.

### F9 (Medium): Re-validation after Correct (AD-3, AD-4)

**Fix.**
- Corrected fields carry `source=admin` and are exempt from the confidence check.
- The duplicate check excludes the invoice's own id.
- An Approve that overrides a reason is recorded in `audit`.

### F10 (Medium): Duplicate race (AD-9)

**Fix.** In the validate stage, take a PostgreSQL transaction-scoped advisory lock on `supplier_id` around the fingerprint and phash check and the status transition. Alternatively, state that validate runs single-instance with batch size 1. Today it only happens to be single-instance because of F4's app-wide cap.

### F11 (Medium): Upload contract limits (AD-6, AD-14)

**Fix.** Server-side limits on `supplier-api` and the goods-in route:
- allowed types JPEG, PNG, HEIC/HEIF and PDF;
- at most 4 MB (F0);
- PDFs of at most 2 pages;
- anything else is rejected with a retake/resize message.

Also add to the Stack:
- `pillow-heif`, for HEIC decoding, EXIF and phash;
- a PDF rasterizer such as `pypdfium2`, for phash of PDFs (and PDFs go to `NO_PHOTO_DATE` per CAP-7).

### F12 (Medium): Operations and monitoring (missing dimension)

**Fix.** Add an AD for operations covering:
- **DB-up window:** define it (for example weekdays 08:00-20:00 SGT), and automate start/stop with a `pipeline` timer using a managed identity that holds a narrowly scoped role on the server. This is ~$0 and removes the risk of forgetting.
- **Alerts** to an action group (email Dj): poison-queue length > 0; oldest non-terminal invoice age; DI pages ≥ 80% of the cap; admin queue age; Log Analytics 90% of cap (azure.md rule 18); RG budgets (rule 17).
- **Runbook:** a short one in `infra/README`.

### F13 (Medium): Delivery and identity gaps (AD-17)

**Fix.**
- Name the repo host.
- Give each environment its own ADO service connection and identity (Dev's cannot reach `invoicing_prod` or the Prod RG), plus a separate gated connection for the `shared` stack.
- Put the shared stack behind the same manual approval as Prod.
- List the ADO substitutes for security.md rules 10, 28 and 30 and terraform.md rules 31-35 (dependency scanning, secret scanning, manual-only deploy, destroy guard).
- Record all standards departures in the accepted-exceptions tables.

### F14 (Medium): Residency and recovery (P-15, P-20, P-12)

**Fix.**
- State LRS for all storage accounts and geo-redundant backup off for PostgreSQL (P-15).
- Verify SWA region availability. If `southeastasia` is not offered, name the P-20 departure or switch to Storage static websites.
- For P-12, enable blob soft delete (7 days) on `images`, `corrections` and the Table account, or name that blob and link data have no RPO. Rebuilding `supplierlinks` means reissuing links.

### F15 (Medium): Goods-in supplier resolution (AD-5, AD-6)

**Fix.** Decide that the `quality` stage (not `staff-api`) resolves `supplier_id` from `delivery_id` through `PurchasingPort` when it creates the row. The goods-in upload then stays PG-free like supplier uploads. Only `delivery_id` goes in the blob metadata.

### F16 (Medium): CAP-10 seam (Deferred)

**Fix.** See A3: bind `ExtractionPort.extract(blob_ref, model_id)`, the supplier-to-model lookup, and the correction JSON schema now. Leave only the training mechanics deferred.

### F17 (Low findings)

- The spine does not state a rule that the supplier is never told check outcomes (CAP-7 quiet requirement; see Task B).
- One active link per supplier: reissuing revokes the previous link (P-8).
- Security headers through `staticwebapp.config.json` and the Functions responses (security.md rule 25).
- The Stack table is missing Terraform, azurerm/AVM, MSAL, pydantic-settings, azure-functions, azure-identity and azure-storage SDK versions.
- Every AD should carry a Cost line (AD-3, AD-5, AD-7, AD-13 omit it).
- Add a `Clock` port for timer and date logic (coding-style.md rule 23).
- CAP-3: name that a server-side `UNREADABLE` goes to the admin queue and cannot prompt a retake. Share the blur and darkness thresholds between the client and the `quality` stage from one config.
- The accounts API's idempotency on `invoice_id` is unverified for the real system. Add it to Q9.
- Add a straight-through-rate metric for the 90% success signal. Record the per-field 98%-on-all-fields risk to that target.
- Supplier master ownership in the target state (on-premises?) should be an open question.
- Use user-assigned identities per azure.md rule 7.
