---
title: 'Story 1.9: On-device photo quality check with send anyway'
type: 'feature'
ticket: '1-9-on-device-photo-quality-check-with-send-anyway'
created: '2026-09-29'
status: 'built'
baseline_revision: 'bd172a9836bdcac58c84a627cdf01fcd25fc3d0f'
route: 'full'
route_source: 'auto'
review: 'thorough'
review_source: 'auto'
lenses_ran: ['blind-hunter', 'edge-case-hunter', 'verification-gap', 'intent-alignment']
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-ocrinvoicing-2026-09-28/EXPERIENCE.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-ocrinvoicing-2026-09-28/ARCHITECTURE-SPINE.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Suppliers can send blurry, dark or cut-off photos without being told, so those invoices fail later in the admin queue. They need an on-device check that names the exact problem and lets them retake, with a way to send anyway after two failures, and PDFs over 2 pages refused on the device.

**Approach:** A framework-free quality module in `shared/quality/` (blur by variance of the Laplacian, darkness by mean luminance, edge cut-off by content touching an image side) reading `shared/quality-thresholds.json`; Check & send runs it on the chosen photo, shows the named problem with **Take again**, counts failures, offers **Send it anyway** after 2; a light PDF page count on the device; the upload carries `device_check` (`passed` / `overridden`) and `supplier-api` stores it in `IntakeBlobMetadata`. Verify offline.

## Boundaries & Constraints

**Always:** Checks run on a downscaled copy (e.g. long side ≤ 1024 px) decoded with EXIF orientation applied (`createImageBitmap(file, {imageOrientation: "from-image"})`), finishing in ≈ 2 s or less; the upload still sends the original bytes (never the canvas). Thresholds come only from `shared/quality-thresholds.json` (blur and darkness keys are also read by the server `quality` stage, AD-6); new edge-check keys are added there marked `[ASSUMPTION]`. The pure measuring functions take `{width, height, data}` pixel arrays so they are testable without a browser canvas. Failure copy names the problem and side exactly (e.g. "The bottom edge is cut off"), from `strings.ts`, per EXPERIENCE.md; announced with `role="alert"`; **Take again** reopens the camera/picker. After the 2nd failure on the same upload, **Send it anyway** appears as a secondary action and uploads with `device_check=overridden`, then the normal Received screen. Passing photos and all PDFs upload with `device_check=passed`. PDFs skip photo checks; > 2 pages refused on the device ("more than 2 pages"). The failure counter resets on Upload another or a new upload. `supplier-api` accepts `X-Device-Check: passed|overridden` (default `passed` when absent; any other value → 400), stores it in the blob metadata, and binds it into the idempotency row (a replay with a different device_check keeps the stored value). Bundle stays ≤ 150 KB gzip; CSP unchanged; accessibility floor passes on new states.

**Never:** Re-encoding or resizing the uploaded file. Server-side quality check (Story 2.1). pdf.js or other large libraries. Blocking send for PDFs whose page count can't be read (the server decides). Calling Azure.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Sharp, bright, framed photo | Passing fixture | Check & send ready; upload `device_check=passed` | — |
| Blurry photo | Laplacian variance < `min_variance` | "The photo is blurry" + Take again, `role="alert"` | — |
| Dark photo | Mean luminance < `min_mean_luminance` | "The photo is too dark" + Take again | Darkness checked before blur (a dark photo also looks blurry) |
| Cut-off edge | Content touches a side above the edge threshold | "The bottom edge is cut off" (side named) | Rotated EXIF photo names the side as the user sees it |
| Second failure | 2 failed checks in the same upload | Send it anyway (secondary) + Take again | — |
| Send it anyway | Tap after 2 failures | Upload with `device_check=overridden`; Received screen | — |
| PDF ≤ 2 pages | 1–2 page PDF | No photo checks; upload `passed` | — |
| PDF > 2 pages | 3+ pages | Refused on the device with the pages message | — |
| PDF pages unknown | Page count unreadable | Allowed (server decides) | — |
| Undecodable image | Decode fails | Check skipped; normal send (`passed`), no crash | — |
| Header values | `X-Device-Check` absent / `passed` / `overridden` / other | Stored `passed` / `passed` / `overridden` / 400 `VALIDATION_FAILED` | — |
| Replay | Same key, different `X-Device-Check` | Stored value kept, same ids | — |
| Timing | 12 MP photo on a mid-range phone | Check ≤ ~2 s (downscaled) | Show "Checking photo…" `role="status"` while running |

</frozen-after-approval>

## Code Map

- `shared/quality-thresholds.json` -- blur/darkness keys (read by server 2.1); add edge keys.
- `shared/quality/` -- empty; the module lives here; `@shared` alias exists in both Vite configs (1.4).
- `web/supplier/src/screens/CheckAndSend.tsx`, `App.tsx`, `strings.ts`, `upload.ts` (`isPdf`, `normalisedType`), `api/upload.ts` (XHR; add the header).
- `web/supplier/e2e/screens.ts` -- add check-failure, second-failure and checking states.
- `backend/src/invoicing/apps/supplier_api/upload.py`, `ports/intake.py` (`device_check`), `ports/upload_keys.py` + adapter (bind the value), `domain/upload.py`.
- Supplier bundle budget: `ci/lib.sh` `SUPPLIER_JS_GZIP_MAX_KB`.

## Tasks & Acceptance

