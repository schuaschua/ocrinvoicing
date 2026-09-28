# Adversarial Review (update): ARCHITECTURE-SPINE, OCR Invoice Automation PoC

- **Reviewer lens:** adversary. For each hole I build two units one level down (stories, apps, stages, jobs, Terraform steps). Each unit obeys every AD to the letter, yet the pair still builds something incompatible or unsafe.
- **Input:** `ARCHITECTURE-SPINE.md` (status `final`, 2026-09-28), AD-1 to AD-20. `epics.md` and `EXPERIENCE.md` were read for context. Line numbers refer to the spine.
- **Focus:** the newly added parts, which are the AD-2 sweeper map, AD-3 posting backoff, AD-11 grants, AD-17 steps and identities, AD-18 data model, AD-19 validation and AD-20 analytics.
- **Verdict:** **Much stronger than the first draft.** The earlier critical holes (claim-before-side-effect, the blob contract, the single analytics writer, reminders without PostgreSQL) are closed. The new detail opens its own holes, though. Three sit in the data model:
  - the current-value rule does not say which run it applies to;
  - bank fingerprints are compared across different field kinds;
  - admin items have no way to tell current reasons from old ones.

  Two more sit in failure handling: the posting-retry counter lives only in the message, and `route_to_admin` has no from-state guard. AD-17 has three identity and grant gaps that stop Story 1.6, Story 2.7 and the migrations as written. Each can be fixed by tightening one rule. None needs a redesign.

---

## Critical

### U-1 [Critical]: Bank fingerprints are compared across field kinds, so CAP-8 either flags every invoice or misses a changed IBAN

- **ADs:** AD-11 L267 (`master` holds "bank ciphertext and fingerprint", one value) and L273–276; AD-18 L431 (three bank field ids: `bank_account_number`, `iban`, `swift`); AD-19 L456 ("any extracted bank field whose fingerprint differs from the supplier's").
- **Pair:** Story 1.6 (the supplier load script) and Story 2.6 (`validate`, bank check).
  - The load script follows AD-11. It takes the CSV's "bank details" column and stores **one** ciphertext and **one** fingerprint per supplier.
  - `validate` follows AD-19. It compares the fingerprint of each extracted bank field against "the supplier's" fingerprint.
- **Outcome:** either way the build is wrong.
  - **Reading A:** every field is compared with the single master fingerprint. The `swift` code (`DBSSSGSG`) never equals an account number. So every invoice that prints a SWIFT code, or both an IBAN and an account number, goes to `BANK_CHANGED`. The 90% straight-through target (CAP-18) becomes out of reach, and admins learn to tick the call-back checklist without calling.
  - **Reading B:** a builder sees that A is absurd and compares only "matching" fields. Master has no `iban`, so a fraudster who prints a new IBAN (with the old local account number, or none) raises nothing. That is exactly the fraud CAP-8 exists to stop.
- **Also to test early:** check that DI `prebuilt-invoice` 2024-11-30 returns a local account number at all. Its payment details are IBAN/SWIFT oriented. If it doesn't, `bank_account_number` is never extracted and CAP-8 is silently dead for Singapore suppliers.
- **Fix (AD-11 and AD-19):**
  - `master` stores one ciphertext and fingerprint **per AD-18 bank field id**. Its shape is `master.supplier_bank{supplier_id, field_id, ciphertext, fingerprint}`, and the load script's CSV has one column per field id.
  - `BANK_CHANGED` fires for an extracted bank field when the master has **no** value for that field id, or when the fingerprints differ. The failure is safe.
  - Comparison is always field to same field.
  - Add "DI returns a local account number" to Open Questions → To test early.

---

## High

### U-2 [High]: The current-value rule ignores runs, so stale DI rows outlive a re-extract, and extract's "reuse the saved run" blocks Re-extract

