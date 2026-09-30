---
name: Babaloo Invoice Intake
status: final
created: 2026-09-28
updated: 2026-09-28
sources:
  - _bmad-output/specs/spec-ocr-invoice-automation/SPEC.md
  - _bmad-output/planning-artifacts/architecture/architecture-ocrinvoicing-2026-09-28/ARCHITECTURE-SPINE.md
  - _bmad-output/brainstorming/brainstorm-ocr-invoice-automation-2026-09-28/brainstorm.html
---

# Babaloo Invoice Intake: Experience Spine

## Foundation

- **Two surfaces.** Each is a React SPA served by its own Function app, from the same origin as its API (AD-14):
  - **Supplier upload page:** mobile web, reached only through the supplier's personal link. There is no login.
  - **Staff app:** responsive web, desktop-first. Staff sign in with Entra, and each role sees only its own surfaces.
- **UI system:** shadcn/ui on Vite + React + Tailwind `[ASSUMPTION]` (also in `DESIGN.md`).
- **References:**
  - `DESIGN.md` is the visual identity reference, and this spine describes the experience.
  - All UI copy lives in one strings module and follows *Voice and Tone* (`coding-style.md` rule 18). The business rules are enforced on the server, and client checks are for convenience only (rule 16).
- **Scope for the PoC:** English only and light mode only. The company name shown to suppliers is **Babaloo**.

## Information Architecture

### Supplier upload page

| Surface | Reached from | Purpose |
| --- | --- | --- |
| Upload home | The personal link `…/u#<token>` (the token sits in the URL fragment, which never reaches the server; AD-6) | Shows who the upload is for, any reminders, and the Take photo / Choose file actions |
| Check & send | After a photo or file is chosen | Device quality check (CAP-3), preview, Send |
| Received | After sending | Confirmation with a reference, and Upload another |
| Link not working | A revoked or unknown link | Tells the supplier to contact the buyer. It reveals nothing else. |

- There is no navigation: it is one linear flow that loops back to Upload home.
- The supplier never sees extracted data, validation results or admin-queue reasons (spec constraints; CAP-7).

### Staff app

| Surface | Roles | Reached from | Purpose |
| --- | --- | --- | --- |
| Admin queue | admin | Sidebar; the admin's landing page | Every invoice waiting for a person, filterable by reason and age (CAP-9) |
| Admin item | admin | Admin queue row | Image, fields and reasons; Correct, Approve, Re-extract or Reject (CAP-8, CAP-9, CAP-10) |
| Goods-in scan | goods_in | The goods_in role's landing page | Pick a delivery, photograph the paper invoice, send (CAP-2) |
| Invoices | admin, finance | Sidebar | Search all invoices with one box for invoice number, supplier name or supplier reference, plus status, with the posting result |
| Overdue POs | admin, procurement, finance | Sidebar | POs past their expected date with no invoice, grouped by supplier, with the date the list was made (CAP-12) |
| Suppliers | procurement, finance, management | Sidebar; procurement's landing page | Supplier list, with a search by supplier name (Flow 5) |
| Supplier scorecard | procurement, finance, management | Suppliers row, or links elsewhere | On-time rate and price trend per material (CAP-17). A Deliveries tab *(could-have, CAP-19)* shows the three dates (PO promised date, delivery date on the invoice, date received) and the gaps between them in days. |
| Price comparison | procurement, finance | Sidebar; a price alert email | For a material, all suppliers' unit prices side by side with each supplier's on-time rate, plus price-rise alerts (CAP-14) |
| Watchlist | procurement, management | Sidebar; management's landing page; a watchlist email | Watchlisted suppliers with their evidence, and ranked alternatives (CAP-15, CAP-16) |
| Finance month | finance, management | Sidebar; finance's landing page | A table per supplier for the month: spend, price-creep alerts, flagged count, duplicate count (CAP-18). The header shows the share of invoices posted without an admin, against the 90% target. |

