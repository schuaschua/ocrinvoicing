---
name: Babaloo Invoice Intake
description: Supplier invoice intake and review for Babaloo, a sport-shoe retail chain. shadcn/ui on Vite + React + Tailwind [ASSUMPTION]; this DESIGN.md specifies only the functional delta over shadcn defaults. No brand layer (Dj's decision).
status: final
created: 2026-09-28
updated: 2026-09-28
sources:
  - _bmad-output/specs/spec-ocr-invoice-automation/SPEC.md
  - _bmad-output/planning-artifacts/architecture/architecture-ocrinvoicing-2026-09-28/ARCHITECTURE-SPINE.md
colors:
  # primary, background, foreground, muted, border, input, ring, card and popover
  # inherit shadcn defaults. destructive is pinned. Functional status tokens are added.
  success: '#15803D'
  success-foreground: '#FFFFFF'
  warning: '#B45309'
  warning-foreground: '#FFFFFF'
  flag: '#DC2626'
  flag-fill: '#DC262614'
  confidence-low: '#B45309'
  destructive: '#B91C1C'
  destructive-foreground: '#FFFFFF'
  flag-halo: '#FFFFFF'
typography:
  # Body, label and heading ramps inherit shadcn. Two functional roles are added.
  body-supplier:
    fontSize: 16px
    lineHeight: '1.5'
  numeric:
    fontFeatureSettings: '"tnum"'
rounded:
  # shadcn defaults inherited.
spacing:
  # Tailwind 4-based scale inherited.
  tap-min: 48px
  supplier-gutter: 16px
components:
  capture-button:
    background: '{colors.primary}'
    foreground: '{colors.primary-foreground}'
    minHeight: 56px
    width: 100%
  reason-chip:
    background: '{colors.muted}'
    foreground: '{colors.foreground}'
    radius: '{rounded.full}'
  reason-chip-blocking:
    background: '{colors.destructive}'
    foreground: '{colors.destructive-foreground}'
    radius: '{rounded.full}'
  confidence-badge-low:
    background: '{colors.confidence-low}'
    foreground: '{colors.warning-foreground}'
  field-flag-box:
    border: '2px solid {colors.flag}'
    outline: '1px solid {colors.flag-halo}'
    background: '{colors.flag-fill}'
  field-flag-box-selected:
    border: '4px solid {colors.flag}'
    outline: '1px solid {colors.flag-halo}'
  focus-ring:
    outline: '2px solid {colors.ring}'
    outlineOffset: 2px
  masked-value:
    typography: '{typography.numeric}'
  status-pill-posted:
    background: '{colors.success}'
    foreground: '{colors.success-foreground}'
    radius: '{rounded.full}'
  status-pill-admin:
    background: '{colors.warning}'
    foreground: '{colors.warning-foreground}'
    radius: '{rounded.full}'
---

## Brand & Style

This is a working tool, not a showcase. It has two audiences with different postures:

- **Suppliers** use one page on their phone, often in a van or a warehouse. The page must feel trustworthy and effortless: one clear action, big targets, nothing to read twice.
- **Staff** (admins, finance, procurement, management and goods-in) spend long sessions in the staff app. It should feel calm, dense and exact: numbers line up, and flags stand out only where something needs a decision.

The app inherits shadcn/ui defaults wholesale, with no brand layer (Dj's decision). The only brand element is the name **Babaloo**, set as text in the header of both surfaces. No logo is used.

## Colors

- **shadcn defaults** cover all chrome, text and surfaces.
- **Success (`#15803D`)** is used only on the "Posted" status and on the supplier's "Received" confirmation. It means *done, nothing to do*.
- **Warning (`#B45309`, also as `confidence-low` so the badge can be retuned on its own)** is used only on the "In admin queue" status and on low-confidence badges. It means *a person needs to look*.
- **Flag (`#DC2626` outline, 8% fill, with a 1px white `flag-halo`)** is used only for the boxes drawn on invoice images around flagged fields. The halo keeps the box visible on any photo (WCAG 1.4.11). It is never used on buttons or text.
- **Destructive (`#B91C1C`, pinned rather than inherited, 6.47:1 with white text)** is used for the Reject action and for blocking reason chips, such as a bank-details change. Blocking chips also carry an icon.

Measured contrast: white text on success is 5.02:1 and on warning 5.02:1. The flag outline is 4.83:1 on white and 4.39:1 on `#F4F4F5`. Success-colored text is used only at 16px or larger, together with its label.

Avoid:
- more than one status color in a screen region;
- any use of color on the supplier page beyond primary and success.

## Typography

The shadcn ramp is inherited. Two roles are added:

- **`body-supplier`** makes all supplier-page body text at least 16px, so iOS doesn't zoom on input and the text stays readable outdoors.
- **`numeric`** uses tabular figures for every amount, quantity, date and confidence value in the staff app, so columns align.

Amounts are right-aligned in tables.

## Layout & Spacing

- **Supplier page:** a single column with a `{spacing.supplier-gutter}` side margin, and no max width on screens narrower than 480px. The primary action sits in the lower half of the screen, within thumb reach.
- **Staff app:** a sidebar on screens of 1024px and wider, with content up to full width, since tables are dense. The admin item detail is a two-pane layout: the image on the left (about 55%) and the fields on the right.
- **Goods-in screen:** uses the supplier-page layout rules, because it runs on a phone or tablet at the dock.
- **Tap targets:** every interactive element is at least `{spacing.tap-min}`.

## Elevation & Depth

Inherited from shadcn. The only added depth is the image viewer in the admin item detail. It sits on the `muted` surface so a white invoice photo doesn't blend into the page.

## Shapes

Inherited from shadcn. Pills (`{rounded.full}`) are used only for status pills and reason chips.

## Components

These shadcn components are used unchanged: `Button`, `Card`, `Table`, `Dialog`, `Sheet`, `Tabs`, `Badge`, `Input`, `Select`, `Textarea`, `Toast`, `Skeleton`, `Alert`, `DropdownMenu`, `Tooltip`. Behavioral-only components (Quality check, Delivery picker, Reminder banner, Queue table, Image viewer, Field list, Admin actions, Bank-change panel, Evidence list, Alternatives list, Supplier reference, Chart, Status labels) use these visuals unchanged; their behavior is in `EXPERIENCE.md`.

Added or overridden:

- **Capture button:** the supplier page's single primary action. Full width, at least 56px tall, with an icon and a label.
- **Reason chip:** one per admin-queue reason, labelled with the plain-language name from `EXPERIENCE.md`, never the code. The blocking variant is used for `BANK_CHANGED` and `SUPPLIER_ID_MISMATCH`.
- **Confidence badge:** shown next to any extracted field with confidence below 98%, with the value (for example "91%") in `{typography.numeric}`.
- **Field flag box:** a red outline with a white halo, drawn over the invoice image at a flagged field's bounding region, with a numbered tag that matches the field list. When selected, the stroke widens to 4px, so selection doesn't rely on color alone.
- **Focus ring:** `{components.focus-ring}` on every interactive element, never removed.
- **Masked value:** admins see bank account numbers as `•••• 4821`, in `{typography.numeric}`, with a **Show** control.
- **Status pills:** "Posted" in success, "In admin queue" in warning, and the other statuses as a shadcn outline badge.

## Do's and Don'ts

| Do | Don't |
| --- | --- |
| Inherit shadcn for anything not listed here | Restyle shadcn components ad hoc |
| Pair every status color with a text label | Use color alone to show a state |
| Keep the supplier page to one primary action per screen | Put tables, extracted fields or reasons on the supplier page |
| Use tabular figures for every number in the staff app | Mix proportional and tabular figures in one column |
| Use design tokens as CSS variables (`coding-style.md` rule 17) | Hard-code colors, sizes or spacing in components |
