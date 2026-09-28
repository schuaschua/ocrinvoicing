# Adversarial Review: ARCHITECTURE-SPINE (OCR Invoice Automation PoC)

- **Reviewer lens:** adversary. I built pairs of units one level down, each following every AD exactly, that still don't fit together.
- **Inputs:** `ARCHITECTURE-SPINE.md` (draft, 2026-09-28) and `SPEC.md`.
- **Verdict:** **Not yet a safe build substrate.** The layering, ports and schema ownership are sound. But the spine fixes the *shape* of hand-offs without fixing their *failure semantics*. Five holes will produce stranded invoices, double posts, or two teams writing the same entity. They are all closable with tightened rules, and no redesign is needed.

Severity: **Critical** means data loss, a double payment or a stuck invoice in normal operation. **High** means two stories will build incompatible code. **Medium** means a contradiction or gap that someone will find late.

---

## H-1 [Critical]: "Update status, then enqueue" strands invoices, and AD-3's duplicate rule hides it

**ADs:** AD-2 (stage finishes by status change then enqueue), AD-3 (zero rows means duplicate, so acknowledge and stop), AD-7.

**Pair:** `pipeline/extract` vs `pipeline/validate` (the same applies to every stage-to-stage edge and to `staff-api` admin Correct/Approve).

1. The extract stage runs `UPDATE … SET status='awaiting_validation' WHERE status='awaiting_extraction'` and commits, then the host dies (Flex scale-in, timeout or deploy) before `q-validate` is enqueued.
2. The original `q-extract` message becomes visible again and is redelivered.
3. The same UPDATE now changes zero rows, so under AD-3 it is "a duplicate: acknowledge it and do nothing more".
4. The invoice sits in `awaiting_validation` forever, with no message anywhere. No reason is recorded, no admin item exists and no alert fires. The CAP-9 promise that every exception is visible is broken silently.

Both stories obey the ADs. The hole is that AD-3 cannot tell "someone else already did it" apart from "I did it and crashed before handing off".

The same pattern hits `staff-api`. Admin Approve commits `in_admin_queue → ready_to_post`, then the enqueue to `q-post` fails (a storage blip), and the admin sees success while nothing posts.

**Fix (new AD-2a, "Hand-off is resumable"):**
- A stage's zero-row result is classified by reading the current status:
  - If the current status equals the transition's **`to`** state, the handler re-enqueues the next stage's message and acknowledges. The next stage is idempotent (H-2), so this is safe.
  - If the status is anything else, acknowledge and do nothing, as today.
- A **stuck-invoice sweeper** timer (weekdays, same slot as AD-13) re-enqueues the owning stage's message for every invoice in a non-terminal, non-`in_admin_queue` status whose `status_changed_at` is older than 1 hour. This needs a `status_changed_at` column that every transition sets.
- `staff-api` admin actions follow the same rule: commit the transition, enqueue, and on enqueue failure return 503. The sweeper is the backstop.
- The alternative is a transactional outbox table in `intake`, with a relay. That is heavier, so the rule above is recommended for a PoC.

## H-2 [Critical]: Side effects happen *before* the conditional update, so redelivery and AD-7 duplicates double-call DI and double-post

**ADs:** AD-3 (conditional update as the idempotency gate), AD-7 (re-enqueue, then complete the original), AD-10 (`invoice_id` as idempotency key), AD-8 (page counting), AD-13 (post stage updates analytics).

**Pair A: `pipeline/post` vs itself (at-least-once).**
- AD-3's gate is the *final* UPDATE `ready_to_post → posted`, but `AccountsPort.post_invoice` runs before it.
- A redelivered message, or a second copy, runs `post_invoice` again. Visibility timeout expiry during a slow accounts call causes this, and so does AD-7 when the re-enqueue succeeds but completing the original fails.
- `invoice_id` as idempotency key only helps if the **real** accounts XML API honours it. Nothing in the spec says it does, and Q9 is deferred.
- `accounts-sim` has **no storage** in AD-11's schema table, so the sim cannot honour the key either. The implementer will choose between in-memory (lost on scale-out) and some ad-hoc store.

**Pair B: `pipeline/extract` vs `intake.di_usage`.** The same redelivery calls DI twice and counts the pages twice. Near the 500-page ceiling, invoices go to `EXTRACTION_QUOTA` early.

**Pair C: `pipeline/validate` concurrent copies.** Validate has no max-instances limit. Two copies run all checks at the same time and both write `intake.admin_item` rows, giving duplicate reasons. Only one wins the status UPDATE, but both wrote their items.

