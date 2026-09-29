---
stepsCompleted: [1, 2, 3, 4]
inputDocuments:
  - _bmad-output/specs/spec-ocr-invoice-automation/SPEC.md
  - _bmad-output/planning-artifacts/architecture/architecture-ocrinvoicing-2026-09-28/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/ux-designs/ux-ocrinvoicing-2026-09-28/DESIGN.md
  - _bmad-output/planning-artifacts/ux-designs/ux-ocrinvoicing-2026-09-28/EXPERIENCE.md
  - docs/architecture/architecture.md
  - docs/architecture/azure.md
  - docs/standards/coding-style.md
  - docs/standards/security.md
  - docs/standards/azure.md
  - docs/standards/terraform.md
---

# ocrinvoicing - Epic Breakdown

## Overview

This document breaks the ocrinvoicing requirements into epics and stories. The requirements come from the spec (`SPEC.md`, used in place of a PRD), the UX design contract, and the architecture spine. FR numbers match the spec's CAP numbers (FR1 = CAP-1).

## Requirements Inventory

### Functional Requirements

- **FR1 (CAP-1):** A supplier submits an invoice photo or PDF from their phone through a personal upload link, and the link identifies the supplier. An upload is recorded against the link's supplier, whatever supplier ID is printed on the invoice. The supplier can't edit extracted data. Links are issued and revoked only by the operator-run supplier load script (`--replace-link`, `--revoke`), an accepted departure from P-8 (AD-6).
- **FR2 (CAP-2):** Paper invoices arriving with goods are captured at warehouse goods-in and linked to that delivery and supplier. They enter the same intake as uploads.
- **FR3 (CAP-3):** A blurred, dark or cropped photo is refused before submission with a retake prompt. After 2 refusals, the supplier may send it anyway. The server re-checks it with the same thresholds: if it passes, it is processed normally, and if it fails, it goes to the admin queue as `UNREADABLE` (AD-6).
- **FR4 (CAP-4):** Invoice fields are extracted from any supplier layout, handwriting included, without per-supplier setup. Each field carries a confidence score, and any checked field (AD-18) below 98% sends the invoice to the admin queue. Other fields are stored but not checked, an accepted departure from P-9.
- **FR5 (CAP-5):** An invoice whose pre-tax sub-total differs from the PO price × the quantity received and not yet invoiced, by more than the larger of 1% and 1.00 (AD-19), goes to the admin queue, not to the accounts system.
- **FR6 (CAP-6):** A duplicate goes to the admin queue. A duplicate is the same supplier, number, amount and date, or a document that looks visually the same (for example, a re-photographed copy).
- **FR7 (CAP-7):** When the photo was taken before the PO's latest goods-received date or more than 30 days after it, the invoice goes to the admin queue, and the supplier is not notified. A PDF or scan with no photo date also goes to the admin queue.
- **FR8 (CAP-8):** An invoice whose bank details differ from the supplier master never auto-posts. The admin queue shows the supplier's phone number on file for a call-back.
- **FR9 (CAP-9):** One admin queue receives every exception, showing the reason, the relevant photo crop and the flagged fields. The admin resolves each item from there.
- **FR10 (CAP-10):** Admin corrections improve future extraction for that supplier's format. Training is deferred in the architecture; only the seam and the stored corrections are in scope.
- **FR11 (CAP-11):** Clean invoices post automatically to the accounts system through its XML API. Failed calls retry, then go to the admin queue with the API error.
- **FR12 (CAP-12):** An overdue list, made each weekday, shows POs past their expected date with no invoice, grouped by supplier. A PO is overdue the day after its expected date, and one due at the weekend appears on Monday's list (AD-13).
- **FR13 (CAP-13):** A supplier with an overdue PO gets a reminder through the upload app, with no manual sending. The reminder repeats weekly until the invoice arrives.
- **FR14 (CAP-14):** Finance and procurement compare suppliers' unit prices for the same material side by side. A posted unit price more than 2% above the supplier's previous posted price for that material (AD-20) triggers an alert naming the supplier, the material and the invoices.
- **FR15 (CAP-15):** A supplier is watchlisted after 3 or more price increases within a year, an average of 7 or more days late, or prices 5% or more above the cheapest supplier of the same material. Procurement and management are notified with the evidence.
- **FR16 (CAP-16):** For a watchlisted supplier, alternatives already invoicing the same materials are shown, ranked by price and speed.
- **FR17 (CAP-17):** Procurement sees a supplier scorecard, with on-time rate and price trend per material, derived from posted invoices.
- **FR18 (CAP-18):** Finance sees a monthly view per supplier: spend, price-creep alerts, and counts of flagged and duplicate invoices.
- **FR19 (CAP-19, could-have):** Each delivery shows the PO promised date, the invoice delivery date, the goods-received date, and the gaps between them.
- **FR20 (CAP-20):** A simulated PO and goods-received data source stands in for the external database. FR5, FR12 and FR19 run end to end against it, and switching to the real database changes no capability behaviour.

### NonFunctional Requirements

- **NFR1 (P-1):** PaaS or serverless only. No VMs or other IaaS.
- **NFR2 (P-2):** Monthly Azure spend has a US $10 ceiling. The accepted actual is about $11–12. A budget alert fires at $8, with resource-group budgets as the standards require. Every component states its cost.
- **NFR3 (P-3):** Intake stages hand off through queues only. A failed step retries, then goes to the admin queue.
- **NFR4 (P-4):** The accounts API and the PO/GRN database are each reached only through their own adapter. Swapping a simulation for the real system changes only the adapter.
- **NFR5 (P-5):** The supplier comes only from the link or the delivery, never from the invoice.
- **NFR6 (P-6):** Every call uses TLS and an authenticated caller.
- **NFR7 (P-7):** Bank details are encrypted at rest wherever they appear, and only the admin role can read them. A changed bank account never auto-posts.
- **NFR8 (P-8):** Upload links are unguessable (256 random bits) and per supplier. They are issued and revoked by the operator-run load script, an accepted departure from P-8 (AD-6).
- **NFR9 (P-9):** Document Intelligence is the only AI, starting with its prebuilt invoice model. The confidence threshold is 98% on the AD-18 checked fields only, an accepted departure from P-9.
- **NFR10 (P-10):** Analytics read only from pre-computed summary tables.
- **NFR11 (P-11):** Images and raw corrections are deleted after 1 month by platform lifecycle rules.
- **NFR12 (P-12):** RTO and RPO of 24 h, using platform backups only.
- **NFR13 (P-13):** Dev and Prod only. Prod changes go through the pipeline with manual approval. No real supplier data in Dev. Sharing one database server and one DI resource between them is an accepted departure.
- **NFR14 (P-14, P-15):** Single region, `southeastasia`. All data is stored and processed there, storage is LRS, and there is no geo-backup.
- **NFR15 (P-16, P-17):** Names follow `babaloo-sea-lng-<type>-<nn>` (Dev 01–09, Prod 11–19, shared 21–29). The five mandatory tags are applied by the pipeline.
- **NFR16 (P-18):** Managed identities everywhere. The only secrets (the pgcrypto and HMAC keys) are in Key Vault.
- **NFR17 (P-19):** Staff sign in with Entra ID and MFA through Security Defaults (an accepted departure) and get role-based access. Suppliers use their links.
- **NFR18 (P-20):** The approved services are PostgreSQL Flexible Server, Document Intelligence and Azure DevOps Pipelines. Every service runs in `southeastasia`.
- **NFR19 (spec):** 90% of invoices reach the accounts system with no admin involvement.
- **NFR20 (spec):** The PoC is tested at no more than 500 invoice pages a month, and no invoice is longer than 2 pages.
- **NFR21 (UX):** WCAG 2.2 AA on both surfaces.
- **NFR22 (standards):**
  - money uses `Decimal`;
  - dates are ISO dates and timestamps are ISO 8601 UTC;
  - the domain package is framework-free;
  - configuration comes from one settings object;
  - SQL uses bound parameters;
  - dependency versions are pinned;
  - there is no dead code;
  - every acceptance criterion has a test named after its story;
  - coverage is 80% for the backend and 60% for the web app;
  - migrations are expand-then-contract.
- **NFR23 (standards):** Logs never contain field values, tokens, headers or bank details. There is one trace per `correlation_id`, and audit tables are append-only.

### Additional Requirements

- **No starter template.** This is a greenfield repo in Azure Repos.
  - **Backend:** a Python 3.13 Functions v2 project with four apps (`supplier_api`, `staff_api`, `pipeline`, `accounts_sim`), sharing one `invoicing` package (domain / ports / adapters / apps).
  - **Web:** two Vite + React + TS SPAs, each packaged into its API app.
  - **Infra:** Terraform per `terraform.md`.
- **Infrastructure (AD-17):**
  - One subscription with three resource groups (`shared`, `dev` and `prod`), named per P-16.
  - Every resource belongs to one step of the AD-17 step table: 1. `infra/bootstrap/` (operator: state, resource groups, deploy identities, two Entra app registrations per environment, the `ACS Email Sender` role, the $8 subscription budget) → 2. `shared/foundation` (PostgreSQL B1ms PG 18 with `invoicing_dev` and `invoicing_prod`, DI F0 with a custom subdomain, ACS Email and its domain, the PostgreSQL firewall open for the PoC) → 3. operator RBAC step → 4. `<env>/foundation` → 4b. operator PGP key step → 5. operator database step → 6. migrations → 7. `<env>/app` → 8. operator redirect-URI step → 9. code deploy.
  - Azure DevOps pipelines authenticate with workload identity federation, using a separate deploy identity per stack owner. Dev applies its saved plan automatically on merge, an accepted departure from `terraform.md` rules 26 and 33. Prod and `shared` apply only after manual approval.
- **CI checks:**
  - lint and format;
  - tests and coverage;
  - `pip-audit` and `npm audit` on every PR, plus a weekly run;
  - `gitleaks` as a required check;
  - Alembic migrations run in the pipeline, never at app start.
- **Compute (AD-1):**
  - Four Flex Consumption apps per environment, each with its own plan and user-assigned identity.
  - All on-demand, with timers in UTC.
  - The `pipeline` app's `host.json` sets `batchSize` 1 and `newBatchThreshold` 0.
