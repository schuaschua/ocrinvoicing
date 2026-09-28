---
id: SPEC-ocr-invoice-automation
companions:
  - ../../planning-artifacts/architecture/architecture-ocrinvoicing-2026-09-28/ARCHITECTURE-SPINE.md
  - ../../planning-artifacts/ux-designs/ux-ocrinvoicing-2026-09-28/DESIGN.md
  - ../../planning-artifacts/ux-designs/ux-ocrinvoicing-2026-09-28/EXPERIENCE.md
sources: []
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# OCR Invoice Automation

## Why

This build is a proof of concept. Pain plus opportunity. A sport-shoe retail chain receives thousands of supplier material invoices a month, many as phone photos shared over WhatsApp. Admins extract the photos, key in the data and send it to the accounts system by hand: slow, error-prone (wrong supplier IDs slip through) and open to fraud (edited photos, duplicates, impersonated senders redirecting payments). Automating intake removes the keying. The same invoice data then shows finance and procurement which suppliers ship late or overcharge.

## Capabilities

- **CAP-1**
  - **intent:** A supplier submits an invoice photo or PDF from their phone through a personal upload link, and the link identifies the supplier.
  - **success:** An upload via supplier A's link is recorded as supplier A regardless of the supplier ID printed on the invoice; the supplier has no way to edit extracted data. Links are issued and revoked by an operator-run supplier load script: `--replace-link` revokes a supplier's link and issues a new one, and `--revoke` revokes it without issuing another. Each new link is printed once, for Dj to send to the supplier. This departs from P-8 ("issued and revoked automatically"), as Dj accepted (AD-6).
- **CAP-2**
  - **intent:** Paper invoices arriving with goods are captured at warehouse goods-in and linked to that delivery.
  - **success:** A paper invoice scanned at goods-in enters the same intake as uploads, attached to its delivery and supplier.
- **CAP-3**
  - **intent:** Unreadable photos are rejected at upload so the supplier retakes them.
  - **success:** A blurred, dark or cropped photo is refused before submission with a retake prompt; a clear photo is accepted. After 2 refusals the supplier may send it anyway; the server re-checks it with the same thresholds, processes it normally if it passes, and sends it to the admin queue if it fails.
- **CAP-4**
  - **intent:** Invoice fields are extracted from any supplier layout, including handwriting, with a confidence per field.
  - **success:** An invoice in a layout never seen before is extracted without per-supplier setup; each field carries a confidence score, and any checked field below 98% sends the invoice to the admin queue. The checked fields are the supplier name, invoice number, invoice date, sub-total and total; each line's product code, quantity, unit price and amount; the PO number on supplier uploads; and the supplier tax ID when it is printed. Other fields are stored but not checked (AD-18).
- **CAP-5**
  - **intent:** Extracted amounts are checked against the PO price × received quantity.
  - **success:** An invoice whose pre-tax amount differs from PO price × the received quantity not yet invoiced, by more than the larger of 1% and 1.00, lands in the admin queue, not the accounts system (AD-19).
- **CAP-6**
  - **intent:** Duplicate invoices are caught, including re-photographed copies.
  - **success:** A second submission of the same invoice (same supplier, number, amount, date, or visually the same document) lands in the admin queue.
- **CAP-7**
  - **intent:** The photo-taken date is checked against the PO's latest goods-received date.
  - **success:** A photo taken before the goods were received, or more than 30 days after, lands in the admin queue; the supplier is not notified. A PDF or scan with no photo-taken date also lands in the admin queue as an exception.
- **CAP-8**
  - **intent:** Invoices with bank details that differ from the supplier master are held for verification.
  - **success:** Such an invoice never auto-posts; the admin queue shows it with the supplier's phone number on file for call-back.
- **CAP-9**
  - **intent:** One admin queue receives every exception: low confidence, PO mismatch, duplicate, date mismatch, bank change, printed supplier ID not matching the link's supplier, accounts API failure.
  - **success:** Each queued item shows the reason, the relevant photo crop and the flagged fields; the admin resolves it from there.
- **CAP-10**
  - **intent:** Admin corrections improve future extraction for that supplier's format.
  - **success:** Every admin correction is stored for learning (for 30 days, P-11), behind a model-selection seam. Training custom models from the corrections is deferred (architecture Deferred, Q10b); until it is built, a corrected field is not guaranteed to read correctly on the supplier's next invoice.