**Fix (tighten AD-3, "Claim before side effect"):**
- Every stage whose work has an external side effect first **claims** the invoice with a conditional transition into a transient state: `extracting`, `validating`, `posting`. The claim carries a `claimed_at` lease of 10 minutes.
- Side effects run only after a successful claim. On completion the stage transitions from the transient state.
- A redelivered message that finds the transient state with an unexpired lease acknowledges. With an expired lease, it re-claims.
- Side-effect results are persisted keyed by `invoice_id` **before** the final transition:
  - The DI raw result goes in `intake.extraction` with a unique `invoice_id`. On retry, extract reuses the stored result and does not call DI or count pages again.
  - `accounts_ref` goes on the invoice. Post checks it before calling `AccountsPort`.
- Validate replaces its admin items as a set: `DELETE … WHERE invoice_id AND run superseded`, then INSERT, in the same transaction as the status transition.
- Add schema **`sim_accounts`** to AD-11, written only by `accounts-sim`, with a unique constraint on `invoice_id`.
- State as a port contract that `AccountsPort.post_invoice` must be idempotent on `invoice_id`, and list "real accounts API idempotency" as an Open Question under Q9.

## H-3 [High]: The invoice row's birth has no owner contract. Blob metadata is the only carrier, it is unspecified, and goods-in has two plausible resolvers

**ADs:** AD-3 (`[*] → received: quality stage creates row`), AD-5 (supplier from link or delivery), AD-6 (supplier-api never touches PostgreSQL; metadata `supplier_id`, `source`, `delivery_id`), AD-11 (`intake` written by pipeline and staff-api *admin actions*).

**Pair A: `supplier-api` upload vs `pipeline/quality`.**
- The only data path from the upload to the row is blob metadata, and its contract is one sentence long.
- Unspecified details include:
  - exact key names and case (Azure metadata keys are case-insensitive and returned lower-cased by some SDKs);
  - whether `delivery_id` is absent or empty for `source=link`;
  - `content_type`, the original filename and `received_at`;
  - which link issued the upload (needed for audit, and to tell "link revoked between upload and quality" apart).
- Each side will pick its own keys.
- Quality stage redelivery after a crash post-INSERT hits a primary-key violation, which becomes an "ordinary failure", then poison, then `PROCESSING_FAILED` on a clean invoice, unless the INSERT is idempotent. Nothing says it must be.

**Pair B: `staff-api` goods-in vs `pipeline/quality`.**
- AD-5 says the supplier comes "from the delivery record returned by `PurchasingPort`" but does not say **who calls it**.
- Story 1 (staff-api goods_in) resolves `delivery_id → supplier_id` at scan time and writes `supplier_id` into metadata.
- Story 2 (quality) sees `source=goods_in`, calls `PurchasingPort.get_delivery(delivery_id)` and sets `supplier_id` itself.
- Both are AD-compliant, there are now two owners of `supplier_id` resolution, and they can disagree.
- `PurchasingPort` in the spine has no `get_delivery` at all, only `get_delivery_dates`.
- Separately, goods-in at staff-api needs PostgreSQL (`sim_purchasing`) while AD-12 stops it at night. Unlike supplier uploads, warehouse scans fail out of hours, and AD-6 does not cover this.
- A staff-api developer may also reasonably create the `intake.invoice` row directly, since staff-api can write `intake`. AD-11 limits that to "admin actions", but goods-in is not one, which is exactly the ambiguity.

**Fix (new AD-6a, "Intake blob contract"):**
- Define `ports/messages.py::IntakeBlobMetadata` (Pydantic), shared by both writers and the quality reader:
  - `invoice_id`
  - `source` (`link` or `goods_in`)
  - `supplier_id` (always present, resolved by the *intake writer*)
  - `delivery_id` (present if and only if `source=goods_in`)
  - `link_key_hash` (link only)
  - `content_type`
  - `received_at` (ISO UTC)
  - `schema_version`
- Keys are lower-case snake_case. Readers go through the one `adapters/blob.py` parser only.
- The **intake writer** (supplier-api or staff-api goods_in) is the sole resolver of `supplier_id`. Quality never calls `PurchasingPort` for identity.
- Add `get_delivery(delivery_id) -> {supplier_id, po_ids, received_at}` to `PurchasingPort`.
- Only `pipeline/quality` inserts `intake.invoice`, using `INSERT … ON CONFLICT (id) DO NOTHING` followed by the conditional transition. It reads the row back on conflict. staff-api never inserts invoices.
- State explicitly that goods-in requires the database (an accepted limitation), or give goods-in its own delivery cache in Table Storage.

