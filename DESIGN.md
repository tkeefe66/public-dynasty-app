# Design — superseded twice. Start at [`DESIGN_SYSTEM.md`](DESIGN_SYSTEM.md).

This file used to hold **"The Ledger"** — the app's first design system. It is
**two systems out of date** and nothing in it describes what the app renders.

Its full text is in git history (`git log --follow -- DESIGN.md`). It was gutted
rather than deleted because a root-level `DESIGN.md` is the first file anyone
opens looking for the rules, and finding the wrong constitution there is worse
than finding a signpost.

## The lineage

| System | Identity | Status |
|---|---|---|
| **The Ledger** | Verdict Violet, Instrument Serif, 10px cards, grade pills, frozen columns | Retired — this file |
| **Agate** | Warm newsprint, Archivo 900 uppercase, 26px lockstep, zero radius, striped ground | Retired 2026-08-13 — see `design_handoff_agate/` |
| **Furniture** | Cobalt `#2f42ff`, Bricolage Grotesque mixed-case, 40px pitch, 16px radius, solid panels | **Shipped** — `.design/` |

Every token The Ledger named — `--accent` (Verdict Violet), `--info`,
`--playoff`, `--warn`, `--window`, the nine `--pill-*`, `--surface`, `--divider`
— was deleted two systems ago. **Never reintroduce them.** Instrument Serif and
Archivo are both gone. Cards no longer carry a 10px radius because Agate removed
radius entirely and Furniture reintroduced it at 16px, which is not the same
value or the same idea.

## Where the rules actually live

- [`DESIGN_SYSTEM.md`](DESIGN_SYSTEM.md) — the entry point.
- `.design/SKILL.md` — the rule list of record.
- `.design/tokens/` — the source of truth for every value. Generated; never edit
  a value there.
- The `furniture-styling` skill — how UI gets built in `web/`.
- The `design-system-sync` skill — wiring `.design/` in, and re-syncing it.

Note that `.design/guidelines/DESIGN.md` is a *third* file by this name and it
still describes Agate. `.design/SKILL.md` wins over it.

## What survived all three systems

Four rules, unchanged since The Ledger:

1. **No colour on data** that is not a sign. A colored word is a lie; a colored
   number is a receipt.
2. **Figures reconcile.** Any headline number equals the rows beneath it.
3. **Colour is identity, never ranking.**
4. **Never render "KTC"** — it is *Trade Value*, always.
