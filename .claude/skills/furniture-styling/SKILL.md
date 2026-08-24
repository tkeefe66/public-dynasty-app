---
name: furniture-styling
description: Use when writing or changing any UI in web/ — a new screen, component, empty state, table, chart, form, or button. Also use when a design decision needs the house rule, when picking a radius, shadow, colour or font size, when a table needs row dividers, when deciding what a row becomes on a phone, or when tests/furniture-rules.test.ts fails. Also use when mocking up UI variants before porting them, or when a specimen page renders in the wrong face, the wrong theme, or with no tokens at all.
---

# Furniture — how UI gets built in this repo

Supersedes `agate-styling`. **Agate is retired**: monochrome newsprint, Archivo 900
uppercase, 26px lockstep, zero radius, a striped ground that *was* the divider. Any
rule you find phrased that way is Agate's and no longer applies. Furniture is
cobalt `#2f42ff`, Bricolage Grotesque in **mixed case**, 40px pitch, 16px radius,
one elevation, solid panels.

Values live in `.design/` and nowhere else — **REQUIRED BACKGROUND:**
`design-system-sync`. `.design/SKILL.md` is the rule list of record;
`.design/guidelines/DESIGN.md` still describes Agate and will mislead you.

## Read this first: the port is COMPLETE

Every file under `web/{app,components,lib}` is Furniture and the drift guard runs
at full strength over all of them — `UNSCOPED` in
`web/tests/furniture-rules.test.ts` is empty. `web/components/agate/` is deleted;
the guard's `retired-primitives` rule is a tripwire matching any `agate/*` import,
so a revert or a paste out of git history fails the build. **Write Furniture
everywhere. There are no unported neighbours left to match.**

Two lessons from that port worth keeping, because both produced a green guard
that was checking nothing:

- The guard's `walk()` resolves against the **repo root**, not vitest's CWD. When
  it resolved wrong, `readdirSync` threw, the `catch` swallowed it, and every rule
  passed over zero files. There is now a "has something to check" assertion that
  fails when a non-empty scope yields no files — keep it.
- **A green guard only covers the rules it has.** An `adhoc-size` rule was missing
  for the entire port, so 52 off-scale `text-[Npx]` values survived in 16 files
  with everything green. Before trusting a pass, ask what the guard does *not*
  look for.

## What changed, and what did not

**Survived** — these four still hold, unchanged: no colour on data; **any headline
figure must equal the rows beneath it** (a margin is a margin, never one side's raw
figure — broken four times in this repo's history, and the one rule with no
exceptions); franchise colour is identity, never ranking; **never render "KTC"** —
it is *Trade Value*, always.

**Died with Agate:** zero radius · zero shadow · "the ruled ground is the divider"
· uppercase section headings.

## The five that break things

1. **A solid panel has no stripe, so it must draw its own row rules.** Every table
   needs an explicit `border-top: 1px solid var(--rule)` between rows. Most
   commonly missed line in the system, and `divide-y` — banned under Agate — is
   now the right shape. The guard's `row-rules` rule inverted with it.
2. **Figures reconcile.** See above. No exceptions.
3. **Colour never carries information that is not also in the figure or the sort
   order.** Bars may be `--pos-bar`/`--neg-bar`; chart series may carry franchise
   identity via `--id-N-line`.
4. **Never render "KTC".**
5. **On mobile an entry becomes a card, not a row.** Do not solve narrow layouts
   with border logic — a card's edge *is* the entry boundary. `Panel` is the
   desktop body, `CardList`/`EntryCard` the narrow one, and every interaction
   (sort, filter, collapse) must drive **both**.

## Token traps that each cost a round

- **A `-strong` tone is about the GROUND, not the component.** On `--bg` or any
  wash use the `-strong` half (`{stamp,pos,neg,warn}-strong`); the base tone is
  tuned for white `--surface` and drops below AA on the page ground.
- **Never `-ink` on a wash.** `--stamp-ink` is the ink for the *solid* cobalt fill
  (white). On `--stamp-wash` it measures 1.13:1. Text on a wash takes `-strong`.
- **Never an alpha of a reversed ink.** A second line on cobalt is
  `--stamp-ink-dim`; `rgba(255,255,255,.72)` is 3.97:1 at 9px and small reversed
  type gets no large-text exemption.