- **ADs:** AD-18 L425–430 ("For each field or line, the newest row wins"; lines keyed by `line_no`); AD-3 L110 ("saved under `invoice_id` … a retry reuses it"), L115 (Re-extract).
- **Pair A:** `pipeline/extract` (Story 2.3) and `pipeline/validate` (Stories 2.5/2.6) around an admin Re-extract.
  - Run 1 read 5 lines and `purchase_order`. Validate hit a bug, and after 5 dequeues it went to poison and `PROCESSING_FAILED`. The admin chose Re-extract.
  - **Extract** follows AD-3 exactly: "a retry reuses [the saved result]" under `invoice_id`. Run 1 exists, so DI is **not** called again. Re-extract quietly becomes re-validate.
  - Suppose a builder does call DI again, creating run 2 with 4 lines and no `purchase_order`. Then **validate** applies "the newest row wins" per field and per line. The newest `line_no=5` row is still run 1's, and the newest `purchase_order` is still run 1's.
  - The stale line enters the PO sum (AD-19 L447). The "a missing checked field counts as confidence 0" rule (L437) never fires, because a stale value exists.
- **Pair B:** admin Correct (Story 2.10) followed by a later Re-extract.
  - The Correct row (`source=admin`, older) loses to the new run's DI row, which is newer. The correction is dropped silently.
  - The spine also never says which `run_id` an admin row carries.
- **Pair C:** Correct on a line.
  - `invoice_line` is a whole-row entity. One builder writes an admin row holding only the corrected `quantity`, with the other columns null.
  - "Newest row wins" then makes `product_code` null, and the line stops matching its PO.
- **Fix (AD-18 "Current value" and AD-3 "Save the result"):**
  - The current values are the rows of the invoice's **latest `extraction_run`**, overlaid by `source=admin` rows that carry **that `run_id`**.
  - Rows from earlier runs are never current. So a new run drops earlier corrections, which is intended, because Re-extract means re-read.
  - An admin line correction writes a **complete** line row, copying every uncorrected column.
  - Extract reuses a saved run only if it was created **after the invoice's latest transition into `awaiting_extraction`**, read from `status_history`.

### U-3 [High]: `admin_item` can't tell current reasons from earlier ones, so the queue and the action guard read stale reasons

- **ADs:** AD-4 L150–151 (`admin_item{…, run_id, …}`, no status column, resolutions only in `audit`); AD-18 L425 (`run_id` is the extraction run); AD-3 L113 (Correct → re-validate on the same run).
- **Pair:** `pipeline/validate` (writes reasons) and `staff-api` queue/item and action guard (Stories 2.8, 2.10, 3.3).
  - Pass 1 routes `LOW_CONFIDENCE` + `BANK_CHANGED`. The admin Corrects the low-confidence field. Re-validation routes `BANK_CHANGED` only, under the **same `run_id`**, because no new extraction happened.
  - Staff-api follows AD-4 and lists the invoice's `admin_item` rows. It has only `invoice_id` and `run_id` to group by, and both passes share them. So the chips still show "Unsure reading".
  - The server-side action guard (Story 3.3, "Approve is offered only if every reason allows it") evaluates the stale set as well.
  - Story 2.5 already reads `run_id` as "one routing batch" ("`route_to_admin` writes them all under one `run_id`"). That is a second, incompatible meaning of the same column.
  - A poison-created item (`PROCESSING_FAILED` before extraction) has no run at all.
- **Outcome:** the wrong actions are offered or refused, and "Returned after correction" shows mixed old and new reasons. With `ACCOUNTS_API_ERROR` after an earlier `DUPLICATE` Approve, the stale `DUPLICATE` chip blocks the Approve that should retry the posting.
- **Fix (AD-4):**
  - `admin_item` gains `routing_id`, one UUIDv7 per `route_to_admin` call, and `run_id` becomes nullable.
  - An invoice's open reasons are the items of its **latest** `routing_id`. The queue, the item view and every server-side action guard read only those.

### U-4 [High]: The posting failure count lives only in the message, so the sweeper and admin Approve reset it or double it

