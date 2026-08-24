# Public Dynasty — Agate Design System

> **2026-08-13 — Furniture is the shipped system.** Everything below describing Agate as
> the current design (warm newsprint, Archivo 900 uppercase, 26px pitch, zero radius, zero
> shadow, ink-navy stamp) now describes the PREVIOUS system, preserved at
> `:root[data-theme="agate"]` in `tokens/legacy-agate.css`. The default `:root` is
> Furniture: cobalt `#2f42ff`, Bricolage Grotesque in mixed case, 40px rule pitch, 16px /
> 8px / pill radii, two elevations, and a solid panel ground where rows carry an explicit
> rule. Four rules survived the change and still hold: **no colour on data**, **figures
> reconcile with the rows beneath them**, **franchise colour is identity only**, and
> **never render "KTC" — it is Trade Value**. The rules that died with it: zero radius,
> zero shadow, "the ruled ground is the divider", uppercase section headings.
>
> Why: Agate was working exactly as specified, and the specification was the problem at
> consumer scale. See `explorations/dated-to-current.html` for the diagnosis,
> `explorations/new-frame.html` for the three directions considered, and
> `guidelines/layer1-handoff.html` for what shipping it takes.

The design system for **Fantasy Analyzer** (`dynasty.tomkeefe.ai`), a receipts-first ledger for Sleeper dynasty
leagues: every trade graded, every claim drillable. Agate is what the app looks like
after the redesign this project produced.

## Sources

Everything here was derived from real source, not from screenshots. **This project is a
faithful port of the `design_handoff_agate/` package** (mounted local folder), with one
addition of my own, clearly fenced: see `## The soul question` below.

- **Handoff package read:** `design_handoff_agate/` — `DESIGN.md` (the written system of
  record, kept here as `guidelines/DESIGN.md`), `design-system/` (tokens, 14 specimen
  cards, 18 components, 4 UI kits), `Agate System.dc.html`, `Dynasty Directions.dc.html`.
- **Live app the user pointed at:** `dynasty.tomkeefe.ai/league/9000000000000000001?year=2023`
  — this is the app **before** the Agate redesign, and is the "all white/black, no soul"
  screen in question.


- **Repo:** `github.com/tkeefe66/public-dynasty-app`, branch `main`, subtree `web/`
  (Next.js + TypeScript + Tailwind). Read at tree `7692965931cc`.
- **Live app:** `ffbdynasty.com/league/9000000000000000001`
- **In-project design record:** `Agate System.dc.html` (§01–§10, the drawn system),
  `Dynasty Directions.dc.html` (the dashboard and trade screens plus two rejected
  directions), `handoff/DESIGN.md` (the written system of record),
  `design_handoff_agate/` (the developer port package), `github.md` (screen map,
  open conflicts, sync log).

Do not assume a reader has repo access. If they do, the `## Screen map` table in
`github.md` ties each screen to the files it was built from.

## The north star

**"Agate."** The interface is a book of record, and **rules do the work that boxes do
elsewhere.** A ledger entry is one 26px rule tall; the ruled ground *is* the divider,
so no row, cell, or card carries a border. The league's own name is the masthead. Every
figure is Geist Mono with tabular numerals, and the only color on screen is a signed
number or a grade letter. Two grounds are equal: warm newsprint, and ink on slate.

This replaced "The Ledger," which was thoroughly specified but had nothing carrying it —
every surface was the same 10px hairline card, all type sat in one 11–13px band, there
was no masthead, and the one distinctive move (an Instrument Serif verdict line) appeared
on a single screen.

---

## The soul question

> "It is all white/black and has no soul. How can we fix that?"

The live site reads flat for two reasons, and only one of them is color.

**1. Nothing on it is louder than anything else.** Every surface is the same hairline card,
every figure sits in the same 11–13px band, and the league's own name is never printed at
size. Agate already fixes this and it is the larger half of the answer: a masthead in
Archivo 900, a 26px ruled ground that replaces every border, three type families with one
job each, and figures that reconcile. Ported here as shipped — do not soften it looking for
color.

