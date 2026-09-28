# Accessibility review: DESIGN.md + EXPERIENCE.md (WCAG 2.2 AA)

Reviewed: 2026-09-28. Scope: `DESIGN.md`, `EXPERIENCE.md` in this folder. Lens: WCAG 2.2 AA.

## Verdict

**Not ready: revise before build.** The spines have a sound base. Every status has a text label, targets are 48px, text is 16px, native file and camera inputs are used, `aria-live` covers the quality check, the field list mirrors the flag boxes, and it is paginated rather than infinite scroll. The added status tokens pass AA as pill fills with white text. But the spines claim "WCAG 2.2 AA" while specifying several patterns that fail it as written:

- the global single-key shortcuts (2.1.4);
- the fixed 30 s reveal (2.2.1);
- a quality gate with no override, which can lock out low-vision or motor-impaired suppliers;
- flag boxes drawn over arbitrary photo content (1.4.11);
- charts with no text alternative (1.1.1);
- status messages outside the quality check that are never announced (4.1.3).

Most fixes are one-line spine edits.

Counts: critical 1 · high 7 · medium 12 · low 7

## Computed contrast (WCAG relative luminance)

| Pair | Ratio | Requirement | Result |
| --- | --- | --- | --- |
| White on success `#15803D` (Posted pill, text) | 5.02:1 | 4.5:1 text | Pass |
| White on warning / confidence-low `#B45309` (pill, badge text) | 5.02:1 | 4.5:1 text | Pass |
| Success `#15803D` as text on muted `#F4F4F5` | 4.56:1 | 4.5:1 | Pass (marginal) |
| Warning `#B45309` as text on muted `#F4F4F5` | 4.57:1 | 4.5:1 | Pass (marginal) |
| Flag `#DC2626` outline on white | 4.83:1 | 3:1 non-text | Pass |
| Flag `#DC2626` outline on muted `#F4F4F5` | 4.39:1 | 3:1 | Pass |
| Flag outline vs its own 8% fill (on white `#FCEEEE`) | 4.28:1 | 3:1 | Pass |
| Flag outline vs its own 8% fill on muted (`#F2E4E5`) | 3.91:1 | 3:1 | Pass |
| Flag `#DC2626` vs black ink / dark photo `#18181B` | 3.67:1 / 4.35:1 | 3:1 | Pass |
| Flag `#DC2626` vs mid-grey photo `#71717A` (shadow, cardboard, van interior) | 1.00:1 | 3:1 | **Fail** |
| Flag `#DC2626` vs red letterhead or stamp | ~1:1 | 3:1 | **Fail** |
| shadcn v3-era destructive `#EF4444` with `#FAFAFA` text (blocking chip) | 3.61:1 | 4.5:1 | **Fail** |
| shadcn v4 destructive `#E7000B` with white | 4.77:1 | 4.5:1 | Pass |

The Tailwind v4 default is roughly `#E7000B`. The v3-era value is `#EF4444`. Because DESIGN.md inherits shadcn without pinning a version, the blocking chip may fail.

## Findings

### Critical

- **[critical]** The quality check has no override and no accessible alternative. A blurry or cut-off photo can only be retaken. A supplier with low vision, a tremor, or one-handed use in a van may never produce a passing photo, and **Choose file** still runs the photo checks on JPEG/PNG. The only escape is to contact the buyer, and the link-failure copy doesn't say that. This makes the task impossible for some users. It is not framed as a WCAG failure, but it is a hard lockout that conflicts with 1.3.1/2.5.x intent and with EN 301 549 "operation without vision" (EXPERIENCE.md, Component Patterns > Quality check; State Patterns > Photo refused). *Fix:* add to Quality check: "After 2 failed checks in a row, show a secondary **Send anyway** link, labelled 'Send it anyway. Babaloo will check it by hand'. It routes to the admin queue as `UNREADABLE`, so the server still decides. Failure copy names the specific edge ('The left edge of the invoice is cut off') and gives one framing tip. The Photo refused state also shows 'Having trouble? Contact your buyer at Babaloo.'"

### High

- **[high]** The single-character shortcuts `j`, `k`, `c`, `a`, `r`, `n`, `p` have no off switch, no remapping, and no focus scoping. This fails 2.1.4 Character Key Shortcuts. They collide with screen-reader browse-mode quick keys (in NVDA and JAWS, `k` is the next link, `r` the next region, `c` the next combobox, `a` the next radio button, `p` the next paragraph, `j` jumps), and with speech-input users dictating words (EXPERIENCE.md, Interaction Primitives > Staff; Component Patterns > Image viewer). *Fix:* add to Interaction Primitives: "Single-key shortcuts are off by default and are turned on in a per-user 'Keyboard shortcuts' setting, with a help dialog on `?` listing them. They never fire when focus is in an input, textarea, select or contenteditable, or while a dialog is open. The same actions are available with modifiers (`Alt+Shift+A`, and so on) at all times."

