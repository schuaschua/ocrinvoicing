---
title: 'Story 1.8: Supplier sends a photo or PDF and gets a reference'
type: 'feature'
ticket: '1-8-supplier-sends-a-photo-or-pdf-and-gets-a-reference'
created: '2026-09-29'
status: 'built'
baseline_revision: 'cb1b8c7cb0381fd0d9fac1c7e7ca00e39f3193f4'
route: 'full'
route_source: 'auto'
review: 'thorough'
review_source: 'auto'
lenses_ran: ['blind-hunter', 'edge-case-hunter', 'verification-gap', 'intent-alignment']
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-ocrinvoicing-2026-09-28/ARCHITECTURE-SPINE.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-ocrinvoicing-2026-09-28/EXPERIENCE.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** A supplier on Upload home can't send anything yet. They need to pick or photograph an invoice, send the original bytes once (even over a flaky connection), and get a reference — and the server must accept each upload exactly once without PostgreSQL (AD-6).

**Approach:** Add `POST /api/upload` on `supplier-api` following AD-6's three ordered steps (Idempotency-Key → invoice_id in Table `uploadkeys`; original bytes to `images/<invoice_id>` with `IntakeBlobMetadata`; `QueueMessage` on `q-quality`), with blob/table/queue adapters and reference derivation; and the supplier SPA's file pick / camera, Check & send, upload with a per-file idempotency key, Received and failure states. Verify offline with fakes.

## Boundaries & Constraints

