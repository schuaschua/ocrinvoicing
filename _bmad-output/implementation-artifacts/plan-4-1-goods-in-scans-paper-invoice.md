---
title: 'Story 4.1: Goods-in scans a paper invoice against a delivery'
type: 'feature'
ticket: '4-1-goods-in-scans-a-paper-invoice-against-a-delivery'
created: '2026-09-30'
status: 'done'
route: 'full'
route_source: 'auto'
baseline_revision: '9cfe0f4d34ad3152bad840e66a193f29f6bf0432'
review: 'thorough'
review_source: 'auto'
lenses_ran: ['blind-hunter', 'edge-case-hunter', 'verification-gap', 'intent-alignment']
review_loop_iteration: 0
context:
  - '{project-root}/docs/standards/coding-style.md'
  - '{project-root}/docs/standards/security.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Paper invoices that arrive with a delivery never enter the system; only supplier uploads do.

**Approach:** Give goods-in workers a `/goods-in` screen in `web/staff`: today's deliveries first plus a search by PO number or supplier, a delivery picker, and the same capture and on-device quality check as the supplier page. staff-api gets a delivery list/search API and a goods-in upload that takes the supplier from the chosen delivery (`PurchasingPort.get_delivery`, never from the invoice, AD-5) and follows the AD-6 `Idempotency-Key` order (key, blob if missing, enqueue `q-quality`), so a retry never creates a second invoice.

## Boundaries & Constraints

