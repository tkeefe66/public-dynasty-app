# Trade Lineage Phase 2: The "Became" Grade — Design Spec

**Date:** 2026-06-08
**Epic:** Lineage (#2), Phase 2. Builds on Phase 1 (the lineage trees) and `current_holders`.
**Status:** Design approved — pending spec review before plan.

## Problem

Today a trade is graded only by what each side *directly* received. So Bobster's
Barkley deal reads "got nothing" (he flipped Barkley before he played). Phase 1
*shows* what the trade became; Phase 2 puts that into the **numbers**, as a
parallel "what it became" grade alongside the existing direct grade.

## Decisions locked during brainstorming

| Decision | Choice |
|---|---|
| Replace or parallel | **Parallel.** Keep the direct grade and the LLM verdicts untouched; add a "became" figure beside them. |
| Metrics | **All four:** Trade Value / Total Points / Points Started / Playoff Points, recomputed on the terminal haul. |
| Terminal definition | **Bounded traversal (the anti-spiderweb rule).** A received *player* gets exactly **one flip**; the resulting players are terminal. A *pick* is an IOU, so follow it through every flip/draft until it becomes **players**; those players are terminal. A terminal player traded onward is a *new* trade's story (stop). Terminal is defined by this traversal, NOT by current holdings. |
| Same rule for the tree | **Yes** — re-bound the shipped Phase-1 lineage tree (`engine/lineage.py`, currently a full unbounded recursion) to this same rule, so the picture and the grade tell the same story. Shared walk. |
| Shape | **Per-side totals**, not a zero-sum swing. "What *your* haul became." |
| When computed | **During refresh, cached, incremental** (only recompute for trades whose terminal set changed). The became-production needs the per-week matchups, which only exist during refresh. |
| Story integration | Out of scope (Phase 2.5). Numbers only. |

## The model

For each side, walk what they **received** under the bounded rule above to its
**terminal players** (a received player → one flip → players; a pick → followed
through flips/drafts → players; players are the stop). Then measure those
terminal players:

- **Trade Value (became)** = current KTC of the terminal players (`ktc_values`),
  plus KTC pick-value (`pick_values`) for any branch that still ends on an
  *undrafted* pick. A terminal player who was later traded onward is still
  valued at current market (he is what this trade yielded); his onward trade is
  a separate trade's became.
- **Total / Started / Playoff Points (became)** = points each terminal player
  scored **while this side owned him** (the same matchup walk
  `grade_hindsight_production` does, anchored on the terminal players and this
  side's ownership windows). A player flipped immediately contributes ~0 points
  but still his market value.

So Bobster's "became" for the Barkley deal = the players he flipped Barkley into
(and what any picks in that package became), valued today, plus the points they
scored while he held them. The direct grade ("received Barkley, scored 0 for
him") is unchanged and sits beside it.

Walked example (locked): A received → flip → `player B (terminal) + pick P1`;
`P1 → flip → player C (terminal) + pick P2`; `P2 → ... → player (terminal)`.
Became = B + C + P2's player. B/C are never followed past here.

## Engine — shared bounded walk + `engine/regrade.py` (net-new)

- **Revise `engine/lineage.py`** to the bounded rule. The current
  `build_trade_lineage` recurses with no limit; change the recursion so a
  **player follows only one flip** (its result players are terminal) while a
  **pick keeps following** until it resolves to players. Extract the core walk so
  it yields, per side, the **terminal assets** with identity (player_id, or an
  undrafted pick's season/round) and the bounded tree. Both the tree (Phase 1)
  and `terminal_holdings` (Phase 2) use this one walk → consistent story.
  - `terminal_assets(trade, resolved_trades) -> dict[user_id, list[TerminalAsset]]`
    where `TerminalAsset` carries `kind`, `player_id` or pick `(season, round)`,
    and a label.
- `engine/regrade.py`: `build_became_grade(trade, resolved_trades, *, matchups, roster_to_user_by_league, playoff_weeks_by_league, league_season_by_id, ktc_values, pick_values, fmt) -> dict[user_id, BecameMetrics]`
  - `BecameMetrics` = `{ ktc, production, started, playoff, terminal_labels: list[str] }`.
  - Value terminal players via `ktc_values` (and `pick_values` for branches still
    ending on an undrafted pick); production via a matchup walk over the terminal
    players, summed over each side's ownership windows.
- Pure, unit-testable on fixtures: one-player-flip terminal, pick-followed-to-
  player terminal, the multi-hop pick chain (B + C + P2-player), a player flipped
  onward (valued at market, ~0 production), an undrafted-pick terminal (value
  only). `current_holders` is NOT the terminal definer anymore (the walk is).

## Refresh + cache

- In `GraderService.run`, after grading and `current_holders`, compute
  `build_became_grade` per trade (matchups, ktc, pick values all in scope there),
  **incrementally**: a `terminal-set hash` per trade skips recompute when the
  terminal holdings are unchanged (mirrors the story `facts_hash` skip), so the
  scheduled refresh stays cheap.
- Store `became_grades: dict[trade_id, dict[user_id, BecameMetrics-dict]]` on
  `ChainCacheEntry` (new field, default `{}`, backward compatible).

## API

- Add a `BecameMetrics` Pydantic model and `became: dict[user_id, BecameMetrics]`
  to `TradeDetailResp`, read from the cache in `trade_view.build_trade_detail`.

## Frontend — `web/components/TradeBecame.tsx`

- A "What it became" block on the trade detail page, beside the direct receipts:
  the four metrics per side, plus the terminal-holdings labels. Visually distinct
  from the direct receipts so it reads as the *downstream* outcome. Renders only
  when a side has a non-trivial terminal set (otherwise the direct grade already
  tells the whole story).

## Testing

- **Engine** (fixtures): kept asset → its current value + production;
  flipped-into-two → both terminals' value + production; dropped terminal → 0;
  undrafted-pick terminal → value only, 0 production; the incremental
  terminal-set hash is stable for unchanged holdings.
- **Cache:** `became_grades` round-trips; pre-migration entry loads with `{}`.
- **API:** `build_trade_detail` surfaces `became` per side.
- **Frontend:** vitest render of the became block (four metrics + labels), and
  that it renders nothing for an empty/trivial side.

## Out of scope

Story/verdict integration (Phase 2.5), following the *given* side's lineage,
counting transient production of since-dropped assets, FAAB.

## Open questions

The exact "incremental terminal-set hash" key and whether to value undrafted
picks at a flat tier or the pick-value table are tuned during implementation.