**2. Agate has one sanctioned color and never spends it.** `--stamp` — now ink navy `#172a44`, the handoff's `#0f3b3a` teal having been rejected — is
permitted to back the nameplate band and the ruling stamp on paper, and the handoff noted
that no dark counterpart had been drawn. So it never gets used, and the app prints in one
ink.

**Direction B is now applied** — through the tokens, `Button`, `MonoRun`, `Ruled`, and all
four UI kits. `tokens/stamp.css` carries a one-line escape hatch back to Direction 0.

**What I added.** `tokens/stamp.css` — the drawn dark stamp (`#1e3958`, not the light value
reused, which reads as a hole in slate), plus hover/pressed/rule values so stamp can act as
a **second ink** rather than a lone one-off. `guidelines/soul-directions.html` shows the
same dashboard header at four intensities:

| | What changes | Cost |
|---|---|---|
| **0** As handed off | nothing | reads as a spreadsheet in a group chat |
| **A** Stamp band | the masthead band is a printed field | almost none — already sanctioned |
| **B** Stamp structural — **shipped** | band, the 2px rule that *opens* a band, active year, primary button | small; two-weight hierarchy now reads in color as well as thickness |
| **C** Two inks | app strip stamped, stock warms to `#f3f0e6` | the eye starts reading chrome before figures — Agate's original failure mode |

**The rules that do not loosen, in any direction.** Stamp is a *ground* you reverse type out
of, never a word painted on paper. No figure, bar, chart series, or grade letter changes
color — those stay ink / `--pos` / `--neg`. No pills, no radius, no shadow, no gradient.
Four sanctioned slots only; a fifth needs a named component.

**Not the answer:** franchise colors, per-lens hues, colored bars, a gradient masthead. Each
would make the data lie, and the data is the product.

---

## CONTENT FUNDAMENTALS

**Voice.** First person, short declarative sentences, concrete nouns, real numbers only.
The app is a record-keeper with an opinion, not a hype machine and not a neutral database.
It states what happened and lets the figure carry the judgment.

**Casing.** Sentence case in all prose. UPPERCASE **only** in Geist Mono — labels,
kickers, column headers, section headings, badges. Never Title Case In Prose. Section
headings are bare nouns with no articles: `FRANCHISES`, `TRADES`, `SCOREBOARD`,
`PRODUCTION`, `FINDINGS` — never "The Franchises" or "Trade Details."

**Person.** Second person for the reader's own standing ("Okafor owns you: 8–4"), first
person plural when the app is at fault ("Not you — us"). Never "Your league is looking
great!" — the app does not congratulate.

**Numbers.** Always real, never rounded for effect, never invented. A margin is stated
as a margin. Signed values always render the sign character.

**The five lenses** are a fixed vocabulary, always in this order:
**Trade Value · Total Points · Regular Season Points · Playoff Points · Toilet Bowl Points.**
Abbreviate to `Value · Total · Reg · Playoff · Toilet` in column headers only.
**Never render "KTC"** anywhere in the interface — it is *Trade Value*, always.

**Examples**

| Say | Never |
|---|---|
| "Okafor owns you: 8–4, +9.6 a game" | "You're 4-8 against Okafor 😬" |
| "Nobody has made a move yet." | "No trades found." |
| "Not you — us. Try again." | "Oops! Something went wrong." |
| "Two years later, Cavanaugh is still paying rent on this one." | "This trade was very lopsided!" |
| "Trades like he's got a spreadsheet open. He does." | (roasts stay dry, never mean) |

**Emoji.** Two, ever: 🏆 and 🚽, and only on the trophy line. 👑, 🪣, ★, and ▽ are all
retired. Rank is a number; last place gets a 1px ink rule above it and dim type.

**Errors and empties** name the condition in a mono kicker, then say what happened in an
Archivo headline in plain words, then one line of body. No apology longer than a sentence.
An empty state says what *will* appear here, not that something is missing.

---

## VISUAL FOUNDATIONS