- **ADs:** AD-2 L79 (`QueueMessage{…, attempt}`), L90 (the sweeper re-enqueues `ready_to_post` whose `next_attempt_at` is empty or past); AD-3 L111; AD-10 L245–246 ("On the 5th failure …").
- **Pair:** `pipeline/post` (Story 3.2, which counts failures in `attempt`, "carrying `attempt`") and the `pipeline` sweeper (Story 2.2).
  - The accounts system is down. Post fails and sets `next_attempt_at = now + 60 min`, which moves `status_changed_at` too. It re-enqueues with a 60-minute delay and `attempt=4`.
  - That message is lost. Every Storage Queue has a TTL, and a crash between the commit and `send_message` is exactly the case the sweeper exists for.
  - The sweeper builds a new `QueueMessage`. The spine doesn't say what `attempt` it carries, and the sweeper has no source for it, so it uses 0 or 1.
  - Post restarts the 1/5/15/60 ladder, and the invoice loops for as long as the outage lasts, never reaching `ACCOUNTS_API_ERROR`.
  - The reverse also happens. The sweeper's copy and the delayed copy both exist (L92, "a duplicate is harmless"). Each carries its own `attempt`, and the higher one wins, so admin escalation can come early.
  - The post claim (AD-3 L107) doesn't check `next_attempt_at` either. So a duplicate message makes the next attempt early, and the backoff is not enforced.
- **Fix (AD-3 "Posting backoff"):**
  - Store `post_failures` on `intake.invoice`. It is incremented in the same transaction as `posting → ready_to_post`, and reset when the invoice enters `ready_to_post` from `validating` or `in_admin_queue`.
  - The 5th failure is decided from that column, and `QueueMessage.attempt` is informational only.
  - The post claim adds `AND (next_attempt_at IS NULL OR next_attempt_at <= now())`. A message that is too early is re-enqueued with the remaining delay.

### U-5 [High]: `route_to_admin` has no from-state guard, so a poison message can pull an invoice that has already posted into the queue, and it can then be Rejected

- **ADs:** AD-4 L150 ("works from **any** non-terminal state"); AD-2 L94 (the poison trigger calls `route_to_admin(PROCESSING_FAILED)`); AD-3 L106 (every *other* transition is conditional on `from`), L110, L116 (Reject).
- **Pair:** `pipeline/post` and the `q-post-poison` trigger (Story 2.2), then `staff-api` Reject (Story 2.10).
  - Post claims the invoice, and the accounts call **succeeds** and returns `accounts_ref`. The save of `accounts_ref` then throws a non-connection error, such as a constraint or serialisation error, or a bug. This is not AD-7's "can't connect".
  - After 5 dequeues the message reaches poison. The trigger calls `route_to_admin` from `posting`, which AD-4 allows.
  - The admin sees "Processing failed". The UX table offers Re-extract or Reject, and the admin **Rejects** it.
- **Outcome:** the invoice is posted, and will be paid, in the accounts system but `rejected` in intake. Analytics never counts it (AD-20 uses posted only). Nothing reconciles the two.
- **Same hole, second path:** a validate worker whose 10-minute lease expired while it waited on `pg_advisory_xact_lock`. A second worker takes over and completes to `ready_to_post`. The first worker then calls `route_to_admin` and pulls the invoice back out of `ready_to_post` or `posting`.
- **Fix (AD-4):**
  - `route_to_admin(invoice_id, reasons, from_status)` is conditional like every transition. A stage passes its claim state, and zero rows means the result is discarded.
  - The poison trigger routes only when the invoice is in the input state of that queue, or in its claim state with an expired lease.
  - Reject is refused when `accounts_ref` exists, so such an invoice can only be Approved, which re-posts it idempotently.

### U-6 [High]: The PO match uses cumulative receipts, so the second invoice against any PO always fails

- **ADs:** AD-19 L447 ("the PO unit price times the quantity received so far (`get_receipts`)"); AD-10 L249.
- **Pair:** Story 2.4 (sim seed with partial deliveries, several receipts per PO) and Story 2.5 (`validate` PO match).
  - A PO for 100 units is delivered as 50 + 50, and the supplier invoices each delivery. Invoice 1 matches, because 50 units are received.
  - Invoice 2 arrives after the second receipt. It is compared against 100 received units, and its `sub_total` is half of that, so it raises `PO_MISMATCH`.
  - Every partial-delivery supplier goes to the admin queue. An invoice for the **whole** PO sent after only the first delivery fails too, which is correct, but the rule can't tell the two cases apart.
