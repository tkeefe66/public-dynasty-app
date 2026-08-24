---
name: fantasy-analyzer-design
description: Use this skill to generate well-branded interfaces and assets for Fantasy Analyzer, either for production or throwaway prototypes/mocks/etc. Contains essential design guidelines, colors, type, fonts, assets, and UI kit components for prototyping.
user-invocable: true
---

Read `readme.md` here, then explore. If you are making visual artifacts (mocks, slides,
throwaway prototypes), copy assets out and write static HTML. If you are working on
production code, read the rules here and become an expert in this brand.

If invoked with no other guidance, ask what they want to build, ask some questions, and act
as an expert designer who outputs HTML artifacts *or* production code, depending on need.

## Read this first: which system are you in?

This project shipped **Furniture** on 13 Aug 2026. Furniture is the default: cobalt
`#2f42ff`, Bricolage Grotesque, 40px pitch, 16px radius, one elevation, solid panels.

**Agate is the retired predecessor** — monochrome, 26px lockstep, zero radius, striped
ground, ink-navy stamp. It survives only under `:root[data-theme="agate"]` so four legacy
kits still render. **Any rule you find phrased as "zero radius" or "the ruled ground is the
divider" is Agate's and no longer applies.** **This list is the rule of record** — if a file
disagrees with it, this list wins.

## The rules that break things if you miss them

1. **A solid panel has no stripe, so it must draw its own row rules.** Every table needs an
   explicit `border-top: 1px solid var(--rule)` between rows. This is the single most
   commonly missed line, and the app's own drift guard currently forbids it — `divide-y`
   must be inverted in the same commit.
2. **Any headline figure must equal the rows beneath it.** A margin is a margin, never one
   side's raw figure. This has broken four times in this project's history and it is the one
   rule with no exceptions.
3. **Colour never carries information that is not also in the figure or the sort order.**
   Bars may be `--pos-bar` / `--neg-bar`; chart series may carry franchise identity via
   `--id-N-line`. Franchise colour is identity, never ranking.
4. **Never render "KTC".** It is **Trade Value**, always.
5. **On mobile an entry becomes a card, not a row.** Do not try to solve narrow layouts with
   border logic — a card's edge *is* the entry boundary.

## Token traps that have each cost a round

- **Signed figures take the `-strong` pair.** `--pos` / `--neg` do NOT clear WCAG AA as text
  on any light ground this system defines. Measured: `--pos` #00a63e is 2.90:1 on `--bg`,
  3.22:1 on `--surface` and 3.06:1 on `--surface-sunk`, against a 4.5:1 bar — and on `--bg`
  it misses even the 3:1 large-text floor. `--pos-strong` #007a33 is 4.94 / 5.48 / 5.21 and
  `--neg-strong` #a3131d is 7.09 / 7.87 / 7.48. Dark theme passes either way, but a utility
  class picks the token for both themes, so light decides.
- **Never `-ink` on a wash.** `--stamp-ink` is the ink for the *solid* cobalt fill (white).
  On `--stamp-wash` it measures 1.13:1.
- **Never an alpha of a reversed ink.** For a second line on cobalt use `--stamp-ink-dim`;
  `rgba(255,255,255,.72)` is 3.97:1 at 9px and small reversed type gets no exemption.
- **A fill ramp is not a stroke ramp.** `--id-1..6` are fills (chips, avatars, edges). For
  any polyline, axis stub, scatter mark or connector use `--id-N-line` — as 1–3px lines on
  white only two of the six fills clear the 3:1 WCAG 1.4.11 asks of a graphical object.
- **44px minimum tap target**, 26px absolute floor for inline glyph buttons.

## The mark

`assets/logo/mark.svg` **must be inlined**, never `<img src>` — an `<img>` is its own
document, so `currentColor` resolves against nothing and the mark renders black.
`favicon.svg` is a deliberately different drawing (the seam smudges below ~24px). The
wordmark is HTML in Bricolage, not SVG `<text>`.

## Where things are

Everything in this table ships in the export and you can open it.

| Path | What |
| --- | --- |
| `styles.css` | The one file a consumer links. Imports everything below. |
| `tokens/` | Colours, type, rhythm, stamp, fonts. **The source of truth for values.** |
| `assets/fonts/` | Six variable woff2 builds + OFL. Take these, not a CDN. |
| `assets/logo/` | The mark, app icon, monos, favicon. |
| `components/{ledger,data,controls,feedback}/` | 22 primitives, each with a `.prompt.md`. |
| `templates/{dashboard,franchise,trade,mobile}/` | Copyable starting screens. |

### In the design project only — NOT in the export

`handoff/export-design-repo.sh` deliberately leaves these behind: decision history is
useful in the design project and noise in a code repo. **Do not cite them in files that
travel** — a consumer cannot open them, and briefing an agent against a path that is not
there burns a whole run before anyone notices.

| Path | What | Where to look instead |
| --- | --- | --- |
| `ui_kits/furniture/` | ~40 drawn product screens, desktop and phone | `templates/` ships four copyable screens |
| `guidelines/` | Dated audit cards, explorations, rule history | This file is the rule of record |
| `explorations/` | Direction studies | — |

The nineteen marks are in `components/controls/fx-icon-paths.js`, which **does** travel —
earlier revisions of this file pointed at `ui_kits/furniture/icons.js`, which does not.

`guidelines/DESIGN.md` was removed from the export on 2026-08-16. It was the only design
document a consumer ever saw and it still described Agate on five axes — name "FFB Dynasty",
bg #f7f6f1, stamp #172a44 navy, Archivo 900 uppercase, and a pos/neg pair matching neither
the base tokens nor the `-strong` ones. This file replaces it.
