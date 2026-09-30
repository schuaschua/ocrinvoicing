---
title: 'Story 3.3: Admin approves exceptions after checking them'
type: 'feature'
ticket: '3-3-admin-approves-exceptions-after-checking-them'
created: '2026-09-30'
status: 'built'
route: 'full'
route_source: 'auto'
baseline_revision: '6cd1bdc18086429a5fbe697a73d5b0691dae9357'
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

**Problem:** An admin can correct, re-extract or reject (2.10) but cannot approve a genuine exception, so invoices with a changed bank account, a false duplicate, a PO tolerance question or an accounts error can never be paid.

**Approach:** Add Approve to the 2.10 action framework: the guard offers it only when every open reason allows it (and alone when `accounts_ref` exists); an admin-only endpoint requires a reason and, for `BANK_CHANGED`, both call-back checks, moves the invoice to `ready_to_post` (resetting the post backoff), enqueues `q-post` and audits it. The item screen gets the Approve dialog with a summary, the bank checklist gate, a side-by-side duplicate comparison and the accounts error display, plus the `a` shortcut.

## Boundaries & Constraints

**Always:** reuse 2.10's transaction shape (invoice row lock, guard re-check, `routing_id` must be the latest, conditional transition `in_admin_queue → ready_to_post`, audit row, enqueue after commit); `post_failures` and `next_attempt_at` reset on that transition (3.2); the guard: Approve if every open reason allows it (`LOW_CONFIDENCE`, `PO_MISMATCH`, `DATE_MISMATCH`, `NO_PHOTO_DATE`, `SUPPLIER_ID_MISMATCH`, `DUPLICATE`, `BANK_CHANGED`, `ACCOUNTS_API_ERROR`), never for `UNREADABLE`, `UNSUPPORTED_DOCUMENT`, `EXTRACTION_QUOTA`, `PROCESSING_FAILED`; with `accounts_ref` only Approve (re-post is idempotent); reason required (1–500 chars, trimmed), stored in the audit detail, never logged; `BANK_CHANGED` requires `checks.called_number_on_file` and `checks.supplier_confirmed` both true on the server, recorded in the audit; the duplicate comparison image is served only while an open `DUPLICATE` reason on a queued invoice names that invoice; admin only, 404 otherwise; no field values in logs.

**Never:** new reasons or guard changes beyond Approve; editing bank values; search (3.4); more than **3** new test cases.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Approve | reasons all allow it, reason text | summary dialog (supplier, amount, reason) → confirm → `ready_to_post`, `post_failures`/`next_attempt_at` reset, `q-post` enqueued, audit `invoice.approved` {admin_oid, reason, checks} | — |
| Missing reason | empty / >500 chars | 400; nothing written | — |
| Bank change | `BANK_CHANGED` open | Approve disabled until both checks ticked, "Tick both checks to approve."; server refuses without both | 400 `CHECKS_REQUIRED` |
| Duplicate | `DUPLICATE` open | matching invoice (received, supplier, total, image) side by side; Approve labelled "Not a duplicate" | matching image gone → placeholder |
| Accounts error | `ACCOUNTS_API_ERROR` open | panel shows the stored status and code; Approve retries posting | — |
| Mixed reasons | one open reason disallows Approve | not offered; server 409 `ACTION_NOT_ALLOWED` | — |
| Already posted | `accounts_ref` set | only Approve offered; re-post returns the same ref | — |
| Race / stale | another admin first or old `routing_id` | 409 "Already handled by another admin." | nothing written |
| Shortcut | shortcuts on, `a` where Approve is offered | opens the Approve dialog; nothing where not offered | — |

</frozen-after-approval>

## Code Map

- `backend/src/invoicing/domain/actions.py` -- the 2.10 guard (`allowed_actions`, `AdminAction`); add `APPROVE` with the rules above.
- `backend/src/invoicing/apps/staff_api/actions.py`, `adapters/postgres/admin_actions.py`, `ports/admin_actions.py` -- the four action endpoints, locked transaction, `routing_id` check, audit, `after_commit` enqueue; add `approve` the same way.
- `backend/src/invoicing/adapters/postgres/invoices.py` -- `transition_in` with the 3.2 reset of `post_failures`/`next_attempt_at` into `ready_to_post`.
- `backend/src/invoicing/adapters/postgres/admin_item.py`, `ports/admin_item.py`, `apps/staff_api/item.py` -- item body (`allowed_actions`, reasons with detail, `routing_id`); add `duplicate_of` (from the `DUPLICATE` reason detail `invoice_id`: received, supplier name, current total, image availability) and a duplicate image route; `ACCOUNTS_API_ERROR` detail `{status, code}` is already in reasons.
- `backend/src/invoicing/domain/validation.py` `check_duplicate` -- detail shape (`invoice_id`, `basis`).
- `web/staff/src/components/item/ItemActions.tsx`, `BankChangePanel.tsx`, `screens/ItemScreen.tsx`, `api/item.ts`, `components/Modal.tsx`, `shell/shortcuts.ts` (`a`), `strings.ts` -- dialogs, checklist, comparison, error panel.
- Tests: `backend/tests/domain/test_story_2_10_actions.py`, `tests/apps/test_story_2_10_admin_actions.py`, `web/staff/src/components/item/ItemActions.test.tsx`, `src/shell/shortcuts.test.tsx`.