## H-4 [High]: The admin queue has no data contract, `PROCESSING_FAILED` enters from states the diagram doesn't allow, and admin actions are undefined for non-validate reasons

**ADs:** AD-2 (poison to q-admin sink with `PROCESSING_FAILED`), AD-3 (diagram; Correct → re-validate; Approve → post), AD-4 (only *validate* is said to write `admin_item`).

**Pair A: `pipeline/q-admin sink` vs AD-3's state machine.**
- A poison message from `q-quality`, `q-extract`, `q-validate` or `q-post` needs `→ in_admin_queue` from `received`, `awaiting_extraction`, `awaiting_validation` or `ready_to_post`.
- The diagram allows none of `awaiting_extraction → in_admin_queue (PROCESSING_FAILED)`, `awaiting_validation → in_admin_queue` (only via validate with reasons) or `received → in_admin_queue (PROCESSING_FAILED)`.
- It also has no owner for them. AD-3 says "only their owner performs them", and the sink is not an owner.
- Worst case: poison from `q-quality` **before the row exists**. The sink has an `invoice_id` but no row to transition, and `admin_item` presumably has an FK. That invoice is invisible.

**Pair B: `pipeline/validate` vs `staff-api` admin queue.**
- AD-4 says validate writes reasons, flagged field ids and bounding regions to `admin_item`. Quality (UNREADABLE), extract (EXTRACTION_QUOTA), post (ACCOUNTS_API_ERROR, with the "API error attached") and the sink are not told to write `admin_item`, or in what shape.
- The staff-api story will query `admin_item` and render "reason, crop, flagged fields" (CAP-9), so any stage that doesn't write it produces an invoice `in_admin_queue` with nothing to show.
- The shape is also undecided: one row per reason, or one row per invoice with a reasons array? Where does the API error payload go? Is there an open/resolved field? That would be a second lifecycle field, contradicting AD-3's "only lifecycle field".

**Pair C: admin Correct/Approve vs the reason that got it there.**
- Correct on `UNREADABLE`, `EXTRACTION_QUOTA` or `PROCESSING_FAILED` from extract sends it to `awaiting_validation` with **no extracted fields**. Validate then runs on empty data and either crashes or re-flags forever.
- Approve on `DUPLICATE` or `BANK_CHANGED` is allowed by the diagram. Approve on `UNREADABLE` posts an invoice with no data.
- Correct and re-validate is also non-deterministic against duplicates. The re-validated invoice may now match a *later* invoice, or its own `image_hash` row (see H-6).

**Fix (tighten AD-3 and AD-4):**
- Add `* (non-terminal) → in_admin_queue` owned by the **q-admin sink** with reason `PROCESSING_FAILED`.
- The sink upserts a minimal `intake.invoice` from blob metadata if the row is missing (the same `ON CONFLICT` rule as H-3).
- Define `intake.admin_item`:
  - `id`
  - `invoice_id`
  - `reason_code` (AD-4 enum)
  - `stage` (quality, extract, validate, post or sink)
  - `field_ids[]`
  - `regions jsonb` (DI `boundingRegions` shape, page-indexed)
  - `detail jsonb` (API error, duplicate-of `invoice_id`, bank fingerprint mismatch flag)
  - `validation_run_id`
  - `created_at`
- There is one row per reason. There is **no** status column: "open" means the invoice is `in_admin_queue` and the row belongs to the latest `validation_run_id` for that invoice.
- Every transition *into* `in_admin_queue` writes its `admin_item` rows **in the same DB transaction** as the status UPDATE, whichever stage performs it.
- Admin actions are gated per reason in `domain/`:
  - Correct is allowed only when extracted fields exist. Otherwise the admin gets **Re-extract** (a new transition `in_admin_queue → awaiting_extraction`, admin-owned).
  - Approve is disallowed while any `UNREADABLE`, `EXTRACTION_QUOTA` or `PROCESSING_FAILED` reason is open.

## H-5 [High]: Analytics has two writers (AD-11 vs AD-13) that race

**ADs:** AD-11 (`analytics` written only by the refresh), AD-13 (the post stage also updates `analytics.*` incrementally), P-10.

**Pair: `analytics refresh` timer vs `pipeline/post`.**
- The refresh story implements a full rebuild (`TRUNCATE`/`INSERT … SELECT`) at 01:30 UTC.
- The post story does `UPDATE analytics.supplier_month SET spend = spend + :x`.
- A post committing during the rebuild is either lost, because it is overwritten by the rebuild's snapshot, or double-counted, because it is added to a table that already includes it.
- A post-stage redelivery (H-2) double-increments.
- The post stage's DB role also needs write access to `analytics`, which AD-11 forbids.