### Color
Six ground values, two signed values, and **one second ink**. There is still no accent *on
data*: `--stamp` fills four chrome slots (masthead band, ruling stamp, primary button, active
MonoRun cell) and the 2px rule that opens a band; it never colors a figure, bar, series, or
grade letter. Retired for good —
Verdict Violet, `--info`, `--playoff`, `--warn`, `--window`, and nine `--pill-*` tokens
were all retired. The only color in the interface is a signed number or a single grade
letter. A colored word is a lie; a colored number is a receipt.

**Two grounds, equal.** Light is warm newsprint (`#f7f6f1`), never pure white. Dark is
**not inverted paper** — it is ink on slate: a cool near-neutral ground (`#17181a`)
carrying the same warm off-white ink (`#ecebe5`), so Archivo 900 reads *printed* rather
than lit. `--pos`/`--neg` take different values per ground; both pairs are AA-verified.

One **stamp ink** (`#172a44`, ink navy) may back the nameplate band and ruling stamp on
the light ground only. Nothing else may reference it, and there is deliberately no dark
counterpart.

### Type
Three families, each with one job:

- **Archivo** 900 / 800 / 700 — the voice. Nameplates, section headings, leads, franchise
  and player names. Never below 12px.
- **Geist Sans** — prose and controls only.
- **Geist Mono** — every figure, label, and piece of metadata, always `tabular-nums`.

Instrument Serif is retired. The nameplate steps through four size tiers by **character
count** (44 / 36 / 28 / 22px desktop) so the masthead band is the same height whatever the
league is called — computed server-side from the name string, never measured in the
browser. Two lines maximum; never truncated, never ellipsed, never scaled to fit one line.

### Backgrounds
No images, no gradients, no textures, no patterns — with one exception that is the whole
system: **the ruled ground**, a `repeating-linear-gradient` at a fixed 26px pitch where
the stripes *are* the row dividers. Full-bleed imagery does not exist here. The only
photograph anywhere in the app is a Sleeper avatar.

### Depth
**There is none.** No shadows, no radius (`--radius: 0` everywhere), no gradients, no
blur, no translucency. Depth is the ruled ground and 1px rules; emphasis is a heavier rule
— 1px `--ink` opens a band, `--rule` separates within it. The only sanctioned inset is
zero-blur: the you-marker's 3px ink bar.

**Cards are gone as a concept.** No card border, no card radius, no card surface fill.
Chips and pills are retired — a category is mono uppercase text.

The one place something detaches from the page is a **modal**: a full-bleed `--ink` field
at **55%** behind, a `--bg` panel with a 1px ink border in front. No blur, no shadow.
Popovers (tooltips, dropdowns) get no field at all.

### Corner radii
Zero. Everywhere. Including focus rings, buttons, avatars, badges, overlays, and inputs.
A rounded corner would be the only curve on screen.

### Borders
1px, two weights of meaning. `--ink` opens a band or bounds a floating panel; `--rule`
separates within one. **Rows inside a ruled band carry no border at all** — if you are
writing `border-bottom` on a row, the ground is missing.

### Animation
Almost none, and deliberately so. Hover 160ms, disclosure 160ms opacity, tooltip 120ms
opacity. **No travel, no scroll reveals, no entrance animation, no marquee, no
choreography.** The single animated element in the whole system is one indeterminate ink
segment on a hairline track — one per view, square like everything else. No spinners, no
shimmer, no pulsing dot, and never a view-wide `animate-pulse`: a page that breathes reads
as decoration. `prefers-reduced-motion` neutralizes everything.

### Hover and press
Hover on a ledger row is **the lit stripe only** — no tint, no lift, no shadow. Hover on a
button is a small opacity shift. There is no press transform: nothing shrinks, nothing
depresses. Interactive text gets an underline at 3px offset.

### Focus
2px `--ringfocus` outline at 2px offset, radius 0, `:focus-visible` only. `--ringfocus`
aliases ink, so it flips with the ground.

