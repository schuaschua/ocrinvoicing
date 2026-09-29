---
title: 'Story 2.6: Validation catches duplicates, date mismatches and bank changes'
type: 'feature'
ticket: '2-6-validation-catches-duplicates-date-mismatches-and-bank-chang'
created: '2026-09-30'
status: 'built'
route: 'full'
route_source: 'auto'
baseline_revision: 'cb7fab2bf24f3453570448ce65813c1be8d87770'
review: 'thorough'
review_source: 'auto'
lenses_ran: ['edge-case-hunter', 'verification-gap']
review_loop_iteration: 0
context:
  - '{project-root}/docs/standards/coding-style.md'
  - '{project-root}/docs/standards/security.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The validate stage (2.5) cannot stop a resent or copied invoice, a photo taken long before or after the goods arrived, or changed bank details, so fraud and double payments could reach `ready_to_post`.

**Approach:** Add three checks to the existing validate stage — duplicates (AD-9) under the per-supplier lock, photo date against the PO's latest goods receipt, and bank fingerprints against the master (AD-19) — each adding reasons to the same single routing; after a PO match is committed, delete the supplier's reminder row for that PO (AD-6).

## Boundaries & Constraints

**Always:** reasons join 2.5's list before the one `route_to_admin`; the duplicate read and decision happen inside `finish_locked` under the supplier lock; bank comparison by fingerprint per field id only (never ciphertext, never decrypt, never a value in a log); UUIDv7 `invoice_id` order decides "earlier"; bound parameters; no field values in logs.

**Never:** notify the supplier (FR7); change 2.5's checks; posting, admin screens, or reminder sending (4.3); more than **3** new test cases.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Fingerprint duplicate | earlier non-rejected invoice of the same supplier with the same normalised `invoice_number`, `invoice_total`, `invoice_date` | `DUPLICATE`, detail holds the earlier invoice id | — |
| Phash duplicate | earlier invoice's phash within Hamming distance ≤ 8 | `DUPLICATE` | — |
| Self / later / rejected | only itself, a later-id invoice, or a `rejected` one matches | not flagged | — |
| Concurrent copies | two copies validated at once | exactly one — the later id — is `DUPLICATE` (lock serialises; earlier never looks at later) | — |
| Date in range | photo date (Asia/Singapore) = receipt date, or receipt + 30 days | no reason | — |
| Date out of range | one day before receipt, or receipt + 31 days | `DATE_MISMATCH` | — |
| No photo date | `photo_taken_at` NULL (PDF, scan) | `NO_PHOTO_DATE`; no supplier notification | — |
| No PO / receipt | PO problem already recorded | date check skipped | — |
| Bank same | every extracted bank fingerprint equals the master's for the same bare field id | no reason | — |
| Bank changed / unknown | a fingerprint differs, or the master has no value for that field id | `BANK_CHANGED` with those field ids | — |
| Reminder cleanup | invoice matched to a PO and committed | `supplierreminders` row (PartitionKey=supplier_id, RowKey=po_number) deleted; missing row is fine | delete failure logged with a code, invoice unaffected |

</frozen-after-approval>

## Code Map

