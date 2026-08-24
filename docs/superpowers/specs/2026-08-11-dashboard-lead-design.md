# Dashboard lead — verdict headline + figure strip

**Date:** 2026-08-11
**Status:** approved, not yet implemented
**Surface:** `web/components/HeadlineMoves.tsx`, `web/components/DashboardSkeleton.tsx`,
`api/app/services/aggregations.py`, `api/app/models/league.py`

## The problem

The dashboard lead reads as a verdict but delivers none.

1. **The prose and the figure block say the same thing twice.** The body sentence
   spends its width on "+12,483 in value and +179.8 points" — the two numbers the
   figure block already carries an inch to the right.
2. **Nobody won.** A +12,483 Trade Value swing belongs to exactly one side. The
   lead names both owners and attributes the swing to neither, which is why the
   headline falls back on vague loudness ("still the loudest swing on the board").
   The trade-story pipeline has computed a value winner *and* a production winner
   per trade since the story feature shipped; the dashboard just never asked for
   them.
3. **The figure rail is mostly air** — a bordered 250px box holding two whisper
   rows.

A fourth, self-inflicted: commit `11ebe55` widened the live rail to 250px but left
`DashboardSkeleton` at 210px, so the lead shifts 40px when data lands — exactly
what that skeleton exists to prevent.

## The decision

**Option A — figure strip, no box**, with two headline forms. Reviewed against a
head-to-head ledger (B) and display-scale figures in the retained rail (C) as
rendered mockups; A won on being the only one that is rules rather than a box,
which is what the system says depth is.

## Backend

`LatestTrade` (`api/app/models/league.py`) gains three optional fields. All three
are derived at response time inside `_latest_trades`
(`api/app/services/aggregations.py`) from the grade blob it already reads —
nothing new is computed and nothing new is persisted, so **no `ChainCacheEntry`
field and no `SCHEMA_VERSION` bump**.

| Field | Type | Derivation |
|---|---|---|
| `value_winner` | `OwnerRef \| None` | argmax over `snapshot_value_swing` (zero-sum) |
| `production_winner` | `OwnerRef \| None` | argmax over `production_total` (received-only) |
| `production_split` | `tuple[float, float] \| None` | `[value_winner's total, the other side's total]` — emitted only when the trade has exactly two sides |

All three are `None` when the grade blob is missing or carries fewer than two
graded sides. The existing `swing_ktc` / `swing_prod` / `assets_short` fields are
untouched — `TradeCard`, `TradesTab`, and `lib/receipts.ts` all read them, so this
is purely additive.

`production_split` is ordered by the **value winner**, not by who leads that
metric. The left-hand number in every strip cell belongs to the same person, so
the reader tracks one subject across the row.

### Why `production_split` and not `swing_prod`

`swing_prod` is `max − min` — a spread. `CLAUDE.md` is explicit that Trade Value is
the one swing metric and the four production metrics are received-only tallies read
head-to-head ("104 vs 56"). The current lead prints a production *swing*, which is
off-convention; the split corrects it.

## Copy

Two deterministic headline forms, selected by whether the two winners agree. No
LLM, no claim the payload can't support — the mockup's "isn't close anymore" and
"out-earned in all but three weeks" needed weekly data the dashboard doesn't carry
and are out.

| Case | Headline |
|---|---|
| Winners agree | `{name} won this one on both counts.` |
| Winners differ | `{value_winner} won the value. {production_winner} won the field.` |
| Either winner `None` | Current form: `{a} & {b}'s trade is still the loudest swing on the board.` |

Body drops every figure: `{assets_short}, traded {date}.`

## Layout

The kicker rule and headline go full width — the right rail is deleted. Beneath
the body, one `<Ruled>` strip of two rules: a label rule and a figure rule, three
cells each, capped at **620px**. Full width was tried and rejected in the mockup:
at 1180px a figure lands every ~390px and the three read as unrelated facts.

| Cell | Content | Treatment |
|---|---|---|
| `VALUE` | `+12,483` | Signed → `--pos`/`--neg`. The one colored figure. |
| `POINTS` | `179.8 vs 58.3` | **No color.** Received-only totals are never negative, so a sign color would always be green and mean nothing (Agate rule 6: color only on signed numbers). The lens winner is `font-semibold`; the other side and the `vs` are `--dim`. |
| `SINCE` | `Aug 29, 2025` | `--dim`. |

Three sides or more → the `POINTS` cell is a `--dim` em dash. `production_split`
is null there, and the only production figure the payload carries (`swing_prod`)
is a spread across every side rather than any one owner's total — printing it
under a `POINTS` label would misdescribe it. Zero of the league's 47 trades have
more than two sides, so this branch is defensive. Both sides at 0.0 → the cell is a `--dim` em dash, matching
the trade page's rule that a lens both sides left at zero is unscored
(`trade_view.py::_realized_lens_totals`) — an offseason trade whose players
haven't played yet must not read as a 0.0-vs-0.0 result.

**One strip at every width.** At 390px the three cells get ~120px each and the
longest string (`179.8 vs 58.3`, ~86px at 11px Geist Mono) fits, so the
desktop/mobile duplication in `HeadlineMoves` collapses to a single render — the
component loses a branch rather than gaining one.

`DashboardSkeleton` drops its rail on the same tracks, which closes the 40px shift.

### The other three phase sources

The lead is one fixed skeleton; only the source changes, so all four adopt the
strip. A strip cell is label-over-value, which the week recap already fits
(`HIGH  Alice 140.0`; `BLOWOUT  Alice +50.0`). The blowout figure carries a sign
and the high score doesn't: `week_recap.py:174-179` only ever proposes a
strictly positive margin, so the `+` isn't reporting direction — it's what
tells a margin apart from a score sitting one cell over in the same strip.
Bracket-watch and the empty state keep their em-dash placeholders. Verified in
the mockup.

## Design-system amendment

`Dynasty Directions.dc.html` Fig. 2a.1 specifies the lead as *"kicker left, phase
note right, headline, body, bordered figure block on the right rail"*, and
`HeadlineMoves` is on the do-not-restyle list as its reference implementation.
This removes the rail. `design_handoff_agate/DESIGN.md` is updated in the same
commit so the handoff and the code don't drift; the `agate-styling` skill's
reuse table gains the strip.

No new token, no new stamp slot, no guard-test allowance.

## Testing

**`api/tests`** — winner derivation: winners agree; winners differ; three-way
trade (`production_split is None`); missing grade blob (all three `None`);
existing `swing_*` fields unchanged.

**`web/tests/HeadlineMoves.test.tsx`** — each headline form including the
`None` fallback; strip renders three cells; `POINTS` carries no `text-pos`/
`text-neg`; the winning figure is weighted and the losing one dimmed; every phase
source renders the same strip; the empty state keeps its placeholders and its
button.

**`web/tests/DashboardSkeleton.test.tsx`** — skeleton and live lead agree on
column tracks.

`web/tests/agate-rules.test.ts` runs unchanged.

## Out of scope

- Weekly "out-earned in N of M weeks" claims — needs a per-week rollup the
  dashboard doesn't fetch.
- Bracket-watch content (still `TODO(bracket-watch-payload)`).
- The Trades-tab and owner-page trade rows, which keep `swing_prod`.