### Layout
Max width 1180px, gutters 18px desktop / 14px at ≤700px. Nothing is fixed or sticky —
**the frozen-column paint mask and `overflow-x-auto` were both retired.** Career figures
and year-scoped figures never share a table: *Franchises* is career-wide, *Trades* follows
the year, and each states its scope in its own header in the same row order, so the reader
travels down and across rather than sideways.

**Mobile keeps every column.** An entry wraps onto two or three rules instead of hiding
fields behind a swipe. The only element permitted to scroll horizontally is the year line.

### Transparency and blur
Two uses, total: the modal field at 55%, and 0.4–0.5 opacity on crosshair hairlines inside
a plot. No blur anywhere — no `backdrop-filter`, no frosted panels.

### Imagery
None. No illustration, no stock photography, no decorative SVG. Meaning is carried by type,
rule weight, and position. Avatars come from Sleeper and render **square** at 26px — one
rule tall — falling back to the owner's initial in mono on a `--rule` fill.

### Charts
Series are distinguished by **stroke weight, not hue**: 2.5px solid ink for the leader,
1.25px dashed for the other side. No legend — each line is labelled at its own right end
with the owner and final figure. Phase is a rail *under* the axis (solid ink for
postseason), never a translucent band over the data. Plot height is a whole number of rules
so gridlines share the table pitch. Bars are ink on a 1px ink outline and are **never
colored** — a bar is not a number.

---

## ICONOGRAPHY

> **Two first-party sets, no CDN.** Agate's nineteen marks are **cut** — right angles and
> 45° edges, explicitly no curves, because the system has no radius
> (`components/controls/icon-paths.js`). Furniture has a 16px radius everywhere, so cut
> marks fight it; `ui_kits/furniture/icons.js` is **the same nineteen names redrawn as
> stroked marks** (16px grid, stroke 1.6, round caps and joins, `currentColor`). A call site
> swaps sets without renaming anything.
>
> The app's drift guard bans `lucide` outright, which is why neither set is a CDN import.
> The one exception is the superseded Collection prototype under `explorations/collection/`,
> which still loads Lucide — fine for a mockup, and it must not travel into production.
>
> `icons.js` is a **classic script** loaded with a plain `<script src>`. Do not add an
> `export` statement to it: that throws a SyntaxError and silently kills every mark on the
> page (it did exactly that once).


**The app had no icon set.** `ThemeToggle.tsx` imported `lucide-react` for a sun and a
moon inside a `rounded-full` pill — an off-the-shelf set *and* a radius, both forbidden —
and everything else used unicode text glyphs. There was no icon font, no sprite, and no SVG
directory to copy.

So the set was **drawn to the system**: nineteen solid marks on a 16px grid, right angles
and 45° edges only, shapes **cut rather than stroked** so they carry the mass of Archivo 900
instead of the thinness of a divider. `fill` is `currentColor` and holes are real
transparency via `fill-rule: evenodd`, so a mark knocks out to paper, slate, or an ink
button with no variants. No outline version, no second weight, no duotone.

A hairline (stroked) alternative was drawn and rejected — it was drawn in the weight of a
*divider*, which speaks to only half of a system whose identity is the contrast between
hairline rules and heavy type.

**The inventory** is exactly what the app uses, derived from its components:
`sort-desc`, `sort-asc`, `open`, `closed`, `forward`, `back`, `info`, `light`, `dark`,
`copy`, `share`, `swap`, `table`, `season`, `menu`, `close`, `done`, `alert`, `add`.
Adding a twentieth means naming the component that needs it.

**Rules:** 11–12px in a table header, 12–14px in a control, 20px in a specimen. Always
beside a label except `menu` and `close` (unambiguous and target-hungry). Near data a mark
stays `--dim` — a solid triangle carries real mass in a dense row. Never `--pos`/`--neg`;
those belong to figures. `light` and `dark` are a ring and a solid square, not a sun and a
moon, because the system has no curves.

**Unicode stays inline.** Glyphs set *in a sentence* remain characters: `All trades →`,
`← Back`, `·` separators, `▾ ▸ ↑ Σ`, and 🏆/🚽. An SVG swapped into a sentence will not
sit on the baseline. The set is for controls only.