- **CAP-11**
  - **intent:** Invoices that pass every check post automatically to the accounts system.
  - **success:** A clean invoice reaches the accounts system through its XML API with no human keying; failed calls retry, then go to the admin queue with the API error.
- **CAP-12**
  - **intent:** An overdue list, made each weekday, shows POs past their expected date with no invoice received, grouped by supplier.
  - **success:** A PO expected 7 Jan with no invoice appears on the next weekday's list (8 Jan, when that is a weekday) under its supplier.
- **CAP-13**
  - **intent:** Overdue POs trigger a reminder to the supplier through the upload app.
  - **success:** A supplier with an overdue PO receives a reminder without anyone sending it manually, repeated once a week until the invoice arrives.
- **CAP-14**
  - **intent:** Finance and procurement can compare suppliers' prices for the same material and are alerted when a supplier's unit price rises against its own recent invoices.
  - **success:** For a material, all suppliers' unit prices are shown side by side; a price rise triggers an alert naming the supplier, material and invoices.
- **CAP-15**
  - **intent:** A supplier is added to a watchlist when it has 3+ price increases within a year, deliveries 7+ days late on average, or prices 5%+ above the cheapest supplier of the same material.
  - **success:** When a rule trips, procurement and management are notified with the evidence (invoices, dates, price history) to start a conversation with the supplier.
- **CAP-16**
  - **intent:** When a supplier is watchlisted, alternatives already invoicing the same material are shown, ranked by price and speed.
  - **success:** Management sees a ranked shortlist for the watchlisted supplier's materials alongside the alert.
- **CAP-17**
  - **intent:** Procurement sees a supplier scorecard (on-time rate, price trend per material) when deciding an order.
  - **success:** For any supplier and material, procurement can view on-time rate and price trend derived from posted invoices.
- **CAP-18**
  - **intent:** Finance sees monthly spend by supplier, price-creep alerts, and counts of flagged and duplicate invoices.
  - **success:** A monthly finance view shows these figures per supplier.
- **CAP-19** *(could-have)*
  - **intent:** Each delivery compares the PO promised date, the invoice delivery date and the goods-received date.
  - **success:** For a delivery, all three dates and the gaps between them are shown.
- **CAP-20**
  - **intent:** A simulated PO and goods-received data source stands in for the external DB until it is connected.
  - **success:** CAP-5, CAP-12 and CAP-19 run end to end against the simulated data, and switching to the external DB changes no capability behaviour.

## Constraints

- The accounts system accepts data only through its API, in XML only.
- Suppliers cannot edit or confirm extracted data; the system trusts what it reads from the document.
- The photo's own date is trusted as the photo-taken date.
- Supplier identity comes from the upload link or the warehouse delivery, never from the supplier ID written on the invoice.
- Every invoice auto-posts unless a check flags it; the admin queue is the only human touchpoint.
- The late-shipment signal is rule-based (no invoice by the PO expected date); no predictive modelling.
- The PoC is tested at no more than 500 invoice pages a month, and no invoice is longer than 2 pages. The target state is thousands of invoices a month.
- OCR confidence threshold is 98% per checked field (CAP-4); below it, the invoice goes to the admin queue.
- PO and goods-received data come from an external DB, simulated for now; the source must be swappable without changing the capabilities that use it.
- Invoice images and admin corrections are retained for 1 month (PoC).
- All capabilities are in scope; no minimal-first slice. CAP-19 is could-have.

## Non-goals

- Recognising suppliers from invoice logos.
- Supplier editing or confirmation of extracted data.
- Predicting late shipments beyond the overdue rule.
- Staffing or redeployment of freed-up admins.
- Changing the accounts system itself.
- Production record-retention policy (1 month applies to the PoC only).
- Managing the move off WhatsApp (handled by a memo to suppliers).

## Success signal

- An invoice photographed and uploaded through a supplier's link that passes every check appears in the accounts system with no human keying. One that fails any check appears in the admin queue with its reason.
- 90% of invoices reach the accounts system with no admin involvement.
- Procurement can open any supplier and see its on-time rate and price trend, and a supplier that trips a watchlist rule triggers a notification with evidence.

## Assumptions

- The upload page is a mobile web page reached by link ("a page on mobile", later "the suppliers app").
- The supplier master holds bank details and a phone number on file (CAP-8).