- **Fix (AD-19):** the expected amount for a matched PO line is its unit price times (quantity received so far minus the quantity already invoiced). "Already invoiced" is the current line quantities of the other, non-rejected invoices matched to that `po_line_id`. For a goods-in scan, it is the quantity received on **that delivery**. Compute it under the same per-supplier advisory lock as AD-9.

### U-7 [High]: The upload idempotency rule has no write order, so a retry can confirm an invoice that was never stored

- **ADs:** AD-6 L177–180 (create id, write blob, enqueue; `uploadkeys` returns the same `invoice_id` "within 24 hours"); AD-2 L83 (the sweeper sees only rows in PostgreSQL).
- **Pair:** `supplier-api` upload (Story 1.8) and the same endpoint on a retry.
  - One builder writes `uploadkeys` first, which is natural, because it reserves the key. The function then dies before the blob write or before `send_message`.
  - The phone retries, the key is found, and AD-6 says to "return the same `invoice_id`". The supplier sees "Received. Reference R-…", but there is no blob, or no message.
  - No `intake.invoice` row exists, so the sweeper can never find it. The invoice is lost silently, while the supplier holds a valid-looking reference.
  - The opposite order (blob, enqueue, then key) creates two invoices on a retry after a crash. That case is safe, because AD-9 catches it.
- **Fix (AD-6 "Uploads"):**
  - Insert the key first with `invoice_id`, using `insert-if-absent`.
  - Write the blob to `images/<invoice_id>`, overwriting is harmless, and then enqueue.
  - A retry that finds the key **re-runs the blob-if-missing and enqueue steps** before returning. A duplicate message is harmless (AD-2).
  - Give goods-in uploads (`staff-api`) the same `Idempotency-Key` rule.

### U-8 [High]: AD-17 steps can't grant what AD-11 and AD-14 need (database ownership, Dj's user, built-in auth)

- **ADs:** AD-11 L280–292; AD-12 L306; AD-14 L337; AD-17 L386–393, L404; `azure.md` rule 31 (deploy identity: RBAC Administrator on its resource group, **only runtime roles and only for service principals**, no directory rights); Conventions L486 ("the only secrets are the pgcrypto and HMAC keys").
- **(a) Step 6 migrations and step 2 databases.**
  - AD-11 L291 revokes `CONNECT` from `PUBLIC` on both databases, and L292 makes "every grant an Alembic migration".
  - Step 2 creates the databases through Terraform, so they are owned by the server admin, not by the env deploy identity.
  - Only a database's owner, or a superuser-like admin, can `REVOKE CONNECT … FROM PUBLIC`, `GRANT CONNECT` to each login, or `GRANT CREATE ON DATABASE` to the deploy identity. The migration running as the deploy identity (step 6) therefore fails on its first grant, or cannot even `CREATE SCHEMA`.
  - PostgreSQL roles are also **cluster-wide**, so AD-12's "logins exist only in its own database" is false. `CONNECT` is the only barrier, and nothing in the step table performs it.
  - **Fix:** step 5 (operator, as Entra admin) also runs, per database: `ALTER DATABASE … OWNER TO <env deploy identity>`, `REVOKE CONNECT … FROM PUBLIC`, and `GRANT CONNECT` to each login in its own environment. Reword AD-12 L306 to "each environment's logins can connect only to its own database".
- **(b) Dj's user (the load script).**
  - It needs Key Vault secret read (the pgcrypto and HMAC keys) and Table data write on `supplierlinks` in each environment. Nobody grants them.
  - Step 4 and step 7 run as the deploy identity, which by rule 31 can assign roles **only to service principals**. The bootstrap, step 1, runs before the Key Vault and storage exist.
  - **Fix:** a new operator step after step 4 grants Dj's user Key Vault Secrets User and Storage Table Data Contributor, scoped to that environment's vault and storage account. Name it in the AD-17 table.
  - The same gap exists for writing the Key Vault secrets in step 4. The deploy identity needs Key Vault Secrets Officer, which is not a runtime role. Either list it as an allowed exception, or use access-policy mode.
