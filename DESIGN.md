---
version: alpha
name: Port Dashboard
description: Cyberpunk CRT-terminal aesthetic for a local port control center — deep teal backgrounds, cream foregrounds, amber as the single high-emphasis accent.
colors:
  background: "#041c1c"
  surface: "#062a2a"
  surface-elevated: "#083232"
  foreground: "#FFE6CB"
  foreground-muted: "rgba(255, 230, 203, 0.55)"
  foreground-dim: "rgba(255, 230, 203, 0.35)"
  primary: "{colors.background}"
  secondary: "{colors.foreground-muted}"
  tertiary: "{colors.accent}"
  neutral: "{colors.surface}"
  on-primary: "{colors.foreground}"
  on-tertiary: "{colors.on-accent}"
  accent: "#FFBD38"
  accent-glow: "rgba(255, 189, 56, 0.35)"
  border: "rgba(255, 230, 203, 0.15)"
  accent-glow-color: "#FFBD38"
  border-strong: "rgba(255, 230, 203, 0.40)"
  success: "#10B981"
  info: "#0EA5E9"
  warning: "#F59E0B"
  danger: "#EF4444"
  on-accent: "#1A0F00"
typography:
  display:
    fontFamily: "JetBrains Mono"
    fontSize: 1.5rem
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "0.05em"
  h1:
    fontFamily: "JetBrains Mono"
    fontSize: 1.5rem
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "0.05em"
  h2:
    fontFamily: "JetBrains Mono"
    fontSize: 1.125rem
    fontWeight: 700
    lineHeight: 1.25
    letterSpacing: "0.04em"
  body:
    fontFamily: "system-ui"
    fontSize: "0.875rem"
    lineHeight: 1.5
  body-mono:
    fontFamily: "JetBrains Mono"
    fontSize: "0.8125rem"
    lineHeight: 1.45
  label-caps:
    fontFamily: "JetBrains Mono"
    fontSize: "0.6875rem"
    fontWeight: 700
    letterSpacing: "0.10em"
  metric-value:
    fontFamily: "JetBrains Mono"
    fontSize: "0.75rem"
    fontWeight: 600
    lineHeight: 1.3
rounded:
  none: 0
  sm: 2px
  md: 4px
  lg: 6px
  full: 9999px
spacing:
  xs: 4px
  sm: 8px
  md: 12px
  lg: 16px
  xl: 24px
  2xl: 32px
  3xl: 48px
elevation:
  glow-amber: "0 0 8px rgba(255, 189, 56, 0.45)"
  glow-amber-lg: "0 0 16px rgba(255, 189, 56, 0.55)"
  card-rest: "0 0 0 1px rgba(255, 230, 203, 0.08)"
  card-hover: "0 0 0 1px rgba(255, 230, 203, 0.25)"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.on-accent}"
    rounded: "{rounded.sm}"
    padding: "8px 16px"
    typography: "{typography.label-caps}"
  button-ghost:
    backgroundColor: "{colors.background}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.sm}"
    padding: "8px 16px"
    typography: "{typography.label-caps}"
  button-ghost-active:
    backgroundColor: "{colors.foreground}"
    textColor: "{colors.background}"
    rounded: "{rounded.sm}"
    padding: "8px 16px"
    typography: "{typography.label-caps}"
  tab-inactive:
    backgroundColor: "{colors.background}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.sm}"
    padding: "8px 16px"
    typography: "{typography.label-caps}"
  tab-active:
    backgroundColor: "{colors.foreground}"
    textColor: "{colors.background}"
    rounded: "{rounded.sm}"
    padding: "8px 16px"
    typography: "{typography.label-caps}"
  card-surface:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.md}"
    padding: "16px"
  card-status-running:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.success}"
    rounded: "{rounded.md}"
    padding: "12px"
  card-status-external:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.info}"
    rounded: "{rounded.md}"
    padding: "12px"
  card-status-warning:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.warning}"
    rounded: "{rounded.md}"
    padding: "12px"
  card-status-danger:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.md}"
    padding: "12px"
  badge-label:
    backgroundColor: "{colors.background}"
    textColor: "{colors.accent}"
    rounded: "{rounded.sm}"
    padding: "2px 6px"
    typography: "{typography.label-caps}"
  metric-row:
    backgroundColor: "{colors.background}"
    textColor: "{colors.foreground-muted}"
    rounded: "{rounded.sm}"
    padding: "8px 12px"
  metric-row-elevated:
    backgroundColor: "{colors.surface-elevated}"
    textColor: "{colors.foreground-muted}"
    rounded: "{rounded.sm}"
    padding: "8px 12px"
  input-field:
    backgroundColor: "{colors.background}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.sm}"
    padding: "8px 12px"
  input-field-focused:
    backgroundColor: "{colors.background}"
    textColor: "{colors.accent}"
    rounded: "{rounded.sm}"
    padding: "8px 12px"
  glow-indicator:
    backgroundColor: "{colors.accent-glow-color}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.full}"
    padding: "8px"