- **Messaging (AD-2):**
  - Storage Queues `q-quality`, `q-extract`, `q-validate` and `q-post`.
  - `QueueMessage{invoice_id, correlation_id, first_enqueued_at, attempt}`.
  - The unit that performs a transition enqueues the next stage.
  - A sweeper timer runs every 15 minutes and re-enqueues stranded invoices by the AD-2 status map, never `in_admin_queue`. It also deletes `uploadkeys` rows older than 24 h.
  - Each `*-poison` queue has a trigger that calls `route_to_admin(PROCESSING_FAILED)`, only while the invoice is still in that queue's input state or in its claim state with an expired lease.
- **State machine (AD-3):**
  - A single `status` with `status_changed_at` and `claimed_until`.
  - Every transition is a conditional UPDATE.
  - Stages claim first (`extracting`, `validating` or `posting`, with a 10-minute lease).
  - Side-effect results are saved under `invoice_id` and reused on retry.
  - Admin actions are Correct, Approve, Re-extract, Retry intake and Reject. Reject is refused once `accounts_ref` exists.
  - Posting failures are counted in `intake.invoice.post_failures`, and the post claim respects `next_attempt_at`.
- **Admin queue (AD-4):**
  - The 12-code reason catalogue is in `domain/reasons.py`.
  - `route_to_admin` is the only way in, and it writes one `admin_item` row per reason in the same transaction.
  - Validation is a single stage that routes all reasons at once.
  - The printed-supplier check compares `vendor_tax_id` with the master `tax_id` when both exist, and otherwise requires a rapidfuzz token-set similarity of 85 or more between `vendor_name` and the supplier's name (AD-19).
  - An invoice's open reasons are the `admin_item` rows of its latest `routing_id`.
- **Intake (AD-5, AD-6):**
  - Blob metadata is `IntakeBlobMetadata{…, device_check}`.
  - Only the `quality` stage inserts the invoice row, with `ON CONFLICT DO NOTHING`.
  - Links are stored in the `supplierlinks` table as a SHA-256 hash.
  - The upload path never touches PostgreSQL.
  - Uploads accept JPEG, PNG or PDF up to 4 MB.
  - An `Idempotency-Key` is stored in `uploadkeys` for 24 h.
  - The `quality` stage handles EXIF orientation, the readability re-check, PDFs over 2 pages, `photo_taken_at` and the phash.
  - The `supplierreminders` table is written by the weekly job and cleared by `validate` when an invoice arrives.
- **Database down (AD-7):** consumers re-enqueue with a 15-minute delay while PostgreSQL is stopped, and 429 responses honour `Retry-After`.
- **Extraction (AD-8):**
  - Only the DI adapter calls DI: API `2024-11-30`, managed identity, at most 1 request per 2 s in each environment.
  - Page caps are Dev 100 and Prod 400, counted in `intake.di_usage`.
  - A `ModelSelector` port picks the model, defaulting to `prebuilt-invoice`.
  - Results are stored as AD-18 rows (`extraction_run`, `invoice_field`, `invoice_line`) with confidence, page and polygon. The raw DI result is not stored.
- **Duplicates (AD-9):** the fingerprint, plus a 64-bit phash with Hamming distance ≤ 8, checked under an advisory lock per supplier.
- **Accounts and purchasing (AD-10):**
  - `AccountsPort` is idempotent on `invoice_id` and the adapter never retries. The `post` stage backs off at 1, 5, 15 and 60 min, and goes to `ACCOUNTS_API_ERROR` on the 5th failure.
  - `PurchasingPort` offers `get_po`, `get_receipts`, `get_delivery`, `list_overdue_pos` and `get_delivery_dates`.
  - The simulations are schemas `sim_purchasing` and `sim_accounts` (the `accounts-sim` app).