- **(c) Built-in auth on `staff-api` and `accounts-sim`.**
  - The server-directed login in AD-14 (redirect plus session cookie) needs a client secret, or a federated credential on the app registration. The Conventions forbid the secret. A federated credential, and the redirect URI `https://<staff-api host>/.auth/login/aad/callback`, need **directory rights**.
  - Only the bootstrap has directory rights, and it runs at step 1, before the app (step 7) and its identity (step 4) exist. Flex default host names may carry a random suffix.
  - **Fix:** name the mechanism. Either use an ID-token-only login with no secret, where the bootstrap enables ID tokens and registers the redirect URI from the fixed P-16 host name (unique default host name turned off). Or add an operator step after step 7 that adds the federated credential and the redirect URI.

### U-9 [High]: `accounts-sim` has no audience of its own, so any assigned staff user (or any identity in the tenant) can post invoices

- **ADs:** AD-1 L65; AD-10 L243 ("called with a managed-identity token"); AD-17 L386 (bootstrap creates "**the** Entra app registration", one only).
- **Pair:** Story 3.1 (`accounts-sim` built-in auth, Terraform) and Story 2.7 (the staff app registration).
  - The only app registration that exists is staff-api's. The Story 3.1 builder points `accounts-sim` built-in auth at it, because nothing else exists.
  - A `goods_in` user's token for that audience is accepted by `accounts-sim`. That user can call `POST /api/invoices` directly and create a posted record, bypassing every check.
  - If the builder instead sets an audience with "assignment required" off, **any** managed identity in the tenant can post. That includes Dev's `pipeline` against Prod's simulator.
  - This matters beyond the simulation, because AD-10 L244 says the switch to the real system changes only the URL and the auth settings.
- **Fix (AD-10):**
  - `accounts-sim` has its own app registration, created in bootstrap.
  - Its built-in auth sets `allowedApplications` / `allowedPrincipals.identities` to **its own environment's `pipeline` identity only**. That needs no directory rights and can be set in step 7.
  - Human users are refused.

---

## Medium

### U-10 [Medium]: AD-2's zero-row recovery contradicts AD-3's claim acknowledgement for claim transitions

- **ADs:** AD-2 L82 ("a redelivered message whose transition changes zero rows, where the invoice is already in the transition's target state, re-enqueues the next stage"); AD-3 L109 ("a claim that changes zero rows means another worker has the invoice, so the message is acknowledged").
- **Pair:** `pipeline/extract` and `pipeline/validate` with a duplicate `q-extract` message.
  - The first transition a stage attempts is its **claim**. The claim's target is `extracting`.
  - A duplicate finds the invoice `extracting` (another worker holds it), so AD-2 says re-enqueue the next stage (`q-validate`), while AD-3 says acknowledge. Two builders pick differently.
  - The AD-2 reading sends `q-validate` while extraction is still running. That is harmless only by luck, because the validate claim changes zero rows. For `post` finding the invoice `posting`, "the next stage" is undefined.
- **Fix (AD-2):** state it per stage. "A stage whose claim changes zero rows checks the invoice's status. If it is the stage's **final** target (`awaiting_extraction` for quality, `awaiting_validation` for extract, `ready_to_post` or `in_admin_queue` for validate, `posted` for post), it re-enqueues the next queue, if there is one. Otherwise it acknowledges."

### U-11 [Medium]: The sweeper cadence is stated twice, differently, and the stuck alert fires every morning

- **ADs:** AD-2 L83 ("a `pipeline` sweeper timer runs every 15 minutes"); AD-13 L317 ("`pipeline` timers run Monday to Friday at 01:30, 04:30 and 08:30 UTC"), which is unqualified and so covers the sweeper; AD-17 L413 (`stuck_invoices` > 0 raises an alert).
- **Pair:** Story 2.2, already written to AD-13's times, and the AD-2 recovery guarantee.
  - At 3 runs a day, a stranded invoice waits up to about 17 hours, and never over a weekend.
  - At 15 minutes, every morning when Dj starts the database, every invoice caught mid-pipeline overnight has `status_changed_at` older than 1 hour. So it counts as "stuck", and a false alert fires every weekday.
