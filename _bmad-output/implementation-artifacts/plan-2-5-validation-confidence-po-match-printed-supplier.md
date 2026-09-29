---
title: 'Story 2.5: Validation checks confidence, PO match and printed supplier'
type: 'feature'
ticket: '2-5-validation-checks-confidence-po-match-and-printed-supplier'
created: '2026-09-30'
status: 'built'
route: 'full'
route_source: 'auto'
baseline_revision: '3c275d22b4ff1510912e2e9a0b17e7dab0e31e51'
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

**Problem:** Extracted invoices wait in `awaiting_validation`; nothing checks them, so wrong amounts or impersonated suppliers could never be caught and nothing reaches `ready_to_post`.

**Approach:** A `validate` queue stage claims the invoice, reads its current values through one domain function (AD-18), runs the confidence, PO-match and printed-supplier checks (AD-19) collecting every failure, then in one transaction under the per-supplier advisory lock saves the line matches and `po_number` and either routes all reasons at once (AD-4) or moves the invoice to `ready_to_post`.

## Boundaries & Constraints

**Always:** claim-before-side-effect (AD-3); every reason collected before one `route_to_admin` (one `routing_id`, each item with the run's `run_id`); money in `Decimal`; the PO computation and its writes under `pg_advisory_xact_lock` keyed on the supplier (the same key Story 2.6's duplicate check will use, AD-9); supplier identity from `intake.invoice.supplier_id`, never from OCR (P-5); bound parameters only; no field values in logs.

