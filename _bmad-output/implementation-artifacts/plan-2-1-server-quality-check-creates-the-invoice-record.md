---
title: 'Story 2.1: Server quality check creates the invoice record'
type: 'feature'
ticket: '2-1-server-quality-check-creates-the-invoice-record'
created: '2026-09-29'
status: 'built'
baseline_revision: '2d7c6b635c00704f9c3903c721d6748e23b34752'
route: 'full'
route_source: 'auto'
review: 'thorough'
review_source: 'auto'
lenses_ran: ['blind-hunter', 'edge-case-hunter', 'verification-gap', 'intent-alignment']
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-ocrinvoicing-2026-09-28/ARCHITECTURE-SPINE.md'
  - '{project-root}/docs/standards/coding-style.md'
  - '{project-root}/docs/standards/security.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Uploads land in `images/` and on `q-quality`, but nothing records them or checks them, so unreadable or oversized documents would disappear. The pipeline needs its first database schema, the AD-3 state machine, `route_to_admin`, and the `quality` stage.

**Approach:** Add Alembic with the first `intake` migration (tables + AD-11 grants), the framework-free state machine and `route_to_admin` in `domain/`, a PostgreSQL adapter (SQLAlchemy Core + psycopg, Entra token auth), and the `pipeline` app's `quality` queue function: insert the invoice from blob metadata, re-check readability with Pillow using the shared thresholds, store `photo_taken_at` and the phash, then move to `awaiting_extraction` + enqueue `q-extract`, or route `UNREADABLE` / `UNSUPPORTED_DOCUMENT`. Integration tests run against a throwaway PostgreSQL 18 container.

## Boundaries & Constraints

**Always:** AD-3 exactly: one `status` column and the invoice columns listed in AD-3; every transition is one domain function running `UPDATE … WHERE id = :id AND status = :from` plus an `intake.status_history` insert in the same transaction; zero rows changed → read status: if it is the stage's final target re-enqueue the next stage, else just acknowledge (AD-2). Only `quality` inserts `intake.invoice` (`INSERT … ON CONFLICT (id) DO NOTHING`); `route_to_admin` may create the row from `IntakeBlobMetadata` (AD-4, AD-5). Supplier only from metadata. `route_to_admin(invoice_id, reasons, from_status, metadata?)` is the only way into `in_admin_queue`, writes one `intake.admin_item` per reason with one UUIDv7 `routing_id` per call, same transaction. Reason codes only from `domain/reasons.py` (the 12 in AD-4). Readability: EXIF orientation applied, Pillow grey "L", 1024 px long-side copy (`analysis.max_long_side_px`), variance of the Laplacian vs `blur.min_variance`, mean luminance vs `darkness.min_mean_luminance`, from `shared/quality-thresholds.json` packaged with the pipeline app. `photo_taken_at` from EXIF `DateTimeOriginal`, Singapore time unless `OffsetTimeOriginal` (null when absent); 64-bit phash (ImageHash 4.3.2) in `intake.image_hash` for images only. PDFs: > 2 pages → `UNSUPPORTED_DOCUMENT`; unreadable PDF → `UNREADABLE`. Queue messages via the 1.3 sender; next-stage enqueue after commit. SQL only through SQLAlchemy Core with bound parameters; money not involved. Migrations: `backend/migrations/` Alembic reading libpq `PG*` variables (ci/migrate.sh contract), backward-compatible; grants per AD-11 for `intake` (pipeline: read/write; staff-api: read/write; audit/master etc. belong to later stories), role names from Alembic `-x` / env settings, never hard-coded. Logs: ids, codes, timings only.

