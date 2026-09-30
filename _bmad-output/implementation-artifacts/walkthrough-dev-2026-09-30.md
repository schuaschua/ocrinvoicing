# Dev walkthrough, 30 Sep 2026

Dj and Claude walked the built stories through in Dev after the Dev bootstrap: staff sign-in (step 8), the purchasing seed, and the supplier load of three synthetic suppliers.

## Results

| Story | Result | Evidence |
|---|---|---|
| 1.1 | Accepted (earlier today) | Every Jenkins deploy since build #6 plans and applies it |
| 1.3 | Accepted (earlier today) | `/api/health` answers 200 on supplier-api and staff-api |
| 1.7 | Passed | The Alpha link opens Upload home with the supplier's name. A broken link and an unknown link both get the identical "isn't working" message. The link token appears 0 times in 2 h of App Insights. |
| 1.8 | Passed | Upload accepted, reference `R-XMWWGRDQ` |
| 1.9 | Passed | A blurry photo was named as blurry; the retake passed (`device_check=passed`) |
| 2.1 | Passed | `quality.done code=advance` |
| 2.3 | Passed | `extract.done` in about 9 s |
| 2.5 | Passed | Routed with `LOW_CONFIDENCE`, `NO_PHOTO_DATE` |
| 2.6 | Passed | Re-sending the same invoice was flagged Duplicate |
| 2.8 | Passed | The invoice is listed in the admin queue with its reasons |
| 2.9 | Passed | Photo, flag boxes and fields shown; the values match the invoice |
| 2.10 | Passed | Dj rejected the duplicate |
| 3.1 | Passed | `accounts_sim.stored code=CREATED` |
| 3.2 | Passed | `post.done code=posted`, about 2 min after the approval |
| 3.3 | Passed | Approved with a reason and the summary dialog |
| 3.4 | Passed | Found by invoice number; detail and history shown |
| 2.11 | Passed | Dj turned the keyboard shortcuts on and used them in the admin queue |
| 4.1 | Passed | A goods-in scan of a Gamma PDF against PO-45016 delivery 1: "Received" shown; the upload records `source=goods_in` and the delivery; the supplier comes from the delivery; the printed-supplier check agrees. Held for `LOW_CONFIDENCE` and `NO_PHOTO_DATE`, which is expected for a PDF. |

## Decisions made during the walkthrough

- **Confidence threshold 0.98 → 0.90** (Dj). A correctly read phone photo had almost every checked field below 0.98. PR #3 changes P-9, AD-18, SPEC, Stories 2.5 and 2.9, the UX docs and the code; OCR-28 and OCR-32 are updated.
- **Keep the `lng` app name** in resource names for now (Dj).
- **No always-ready instances** (Dj): cold starts stay, and the concurrency fix below covers most of the wait.
- **Photo-date rule unchanged** (Dj, option A). A PDF, a goods-in scan or a photo without a date taken always gets `NO_PHOTO_DATE` and goes to an admin, as AD-19 says. The rejected alternatives were skipping the check for goods-in scans (B), and B plus falling back to the printed invoice date (C).

## Follow-ups to build

1. **Per-instance HTTP concurrency on Flex Consumption.**
   - No trigger concurrency is set, and the Python default on Flex Consumption is 1 request per instance.
   - So every parallel request on a page load (HTML, JS, CSS, `/api/link`) starts its own cold instance, and the page takes 6–10 s.
   - Fix: set `triggers.http.perInstanceConcurrency` (for example 16) for supplier-api and staff-api in `infra/modules/env-app/main.tf`, and record it in the AD-17 compute ceilings.
2. **Invoices: one search box** (Story 3.4). It should match a reference (with or without `R-`), an invoice number or a supplier name, next to the status dropdown. Dj typed every search into the Invoice number box.
3. **Invoices search alignment** (Story 3.4). The reference hint lifted its input above the others.
   - Fixed in the working tree: `InvoicesScreen.tsx`, top-aligned fields.
   - Not committed yet.
4. **Expired staff session answers 403, not 401** (Story 2.7).
   - Built-in auth answers AJAX calls with an empty 403 once the session is gone.
   - The app shows its "session expired" notice only for 401, so users would see a generic error instead.
   - Handle a body-less 403 from the platform as an expired session in `web/staff/src/api/client.ts`.
5. **Azure SDK HTTP logging in App Insights** (staff-api). Every storage call's request and response lines are logged at INFO. The headers are redacted, but this is noise against the 0.5 GB/day cap. Raise `azure.core.pipeline.policies.http_logging_policy` to WARNING.
6. **`NO_PHOTO_DATE` on phone photos** (Story 2.6, AD-19): decided, no change (option A above). Still unknown: whether phone browsers strip the date from photos taken in the page. If they do, every phone upload is held too.
8. **High: the app's custom metrics never reach Application Insights**, so the `poison_message`, `stuck_invoices` and `di_pages_used_pct` alerts (`ar-01`, `ar-02`, `ar-03`) can never fire (Stories 1.5, 2.2, 2.3).
   - Test: at 06:07 UTC a malformed message went on `q-quality`. It failed 5 times (`quality.malformed_message`), and `poison.done code=MALFORMED_MESSAGE queue=q-quality-poison` was logged at 06:07:40.
   - After 20 minutes there was no `poison_message` in `customMetrics`. Its only custom metrics in 3 days are the host's `dotnet.*`.
   - `az monitor metrics list` says `poison_message` isn't a known metric on `appi-01`.
   - Logs from the same identity do arrive.
   - Suspects: the 60 s periodic metric export never runs before a Flex instance is frozen or recycled (try a shorter export interval, or `force_flush` after each invocation); or the metrics path needs a role or setting the logs don't.
9. **Azure's action-group test notification refuses** with "There are no valid receivers in the request". It fails from `test-alerts.sh`, the `az` CLI, the REST API (2021-09-01 to 2024-10-01-preview) and the portal. The receivers are enabled. Email delivery can't be proven until item 8 is fixed and a real alert fires. `alert_email` stays `alerts@example.test` (Dj's address).
7. **Replace the three supplier links** after testing. They were pasted into the chat: run `load_suppliers --replace-link <id>` for each.

## Still to walk through

- 1.4, 1.6, 2.2, 2.4 and 2.7: seen working along the way; confirm and record.
- 1.5: the alert check. Blocked by follow-ups 8 and 9.
- 2.11: keyboard shortcuts.
- 1.2: the branch policy on `main` (OCR-130).