- **[high]** The 30 s **Show** reveal auto-hides on a fixed timer with no way to extend it. This fails 2.2.1 Timing Adjustable: a screen-reader or low-vision admin reading a 12–16 digit account aloud to a supplier on the phone can easily exceed 30 s, and the value vanishes mid-read with no announcement (EXPERIENCE.md, Component Patterns > Masked value, Bank-change panel). *Fix:* replace the rule with: "**Show** reveals the value until the admin selects **Hide**, leaves the item, or 30 s pass. At 20 s, an `aria-live="polite"` notice 'Hiding in 10 s' offers **Keep showing** (+30 s, re-audited, repeatable). When hidden, focus stays on the Show button, now relabelled 'Show account number', and 'Account number hidden' is announced."

- **[high]** Flag boxes are drawn in red over arbitrary photo content. Against grey shadows, brown cardboard or red letterheads and stamps, the outline drops to about 1:1. This fails 1.4.11 Non-text Contrast, because adjacent colours are unknown (DESIGN.md, Colors > Flag; Components > Field flag box; frontmatter `field-flag-box`). *Fix:* change `field-flag-box` to "`2px solid {colors.flag}` inside a `1px` white outer halo (`outline: 1px solid #FFFFFF` or a double stroke), plus a numbered corner tag (white text on `{colors.flag}`, 4.83:1) matching the field's number in the list." Add a row to Colors: "The flag box always carries a white halo so it keeps 3:1 against any photo."

- **[high]** Charts have no text or table alternative, and series may be told apart by colour alone. This fails 1.1.1 and 1.4.1. It affects the scorecard price trend per material, on-time rate, Deliveries gaps and the Finance month 90% gauge (EXPERIENCE.md, Information Architecture > Supplier scorecard, Price comparison, Finance month; DESIGN.md has no chart guidance). *Fix:* add to EXPERIENCE.md Component Patterns a **Chart** row: "Every chart has a one-sentence text summary above it (for example 'EVA soles up 6% since March') and a 'View as table' toggle showing the same data in a `Table` with caption. Series are distinguished by direct labels or marker shape, not colour alone. Tooltips are keyboard-reachable and are never the only place a value appears." Add a DESIGN.md Colors line for chart series tokens, each at 3:1 or better against the card background.

- **[high]** The spines don't say how status messages outside the quality check are announced. This fails 4.1.3. It affects upload progress and completion, "Received. Reference R-7Q4K.", "Couldn't send…", "Waking up, one moment…", the post-action "next item opened", "Already handled by another admin", the Save and re-check result, the Toast "You don't have access…", the page-limit Alert, and the queue count updating (EXPERIENCE.md, State Patterns; Accessibility Floor). *Fix:* add to Accessibility Floor: "Every row in State Patterns is announced. Success and progress use `role="status"` (polite): progress is announced at start, 50% and done, not every tick. Upload failed, Photo refused and Already handled use `role="alert"`. The Received reference is inside the live region and is also given focus with `tabindex=-1` so it can be re-read. Toasts persist for at least 6 s, pause on hover and focus, and are also listed in a 'Recent notices' region."

- **[high]** The blocking reason chip inherits shadcn `destructive` without a pinned value. With the v3-era token (`#EF4444` / `#FAFAFA`), chip text is 3.61:1, which fails 1.4.3. It also uses the same red hue as the flag, so red means two things (DESIGN.md, frontmatter `reason-chip-blocking`; Colors > Destructive). *Fix:* in the frontmatter, pin `destructive: '#B91C1C'` (6.47:1 with white) or state "destructive must be at least 4.5:1 against destructive-foreground, verified in CI". Give the blocking chip a leading icon (for example a lock or stop sign) and the visually hidden prefix "Blocking:".

- **[high]** No focus-visible spec, and nothing on focus not being obscured. This leaves 2.4.7 and 2.4.11 unaddressed. The risks are sticky table headers and pagination bars, the Sheet sidebar below 1024px, the stacked admin item where the image pane can cover fields, Toasts overlapping the focused row, and the on-screen keyboard covering the supplier Send button. shadcn v4's `ring/50` can fall below 3:1 on `muted` (DESIGN.md, no focus section; EXPERIENCE.md Accessibility Floor > Focus). *Fix:* add a DESIGN.md token `focus-ring: 2px solid {colors.ring}, 2px offset`, with ring at 3:1 or better against both background and muted, and "no reduced-opacity rings". Add to Accessibility Floor: "Sticky headers and footers use `scroll-padding-top/bottom` equal to their height so the focused row is never hidden. Toasts render in a corner away from the table's focus path and never cover the focused element."

### Medium

