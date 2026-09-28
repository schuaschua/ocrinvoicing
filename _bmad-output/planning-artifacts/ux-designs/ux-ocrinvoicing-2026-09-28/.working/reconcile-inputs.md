# Reconcile: UX spines vs inputs

Checked: `DESIGN.md` and `EXPERIENCE.md` (UX spines) against `SPEC.md`, `ARCHITECTURE-SPINE.md` and `brainstorm.html`. I ignored ideas that the spec rejected as non-goals or that the brainstorm returned or dropped: supplier edit and confirm, upload timestamp over EXIF, late-shipment prediction, logo recognition and the logo-vs-link cross-check, and admin redeployment.

Severity: **High** means a capability or rule with no UX home, or a direct contradiction that will mislead the build. **Med** means a gap that a builder will have to guess at. **Low** means polish or a wording mismatch.

---

## 1. SPEC.md

### (a) Dropped or unsupported by the UX

| # | Sev | Spec item | Gap in UX | Suggested fix |
| --- | --- | --- | --- | --- |
| S1 | High | CAP-1: "Links are issued and revoked automatically"; the supplier must *get* the link | No surface or flow for how the supplier receives the link. Supplier admin has only "link status, re-issue a link". AD-6 stores only a hash, so the token can be shown once at most, and AD-16 says emails never carry link tokens. | Add a "Link issued" moment: where the token is shown once (or which channel sends it, e.g. SMS or WhatsApp to the phone on file), copy for handing it over, and what the supplier sees when a new link replaces an old one. Settle whether "re-issue" is a manual button or an automatic master event (see A1). |
| S2 | High | CAP-13: the supplier "receives a reminder … repeated once a week" | The UX has only a read-only banner on Upload home, which a supplier sees only if they open the link themselves. That is not "receiving" a reminder. AD-16 binds CAP-13 to `EmailPort`, but there is no reminder email copy, and the supplier master (Supplier admin) has no email field. The spec's assumption lists only a phone number. | Define the push channel for the reminder (email, which needs an email field in Supplier admin, or SMS) and its copy: no link token, no bank details, POs listed, plus the instruction to "open your saved upload link". Keep the banner as the secondary channel. |
| S3 | Med | CAP-9: each item shows "the relevant photo **crop** and the flagged fields" | The Image viewer shows the whole image with boxes. No crop-first view. | Open Admin item zoomed to the flagged region (crop), with "Show whole invoice" as the fallback. With several flags, step between the crops. |
| S4 | Med | CAP-11: a failed post goes to the queue "with the API error"; the reason set includes `UNREADABLE` and `UNSUPPORTED_DOCUMENT` | The admin actions don't say what resolves `ACCOUNTS_API_ERROR` (Approve means retry the post) or where the API error from `detail` is shown. They don't say what an admin can do for `UNREADABLE` or `UNSUPPORTED_DOCUMENT`, which have no fields to correct. The supplier already saw "Received", and a Reject there is silent. | Per reason, set the allowed actions and the label, e.g. show the API error text plus "Retry posting" (Approve) for `ACCOUNTS_API_ERROR`. For `UNREADABLE` and `UNSUPPORTED_DOCUMENT`: Reject, plus a prompt to call the supplier on the number on file to resend. |
| S5 | Med | CAP-2 plus AD-5: goods-in needs the database up, and the delivery is looked up by `delivery_id` | Goods-in lists only "today's expected deliveries". A late delivery, which is exactly the overdue case, isn't there. The "Database stopped" notice says "Supplier uploads still arrive", which doesn't help the dock. | Add search by PO or supplier on Goods-in scan. Add a Goods-in offline state: "Scanning is unavailable until <time>. Keep the paper invoice with the delivery." |
| S6 | Low | CAP-18: the figures are shown "per supplier" | The IA and Flow 7 show counts of flagged and duplicate invoices as month totals only. | Make Finance month a per-supplier table (spend, price-creep alerts, flagged, duplicates), with totals in the footer. |
| S7 | Low | CAP-19: "all three dates **and the gaps between them**"; the capability is could-have | Deliveries shows the three dates but not the gaps, and it isn't marked could-have. | Add columns for gap in days (promised → invoice, invoice → received). Mark the Deliveries tab as could-have, hidden if CAP-19 isn't built. |
| S8 | Low | Success signal: 90% of invoices post with no admin | No surface shows the straight-through rate. | Add a "Posted without review: 92%" figure to Finance month or the Admin queue header. |

### (b) UX inventions that contradict the spec

| # | Sev | UX says | Conflict | Fix |
| --- | --- | --- | --- | --- |
| S9 | Low | Flow 3 climax: "That supplier's next invoice in the same format should read correctly (CAP-10)" | Correct saves fields, but training is Deferred (Architecture Deferred, Q10b), so the PoC can't promise this. | Reword it to "the correction is saved for training that supplier's format". Don't imply an immediate effect. |

---

## 2. ARCHITECTURE-SPINE.md