**Execution:**
- [x] `shared/quality/{measure.ts, check.ts, pdf.ts}` + tests -- pure measures, threshold evaluation (order: dark, blur, edges), side naming, PDF page count from `/Type /Page` objects; Vitest with generated fixtures (sharp pattern, blurred, dark, content touching each side, passing).
- [x] `web/supplier/src/**` -- decode + downscale with orientation, run the check, failure states, counter, Send it anyway, PDF refusal, header on upload; Vitest; e2e screens.
- [x] `backend/.../upload.py` et al. -- `X-Device-Check` parsing, metadata, idempotency binding; `test_story_1_9_*`.

**Acceptance Criteria:**
- Given `ci/checks.sh all`, when it runs, then it exits 0 and the supplier bundle stays ≤ 150 KB gzip.

## Design Notes

Edge cut-off: in each of the 4 outer strips (a few % of the side), compute the gradient/edge density; a side is "cut off" when its density exceeds `edge.max_border_edge_density` while the interior has content — i.e. the document runs past the frame. Thresholds are uncalibrated `[ASSUMPTION]` values like the others.

## Verification

**Commands:**
- `ci/checks.sh all` -- expected: exit 0

## Implementation Notes

- Implemented by a coding subagent (2026-09-29). `shared/quality/{measure,check,pdf}.ts` (pure measures, dark → blur → edges, busiest side named; PDF page scan), `analysis` and `edge` blocks added to `quality-thresholds.json` as `[ASSUMPTION]`; `deviceCheck.ts` decodes with EXIF orientation, downscales to 1024 px, fails open (passed) on decode error or > 5 s; Check & send states, failure counter per upload, Send it anyway after 2; `X-Device-Check` header stored in metadata and bound to the key row.

## Plan Change Log

## Review Triage Log

**Pass 1 (2026-09-29): blind-hunter, edge-case-hunter, verification-gap, intent-alignment.** Counts: high 2, medium 11, low 9, false 1, maybe-false 0.

| # | Finding | Verdict | Route | Evidence / action |
|---|---------|---------|-------|-------------------|
| 1 | PDF page count can overshoot (orphan/rewritten objects, generation numbers, `endobj` or `/Type /Page` inside streams) and blocks a valid PDF with no override (B1, B2, E1–E3, claim) | high | patch | Use the largest `/Count` of `/Type /Pages` objects, skip stream contents, normalise object numbers; null when unreadable. |
| 2 | `device_check` projection column never verified; a replay could lose "overridden" (VG1) | high | patch | FakeTable honours `select`; assert the column. |
| 3 | Full-size decode before downscale can exhaust memory (B8, E6) | medium | patch | `createImageBitmap` with `resizeWidth/Height`, fallback without. |
| 4 | `imageOrientation` option rejected on older browsers → check silently never runs (E5) | medium | patch | Retry without the option. |
| 5 | Transparent PNG reads as black → "too dark" (E4) | medium | patch | Fill white before drawing. |
| 6 | PDF being checked shows no text and no Send (B9, E7) | medium | patch | "Checking…" status for PDFs. |
| 7 | "Checking photo…" e2e can flip to Send after 5 s (E8, VG other) | medium | patch | Test hook to lengthen the timeout in e2e. |
| 8 | Stored `device_check` empty string → 503 on every retry (E9) | low | patch | Treat empty as legacy `passed`. |
| 9 | No Python test pins the thresholds keys the server will read (B6) | medium | patch | Test loading `analysis`/`blur`/`darkness` keys. |
| 10 | CI doesn't lint `shared/quality/` (implementer) | medium | patch | Add to `ci/checks.sh` lint. |
| 11 | Timing budgets 2 s vs 5 s inconsistent (B10) | low | patch | 2 s target in the thresholds file, 5 s hard cap; test `checkFile` against the cap. |
| 12 | After a failed overridden send, Take again is gone (B11) | low | patch | Keep Take again available. |
| 13 | Replay with a different device check leaves no trace (B13) | low | patch | Log `upload.device_check_mismatch`. |
| 14 | `UploadKey.device_check` defaults to PASSED at the port (B14) | low | patch | Required field; legacy default only in the adapter. |
| 15 | Staff config comment claims staff imports the check; types/header name duplicated; latin1 comment wrong (B15–B17) | low | patch | Fix comment; one exported type and header constant; correct comment. |
| 16 | Busy background (wood grain, keyboard) likely flagged as cut off (B4, intent B) | medium | defer | Uncalibrated heuristic; Send it anyway after 2 tries; calibrate on real photos (Dj). Note added to the thresholds file. |
| 17 | `passed` can't be told from "never checked" (B3, intent E) | medium | defer | A third value changes AD-5's `device_check` enum; raised to Dj. |
| 18 | Spine AD-6/CAP-3 don't mention the edge check, analysis copy or header (B5) | medium | defer | Architecture update for Dj. |
| 19 | Device vs server grey/resample differences near thresholds (E10, B6 part) | low | defer | Calibrate together in Story 2.1. |
| 20 | Timeout can't interrupt synchronous measuring (B7) | low | reject | Bounded by the 1024 px copy. |
| 21 | Invalid header masks an oversize body (B12) | low | reject | Both refuse; order immaterial to the supplier. |
| 22 | Jira/status not in the diff (B18) | false | reject | Handled by the workflow outside the diff. |
| 23 | Tests use synthetic fixtures only (intent G3) | low | reject | Offline scope; real-photo calibration is row 16. |
