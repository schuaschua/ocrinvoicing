---
title: 'Story 2.10: Admin corrects, re-extracts or rejects'
type: 'feature'
ticket: '2-10-admin-corrects-re-extracts-or-rejects'
created: '2026-09-30'
status: 'built'
route: 'full'
route_source: 'auto'
baseline_revision: '598b2441d06b414b873e12aec3fd03ebd885abb4'
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

**Problem:** An admin can see why an invoice is in the queue (2.9) but cannot resolve it: there is no way to fix a misread field, re-run extraction, retry intake or reject.

**Approach:** Add a domain guard for which actions each invoice's open reasons allow (EXPERIENCE.md "Allowed actions by reason", AD-4 multi-reason rule), four admin-only staff-api action endpoints that apply it and move the invoice with a conditional transition (AD-3), and an action bar with Correct mode, Re-extract, Retry intake and Reject in the item screen.

## Boundaries & Constraints

**Always:** the server applies the same guard the UI uses; open reasons = latest `routing_id`; every action is one transaction with its conditional transition from `in_admin_queue`, its rows and its `audit.event` row (`invoice.corrected|reextracted|intake_retried|rejected`, detail with `admin_oid`, never field values; Reject's reason text ≤ 500 chars is the only free text and is never logged); enqueues and the corrections blob happen after the commit; admin rows are new `source=admin` rows with confidence 1.0 and the latest `run_id`, never updates; a corrected line is a complete row copying every uncorrected column (incl. `unit`, `tax`, `po_line_id`, `material_id`); bank fields are never editable and are refused server-side; non-admin or unknown invoice → 404; another admin first (0 rows) → 409 "Already handled by another admin."; POSTs need `X-Requested-With`.

**Never:** Approve and the bank call-back checklist (Story 3.3); keyboard shortcuts (2.11); storing bank values or revealed values in browser storage; more than **4** new test cases.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Guard | open reasons (+ `accounts_ref`, quality done) | Correct if any reason allows; Re-extract only if every reason allows; Retry intake only for `PROCESSING_FAILED` with quality never completed (replaces Re-extract); Reject unless `accounts_ref`; item response lists allowed actions | action not allowed → 409 `ACTION_NOT_ALLOWED`, nothing written |
| Correct | edited header fields and/or lines, Save and re-check | admin rows (confidence 1.0, latest `run_id`), complete line rows, → `awaiting_validation` in one transaction; then `q-validate`, corrections JSON `corrections/<invoice_id>/<uuid7>.json` (no bank data), Toast "Sent for re-check" | bank field id or unknown field / bad value → 400, nothing written |
| Missing field | LOW_CONFIDENCE on a missing `invoice_date` | admin can add it | — |
| 401 mid-edit | Correct edits unsaved, session expires, admin signs in again | edits restored from `sessionStorage` for that invoice if it is still queued; cleared on save, cancel or leaving | — |
| Returned | corrected invoice routed again | queue row marked "Returned after correction" (admin rows exist on the current run); chips = latest routing only | — |
| Re-extract | `EXTRACTION_QUOTA` / `PROCESSING_FAILED` (quality done) | → `awaiting_extraction`, `q-extract` enqueued | — |
| Retry intake | `PROCESSING_FAILED`, quality never completed | → `received`, `q-quality` enqueued | — |
| Reject | reason entered, confirmed | → `rejected`, reason audited | refused once `accounts_ref` exists (not offered) |
| Unreadable | `UNREADABLE` / `UNSUPPORTED_DOCUMENT` | panel shows supplier phone and "Ask the supplier to send it again."; only Reject | — |
| Race | another admin acted first | 409 → "Already handled by another admin." `role="alert"`, back to the queue | nothing written |
| Next item | any action completes | opens the next queued item (first queue page, excluding this one) with focus on its heading; none → queue | — |

</frozen-after-approval>

## Code Map

- `web`/UX source: `_bmad-output/planning-artifacts/ux-designs/ux-ocrinvoicing-2026-09-28/EXPERIENCE.md` l.134-153 (allowed actions by reason), l.164 (unsaved edits), Toast/alert copy; DESIGN.md (Toast).
- `backend/src/invoicing/domain/reasons.py` -- `ReasonCode`; new `domain/actions.py` with `AdminAction` and `allowed_actions(reasons, accounts_ref, quality_done)`.
- `backend/src/invoicing/domain/status.py`, `transitions.py` -- all five edges from `IN_ADMIN_QUEUE` exist; `plan_transition`.
- `backend/src/invoicing/adapters/postgres/invoices.py` -- `transition_in(connection, plan)` (conditional UPDATE + history, returns False on 0 rows).
- `backend/src/invoicing/adapters/postgres/admin_item.py`, `ports/admin_item.py`, `apps/staff_api/item.py` -- item read (`_queued`, open reasons, `_current`), reveal pattern for POST + audit; phone currently only for `BANK_CHANGED` (widen to `UNREADABLE`, `UNSUPPORTED_DOCUMENT`); add `allowed_actions` to the item body.
- `backend/src/invoicing/domain/current_values.py` -- overlay rule; needs a full-row line read (unit, tax, po_line_id, material_id) for complete corrected lines.
- `backend/src/invoicing/domain/extraction.py` -- `is_bank_field_id`; `domain/validation.py` checked header field constants.
- `backend/src/invoicing/adapters/postgres/suppliers.py` -- `write_audit`.
- `backend/src/invoicing/adapters/queue.py` `StorageQueueSender.with_managed_identity`; `ports/messages.py` `QueueMessage.first` (correlation id from `intake.invoice.correlation_id`); staff-api already has Queue Data Message Sender.
- `backend/src/invoicing/adapters/blob_images.py`, `ports/blobs.py` -- model a `CorrectionsStore` writer (`upload_blob(overwrite=False)`); staff-api already has blob access to `corrections`.
- `backend/src/invoicing/adapters/postgres/admin_queue.py`, `ports/admin_queue.py`, `apps/staff_api/queue.py`, `web/staff/src/api/queue.ts`, `QueueScreen.tsx` -- add `returned_after_correction`.
- `backend/src/invoicing/domain/errors.py` -- add a `ConflictError` (409) for `CONFLICT` / `ACTION_NOT_ALLOWED`.
- `web/staff/src/screens/ItemScreen.tsx`, `components/item/*` (FieldList, LineTable read-only today; stale "Approve belongs to 2.10" comment in `BankChangePanel.tsx` → 3.3), `components/Modal.tsx`, `api/item.ts` (`revealBankValue` POST pattern), `api/client.ts` (`SESSION_EXPIRED`, `apiHeaders`), `App.tsx` (session dialog, add a shell Toast live region), `strings.ts`.
- Tests: `backend/tests/apps/test_story_2_9_admin_item.py` (style), `tests/apps/_pipeline_fakes.py` (`FakeQueue`), `ItemScreen.test.tsx`, `e2e/screens.ts`.

## Tasks & Acceptance

**Execution:**
- [x] `domain/actions.py` -- the guard; used by the item read and every action.
- [x] `ports/admin_actions.py` + `adapters/postgres/admin_actions.py` -- `correct`, `reextract`, `retry_intake`, `reject`: each one transaction (guard re-checked inside, conditional transition first, then rows and audit); returns handled / conflict / not allowed.
- [x] `ports/blobs.py` + `adapters/blob_corrections.py` -- write the correction JSON after the commit (failure logged with a code, never undoes the commit).
- [x] `apps/staff_api/actions.py` + routes `POST api/admin/items/{id}/{correct|reextract|retry-intake|reject}`; staff-api queue sender and corrections store wiring; item body gains `allowed_actions`; phone for unreadable reasons; queue row gains `returned_after_correction`.
- [x] Web: action bar, Correct mode (editable non-bank fields and lines, add missing checked fields, Save and re-check, Cancel), Reject dialog with reason, Re-extract and Retry intake confirms, shell Toast, 409 alert and return to queue, next-item navigation, `sessionStorage` restore after re-sign-in; "Returned after correction" on queue rows; strings.
- [x] Tests (≤ 4 new cases): pure `tests/domain/test_story_2_10_actions.py` (the multi-reason matrix incl. accounts_ref and quality done); DB `tests/apps/test_story_2_10_admin_actions.py` (each action incl. Retry intake, complete line row, no bank edit, corrections blob without bank data, race → 409, not-allowed → 409, non-admin 404, audit rows, enqueues after commit, returned flag); Vitest `ItemActions.test.tsx` (guard-driven buttons, Correct save → Toast, 409 alert, edits restored after 401, Reject dialog); extend an existing a11y screen with the action bar.

**Acceptance Criteria:**
- Given `ci/checks.sh all`, then it passes with ≤ 200 test cases, coverage floors and a11y.

## Implementation Notes

- Guard: `domain/actions.py` (`allowed_actions`, `plan_correction`); item read lists `allowed_actions`; every action re-checks it with the invoice row locked (`SELECT … FOR UPDATE`), then runs the conditional transition first. Unknown invoice → 404; exists but not queued (or 0 rows) → 409 `CONFLICT`; guard refuses → 409 `ACTION_NOT_ALLOWED`.
- Correct's value column: the current row's, else DI's type (`invoice_date`/`due_date` date, amounts number with the invoice currency); page and polygon copied so the box still draws. Flagged fields left filled are sent too (confirmed at 1.0); lines are sent whole.
- After commit: enqueue failures and corrections-blob failures are logged with a code and never undo the commit (sweeper re-enqueues, AD-2).
- `LineValue` gained `unit`, `tax`, `material_id`; `admin_item.current_of` reads full line rows.
- Web: shell notices (`shell/notices.ts`) carry the Toast and the 409 alert to the page the screen navigates to; Correct drafts live in `sessionStorage` (`babaloo.correct.<invoice_id>`), kept across a 401, cleared on save, cancel or leaving.

## Plan Change Log

## Review Triage Log

Pass 1 (2026-09-30, unattended). Lenses one at a time: edge-case-hunter, verification-gap; plus the implementer's own race note. Verdicts: high 0, medium 13, low 3, false 0.

| # | Lens | Finding | Verdict | Route | Evidence |
|---|------|---------|---------|-------|----------|
| R1 | implementer | Stale page: an invoice re-routed while another admin has the old page open; their action applies to the new reasons | medium | patch | send the `routing_id` the admin saw; server answers 409 CONFLICT when it is not the latest |
| E1 | edge | Deeply nested JSON → RecursionError 500 | low | patch | one `except` clause |
| E2 | edge | Unchanged values resent by the client can fail server validation (precision, length) → Correct impossible | medium | patch | send only changed line columns; server completes the row from the current line |
| E3/E9 | edge | UI shows missing flagged fields the server won't accept; UI can't add purchase_order/vendor_tax_id the server accepts | medium | patch | one addable set, from the server (`addable_fields` in the item body) |
| E4 | edge | Restored draft opens Correct mode when Correct is no longer allowed | medium | patch | restore only if `correct` is allowed, else clear |
| E5 | edge | Restored draft posts field ids no longer editable | medium | patch | post only currently editable ids |
| E6 | edge | Draft survives re-sign-in without reload and returns on a later visit | low | patch | reset the expired flag on success; clear on leave |
| E7 | edge | "Already handled" alert reappears on later queue visits | medium | patch | clear alert notices on the next path change |
| E8 | edge | "Returned after correction" after a failed re-extract with no new run | low | reject | Re-extract is only offered for EXTRACTION_QUOTA/PROCESSING_FAILED; the badge then reflects a real earlier correction on the current run |
| V1 | gap | Returned flag with an older-run admin row / line-only correction untested | medium | patch | assertions in the 2.10 app test |
| V2 | gap | Re-extract / Retry intake UI path, dialog and Toast untested | medium | patch | one new Vitest case (cap allows) |
| V3 | gap | Line serialization and flagged-unchanged field untested | medium | patch | extend the first ItemActions test |
| V4 | gap | 409 ACTION_NOT_ALLOWED wording untested | medium | patch | folded into the V2 test |
| V5 | gap | UNSUPPORTED_DOCUMENT phone untested | medium | patch | add the reason to a seeded invoice |
| V6 | gap | Reject never checked to enqueue nothing | medium | patch | one assertion |

## Design Notes

Decisions made unattended (Dj asleep, 2026-09-30):
- **Approve is Story 3.3**, so an invoice with `accounts_ref` shows no action here.
- **"Quality never completed" = no `status_history` row leaving `received` for `awaiting_extraction`** — the story's literal test (no `image_hash` and no `photo_taken_at`) also matches PDFs that passed quality.
- **409 for a lost race or a disallowed action**; 404 stays for non-admins and unknown invoices.
- **Correctable fields**: any current non-bank header field, any missing checked header field, and whole lines (DI `unit`/`tax`/`po_line_id`/`material_id` copied).
- **Unsaved edits** survive the full-page sign-in through `sessionStorage` keyed by invoice (never bank data), restored only if the item is still queued.
- **Correction blob** `corrections/<invoice_id>/<uuid7>.json`: `{invoice_id, run_id, admin_oid, at, fields, lines}`; bank fields cannot appear because they cannot be edited.

## Verification

**Commands:**
- `ci/checks.sh all` -- expected: all checks pass, test cases ≤ 200.
