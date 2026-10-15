# Workspace design system

**Plain-language summary.** This guide records how the workspace looks and why, so that every screen follows the same decisions. The interface is a ledger on a desk: warm paper, ink, thin rules, and one wine-red stamp for the main action and the brand. A state (done, running, to-do, failed) is always shown by a small mark in its own colour, never by the action colour, so that what you can do never looks like what has happened. The values below are the tokens in `ui/src/styles.css`; the rules that forbid generic patterns are in section 9 of `CLAUDE.md`.

## 1. Direction

- **Who and what.** A bookkeeper or the owner opens the workspace to see which work packages need them, open the next step and clear to-dos. Later, clients may see it too.
- **Feel.** Dense and calm, like a well-kept ledger: much information per screen, a clear order, and little decoration. The structure stays: a dark side rail, a light canvas, one accent colour.
- **Screens.** Desktop and laptop only, 1366–1920 px wide, mouse and keyboard. Light and dark themes; Hungarian by default, English on request.

## 2. Colour tokens

Every colour in a rule comes from a token. Light values first, dark values in `:root[data-theme="dark"]`.

| Token | Light | Dark | Use |
|---|---|---|---|
| `--canvas` | `#f4f3f0` | `#161518` | page background (warm paper) |
| `--paper` | `#fff` | `#1e1d20` | tables, cards, inputs |
| `--soft` | `#faf9f7` | `#222124` | table header, row hover |
| `--hover` | `#f1efeb` | `#29282c` | hover on neutral controls |
| `--ink` / `--ink-2` | `#1f1d21` / `#47444b` | `#edebef` / `#c7c4cb` | main and secondary text; the focus ring |
| `--muted` / `--faint` | `#67636c` / `#9a969e` | `#9d99a3` / `#6e6a73` | metadata; disabled and decorative marks only (not body text) |
| `--line` / `--line-strong` / `--line-soft` | `#dedbd5` / `#c9c5be` / `#ebe9e4` | `#343238` / `#46434b` / `#2a292d` | borders, control borders, quiet dividers |
| `--tint` / `--tint-line` | `#efede9` / `#dcd8d1` | `#2c2b30` / `#3e3c43` | a selected or pressed surface (neutral) |
| `--rail` | `#1f1d20` | `#0e0d10` | side rail |
| `--accent` / `--accent-hover` | `#a33f53` / `#8e3547` | `#d9798d` / `#e48fa1` | the main action of a view and the brand, nothing else |
| `--error` (+ `-tint`, `-line`) | `#c0362c` | `#ff8577` | failed, invalid, destructive |
| `--warn` (+ `-tint`, `-line`) | `#866100` | `#e4c063` | something is off but nothing failed |
| `--todo` (+ `-tint`, `-line`) | `#b0500e` | `#f0a463` | a person has to act (open to-dos) |
| `--ok` (+ `-tint`, `-line`) | `#2c7651` | `#74cf9f` | done, approved |
| `--run` (+ `-tint`, `-line`) | `#2d5c9e` | `#8fb5ee` | running, queued, a selection |

Every text pair above reaches at least 4.5:1 contrast in both themes (the lowest is to-do text on its own tint, 4.65:1).

## 3. Type, space, shape, depth