- **A fill ramp is not a stroke ramp.** `--id-1..6` are fills (chips, avatars,
  identity edges). Any polyline, axis stub, scatter mark or connector takes
  `--id-N-line` — as 1–3px lines on white only two of the six fills clear the 3:1
  WCAG 1.4.11 asks of a graphical object, so a plot's *winning* series was once its
  faintest line.
- **44px minimum tap target**, 26px absolute floor for an inline glyph button.
- **The mark must be inlined**, never `<img src>` — an `<img>` is its own document,
  so `currentColor` resolves against nothing and the mark renders black.
  `favicon.svg` is a deliberately different drawing.

## Reuse, don't invent

22 primitives in `.design/components/{ledger,data,controls,feedback}/`, each with a
`.prompt.md` holding its call shape and its own gotcha. Read the prompt, not just
the JSX. The app's own implementations live in `web/components/furniture/`.

The "Replaced" column below names **deleted** components — `web/components/agate/`
is gone. They are listed only so that a stale reference in an old doc, a comment,
or a git-history paste resolves to its Furniture successor instead of sending you
looking for a file that no longer exists.

| Need | Furniture primitive | Replaced |
|---|---|---|
| A ledger container | `Panel` | `Ruled` / `LedgerSection` |
| One row | `Row` (`head` · `body` · `total` · `mine`) | `Rule` |
| A row on a phone | `EntryCard` + `CardList` + `MetaLine`/`Meta` | — (new; the decided mobile answer) |
| Section heading | `SectionHead` — **mixed case, never uppercase** | `CardHead` |
| League masthead | `StampBand` | `Nameplate` |
| Every number | `Figure` | — |
| A magnitude bar | `Bar` — **may carry colour now** | `InkBar` |
| Single-select (years, metrics, views) | `SegmentControl` — the ONE dialect | `MonoRun` |
| Primary action | `Button` — one primary per view | — |
| "Out to a bigger view" | `MonoLink`, never a second button | — |
| One of 19 marks | `Mark` — **stroked**, 1.6 weight, round joins | `Icon` (cut marks) |
| Grade letter | `GradeLetter` (uses the strong pair) | — |
| Empty / error / not-found | `StateMessage` | — |
| Loading | `IndeterminateBar`, one per view | — |
| A trade ruling | `RulingStamp` | — |

## `Row` grammar

`cols` is a `grid-template-columns` string repeated **verbatim** on the head row and
every body row — that repetition *is* the column contract, and a mismatch is the
most common ledger bug.

- `head` — sunk ground, mono uppercase label type, **44px** so a `SortButton` fits.
- `body` — `border-top: 1px solid var(--rule)`.
- `total` — sunk ground, `2px solid var(--ink)` top rule. It must **name** what it
  totals when the rows are an abbreviation, and it must be **recomputed from the
  visible set** when a filter changes. Filtering a ledger without recomputing its
  total shipped once.
- `mine` — a 6% stamp wash and an inset stamp bar. Stamp because "you" is the
  product speaking, not a data value.
- **Never nest a `<button>` inside a row that is already a link.**

## Shape, elevation, stamp

One sanctioned value each; a second is how a system starts drifting.

- **Radius:** `--radius` 16px on panels, cards, heroes · `--radius-sm` 8px on
  controls, inputs, inline chips · `--radius-pill` on segmented controls and filter
  chips. Zero stays on rules and figures. No fourth.
- **Elevation:** `--shadow` resting, `--shadow-lift` lifted. A panel reads as laid
  on the page, not floating. No hover lift on a row.
- **Stamp is a GROUND you reverse type out of**, never a word painted on paper, and
  it never touches a figure, bar, chart series, or grade letter. Five slots: the
  primary button fill, an active segment or tab cell, a link, the focus ring, and
  the "you" marker. A sixth means naming the component in `.design/tokens/stamp.css`.

## Type

Bricolage Grotesque at 700/800 in **mixed case** — the change of case matters as
much as the change of face; Archivo 900 uppercase is what read as shouting at
consumer scale. Geist sets prose. Geist Mono sets **every** figure and label, always
`tabular-nums`, and keeps its uppercase letterspacing — a mono label is the one
place caps still earn their keep. Seven sizes (`--text-nameplate` 44 → `--text-label`
8.5) and there is no eighth: a size not on the list is a size someone eyeballed.
Nameplates step by **character count**, computed server-side, never measured in the
browser.

