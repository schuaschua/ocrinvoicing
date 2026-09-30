---
title: 'Fix: an expired staff session shows a generic error instead of the sign-in notice'
type: 'bugfix'
ticket: ''
created: '2026-09-30'
status: 'built'
route: 'oneshot'
route_source: 'auto'
review: 'quick'
review_source: 'auto'
lenses_ran: ['quick']
review_loop_iteration: 0
baseline_revision: '761c4987a383f9d92c8f6d53512a8483ccd3ee0d'
context:
  - '{project-root}/docs/standards/coding-style.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** In Dev, staff-api's built-in auth (redirect to login) answers AJAX calls from an expired or missing session with an empty **403**, not the 401 the design expects (AD-14; README step 8 open question). The staff app raises its "session expired, sign in again" notice only for 401. After the 8-hour sign-in ends, screens would show a generic error instead (Story 2.7; walkthrough-dev-2026-09-30.md follow-up 4).

**Approach:** Treat a 403 with no JSON error body as the expired session it is, in the shared API client and in the goods-in XHR upload. Our own 403s always carry a JSON body (`code: FORBIDDEN`), so they keep meaning "not allowed".

</frozen-after-approval>

## Implementation Notes

Oneshot: the shared `api/client.ts` (copied byte-identically to web/supplier, where no platform 403 occurs because supplier-api is anonymous at the edge), the staff `api/upload.ts`, and assertions in the existing shared `client.test.ts` case.

- Only an **empty** 403 counts: a platform HTML 403 page (site stopped, quota) or our JSON `FORBIDDEN` stays a plain 403. `readErrorBody` now reads the text and reports `empty`. An empty 403 raises `SESSION_EXPIRED` through `sessionExpired()`, which is now exported for XHR callers, so `SESSION_RESTORED` fires after signing in again. The goods-in upload uses it too, with the same empty-body rule. It is rejected as an `ApiError` with status 401, so callers' 401 handling (for example GoodsInScreen `shells()`) applies unchanged.
- A JSON 403 (`FORBIDDEN`) is unchanged.

## Review Triage Log

Quick lens, 8 findings: 2 medium, 6 low, 0 false. All patched.

- Medium: a non-JSON 403, such as a platform HTML page, became "signed out" in both apps; on the supplier page that would show "link isn't working". Narrowed to an empty body only, and the HTML case is asserted.
- Medium: the upload's empty-403 path was untested. A case was added to the existing GoodsInScreen test.
- Low: the upload never set the `expired` flag, so `SESSION_RESTORED` didn't follow. It now calls the exported `sessionExpired()`.
- Low: the client and the upload disagreed on edge bodies. Both now use the empty-text rule.
- Low: `SESSION_EXPIRED`, `SESSION_RESTORED`, `expired`, `apiHeaders` and the `uploadGoodsIn` JSDoc still said "401 only". Updated.
- Low: no Jira key. The PR is titled OCR-30 (Story 2.7), whose criteria are unchanged.
- Note: `ci/checks.sh all` failed twice on the 2.7 App test's 5 s timeout (5.0–5.2 s). Alone it runs in about 500 ms with or without this change. Load average was about 9, with Spotlight at 83% CPU; the third run passed.

## Verification

**Commands:**
- `ci/checks.sh all` -- expected: all checks pass, including the in-step check of the shared files, with at most 200 test cases.

**Manual checks (after the Dev deploy):**
- In a signed-in staff tab, delete the `AppServiceAuthSession` cookie and use the app: the session-expired notice shows, not "Something went wrong".