**Logo.** The source contains no logo or brand mark, and none was invented. The app's name
is set in plain type — Geist Mono 8.5px uppercase, letterspaced 0.16em, reversed out of an
ink strip — and appears in that strip and nowhere else. The favicon is the letters `DA`
(Dynasty Analyzer) in Geist Mono 500, ground on ink, at 512² / 180² / 32² / 16². No `.ico`,
no manifest.

---

## Index

| Path | What it is |
|---|---|
| `styles.css` | The entry point. `@import` list only — link this one file. |
| `tokens/colors.css` | Ground, signed outcomes, stamp ink, focus, overlay field. Both grounds. |
| `tokens/stamp.css` | **Added.** The drawn dark stamp + the second-ink range. Read its header before using. |
| `guidelines/soul-directions.html` | **Added.** The four intensities above, on the real dashboard header. |
| `guidelines/DESIGN.md` | The handoff's written system of record, verbatim. |
| `thumbnail.html` | Project tile. |
| `tokens/typography.css` | Three families, nameplate tiers, the size and tracking scale. |
| `tokens/rhythm.css` | `--rule-pitch`, targets, gutters, stroke weights, durations. |
| `tokens/base.css` | `.ruled`, `.tabular`, `.tap`, `.you-marker`, focus, keyframes. |
| `tokens/fonts.css` | Real `@font-face` rules for the three self-hosted variable families. Archivo (legacy Agate only) still linked. |
| `assets/fonts/` | Six variable `.woff2` files, latin + latin-ext, with their OFL licence texts. |
| `guidelines/*.html` | 22 specimen cards: Colors, Type, Spacing, Brand, Proposal, Stamp ink options. |
| `components/ledger/` | `Ruled`, `Rule`, `LedgerSection`, `Nameplate` |
| `components/data/` | `Figure`, `Label`, `GradeLetter`, `InkBar`, `WindowCell` |
| `components/controls/` | `Icon` (19 marks), `MonoRun`, `Button` |
| `components/feedback/` | `RulingStamp`, `Tooltip`, `IndeterminateBar`, `StateMessage` |
| `templates/<slug>/` | Four copyable starting screens as Design Components: dashboard, trade, franchise, mobile. |
| `ui_kits/dashboard/` | League dashboard — masthead, year line, lead, two ledgers |
| `ui_kits/trade/` | Single trade — ruling stamp, scoreboard, side ledgers, findings |
| `ui_kits/franchise/` | Franchise page — hero, rings, why-this-grade, track record, outlook |
| `ui_kits/mobile/` | 390px — entries wrapped onto rules, nothing dropped |
| `SKILL.md` | Agent-Skills front matter, for use in Claude Code |
| `CLAUDE.md` | State of play + the open items to pick up next session. Read this first. |
| `design_handoff_agate/` | The developer port package: work order, DESIGN.md, session prompts |

### Components — the 22 Furniture primitives

Every component in the bundle, by group. The inventory comes from the app's own component
tree plus `ui_kits/furniture/kit.css`, not from a generic checklist — there is no Toast,
Dialog, Checkbox or Switch, because the product has no counterpart for them.

**`components/ledger/` — structure**
| Component | What it is |
| --- | --- |
| `TopBar` | The one chrome strip: wordmark, league, nav, right group. There is no second nav. |
| `Panel` | A ledger: solid ground, one radius, one elevation. |
| `Row` | One rule in a ledger — `head`, `body`, `total`, `mine`. |
| `EntryCard` | One entry as a card: the narrow-width form of a Row. |
| `CardList` | The card stack, gapped rather than margined. |
| `MetaLine` / `Meta` | A card's secondary facts. Each wraps whole; only the value is tinted. |
| `SectionHead` | A section heading, optionally collapsible. Mixed case, never uppercase. |
| `StampBand` | The league masthead — the one large stamp area. |
| `Name` | A franchise or player name, in the display face at every density. |