## Voice (unchanged from Agate — still binding)

Empty states say what *will* appear here, never that something is missing. Errors
name the condition in a mono kicker, then plain words: "Not you — us." Never
"Oops." Sentence case in prose; UPPERCASE only in Geist Mono. Two glyphs ever, 🏆
and 🚽, on trophy lines only. The five metrics are a fixed vocabulary in a fixed
order: **Trade Value · Total Points · Regular Season Points · Playoff Points ·
Toilet Bowl Points**.

## What is not drawn

**`.design/ui_kits/` DOES NOT EXIST in the installed package**, despite
`.design/readme.md` and `.design/SKILL.md` both citing it repeatedly ("17 screens
in `ui_kits/furniture/`", "`phones.html` is the contact sheet",
`ui_kits/furniture/icons.js`). Every one of those references is dead. Do not brief
an agent against that path. The nineteen marks actually live in
`.design/components/controls/fx-icon-paths.js`.

What you DO have is four copyable screens in `.design/templates/`:
`dashboard/`, `franchise/`, `trade/`, `mobile/`. Each is a `.dc.html` you can read
directly, and they specify **composition** — which panels, in what order, with
what column contract. Tokens and primitives are vocabulary; the templates are the
sentences. Porting the vocabulary without opening these is how a screen ends up
technically compliant and still wrong.

What has **no** Furniture drawing at all is SVG geometry: `ProductionTimeline`,
`CareerArc`, and the plots inside `RosterHealthTab`. A radius-and-elevation pass
does not touch an SVG. Those may be **themed** to Furniture tokens (stroke ramp
`--id-N-line`, `--rule` axes, `--dim` labels), but the geometry itself needs
drawing, and inventing one here is out of scope — ask.

## Mocking up variants before you port them

Judging density, weight or contrast in system-ui is judging a different design. A
specimen page carries the real tokens and the real faces or it is not evidence.

Publish it as an **Artifact**. Its CSP blocks every external host, so a linked font
URL fails *silently* to system-ui — inline the faces as base64 `@font-face` data
URIs instead:

```bash
cd .design/assets/fonts
{ printf '<style>\n'
  for f in geist-latin-var:Geist geist-mono-latin-var:"Geist Mono" \
           bricolage-grotesque-latin-var:"Bricolage Grotesque"; do
    file=${f%%:*}; fam=${f#*:}
    printf '@font-face{font-family:%s;font-weight:100 900;font-display:swap;src:url(data:font/woff2;base64,' "$fam"
    base64 -i $file.woff2 | tr -d '\n'
    printf ') format("woff2");}\n'
  done
  printf '</style>\n'; } > /tmp/fonts.html   # ~246KB, vs a 16MB page limit
```

The three `-latin-var` builds are 184KB together. The `-latin-ext-` builds only
matter for accented copy — skip them.

Four things that are specific to this package:

- **Copy token VALUES into the page.** An artifact cannot `@import` from disk. Five
  files, in the order `web/app/globals.css` uses: fonts, colors, typography,
  rhythm, stamp. **`base.css` and `legacy-agate.css` are not among them** — base is
  the design system's own element reset (Tailwind's preflight owns that in the app),
  and legacy-agate is the retired predecessor scoped to `[data-theme="agate"]`.
- **A dark specimen is a wrapper, not a second page.** `colors.css`, `stamp.css` and
  `rhythm.css` each double their dark selector to the element form
  `[data-theme="dark"][data-theme]` for exactly this. `<div data-theme="dark">`
  inside a light page renders a correct dark specimen.
- **The artifact viewer has three theme states**, and the package ships only one of
  them. Add the other two yourself: bare `:root` for light,
  `@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { … } }`,
  and `:root[data-theme="dark"]`. Miss the media query and every viewer on the
  default "system" setting reads light type on a dark ground.
- **Make the specimen work.** A filter you cannot toggle cannot be judged; one
  delegated click handler flipping a `data-on` attribute is enough. Then hold the
  content identical across variants and state the measurement (px of chrome before
  the data) — a mockup that changes the copy alongside the chrome is not a
  comparison.

## When a screen resists the vocabulary

Name the missing component and stop — ask. Adding an entry to the guard's `except`
list is not the answer; a new named primitive, added to `.design/` through design
review, might be.
