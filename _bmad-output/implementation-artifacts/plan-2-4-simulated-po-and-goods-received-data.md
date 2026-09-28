---
title: 'Story 2.4: Simulated PO and goods-received data'
type: 'feature'
ticket: '2-4-simulated-po-and-goods-received-data'
created: '2026-09-29'
status: 'built'
baseline_revision: '3bab4521d1f09fc300a7961e77bf1e20ed8de3cd'
route: 'full'
route_source: 'auto'
review: 'thorough'
review_source: 'auto'
lenses_ran: ['blind-hunter', 'edge-case-hunter', 'verification-gap', 'intent-alignment']
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-ocrinvoicing-2026-09-28/ARCHITECTURE-SPINE.md'
  - '{project-root}/docs/standards/coding-style.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Validation (2.5), goods-in (4.1), the overdue list (4.2) and analytics need PO, delivery and goods-received data, but the real purchasing system isn't connected. A simulation behind its own port lets that work proceed now and be swapped for the real system later by one setting.

**Approach:** A second Alembic revision creating `sim_purchasing` (materials, POs, PO lines, deliveries, goods receipts) with `SELECT` for the pipeline and staff-api logins; an operator seed command loading synthetic data from a JSON file; `PurchasingPort` with `get_po`, `get_receipts`, `get_delivery`, `list_overdue_pos`, `get_delivery_dates`; the simulation adapter in `adapters/purchasing_sim/` chosen by `PURCHASING_ADAPTER`; an import rule that only that adapter touches `sim_purchasing`; and a reusable port contract test suite run against the simulation on PostgreSQL 18.

## Boundaries & Constraints

**Always:** AD-10 port shape: `get_po(po_number)` → supplier + lines `{po_line_id, material_id, material_name, supplier_product_code, unit_price, quantity, expected_date}` or None; `get_receipts(po_number)` → receipts `{receipt_id, received_date, lines: {po_line_id: quantity}}`; `get_delivery(delivery_id)` → `{delivery_id, supplier_id, po_number, delivery_date}` or None; `list_overdue_pos(as_of)` → POs with an earliest line `expected_date` before `as_of` (the invoiced filter belongs to AD-13's job, not the port); `get_delivery_dates(po_number)` → promised (expected), delivered (delivery_date) and received dates per delivery. Money `Decimal`/`numeric(18,2)`, quantities `numeric(18,3)`, dates `date`. Materials live only in `sim_purchasing` (never `master`). Only `invoicing.adapters.purchasing_sim` may reference `sim_purchasing` or be imported by non-composition code: enforced by an import-linter contract (pinned) and a test that no other source file contains the string `sim_purchasing`. `PURCHASING_ADAPTER` setting (`sim` only valid value today) selects the adapter in a single factory used by apps. Migration is backward-compatible, grants SELECT only (no writes for app logins; the seed runs as the migration/operator role). Seed is synthetic (security.md rule 1), idempotent (upsert by natural keys), and includes: the same material from ≥ 3 suppliers with different prices, a PO delivered in 2 parts, a PO with no receipt, an overdue PO, and a goods-in delivery. Supplier ids in the seed are fixed synthetic UUIDs listed in the JSON (Story 1.6's loader can later map them); no foreign key to `master`.

**Never:** Writes to `sim_purchasing` from app code, validation logic (2.5), analytics, the real purchasing adapter, calling Azure, real data.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Known PO | `get_po("PO-45012")` | Supplier + all lines with Decimal prices, material names | — |
| Unknown PO | `get_po("NOPE")` | None | — |
| Partial delivery | `get_receipts` on the 2-part PO | 2 receipts, quantities per `po_line_id` | — |
| No receipt | `get_receipts` on an unreceived PO | Empty list | — |
| Delivery | `get_delivery(id)` | Supplier, PO, delivery date | Unknown → None |
| Overdue | `list_overdue_pos(as_of)` | Only POs whose earliest expected date < `as_of` | — |
| Delivery dates | `get_delivery_dates(po)` | Promised, delivered, received dates per delivery | — |
| Seed twice | Run seed again | Same row counts (idempotent) | — |
| Grants | pipeline / staff-api login | SELECT works; INSERT/UPDATE/DELETE refused | — |
| Import rule | Another module imports `purchasing_sim` or mentions `sim_purchasing` | lint/test fails | — |
| Adapter choice | `PURCHASING_ADAPTER=sim` / other | Simulation adapter / settings error naming the setting | — |

</frozen-after-approval>

## Code Map

- `backend/migrations/versions/0001_intake.py`, `migrations/env.py` -- revision style, `-x` roles, grants pattern (least privilege from 2.1).
- `backend/src/invoicing/adapters/postgres/{engine.py, invoices.py}` -- engine (`open_connection`, `DatabaseOfflineError`, pool 6), Core usage; the sim adapter reuses the engine.
- `backend/src/invoicing/ports/` -- add `purchasing.py`; `domain/` stays framework-free (value types may live in the port module).
- `backend/src/invoicing/apps/common.py`, `apps/*/settings.py` -- settings pattern; add `PURCHASING_ADAPTER` to pipeline and staff-api settings (default `sim`).
- `backend/tests/conftest.py` -- PostgreSQL 18 container fixture, logins, alembic upgrade.
- `ci/checks.sh` `lint` -- add the import-linter run for the backend.
- `ci/migrate.sh` -- runs `upgrade head` (unchanged).