- `backend/src/invoicing/apps/pipeline/validate.py` -- `validate()`, `compute` closure (reasons list), `_purchasing()` (`_PurchasingFacts`: add latest receipt date), `ValidateDependencies`, handler enqueue after commit (reminder delete goes beside it).
- `backend/src/invoicing/adapters/postgres/validation.py` -- `load()` (never reads bank columns), `_finish` (`lock_supplier`, `compute(invoiced_elsewhere)`, then `route_in`/`transition_in`, then writes).
- `backend/src/invoicing/ports/validation.py` -- `ComputeResult`/`finish_locked` contract: widen what `compute` receives with the earlier candidates.
- `backend/src/invoicing/domain/validation.py` -- 2.5 checks and normalisers (`normalise_po_number`, `_text`); add the new pure checks here.
- `backend/src/invoicing/domain/current_values.py` -- current-value function (reuse for earlier invoices' fingerprints).
- `backend/src/invoicing/adapters/postgres/schema.py` -- `image_hash(invoice_id, phash bigint)`, `invoice.photo_taken_at`; `adapters/postgres/invoices.py` `unsigned_phash`.
- `backend/src/invoicing/domain/suppliers.py` -- `BANK_FIELD_IDS`; `domain/extraction.py` `is_bank_field_id` (`payment[n].<id>`).
- `backend/src/invoicing/adapters/postgres/suppliers.py` -- `supplier_bank` table (pipeline may read supplier_id, field_id, fingerprint only).
- `backend/src/invoicing/adapters/table_upload_keys.py`, `ports/upload_keys.py` -- Azure Table adapter and table-name constant pattern; `function_app.py` builds table adapters with managed identity.
- `backend/src/invoicing/domain/reasons.py` -- `DUPLICATE`, `DATE_MISMATCH`, `NO_PHOTO_DATE`, `BANK_CHANGED` exist.
- `backend/tests/apps/test_story_2_5_validate.py`, `tests/domain/test_story_2_5_validation_rules.py`, `tests/adapters/test_table_upload_keys_adapter.py` -- style and fixtures.

## Tasks & Acceptance

**Execution:**
- [x] `backend/src/invoicing/domain/validation.py` -- pure `check_duplicate(own, earlier)` (normalised invoice number: uppercase, alphanumerics only; fingerprint needs all three parts; phash Hamming ≤ 8), `check_photo_date(photo_taken_at, latest_receipt)` (Asia/Singapore date, 0..30 days inclusive), `check_bank(extracted, master)` by bare field id.
- [x] `backend/src/invoicing/ports/validation.py` + `adapters/postgres/validation.py` -- inside `_finish`, after the lock: load the same supplier's earlier (`id <` this id), non-rejected invoices' current `invoice_number`/`invoice_total`/`invoice_date` and phash, and pass them to `compute` with `invoiced_elsewhere`; load this invoice's current bank fingerprints and the master's fingerprints (a separate query selecting only fingerprint columns) and its `photo_taken_at` in `load()`.
- [x] `backend/src/invoicing/apps/pipeline/validate.py` -- add the three reasons to the list; latest receipt date in `_PurchasingFacts`; after the commit, when the PO matched, delete the reminder row.
- [x] `backend/src/invoicing/ports/reminders.py` + `adapters/table_reminders.py` + `function_app.py` -- `SUPPLIER_REMINDERS_TABLE = "supplierreminders"`, `ReminderStore.delete(supplier_id, po_number)` (not-found ignored), managed-identity client like the upload-keys adapter.
- [x] Tests (≤ 3 new cases): `tests/domain/test_story_2_6_validation_rules.py` (pure: fingerprint normalisation, phash distance 8/9, self/later/rejected, 0/30/31-day and day-before edges, Singapore date of a UTC timestamp, SWIFT never compared with an account number, bank value missing from master); `tests/apps/test_story_2_6_validate.py` (DB: two copies → later flagged; rejected original + resend not flagged; bank change routed with 2.5's reasons in one routing; reminder delete called for a matched PO; **lock proof**: hold `pg_advisory_xact_lock(hashtextextended(supplier_id::text,0))` on another connection and show the finish waits until it is released — the deferred item from 2.5); reminder adapter assertions inside an existing table-adapter test.

**Acceptance Criteria:**
- Given `ci/checks.sh all`, then it passes with ≤ 200 test cases and backend coverage ≥ 80 %.

## Implementation Notes

- `FieldValue` gained `bank_fingerprint` (repr hidden) so the invoice's current bank fingerprints come through the one AD-18 rule; `load()` reads `bank_fingerprint`, never `bank_ciphertext`. The master's fingerprints are a separate `field_id, fingerprint` query in `load()`.
- `ComputeResult` now takes `(invoiced_elsewhere, earlier)`; `_earlier` reads the lower-id, non-rejected invoices' `invoice_number/invoice_total/invoice_date` current values and phash inside `_finish` after the lock.
- DUPLICATE detail is `{"invoice_id", "basis": "fingerprint"|"phash"}` naming the earliest match; DATE_MISMATCH detail is `{"days": n}`; BANK_CHANGED names the full `payment[n].<id>` field ids, no detail.
- The date check (and NO_PHOTO_DATE) is skipped when there is no receipt (no PO, other supplier's PO, or no receipt).
- "Matched to a PO" = the committed `invoice.po_number` is set (routed or not); the reminder delete runs in `validate()` right after the commit. A PO number with a character Table keys forbid is never sent (no such row can exist).
- Up to six reasons can exceed the 64-char log value limit: then `validate.done` carries `count` and one `validate.reason` event per code.
- 2.5 test: seeding moved to `tests/apps/_validation_seed.py` (photo date, phash, bank fingerprints added); invoice 6 got its own invoice number so it is not a duplicate of invoice 2.
- New cases: 2 (`test_story_2_6_validation_rules`, `test_story_2_6_validate_stage`); reminder adapter assertions sit in `test_story_2_2_delete_is_one_operation_conditional_on_the_listed_etag`.

## Plan Change Log

## Review Triage Log

Pass 1 (2026-09-30, unattended). Lenses one at a time: edge-case-hunter, verification-gap. Verdicts: high 0, medium 5, low 2, false 0.

| # | Lens | Finding | Verdict | Route | Evidence |
|---|------|---------|---------|-------|----------|
| E1 | edge | Earlier copy not yet extracted when the later one validates: no fingerprint to compare | medium | defer | the phash is stored at the quality stage, before extraction, so a resent file is still caught; only a re-photographed copy uploaded while the first is mid-extraction slips through |
| E2 | edge | `invoice_date` as text in another format breaks the fingerprint | low | reject | DI types invoice dates (`valueDate`), mapped to `value_date` |
| E3 | edge | Clearer resend flagged DUPLICATE of an unreadable, still-open original | medium | defer | admin sees both and rejects the original; a UX rule for 2.9/2.10 |
| E4 | edge | Earlier-invoice read unbounded under the lock | medium | defer | fine at PoC volume; needs an indexed fingerprint/phash lookup before real history |
| E5 | edge | Reminder deleted when the PO resolved but amounts mismatch | low | reject | the supplier did invoice that PO; the reminder's purpose (AD-6) is met |
| V1 | gap | Phash duplicate never exercised end to end (adapter signed/unsigned, stage wiring) | medium | patch | only fingerprint matches in the stage test |
| V2 | gap | Per-reason log split over 64 chars untested | medium | patch | reverting it drops all reasons from `validate.done` silently |

## Design Notes

Decisions made unattended (Dj asleep, 2026-09-30):
- **Earlier = lower UUIDv7 id**, read under the supplier lock: the earlier invoice never compares with later ones, so of two concurrent copies only the later is flagged, whatever order they finish in.
- **Earlier candidates** include every non-rejected status (even not yet validated), since a copy uploaded twice must be caught before either posts.
- **Invoice-number normalisation**: uppercase, keep letters and digits only ("INV-001" = "inv 001").
- **Reminder delete after the commit, best effort**: a failure is logged (`code=REMINDER_DELETE_FAILED`) and never fails or retries the invoice; the worst case is one extra weekly reminder.

## Verification

**Commands:**
- `ci/checks.sh all` -- expected: all checks pass, test cases ≤ 200.