- **[medium]** The image viewer has no keyboard or pointer spec for zoom and pan. Panning a zoomed invoice is normally a drag, which fails 2.5.7 Dragging without a single-pointer alternative. Pinch-zoom on the goods-in tablet needs 2.5.1 alternatives. The arrow keys are said to step between regions, which conflicts with pan and scroll (EXPERIENCE.md, Component Patterns > Image viewer). *Fix:* add: "Zoom in, Zoom out, Fit and **Show whole invoice** buttons (at least 24px, labelled). Pan by buttons or by arrow keys when the canvas has focus. Stepping between flagged regions uses `n`/`p` (per the shortcut setting) and **Previous flag / Next flag** buttons. Drag-to-pan is optional, never required."

- **[medium]** The image viewer is the only visual context for a flag. The spec says a screen-reader user can review without the image, but not what replaces it. The OCR bounding region conveys where on the page and "scrawled" handwriting, which matters for the decision (EXPERIENCE.md, Accessibility Floor > Image viewer). *Fix:* add: "The viewer has `role="img"` with `aria-label` 'Invoice from {supplier}, page {n} of {m}, {k} flagged regions'. Each field in the list states its flag reason in text and shows the raw OCR text of its region next to the parsed value. Handwriting and poor legibility are stated in the reason ('Unsure reading, handwritten')."

- **[medium]** The field list's "flag state" has no specified non-colour signal, and it is unclear whether the selected-box highlight is colour-only (1.4.1, 1.4.11) (EXPERIENCE.md, Component Patterns > Field list; DESIGN.md, Components > Field flag box). *Fix:* in DESIGN.md Components add: "Flagged fields show a flag icon, the text 'Flagged: {reason label}' and the matching box number. The selected box changes stroke width (2px to 4px) and shows its tag, not only a colour change."

- **[medium]** `field-flag-box` elements are selectable ("selecting a box focuses its field"), but small bounding regions at fit zoom will be under 24×24 px. The 2.5.8 equivalent-control exception applies only if it is stated (DESIGN.md Layout > Tap targets; EXPERIENCE.md Image viewer). *Fix:* add: "Flag boxes are a pointer convenience, not in the tab order. The field list is the equivalent control. Numbered tags are at least 24×24 px." In DESIGN.md, change "every interactive element is at least 48px" to "at least 48px on supplier and goods-in surfaces, at least 24px (2.5.8) in the staff app, with spacing so 24px circles don't overlap". That keeps dense tables feasible and the claim true.

- **[medium]** Approve stays disabled until both checklist items are ticked. Disabled shadcn buttons leave the tab order and give no reason, so screen-reader users hear nothing and don't know why (3.3.2, 4.1.2) (EXPERIENCE.md, Component Patterns > Bank-change panel). *Fix:* "Approve uses `aria-disabled="true"`, stays focusable, and is described by 'Tick both checks to approve'. Activating it moves focus to the first unticked checkbox. Checklist labels are clickable, with a hit area of at least 24px."

- **[medium]** Required-reason and Correct-mode validation don't say how errors are identified or suggested (3.3.1, 3.3.3). Neither do the 4 MB, JPEG/PNG/PDF and more-than-2-pages refusals on **Choose file** (EXPERIENCE.md, Admin actions; Quality check). *Fix:* add to State Patterns a row "Field error | Staff dialogs, Correct mode: an inline message under the field, linked with `aria-describedby`, `aria-invalid`, focus moved to the first invalid field, and a suggestion (for example 'Enter an amount like 1,246.50'). File refused (supplier): 'This file is 6 MB. Choose one under 4 MB, or take a photo instead.'"

- **[medium]** The masked value `•••• 4821` will be read as "bullet bullet bullet bullet 4821", or skipped. Revealed digits are read as one large number (1.3.1, 4.1.2) (DESIGN.md Components > Masked value; EXPERIENCE.md Masked value). *Fix:* "Masked value has `aria-label` 'Account ending 4821'. The bullets are `aria-hidden`. Revealed values are grouped in 4s with `aria-label` spelling the digits. Show is a toggle button with `aria-pressed`."

- **[medium]** The camera capture fallback isn't specified. `<input capture>` is ignored or broken in some in-app browsers (WhatsApp, SMS webviews), and a screen-reader user gets no framing help from the OS camera. The photo preview needs a text alternative (1.1.1, 4.1.2) (EXPERIENCE.md, Capture button; Responsive > Supplier page). *Fix:* "If `capture` is unsupported, **Take photo** falls back to the file picker, which offers the camera. The preview `<img>` has alt 'Your photo, ready to check'. During the check, `role="status"` announces 'Checking photo…', then 'Photo looks good. Ready to send.' or the named problem. Focus moves to **Send** or **Take again**."