## Tasks & Acceptance

**Execution:**
- [x] Guard: `APPROVE`.
- [x] `POST api/admin/items/{id}/approve` `{routing_id, reason, checks?}` with the rules above.
- [x] Item body `duplicate_of`; `GET api/admin/items/{id}/duplicate/image`.
- [x] Web: Approve button/dialog with summary and reason, bank checklist gate, duplicate side-by-side with "Not a duplicate", accounts error panel, `a` shortcut, strings.
- [x] Tests (≤ 3 new cases): guard matrix assertions added to the 2.10 domain test (no new case); one DB app test for approve (each reason kind, checks enforced, audit, reset, enqueue, race, accounts_ref re-post, duplicate image access rules); one Vitest for the dialog, checklist gate, duplicate view, error panel and `a`.

**Acceptance Criteria:**
- Given `ci/checks.sh all`, then it passes with ≤ 200 test cases and the a11y check.

## Implementation Notes

- Guard order is Correct, Approve, Re-extract/Retry intake, Reject (EXPERIENCE.md Admin item); with `accounts_ref` the guard returns `(approve,)` whatever the reasons.
- `CHECKS_REQUIRED` is a new `ErrorCode` (HTTP 400, "Tick both checks to approve.", `ChecksRequiredError`). The adapter checks it through a pre-transition gate inside the locked transaction (after the routing and guard checks), so nothing is written. The audit `checks` is always both booleans.
- `checks` must be an object of only the two keys with boolean values (400 otherwise); a missing key counts as false.
- `item_endpoints` now returns 4 endpoints (adds the duplicate image) and `action_endpoints` returns 5 (adds approve); the 2.9 and 2.10 tests were updated for the unpacking, Approve in `allowed_actions`, and `duplicate_of: null`.
- `duplicate_of` = `{invoice_id, received_at, content_type, supplier_name, invoice_total, currency, image_available}`; the total is the AD-18 current `invoice_total`. The duplicate image route reuses the item image streaming (no-store, `IMAGE_DELETED`).
- Web: `amountText` moved from QueueScreen to `src/lib/format.ts` (with `dateTimeText`, previously local to ItemScreen) so the Approve summary and duplicate comparison share it. The checklist lives in `BankChangePanel` (state in ItemScreen, keyed by invoice id); it shows while Approve is offered, and the panel also shows when `BANK_CHANGED` is open with no bank changes, so Approve can never be stuck. `a` is bound only while Approve is offered and enabled. Reject and Approve keep separate reason drafts. The unused `actions.none` copy was reworded ("No action is available for this invoice."), since an `accounts_ref` now offers Approve.
- The a11y fixture (e2e/screens.ts 2.9 item) now carries Approve, the checklist, a duplicate and an accounts error, so axe and the 48px check cover them; the checkbox inputs are `size-tap-min`.
- New test cases: 2 (backend `test_story_3_3_admin_approves_exceptions`, Vitest "3.3 admin approves exceptions"); `ci/checks.sh all` passed with 186 cases.

## Plan Change Log

## Review Triage Log

Pass 1 (2026-09-30, unattended). Lenses one at a time: edge-case-hunter, verification-gap. Verdicts: high 0, medium 3, low 2, false 1.

| # | Lens | Finding | Verdict | Route | Evidence |
|---|------|---------|---------|-------|----------|
| E1/V-other | both | `DUPLICATE` open but detail missing/malformed or the match gone: no warning, plain "Approve" | low | patch | key the duplicate cue on the open reason; show "matching invoice unavailable" |
| E2 | edge | Several `DUPLICATE` reasons open | false | reject | `route_to_admin` de-duplicates by reason |
| E3 | edge | "Not a duplicate" also approves other open reasons without saying so | medium | patch | label it so only when `DUPLICATE` is the only open reason |
| V1 | gap | AccountsErrorPanel's null-status, missing-code and non-approvable branches untested | medium | patch | the most common real shape (timeout) |
| V2 | gap | Unknown `checks` keys and `checks: null` not exercised | medium | patch | one more body in the existing 400 loop |

## Design Notes

Decisions made unattended (Dj asleep, 2026-09-30):
- **Checklist enforced on the server** (`CHECKS_REQUIRED`), not only in the UI, and recorded in the audit.
- **Duplicate image** has its own route authorised by the open `DUPLICATE` reason, so the item image rule (queued invoices only) stays intact.
- **Accounts error text**: 3.2 stores only `{status, code}`, so that is what shows.

## Verification

**Commands:**
- `ci/checks.sh all` -- expected: all checks pass, test cases ≤ 200.