## Tasks & Acceptance

**Execution:**
- [x] `backend/migrations/versions/0002_sim_purchasing.py` -- tables, keys, indexes, SELECT grants; up/down tests.
- [x] `backend/src/invoicing/ports/purchasing.py` -- port + value types.
- [x] `backend/src/invoicing/adapters/purchasing_sim/{__init__.py, adapter.py, schema.py}` -- Core queries; `DatabaseOfflineError` passthrough.
- [x] `backend/src/invoicing/adapters/purchasing_factory.py` (or in apps/common) -- `PURCHASING_ADAPTER` selection.
- [x] `backend/seed/sim_purchasing.json` + `backend/src/invoicing/tools/seed_purchasing.py` -- idempotent operator seed (connects via `PG*`); README step.
- [x] `backend/pyproject.toml` (import-linter pinned, `[tool.importlinter]` contracts) + `ci/checks.sh` lint step.
- [x] `backend/tests/contracts/purchasing_contract.py` + `test_story_2_4_*` -- reusable contract suite parametrised by adapter factory, run against the simulation on PostgreSQL 18; grants, seed idempotence, import rule tests.

**Acceptance Criteria:**
- Given `ci/checks.sh all`, when it runs with Docker, then it exits 0 including the contract suite and the import-linter check.

## Verification

**Commands:**
- `ci/checks.sh all` -- expected: exit 0

## Implementation Notes

- Implemented by a coding subagent (2026-09-29). Migration `0002_sim_purchasing` (6 tables incl. `goods_receipt_line`; SELECT-only grants), `PurchasingPort` + value types, `adapters/purchasing_sim/` (Core, read-only), `purchasing_factory.py` with `PURCHASING_ADAPTER` (`sim`), idempotent seed (`backend/seed/sim_purchasing.json`, `python -m invoicing.tools.seed_purchasing`), import-linter protected contract in `ci/checks.sh lint`, reusable contract suite run as both app logins. "Promised date" = earliest expected date of the PO lines a delivery received (PO earliest while unreceived).

## Plan Change Log

## Review Triage Log

**Pass 1 (2026-09-29): blind-hunter, edge-case-hunter, verification-gap, intent-alignment.** Counts: high 0, medium 8, low 12, false 1, maybe-false 0.

| # | Finding | Verdict | Route | Evidence / action |
|---|---------|---------|-------|-------------------|
| 1 | Overdue ignores receipts (B1, intent a) | low | patch | Correct per AD-13 (overdue until invoiced); state it in the port docstring. |
| 2 | Port types lack `line_no`, `order_date`, `delivery_no` (B10) | medium | patch | Add while the port is new. |
| 3 | No check that receipt lines belong to the delivery's PO or stay ≤ ordered; dates not ordered (B5, B6, E4, E6) | medium | patch | Seed validation + tests. |
| 4 | Seed never prunes, reports every row as upserted (B8) | low | patch | Warn with counts of DB rows not in the file. |
| 5 | Nothing stops synthetic data going into prod (B9) | medium | patch | `--allow-prod` required for `invoicing_prod`; README note. |
| 6 | README describes a pipeline job that doesn't exist (B12) | low | patch | Reword as an operator step. |
| 7 | Promised date from received lines indistinguishable from the fallback (VG1) | medium | patch | Seed a delivery receiving only a later-due line; assert its promised date. |
| 8 | `PO-45014` assertion vacuous; delivered-not-received only via an ad-hoc insert into the shared DB (B4, B11, E12) | medium | patch | Assert no deliveries; seed a delivered-not-received case in the contract; drop the insert. |
| 9 | Drift test skips unique/check constraints the seed relies on (B7) | medium | patch | Compare them. |
| 10 | `"SIM"` test case lowercased (B3, VG other, E9) | low | patch | Assert `SIM` is refused. |
| 11 | Id reused under another natural key → raw IntegrityError; missing seed file → traceback (E1–E3, E14) | low | patch | Clear errors, exit 2. |
| 12 | PO line order unpinned (VG2) | low | defer | Needs an out-of-order fixture; value arrives with 2.5. |
| 13 | staff-api has the setting but no port (B2, E16, intent b) | low | reject | No staff-api database engine until 2.7+/4.1; setting validated early on purpose. |
| 14 | Default privileges without `FOR ROLE` (E10, E11) | low | reject | Migrations always run as the env deploy identity that owns the schema (AD-11). |
| 15 | `"1"` and `"01"` receipt keys collapse (E5) | low | reject | Synthetic file under our control. |
| 16 | Receipt/PO with no lines handled silently (E7, E8) | low | reject | Seed validation forbids them. |
| 17 | `later_table` in a shared DB (E13) | low | reject | Tests run serially; created in its own schema scope. |
| 18 | Contract fixture builds the adapter directly, not via the factory (E15) | low | reject | Factory has its own test; contract targets the port. |
| 19 | Consumers (2.5, 4.1, 4.2, analytics) not exercised (intent a) | low | reject | They don't exist yet; port shape per AD-10. |
| 20 | Contract data-bound to the synthetic seed (intent d) | low | reject | Real-adapter reuse will need the same fixture data or a data-agnostic subset; noted. |
| 21 | Jira/status not in the diff (B13) | false | reject | Handled by the workflow. |