**Never:** duplicate, date or bank checks and reminder cleanup (2.6); posting (Epic 3); admin screens or actions (2.8–2.10); decrypting anything; more than **3** new test cases.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| All pass | confident fields, PO of this supplier, all lines matched, sub_total within tolerance, tax ids equal | `po_line_id`/`material_id` filled, `po_number` saved, → `ready_to_post`, `q-post` enqueued | — |
| Low confidence | a checked field < 0.98 or missing (e.g. `invoice_date`, `line[2].quantity`) | `LOW_CONFIDENCE` with exactly those field ids; bank and unchecked fields ignored; admin rows count 1.0 | — |
| Checked-field scope | goods-in scan without `purchase_order`; upload without `vendor_tax_id` | `purchase_order` checked only for uploads; `vendor_tax_id` only when DI returned it | — |
| Tolerance edge | sub_total − expected = max(1 %, 1.00) exactly / 0.01 beyond | passes / `PO_MISMATCH` with expected and actual in `detail` | — |
| Partial deliveries | second upload against a PO whose earlier invoice (not rejected) already matched part of the received qty | expected = unit price × (received − other invoices' current qty) per matched line | — |
| Goods-in scan | `source=goods_in`, delivery with receipt | PO from the delivery; expected uses qty received on that delivery | — |
| PO problems | missing / unknown PO, another supplier's PO, unmatched line, no receipt | `PO_MISMATCH` | — |
| Supplier by tax id | both tax ids present, differ after normalising | `SUPPLIER_ID_MISMATCH` (name not consulted) | — |
| Supplier by name | no tax id pair; normalised name token-set ≥ 85 / < 85 | pass / `SUPPLIER_ID_MISMATCH` | — |
| Several reasons | low confidence + PO mismatch + supplier mismatch | one routing, three items, one `routing_id`, each with `run_id` | — |
| Lost race | routing or finish changes 0 rows | result discarded, nothing written, message acknowledged | — |
| No run | no extraction run | raise with a code (host retry → poison) | code logged |

</frozen-after-approval>

## Code Map

- `backend/src/invoicing/apps/pipeline/extract.py` -- stage pattern to copy (claim, outcome enum, handler, enqueue after commit, `release_claim` on error, `StageFailed`).
- `backend/src/invoicing/apps/pipeline/function_app.py` -- `purchasing = purchasing_port(...)` already built "for 2.5"; add `validate` trigger via `wait_for_database(QueueName.VALIDATE, ...)`; `validate_poison` exists; update module docstring.
- `backend/src/invoicing/domain/status.py` -- `FINAL_TARGETS[Stage.VALIDATE]`, `CLAIM_STATUS`; unchanged.
- `backend/src/invoicing/domain/sweep.py` -- add `Stage.VALIDATE` to `CONSUMED_QUEUES`.
- `backend/src/invoicing/adapters/postgres/engine.py` -- `POOL_SIZE` 7 → 8 (comment says each stage adds one).
- `backend/src/invoicing/domain/transitions.py` -- `AdminReason(reason, field_ids, detail, run_id)`, `route_to_admin`, `plan_transition`, `plan_claim`.
- `backend/src/invoicing/adapters/postgres/invoices.py` -- `transition_in(connection, plan)` and `_route` pattern for joining a stage write to the transition in one transaction.
- `backend/src/invoicing/domain/extraction.py` -- `CHECKED_LINE_FIELDS`, `line_field_id`, `is_bank_field_id`; add header checked-field constants.
- `backend/src/invoicing/adapters/postgres/schema.py`, `migrations/versions/0005_extraction.py` -- `extraction_run`, `invoice_field`, `invoice_line` (po_line_id, material_id); latest is 0005.
- `backend/src/invoicing/adapters/postgres/extraction.py` -- `lock_di_usage` shows the advisory-lock style.
- `backend/src/invoicing/ports/purchasing.py` -- `PurchasingPort.get_po/get_receipts/get_delivery`, `PurchaseOrder`, `PoLine`, `GoodsReceipt`; `adapters/purchasing_sim/adapter.py` and `schema.py`; `tests/contracts/purchasing_contract.py`.
- `backend/src/invoicing/adapters/postgres/suppliers.py` -- `supplier` table (name, tax_id); pipeline has SELECT on it (0004).
- `backend/tests/apps/test_story_2_3_extract.py`, `tests/conftest.py` (`pipeline_engine`, `reset_intake`, `purchasing_seeded`), `tests/apps/_pipeline_fakes.py` -- test style and fixtures.

## Tasks & Acceptance

**Execution:**
- [x] `backend/src/invoicing/domain/current_values.py` -- the one function giving an invoice's current fields and lines: latest run's rows overlaid by `source=admin` rows with that `run_id`, newest wins per field / line (AD-18). Pure, over rows passed in.
- [x] `backend/src/invoicing/domain/validation.py` -- pure checks returning `AdminReason`s: confidence (header list, `purchase_order` for `link` uploads, `vendor_tax_id` if present, line fields; missing = 0; bank ids never), PO match (line matching by `product_code = supplier_product_code`, expected amount, tolerance max(1 %, 1.00) with amounts quantised to 0.01 `ROUND_HALF_UP`, detail `{expected, actual}` as strings), printed supplier (tax-id normalise; name normalise casefold, strip punctuation and legal suffixes such as "pte ltd", "ltd", "private limited", "sdn bhd", "inc", "llc", "co"; `rapidfuzz.fuzz.token_set_ratio` ≥ 85).
- [x] `backend/src/invoicing/ports/purchasing.py` + sim adapter + contract -- `GoodsReceipt.delivery_id: str | None` so a goods-in scan finds its delivery's receipt.
- [x] `backend/src/invoicing/ports/suppliers.py` + `adapters/postgres/suppliers.py` -- `SupplierReader.get(supplier_id) -> SupplierFacts(name, tax_id)` (pipeline read).
- [x] `backend/src/invoicing/ports/validation.py` + `adapters/postgres/validation.py` -- load current rows and invoice facts (`source`, `supplier_id`, `delivery_id`); `finish_locked(invoice_id, supplier_id, compute)`: one transaction, `pg_advisory_xact_lock(hashtextextended(supplier_id::text, 0))`, reads other non-rejected invoices' current quantities per `po_line_id`, calls `compute`, writes `invoice_line.po_line_id/material_id` on the current rows, `invoice.po_number`, then `transition_in` or the routing; returns False when the transition changed 0 rows (and writes nothing).
- [x] `backend/migrations/versions/0006_validation.py` -- pipeline `UPDATE (po_line_id, material_id) ON intake.invoice_line` (deferred item from 2.3).
- [x] `backend/src/invoicing/apps/pipeline/validate.py` + `function_app.py`, `settings`/`engine.py`, `domain/sweep.py` -- the stage per the matrix.
- [x] `backend/pyproject.toml` / `uv.lock` -- add `rapidfuzz`, exact pin.
- [x] Tests (≤ 3 cases): `backend/tests/domain/test_story_2_5_validation_rules.py` (one pure test: tolerance edges, rounding, name/tax normalisation, checked-field scope, current-value overlay); `backend/tests/apps/test_story_2_5_validate.py` (one DB test with the seeded sim PO: all pass, several reasons in one routing, partial delivery, goods-in, lost race); contract test updated for `delivery_id` without new cases.

**Acceptance Criteria:**
- Given `ci/checks.sh all`, then it passes with ≤ 200 test cases and backend coverage ≥ 80 %.

## Implementation Notes

- **rapidfuzz stays out of the domain.** `tests/test_layering.py` lets `domain` import the standard library only, so `check_printed_supplier` takes the similarity as a parameter; `apps/pipeline/validate.py` passes rapidfuzz's `token_set_ratio` (the default in `ValidateDependencies`).
- **`GoodsReceipt.delivery_id` is `UUID | None`** (default None), not `str | None`: every other delivery id (`Delivery`, `intake.invoice.delivery_id`) is a UUID, and the goods-in match compares them.
- **Line confidence field ids.** `invoice_line` keeps only a line's lowest checked confidence (AD-18), so a line names exactly its missing checked fields (e.g. `line[2].quantity`); a line with none missing but a confidence under 0.98 names all four checked fields.
- **`po_number` is saved only for a PO that exists and is the supplier's**; otherwise NULL, so another supplier's PO never counts as invoiced for the AD-13 overdue job. Line matches are written on every current line (NULL when unmatched).
- **Review fixes (loop 1):** product codes match after normalising (trim, collapse inner whitespace, uppercase) on both sides; a code shared by two PO lines is `AMBIGUOUS_PRODUCT_CODE` and its invoice lines stay unmatched; the printed PO number is trimmed and uppercased before `get_po`; zero current lines is `NO_LINES`; current-value ties on `created_at` go to the later row `id` (UUIDv7), so `FieldValue` now carries `id`.
- **PO_MISMATCH is one item** (AD-4 keeps one item per reason) with `detail {expected, actual, problems[]}`; problem codes: `PO_MISSING`, `PO_UNKNOWN`, `PO_OTHER_SUPPLIER`, `LINE_UNMATCHED`, `NO_RECEIPT`, `SUB_TOTAL_MISSING`, `AMOUNT_OUTSIDE_TOLERANCE`. Expected sums each matched PO line once and never deducts below 0.
- **Printed-supplier detail** holds `basis` (`tax_id` or `name`) and the name `score`, never a value. Legal suffixes are dropped from the end of the name only.
- **`PostgresInvoiceRepository.route_in`** joins a routing to the caller's transaction, like `transition_in`. Admin rows count 1.0 for confidence whatever they store.
- Migration `0006_validation` grants the pipeline `UPDATE (po_line_id, material_id)` on `intake.invoice_line` only.
- Verified: `ci/checks.sh all` passes; 165 of 200 test cases (+2); backend coverage 85.6 %.

## Plan Change Log

## Review Triage Log

Pass 1 (2026-09-30, unattended). Lenses one at a time: edge-case-hunter, verification-gap. Verdicts: high 0, medium 10, low 7, false 2.

| # | Lens | Finding | Verdict | Route | Evidence |
|---|------|---------|---------|-------|----------|
| E1 | edge | Goods-in scans all fail when an adapter leaves `delivery_id` None | low | reject | the purchasing contract now asserts `delivery_id`; any adapter failing it fails CI |
| E2 | edge | Two PO lines with one `supplier_product_code`: the last silently wins | medium | patch | `by_code` dict overwrites; wrong `po_line_id` and expected amount |
| E3 | edge | Product codes compared case- and space-sensitively | medium | patch | OCR output varies in case/spacing; genuine lines become `LINE_UNMATCHED` |
| E4 | edge | Printed PO not normalised before `get_po` | medium | patch | `po-45012` / ` PO-45012 ` → `PO_UNKNOWN` |
| E5 | edge | No lines and sub_total ≤ 1.00 passes everything | medium | patch | expected 0.00, within tolerance, no line checks: reaches `ready_to_post` |
| E6 | edge | Empty `vendor_tax_id` row triggers LOW_CONFIDENCE | low | reject | DI returned the field; a checked field without a value counts as 0 (AD-18) |
| E7 | edge | Missing master row reported as SUPPLIER_ID_MISMATCH | low | reject | supplier_id comes from a link issued for a master supplier; mismatch routing is the safe outcome |
| E8 | edge | Admin correction line without `po_line_id` drops out of other invoices' quantity | medium | defer | admin Correct is Story 2.10; it must copy `po_line_id` (AD-18 "copying every uncorrected column") |
| E9 | edge | Same `created_at` ties make current values order-dependent | low | patch | rows of one transaction share `now()`; tiebreak by UUIDv7 `id` is a direct fix |
| E10 | edge | Stale worker finishes after its lease was reclaimed | false | reject | its result was computed under the supplier lock and the finish is conditional on `validating`; the reclaimer's zero-row finish is discarded (AD-3/AD-2) |
| E11 | edge | Writes happen after the transition, not before as the plan says | false | reject | transition-first is what makes a lost race write nothing; plan wording only |
| E12 | edge | `delivery_id` UUID vs plan's str | low | reject | recorded deviation; every delivery id is a UUID |
| E13 | edge | PO_MISMATCH detail may hold null expected/actual | low | reject | JSON null is valid; 2.9 renders it |
| V1 | gap | VALIDATE in `CONSUMED_QUEUES` unpinned | medium | patch | sweeper tests widen or skip it |
| V2 | gap | Goods-in "own delivery only" filter unobservable | medium | patch | fixture gives the same expected with or without the filter |
| V3 | gap | Re-validation excluding itself unpinned | medium | patch | no test re-validates a matched invoice |
| V4 | gap | `SUB_TOTAL_MISSING` never exercised | medium | patch | without it the stage would raise and go to poison |
| V5 | gap | Lost race on the routing path untested | medium | patch | the race block only exercises `transition_in` |
| V6 | gap | Supplier advisory lock unverified | medium | defer | a deterministic concurrency test fits Story 2.6, which reuses the lock and must prove the duplicate race |
| V7 | gap | Admin line always confident untested | low | patch | one assertion |

## Design Notes

Decisions made unattended (Dj asleep, 2026-09-30):
- **Delivery receipt**: `GoodsReceipt` gains `delivery_id` (the sim table already holds one receipt per delivery) rather than a new port method, so real adapters return it with the receipts they already fetch.
- **Lock key** `hashtextextended(supplier_id::text, 0)`: one 64-bit key per supplier, shared with 2.6.
- **Purchasing reads happen before the transaction** (it is an external system, AD-10); only the intake reads for "other invoices' quantities" and the writes run under the lock.
- **Other invoices' quantities** use the same current-value function, over invoices of the supplier that are not `rejected` and not this invoice.
- **rapidfuzz** is added (named by AD-19); `pip-audit` covers it.

## Verification

**Commands:**
- `ci/checks.sh all` -- expected: all checks pass, test cases ≤ 200.