**Fix:**
- Delete the AD-13 bullet. Keep AD-11: the refresh is the **only** writer.
- If near-real-time figures are wanted, the post stage writes nothing new. The refresh is incremental from a watermark over `intake.invoice.posted_at`, and upserts are keyed by `(supplier_id, material_id, period)`.
- A second, event-driven refresh trigger (a `q-analytics` message from post) may call the *same* refresh function, serialised with max instances 1.

## H-6 [Medium–High]: Duplicate detection races with itself and matches itself

**ADs:** AD-9 (quality stores `phash`; validate compares against "any of the same supplier's hashes" and fingerprints of "an earlier invoice"), AD-3.

**Pair: two concurrent `pipeline/validate` runs (two copies of one invoice uploaded a minute apart).**
- There are two failure cases:
  - **Neither is flagged:** both are validating while neither has a fingerprint persisted yet (fingerprint fields come from extraction).
  - **Both are flagged:** both see each other's hash.
- The invoice's **own** `image_hash` row is within distance 0 of itself, so a literal implementation flags every invoice as `DUPLICATE`.
- "Earlier" is undefined: by upload time, `invoice_id` order, or posting order? It also isn't clear whether `rejected` invoices count.

**Fix (tighten AD-9):**
- Compare only against invoices with `id < self.id`. UUIDv7 gives upload order, and self is excluded.
- Exclude `rejected` invoices.
- Persist the fingerprint in extract, not validate, so it exists before any validate runs.
- Validate takes `pg_advisory_xact_lock(hash(supplier_id))` for the duplicate check, which serialises per supplier.
- Record `duplicate_of` in `admin_item.detail`.

## H-7 [Medium]: Dev and Prod share one F0 quota and one rate limit but count them separately

**ADs:** AD-8 (shared DI F0; `intake.di_usage` counts pages; extract max instances 1, at most 1 request a second), AD-12 (separate databases, Dev has no grant on prod).

**Pair: Dev `extract` vs Prod `extract`.**
- Each is max-instances 1, at most 1 request a second, and counting to 500 in *its own* database. Together they send 2 requests a second and up to 1,000 pages to a resource that allows 1 a second and 500 a month.
- DI 429s become "ordinary failures" under AD-2, so they are retried 5 times and then poisoned. Under a Dev test burst, Prod invoices land as `PROCESSING_FAILED`.
- When F0's real monthly cap is hit, DI returns 403 or 429, not the app's own `EXTRACTION_QUOTA`.

**Fix:**
- Split the quota by configuration (for example `DI_MONTHLY_PAGE_BUDGET`: Dev 100, Prod 400) and the rate (Dev 0.3 requests a second, Prod 0.7).
- Classify DI throttling (429, or 403 quota) in the adapter as *transient*, handled with the AD-7 delayed re-enqueue so it doesn't consume dequeue count, and treat the quota response as `EXTRACTION_QUOTA`.
- Alternatively, keep the page counter in the **shared** storage account's Table (resource group `shared`), readable by both environments.

## H-8 [Medium]: supplier-api cannot show reminders, because it never touches PostgreSQL

**ADs:** AD-6 (the upload path touches only Table, Blob and Queue), AD-16 (reminders are also shown on the upload page), AD-13 (reminders computed from PostgreSQL on Mondays).

**Pair: `pipeline` reminder timer vs `supplier-api` upload page.** The timer computes overdue POs in PostgreSQL. The supplier page has no route to read them without breaking AD-6, and a supplier-api developer will add a DB read "just for GETs".

**Fix:** the reminder timer writes `supplierreminders` (Table: `PartitionKey=supplier_id`, `po_ids`, `due_dates`, `generated_at`), and supplier-api reads only that. Extend AD-6's store list explicitly to "reads: `supplierlinks`, `supplierreminders`".

## H-9 [Medium]: Two retry layers on posting, so the poison queue can beat `ACCOUNTS_API_ERROR`

**ADs:** AD-2 (`maxDequeueCount` 5, then poison, then `PROCESSING_FAILED`), AD-10 (5 retries with backoff, then `ACCOUNTS_API_ERROR`).

**Pair: `pipeline/post` vs the `q-admin sink`.**
- If post lets an accounts exception escape, AD-2 retries 5 times and the sink records `PROCESSING_FAILED`, losing the API error that CAP-11 requires.
- If post retries in-process 5 times per dequeue, a long outage gives 25 attempts and function timeouts.

