# Spine Pair Review — ocrinvoicing

Reviewed: `DESIGN.md` (133 lines), `EXPERIENCE.md` (247 lines), `.memlog.md`. Sources checked: `SPEC.md` (CAP-1..CAP-20), `ARCHITECTURE-SPINE.md` (AD-1..AD-17), `docs/standards/coding-style.md` (rules 15–18). Benchmarks: bmad-ux `design-example-shadcn.md`, `design-example-mobile.md`, `experience-example-shadcn.md`, `experience-example-mobile.md`, `design-md-spec.md`. Mockups were skipped by the user's choice, so visual reference coverage is N/A.

## Overall verdict

**Adequate. Fix the five high findings before story-dev extraction.** The pair is lean, faithful to its sources and correctly shaped. Every `{token}` reference, AD number and `coding-style.md` rule it cites resolves. Flows cover every user-facing capability. However, a consumer extracting stories would hit five load-bearing gaps:

1. The asynchronous result of **Correct** is not specified.
2. The rule that intersects allowed actions across reasons can make some invoices impossible to resolve correctly.
3. There are no labels for invoice statuses.
4. The derivation of the supplier reference collides.
5. Session-expiry (401) handling is missing.

Components and states are the thinnest areas: many EXPERIENCE components have no visual entry, and several surfaces lack error, empty and retention states. Nothing is critical, because every color token has a hex value and every reference resolves.

Counts: **critical 0 · high 5 · medium 11 · low 21**.

## 1. Flow coverage — adequate

CAP map: CAP-1/3/13 → Flow 1; CAP-8/9/11 → Flow 2; CAP-9/10 → Flow 3; CAP-2 → Flow 4; CAP-14/17/19 → Flow 5; CAP-15/16 → Flow 6; CAP-18 → Flow 7. CAP-4..7 are pipeline checks that surface through Admin item and the actions-by-reason table, which is justified. CAP-12 is covered only by the Overdue POs surface. CAP-20 is not user-facing. Every flow has a named protagonist, numbered steps and a climax.

### Findings

- **[high]** Flow 3's climax ("the invoice passes the PO match and posts") implies a synchronous result, but Correct only moves the invoice to `awaiting_validation`, and the pipeline re-validates it asynchronously (AD-2/AD-3). *Admin actions* also sends the admin to the next item straight away. Nothing says what the admin sees while re-validation runs, whether the item disappears from the queue, or what happens when re-validation raises a new reason (it re-enters the queue as a new `admin_item` run). Flow 3 also has no failure path. (EXPERIENCE.md L105, L210–215). *Fix:* Commit the post-Save behaviour: the item leaves the queue with a Toast ("Sent for re-check"), and a re-flag re-enters the queue with a "Re-checked" marker and the new reasons. Rewrite the Flow 3 climax to match, and add a failure path for the case where re-validation still fails.
- **[medium]** Flow 4 (goods-in) has no failure path. It doesn't cover a failed quality check at the dock, a delivery that isn't in today's list, or the database being stopped mid-shift. (EXPERIENCE.md L218–221). *Fix:* Add a failure line, for example: the delivery isn't listed → Rahman searches by PO number, and if there's no match he keeps the paper with the delivery.
- **[low]** CAP-12 (Overdue POs) and the CAP-11 `ACCOUNTS_API_ERROR` recovery exist only as a surface row and a table row. Neither has a flow or a component. (EXPERIENCE.md L47, L121). *Fix:* Acceptable for the PoC. Optionally, add a one-line flow for a procurement user reading the overdue list.
- **[low]** CAP-1's success criterion says links are "issued and revoked automatically". The spine replaces this with an operator-run script but doesn't mark it as a departure from the spec. (EXPERIENCE.md L242–246). *Fix:* Add "Departs from CAP-1 'automatically' (Dj's decision; AD-6)".
- **[low]** Step 3 of Flow 5 depends on the Deliveries tab, which is could-have (CAP-19). If CAP-19 is cut, the flow breaks. (EXPERIENCE.md L227). *Fix:* Mark step 3 as optional (could-have).
- **[low]** The supplier phone number differs between the Voice example (+65 9123 4567) and Flow 2 (+65 6123 4567). (EXPERIENCE.md L68, L203). *Fix:* Use one number.