**Always:** AD-6 order and replay: a retry with the same key within 24 h returns the same `invoice_id`/reference and replays the blob write (if missing) and the enqueue; never a second invoice. `uploadkeys` stores `supplier_id` with the key; the same key from a different supplier is refused. Server enforces JPEG, PNG or PDF by magic bytes (not the client's Content-Type) and ≤ 4 MB, with a plain message, whatever the client did. Blob = original bytes, never re-encoded; metadata `IntakeBlobMetadata{invoice_id, source=link, supplier_id, content_type, uploaded_at, device_check}` in `ports/intake.py`; `delivery_id` absent. `QueueMessage` from 1.3, plain JSON. Reference `R-` + 8 Crockford/RFC 4648 base32 chars from the random part (`rand_b`) of the UUIDv7 (EXPERIENCE.md, e.g. `R-7Q4KXM2D`), derived in `domain/`. No PostgreSQL; token rules from 1.7 (`current_link`, identical 401). UX per EXPERIENCE.md: Choose file (JPEG/PNG/PDF), Take photo (camera capture input; camera-unavailable message offers Choose file), Check & send with Send, progress `role="status"` announced at start and end, Send disabled while sending, leave-page confirmation mid-upload, "Couldn't send. Check your connection and tap Send again." `role="alert"` with the file kept and the same key reused, Received "Received. Reference R-XXXXXXXX" announced with focus on the reference, **Upload another** → Upload home. Capture buttons ≥ 56px rendered (1.7 deferral).

**Never:** On-device quality checks and Send it anyway (Story 1.9) — until then `device_check` is `passed`. The `quality` stage (2.1). Reminder banner (4.3). PostgreSQL. Logging the token, file names, file bytes or the idempotency key value. Calling Azure.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy path | Valid token, new key, 1 MB JPEG | 200 `{invoice_id, reference}`; key row, blob with metadata, one queue message, in that order | — |
| Retry, all done | Same key again within 24 h | Same `invoice_id`/reference; blob not rewritten; message enqueued again (harmless, AD-2) | — |
| Crash after key | Key row exists, no blob | Retry writes blob and enqueues; same ids | — |
| Crash after blob | Key + blob, no message | Retry skips blob, enqueues | — |
| Crash after enqueue | All three done, response lost | Retry returns same ids, enqueues again | — |
| Concurrent same key | Two requests race on insert | Loser reads the winner's `invoice_id`; one invoice | — |
| Key from another supplier | Key row with a different `supplier_id` | 409 `IDEMPOTENCY_KEY_CONFLICT`, nothing written | — |
| Missing/invalid key | No `Idempotency-Key` or not a UUID | 400 `VALIDATION_FAILED` plain message | — |
| Too large | > 4 MB body | 413 plain message, nothing written | Checked before reading when Content-Length says so, and on actual length |
| Wrong type | GIF, HEIC or bytes not matching JPEG/PNG/PDF | 415 plain message, nothing written | Magic bytes decide |
| Invalid token | As 1.7 | Identical 401, nothing written | — |
| Storage outage | Table/blob/queue error | 503 retryable; client keeps file, same key | — |
| DB stopped | PostgreSQL down | Upload works | — |
| Network failure (client) | Request fails | Alert "Couldn't send…", file kept, Send again reuses the key | — |
| Camera blocked | Camera unavailable / in-app browser | Message offers Choose file | — |
| Leave mid-upload | Navigation/close during send | `beforeunload` confirmation | — |

</frozen-after-approval>

## Code Map

- `backend/src/invoicing/apps/supplier_api/{function_app.py, link.py}` -- `current_link()` resolves the token; add `upload.py` + route `api/upload` (POST) before the SPA catch-all.
- `backend/src/invoicing/ports/{links.py, messages.py, queue.py}` -- key-scheme style (PK first 2 hex chars) to mirror for `uploadkeys`; `QueueMessage`, `QueueSender`, `QueueName`.
- `backend/src/invoicing/adapters/{queue.py, table_links.py, http.py}` -- async managed-identity patterns, error → 503 mapping, `Retry-After`; add blob and upload-key adapters beside them.
- `backend/src/invoicing/domain/{ids.py, errors.py}` -- UUIDv7; add reference derivation and new codes (`IDEMPOTENCY_KEY_CONFLICT` 409, `PAYLOAD_TOO_LARGE` 413, `UNSUPPORTED_MEDIA_TYPE` 415).
- `infra/modules/env-app` -- supplier-api roles: Blob Data Contributor on `images`, Queue Data Message Sender on `q-quality`, Table Data Contributor (AD-17); no change expected.
- `web/supplier/src/{App.tsx, screens/UploadHome.tsx, api/client.ts, strings.ts}` -- Upload home buttons (no behaviour yet); client sends `X-Upload-Token`; add upload call (raw body with the file's type, `Idempotency-Key`, progress via XHR upload events inside `src/api/` only).
- `web/supplier/e2e/screens.ts` -- add Check & send, sending, failed, Received screens; 56px check.

## Tasks & Acceptance

**Execution:**
- [x] `backend/src/invoicing/domain/{reference.py, upload.py}` -- reference from UUIDv7 `rand_b`; file-type sniffing and size rule; tests.
- [x] `backend/src/invoicing/ports/{intake.py, blobs.py, upload_keys.py}` + `adapters/{blob_images.py, table_upload_keys.py}` -- `IntakeBlobMetadata`; create-if-absent blob write; insert-if-absent key with supplier check; tests incl. SDK error mapping and no key/token in logs.
- [x] `backend/src/invoicing/apps/supplier_api/upload.py` + route -- AD-6 steps and replay; tests for every matrix row.
- [x] `web/supplier/src/**` -- pick/capture, Check & send, upload with progress + key per file, Received, failure, camera unavailable, leave confirmation; Vitest; e2e screens and 56px capture check.

**Acceptance Criteria:**
- Given `ci/checks.sh all`, when it runs, then it exits 0 and the supplier bundle stays ≤ 150 KB gzip.

## Design Notes

Upload body is the raw file (`Content-Type` = the file's type), not multipart: no parser, bytes stored exactly as sent. `uploadkeys`: PartitionKey = first 2 hex chars of the key, RowKey = key; fields `invoice_id`, `supplier_id`, `created_at` (the sweeper deletes > 24 h, Story 2.2). A key reused after 24 h (row swept) creates a new invoice — accepted by AD-6.

## Verification

**Commands:**
- `ci/checks.sh all` -- expected: exit 0

## Implementation Notes

- Implemented by a coding subagent (2026-09-29). `azure-storage-blob` 12.30.3; reference = Crockford base32 of the low 40 bits of `rand_b`; magic-byte sniffing; conditional blob write (`If-None-Match: *`); insert-if-absent key row with race handling; shared storage-error mapping; XHR upload with progress and a 180 s timeout; Check & send and Received screens; `uploadkeys` also stores `correlation_id`; capture buttons fixed to render at 56px (tailwind-merge had dropped `min-h-capture`).

## Plan Change Log

## Review Triage Log

**Pass 1 (2026-09-29): blind-hunter, edge-case-hunter, verification-gap, intent-alignment.** Counts: high 1, medium 15, low 8, false 1, maybe-false 0.

| # | Finding | Verdict | Route | Evidence / action |
|---|---------|---------|-------|-------------------|
| 1 | Same key + different bytes returns the earlier invoice and silently drops the new file (B1, E1) | high | patch | Store SHA-256 and sniffed type in the key row; mismatch → 409 `IDEMPOTENCY_KEY_CONFLICT`. |
| 2 | Replay stamps `first_enqueued_at` with the retry time (B3, E3) | medium | patch | Use the key row's `created_at`. |
| 3 | Blob `ResourceExistsError` for other 409s treated as "already stored" (E2) | medium | patch | Only `BlobAlreadyExists` means stored; others → 503 with a code. |
| 4 | Unknown `AzureError`s all labelled TRANSIENT (B4) | medium | patch | Classify by status: 5xx/connection transient (WARNING); other 4xx own code (ERROR); still 503 to the supplier. |
| 5 | Re-choosing the same file after "Couldn't send" makes a new key → possible second invoice (B10) | medium | patch | Key per file identity (name, size, lastModified) for the session. |
| 6 | Received live region mounted with its text (not announced); progress bar inside the live region (B6, B7) | medium | patch | Region present and empty first; only "Sending…" text in the live region. |
| 7 | Camera heuristic can block a working Take photo (B8) | medium | patch | Keep Take photo usable; show the camera hint only after the input can't be used. |
| 8 | Phone photos > 4 MB common; message says "take a photo instead"; camera `accept="image/*"` lets HEIC/WebP through (B9) | medium | patch | Narrow `accept` to JPEG/PNG; fix the message. Product question (limit follows DI F0's 4 MB) raised to Dj. |
| 9 | PDF with leading bytes before `%PDF-` refused (E6) | low | patch | Accept `%PDF-` within the first 1024 bytes. |
| 10 | `image/jpg`/`image/pjpeg`/`image/x-png` refused on the page (E7) | low | patch | Normalise aliases. |
| 11 | Double Send before re-render (E8) | medium | patch | Synchronous in-flight guard. |
| 12 | Empty body shows the generic error (E9) | low | patch | Map to the empty-file reason. |
| 13 | "1024 KB" rounding (E10) | low | patch | Round then switch to MB. |
| 14 | Content-Length check comment implies DoS protection (B5) | low | patch | Correct the wording (the host reads the body). |
| 15 | `uploaded_at` asserted against itself; clock unused in tests (B11) | medium | patch | Fixed clock; assert `uploaded_at` and `first_enqueued_at`. |
| 16 | PDF with empty type labelled "Photo" (B13) | low | patch | Fall back to the extension. |
| 17 | Log event `count=int(written)` cryptic; race loser logged as replay (B14) | low | patch | `blob_written`; log type and size. |
| 18 | 40-bit reference can repeat; misleading mask (B12, E5) | low | patch | Document collision behaviour (staff search shows supplier and date); fix the mask. |
| 19 | Key-claim retry-once path unpinned (VG1) | medium | patch | Test first insert refused + row missing → second insert; count inserts/reads. |
| 20 | Upload route ignoring the caller's correlation id untested (VG2) | medium | patch | Test response, stored row and message ids differ from the header. |
| 21 | Blob written but enqueue failed and the supplier never retries → orphan original (E4) | medium | defer | Story 2.2 sweeper: reconcile `uploadkeys` rows older than 1 h whose blob exists and no invoice row, re-enqueue. |
| 22 | 24 h retry window not enforced until the 2.2 sweeper deletes rows (B2) | low | defer | Sweeper (2.2) deletes rows > 24 h per AD-6; documented. |
| 23 | Storage resources / identity roles not provisioned or tested (intent a) | false | reject | `images`, `q-quality`, `uploadkeys` and supplier-api's roles exist from Stories 1.1/1.3. |
| 24 | No automatic retry or reload survival (intent R3 b/c) | low | reject | Manual same-key retry matches EXPERIENCE.md. |
| 25 | Browser ↔ server contract only by separate tests (intent b) | low | reject | Offline scope; shared constants are tested on both sides. |