**Never:** Extraction, validation or posting logic (2.3–2.10). DB-wait / poison / sweeper behaviour (2.2). The `master`, `audit`, `sim_*`, `analytics` schemas. Running migrations at app start. Calling Azure. Real data.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Readable photo | Message for a sharp, bright JPEG | Row inserted `received` → `awaiting_extraction`; 2 history rows; phash + `photo_taken_at` saved; `q-extract` enqueued once | — |
| Readable PDF ≤ 2 pages | 1–2 page PDF | → `awaiting_extraction`, no phash, `photo_taken_at` null | — |
| Unreadable photo | Dark or blurry | `in_admin_queue`, one `admin_item` `UNREADABLE` with a `routing_id`, history row; nothing enqueued | — |
| Overridden, passes | `device_check=overridden`, readable | Processed like any other | — |
| Overridden, fails | `device_check=overridden`, unreadable | `UNREADABLE` | — |
| PDF > 2 pages | 3 pages | `UNSUPPORTED_DOCUMENT` | — |
| Corrupt file | Bytes not decodable | `UNREADABLE` | — |
| EXIF orientation | Rotated JPEG with orientation tag | Measured after rotation; phash on rotated image | — |
| EXIF time | `DateTimeOriginal` without / with `OffsetTimeOriginal` | Stored as UTC from SGT / from the given offset | Malformed → null |
| Redelivery, done | Message again after success | No new row, no duplicate history; status is `awaiting_extraction` → re-enqueue `q-extract`; ack | — |
| Redelivery, routed | Message after routing to admin | Ack only, nothing enqueued | — |
| Concurrent insert | Two deliveries insert at once | One row (`ON CONFLICT DO NOTHING`), one wins the transition | — |
| Missing blob | Message for an `invoice_id` with no blob | Error raised (retried; poison handling is 2.2) | Logged with code only |

</frozen-after-approval>

## Code Map

- `backend/src/invoicing/ports/{messages.py, queue.py, intake.py}` -- `QueueMessage`, `QueueSender`, `QueueName` (`q-quality`, `q-extract`), `IntakeBlobMetadata`, `DeviceCheck` (in `domain/upload.py`).
- `backend/src/invoicing/adapters/{queue.py, blob_images.py, storage_errors.py, logging.py, telemetry.py}` -- reuse; add a blob *read* (bytes + metadata) to the blob adapter/port; `correlation_span` from `QueueMessage.correlation_id` around the handler (1.5 deferral).
- `backend/src/invoicing/apps/pipeline/{function_app.py, settings.py, host.json}` -- pipeline app has no functions yet; `host.json` batchSize 1 etc. from 1.3; add DB settings (host, database, login name) and the queue trigger on `q-quality`.
- `ci/migrate.sh` -- activates once `backend/migrations/env.py` exists; reads `PG*`; runs `uv run --no-dev alembic upgrade head`.
- `ci/code-deploy.sh` -- packages `shared/security-headers.json`; also package `shared/quality-thresholds.json` for the pipeline app.
- `infra/modules/env-app/main.tf` -- pipeline app settings: add DB host/database/user settings if missing (no secrets; Entra token at runtime).
- `shared/quality-thresholds.json` -- server reads `analysis`, `blur`, `darkness` (contract test from 1.9).
- `ARCHITECTURE-SPINE.md` AD-2/3/4/5/6/9/11/19 -- source of columns, codes and rules.

## Tasks & Acceptance

**Execution:**
- [x] `backend/src/invoicing/domain/{reasons.py, status.py, transitions.py, quality.py, exif_time.py}` -- reason catalogue, status enum + allowed transitions + stage final targets, transition/route_to_admin plans (pure), readability measures over pixel data, EXIF time parsing; unit tests.
- [x] `backend/migrations/` (Alembic env reading `PG*`, first `intake` revision with tables, indexes, grants from `-x` role names) + `backend/pyproject.toml` deps (sqlalchemy 2.1.1, psycopg 3.3.6, alembic 1.20.0, Pillow, ImageHash 4.3.2, pypdf) pinned.
- [x] `backend/src/invoicing/ports/invoices.py`, `adapters/postgres/*.py` -- repository (insert-if-absent, conditional transition + history, route_to_admin, image_hash, status read) and engine factory with Entra token.
- [x] `backend/src/invoicing/apps/pipeline/{function_app.py, quality.py, settings.py}` -- `quality` queue trigger; after-commit enqueue; redelivery rule; correlation span.
- [x] `backend/tests/**` -- `test_story_2_1_*` for every matrix row; integration tests against PostgreSQL 18 in Docker (session fixture, skip locally without Docker, fail under `TF_BUILD`); migration up/down test; grants test.
- [x] `ci/code-deploy.sh`, `infra/modules/env-app` -- package thresholds for pipeline; DB settings. Tests.

**Acceptance Criteria:**
- Given `ci/checks.sh all`, when it runs with Docker available, then it exits 0 including the PostgreSQL integration tests.

## Design Notes

Transitions are planned in `domain/` (pure) and executed by the Postgres adapter in one transaction; the domain never imports SQLAlchemy. The quality function returns an outcome (`advance` / `route` / `ack`) and the app enqueues after commit, so a crash between commit and enqueue is recovered by redelivery (and the 2.2 sweeper).

## Verification

**Commands:**
- `ci/checks.sh all` -- expected: exit 0