**Always:** role `goods_in` only (`Surface.GOODS_IN_SCAN`); `platform_auth_trusted` passed explicitly; POST needs `X-Requested-With`; the upload body and limits exactly as the supplier upload (raw body, 4 MB, JPEG/PNG/PDF by content, empty 400, 413, 415, `X-Device-Check` optional); the delivery is looked up first — unknown → 404 `DELIVERY_NOT_FOUND` with nothing written, database stopped → 503 `DB_OFFLINE` with nothing written; blob metadata `source=goods_in`, `delivery_id`, `supplier_id` from the delivery; `UploadKey` also records `source` and `delivery_id`, and a reused key with a different delivery/source/supplier/content → 409; the key → blob → enqueue steps are one shared helper used by both upload endpoints (no behaviour change for supplier uploads); response `{invoice_id, po_number, supplier_name}` → UI "Received for PO {po}, {supplier}."; database stopped on open → "Scanning is unavailable until the system is back (weekdays 9am). Keep the paper invoice with the delivery."; supplier-page layout rules (48px targets, single column); capture and quality modules reused (`@shared/quality`, the supplier app's device-check/capture helpers copied byte-identically and added to `SHARED_FILES`); `shared/quality` tests still run once (supplier app only); no field values in logs.

**Never:** a supplier chosen or typed by the worker; OCR-derived supplier; pipeline changes (the quality and validate stages already handle goods-in); overdue PO list (4.2); more than **3** new test cases.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Open | goods_in user | today's deliveries (Asia/Singapore date) with PO, supplier, delivery no.; search box | — |
| Search | PO number (prefix, any case) or supplier name (contains, any case) | matching deliveries of the last 60 days, newest first, ≤ 50 | query < 2 chars → 400 |
| Send | delivery chosen, photo passes the device check | key claimed, blob with `source=goods_in`, `delivery_id`, delivery's supplier; `q-quality`; "Received for PO {po}, {supplier}." | — |
| Retry | same key, same delivery and bytes | same `invoice_id`, no second blob or invoice | — |
| Key reuse | same key, other delivery or bytes | 409 | nothing written |
| Unknown delivery | id not in purchasing | 404 `DELIVERY_NOT_FOUND` | nothing written |
| DB stopped | on open or on send | the goods-in unavailable message | 503 `DB_OFFLINE`, nothing written |
| Wrong role | admin, finance… | 403 | — |
| Bad file | too big / wrong type / empty | 413 / 415 / 400 | — |

</frozen-after-approval>

## Code Map

- `backend/src/invoicing/apps/supplier_api/upload.py` -- `upload_endpoint`, `upload_key()`, the three-step order; extract the steps into a shared helper (e.g. `backend/src/invoicing/apps/intake_upload.py`) taking `(supplier_id, source, delivery_id)`; supplier behaviour unchanged.
- `backend/src/invoicing/domain/upload.py` -- `check_upload`, `check_declared_length`, `parse_device_check`, `MAX_UPLOAD_BYTES`.
- `backend/src/invoicing/ports/upload_keys.py`, `adapters/table_upload_keys.py` -- `UploadKey` gains `source`, `delivery_id` (old rows read as `link`/None); conflict comparison; `tests/apps/_pipeline_fakes.py` `FakeUploadKeys`.
- `backend/src/invoicing/ports/intake.py` -- `IntakeBlobMetadata(source, delivery_id)`, `IntakeSource.GOODS_IN`.
- `backend/src/invoicing/ports/purchasing.py`, `adapters/purchasing_sim/adapter.py`, `tests/contracts/purchasing_contract.py` -- add `list_deliveries(on: date)` and `search_deliveries(text, since: date)` (PO prefix; supplier match done in staff-api against master names); contract assertions inside the existing contract tests.
- `backend/src/invoicing/adapters/purchasing_factory.py` -- `purchasing_port(name, engine)`; wire in `apps/staff_api/function_app.py` with `settings.purchasing_adapter`, plus `TableUploadKeyStore.with_managed_identity`.
- `backend/src/invoicing/adapters/postgres/suppliers.py` -- `supplier_names`.
- `backend/src/invoicing/apps/staff_api/*` -- route pattern; `Surface.GOODS_IN_SCAN`.
- `web/supplier/src/deviceCheck.ts`, `src/upload.ts`, `src/screens/capture.ts`, `src/api/upload.ts`, `src/screens/CheckAndSend.tsx` -- capture/check/upload pattern to reuse; `ci/tests/test_web_apps_in_step.py` `SHARED_FILES`; `web/staff/vitest.config.ts` comment about shared/quality.
- `web/staff/src/App.tsx` (surface switch, offline handling), `surfaces.ts` (`goods_in_scan` → `/goods-in`), `strings.ts`, `api/client.ts`.
- Tests: `backend/tests/apps/test_supplier_upload.py` (fakes and patched factories), `test_story_3_4_invoice_search.py` (DB + staff principal), `web/supplier/src/screens/*.test.tsx`, `web/staff/e2e/screens.ts`.

## Tasks & Acceptance

**Execution:**
- [x] Shared intake helper; supplier upload uses it.
- [x] `UploadKey` source/delivery; conflict rule.
- [x] Purchasing port list/search + sim adapter + contract assertions.
- [x] staff-api `GET api/goods-in/deliveries?q=` (no `q` → today's), `POST api/goods-in/deliveries/{delivery_id}/upload`; wiring.
- [x] web/staff `GoodsInScreen` (list/search, picker, capture, device check, send with progress, received message, unavailable message), shared helper files, strings.
- [x] Tests (≤ 3 new cases): one backend app test (supplier from the delivery even when the invoice claims another; retry idempotent; key reuse 409; unknown delivery 404; DB stopped 503; roles; file limits; list and search); one Vitest for the screen; one a11y screen for goods-in.

**Acceptance Criteria:**
- Given `ci/checks.sh all`, then it passes with ≤ 200 test cases and the a11y check.

## Implementation Notes

- Shared intake: `backend/src/invoicing/apps/intake_upload.py` (`checked_upload`, `UploadOwner`, `accept_upload`); `supplier_api/upload.py` now only resolves the link and calls it (same order of checks, same logs, same responses).
- `DELIVERY_NOT_FOUND` added to `ErrorCode` (404); a malformed delivery id answers the same 404. `source` and `delivery_id` added to the log-field allow-list (a code and a record id).
- `search_deliveries(text, since)` keeps the plan's signature: staff-api calls it once with the text (PO prefix) and, only when a master name matches, once more with `""` to pick those suppliers' recent deliveries; results are merged, newest first, capped at 50. Supplier names come from a new `SupplierDirectory` port (`PostgresSupplierDirectory`, reusing `supplier_names`).
- The goods-in upload checks the request (key, device check, size, type) before the delivery lookup; both happen before anything is written. The supplier name is read before the key step, so a stopped database writes nothing.
- web/staff: `src/upload.ts`, `src/deviceCheck.ts`, `src/screens/capture.ts` and the test helper `src/test/fakeXhr.ts` copied byte-identically and pinned in `SHARED_FILES`; each app keeps its own `src/api/upload.ts` (staff's exports the same `DeviceCheck` type and the goods-in XHR upload, which raises the shell's 401/`DB_OFFLINE` events itself). On the goods-in route the shell's offline notice uses the goods-in words and heading.
- PO numbers show as "PO 45016" (`poLabel` strips a leading `PO-`), so the received line reads "Received for PO 45012, Synthetic Alpha Building Supplies."
- Tests added: `backend/tests/apps/test_story_4_1_goods_in.py` (1 case), `web/staff/src/screens/GoodsInScreen.test.tsx` (1 case), one a11y screen in `web/staff/e2e/screens.ts` (1 case). Contract and upload-key adapter assertions were added inside existing tests.
- Spine note (reported, not edited): AD-10 lists five `PurchasingPort` methods; this story adds `list_deliveries` and `search_deliveries`.

## Plan Change Log

## Review Triage Log

| # | Lens | Finding | Verdict | Route | Evidence |
|---|------|---------|---------|-------|----------|
| 1 | blind | PO search misses the number the screen shows ("45012", "PO 45012") | medium | patch | `poLabel` shows "PO 45012"; `istartswith` on "PO-45012"; contract pins `found("45012") == []`. |
| 2 | blind, edge | 409 never recoverable: `keyFor` returns the same cached key | low | reject | The key includes the delivery, so the UI can't reuse it across deliveries; same name/size/mtime with other bytes is unlikely; fix adds a branch. |
| 3 | blind, edge, gap | `strings.goodsIn.deliveryGone` unused; 404 drops back to the list silently | medium | patch | grep: only defined in strings.ts; `onDeliveryGone` sets `{kind:"pick"}` with no notice. |
| 4 | blind, edge | Supplier-name search loads 60 days of deliveries and filters in memory | low | reject | Synthetic PoC volume is tens of rows; fix adds a port parameter. |
| 5 | blind | Today's list has no cap | low | reject | A day's deliveries are few; fix adds complexity. |
| 6 | blind | Docstring/frozen say the delivery is looked up first; code checks the file first | low | patch | `goods_in_upload` calls `checked_upload(req)` before `get_delivery`; unknown delivery + bad file gives 413/415/400, not 404. Direct reorder. |
| 7 | blind | No Terraform roles for staff-api's new table/blob writes or PURCHASING_ADAPTER | false | reject | `infra/modules/env-app/main.tf:127-136` grants staff_api Blob Data Contributor on images, Table Data Contributor and Queue Message Sender; setting defaults to `sim`. |
| 8 | blind | Nothing records which worker scanned; `delivery_id` allow-listed but never logged | low / maybe-false | patch (delivery_id) / defer (principal) | `accept_upload` logs no delivery_id. Whether the spine requires recording the scanning worker is unverified. |
| 9 | blind | Test gaps: cross-source key 409, BAD_SOURCE, empty delivery_id, pre-4.1 rows on a fresh claim | low | reject | The conflict tuple is exercised by the other-delivery 409; corrupt rows are written only by this code. |
| 10 | blind, align | Screen test never exercises photo-problem / Take again / Send it anyway / too-many-pages | medium | patch | jsdom always yields `skipped`; `CheckAndSend` is a new, unshared copy. |
| 11 | blind, align | `CheckAndSend` duplicated rather than shared | low | reject | Behaviour matches (R3b); the rules live in the pinned shared helpers; sharing means reshaping the supplier app. |
| 12 | blind | AD-10 stale; Jira sync not recorded | low | defer (AD-10) | Jira was synced this session (OCR-82, OCR-86/87/88 In Progress). AD-10 needs an architecture edit by its owner. |
| 13 | blind, edge | PO supplier reassigned between a failed send and its retry gives 409 | low | reject | Very unlikely mid-retry; the sweeper recovers the partial upload. |
| 14 | edge | XHR follows an Entra redirect on an expired session | low | reject | Built-in auth answers 401 to requests with X-Requested-With (client.ts:58), which the upload sends. |
| 15 | edge | Upload's 401 doesn't set `expired`, so SESSION_RESTORED never fires | false | reject | Only ItemScreen listens for SESSION_RESTORED, and it is never mounted with GoodsInScreen. |
| 16 | edge | Over-64-character search shows the "at least 2 characters" wording | low | reject | Unlikely at a loading dock; fix adds a branch. |
| 17 | edge | Row with inconsistent source/delivery_id accepted | low | reject | Rows are written only by `_entity`, which keeps them consistent. |
| 18 | gap | 503 DB_OFFLINE / 401 on a send untested | medium | patch | Pre-verified: deleting the dispatch branch fails no test. |
| 19 | gap | 60-day window and cap not pinned at staff-api | medium | patch (window) | Pre-verified: all seeded deliveries fall inside the window. |
| 20 | gap | Stale header comment in `ci/tests/test_web_apps_in_step.py` | low | patch | It still lists upload/fakeXhr as supplier-only. |
| 21 | align | "Today's deliveries" is dated-today, not expected-today (EXPERIENCE.md) | false | reject | The frozen intent says "today's deliveries"; the Design Notes record the choice. |
| 22 | align | Invoice-level promises tested only up to blob and queue | false | reject | The pipeline's goods-in branches already exist and are out of scope (frozen Never: pipeline changes). |

## Design Notes

Decisions made unattended (Dj asleep, 2026-09-30):
- **"Today's expected deliveries" = deliveries dated today (Singapore)**: the sim has no expected-delivery rows; late ones are found by search.
- **Two new `PurchasingPort` methods** (list and search) — AD-10 lists five methods, so the spine needs a note (reported, not edited).
- **Upload keys record source and delivery**, so a goods-in retry against another delivery is a conflict, not a silent reuse.
- **Supplier-name search** runs in staff-api against master names (purchasing has no names); PO search in the port.
- **Device-check/capture helpers are copied into web/staff and pinned byte-identical** rather than moved to `shared/`, to avoid reshaping the supplier app.

## Verification

**Commands:**
- `ci/checks.sh all` -- expected: all checks pass, test cases ≤ 200.