## 2. Token completeness — adequate

All six added color tokens have hex values. Every `{…}` reference resolves, either to frontmatter or to stated shadcn inheritance: `colors.primary`, `primary-foreground`, `muted`, `foreground`, `destructive`, `destructive-foreground`, `rounded.full`, `typography.numeric`, `spacing.tap-min` and `spacing.supplier-gutter`. Measured contrast against white: success `#15803D` 5.0:1, warning `#B45309` 5.0:1, flag `#DC2626` 4.8:1. All pass, but the documents don't state these ratios.

### Findings

- **[medium]** No contrast target is stated for the added tokens. These are white text on success, warning and confidence-badge fills, plus the flag outline (a non-text 3:1 minimum against invoice imagery). The Accessibility Floor defers to DESIGN.md, and DESIGN.md only says "inherits shadcn's AA defaults", which doesn't cover tokens it adds. (DESIGN.md L14–20, L75–86; EXPERIENCE.md L169). *Fix:* Add one line to Colors: "success/warning/confidence-low with white text ≥ 4.5:1 (measured 5.0:1); flag outline ≥ 3:1 non-text".
- **[low]** The comment listing inherited colors omits `primary-foreground` and `destructive-foreground`, although both are referenced. (DESIGN.md L11–12, L37, L46). *Fix:* Add them to the list.
- **[low]** `rounded:` contains only a comment, so it parses as YAML `null`, yet `{rounded.full}` is referenced three times. (DESIGN.md L28–29). *Fix:* Declare `full: 9999px`, or at least write `rounded: {}` with the inheritance note.
- **[low]** Some values may not survive a token resolver. `typography.numeric.fontFeatureSettings` isn't one of the spec's typography properties. `field-flag-box.border` embeds a reference inside a composite string. `flag-fill` is an 8-digit hex with alpha. (DESIGN.md L19, L27, L52). *Fix:* Split the border into `borderWidth` plus `borderColor: '{colors.flag}'`, and note that `fontFeatureSettings` is an extension.
- **[low]** `confidence-low` duplicates the hex value of `warning`. (DESIGN.md L16, L20). *Fix:* Make it `'{colors.warning}'`, or state why it may diverge.
- **[low]** Three visual states have no tokens or visual spec: the "Corrected" field marker, the Bank-change panel and the image-viewer surface (named only in prose as `muted`). (EXPERIENCE.md L104, L106; DESIGN.md L106). *Fix:* Add component entries (see section 3).

## 3. Component coverage — thin

EXPERIENCE rows with no DESIGN.md Components entry (11): Quality check, Delivery picker, Reminder banner, Queue table, Image viewer, Field list, Admin actions, Bank-change panel, Evidence list, Supplier reference, Alternatives list. DESIGN entries with no EXPERIENCE row of their own (4): Reason chip, Confidence badge, Field flag box, Status pills. Their behavior is partly embedded in other rows.

### Findings