**`components/data/` — figures**
| Component | What it is |
| --- | --- |
| `Figure` | Every number. Tabular mono; only signed values carry colour. |
| `GradeLetter` | A grade on the A-F tone ramp, using the strong pair. |
| `Bar` | A magnitude bar in a sunk track. Replaces Agate's `InkBar`. |
| `Label` / `Kicker` | Mono uppercase micro-copy at the 8.5px floor. |
| `WindowCell` | The competitive window as an ORDERED five-step ladder. |
| `Avatar` | A franchise identity mark — colour plus initial. |

**`components/controls/` — interaction**
| Component | What it is |
| --- | --- |
| `Button` | Stamp-filled primary or outlined ghost. One primary per view. |
| `SegmentControl` | The ONE single-select dialect: year filters, metric switches, view toggles. |
| `SortButton` | A sortable column header; direction carried by `aria-sort`. |
| `MonoLink` | "Out to a bigger view" — never a second button. |
| `Field` | A text input with mono label and hint. |
| `ThemeToggle` | Light / Dark. Dark is a first-class ground, not an inversion. |
| `Mark` | One of the nineteen stroked marks. `FX_ICON_PATHS`, `FX_ICON_NAMES`. |

**`components/feedback/` — state**
| Component | What it is |
| --- | --- |
| `Tooltip` | The definition behind a label. Every pillar and signal gets one. |
| `StateMessage` | Empty, error, not-found — always with the one action that resolves it. |
| `IndeterminateBar` | The system's one loading indicator. One per view. |
| `RulingStamp` | A trade ruling with the verdict as the headline. |

**Retired with Agate** (the concepts, not just the code): `Ruled`, `Rule` and
`LedgerSection` encoded the striped ground and the 26px clamp — replaced by `Panel`,
`Row` and `SectionHead`. `Icon` was the CUT mark set, replaced by the stroked `Mark`.
`InkBar` became `Bar` (bars may now carry colour). `Nameplate` folded into `StampBand`,
and `MonoRun` — which unified four source treatments into one dialect — became
`SegmentControl`. Agate's own `.ruled` CSS survives under `[data-theme="agate"]`, so the
four Agate UI kits still render.

**Intentional additions** (no direct source counterpart): `Mark` (the app had no icon set,
only `lucide-react` in one file); `IndeterminateBar` (replaces a view-wide
`animate-pulse` and several spinners with the one sanctioned animation); `EntryCard` (the
decided answer to the mobile split); and `tokens/stamp.css` as a named layer.

### Not covered

**Every product screen is now drawn** — 17 in `ui_kits/furniture/`, each with a phone view
at a real 390px (`ui_kits/furniture/phones.html` is the contact sheet). What remains
undrawn is the SVG geometry: `ProductionTimeline`, `CareerArc` and the plots inside
`RosterHealthTab`. A radius-and-elevation pass does not touch an SVG, so those need
drawing rather than theming.

All four `templates/` are Furniture. They are what a consuming project copies:
`templates/dashboard` (league front page), `templates/franchise` (the deepest screen —
grade-first hero and five tabs), `templates/trade` (a ruling), `templates/mobile` (the
390px form). Each is one `.dc.html` plus a `ds-base.js` whose single `base` line is the
only thing a consumer edits.

### Known substitutions

**Resolved.** Bricolage Grotesque, Geist and Geist Mono are self-hosted from
`assets/fonts/` as six variable `.woff2` files (latin + latin-ext each), declared with real
`@font-face` rules in `tokens/fonts.css`. All three are SIL Open Font License 1.1; the
licence texts ship beside the binaries.

Variable rather than static, deliberately: Bricolage's `opsz` axis redraws its letterforms
for the size they are set at, and a static instance freezes that at 14 — which would set
every 44px nameplate in a text cut. The type scale here runs 8.5px to 44px, so the axis is
doing real work. Because `font-weight` is declared as a range, every weight between 200 and
800 is available without another file.

One family is still linked rather than self-hosted: **Archivo**, used only by the legacy
`[data-theme="agate"]` scope, for which no binary was supplied. Nothing under Furniture
loads it.