- **Fix:** AD-13 says "analytics and reminder timers". AD-2 keeps 15 minutes, and the sweeper counts an invoice as stuck only if `status_changed_at` is more than 1 hour older than the **database's last start**, taken from `pg_postmaster_start_time()`.

### U-12 [Medium]: Duplicate detection is symmetric and matches rejected photos, so both copies are flagged and every resent photo is flagged

- **ADs:** AD-9 L227–230 (fingerprint excludes `rejected`; the phash compares "any of the same supplier's hashes"; hashes are kept forever).
- **Pair A:** two copies A and B that are both extracted before either validates, which is common because goods-in and the supplier send the same paper invoice.
  - The advisory lock serialises the two runs, but each finds the other: A matches B's fields, B matches A's.
  - **Both** get `DUPLICATE`. Story 2.6 expects "exactly one", so the spine rule and the story test disagree.
- **Pair B:** an admin Rejects an `UNREADABLE` photo with "Ask the supplier to send it again". The clear resend is within Hamming distance 8 of the rejected blurry photo, whose hash is kept. The resend is flagged `DUPLICATE`, every time.
- **Fix (AD-9):** compare only against invoices that are **not `rejected`** (for both hash and fingerprint) and that come **earlier in `invoice_id` (UUIDv7) order**.

### U-13 [Medium]: `route_to_admin` creating the row, and Re-extract, both skip the quality stage

- **ADs:** AD-4 L150 ("creates the invoice row if it's missing", with signature `(invoice_id, reasons)`); AD-5 L163 ("only the `quality` stage inserts `intake.invoice`"); AD-3 L115 (Re-extract → `awaiting_extraction`).
- **Pair:** the `q-quality-poison` trigger and `staff-api` Re-extract.
  - When the poison trigger creates the row, `route_to_admin` has no supplier and no metadata. So either `supplier_id` is null, which breaks AD-5, or the trigger reads the blob itself, which is a second row-creation path that contradicts L163.
  - The admin then chooses Re-extract, and the invoice jumps to `awaiting_extraction`. The invoice never had its EXIF orientation applied, its `photo_taken_at` saved, its phash stored or its page count checked.
  - So a 10-page PDF spends 10 DI pages, and the photo gets `NO_PHOTO_DATE` and no phash duplicate check.
- **Fix:**
  - `route_to_admin` takes `IntakeBlobMetadata` whenever it may create the row.
  - Add the transition `in_admin_queue → received` ("admin retry"), which re-enqueues `q-quality`. It is used for `PROCESSING_FAILED` when quality never completed, meaning no `image_hash` row and no `photo_taken_at` decision has been recorded.

### U-14 [Medium]: The DI rate limit can't hold across Flex instances, and a 429 during polling analyses the document again

- **ADs:** AD-8 L211 ("at most 1 request every 2 seconds in each environment, polling calls included"); AD-2 L95 (`batchSize` 1 limits concurrency per **instance** only); AD-1 (Flex with on-demand instances and no instance cap); AD-7 L199 (a 429 re-enqueues the message).
- **Pair:** two `extract` instances in Prod, because Flex scales queue functions per function. An in-process limiter in `adapters/document_intelligence.py` gives each instance 0.5 requests a second.
  - Two instances plus Dev exceed F0's 1 request a second.
  - A 429 on a **poll** re-enqueues the message. The retry has no saved result, so it starts a new `analyze`. The pages are billed again by F0 and counted again in `di_usage`.
- **Fix (AD-8):**
  - Throttle through PostgreSQL: a row with the last call time in `intake.di_usage`, updated under `pg_advisory_xact_lock`.
  - Save the `Operation-Location` against `invoice_id` before polling, so a retry resumes polling instead of re-analysing.
  - Also reserve the pages in `di_usage` before the call, so concurrent instances can't both pass the cap check.