### (a) Dropped or unsupported by the UX

| # | Sev | AD | Gap | Fix |
| --- | --- | --- | --- | --- |
| A1 | Med | AD-6: links are issued and revoked "triggered automatically by supplier master events" | Supplier admin has a manual "re-issue a link" control. It is unclear whether that is a master event or a bypass. | State that re-issue is a supplier-master action ("Replace link", which revokes the old one and issues a new one) that goes through the same automatic path. Log it to audit. |
| A2 | Med | AD-11: images, crops and decrypted bank details go only to `admin`; correction JSON never holds plaintext bank values | The Invoices surface (admin and finance) and the Evidence list ("linking to the invoice (admin and finance)") don't say that finance sees no image and a masked bank value with no Show. Correct mode doesn't say how bank fields are edited, or whether they can be. | Finance invoice detail: fields only, no image, bank value masked with no Show. Field list in Correct mode: bank fields are not editable, or they go through a separate masked input that never echoes the value. |
| A3 | Low | AD-13: the overdue list and reminders run on weekdays only, and the CAP-12 wording is open | The Overdue POs surface shows no "as of" date, so a Monday list covering the weekend isn't explained. | Add a header line: "As of Mon 12 Jan, 08:30". |
| A4 | Low | AD-7 and AD-12: invoices uploaded while the database is stopped wait | The Admin queue and Invoices surfaces give no hint that overnight uploads are still in the pipeline. | Optional: in the queue header, "5 invoices still processing". |

### (b) UX inventions that contradict the architecture

| # | Sev | UX says | Conflict | Fix |
| --- | --- | --- | --- | --- |
| A5 | Med | State "Page limit near": "412 of 500 pages used this month" | AD-8 caps each environment at Dev 100 and Prod 400. The 500 is the shared F0 limit, not the environment cap the alert tracks. | Use the environment cap, e.g. "322 of 400 pages used this month". |
| A6 | Med | Flow 1: "PO 45019 is gone from the banner the next time he opens the link" | AD-6 and AD-13: the banner reads `supplierreminders`, which the reminder job writes at the first run of each ISO week. `supplier-api` can't read PostgreSQL. So the banner stays stale for up to a week after the invoice arrives. | Either have the pipeline (validate or post) clear the supplier's reminder row when a PO gets its invoice, which needs an AD-6 or AD-13 amendment, or change the flow and banner copy to "Reminders update weekly". |
| A7 | Low | Supplier "Received. Reference R-7Q4K." | No short reference exists in the architecture. `invoice_id` is a UUIDv7, and `supplier-api` can't touch the database to allocate one. | Derive the short reference deterministically from `invoice_id` at upload (e.g. its last 5 base32 characters) and record that in the Consistency Conventions, or show a truncated id. |
| A8 | Low | Reason label `ACCOUNTS_API_ERROR`: "Accounts system rejected it" | AD-10 sends this reason after 5 failed attempts, which covers the system being unreachable as well as rejections. | Label it "Couldn't post to accounts" and show the error in `detail`. |

---

## 3. brainstorm.html (experience ideas kept in scope)

### (a) Dropped or without a UX home

| # | Sev | Brainstorm idea (kept) | Gap | Fix |
| --- | --- | --- | --- | --- |
| B1 | Med | Coach: "the admin sees **only a crop** of the photo and the uncertain field or fields to fix, not the whole invoice" | The UX leads with the full image, the opposite emphasis. The same issue as S3. | See S3. |
| B2 | Med | "Scorecard that combines price **and speed** for each material, to show who's cheapest and who's fastest" (the cheap+fast quadrant sketch) | Price comparison shows prices only. Speed and price for the same material are shown side by side only in the watchlist Alternatives list. | Add an on-time-rate column to Price comparison, or a price × on-time view per material. |
| B3 | Low | Procurement view: on-time rate and price trend "right in the ordering flow", before placing a PO | There is no ordering flow in this system, and the scorecard is standalone. | Keep it standalone for the PoC. Note in Open Questions that a deep link from the ordering tool (`/suppliers/<id>?material=`) is the future hook. |
| B4 | Low | The link carries three jobs, one of them "arrival time: records when each invoice arrives" | No staff surface shows arrival (upload) time next to the photo date and the delivery date for a `DATE_MISMATCH` item. | For `DATE_MISMATCH` and `NO_PHOTO_DATE`, show the photo date, the uploaded-at time and the invoice delivery date together in Admin item. |
| B5 | Low | Notifications with evidence to procurement and management; price-creep alerts | The email notifications (watchlist, price alert, supplier reminder) appear only in the flows. No notification catalogue gives recipients, subject copy or deep-link target, or states the AD-16 rule of no bank details and no tokens. | Add a short "Notifications" table to EXPERIENCE.md. |

### (b) UX inventions that contradict the brainstorm

None beyond B1. The UX follows the kept ideas: date mismatch goes to the admin and not the supplier, no supplier editing, and one admin queue.