- **Navigation by role.** The sidebar shows only the surfaces the signed-in role may use; the others are hidden, not disabled. A user with several roles sees the combined set and lands on the landing page of their first role in this order: admin, finance, procurement, management, goods_in.
- **Not a surface: supplier master.** There is no supplier admin screen (Dj's decision). An operator-run script loads suppliers through the application code (AD-11). It prints each new link once for Dj to send to the supplier on WhatsApp or SMS. `--replace-link` revokes a supplier's link and issues a new one, and `--revoke` revokes it without issuing another (AD-6). This departs from P-8, as Dj accepted.
- **Deep links.** Every alert email links straight to its evidence.

### Email entry points

Emails never carry bank details or link tokens (AD-16).

| Trigger | Recipients | Copy (subject) | Link target |
| --- | --- | --- | --- |
| Price rise (CAP-14) | finance, procurement | "Price rise: {supplier}, {material} +{n}%" | Price comparison for that material |
| Watchlist (CAP-15) | procurement, management | "{supplier} added to the watchlist: {rule}" | Watchlist entry |

- **Dialogs** stack one level deep at most.

## Voice and Tone

Microcopy. The aesthetic posture lives in `DESIGN.md`.

| Do | Don't |
| --- | --- |
| Supplier: "Uploading for **Lim Leather Trading**" | "Welcome! Please upload your invoice document below 😊" |
| Supplier: "Photo is too dark. Move to better light and take it again." | "Image quality check failed (luminance < threshold)" |
| Supplier: "Received. Reference R-7Q4KXM2D." | "Your invoice has been successfully submitted and will be processed!" |
| Supplier: "This link isn't working. Please contact your buyer at Babaloo." | "Token revoked" or "Invalid supplier ID" |
| Staff: "Bank details changed: call the supplier on +65 9123 4567 before approving." | "BANK_CHANGED" |
| Staff: "3 invoices waiting" | "You have 3 pending items in your queue!" |
| Staff: "Couldn't reach the accounts system. It will retry, and you'll see it here if it keeps failing." | Stack traces or error codes as the headline |

- **To suppliers:** short, polite, concrete. Never mention checks, fraud, confidence or the admin queue.
- **To staff:** state the fact, then the next action. Codes appear only as secondary text for support.

**Reason labels** (from AD-4; these are the only labels used):

| Code | Label |
| --- | --- |
| `UNREADABLE` | Photo unreadable |
| `UNSUPPORTED_DOCUMENT` | More than 2 pages |
| `EXTRACTION_QUOTA` | Monthly page limit reached |
| `LOW_CONFIDENCE` | Unsure reading |
| `PO_MISMATCH` | Amount doesn't match PO |
| `DUPLICATE` | Possible duplicate |
| `DATE_MISMATCH` | Photo date doesn't match delivery |
| `NO_PHOTO_DATE` | No photo date |
| `BANK_CHANGED` | Bank details changed |
| `SUPPLIER_ID_MISMATCH` | Supplier on invoice doesn't match |
| `ACCOUNTS_API_ERROR` | Couldn't post to accounts |
| `PROCESSING_FAILED` | Processing failed |

## Component Patterns

Behavioral. Visual specs live in `DESIGN.md.Components`.

| Component | Use | Behavioral rules |
| --- | --- | --- |
| Capture button | Upload home, Goods-in | **Take photo** opens the camera. **Choose file** accepts JPEG, PNG or PDF up to 4 MB. The page sends the original file bytes, never a re-encoded canvas, so EXIF data survives (AD-6). If camera permission is denied, or an in-app browser blocks the camera, the page says "Camera not available here. Tap Choose file to pick a photo, or open this link in your phone's browser." |
| Quality check | Check & send | Runs on the device in about 2 s or less: blur, darkness, document cut off at the edge. A failure names the exact problem, for example "The bottom edge is cut off", and offers **Take again** (CAP-3). The failure is announced with `role="alert"`. After 2 failures on the same upload, a secondary option appears: **Send it anyway**. It sends the photo marked as overridden, and the supplier sees the normal Received screen (Dj's decision, for accessibility). The server re-checks it with the same thresholds: it is processed normally if it passes, and goes to the admin queue as Photo unreadable if it fails (AD-6). PDFs skip the photo checks but are refused above 2 pages or 4 MB. |
| Reminder banner | Upload home | Shown when the supplier has overdue POs (CAP-13): "2 deliveries are waiting for an invoice: PO 45012, PO 45019." Read-only. |
| Supplier reference | Received | A short reference shown to the supplier: `R-` followed by 8 base32 characters taken from the random part of `invoice_id` (not the timestamp), for example `R-7Q4KXM2D`. Admins can search by it. |
| Delivery picker | Goods-in | Shows today's expected deliveries first, plus a search by PO number or supplier, so late and overdue deliveries can be picked. |
| Queue table | Admin queue | Columns: received, supplier, amount, reason chips, age. Sorted oldest first. Filters for reason and supplier. The supplier name in each row is a real link that opens the item, so the row works by keyboard and screen reader. Clicking anywhere else on the row also opens the item. |
| Image viewer | Admin item | Opens zoomed to the first flagged region, which is the photo crop of CAP-9. **Previous** and **Next** buttons step between flagged regions, and **Show whole invoice** zooms out. Zoom in, zoom out and pan have buttons, so nothing needs a drag gesture (WCAG 2.5.7). Field flag boxes are drawn from the bounding regions. Each box carries a numbered tag that matches its field in the list. Selecting a field highlights its box, and selecting a box focuses its field. If the image was already deleted by the 30-day retention rule, a placeholder says "Image deleted after 30 days" and the fields still show. Shown to admins only (AD-11). |
| Field list | Admin item | Each field shows its value, a confidence badge when confidence is below 90% (announced as "Confidence 84%"), and its flag state. In Correct mode, fields become editable, and corrected fields are marked "Corrected". Bank fields are never editable: a wrong bank reading is resolved by Approve (after a call-back) or Reject. |
| Admin actions | Admin item | See *Admin actions* below. |
| Bank-change panel | Admin item, reason `BANK_CHANGED` | Shows the supplier's phone number on file and, for each changed bank field, the account on file (masked, or "No account on file" when the master has none for that field) and the new account (masked), with a **Show** control; each use is logged to audit. It has a checklist ("Called the number on file", "Supplier confirmed the new account"), and Approve stays disabled until both boxes are ticked. Text beside the button says why: "Tick both checks to approve." |
| Masked value | Admin item (admin only) | `•••• 4821`, announced as "account ending 4821". **Show** writes an audit entry and reveals the value for at most 30 s, or until the admin taps **Hide** or leaves the item, whichever comes first. At 20 s, an announced warning offers **Keep showing** (+30 s, audited again). The page announces when the value is hidden again. Non-admin roles never see any digits, only "Bank details on file" (AD-11). |
| Evidence list | Watchlist, Price comparison | The invoices, dates and prices behind an alert, each linking to the invoice for admin and finance, and shown as read-only rows for other roles. Non-admin roles never see invoice images, and they never see any bank digits (AD-11). |
| Alternatives list | Watchlist | Other suppliers already invoicing the same material, ranked by price and then on-time rate (CAP-16). |
| Chart | Supplier scorecard, Price comparison, Finance month | Every chart has a one-sentence text summary above it (for example "EVA soles up 6% since March"), a **View as table** toggle, and series told apart by label or marker, not color alone (1.1.1, 1.4.1). |
| Status labels | Invoices, Admin item | Invoice statuses are always shown as labels, never as codes: received, awaiting extraction, extracting → "Processing"; awaiting validation, validating → "Checking" (or "Re-checking" after a correction); ready to post, posting → "Posting"; posted → "Posted"; in admin queue → "In admin queue"; rejected → "Rejected". |

### Admin actions

- **Correct:** edit, then **Save and re-check**. The item leaves the queue with the Toast "Sent for re-check", and the invoice's status reads "Re-checking". If the re-check flags it again, it returns to the queue marked "Returned after correction", with its new reasons.
- **Approve:** a reason is required, and a summary dialog shows the supplier, amount, and reason before the admin confirms (WCAG 3.3.4).
- **Re-extract:** see *Allowed actions by reason*.
- **Reject:** a reason is required, with a confirm dialog.

After an action, the next queue item opens and focus moves to its heading.

#### Allowed actions by reason

| Reason | Allowed actions | Note |
| --- | --- | --- |
| Photo unreadable, More than 2 pages | Reject | The panel shows the supplier's phone number with the prompt "Ask the supplier to send it again." |
| Monthly page limit reached, Processing failed | Re-extract, Reject | For Processing failed before the server quality check completed, **Retry intake** is shown in place of Re-extract; it sends the upload through the quality check again (AD-3). |
| Unsure reading, Amount doesn't match PO, Photo date doesn't match delivery, No photo date, Supplier on invoice doesn't match | Correct, Approve, Reject | |
| Possible duplicate | Approve (not a duplicate), Reject | Shows the matching invoice side by side |
| Bank details changed | Approve (after the call-back checklist), Reject | Bank fields are never editable |
| Couldn't post to accounts | Approve (retry posting), Reject | Shows the accounts system's error message |

When an invoice has several reasons:
- **Correct** is offered if any reason allows it.
- **Approve** is offered only if every reason allows it. For "Bank details changed", the call-back checklist is still required.
- **Re-extract** is offered only if every reason allows it.
- **Reject** is always offered, except once the invoice has reached the accounts system (it has an accounts reference). Then only **Approve** is offered, which re-posts it safely (AD-3).

For example, "Bank details changed" together with "Amount doesn't match PO" means: Correct the amount (bank fields stay locked), re-check, and then Approve after the call-back.

## State Patterns

| State | Surface | Treatment |
| --- | --- | --- |
| App waking up | Both | Skeleton rows. After 3 s, the line "Waking up, one moment…" (the app scales to zero when idle). |
| Upload in progress | Check & send | A progress bar (`role="status"`, announced at the start and the end) and a disabled Send button. Leaving the page while it is in progress asks for confirmation. |
| Upload failed (network) | Check & send | "Couldn't send. Check your connection and tap Send again." (`role="alert"`). The chosen photo is kept. A retry reuses the same upload key, so it never creates a second invoice (architecture AD-6). |
| Photo refused | Check & send | See Quality check. |
| Received | Received | "Received" is announced (`role="status"`), and focus moves to the reference number. |
| Revoked or unknown link | Supplier page | The Link not working surface. It is identical for revoked and unknown links. |
| Database stopped | Supplier page | No change: uploads work 24/7 (AD-6). |
| Session expired | Staff app | When an API call returns 401, a dialog says "Your session ended. Sign in again to continue." Unsaved Correct edits are kept in memory and restored after sign-in. |
| Database stopped | Staff app | Detected when the API returns error code `DB_OFFLINE` (HTTP 503). A full-page notice: "The system is offline outside working hours (weekdays 9am–9pm). Supplier uploads still arrive and will be processed when it's back." (AD-12) |
| Database stopped | Goods-in scan | "Scanning is unavailable until the system is back (weekdays 9am). Keep the paper invoice with the delivery." |
| Empty queue | Admin queue | "Nothing waiting. New exceptions appear here automatically." |
| Page limit near | Admin queue header | At 80% of this environment's Document Intelligence (DI) page cap (Prod 400, Dev 100), an Alert: "322 of 400 pages used this month." |
| Item already resolved | Admin item | When another admin acted first: "Already handled by another admin." (`role="alert"`), and the admin is returned to the queue. |
| No data yet | Analytics surfaces | "No posted invoices yet for this period." |
| Not allowed | Any staff route | Opening a route outside the user's roles redirects them to their landing page, which shows an inline Alert (not a Toast that disappears): "You don't have access to that page." |

## Interaction Primitives

- **Supplier:** tap only. There are no gestures beyond native scroll, and at most one primary action per screen.
- **Staff:** mouse and keyboard.
  - **Single-key shortcuts are off by default** (2.1.4). A setting turns them on; it is kept in this browser (`localStorage`), not on the server (AD-14). `?` opens a help dialog listing them. When they are on: in the admin queue, `j` and `k` move between rows and `Enter` opens an item; in the admin item, `c` corrects, `a` approves, `r` rejects and `n`/`p` step between flagged regions.
  - Shortcuts never fire inside inputs or while a dialog is open. Each one opens the same dialog as its button, so nothing is shortcut-only.
  - `Esc` closes the topmost dialog; with no dialog open, it returns to the queue.
- **Tables:** paginated at 50 rows. No infinite scroll.
- **Banned:**
  - supplier-side editing or confirming of extracted data;
  - any exception message shown to suppliers;
  - drag and drop as the only way to upload;
  - hover-only controls on touch surfaces.

## Accessibility Floor

Behavioral. Visual contrast lives in `DESIGN.md`, which inherits shadcn's AA defaults.

- WCAG 2.2 AA on both surfaces.
- Tap targets are at least 48px, and supplier-page text is at least 16px. The page works at 200% zoom and at the largest mobile text size.
- **Camera and file input** use native controls with visible labels. Quality-check results are announced with `aria-live`.
- **Image viewer:** every flag box has a matching field in the list, so a screen-reader user can review an item without the image.
- **Status and reasons:** color is never the only signal (see `DESIGN.md`).
- **Focus:** the tab order follows reading order, and `Esc` closes the topmost dialog. After an admin action, focus moves to the next item's heading. Focus rings follow `DESIGN.md`, and sticky headers and Toasts never cover the focused element (2.4.11): scroll padding equals the header height.
- **Routes:** each route sets a unique page title ("Admin queue – Babaloo"), and focus moves to the `h1` on navigation.
- **Status messages:** every status the page changes on its own (upload progress, Received, Couldn't send, Already handled, Sent for re-check, the reveal warning) uses `role="status"` or `role="alert"` (4.1.3).
- **Reflow and text:** both surfaces reflow at 320px with no horizontal scroll except inside data tables, which scroll within their own region. They tolerate WCAG text-spacing overrides.
- **Motion:** when `prefers-reduced-motion` is set, the image viewer zooms without animation.
- **Language:** `lang="en"` on both apps.
- **Charts:** see the Chart pattern.

## Responsive & Platform

| Surface | Primary device | Behavior |
| --- | --- | --- |
| Supplier page | Android and iOS phones, often mid-range, on mobile data | Single column. The build is kept small (roughly 150 KB JS, gzipped) for weak signal `[ASSUMPTION]`. Works in the phone's in-app browser (WhatsApp, SMS). |
| Goods-in scan | Tablet or phone at the loading dock | Supplier-page layout rules. |
| Staff app | Laptop or desktop, 1280px and wider | Sidebar at 1024px and wider. Below 1024px, the sidebar becomes a Sheet. The admin item stacks the image above the fields below 1024px. |

## Key Flows

Flows 1 and 2 include a failure path. Flows 3 to 7 are happy paths only, and their failure states are covered in *State Patterns*.

### Flow 1: Supplier uploads after a delivery (Mr Lim, owner of Lim Leather Trading, in his van, Android phone)

1. After dropping off leather trim at the warehouse, Mr Lim taps the link saved on his phone.
2. Upload home says "Uploading for **Lim Leather Trading**". A reminder banner lists PO 45019 as waiting for an invoice.
3. He taps **Take photo** and photographs the invoice on his clipboard.
4. The quality check passes in about a second, and a preview shows with **Send**.
5. He taps **Send**, and the progress bar fills.
6. **Climax:** "Received. Reference R-7Q4KXM2D." appears in the success color. He never had to type anything or send a WhatsApp message.

**Failure:** the van is dark, and the check says "Photo is too dark. Move to better light and take it again." He steps out and retakes it, and it passes.

### Flow 2: Admin clears a bank-details change (Priya, accounts admin, Tuesday morning)

1. Priya signs in, and the Admin queue opens: "3 invoices waiting".
2. The top row shows the chip **Bank details changed** from Kowloon Soles.
3. She opens it. The image is on the left, with the bank account field boxed. On the right, the bank-change panel shows the old account (`•••• 4821`), the new account (`•••• 9930`) and "Call +65 6123 4567 (number on file)".
4. She calls. The supplier's finance manager confirms they changed banks last month.
5. She ticks both checklist items, taps **Approve** and enters "Confirmed new account by phone with Ms Chan".
6. **Climax:** the item leaves the queue and the next one opens. On the Invoices surface, Kowloon Soles' invoice shows "Posted", and nobody had to type it into the accounts system.

**Failure:** the phone number on file is out of service, so Priya taps **Reject** with the reason "Could not verify bank change". The payment never goes out.

### Flow 3: Admin corrects an unsure reading (Priya, same session)

1. Next item: **Unsure reading** on a handwritten invoice from Chen Rubber.
2. The invoice total shows "91%" with its box on the image around a scrawled "1,248.50".
3. She presses `c`, changes the total to 1,246.50, and taps **Save and re-check**.
4. **Climax:** the item leaves the queue with "Sent for re-check". A minute later, Invoices shows it as "Posted": every check passed after the correction.

**Note:** the correction is saved for learning from corrections (CAP-10), whose training the architecture defers. Until that is built, the supplier's next invoice isn't guaranteed to read correctly.

### Flow 4: Goods-in scans a paper invoice (Rahman, loading bay, tablet)

1. The Goods-in scan screen shows today's expected deliveries. Rahman taps the one for PO 45102 from Sole Supply Co.
2. He takes a photo of the paper invoice from the box. The quality check passes, and he taps **Send**.
3. **Climax:** "Received for PO 45102, Sole Supply Co." appears, and the invoice enters the same pipeline as supplier uploads (CAP-2).

### Flow 5: Procurement checks a supplier before ordering (Wei Ling, procurement)

1. Wei Ling opens Suppliers and searches for "Kowloon Soles".
2. The scorecard shows an 82% on-time rate over 12 months and a price trend per material, with EVA soles up 6% since March.
3. She opens Deliveries and sees the three dates for each delivery (PO promised, invoice delivery, received).
4. **Climax:** she opens Price comparison for EVA soles, sees a cheaper supplier with a better on-time rate, and splits the order.

### Flow 6: Management gets a watchlist alert (Mr Goh, operations director)

1. An email arrives: "Kowloon Soles added to the watchlist: 3 price increases this year."
2. He taps the link, and the Watchlist entry opens with the evidence: 3 invoices with dates and unit prices.
3. **Climax:** below the evidence is a ranked list of alternatives already invoicing the same materials. He forwards it to Wei Ling to start the conversation with Kowloon Soles.

### Flow 7: Finance month-end (Siti, finance)

1. Siti opens Finance month for September.
2. The header shows "92% posted without an admin (target 90%)". The per-supplier table shows spend, 2 price-creep alerts, 14 flagged invoices and 3 duplicates caught.
3. **Climax:** she exports nothing and re-keys nothing, because the figures come from posted invoices.