### U-15 [Medium]: "Invoiced" means different things to validate and to the refresh job, so suppliers are reminded about invoices they already sent

- **ADs:** AD-6 L187 (validate deletes the reminder row when a matched invoice arrives, "so the banner never lists a PO that has already been invoiced"); AD-13 L319–320; AD-20 L464 ("the refresh job computes these from **posted invoices only**").
- **Pair:** Story 2.6 (reminder delete) and Story 4.2/4.3 (the refresh job builds the overdue list and the reminder rows).
  - Validate deletes the row for PO 45012, and the invoice then sits in the admin queue for a week.
  - Monday's refresh obeys AD-20's "posted only". PO 45012 still has no posted invoice, so the job rewrites the reminder row, and the supplier is nagged for an invoice they already sent.
  - A race makes it worse. The refresh reads PostgreSQL at 01:30 and writes Table rows afterwards. A validate that deletes in between is undone.
  - Nothing ever removes a row for a PO that was cancelled or closed.
  - The Table entity shape (`PartitionKey`/`RowKey`) is not fixed. Validate deletes by PO, while `supplier-api` reads by supplier.
- **Fix:**
  - AD-13 says the overdue list and reminders count a PO as invoiced when any **non-rejected** invoice's current PO (AD-19) is that PO. This is an explicit exception to AD-20's posted-only rule.
  - The weekly write **replaces** a supplier's partition.
  - Just before writing each row, the refresh re-checks that PO against `intake`.
  - Fix the entity shape as `PartitionKey=supplier_id, RowKey=po_number`.

### U-16 [Medium]: AD-20's inputs are unfixed (current rows, the posting watermark, receipts, "previous price")

- **ADs:** AD-20 L464–473; AD-13 L318 (a `posted_at` watermark, a field defined nowhere in AD-3 or AD-18); AD-18 L429–430.
- **Pair:** Story 5.1 (refresh) and Stories 3.2/2.10 (the writers of lines and posting times).
  - **Superseded rows:** the refresh joins `invoice_line` on `material_id` without the current-value rule. A line corrected by an admin then contributes two prices, the DI one and the admin one.
  - **Watermark gaps:** `posted_at = now()` is set inside the post transaction. A transaction that commits after the refresh has read `max(posted_at)` but carries an earlier timestamp is **skipped forever**. Post runs whenever the database is up, and so does the refresh.
  - **Receipts:** lateness (L471) is computed from goods receipts, which are not posted invoices. A watermark on `posted_at` never picks up a receipt recorded after the invoice posted, so on-time rates go stale.
  - **"Previous posted price":** a builder might order by `posted_at`, or by `invoice_date`. An old invoice posted late after admin handling becomes a fake "rise" or hides a real one. Each rise also counts toward the watchlist (L466).
- **Fix (AD-20):**
  - Lines are read through the AD-18 current-value rule.
  - `posted_at` is the `at` of the `status_history` row that moved the invoice to `posted`. The refresh reprocesses a trailing window (watermark minus 1 hour) idempotently, keyed by `invoice_id`.
  - Lateness is recomputed in full over 365 days on each run. It is cheap at PoC volume.
  - "Previous" is ordered by `invoice_date`, then `invoice_id`.
  - `analytics.alert` gets `emailed_at`, so an alert that was throttled or hit by a crash is still sent (Story 5.2).

---

## Low (worth one line each)

- **AD-11 L271 and L286.** `audit` is "written by every app", but `accounts-sim` has no `audit` grant and `supplier-api` has no login. The row should read "every app with a database login".
- **AD-11 L284.** `pipeline` holds the pgcrypto key (it must encrypt extracted bank fields), so hiding the `master` ciphertext columns from it protects only against a leaked connection, not a leaked process. Record that as accepted, or split encryption from decryption with `pgp_pub_encrypt`, so that only `staff-api` holds the private key.
- **AD-18 L435.** Bank fields are "checked" for `LOW_CONFIDENCE`, yet they are never editable (UX). A misread bank field returns after every Correct.
  - A fingerprint match with the master already proves the read was right, and a mismatch already raises `BANK_CHANGED`.
  - **Fix:** remove bank fields from the checked set.