- **[medium]** Reflow at 320 CSS px (1.4.10) isn't addressed for the staff app, where 1280px at 400% gives 320px. Dense tables, the two-pane admin item, filter bars and the Finance month header all need a stated behaviour (EXPERIENCE.md, Responsive & Platform). *Fix:* add: "At 320px wide, all staff surfaces reflow to one column. Data tables may scroll horizontally inside their own region (`role="region"`, `aria-label`, `tabindex=0`), and nothing else does. The first column stays sticky. Filters collapse into a Sheet."

- **[medium]** SPA route changes don't set a unique page title or move focus, so screen-reader users get no announcement of the new surface (2.4.2, 2.4.3, 4.1.3). This includes the auto-advance to the next admin item (EXPERIENCE.md, Accessibility Floor > Focus; Admin actions "moves to the next item"). *Fix:* add: "Each surface sets `document.title` ('Admin item: Chen Rubber, Unsure reading · Babaloo'). On route change, focus moves to the page `h1`. After an admin action, 'Approved. Next: {supplier}, {reason}' is announced, and focus goes to the new item's `h1`, not a queue row, which removes the current ambiguity. When the queue is empty, focus goes to the empty-state message."

- **[medium]** Queue rows are said to open "by clicking a row". A clickable `<tr>` is not keyboard-operable or announced as a link (2.1.1, 4.1.2) (EXPERIENCE.md, Queue table). *Fix:* "The supplier cell is a real link to Admin item. The whole-row click is a pointer convenience only. `j`/`k` move a visible row focus (`aria-selected` in a grid, or roving tabindex)."

- **[medium]** The Entra session and in-progress work have no timeout handling. An admin mid-Correct or on a long call-back could lose edits when the token expires (2.2.1, 2.2.5 intent). Accessible authentication (3.3.8) for Entra is assumed rather than stated (EXPERIENCE.md, Foundation > Staff app). *Fix:* add: "Before a session expires, warn 2 minutes ahead with an option to extend. Unsaved Correct-mode edits and dialog reasons survive re-sign-in. Entra sign-in allows paste and password managers, and offers passkey or Authenticator push. No CAPTCHA or transcription challenge is added (3.3.8)." The supplier link needs no cognitive test, which passes 3.3.8. Note that as a strength.

### Low

- **[low]** Page language isn't stated for the markup, and supplier names may be in other scripts (3.1.1, 3.1.2) (EXPERIENCE.md, Foundation > Scope). *Fix:* "Both SPAs set `<html lang="en">`. Supplier names in non-Latin scripts are wrapped with the matching `lang` when known."

- **[low]** Text spacing (1.4.12): full-radius pills and chips and the 56px capture button may clip when line-height is 1.5, letter spacing 0.12em and word spacing 0.16em (DESIGN.md, Shapes; Components). *Fix:* "Pills, chips and buttons use `min-height`, not fixed `height`, allow wrapping, and never truncate the label with `overflow: hidden`."

- **[low]** Motion: the skeleton shimmer, the image-viewer zoom to the first flagged region, and the progress bar have no reduced-motion rule (2.2.2 for long waits, 2.3.3 good practice) (EXPERIENCE.md, State Patterns > App waking up; Image viewer). *Fix:* "Honour `prefers-reduced-motion`: static skeletons, instant zoom and pan, no auto-scrolling. The shimmer stops after 5 s once 'Waking up, one moment…' shows."

- **[low]** The confidence badge "91%" has no programmatic meaning, and the Field list reads as a bare percentage (1.3.1) (DESIGN.md, Components > Confidence badge). *Fix:* "The badge has a visually hidden prefix 'Confidence' and a tooltip or `title` 'Below 98%: check this value'. The tooltip is also available on focus."

- **[low]** The "Received" climax relies on the success colour for emphasis (Flow 1, step 6). The text carries the meaning, so this passes 1.4.1, but on the supplier page outdoors success-as-text is 5.02:1 on white, and a lighter tint surface would drop it toward 4.5:1 (DESIGN.md, Colors > Success). *Fix:* "The Received state uses a check icon plus a heading 'Received', with `{colors.success}` as text only on the white background, never on muted."

- **[low]** Hidden sidebar items plus the Toast redirect for disallowed routes is fine. But a Toast that auto-dismisses is the only explanation of why the page changed (2.2.1, 4.1.3) (EXPERIENCE.md, State Patterns > Not allowed). *Fix:* "Show the 'You don't have access to that page' message as an inline Alert at the top of the landing page, dismissible and not timed, in addition to or instead of the Toast."

- **[low]** Error prevention for the financial actions (3.3.4): Reject has a confirm dialog, but Approve (which triggers posting and payment) relies on the reason dialog alone, with no summary of what will be posted (EXPERIENCE.md, Admin actions). *Fix:* "The Approve dialog shows supplier, amount and the masked account being paid, next to the reason field, so the admin reviews before confirming."
