---
title: 'Story 2.11: Opt-in keyboard shortcuts for the admin queue'
type: 'feature'
ticket: '2-11-opt-in-keyboard-shortcuts-for-the-admin-queue'
created: '2026-09-30'
status: 'built'
route: 'full'
route_source: 'auto'
baseline_revision: '317c6b55ee8eb23dab129277cc228056617886e5'
review: 'thorough'
review_source: 'auto'
lenses_ran: ['edge-case-hunter', 'verification-gap']
review_loop_iteration: 0
context:
  - '{project-root}/docs/standards/coding-style.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Admins who clear the queue all day must reach for the mouse for every row, dialog and flagged region.

**Approach:** Add an opt-in (off by default) single-key shortcut layer to `web/staff`, stored per browser in `localStorage`, with a settings toggle and a help dialog; shortcuts never fire while typing or while a dialog is open, so screen-reader and keyboard users who don't opt in are unaffected.

## Boundaries & Constraints

**Always:** off by default and off when `localStorage` is unavailable or throws (wrap every read/write); no server-side profile (AD-14); keys ignore modifiers (Ctrl/Alt/Meta) and repeat; never fire when focus is in an input, textarea, select or contenteditable, or while a dialog is open; shortcuts invoke the same handlers as the buttons (no second code path); help dialog and toggle copy in `strings.ts`; the toggle is a real labelled switch/checkbox.

**Never:** Approve's `a` (Story 3.3); any backend change; more than **2** new test cases.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Default | new user / storage empty | shortcuts off; `j`, `k`, `c`… do nothing | — |
| Storage unavailable | `localStorage` throws | treated as off; toggle still works for the session | no error shown |
| Queue | on, on `/queue` | `j`/`k` move the active row (focus + visible ring), `Enter` opens it | at ends: stays |
| Item | on, on an item | `c` opens Correct mode, `r` the Reject dialog (only when those actions are allowed); `n`/`p` step flagged regions | disallowed action: nothing |
| Help | on, `?` | help dialog listing the shortcuts | — |
| Input focus | focus in an input/textarea/select | key does nothing | — |
| Dialog open | any dialog open | shortcut keys do nothing; `Esc` closes the topmost dialog | — |
| Esc, no dialog | on an item, no dialog | returns to the queue | on the queue: nothing |
| Toggle | settings toggle | persists in `localStorage` (`ocr.shortcuts=on`), takes effect at once | — |

</frozen-after-approval>

## Code Map

- `web/staff/src/App.tsx` -- shell (header, notices, session dialog, Toast); mount the shortcut provider, settings toggle and help dialog here.
- `web/staff/src/screens/QueueScreen.tsx` -- rows (supplier link + row click); add active-row index for `j`/`k`/`Enter`.
- `web/staff/src/screens/ItemScreen.tsx`, `components/item/ItemActions.tsx` (Correct/Reject handlers, `allowed_actions`), `components/item/ImageViewer.tsx` (Previous/Next flagged region handlers).
- `web/staff/src/components/Modal.tsx` -- native `<dialog>`; `Esc` already closes it (use the open-dialog state for the guard).
- `web/staff/src/router.ts` -- `navigate()` for Esc → `/queue`.
- `web/staff/src/strings.ts` -- toggle, help dialog copy.
- Tests: `web/staff/src/screens/QueueScreen.test.tsx`, `components/item/ItemActions.test.tsx` (style), `ci/tests/test_web_apps_in_step.py` (staff-only files list).

## Tasks & Acceptance

**Execution:**
- [x] `web/staff/src/shell/shortcuts.ts(x)` -- setting read/write with try/catch, a `useShortcuts` hook registering per-screen key maps, the input/dialog/modifier guards.
- [x] Settings toggle and help dialog in the shell; strings.
- [x] Queue key map (`j`/`k`/`Enter`), item key map (`c`/`r`/`n`/`p`/`Esc`), `?` everywhere.
- [x] Tests (≤ 2 new cases): one Vitest for the guards and default-off/storage-failure (`test_story_2_11` naming in the describe), one for queue and item keys through the real screens.

**Acceptance Criteria:**
- Given `ci/checks.sh all`, then it passes with ≤ 200 test cases and the a11y check.

## Implementation Notes

- `web/staff/src/shell/shortcuts.ts`: the `ocr.shortcuts` setting (every storage read and write in try/catch; a refused write keeps the choice in memory for the session), `useShortcutsEnabled`, `setShortcutsEnabled`, and `useShortcuts(keyMap)`, which each screen calls with the buttons' own handlers. Guards: modifiers (Ctrl/Alt/Meta), repeat, IME composition, focus in input/textarea/select/contenteditable, any open `<dialog>`; `Enter` is also left to a focused link or button so it never double-fires.
- Toggle: `shell/ShortcutsToggle.tsx`, a `<button role="switch" aria-checked>` (a checkbox failed the 48px tap-target check). It sits in the header next to the user name from 640px; below that it moves into the Sheet, because the header must fit 320px (reflow check). Help dialog (`?`) is a `Modal` in `App.tsx`; copy in `strings.shortcuts`.
- Queue: rows get `tabIndex=-1` and `aria-current` for the chosen row; `j`/`k` focus it (global focus ring, inset so the table scroller doesn't clip it), `Enter` calls the same `open()` as a row click.
- Item: `c`/`r` in `ItemActions` only when `allowed_actions` has them; `n`/`p` in `ImageViewer` call the Previous/Next flag `step()` only while those buttons work; `Esc` in `ItemScreen` navigates to `/queue` like the Back link.
- Decision (unattended): `Esc` does nothing in Correct mode, since leaving the item drops the unsaved edits.
- Tests: `web/staff/src/shell/shortcuts.test.tsx`, 2 cases (180 of 200 repo-wide). `ci/tests/test_web_apps_in_step.py` needed no change: `src/shell/` is already staff-only and not in `SHARED_FILES`.

## Plan Change Log

## Review Triage Log

Pass 1 (2026-09-30, unattended). Lenses one at a time: edge-case-hunter, verification-gap. Verdicts: high 0, medium 5, low 2, false 0.

| # | Lens | Finding | Verdict | Route | Evidence |
|---|------|---------|---------|-------|----------|
| E1 | edge | Caps Lock / Shift makes every letter shortcut do nothing | medium | patch | `event.key` is upper-case; lower-case single letters before lookup |
| E2 | edge | Help dialog reopens after shortcuts are turned off in another tab and back on | low | patch | `helpOpen` not reset when the setting goes off |
| V1 | gap | `c`/`r` gating on `allowed_actions` never exercised with a restricted set | medium | patch | fixture always allows both |
| V2 | gap | `n`/`p` guard for PDF and missing-image items untested | medium | patch | only a JPEG fixture |
| V3 | gap | Enter left to a focused link/button unverified | medium | patch | removing it would cancel button activation |
| V4 | gap | Chosen row not reset after a filter/page change unverified | medium | patch | Enter could open a row the admin never chose |
| V5 | gap | Help closed on OFFLINE/SESSION_EXPIRED unverified | low | patch | one assertion |

## Design Notes

Decisions made unattended (Dj asleep, 2026-09-30): the setting key is `ocr.shortcuts`; the toggle lives in the shell header next to the user name; `c`/`r` only act when the action is in `allowed_actions`, so a shortcut never offers more than the buttons.

## Verification

**Commands:**
- `ci/checks.sh all` -- expected: all checks pass, test cases ≤ 200.