- **AD-3 L113.** Correct's admin rows and the transition must be one transaction (otherwise, when another admin acts first, rows are left behind). The `corrections` blob is written after the commit.

---

## Stories that contradict the spine (fix them before building)

The spine is right in each case below. The story will be built wrong unless it is edited.

| Story | Says | Spine | Risk |
| --- | --- | --- | --- |
| 1.7 | link is `…/u/<token>` | AD-6 L172: token in the fragment, `/u#<token>` | **High:** the token lands in App Insights request telemetry and server logs |
| 2.3 vs 2.6 | extract "stores every field"; encrypting bank fields is a task in 2.6 (`validate`) | AD-11 L273: ciphertext "from its first write", which is extract | **High:** plaintext bank values in `invoice_field` once 2.3 ships |
| 2.2 | sweeper runs at 01:30/04:30/08:30 UTC; "unclaimed" invoices | AD-2 L83: every 15 minutes, by the status map | Medium (see U-11) |
| 2.4 | the adapter reads "through its own database role" | AD-10 L250: no per-adapter role; import-linter | Low |
| 2.5 | compares the invoice **total**; `run_id` is the routing batch | AD-19 L447: pre-tax `sub_total`; AD-18: `run_id` is the extraction run | Medium (see U-3) |
| 2.6 | `DATE_MISMATCH` against "the invoice delivery date" | AD-19 L451: latest goods-received date, from 0 to 30 days | Medium |
| 2.11 | setting "stored with the user profile" | AD-14 L343: `localStorage`, no server profile | Low |
| 3.2 | `ACCOUNTS_ADAPTER=sim` | AD-10 L244: only `ACCOUNTS_BASE_URL` and auth | Low |
| 4.2 | "daily or weekdays is still open" | AD-13 L319: weekdays, decided | Low |
| 5.2 | throttle 30/min, 100/h "across both environments" | AD-16 L364: per-environment caps with no shared state | Low |

---

## Proposed spine deltas (summary)

1. **AD-11 and AD-19:** store bank ciphertext and fingerprint per bank field id. A field that has no master value, or whose fingerprint differs, raises `BANK_CHANGED`. (U-1)
2. **AD-18:** current value = the latest run's rows plus admin rows carrying that `run_id`. Admin line rows are complete rows. **AD-3:** extract reuses a run only if it was created since the invoice last entered `awaiting_extraction`. (U-2)
3. **AD-4:** add `admin_item.routing_id`. Open reasons are those of the latest routing. `route_to_admin` takes `from_status` (and the metadata when it creates the row). Poison routes only from its own stage's states. Reject is refused once `accounts_ref` exists. (U-3, U-5, U-13)
4. **AD-3:** add `invoice.post_failures`, and the claim respects `next_attempt_at`. (U-4)
5. **AD-19:** expected PO amount = received minus already invoiced, or the delivery's receipt for goods-in. (U-6)
6. **AD-6:** write order key, then blob, then enqueue. A retry replays the missing steps. (U-7)
7. **AD-17:** step 5 also transfers database ownership and handles `CONNECT`. Add an operator step for Dj's user and for Key Vault writes. Name the login mechanism for built-in auth and when its redirect or credential is registered. (U-8)
8. **AD-10:** `accounts-sim` gets its own app registration and accepts only its environment's `pipeline` identity. (U-9)
9. **AD-2 and AD-13:** zero-row handling is defined per stage. The 15-minute sweeper is excluded from AD-13's timer times, and stuck counts are measured from the database's start time. (U-10, U-11)
10. **AD-9:** compare only against earlier, non-rejected invoices. (U-12)
11. **AD-8:** throttle and reserve pages through PostgreSQL, and resume polling from the saved `Operation-Location`. (U-14)
12. **AD-13 and AD-20:** define "invoiced" for reminders, how the reminder partition is replaced, and the entity keys. Also a trailing-window watermark, full recompute of lateness, `invoice_date` ordering for "previous" and `alert.emailed_at`. (U-15, U-16)