**Fix:**
- `AccountsPort` retries **in-process** with bounded backoff (total under half the function timeout).
- Then post raises the domain error `AccountsApiError`, which the stage catches and turns into the `ready_to_post → in_admin_queue` transition, with the error in `admin_item.detail`.
- Accounts errors never reach AD-2. Define `domain/errors.py` classes as transient (AD-7 path) vs terminal (reason path) vs bug (AD-2 path).

## H-10 [Medium]: Re-validation depends on the image surviving 30 days, and EXIF has no owner

**ADs:** AD-15 (images deleted after 30 days), AD-3 (Correct → full re-validate), conventions ("EXIF read on the server"), AD-7 (7-day message TTL).

**Pair: `pipeline/quality` vs `pipeline/validate`.**
- It is not said which stage reads EXIF `DateTimeOriginal`.
- If validate reads it from the blob, an admin who corrects an invoice more than 30 days old gets a fresh `NO_PHOTO_DATE`, and the CAP-9 crop is gone.
- The AD-7 re-enqueue also *resets* the message TTL each time, so "7 days covers a weekend" is not what bounds a message.

**Fix:**
- Quality extracts EXIF into `intake.invoice.photo_taken_at` (nullable), alongside `phash`. Validate never reads blobs.
- The admin UI shows a "image expired" state.
- Add a max-age check on messages (`enqueued_at` from `invoice.received_at` older than 7 days goes to the sink).

---

## Smaller gaps

- **Link issuance channel.** "Triggered automatically by supplier master events", but master is written only by staff-api and there is no event mechanism or delivery channel. Is the token emailed via AD-16, and by which app? Name the trigger (same-transaction call in the master-update handler) and the channel.
- **Link revoked between upload and quality.** Should quality re-check `supplierlinks.revoked_at`? Decide it and add a reason code, or state explicitly that the upload-time check is final.
- **PDF inputs** (CAP-1 allows PDF). ImageHash and EXIF need a rasterised page 1. Say who renders it (quality) and with what library, which also belongs in the Stack table.
- **`correlation_id` on admin re-entry.** Does a re-validation after Correct reuse the invoice's `correlation_id` or mint a child? This affects the "one trace per `correlation_id`" convention.
- **Timers vs a stopped database.** AD-7 says "exit and run at next slot". If Dj starts the DB after 09:30 SGT on Monday, CAP-13's weekly reminder slips a full week. Use a `job_run` watermark table and run when `last_success` is older than the period.
- **`sim_purchasing` role vs identity.** The "purchasing adapter's own database role" is reached by both staff-api (CAP-19, goods-in) and pipeline. Which managed identity maps to it in each app? State it as one PG role granted to both apps' identities.

## Proposed AD deltas (summary)

| # | Change | Closes |
| --- | --- | --- |
| AD-2a | Resumable hand-off: zero rows with status == `to` means re-enqueue the next stage. Add a stuck-invoice sweeper and `status_changed_at`. | H-1 |
| AD-3 | Claim-before-side-effect transient states with a lease. Persist DI results and `accounts_ref` before transition. Sink-owned `* → in_admin_queue`. Admin Re-extract. Per-reason gating of Correct and Approve. | H-2, H-4 |
| AD-4 | `admin_item` schema (one row per reason, `validation_run_id`, `detail`, no status). Written in the same transaction as every transition into `in_admin_queue`. | H-4 |
| AD-6a | `IntakeBlobMetadata` contract. The intake writer resolves the supplier. Only quality inserts, with `ON CONFLICT`. `PurchasingPort.get_delivery`. `supplierreminders` Table. | H-3, H-8 |
| AD-9 | Compare only against `id < self`, excluding rejected. Fingerprint persisted at extract. Per-supplier advisory lock. | H-6 |
| AD-10 | In-process retries only. `AccountsApiError` is terminal. Idempotency is a port contract. Add schema `sim_accounts`. | H-2, H-9 |
| AD-11 and AD-13 | Remove the post-stage analytics write. The refresh is the single, watermark-incremental writer. | H-5 |
| AD-8 | Per-environment page and rate budgets. DI throttling classified as transient. | H-7 |
| AD-15 and conventions | EXIF and phash captured at quality. Validate never reads blobs. | H-10 |
| `domain/errors.py` | Three error classes (transient, terminal, bug) mapped to AD-7, the reason path and AD-2 respectively. | H-2, H-7, H-9 |
