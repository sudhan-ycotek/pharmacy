# Pharmacy System UX & Data Model Redesign — Design

## Context

The first version of the pharmacy system (built and merged earlier) is functionally complete but was intentionally bare — plain unstyled HTML, freeform text fields for packaging units, browser-native dialogs, no visibility into who made a sale. Now that the core is working, the owner wants it to actually be usable day-to-day by a non-technical cashier: clear labels, guided input instead of freeform typing, a keyboard-first sales flow (mouse movement is too slow for busy hours), and a visual design that looks like a real point-of-sale tool rather than a bare form. This spec covers that redesign — visual system, category-driven packaging model, sales flow, and a handful of smaller gaps (seller attribution, password management, custom dialogs).

## Visual Design System

Reference direction approved by the owner: [mockup](https://claude.ai/code/artifact/d61a730c-7700-4e4a-8a75-a61720054d48) — a clean white dashboard with icon sidebar, stat cards, quick-action cards, and a data table with thumbnails.

**Tokens** (light theme shown; a dark variant is defined via the same CSS variables under `prefers-color-scheme: dark`, since it costs nothing extra once the palette is token-based):

```
--bg: #f4f6f3        --surface: #ffffff     --border: #e1e6e0
--text: #191d1a      --text-muted: #64716a
--accent: #1f6f54     --accent-soft: #e1efe7   (pharmacy teal-green, used for active nav/primary actions/links)
--good: #2e7d4f / --good-soft: #e5f3ea         (in-stock, completed)
--warning: #a8710b / --warning-soft: #fbf0dd   (low stock)
--critical: #b3261e / --critical-soft: #fbe9e7 (voided, errors)
```

**Type**: native OS UI font stack (`"Segoe UI", -apple-system, "Helvetica Neue", Arial, sans-serif`) for all text — deliberate choice since this runs on one specific Windows PC and should feel like it belongs there, not like a downloaded web app. All numeric columns (prices, quantities, stock counts, dates) use a monospace stack with `font-variant-numeric: tabular-nums` for POS-terminal-style column alignment.

**Layout**: fixed-width icon+label sidebar (Dashboard, POS, Products, Sales History, Staff Accounts, and a Settings section with Change Password), a top bar per page with an `<h1>` and a one-line description of what the page is for, stat-card rows, quick-action cards, and tables with thumbnail images + tabular numeric columns + status pills (colored dot + label, using the semantic colors above — not the accent color).

This system replaces `static/style.css` entirely and applies to every template — no page ships without it.

## Data Model: Category Drives Packaging Structure

Replace `medicines.category` (free text) with `medicines.packaging_type`, constrained to exactly two values: `box_file` or `bottled_other`. The category picked at Add Medicine time determines the packaging form shown — no more freeform "add a unit row" UI.

- **`box_file`**: always exactly 3 `medicine_units` rows, always named `Box`, `File`, `Tablet` (not customizable). Admin enters two conversion numbers — tablets per file, files per box — plus one price per level (Box, File, Tablet). Base unit is always `Tablet` (`qty_in_base_units = 1`), matching the existing stock-in-base-units design.
- **`bottled_other`**: always exactly 1 `medicine_units` row. Admin picks a unit type from a preset list (Bottle, Tube, Sachet, Pack, Strip, Jar, or "Other" with a custom text field) + 1 price. That unit is the base unit.
- New `medicine_units.is_sellable` column (boolean): `1` for every row except `box_file`'s `Box` row, which is `0`. Box exists only for stock intake (adding "1 box" converts to its tablet count, unchanged from today) — it is never offered as a sale option. This directly fixes the "don't sell at box level" requirement without inferring it from row position.

No data migration path is needed — the app has no real production data yet (still pre-deployment), so this ships as a fresh schema.

## Add Medicine Form

- Name (text), Category (select: Box/File | Bottled/Other) — selecting toggles the fields below via JS, no reload.
- Box/File selected: "Tablets per file" (number), "Files per box" (number), and Price per Box / Price per File / Price per Tablet (three number inputs). A live text preview updates as the admin types: "1 box = 12 files = 240 tablets."
- Bottled/Other selected: unit-type select (Bottle/Tube/Sachet/Pack/Strip/Jar/Other — "Other" reveals a text input for a custom name) + one price input.
- Low stock threshold (number), with a hint clarifying it's counted in base units (tablets, or the bottled unit).
- Photo: unchanged QR-from-phone flow from the first version.

## POS / New Sale Flow (keyboard-first)

1. Search box auto-focused on page load. Typing filters medicines live; each result row shows a photo thumbnail (fallback icon if none set), name, and category — enough for a non-medical cashier to recognize the item on sight.
2. Arrow keys move the highlighted result; Enter opens a quantity modal for that medicine.
3. The modal offers only sellable units (`is_sellable = 1`) — File and Tablet for `box_file` medicines, the single unit for `bottled_other`. Never Box. Tab or arrow keys switch which unit is selected; a number input takes the quantity. Enter adds the line to the running bill and returns focus to the search box for the next item.
4. The bill is a table below the search box (tabular-aligned numbers), each line removable.
5. A single shortcut key (F2) finalizes the sale from anywhere on the page — a full transaction is completable without touching the mouse.
6. Errors (insufficient stock, invalid quantity, etc.) surface as an inline banner inside the modal or above the bill — never a browser `alert()`.

## Sales History

- New page listing sales: date/time, **sold by** (the seller's username — join to `users` on `sales.user_id`), total, status (Completed/Voided), and a link to the receipt. Reachable from the sidebar.
- Admins see every sale; staff see only their own — enforced server-side by filtering the query on `user_id`, not by hiding rows client-side.
- The receipt page itself also shows "Sold by: <username>."
- Void remains admin-only, reachable from the receipt page, and now confirmed via a custom modal instead of the browser's `confirm()`.

## Password Management

- **Change own password** (available to both roles, reachable from a "Change Password" link under Settings in the sidebar): current password + new password, verified against the current hash before saving.
- **Admin resets a staff member's password** (Staff Accounts page, admin only): a "Reset Password" action per staff row opens a modal for a new password — no need to know the old one, since the admin is already authenticated and this is their own staff.

## Dialogs & Page Descriptions

- Every native `alert()`, `confirm()`, and `prompt()` in the app is replaced with a styled modal component matching the visual design system (used for: sale-line quantity entry, void confirmation, remove-staff confirmation, sale-finalize errors, reset-password confirmation).
- Every page's top bar carries a one-line description of the page's purpose beneath its `<h1>` (shown in the approved mockup) — e.g. Dashboard: "Overview of today's sales and stock that needs attention." POS: "Search for a medicine, add it to the bill, then finalize to print a receipt." Products: "Manage your medicine catalog, stock, and pricing." Sales History: "Browse past sales; admins can void one to restore its stock." Staff Accounts: "Add, remove, or reset passwords for staff logins."

## Out of Scope (unchanged from the first version)

No batch/expiry tracking, no supplier tracking, no full sales search/filter/reporting beyond the plain list above.