- **Data and security (AD-11):**
  - Schemas each have a single writer: `intake`, `master` (written by the supplier load script), `analytics`, `sim_*` and `audit`.
  - Bank details are stored per bank field id as `pgp_pub_encrypt` ciphertext plus an HMAC fingerprint, normalised first, from their first write (the `extract` stage). Only `staff-api` holds the private key, and only the admin role sees plaintext.
  - Each environment has the AD-11 database logins (the `pipeline`, `staff-api` and `accounts-sim` identities, Dj's user, the deploy identity), with Entra-only auth. `supplier-api` has none. Each login can connect only to its own environment's database, and every schema grant is an Alembic migration.
  - `pgcrypto` is allow-listed.
- **Operations (AD-12, AD-13):**
  - The database server is stopped by hand outside weekdays 9am–9pm.
  - Timers run at 01:30, 04:30 and 08:30 UTC on weekdays, and each job does its work at most once a day.
  - The analytics refresh is the only writer of `analytics`, working incrementally from a watermark, and it de-duplicates alerts.
- **Web access (AD-14):**
  - Each web app is served by its own API app, from the same origin, with security headers.
  - Staff use built-in auth with assignment required, 5 app roles and a session cookie.
  - Every call sends `X-Requested-With`.
  - `staff-api` returns 503 `DB_OFFLINE` when the database is down.
- **Retention (AD-15):** blob containers `images` and `corrections` delete after 30 days, with 7-day soft delete.
- **Email (AD-16):** an `EmailPort` over ACS Email with a verified custom domain. It throttles per environment with no shared state: Dev at most 5 a minute and 20 an hour, Prod at most 25 a minute and 80 an hour. Recipients come from `ALERT_RECIPIENTS_<ROLE>`. Emails go to staff alerts only.
- **Monitoring (AD-17):**
  - Log Analytics capped at 0.08 GB/day, with no separate log-cap alert (Dj's decision).
  - Alerts on the budgets and on the Application Insights custom metrics `poison_message{queue}`, `stuck_invoices` and `di_pages_used_pct` (80%), with alerting on custom metric dimensions turned on.
- **Supplier load script:** an operator-run script, run as Dj's user, that loads suppliers through the application code. It encrypts each bank field, stores `supplier_name` with each link for display, prints each new link once, and supports `--replace-link` and `--revoke`.

### UX Design Requirements

- **UX-DR1:**
  - Apply the shadcn/ui + Tailwind base to both SPAs.
  - Tokens are CSS variables: `success`, `warning`, `flag`, `flag-fill`, `flag-halo`, `confidence-low`, `destructive #B91C1C`, `tap-min 48px`, `supplier-gutter`.
  - Typography: `body-supplier` at 16px, and `numeric` with tabular figures.
  - Focus ring: 2px `ring` with a 2px offset, never removed.
  - A "Babaloo" text header.
- **UX-DR2:** One strings module per SPA, holding all copy per Voice and Tone, including the 12 reason labels and the status labels. Codes never appear as headlines.
- **UX-DR3:** One API client module per SPA. It sends `X-Requested-With`, maps 401 to the session-expired dialog and 503 `DB_OFFLINE` to the offline notice, and components never call `fetch` directly.
- **UX-DR4:** Supplier Upload home: "Uploading for {supplier}", the reminder banner, and **Take photo** / **Choose file**.
  - Camera-unavailable fallback copy.
  - The page sends the original file bytes.
  - Files are JPEG, PNG or PDF, 4 MB or less.
- **UX-DR5:** The on-device quality check (blur, darkness, edge cut off) takes about 2 s or less.
  - Each failure names its problem and is announced with `role=alert`.
  - **Send it anyway** appears after 2 failures. The server re-checks the upload, and it is processed normally if it passes.
  - PDFs are checked only for page count and size.
- **UX-DR6:** Check & send and Received:
  - a progress bar with `role=status`;
  - a retry with the same Idempotency-Key;
  - "Received. Reference R-XXXXXXXX", with focus moving to the reference;
  - a leave-page confirmation while uploading;
  - Upload another.
- **UX-DR7:** A Link not working page, identical for revoked and unknown links.
- **UX-DR8:** Staff shell:
  - Entra sign-in;
  - the sidebar shows only the surfaces of the user's roles (the combined set for a user with several roles);
  - each role lands on its own home page, and several roles resolve in the order admin → finance → procurement → management → goods_in;
  - a "no access" inline Alert;
  - a unique page title per route, with focus on the `h1` after navigation;
  - the sidebar becomes a Sheet below 1024px.
- **UX-DR9:** Admin queue table:
  - columns for received, supplier, amount, reason chips and age;
  - oldest first, with filters for reason and supplier;
  - the row is a real link;
  - pagination at 50;
  - an empty state;
  - the DI page-cap Alert at 80% of the environment's cap.
- **UX-DR10:** Admin item image viewer:
  - opens zoomed to the first flagged region, with Previous / Next and Show whole invoice;
  - zoom and pan buttons, with no drag needed;
  - flag boxes with a white halo and numbered tags linked to the field list, and a 4px stroke when selected;
  - a placeholder when the image has been deleted;
  - reduced-motion support.
- **UX-DR11:** Field list:
  - value, confidence badge below 98% ("Confidence 91%") and flag state;
  - Correct mode edits fields and marks them "Corrected";
  - bank fields are never editable.
- **UX-DR12:** Admin actions:
  - Correct → "Sent for re-check", and a flagged-again item returns marked "Returned after correction";
  - Approve needs a reason and a summary dialog;
  - Re-extract;
  - Reject needs a reason and a confirm;
  - the allowed-actions-by-reason table and the multi-reason rule apply;
  - the next item opens after an action;
  - "Already handled by another admin".
- **UX-DR13:** Bank-change panel:
  - the phone number on file and the old and new accounts, masked;
  - a two-item checklist gates Approve, with an explanation next to the button.
- **UX-DR14:** Masked value (admin only):
  - "account ending 4821";
  - Show until Hide, leaving the item, or 30 s, with a "Keep showing" warning at 20 s;
  - every reveal is audited and announced;
  - non-admins see only "Bank details on file".
- **UX-DR15:** Opt-in single-key shortcuts (j/k/Enter, c/a/r, n/p) with a `?` help dialog. They never fire in inputs or dialogs, and `Esc` behaviour is defined.
- **UX-DR16:** The Goods-in scan screen lists today's deliveries first and has a PO / supplier search. It uses the supplier-page layout, and shows its own state while the database is stopped.
- **UX-DR17:** Invoices surface (admin and finance): search by supplier, number, status or reference, with status labels.
- **UX-DR18:** Chart pattern: a one-sentence summary, a View as table toggle, and series told apart without colour.
- **UX-DR19:** Analytics surfaces:
  - Overdue POs, with the date the list was made;
  - Suppliers and Scorecard, plus a could-have Deliveries tab showing the three dates and the gaps between them;
  - Price comparison, with an on-time column;
  - Watchlist, with evidence and alternatives;
  - Finance month, per supplier, with the straight-through rate against the 90% target.
- **UX-DR20:** Shared states:
  - waking up: a skeleton, then a line after 3 s;
  - database stopped: the staff notice, while the supplier page stays unaffected;
  - session expired: unsaved corrections are restored after sign-in;
  - no data yet.
- **UX-DR21:** Accessibility floor:
  - WCAG 2.2 AA;
  - reflow at 320px;
  - text spacing;
  - `lang="en"`;
  - live regions for every status message;
  - scroll padding under sticky headers;
  - tap targets of 48px;
  - the image-free review path through the field list.
- **UX-DR22:** The supplier bundle stays at roughly 150 KB of JS or less (gzipped) and works in in-app browsers.
- **UX-DR23:** Staff alert emails (price rise, watchlist) with the defined subjects and deep links. They never include bank details or tokens.

### FR Coverage Map

- FR1: Epic 1 - Supplier upload by personal link
- FR2: Epic 4 - Goods-in capture against a delivery
- FR3: Epic 1 (device check, send anyway) and Epic 2 (server re-check)
- FR4: Epic 2 - Extraction with confidence
- FR5: Epic 2 - PO price × received quantity check
- FR6: Epic 2 - Duplicate detection
- FR7: Epic 2 - Photo date check
- FR8: Epic 2 - Bank details change hold (approval after call-back in Epic 3)
- FR9: Epic 2 - Admin queue
- FR10: Epic 2 - Corrections stored and ModelSelector seam
- FR11: Epic 3 - Auto-post to accounts XML API
- FR12: Epic 4 - Overdue PO list
- FR13: Epic 4 - Weekly supplier reminders on the upload page
- FR14: Epic 5 - Price comparison and price-rise alerts
- FR15: Epic 5 - Watchlist
- FR16: Epic 5 - Ranked alternatives
- FR17: Epic 5 - Supplier scorecard
- FR18: Epic 5 - Finance month view
- FR19: Epic 4 - Three-date check per delivery (could-have)
- FR20: Epic 2 - Simulated PO and goods-received data

## Epic List

### Epic 1: Suppliers can upload invoices by link
Suppliers get a personal link, photograph or pick an invoice on their phone, pass the on-device quality check (or send it anyway), and get a reference. Uploads work at any hour. This epic includes the platform setup stories, the supplier load script and the upload page and API.
**FRs covered:** FR1, FR3 (device)

### Epic 2: Invoices are read and checked automatically, and exceptions reach the admin queue
Uploads are quality-checked on the server, extracted and validated (confidence, PO match against simulated purchasing data, duplicates, photo date, bank details, printed supplier ID). Every exception lands in one admin queue, where admins signed in with Entra see the crop and flagged fields and can Correct, Re-extract or Reject. Corrections are stored for later learning.
**FRs covered:** FR3 (server), FR4, FR5, FR6, FR7, FR8, FR9, FR10, FR20

### Epic 3: Clean invoices post to the accounts system automatically
Passing invoices post to the simulated accounts XML API with retries. Failures go to the admin queue with the API error, and Approve (including after a bank call-back) sends the invoice to posting. Admin and finance can search every invoice and its status.
**FRs covered:** FR11

### Epic 4: Deliveries are tracked, and overdue suppliers are reminded
Goods-in staff photograph paper invoices against a delivery. An overdue list shows missing invoices by supplier, suppliers see weekly reminders on their upload page, and each delivery shows its three dates and the gaps between them (could-have).
**FRs covered:** FR2, FR12, FR13, FR19

### Epic 5: Finance and procurement see supplier price and speed insights
The analytics refresh builds the summary tables behind price comparison with price-rise alerts, the watchlist with evidence and ranked alternatives, supplier scorecards and the finance month view. Alerts reach staff by email.
**FRs covered:** FR14, FR15, FR16, FR17, FR18

## Epic 1: Suppliers can upload invoices by link

Suppliers get a personal link, photograph or pick an invoice on their phone, pass the on-device quality check (or send it anyway), and get a reference. Uploads work at any hour.

### Story 1.1: Repository and Terraform foundation

As Dj (the platform owner),
I want the repository, Terraform state and shared, Dev and Prod foundation stacks in place,
So that every later story deploys into named, tagged, budgeted Azure resources in `southeastasia`.

**Acceptance Criteria:**

**Given** an empty Azure Repos repository
**When** the layout is committed
**Then** it contains `backend/`, `web/supplier/`, `web/staff/`, `shared/` (with `quality-thresholds.json`) and `infra/` (with `bootstrap/`, `modules/`, `shared/`, `dev/` and `prod/`) per `terraform.md` and the spine's Structural Seed
**And** it contains `.gitignore`, `README.md` and committed lock files

**Given** the `infra/bootstrap/` scripts have been run once by an operator with Owner rights (AD-17 step 1)
**When** they finish
**Then** the Terraform state storage exists with Entra auth, shared-key access disabled and versioning on
**And** the three resource groups exist, named per P-16 (`babaloo-sea-lng-rg-<nn>`: Dev `0x`, Prod `1x`, shared `2x`), with the 5 P-17 tags, and the resource providers are registered
**And** the deploy identities for `dev`, `prod` and `shared` exist with their federated credentials, each holding only the rights in AD-17 "Deploy identity rights"
**And** each environment has two Entra app registrations: `staff-api` (app roles `admin`, `finance`, `procurement`, `management` and `goods_in`, "assignment required", ID-token issuance on) and `accounts-sim`
**And** the custom role `ACS Email Sender` (the email send action only) and the $8 subscription budget alert exist

**Given** the `shared/foundation` stack is applied
**When** it completes
**Then** PostgreSQL Flexible Server B1ms runs PostgreSQL 18 with 32 GB, a 7-day local backup, Entra-only auth, TLS required and `pgcrypto` allow-listed
**And** its firewall is open to all public IPv4 addresses, the accepted exception to `azure.md` rule 13 recorded in AD-17
**And** it holds the databases `invoicing_dev` and `invoicing_prod`, and its name follows `babaloo-sea-lng-<type>-2x` (AD-12, AD-17)
**And** one Document Intelligence F0 resource exists in `southeastasia` with a custom subdomain (AD-8)
**And** ACS Email exists with Dj's verified custom domain (the DNS records are added by hand), and the `shared` resource-group budget exists

**Given** the operator RBAC step in the bootstrap README (AD-17 step 3)
**When** it is done
**Then** each environment's deploy identity holds RBAC Administrator on the DI and ACS resources, conditioned to assigning only the runtime roles those resources need

**Given** each `<env>/foundation` stack is applied
**When** it completes
**Then** the environment has:
- the four user-assigned app identities (`supplier-api`, `staff-api`, `pipeline` and `accounts-sim`);
- a storage account (LRS, 7-day soft delete) with containers `images` and `corrections`, a 30-day lifecycle delete rule, the queues `q-quality`, `q-extract`, `q-validate` and `q-post`, and the tables `supplierlinks`, `uploadkeys` and `supplierreminders`;
- a Key Vault holding the HMAC key generated by Terraform, with the deploy identity as Key Vault Secrets Officer on this vault only;
- a Log Analytics workspace (0.08 GB/day cap, 30-day retention), Application Insights (sampling on) and an action group that emails Dj;
- the RG budget (alerts at 90%, 100% and 110%, plus the 110% forecast);
- all names following P-16 with Dev `0x` and Prod `1x`.

**And** the stack reads the `shared/foundation` outputs through `terraform_remote_state`, the departure recorded in AD-17
**And** a resource missing any of the 5 tags fails the plan

**Given** the operator PGP key step in the bootstrap README (AD-17 step 4b), run once per environment
**When** it is done
**Then** the environment vault holds `pgp-public-key`, and a separate bootstrap-only private-key vault in `babaloo-sea-lng-rg-22` (`kv-22` Dev, `kv-23` Prod) holds `pgp-private-key` (an RSA 3072, ASCII-armoured OpenPGP key pair with no passphrase, made offline with `gpg`); no local copy remains, and Terraform does not manage either secret
**And** only the environment's `staff-api` identity can read `pgp-private-key`: no deploy identity, pipeline identity or Dj's everyday user has a role on the private-key vault (Dj, 2026-09-29)

**Given** the operator database step in the bootstrap README (AD-17 step 5), run once per environment as the PostgreSQL Entra admin
**When** it finishes
**Then** that environment's AD-11 logins exist (the `pipeline`, `staff-api` and `accounts-sim` identities, Dj's loaders group and the deploy identity), created with `pgaadauth_create_principal`
**And** the environment's deploy identity owns its database, `CONNECT` is revoked from `PUBLIC`, and only that environment's logins are granted `CONNECT`
**And** a test shows that a Dev login can't connect to `invoicing_prod`
**And** Dj's loaders group, with Dj as a member, holds Key Vault Secrets User on only the `pgp-public-key` and `hmac-key` secrets, and Storage Table Data Contributor on that environment's storage account, for the load script (Dj, 2026-09-29: guest UPN over 63 characters)

### Story 1.2: CI/CD pipeline in Azure DevOps

As Dj,
I want every pull request checked and every merge deployed through a gated pipeline,
So that nothing reaches Prod without passing checks and my approval.

**Acceptance Criteria:**

**Given** a pull request to the integration branch
**When** the PR build runs
**Then** it runs lint and format checks, the backend and web tests with coverage (backend at least 80%, web at least 60%), `pip-audit`, `npm audit --omit=dev` and `gitleaks`
**And** a failing check blocks the merge through branch policy

**Given** a merge
**When** the deploy pipeline runs
**Then** it authenticates only through workload-identity-federation service connections, one deploy identity per stack owner (`shared`, `dev` and `prod`)
**And** it applies `dev` from a saved plan automatically on merge to `main`, the accepted departure from `terraform.md` rules 26 and 33 and `security.md` rule 34 recorded in AD-17
**And** it applies `shared` and `prod` from a saved plan only after manual approval
**And** the operator steps (AD-17 steps 1, 3, 4b, 5 and 8) stay outside the pipeline, in the bootstrap README

**Given** the weekly schedule
**When** the dependency scan runs
**Then** `pip-audit` and `npm audit` run against the main branch and report any findings

**Given** a migration exists
**When** the deploy runs
**Then** Alembic `upgrade head` runs as a pipeline step, as the environment's deploy identity, connecting directly while the PostgreSQL firewall is open (no temporary firewall rule, AD-17), after `<env>/foundation` and before `<env>/app` and the code deploy (AD-17 steps 6, 7 and 9), never at app start
**And** every schema grant is part of a migration (AD-11)

**Tasks:**
- Client side: create the Azure DevOps project in the `example-org` organisation; its name is an input to `state-backend.sh` and `ado-setup.sh` (started 2026-09-29 07:00).

### Story 1.3: Python Functions API skeleton

As a developer,
I want the shared `invoicing` package and four Flex Consumption apps deployed,
So that every later story adds code to a working, observable back end.

**Acceptance Criteria:**

**Given** the backend project
**When** it is built
**Then** it has the package `backend/src/invoicing/` with `domain/`, `ports/`, `adapters/` and `apps/{supplier_api,staff_api,pipeline,accounts_sim}`, on Python 3.13 with the Functions v2 model and pinned dependencies
**And** an import-lint test fails if `domain/` imports any framework, ORM or HTTP library

**Given** the `<env>/app` stack is applied
**When** it completes
**Then** four Flex apps exist (one plan each, on-demand only, 2,048 MB instance memory), each using its user-assigned identity from `<env>/foundation`
**And** the maximum instance count is 1 for `pipeline` and 10 for each other app (AD-17 compute ceilings)
**And** each identity gets exactly the runtime roles in the AD-17 table, at the narrowest scope, with none subscription-scoped

**Given** any app
**When** it serves a request
**Then** it reads configuration only from one `pydantic-settings` object
**And** it returns errors as `{code, message, correlation_id}`
**And** its logs carry ids and codes only, never values, tokens or headers

**Given** the `pipeline` app
**When** it is deployed
**Then** `host.json` has `batchSize` 1, `newBatchThreshold` 0 and `extensions.queues.messageEncoding` set to `none`
**And** every producer sends `QueueMessage` as plain JSON text through the `azure-storage-queue` SDK (AD-2); the queues themselves come from `<env>/foundation` (Story 1.1)

**Given** a `GET /api/health` call to `supplier-api` or `staff-api`
**When** it runs
**Then** it returns 200 with the app version

### Story 1.4: React web app skeletons

As a developer,
I want both single-page apps scaffolded with the design tokens, strings module and API client,
So that every screen story starts from the agreed visual and behavioral base.

**Acceptance Criteria:**

**Given** `web/supplier` and `web/staff`
**When** they are built with Vite
**Then** each uses React, TypeScript, shadcn/ui and Tailwind, with pinned versions and a committed `package-lock.json`
**And** each has `lang="en"` and the "Babaloo" text header

**Given** the design tokens in `DESIGN.md`
**When** the apps load
**Then** these are defined as CSS variables (UX-DR1):
- `success`, `warning`, `flag`, `flag-fill`, `flag-halo`, `confidence-low`, `destructive #B91C1C`;
- `tap-min`, `supplier-gutter`;
- the `body-supplier` and `numeric` typography;
- the 2px focus ring.

**And** a lint rule blocks hard-coded colors

**Given** any component
**When** it needs copy
**Then** it takes the copy from the one strings module per app, which holds the 12 reason labels and the status labels (UX-DR2)

**Given** any API call
**When** it is made
**Then** it goes through `src/api/`, which sends `X-Requested-With: XMLHttpRequest`, maps 401 to a session-expired event and 503 `DB_OFFLINE` to an offline event (UX-DR3)
**And** a lint rule blocks direct `fetch` in components

**Given** a build
**When** it deploys
**Then** `web/supplier` is packaged into `supplier-api` and `web/staff` into `staff-api`, served from the same origin
**And** every response carries the security headers (HSTS, CSP self with no inline scripts, nosniff, Referrer-Policy)

**Given** the supplier build
**When** it is measured
**Then** its JavaScript is at most about 150 KB gzipped (UX-DR22)

**Given** both apps
**When** CI runs
**Then** an automated axe check runs on every screen, and WCAG 2.2 AA violations fail the build (UX-DR21)
**And** the layouts reflow at 320px with no horizontal page scroll, tolerate text-spacing overrides, use 48px tap targets, and set scroll padding equal to the sticky header height

### Story 1.5: Monitoring and alerts

As Dj,
I want the core alerts wired from day one,
So that I learn about cost, failures and quota before users do.

**Acceptance Criteria:**

**Given** each environment
**When** monitoring is applied
**Then** every app sends traces to that environment's Application Insights, with sampling on and one trace per `correlation_id`
**And** a metrics helper in the `invoicing` package emits Application Insights custom metrics with dimensions, and alerting on custom metric dimensions is turned on (AD-17)
**And** alerts to Dj fire through the action group when a resource-group budget threshold or the $8 subscription budget is crossed

**Note:** the pipeline alerts use custom metrics emitted by later stories: `poison_message{queue}` and `stuck_invoices` (Story 2.2) and `di_pages_used_pct` (Story 2.3). Each of those stories adds its own alert rule. There is no separate log-cap alert (Dj's decision, AD-17).

**Given** an alert rule
**When** it fires in a test
**Then** Dj receives the email

### Story 1.6: Load suppliers and issue upload links

As Dj,
I want to load suppliers with a script that issues each one a personal upload link,
So that suppliers can start uploading without anyone typing bank details into a database.

**Acceptance Criteria:**

**Given** a CSV of synthetic suppliers (`supplier_id`, name, phone, `tax_id`, and one column per AD-18 bank field id: `bank_account_number`, `iban` and `swift`), where `supplier_id` is a required UUID matching the purchasing seed's supplier ids and rows match on it (Dj, 2026-09-29)
**When** the operator runs the supplier load script against Dev as Dj's loaders group, with Dj as a member (Dj, 2026-09-29: guest UPN over 63 characters)
**Then** the suppliers are created or updated in `master.supplier{id, name, tax_id, phone}` through the application code (the first `master` migration)
**And** each non-empty bank value is stored as one `master.supplier_bank{supplier_id, field_id, ciphertext, fingerprint}` row, with `pgp_pub_encrypt` ciphertext plus an HMAC-SHA256 fingerprint, normalised first (spaces and hyphens stripped, uppercase), using the public key and the HMAC key from Key Vault (AD-11)
**And** a bank field, `phone` or `tax_id` left blank in the CSV leaves any stored value for that field unchanged (Dj, 2026-09-29)
**And** the migration grants `master` per AD-11: read/write for Dj's loaders group, read including ciphertext for `staff-api`, and read without the ciphertext column for `pipeline`
**And** it creates `audit.event(id, at, actor, action, entity, entity_id, detail)`, with `INSERT` only for every login that writes it and `SELECT` for `staff-api`
**And** the script writes an `audit.event` entry when a supplier is created or updated and when a bank field is added or changed, naming field ids only, never values (Dj, 2026-09-29)

**Given** a supplier with no active link (new, or revoked earlier and still in the CSV; Dj, 2026-09-29)
**When** the script runs
**Then** it creates a 256-bit random token (base64url) and stores only its SHA-256 hash in `supplierlinks` with `supplier_id`, `supplier_name` (for display on the upload page) and `issued_at`
**And** it prints the full link `https://<supplier-api host>/u#<token>` once, and never again (AD-6)
**And** it writes an `audit.event` entry for the issue, naming the supplier only, never the token (Dj, 2026-09-29)

**Given** an existing supplier with `--replace-link`
**When** the script runs
**Then** it sets `revoked_at` on the old link, issues and prints a new link, and writes an audit entry

**Given** an existing supplier with `--revoke`
**When** the script runs
**Then** it sets `revoked_at` on the supplier's link without issuing a new one, and writes an audit entry
**And** that link then accepts no uploads and shows Link not working (Story 1.7)

**Given** the script's logs
**When** they are inspected
**Then** they contain no token, bank value or phone number

**Tasks:**
- Prerequisites (Story 1.1): `pgp-public-key` and `hmac-key` in the environment vault (the private key is in the separate private-key vault, readable only by staff-api); Dj's loaders group login (Dj a member), Key Vault Secrets User on those two secrets and Storage Table Data Contributor from the operator database step (AD-17 step 5). This story has no Terraform.
- Python: `master` migration with its grants; `SupplierLinkRegistry` port and table adapter; the load script (`--replace-link`, `--revoke`); `audit` append-only table and grants.
- Tests: `test_story_1_6_*` for encryption, one row per bank field id, fingerprint normalisation, link issue, replace and revoke, `pipeline` refused on the ciphertext column, and log redaction.

### Story 1.7: Supplier opens their link

As a supplier (Mr Lim),
I want my link to open a page that shows it is uploading for my company,
So that I know I'm sending to the right place.

**Acceptance Criteria:**

**Given** a valid, unrevoked link
**When** the supplier opens `…/u#<token>`
**Then** the page reads the token from the URL fragment, which the browser never sends to the server, and sends it in the `X-Upload-Token` header on every call (AD-6)
**And** Upload home shows "Uploading for **{supplier name}**" with **Take photo** and **Choose file** (UX-DR4)
**And** `supplier-api` resolves `supplier_id` and `supplier_name` from `supplierlinks` by the token hash, without touching PostgreSQL

**Given** a revoked or unknown token
**When** the page opens
**Then** it shows "This link isn't working. Please contact your buyer at Babaloo.", identical for both cases (UX-DR7)

**Given** the PostgreSQL server is stopped
**When** a valid link opens
**Then** Upload home still works

**Given** the app has scaled to zero
**When** the page loads
**Then** a skeleton shows, and after 3 s "Waking up, one moment…" (UX-DR20)

**Given** any request
**When** it is logged
**Then** the token never appears, because no URL sent to the server carries it and the `X-Upload-Token` header is never logged (AD-14)

**Tasks:**
- Python: `GET /api/link`, reading the token from `X-Upload-Token` and returning `supplier_name` only; the link lookup through the registry port.
- React: Upload home and Link not working; waking-up state.
- Tests: `test_story_1_7_*` for valid, revoked and unknown links, and the DB-stopped case; a Vitest for each screen.

### Story 1.8: Supplier sends a photo or PDF and gets a reference

As a supplier (Mr Lim),
I want to send my invoice photo and get a reference,
So that I know it arrived without typing anything.

**Acceptance Criteria:**

**Given** a chosen JPEG, PNG or PDF of 4 MB or less
**When** the supplier taps **Send**
**Then** the page uploads the original file bytes, never re-encoded, with an `Idempotency-Key` created once for that file
**And** a progress bar with `role="status"` shows, and leaving mid-upload asks for confirmation (UX-DR6)

**Given** a valid upload
**When** `supplier-api` receives it
**Then** it checks the `X-Upload-Token`, creates a UUIDv7 `invoice_id`, and inserts `Idempotency-Key → invoice_id` into `uploadkeys` if absent; if the key already exists, the stored `invoice_id` is used
**And** it then writes the original bytes to `images/<invoice_id>` with `IntakeBlobMetadata` (`source=link`, `supplier_id`, `content_type`, `uploaded_at`, `device_check`), unless the blob already exists
**And** it then enqueues `QueueMessage` on `q-quality` and returns the `invoice_id` and reference, in that order and all without PostgreSQL (AD-6)

**Given** a retry with the same `Idempotency-Key` within 24 hours
**When** it arrives
**Then** the same `invoice_id` and reference are returned, the blob write (if missing) and the enqueue are replayed, and no second invoice is created
**And** a first attempt that died after writing the key is completed by the retry

**Given** a file over 4 MB or of another type
**When** it is sent
**Then** the server rejects it with a plain message, whatever the client did

**Given** a successful upload
**When** the Received screen shows
**Then** it reads "Received. Reference R-XXXXXXXX", using 8 base32 characters from the random part of `invoice_id`
**And** "Received" is announced and focus moves to the reference
**And** **Upload another** returns to Upload home

**Given** a network failure
**When** the upload fails
**Then** "Couldn't send. Check your connection and tap Send again." shows with `role="alert"`, and the photo is kept

**Given** the camera is blocked or in-app browsers deny it
**When** **Take photo** is tapped
**Then** the camera-unavailable message offers **Choose file**

**Tasks:**
- Python: `POST /api/upload`; the blob, table and queue adapters; `IntakeBlobMetadata` and `QueueMessage` models; reference derivation.
- React: Check & send and Received screens; the API client call with the idempotency key.
- Tests: `test_story_1_8_*` for the happy path, retry idempotency, a crash after each of the three steps, size and type rejection, and the DB-stopped case; Vitest for the screens.

### Story 1.9: On-device photo quality check with send anyway

As a supplier (Mr Lim),
I want to be told straight away when a photo is too blurry, dark or cut off,
So that I can retake it instead of having it rejected later.

**Acceptance Criteria:**

**Given** a photo
**When** it is chosen
**Then** blur, darkness and edge-cut-off checks run on the device in about 2 s or less (UX-DR5), using the thresholds in `shared/quality-thresholds.json`, which the server `quality` stage also reads (AD-6)

**Given** a failing photo
**When** the check completes
**Then** the exact problem is named (for example "The bottom edge is cut off") with **Take again**, announced with `role="alert"`

**Given** 2 failed checks on the same upload
**When** the second failure shows
**Then** **Send it anyway** appears as a secondary action
**And** sending uploads with `device_check=overridden` and shows the normal Received screen; the server re-check then processes it normally if it passes, or routes it `UNREADABLE` if it fails (FR3, AD-6)

**Given** a PDF
**When** it is chosen
**Then** the photo checks are skipped, and a PDF with more than 2 pages is refused on the device

**Given** a passing photo
**When** it is sent
**Then** it uploads with `device_check=passed`

**Given** a photo the phone can't check (no image decoder, the decode fails, or the check runs past its time limit), or a PDF whose page count can't be read
**When** it is sent
**Then** it uploads with `device_check=skipped`, and the server processes it like `passed` (Dj, 2026-09-29)

**Tasks:**
- React: quality-check module (variance of the Laplacian for blur, mean luminance for darkness, edge detection) in `shared/quality/`, beside `shared/quality-thresholds.json`, so `web/staff` can import it for Story 4.1; Check & send states; the send-anyway flow.
- Python: accept and store `device_check` (`passed`, `overridden` or `skipped`) in the metadata.
- Tests: `test_story_1_9_*` for metadata; Vitest with fixture images for blur, dark, cut-off and pass.

## Epic 2: Invoices are read and checked automatically, and exceptions reach the admin queue

Uploads are quality-checked on the server, extracted, and validated. Every exception lands in one admin queue, where admins see the crop and flagged fields and can Correct, Re-extract or Reject.

### Story 2.1: Server quality check creates the invoice record

As an admin (Priya),
I want every upload recorded and checked for readability on the server,
So that unreadable or oversized documents reach me instead of disappearing.

**Acceptance Criteria:**

**Given** a message on `q-quality`
**When** the `quality` stage runs
**Then** it inserts `intake.invoice` from `IntakeBlobMetadata` with `INSERT … ON CONFLICT (id) DO NOTHING`, with status `received` and the AD-3 columns (the first `intake` migration, which also creates `status_history` and grants `intake` per AD-11; AD-3, AD-5)
**And** every transition writes an `intake.status_history` row `{invoice_id, from_status, to_status, actor, at}` in the same transaction
**And** the supplier is taken only from the metadata, and nothing changes it afterwards (P-5)

**Given** an image
**When** it is checked
**Then** the stage applies the EXIF orientation and re-checks readability with the page's measures (variance of the Laplacian and mean luminance, computed with Pillow) and the thresholds in `shared/quality-thresholds.json`
**And** it saves `photo_taken_at` from EXIF `DateTimeOriginal`, read as Singapore time unless `OffsetTimeOriginal` gives an offset (or null), and stores a 64-bit phash in `intake.image_hash` (AD-6, AD-9, AD-19)

**Given** a readable image or a PDF of 2 pages or fewer
**When** the check passes
**Then** the invoice moves `received → awaiting_extraction` by conditional UPDATE, and the stage enqueues `q-extract`

**Given** an unreadable image, including a `device_check=overridden` upload that fails
**When** the check fails
**Then** `domain.route_to_admin(invoice_id, [UNREADABLE], from_status)` moves it to `in_admin_queue` by conditional transition and, in the same transaction, writes one `intake.admin_item` row `{id, invoice_id, routing_id, run_id?, reason, field_ids[], detail, created_at}`, with one UUIDv7 `routing_id` per call (AD-4)
**And** a `device_check=overridden` upload that passes the re-check is processed like any other (AD-6)

**Given** a PDF of more than 2 pages
**When** it is checked
**Then** it is routed with `UNSUPPORTED_DOCUMENT`

**Given** a redelivered message whose transition changes zero rows
**When** it is processed
**Then** the stage reads the status: if it is the stage's final target (`awaiting_extraction` for quality), the next stage is re-enqueued; otherwise the message is only acknowledged. Either way, no duplicate row is created (AD-2)
**And** extract, validate and post use the same per-stage rule, with final targets `awaiting_validation`, `ready_to_post` or `in_admin_queue`, and `posted`

**Tasks:**
- Python: `intake` migration (`invoice` with every AD-3 column, `status_history`, `admin_item` with `routing_id`, `image_hash`) and its AD-11 grants; domain state machine with lease reclaim, and `route_to_admin(invoice_id, reasons, from_status, metadata?)`; reasons catalogue; the `quality` function reading `shared/quality-thresholds.json`.
- Tests: `test_story_2_1_*` for each path, redelivery, EXIF orientation, and a PDF page count.

### Story 2.2: The pipeline never loses an invoice

As Dj,
I want invoices to wait out a stopped database, and failures to reach the admin queue,
So that nothing uploaded overnight or at weekends is lost.

**Acceptance Criteria:**

**Given** PostgreSQL is stopped
**When** any queue consumer runs
**Then** it re-enqueues the same message with a 15-minute visibility delay, keeping `first_enqueued_at` and `attempt`, and completes the original, so the dequeue count isn't used up (AD-7)

**Given** a message that fails 5 times for another reason
**When** it lands in a `*-poison` queue
**Then** the poison trigger calls `route_to_admin(PROCESSING_FAILED)` only when the invoice is still in that queue's input state, or in its claim state with an expired lease; otherwise it acknowledges the poison message (AD-2, AD-4)
**And** when the invoice row is missing, it passes the blob's `IntakeBlobMetadata`, so `route_to_admin` creates the row
**And** it emits the custom metric `poison_message{queue}`, and an alert to Dj fires when that is more than 0 in an hour (AD-17)
**And** the trigger follows the same database-wait rule

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

**Tasks:**
- Python: DB-wait decorator for consumers; poison triggers with the state guard; sweeper timer (status map, `uploadkeys` cleanup); lease reclaim; the `poison_message` and `stuck_invoices` metrics.
- Terraform: the `poison_message` and `stuck_invoices` alert rules in `<env>/app`.
- Tests: `test_story_2_2_*` with the database unreachable, poison routing and its guard, each status-map row, `in_admin_queue` left alone, no stuck count right after a database start, lease reclaim, and `uploadkeys` cleanup.

### Story 2.3: Invoice fields are extracted by Document Intelligence

As an admin (Priya),
I want invoice fields read automatically, each with a confidence score,
So that I only look at invoices the system isn't sure about.

**Acceptance Criteria:**

**Given** the shared DI F0 resource (Story 1.1) and the conditioned RBAC Administrator from the operator step (AD-17 step 3)
**When** `<env>/app` is applied
**Then** that environment's `pipeline` identity has Cognitive Services User on the DI resource

**Given** a message on `q-extract`
**When** the `extract` stage runs
**Then** it claims `awaiting_extraction → extracting` with a 10-minute lease
**And** `adapters/document_intelligence.py` calls `prebuilt-invoice` on API `2024-11-30` through the `ModelSelector` port (default `prebuilt-invoice`), saving the `Operation-Location` against `invoice_id` before polling
**And** it maps the result into one `intake.extraction_run` row, one `intake.invoice_field` row per header field and one `intake.invoice_line` row per line, with the AD-18 field ids, `confidence`, `page`, `polygon` and `currency` from `INVOICE_CURRENCY` (SGD), and it drops the raw DI result (AD-8, AD-18)
**And** every bank field (`payment[<n>].bank_account_number`, `.iban` and `.swift`) is stored from its first write as `pgp_pub_encrypt` ciphertext plus an HMAC fingerprint, normalised first, and never as plaintext (AD-11)
**And** it then moves the invoice to `awaiting_validation` and enqueues `q-validate`

**Given** a retry after an extraction run was saved since the invoice last entered `awaiting_extraction` (from `status_history`)
**When** it runs
**Then** the saved run is reused, DI is not called again, and no pages are counted twice
**And** a retry that finds a saved `Operation-Location` resumes polling instead of analysing again

**Given** an admin Re-extract
**When** extraction runs
**Then** DI is called again and a new run is saved, because earlier runs are older than the latest entry into `awaiting_extraction` (AD-3)

**Given** the adapter
**When** it sends requests, polling included
**Then** it sends at most 1 request every 2 s in each environment, keeping the last call time in `intake.di_usage` under `pg_advisory_xact_lock`, so the limit holds across restarts and redeploys (AD-8)

**Given** a 429 response
**When** it arrives
**Then** the message is re-enqueued after `Retry-After`, without using up a dequeue

**Given** the monthly page count in `intake.di_usage` has reached the environment cap (Dev 100, Prod 400), or DI returns a quota error
**When** extraction is attempted
**Then** the invoice is routed with `EXTRACTION_QUOTA`
**And** pages are reserved in `intake.di_usage` under the same lock before each analyze call, so two instances can't both pass the cap
**And** the stage emits `di_pages_used_pct`, and at 80% of the cap Dj gets an alert (AD-17)

**Tasks:**
- Terraform: the `pipeline` Cognitive Services User assignment and the `di_pages_used_pct` alert in `<env>/app` (the DI resource is in Story 1.1).
- Python: DI adapter with the PostgreSQL-backed rate limiter and page reservation; `ModelSelector` port; `extract` function; bank-field encryption and fingerprinting; migrations for `extraction_run`, `invoice_field`, `invoice_line` and `di_usage`.
- Tests: `test_story_2_3_*` with a faked DI for the happy path, AD-18 field ids, no plaintext bank value in any row, reuse on retry, Re-extract calling DI again, resumed polling after a 429, the quota cap and throttling.

### Story 2.4: Simulated PO and goods-received data

As Dj,
I want a simulated purchasing system behind its own adapter,
So that PO checks work now, and the real database can replace it later without code changes elsewhere.

**Acceptance Criteria:**

**Given** the `sim_purchasing` schema migration and seed script
**When** they run on Dev
**Then** synthetic materials, POs (lines with `po_line_id`, `material_id`, `supplier_product_code`, unit price, quantity and expected date), deliveries and goods receipts exist for the loaded suppliers
**And** the seed includes the same material bought from several suppliers, and a PO delivered in parts, so CAP-5, CAP-14 to CAP-17 and partial deliveries can be tested
**And** materials live only in `sim_purchasing`: purchasing owns them, and nothing loads them into `master` (AD-10)

**Given** `PurchasingPort`
**When** it is implemented by the purchasing simulation adapter
**Then** it offers `get_po`, `get_receipts`, `get_delivery`, `list_overdue_pos` and `get_delivery_dates` (AD-10)
**And** `get_po(po_number)` returns the supplier and the lines, each with `po_line_id`, `material_id`, `material_name`, `supplier_product_code`, `unit_price`, `quantity` and `expected_date`
**And** `get_receipts(po_number)` returns each receipt's `received_date` and the received quantity per `po_line_id`
**And** only `adapters/purchasing_sim/` reads `sim_purchasing`, enforced by an import-linter rule, with no per-adapter database role
**And** the adapter is selected by `PURCHASING_ADAPTER`, and no other module imports it

**Given** a contract test suite for `PurchasingPort`
**When** it runs against the simulation adapter
**Then** it passes, ready to run against the real adapter later (FR20)

**Tasks:**
- Python: `sim_purchasing` migration (with `SELECT` for the `pipeline` and `staff-api` logins, AD-11) and seed; the port and simulation adapter; the import-linter contract.
- Tests: `test_story_2_4_*` port contract tests.

### Story 2.5: Validation checks confidence, PO match and printed supplier

As an admin (Priya),
I want each invoice checked against its PO and its supplier,
So that wrong amounts and impersonated suppliers never auto-post.

**Acceptance Criteria:**

**Given** a message on `q-validate`
**When** the `validate` stage runs
**Then** it claims `awaiting_validation → validating` and runs all checks, collecting every failing reason before routing (AD-4)

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

**Given** no reasons
**When** validation completes
**Then** the invoice moves to `ready_to_post`

**Tasks:**
- Python: `validate` function framework; the current-value domain function; the three checks; money helpers.
- Tests: `test_story_2_5_*` for each check alone and combined, the checked-field list, a missing checked field, the tolerance edges, a second invoice against a PO delivered in parts, tax-id vs fuzzy name match, `Decimal` rounding, and all passing.

### Story 2.6: Validation catches duplicates, date mismatches and bank changes

As an admin (Priya),
I want duplicates, date mismatches and changed bank details caught,
So that fraud and double payments are stopped before posting.

**Acceptance Criteria:**

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

**Given** no `photo_taken_at`, as for a PDF or scan
**When** it is checked
**Then** `NO_PHOTO_DATE` is recorded, and the supplier is never notified (FR7)

**Given** extracted bank fields, already encrypted and fingerprinted by the `extract` stage (Story 2.3)
**When** they are checked
**Then** each is compared by fingerprint with the supplier's `master.supplier_bank` value for the same field id, and nothing is decrypted
**And** a field whose fingerprint differs, or for which the supplier has no value on file, records `BANK_CHANGED`, and the invoice never auto-posts (FR8, P-7, AD-19)

**Given** an invoice matched to a PO
**When** validation completes
**Then** the `supplierreminders` row with `PartitionKey=supplier_id` and `RowKey=po_number` is deleted (AD-6)

**Tasks:**
- Python: fingerprint and phash checks; date check; bank fingerprint check per field id; reminder-row cleanup.
- Tests: `test_story_2_6_*` including the concurrent-duplicate race, self-match and rejected-invoice exclusion, the 0-day and 30-day date edges, EXIF offsets, missing photo date, a SWIFT code never compared with an account number, a bank field missing from the master, and bank normalisation (spaces, hyphens, case).

### Story 2.7: Staff sign in and see only their surfaces

As a staff member,
I want to sign in with my Babaloo Entra account and land on my own home page,
So that I only see what my role allows.

**Acceptance Criteria:**

**Given** the `staff-api` app registration (single tenant, assignment required, app roles `admin`, `finance`, `procurement`, `management`, `goods_in`)
**When** an unassigned tenant user signs in
**Then** access is denied

**Given** an assigned user
**When** they open the staff app
**Then** built-in auth redirects them to Entra login (ID tokens only, no client secret) and sets a `SameSite=Lax` session cookie (AD-14)
**And** the sidebar shows only the surfaces of their roles, the combined set for a user with several roles
**And** they land on their first role's home page in the order admin, finance, procurement, management, goods_in (UX-DR8)

**Given** a route outside the user's roles
**When** it is opened
**Then** they are redirected home with the inline Alert "You don't have access to that page."
**And** the API also enforces the role in the domain layer

**Given** an API call returning 401
**When** it arrives
**Then** the "Your session ended. Sign in again to continue." dialog shows

**Given** an API call returning 503 `DB_OFFLINE`
**When** it arrives
**Then** the full-page offline notice with working hours shows (UX-DR20)

**Given** `staff-api` has scaled to zero
**When** the staff app loads
**Then** skeleton rows show, and after 3 s "Waking up, one moment…" (UX-DR20)

**Given** any route change
**When** it completes
**Then** the page title is unique ("Admin queue – Babaloo") and focus moves to the `h1`
**And** below 1024px the sidebar becomes a Sheet

**Tasks:**
- Terraform: built-in auth on `staff-api` in `<env>/app`, pointing at the `staff-api` app registration created by the bootstrap (Story 1.1), with ID-token login and no client secret.
- Operator: register the redirect URI `https://<staff-api host>/.auth/login/aad/callback` on the app registration once the app exists (AD-17 step 8, bootstrap README).
- Python: role guard, the `DB_OFFLINE` error mapping, and `GET /api/me`.
- React: shell, sidebar by role, landing redirect, session-expired dialog, offline notice.
- Tests: `test_story_2_7_*` for role enforcement, 401 and 503; Vitest for the shell states.

### Story 2.8: Admin queue list

As an admin (Priya),
I want one list of every invoice that needs me, oldest first,
So that I can work through exceptions in order.

**Acceptance Criteria:**

**Given** invoices in `in_admin_queue`
**When** an admin opens the Admin queue
**Then** a table shows received, supplier, amount, reason chips (with labels, not codes) and age, sorted oldest first and paginated at 50 (UX-DR9)
**And** the reason chips are the invoice's open reasons: the `admin_item` rows of its latest `routing_id` only (AD-4)
**And** it can be filtered by reason and by supplier

**Given** the table
**When** it is used by keyboard or screen reader
**Then** the supplier name is a real link to the item, and clicking elsewhere on the row also opens it

**Given** the queue is empty
**When** it opens
**Then** it shows "Nothing waiting. New exceptions appear here automatically."

**Given** DI pages at 80% of this environment's cap
**When** the queue opens
**Then** an Alert shows, for example "322 of 400 pages used this month."

**Given** a non-admin
**When** they call the queue API
**Then** they get 403, and 404 for individual items

**Tasks:**
- Python: `GET /api/admin/queue` with filters and paging.
- React: queue table, filters, empty state, page-cap alert.
- Tests: `test_story_2_8_*`; Vitest for sort, filter and empty states.

### Story 2.9: Admin item shows the crop, fields and bank-change details

As an admin (Priya),
I want to see exactly which part of the invoice is in doubt,
So that I can decide quickly without hunting through the photo.

**Acceptance Criteria:**

**Given** an admin opens an item
**When** the image viewer loads
**Then** it opens zoomed to the first flagged region (UX-DR10)
**And** **Previous**, **Next**, **Show whole invoice** and the zoom and pan buttons work without dragging
**And** the flag boxes have a white halo and numbered tags matching the field list, and a selected box is drawn with a 4px stroke
**And** zoom isn't animated under reduced motion

**Given** the field list
**When** it shows
**Then** each field shows its current value (the AD-18 current-value rule), a confidence badge below 98% (announced as "Confidence 91%") and its flag state; the flagged fields are the `field_ids` of the open reasons
**And** flag boxes and crops are drawn from each row's `page` and `polygon`
**And** selecting a field highlights its box, and the reverse (UX-DR11)

**Given** the image has been deleted by the 30-day rule
**When** the item opens
**Then** the placeholder reads "Image deleted after 30 days", and the fields still show

**Given** the reason `BANK_CHANGED`
**When** the item opens
**Then** the bank-change panel shows the supplier's phone number on file and, for each changed bank field, the value on file (or that none is on file) and the new value, masked ("account ending 4821") (UX-DR13, AD-19)

**Given** an admin taps **Show** on a masked value
**When** it reveals
**Then** the value shows until **Hide**, until the admin leaves the item, or for at most 30 s
**And** at 20 s an announced warning offers **Keep showing**
**And** every reveal writes an audit entry, and the hide is announced (UX-DR14)

**Given** a non-admin
**When** they request an image, crop or bank value
**Then** they are refused, and they only ever see "Bank details on file"

**Tasks:**
- Python: item API (fields, reasons, SAS-free image stream for admins only); reveal endpoint with audit.
- React: image viewer, field list, bank-change panel, masked value.
- Tests: `test_story_2_9_*` for access control and audit; Vitest and axe checks for the viewer and panel.

### Story 2.10: Admin corrects, re-extracts or rejects

As an admin (Priya),
I want to fix a misread field, re-run extraction, or reject an invoice,
So that each exception is resolved from one screen.

**Acceptance Criteria:**

**Given** an item
**When** the actions render
**Then** only the actions allowed by the reasons table and the multi-reason rule for the invoice's open reasons (latest `routing_id`) show, and the server applies the same guard (UX-DR12, AD-4):
- Correct if any reason allows it;
- Re-extract only if every reason allows it;
- Retry intake only for `PROCESSING_FAILED` when the quality stage never completed;
- Reject always, unless the invoice has an `accounts_ref`.

**Given** **Correct**
**When** the admin edits fields and taps **Save and re-check**
**Then** the corrected values are saved as new `source=admin` rows with confidence 1.0, carrying the latest `run_id` and never updating a DI row; a corrected line is written as a complete line row, copying every uncorrected column (AD-18)
**And** those rows and the move to `awaiting_validation` are one transaction
**And** after the commit, `q-validate` is enqueued, the raw correction is written as JSON to the `corrections` container with no bank plaintext (FR10, AD-15), and the Toast "Sent for re-check" shows
**And** bank fields are never editable

**Given** unsaved Correct edits when an API call returns 401
**When** the admin signs in again from the session-expired dialog
**Then** the unsaved edits are restored (UX-DR20)

**Given** a corrected invoice that is flagged again
**When** it returns to the queue
**Then** it is marked "Returned after correction", showing only the reasons of its latest routing (AD-4)

**Given** **Re-extract**, allowed only for `EXTRACTION_QUOTA` and `PROCESSING_FAILED`
**When** the admin uses it
**Then** the invoice moves to `awaiting_extraction` and `q-extract` is enqueued

**Given** `PROCESSING_FAILED` on an invoice whose quality stage never completed (no `image_hash` row and no `photo_taken_at` decision)
**When** the admin uses **Retry intake**
**Then** the invoice moves to `received` and `q-quality` is enqueued, so it goes through the full quality stage (AD-3)

**Given** **Reject**
**When** the admin enters a reason and confirms
**Then** the invoice moves to `rejected` and the reason is audited
**And** Reject is refused, and not offered, once the invoice has an `accounts_ref`; such an invoice can only be Approved, which re-posts it idempotently (AD-3)
**And** for `UNREADABLE` and `UNSUPPORTED_DOCUMENT`, the panel shows the supplier's phone number with "Ask the supplier to send it again."

**Given** another admin acted first
**When** an action is submitted
**Then** "Already handled by another admin." shows with `role="alert"`, and the admin returns to the queue

**Given** any action completes
**When** the next item opens
**Then** focus moves to its heading

**Tasks:**
- Python: action endpoints with conditional transitions, corrections blob writer, audit.
- React: action bar, Correct mode, dialogs, Toasts.
- Tests: `test_story_2_10_*` for each action including Retry intake, the multi-reason matrix on open reasons only, Reject refused once `accounts_ref` exists, a complete corrected line row, the concurrent-admin race, edits restored after a 401, and that corrections hold no bank plaintext.

### Story 2.11: Opt-in keyboard shortcuts for the admin queue

As an admin who works the queue all day,
I want optional single-key shortcuts,
So that I can clear items faster without breaking screen-reader use for others.

**Acceptance Criteria:**

**Given** a new user
**When** they use the staff app
**Then** single-key shortcuts are off by default (UX-DR15)

**Given** the setting is on in this browser
**When** the admin presses keys
**Then** `j`/`k` move between rows and `Enter` opens an item in the queue
**And** in an item, `c` and `r` open the same dialogs as the buttons, and `n`/`p` step through flagged regions (`a` for Approve is added by Story 3.3)
**And** `?` opens the help dialog

**Given** focus is in an input, or a dialog is open
**When** a shortcut key is pressed
**Then** nothing fires, and `Esc` closes the topmost dialog, or returns to the queue if none is open

**Tasks:**
- React: the setting is stored in the browser's `localStorage` and falls back to off when storage is unavailable; the server keeps no user profile (AD-14).
- React: shortcut handler, settings toggle, help dialog.
- Tests: `test_story_2_11_*`; Vitest for the input and dialog guards.

## Epic 3: Clean invoices post to the accounts system automatically

Passing invoices post to the (simulated) accounts XML API with retries. Failures reach the admin queue with the API error. Approve sends checked exceptions to posting, and admin and finance can search every invoice.

### Story 3.1: Simulated accounts system

As Dj,
I want a simulated accounts XML API that behaves like the real one,
So that posting can be built and tested before the on-premises link exists.

**Acceptance Criteria:**

**Given** the `accounts-sim` app with built-in auth on its own app registration (created by the bootstrap, Story 1.1), accepting only its own environment's `pipeline` identity through `allowedPrincipals.identities`
**When** it is called with that identity's managed-identity token over TLS
**Then** `POST /api/invoices` accepts an invoice XML document, validates it against `adapters/accounts_xml/invoice-v1.xsd` (the contract), stores it in `sim_accounts` and returns an `accounts_ref` (AD-10, P-6)

**Given** the same `invoice_id` posted twice
**When** the second call arrives
**Then** the same `accounts_ref` is returned, and no second record is stored

**Given** an unauthenticated call
**When** it arrives
**Then** it gets 401

**Given** a signed-in human user, or any identity other than its own environment's `pipeline` (including the other environment's)
**When** it calls `accounts-sim`
**Then** the call is refused

**Given** the failure mode setting (for example "fail the next N calls")
**When** it is on
**Then** the API returns errors, so retries can be tested end to end

**Tasks:**
- Terraform: built-in auth on `accounts-sim` in `<env>/app`, with `allowedPrincipals.identities` set to the environment's `pipeline` identity.
- Python: `sim_accounts` migration (read/write for the `accounts-sim` login only, AD-11), `invoice-v1.xsd` in `adapters/accounts_xml/`, endpoint, failure mode.
- Tests: `test_story_3_1_*` for idempotency, auth, and schema rejection.

### Story 3.2: Clean invoices post automatically

As a finance user (Siti),
I want invoices that pass every check to reach the accounts system with no keying,
So that 90% of invoices need no admin at all.

**Acceptance Criteria:**

**Given** an invoice in `ready_to_post`
**When** the `post` stage runs
**Then** it claims `ready_to_post → posting` only when `next_attempt_at` is empty or past, and calls `AccountsPort.post_invoice`, where only the one adapter `adapters/accounts_xml/` builds the XML, valid against `invoice-v1.xsd`
**And** it saves `accounts_ref` under `invoice_id` before moving to `posted`, and `posted_at` equals the `at` of that `status_history` row (AD-3, AD-10)

**Given** a `q-post` message that arrives before `next_attempt_at`
**When** the stage runs
**Then** it re-enqueues the message with the remaining delay

**Given** a retry after `accounts_ref` was saved
**When** it runs
**Then** the accounts system is not called again

**Given** an accounts error
**When** posting fails
**Then** the adapter doesn't retry. In one transaction, the stage moves the invoice `posting → ready_to_post`, increments `post_failures`, sets `next_attempt_at` 1, 5, 15 or 60 minutes ahead and releases the lease; it then re-enqueues with that delay (AD-3)
**And** on the 5th failure, decided from `post_failures` and never from `QueueMessage.attempt`, it calls `route_to_admin(ACCOUNTS_API_ERROR)` with the API error in `detail`, never reaching the poison queue
**And** `post_failures` resets when the invoice enters `ready_to_post` from `validating` or `in_admin_queue`

**Given** `ACCOUNTS_BASE_URL` points at this environment's `accounts-sim`
**When** posting runs end to end
**Then** a clean supplier upload reaches `posted` with no human action (FR11)

**Tasks:**
- Python: `AccountsPort`, the one `adapters/accounts_xml/` adapter, `post` function with the `post_failures` backoff.
- Tests: `test_story_3_2_*` end to end from upload to posted, retries into `ACCOUNTS_API_ERROR`, a lost delayed message recovered by the sweeper without resetting the count, an early message re-delayed, and reuse of the saved `accounts_ref`.

### Story 3.3: Admin approves exceptions after checking them

As an admin (Priya),
I want to approve an invoice once I have checked it, including after a bank call-back,
So that genuine invoices get paid without re-keying.

**Acceptance Criteria:**

**Given** an item whose reasons all allow Approve
**When** the admin taps **Approve**
**Then** a reason is required, and a summary dialog shows the supplier, amount, and reason before the admin confirms (WCAG 3.3.4)
**And** the invoice moves to `ready_to_post`, `q-post` is enqueued, and the approval is audited

**Given** the reason `BANK_CHANGED`
**When** the item shows
**Then** Approve stays disabled until "Called the number on file" and "Supplier confirmed the new account" are both ticked, with the explanation "Tick both checks to approve." (UX-DR13)

**Given** the reason `DUPLICATE`
**When** the item shows
**Then** the matching invoice shows side by side, and Approve means "not a duplicate"

**Given** the reason `ACCOUNTS_API_ERROR`
**When** the item shows
**Then** the accounts system's error message shows, and Approve retries the posting

**Given** a mix of open reasons (latest `routing_id`) where one doesn't allow Approve
**When** the actions render
**Then** Approve is not offered, and the server refuses it too (AD-4)

**Given** single-key shortcuts are on (Story 2.11)
**When** the admin presses `a` in an item where Approve is offered
**Then** the Approve dialog opens, the same as the button

**Tasks:**
- Python: approve endpoint with checklist validation and audit.
- React: Approve dialog and summary, checklist gate, duplicate comparison, API error display.
- Tests: `test_story_3_3_*` for the reason matrix, checklist enforcement on the server, and audit.

### Story 3.4: Search all invoices

As a finance user (Siti),
I want to find any invoice and see where it is,
So that I can answer supplier and audit questions without asking the admins.

**Acceptance Criteria:**

**Given** an admin or finance user
**When** they open Invoices
**Then** they can search by supplier, invoice number, status, or supplier reference (`R-…`), paginated at 50 (UX-DR17)
**And** statuses show as labels (Processing, Checking, Re-checking, Posting, Posted, In admin queue, Rejected), never codes

**Given** a result
**When** it is opened
**Then** it shows the current extracted field values (AD-18), the status history from `intake.status_history` and the accounts reference
**And** finance never sees images or bank digits, only "Bank details on file"

**Given** any other role
**When** it calls the API
**Then** the request is refused

**Tasks:**
- Python: invoice search and detail API with role filtering.
- React: Invoices surface and detail.
- Tests: `test_story_3_4_*`; Vitest for the status labels.

## Epic 4: Deliveries are tracked, and overdue suppliers are reminded

Goods-in staff photograph paper invoices against a delivery. An overdue list shows missing invoices by supplier, suppliers see weekly reminders on their upload page, and each delivery shows its three dates (could-have).

### Story 4.1: Goods-in scans a paper invoice against a delivery

As a goods-in worker (Rahman),
I want to photograph the paper invoice that came with a delivery,
So that it enters the same automatic process as supplier uploads.

**Acceptance Criteria:**

**Given** a user with the `goods_in` role on a phone or tablet
**When** they open Goods-in scan
**Then** today's expected deliveries show first, with a search by PO number or supplier for late deliveries (UX-DR16)
**And** the layout follows the supplier-page rules (48px targets, single column)

**Given** a delivery is chosen and a photo passes the on-device check (the shared quality-check module from Story 1.9, with `shared/quality-thresholds.json`)
**When** they tap **Send**
**Then** `staff-api` looks up the supplier with `PurchasingPort.get_delivery(delivery_id)` and writes the blob with `source=goods_in`, `delivery_id` and the supplier, then enqueues `q-quality` (AD-5)
**And** it follows the AD-6 `Idempotency-Key` order (the key in `uploadkeys`, then the blob if missing, then the enqueue), so a retry never creates a second invoice
**And** the screen shows "Received for PO {po}, {supplier}."

**Given** the database is stopped
**When** goods-in opens
**Then** it shows "Scanning is unavailable until the system is back (weekdays 9am). Keep the paper invoice with the delivery."

**Tasks:**
- Python: goods-in upload endpoint; delivery list and search API.
- React: Goods-in screen reusing the capture and quality-check modules.
- Tests: `test_story_4_1_*` showing the supplier comes from the delivery, never from the invoice.

### Story 4.2: Overdue PO list

As a procurement user (Wei Ling),
I want a list of POs past their expected date with no invoice, grouped by supplier,
So that I can chase missing invoices.

**Acceptance Criteria:**

**Given** the weekday timers (01:30, 04:30 and 08:30 UTC)
**When** the first run of the day finds the database up
**Then** the analytics refresh job, created here as the only writer of `analytics` (AD-13), writes `analytics.overdue_po` from `PurchasingPort.list_overdue_pos`
**And** a PO is overdue when its earliest line `expected_date` is before today (Singapore date) and no invoice that is not `rejected` has it as its current `po_number` (AD-19); unlike AD-20, "invoiced" here does not wait for posting
**And** a PO expected at the weekend appears on Monday's list, and the list is computed from the last successful run, so no PO is missed

**Given** an admin, procurement or finance user
**When** they open Overdue POs
**Then** POs show grouped by supplier, with the date the list was made

**Given** a PO expected on 7 Jan with no invoice
**When** the list is made on 8 Jan
**Then** the PO appears under its supplier (FR12)

**Tasks:**
- Python: `analytics` schema migration (read/write for `pipeline`, read for `staff-api`, AD-11); the refresh job timer with its once-a-day guard; `analytics.overdue_po`; list API.
- React: Overdue POs surface.
- Tests: `test_story_4_2_*` for the 7 Jan / 8 Jan case, catch-up after a missed day, and grouping.

### Story 4.3: Suppliers see weekly reminders on their upload page

As a supplier (Mr Lim),
I want my upload page to show which deliveries still need an invoice,
So that I send them without anyone chasing me.

**Acceptance Criteria:**

**Given** a supplier with overdue POs
**When** the analytics refresh job reaches its first successful run of each ISO week
**Then** it replaces the supplier's partition in `supplierreminders` (`PartitionKey=supplier_id`, `RowKey=po_number`) with one row per overdue PO (AD-6, AD-13)
**And** it re-checks each PO against `intake` just before writing its row, so a delete by `validate` is not undone

**Given** those rows
**When** the supplier opens their link
**Then** Upload home shows the reminder banner "2 deliveries are waiting for an invoice: PO 45012, PO 45019." read-only, even while PostgreSQL is stopped (FR13)

**Given** an invoice for one of those POs is validated
**When** the supplier next opens the link
**Then** that PO is no longer in the banner (the cleanup is in Story 2.6)

**Given** the supplier
**When** reminders are sent
**Then** no email goes to the supplier

**Tasks:**
- Python: the weekly reminder step in the refresh job; `GET /api/reminders` in `supplier-api`, reading the supplier's partition identified by the `X-Upload-Token`.
- React: reminder banner.
- Tests: `test_story_4_3_*` for weekly timing, DB-stopped reads, and cleanup after an invoice.

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

**Given** the Deliveries tab
**When** it shows
**Then** each delivery lists the PO promised date, the delivery date on the invoice and the date received, plus the gaps between them in days (FR19)
**And** the tab is marked could-have in the backlog

**Tasks:**
- Python: delivery dates API via `PurchasingPort.get_delivery_dates`.
- React: Deliveries tab.
- Tests: `test_story_4_5_*` for the gap calculations.

## Epic 5: Finance and procurement see supplier price and speed insights

The analytics refresh builds summary tables that feed price comparison, the watchlist, scorecards and the finance month view. Alerts reach staff by email.

### Story 5.1: Analytics refresh builds the summary tables

As a finance user (Siti),
I want supplier figures pre-computed from posted invoices,
So that dashboards are fast and never load the invoice tables.

**Acceptance Criteria:**

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

**Given** a missed day
**When** the next run happens
**Then** it catches up from the watermark with no double counting

**Given** any dashboard API
**When** it runs
**Then** it reads only `analytics.*`

**Tasks:**
- Python: summary-table and `analytics.alert` migrations; the summary steps in the refresh job; read-only dashboard repository.
- Tests: `test_story_5_1_*` for incremental refresh, catch-up, idempotency, the trailing window, a corrected line counted once, lateness, and the straight-through share.

### Story 5.2: Staff alert emails

As a procurement or management user,
I want alerts by email with a link to the evidence,
So that I act on price rises and watchlist changes without checking dashboards daily.

**Acceptance Criteria:**

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

**Tasks:**
- Terraform: the `ACS Email Sender` assignment for `pipeline` in `<env>/app` (ACS and the domain are in Story 1.1).
- Python: `EmailPort` and ACS adapter with throttle; alert dispatch.
- Tests: `test_story_5_2_*` for the throttle, de-duplication and content rules.

### Story 5.3: Price comparison with price-rise alerts

As a procurement user (Wei Ling),
I want every supplier's price for a material side by side, and an alert when a supplier raises prices,
So that I buy from the best supplier.

**Acceptance Criteria:**

**Given** a material
**When** Price comparison opens
**Then** all suppliers' unit prices show side by side, with each supplier's on-time rate (FR14, UX-DR19)
**And** every chart has a one-sentence summary and a **View as table** toggle, and its series are told apart without color (UX-DR18)

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

**Tasks:**
- Python: price comparison API; price-rise rule in the refresh job.
- React: Price comparison surface; reusable Chart component.
- Tests: `test_story_5_3_*` for rule edge cases; Vitest and axe checks for the chart's table view.

### Story 5.4: Supplier watchlist with ranked alternatives

As a management user (Mr Goh),
I want suppliers watchlisted automatically, with the evidence and alternatives,
So that I can start the conversation with the right facts.

**Acceptance Criteria:**

**Given** a supplier with 3 or more price rises (Story 5.3) in the last 365 days, an average of 7 or more days late over the last 365 days (AD-20 lateness), or a latest price 5% or more above the lowest latest price for the same material among suppliers who posted in the last 90 days
**When** the refresh runs
**Then** the supplier is added to the watchlist, with the rule and evidence (invoices, dates, price history) (FR15)
**And** procurement and management are emailed: "{supplier} added to the watchlist: {rule}"

**Given** a watchlist entry
**When** it opens
**Then** it shows the evidence list, whose rows link to the invoice for admin and finance and are read-only for other roles
**And** below it, the alternatives: other suppliers with a posted price for the same material in the last 90 days, ranked by latest price, then by on-time rate (FR16, AD-20)

**Given** no posted invoices for the period
**When** Watchlist opens
**Then** it shows "No posted invoices yet for this period."

**Tasks:**
- Python: watchlist rules and alternatives query; API.
- React: Watchlist surface with evidence and alternatives.
- Tests: `test_story_5_4_*` for each rule threshold and the ranking.

### Story 5.5: Supplier scorecard

As a procurement user (Wei Ling),
I want a supplier's on-time rate and price trend per material,
So that I can decide an order with evidence.

**Acceptance Criteria:**

**Given** the supplier page (from Story 4.4)
**When** the Scorecard tab opens
**Then** it shows the on-time rate (on-time goods receipts divided by all receipts, AD-20) and the price trend per material from posted invoices, read through `analytics.*` (FR17)
**And** its charts follow the Chart pattern

**Given** no posted invoices for the period
**When** the Scorecard tab opens
**Then** it shows "No posted invoices yet for this period."

**Tasks:**
- Python: scorecard API.
- React: Scorecard tab.
- Tests: `test_story_5_5_*`.

### Story 5.6: Finance month view

As a finance user (Siti),
I want a monthly view per supplier,
So that month-end needs no re-keying.

**Acceptance Criteria:**

**Given** a month
**When** Finance month opens
**Then** a table per supplier shows spend, price-creep alerts, flagged count and duplicate count (FR18)
**And** the header shows the share of invoices posted without an admin against the 90% target (NFR19), read from the monthly straight-through share that Story 5.1 computes

**Given** a period with no posted invoices
**When** it opens
**Then** it shows "No posted invoices yet for this period."

**Tasks:**
- Python: finance month API.
- React: Finance month surface.
- Tests: `test_story_5_6_*` for the straight-through calculation.