---

## Overview

Port Dashboard is a local control panel for developers running multiple services on one machine.
The interface reads like a **CRT terminal from an alternate-1985**: deep teal backgrounds,
warm cream foregrounds, a single amber accent driving every interactive signal.
The mood is calm-but-alert — a ship engineer's console, not a marketing landing page.
Every affordance is mono-spaced and uppercase to reinforce that this is an **engine room**, not a product UI.

## Colors

- **Background ({colors.background}):** Deep ink-teal. The page itself. Never use pure black —
  the slight green shift is what gives the cream foregrounds their phosphor-glow quality.
- **Surface ({colors.surface}):** One step lighter than background. Default card / panel fill.
- **Foreground ({colors.foreground}):** Cream. Headlines, body text, primary content. Never white —
  cream is warmer on the eyes against deep teal and reads as "vintage phosphor."
- **Accent ({colors.tertiary} = {colors.accent}):** **Amber. The only high-emphasis color in the system.**
  Use for: primary buttons, active-tab fill, focused-input caret, critical status indicators,
  the brand mark "P". If something is amber, the user can act on it.
- **Success ({colors.success}) / Info ({colors.info}) / Warning ({colors.warning}) / Danger ({colors.danger}):**
  Reserved exclusively for **process-status dots and text** in the port list.
  Never use these for buttons or typography.
- **Border ({colors.border}) / Border-strong ({colors.border-strong}):** Hairline card and divider
  borders. 15% / 40% opacity over the cream foreground — these read as "edge of phosphor"
  rather than "drawn line".

## Typography

Two families, strict roles:

- **JetBrains Mono** — every headline, label, metric, button, tab, and code-adjacent element.
  The mono spacing creates the "control panel" feel and prevents UI labels from competing
  with running logs.
- **system-ui** — body prose only (descriptions, helper text). Keep usage under ~20% of
  the page; if a block is mostly prose, consider whether it belongs in a modal.

`label-caps` is the workhorse: every button, every tab, every status badge uses it.
`tracking-wider` / `tracking-widest` are encouraged on display text — they mimic the
stretched phosphor of a vintage terminal.

## Layout

Spacing follows an 8px grid; the design tolerates 12px (`md`) and 4px (`xs`) where
density matters (status rows, metric cells). Section breaks always use `xl` (24px) or
`2xl` (32px). Page max-width is implicit — the dashboard fills the viewport, no centered
container, because this is a workspace, not a doc.

## Elevation & Depth

There are **no shadows**. Depth is built from:

1. Border-only cards (`card-rest` → `card-hover`) — the border brightens, never the fill.
2. The amber glow token (`glow-amber`, `glow-amber-lg`) — applied to the brand mark,
   the active CPU/RAM bar fill, and any element that is *currently* the user's focus.
3. A fixed ambient radial-glow at the top of the viewport (`accent-glow` at 35%) —
   set once in the root layout, never per-card.

## Shapes

Corners are **sharp or barely rounded**. Use `none` (0px) and `sm` (2px) on buttons,
tabs, inputs, and badges — they should read as engineered panels, not soft cards.
`md` (4px) is the ceiling for any rounded surface. `full` is reserved for status
indicator dots only.

## Components

- **`button-primary`** is the only high-emphasis action on a screen. **At most one per view.**
  Amber fill, dark text. Reserve for "the thing the user came here to do" (Save, Start, Confirm).
- **`tab-active`** and **`tab-inactive`** use inverted contrast (cream fill / teal text → transparent / cream text).
  Active tab is the only filled tab. Inactive tabs never glow.
- **`card-surface`** is the default. **`card-status-running`**, **`-external`**, **`-warning`**, **`-danger`**
  swap the foreground color to indicate process state. The border remains the standard `border` token;
  state is communicated through the dot/badge, not a colored border.
- **`badge-label`** is the small uppercase pill used on the title-bar platform chip
  ("Windows Engine"), status filters, and security levels.
- **`metric-row`** is the label-value pair used for CPU%, memory%, uptime, IP. **`metric-row-elevated`**
  swaps to a slightly lighter fill for the currently-focused stat row.
- **`input-field` / `input-field-focused`** — focus state swaps textColor to `accent`.
- **`divider-strong` / `divider-soft`** — 1px-tall strips used as section separators.

## Do's and Don'ts

- **Do** use `{colors.accent}` for every interactive signal — buttons, active tab, focused input, focused dot.
- **Do** keep all labels uppercase with `label-caps` typography.
- **Do** use mono (`body-mono`) for any value the user will compare across rows (ports, PIDs, memory MB).
- **Don't** introduce a second accent color. If you need another emphasis, adjust opacity of `accent` or `foreground`.
- **Don't** use shadows. If you need depth, brighten the border or add the amber glow.
- **Don't** round corners above `md` (4px). The sharp aesthetic is the brand.
- **Don't** put prose in `system-ui` on more than ~20% of any view — this is a workspace, not a reader.