## Implementation Notes

- Implemented by a coding subagent (2026-09-29). Domain (reasons, status, transitions, quality measures, EXIF time), Alembic `0001_intake` with grants from `-x` roles, SQLAlchemy Core repository with per-connection Entra token, Pillow/ImageHash/pypdf document reader, `quality` queue trigger with after-commit enqueue, PostgreSQL 18 container fixture; `ci/migrate.sh` passes roles; pipeline gets `POSTGRES_*` settings and the thresholds file.

## Plan Change Log

## Review Triage Log

**Pass 1 (2026-09-29): blind-hunter, edge-case-hunter, verification-gap, intent-alignment.** Counts: high 2, medium 14, low 6, false 1, maybe-false 0.

| # | Finding | Verdict | Route | Evidence / action |
|---|---------|---------|-------|-------------------|
| 1 | Both app logins get UPDATE/DELETE on all of `intake` incl. history; default privileges widen later tables (B1) | high | patch | Least privilege: no DELETE; `status_history`, `admin_item`, `image_hash` SELECT+INSERT only; default privileges SELECT, INSERT, UPDATE; test the refusals. |
| 2 | Images between 1× and 2× Pillow's pixel limit only warn and decode in full (B3, E1) | high | patch | Treat `DecompressionBombWarning` as an error / explicit pixel cap; test. |
| 3 | `MemoryError` during decode routes a readable invoice UNREADABLE (E2) | medium | patch | Re-raise for retry. |
| 4 | Transparent PNG measured as black; 16-bit PNG mis-converted (E3, E4) | medium | patch | Composite over white (as the page does); scale 16-bit to 8-bit. Tests. |
| 5 | Host logs the original exception text (psycopg host/user etc.) (B5) | medium | patch | Re-raise a sanitised `StageFailed(code) from None`. |
| 6 | Pure-Python Laplacian loop ~1 s CPU per message (B8) | medium | patch | Vectorise with numpy (already present via ImageHash); equality test vs the reference on fixtures; timing test. |
| 7 | Encrypted / pathological PDFs untested; behaviour unspecified (B9) | medium | patch | Encrypted → UNREADABLE; bounded parse; tests. |
| 8 | Schema-parity test compares names/nullability only (B6) | medium | patch | Compare types and foreign keys too. |
| 9 | supplier-api "no database settings" tests hollow; `POSTGRES_*` in every app's test env (B7) | medium | patch | Per-app settings in tests; delete them for supplier-api. |
| 10 | Routed images' phash/photo time not asserted at stage level (VG1) | medium | patch | EXIF'd dark JPEG → admin queue with hash and time. |
| 11 | `route_to_admin(metadata, from != received)` commits the new row though it returns False (E8) | medium | patch | Roll back. |
| 12 | Empty `AdminRouting.items`; non-JSON detail values (E9, E10) | low | patch | Refuse empty; serialise UUID/Decimal/datetime. |
| 13 | `source`/`delivery_id` mismatch hits a check constraint on every retry (E7) | low | patch | Validate early with a code. |
| 14 | Fractional `max_long_side_px` → 1×1 analysis (E5) | low | patch | Require an integer ≥ 3. |
| 15 | EXIF offset bound asymmetric vs comment (B10, E6) | low | patch | Enforce −12:00…+14:00; tests. |
| 16 | Downgrade relies on DROP SCHEMA for grants; needs `-x` (B11) | low | patch | Revoke explicitly; document. |
| 17 | Permanent failures (bad metadata, missing blob) retried 5× and not routed; `route_to_admin(metadata)` has no caller (B4, intent A3) | medium | defer | Poison trigger routing `PROCESSING_FAILED` with metadata is Story 2.2. |
| 18 | Lease/claim mechanics absent (intent B2, story task line) | medium | defer | No claiming stage exists yet; Story 2.2 AC covers lease reclaim. |
| 19 | Root app stacks' database wiring unasserted (VG2) | low | defer | Needs an app-settings output; with 2.2. |
| 20 | `uploaded_at` not persisted (B2) | low | reject | AD-3 lists the invoice columns exactly; AD-19 uses `photo_taken_at`. |
| 21 | No server byte/pixel size re-check (intent A2) | low | reject | Upload caps bytes at 4 MB; pixel bombs handled by row 2. |
| 22 | No shared device/server fixture (intent D2) | low | reject | Calibration deferral from 1.9 covers it. |
| 23 | Jira/status not in the diff (B12) | false | reject | Handled by the workflow. |