- **[high]** Invoice statuses have no labels. The Invoices surface shows status, and DESIGN names only "Posted" and "In admin queue", saying "the other statuses [are] a shadcn outline badge". AD-3 has ten states (`received`, `awaiting_extraction`, `extracting`, … `rejected`). Without labels, story-dev will render raw codes, which breaks the Voice rule that codes are secondary text only. (DESIGN.md L123; EXPERIENCE.md L46, L73). *Fix:* Add a Status label table next to the Reason labels table, collapsing states where that helps: received / awaiting_extraction / extracting / awaiting_validation / validating → "Processing"; ready_to_post / posting → "Posting"; posted → "Posted"; in_admin_queue → "In admin queue"; rejected → "Rejected". Assign each label a pill variant.
- **[high]** The Supplier reference derivation is broken. "First 6 characters in base32" of a UUIDv7 `invoice_id` are timestamp bits: 30 bits of a millisecond clock, which change only every ~4.4 minutes. Invoices uploaded close together get the same reference, so an admin's "search by it" is ambiguous. The worked example `R-7Q4K` also has 4 characters, not 6. (EXPERIENCE.md L109, L66, L195). *Fix:* Derive the reference from the random tail of the UUIDv7 (for example the last 8 base32 characters of `rand_b`), or store a separate short random reference. Make the example match, and tell the architecture owner (the reference isn't in AD-5/AD-6).
- **[high]** The multi-reason rule "only the actions allowed for **all** of them" can make an invoice impossible to resolve correctly. `BANK_CHANGED` + `LOW_CONFIDENCE` or `PO_MISMATCH` leaves only Approve or Reject, so the admin must post an unsure or mismatched amount, or reject a genuine invoice. Any reason combined with `UNREADABLE` leaves only Reject. (EXPERIENCE.md L112–123). *Fix:* Commit a sequence instead of an intersection. For example: Correct is allowed whenever any correctable reason is present, and bank-field locking still applies. After re-validation, `BANK_CHANGED` re-raises and needs its own call-back approval. Alternatively, state explicitly that such invoices are rejected and resubmitted, and add that to the voice copy.
- **[medium]** The 11 EXPERIENCE components listed above have no DESIGN.md entry. The worst gaps are Image viewer, Bank-change panel, Field list ("Corrected" marker) and Queue table, because they carry the product's core visual states. (DESIGN.md L112–123). *Fix:* For each one, add either a one-line "shadcn X unchanged" mapping (Queue table → `Table` + `Pagination`, Reminder banner → `Alert`, Delivery picker → `Command`/`Select`) or a short visual spec for the custom ones (Image viewer, Bank-change panel, Field list).
- **[medium]** Component names drift between the two files. DESIGN has "Status pills" (tokens `status-pill-*`) with no EXPERIENCE row. Reason chip, Confidence badge and Field flag box have no rows of their own. DESIGN says "Goods-in screen" where the IA says "Goods-in scan", and "admin item detail" where the IA says "Admin item". (DESIGN.md L100–101, L119–123; EXPERIENCE.md L44–45). *Fix:* Use the IA and EXPERIENCE names verbatim in DESIGN.md. Add rows for Reason chip (behavior: blocking variant, tooltip showing the code), Confidence badge (threshold and rounding), Field flag box and Status pill.
- **[medium]** The "matching invoice side by side" view for Possible duplicate is a load-bearing layout with no component, anatomy or rules. It doesn't say which fields are compared, whether both images show, or how the matching invoice's status appears. (EXPERIENCE.md L119). *Fix:* Add a "Duplicate compare" component row with a DESIGN entry.
- **[medium]** Non-admin roles see bank values as `•••• 4821` in the Evidence list. AD-11 says `staff-api` serves decrypted bank details only to admins, so rendering the last 4 digits for finance or management needs either server-side decryption for non-admins or a stored last-4 column. The architecture defines neither. (EXPERIENCE.md L107–108; DESIGN.md L122). *Fix:* Decide which applies: non-admin roles see no bank fields at all (simplest, and matches AD-11), or the architecture adds a last-4 projection.
- **[low]** The shadcn inventory is incomplete. Checkbox (call-back checklist), Progress (upload), Pagination (50-row tables) and Sidebar are used but not listed. `Toast` is superseded by `Sonner` in current shadcn. (DESIGN.md L114). *Fix:* Complete the list and name the toast primitive.
- **[low]** The Capture button has two actions (Take photo, Choose file), but DESIGN specifies only one full-width primary. The visual weight of Choose file is undefined. (DESIGN.md L118; EXPERIENCE.md L98). *Fix:* State that Choose file is a secondary/outline `Button` below it.
- **[low]** Watchlist email `{rule}` and the price-alert wording have no label table, unlike reasons. (EXPERIENCE.md L131–132). *Fix:* Add labels for the three CAP-15 rules.
- **[low]** It is unspecified what happens when a keyboard shortcut targets an unavailable action: `a` while Approve is disabled by the checklist, or `c` when Correct isn't offered. (EXPERIENCE.md L158). *Fix:* "A shortcut for a hidden or disabled action does nothing."
- **[low]** The confidence display doesn't specify rounding. A 97.6% field would show "98%" with a badge. (DESIGN.md L120; EXPERIENCE.md L104). *Fix:* Floor to a whole percent for display.