- **Typeface.** IBM Plex Sans for text, IBM Plex Mono for codes and identifiers (self-hosted `@fontsource` packages, weights 400, 500, 600 and Mono 400). Amounts, dates and counts use tabular figures in the text face; monospace is not used for amounts.
- **Type scale** (about 1.2 per step): `--fs-xs` 12 px (labels, table headers, metadata) · `--fs-sm` 13 px (the base: body, tables, controls) · `--fs-md` 15 px · `--fs-lg` 18 px (section headings) · `--fs-xl` 22 px (page title) · `--fs-2xl` 28 px (a single large figure). Nothing below 12 px. Hierarchy comes from weight (400, 500, 600) and colour as much as from size; headings use slightly negative tracking and balanced wrapping.
- **Space.** A 4 px grid: `--sp-1` 4 · `--sp-2` 8 · `--sp-3` 12 · `--sp-4` 16 · `--sp-5` 20 · `--sp-6` 24 · `--sp-8` 32 px. Table cells 7 × 8 px; the page gutter 24 px.
- **Radii.** Four values: `--r-sm` 4 px (chips, counts, small markers' frames) · `--r-md` 6 px (buttons, inputs) · `--radius` 10 px (tables, cards, popovers) · `--r-full` (pills and dots). Small state markers are square-cornered.
- **Depth.** Borders carry the structure; only overlays (popovers, menus) get a shadow. No decorative gradients, no glass, no glow.
- **Motion.** Button press scales to 0.97 in 100 ms; colour changes 120 ms; nothing moves on its own. `prefers-reduced-motion` turns transitions off.

## 4. Components

- **Buttons.** `.primary`: solid accent, one per view, for its main action. `.secondary`: paper with a strong hairline border, ink label. `.quiet`: text only. `.small-btn`: 28 px high, 12 px label. All at least 32 px high (28 px for small ones).
- **Run buttons.** Every button that starts a run — trial, live, rerun — carries the run's cost cap after a thin divider (`.spend`, for example "≤ 1.71 USD", the sum of the services' caps), because a trial calls the same paid services as a live run; the full sentence is in the tooltip and the mark is hidden from screen readers so the button keeps its name. A run that can spend nothing carries no mark. The recommended run is the one solid button; otherwise the live run, whose result can be released, has a firm ink border.
- **State mark** (`.status`, `.s-<state>`). A 7 px mark plus a plain label: done ● green, running ● blue, queued ○ blue ring, to-do ● orange (orange label), failed or cancelled ■ red. The header's worker badge (`.pill`) uses the same marks; a warning is an amber ◆.
- **Attention count** (`.count-alert`). A count above zero of to-dos or runs to supersede: orange figure on its tint, tabular; zero is shown muted.
- **Stage track** (`.track`). Three short segments before a package's next step — Processing, Review, Result — filled up to where the package stands; the current segment takes the state's colour (running blue, to-do orange, failed red; all green when released). It is decorative (`aria-hidden`): the step's text says the same in words.
- **Links.** Ink with a quiet underline; accent on hover. In table cells the underline appears on hover only.
- **Language switch.** One segmented control (HU / EN), not two separate buttons.
- **Side rail.** Dark, 120 px; icon above a 12 px label; the current item is a lighter block (no stripe on its side).
- **A package's page.** A compact header (18 px title, the summary and the workflow it belongs to on one small line, the owner and the next step on the right) and the three stages as one 40 px bar: number, name and state on one line; the open stage is a neutral tint with an ink underline.
- **Review workspace.** The run picker has a fixed width and the keyboard help takes the rest of the toolbar row (in full in its tooltip). The panes measure where they start and end just above the bottom of the screen, so on a 1366 × 768 laptop the page image, the first fields and the save button show without scrolling the page. The selected item and the active field are cards with a firm border, never a side stripe.
- **Result section.** One row for the run picker (fixed width, its label for screen readers only), the views and the full Excel package. Under it the release line: the shown run's state as one line with its own state mark — released ● green, awaiting approval or open to-dos ● orange, still running ● blue, a trial result neutral — and its detail in muted text; never a tinted banner. The approval sits at the end of that line and is the solid main action only when it can be given. A view may hide columns a person seldom reads by default (the column menu shows them, and the full Excel package always has them).
- **Confidence colours on the page image.** Confident green, to check orange (a person's to-do), likely wrong red, entered by a person blue, unknown grey. The scanned page stays white paper in the dark theme too, so its frames keep the light-theme values there.

## 5. Tables

- The header may wrap onto two lines; the filter icon floats over the header's corner and appears on hover, on focus and while a filter is active.
- A date-time is drawn as its date and its time, so a narrow column puts the time under the date; its text stays one value.
- Words wrap at spaces; only a name-like column may break inside a long unbroken value (a name, a file name, a path, an e-mail address). The dataset marks such columns (`wrap: "anywhere"`, by key in `jav/datasets.py`), so one long address cannot widen a whole table.
- A dataset can give its own columns a minimum width (`.dt-table[data-dataset="…"] th[data-col="…"]`). The work package list's default columns fit 1440 px and 1366 px without sideways scrolling.
- A width a person dragged is kept per browser; the column menu resets it.

## 6. Checking a screen

Before a changed screen is accepted: screenshots before and after in light and dark at 1366 × 768 and 1440 × 900; no sideways scrolling of the page or of a default table; no cell taller than four lines on default columns; no text below 12 px, no colour outside the tokens, no side stripe; the UI tests, the typecheck and the translation check pass.