## 4. State coverage — thin

Covered well: cold start ("Waking up"), database stopped on all three surface groups, upload progress and failure, photo refused, revoked link, empty admin queue, page-limit alert, item already resolved, generic analytics empty, and not-allowed routes.

### Findings

- **[high]** There is no session-expiry state. AD-14 deliberately makes built-in auth return **401** (instead of redirecting) for XHR calls, so every staff surface will receive 401s when the Entra session lapses, and the spine doesn't say what to do. (EXPERIENCE.md L135–151, L160). *Fix:* Add a state row: on any 401, show "Your session has ended. Sign in again." and redirect to `/.auth/login/aad?post_login_redirect_uri=<current route>`, keeping any unsaved Correct edits in memory.
- **[medium]** Staff surfaces have no generic load or action error state (network drop, 5xx), and nothing says how the SPA tells "Database stopped" apart from other failures. That needs a named API error code, which `domain/errors.py` doesn't define. (EXPERIENCE.md L140, L148). *Fix:* Add a "Couldn't load" row with Retry, and name the error code (for example `DB_UNAVAILABLE`) that triggers the full-page offline notice. Pass that code to the architecture owner.
- **[medium]** Nothing covers an Admin item whose image has been deleted by the 30-day lifecycle rule (AD-15). The queue is sorted oldest first, so this is likely. The image viewer, the CAP-9 crop and the duplicate comparison all break. (EXPERIENCE.md L103, L119). *Fix:* Add a state: "Image deleted after 30 days (retention). Fields and reasons are still shown." Show the queue age in warning color before day 30.
- **[medium]** Camera permission denied is not covered. This is the supplier-side "permission denied" case, and it applies to both the supplier page and goods-in. (EXPERIENCE.md L98, L142–145). *Fix:* Add a state: "Camera is blocked. Allow it in your browser settings, or use Choose file."
- **[medium]** After a network failure, "tap Send again" re-posts the photo. If the first request actually reached the server, the retry creates a second `invoice_id`, which raises `DUPLICATE` and adds admin work. (EXPERIENCE.md L143; AD-6). *Fix:* Commit a client-generated upload id (idempotency key) sent on every retry, or accept that the duplicate check absorbs it and say so.
- **[low]** Several surfaces lack a specific empty or no-result state: Goods-in (no deliveries today, no search match), Invoices search, Overdue POs (none overdue), Watchlist (no suppliers watchlisted; "No posted invoices yet" is the wrong copy there) and Suppliers search. (EXPERIENCE.md L146, L150). *Fix:* Add one row per surface.
- **[low]** Quality-check copy exists only for darkness. There are no strings for blur, document cut off, PDF over 2 pages, file over 4 MB or unsupported type. The color of supplier error text is also undefined, since DESIGN rules out colors other than primary and success on the supplier page. (EXPERIENCE.md L65, L99; DESIGN.md L86). *Fix:* Add the five strings, and state that errors use foreground text plus an icon.
- **[low]** Only Overdue POs shows when its data was produced. The other analytics surfaces also refresh only on weekdays (AD-13), but they don't say so. (EXPERIENCE.md L47–53). *Fix:* Add an "Updated {date}" line to the headers of every analytics surface.

## 5. Visual reference coverage — N/A

Mockups were skipped by the user's choice. This is not a finding.

## 6. Bloat & overspecification — strong

### Findings

- **[low]** Some architecture detail is restated in the UX spine: the `X-Requested-With` header, the Supplier master script mechanics (encryption, fingerprinting) and the Function-app hosting in Foundation. (EXPERIENCE.md L16, L160, L242–247). *Fix:* Replace each with a one-line pointer to the AD (AD-6, AD-11, AD-14). Keep only the UX consequence, for example "no supplier admin screen".

## 7. Inheritance discipline — adequate

Every AD reference (AD-4, 6, 11, 12, 14, 16) and every `coding-style.md` rule (15–18) exists and says what the spine claims. Reason labels map 1:1 onto the 12 AD-4 codes. The per-environment DI caps (Prod 400, Dev 100) and the 98% threshold match AD-8 and the SPEC.

### Findings

- **[medium]** The UI system is tagged `[ASSUMPTION]` in EXPERIENCE but stated as fact in DESIGN.md. The memlog records no confirmation from Dj, so it's unclear whether the stack is committed. (EXPERIENCE.md L19; DESIGN.md L3; .memlog.md L7). *Fix:* Get Dj's confirmation and remove the tag, or add the same tag to DESIGN.md.
- **[low]** The pair has two different names: DESIGN.md `name: Babaloo Invoice Intake` and EXPERIENCE.md `name: OCR Invoice Automation`. (DESIGN.md L2; EXPERIENCE.md L2). *Fix:* Use one name, or add a `pairs_with:` line.

## 8. Shape fit — adequate

DESIGN.md follows the canonical section order (Brand & Style → Do's and Don'ts). Its extra frontmatter keys (status, created, updated, sources) are harmless. EXPERIENCE.md has Foundation, IA, Voice and Tone, Component Patterns, State Patterns, Interaction Primitives, Accessibility Floor, Responsive & Platform and Key Flows.

### Findings

- **[low]** There is no Inspiration & Anti-patterns section. The Banned list covers part of it. (EXPERIENCE.md L161–165). *Fix:* Omit it deliberately with a one-line note, or add 2–3 rejected patterns (for example, supplier-side confirmation of extracted data, rejected with its rationale).
- **[low]** A non-canonical "Supplier master" section sits after Key Flows, where consumers expect Key Flows to be last. (EXPERIENCE.md L242–247). *Fix:* Move it into Foundation or the IA as "Out of UI: supplier master and links".

## Mechanical notes

- **Token references checked (DESIGN.md):**
  - Frontmatter: `colors.primary`, `colors.primary-foreground`, `colors.muted`, `colors.foreground`, `colors.destructive`, `colors.destructive-foreground`, `colors.confidence-low`, `colors.warning-foreground`, `colors.flag`, `colors.flag-fill`, `colors.success`, `colors.success-foreground`, `colors.warning`, `rounded.full` (×3), `typography.numeric`.
  - Prose: `{spacing.supplier-gutter}`, `{spacing.tap-min}`, `{rounded.full}`, `{typography.numeric}`.
  - All resolve, either to frontmatter or to stated shadcn inheritance. Unresolved: none.
- **Hex values:** 6/6 color tokens have one (`flag-fill` uses 8-digit RGBA).
- **Contrast (computed, not stated in the documents):** `#15803D`/white 5.0:1; `#B45309`/white 5.0:1; `#DC2626`/white 4.8:1.
- **Capabilities:**
  - With a flow: CAP-1, 2, 3, 8, 9, 10, 11, 13, 14, 15, 16, 17, 18, 19.
  - Covered by a surface or table: CAP-4, 5, 6, 7, 12.
  - Not user-facing: CAP-20.
- **Surfaces × states:** 14 surfaces checked.
  - Cold load: global row.
  - DB stopped: staff (global), goods-in and supplier.
  - Permission denied: staff (global Toast). Supplier camera permission is missing.
  - Generic error: missing on the staff side.
  - Empty: only Admin queue and "Analytics" (generic).
  - Session expiry: missing.
- **Cross-document references verified:** AD-4, AD-6, AD-11, AD-12, AD-14 and AD-16 exist in ARCHITECTURE-SPINE.md. `coding-style.md` rules 15, 16, 17 and 18 exist with matching meaning. The brainstorm source file exists.
- **Imports folder:** empty (mockups skipped).
