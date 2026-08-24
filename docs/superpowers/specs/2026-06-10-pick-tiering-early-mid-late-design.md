# Early/Mid/Late Pick Tiering — Design

**Date:** 2026-06-10
**Status:** Approved (pending spec review)

## Goal

Value draft picks by their **early / mid / late** tier instead of a flat
round-average, in both places the app values *future / unresolved* picks:

- **Phase 1 — Draft Capital** (GM rating Outlook signal).
- **Phase 2 — Trade grader** snapshot value (the headline "Trade Value" swing).

A future pick has no real tier yet (its slot depends on where the original team
finishes), so we **estimate** the tier from the original team's current roster
strength. Resolved picks are unaffected — they're already valued as the player
drafted.

## Decisions (confirmed)

| Topic | Decision |
|---|---|
| Tier estimate | **Roster-strength rank.** Rank owners by current roster KTC value; split into thirds: weakest third → **early** (worth most), middle → **mid**, strongest → **late** (worth least). |
| A pick's tier | The **original** team's tier (`PickAsset.original_owner_user_id` / the pick's `original` roster) — the slot is set by whose record the pick belongs to, not the holder. |
| Applies to | All outlook seasons (2027/2028/2029) uniformly; one tier per team from current strength. |
| Sequencing | **Two phases.** Ship + verify Phase 1 (low blast radius) before Phase 2 (changes headline Trade Value app-wide). |
| Trade grader scope | **Snapshot (today) value only.** The at-trade ("value when traded") value stays round-average — tiering it would need historical roster strength we don't store. |
| Fallback | Any `(season, round, tier)` KTC doesn't publish → the existing round-average value. Unknown original owner → round-average. |

## Existing machinery (confirmed)

- KTC publishes tiered pick entries ("2027 Early 1st", "2027 Mid 2nd", "2027
  1st"). `api/ktc.py` `_PICK_NAME_RE` already matches the tier but as a
  **non-capturing** group; `build_pick_value_table` averages tiers to a round
  value (`(season, round) -> KTCValue`).
- `PickAsset` (`models/trade.py`) already carries `original_owner_user_id` —
  "what determines the draft slot once the draft happens."
- Trade grader values an unresolved/at-trade pick via
  `pick_values[(season, round)]` (`engine/trade_grader.py::_ktc_value`, line ~74);
  resolved picks use the drafted player's KTC.
- `engine/draft_signals.py::pick_holdings_value` values future picks by
  `pick_values[(season, round)]`.
- `roster_value` per owner (current roster KTC sum) is already computed in
  `rating_signals.py`.

## Shared foundation (built in Phase 1, reused in Phase 2)

### 1. Tier-aware KTC pick table — `api/ktc.py`

- Make the tier group in `_PICK_NAME_RE` **capturing**:
  `(?P<tier>early|mid|late)?`.
- New `parse_pick_name_tiered(name) -> tuple[int, int, str] | None` returning
  `(season, round, tier)` where `tier ∈ {"early","mid","late",""}` (`""` =
  untiered round entry).
- New `build_pick_value_table_tiered(ktc_values) -> dict[tuple[int,int,str], KTCValue]`
  — same grouping as `build_pick_value_table` but keyed by `(season, round, tier)`,
  **not averaged**. Keep `build_pick_value_table` unchanged (still the
  round-average fallback).

### 2. Tier-by-owner from roster strength

A pure helper `engine/draft_signals.py::strength_tiers(roster_value_by_id) ->
dict[int, str]`: rank roster_ids by value descending, split into thirds →
`"late"` (top), `"mid"`, `"early"` (bottom). Edge: <3 owners → all `"mid"`.

A helper to resolve a future pick's tiered value with fallback,
`engine/draft_signals.py::tiered_pick_value(season, round, tier, tiered, round_avg) -> float`:
return `tiered[(season, round, tier)]` if present, else `round_avg[(season, round)]`,
else 0.

### 3. Thread the tiered table through refresh

`grader_io.py::pull_supporting_data` already builds `pick_value_table`; add
`pick_value_table_tiered = build_pick_value_table_tiered(ktc_values)` into
`supporting`.

## Phase 1 — Draft Capital tiered

- `pick_holdings_value` gains `tier_by_roster: dict[int, str]`,
  `tiered_values: dict[tuple[int,int,str], float]`; values each held pick
  `(s, rd, original)` by `tiered_pick_value(s, rd, tier_by_roster.get(original, ""), tiered_values, round_avg)`.
  Keeps the round-average `pick_values` arg as the fallback table.
- `rating_signals.py`: build `roster_value_by_id` (map the existing per-uid
  `roster_value` through `r2u_current`), `tier_by_roster = strength_tiers(...)`,
  convert `pick_value_table_tiered` to floats, pass both into
  `pick_holdings_value`.
- **No UI/blurb shape change.** Update the `draft_capital` `?` help to note it's
  tiered by projected finish.

### Phase 1 tests
- `parse_pick_name_tiered` / `build_pick_value_table_tiered`: tiers parsed and
  not averaged; untiered entry → `""`.
- `strength_tiers`: thirds by rank; <3 → all mid.
- `pick_holdings_value`: a weak team's (early-tier) 1st is worth more than a
  strong team's (late-tier) 1st; missing tier → round-average fallback.
- `rating_signals`: pick-rich-with-early-picks owner out-ranks one holding
  late-tier picks of the same round.

## Phase 2 — Trade grader snapshot tiered

- Compute `tier_by_user: dict[uid, str]` from current roster strength **before
  the grading loop** in `grader.py` (fetch current rosters earlier, or compute in
  `pull_supporting_data`), using the same `strength_tiers` logic keyed by uid.
- `trade_grader.py::_ktc_value` (and `grade_snapshot_value`, `grade_trade`) gain
  optional `tier_by_user` + `tiered_values`. For an unresolved / `ignore_drafted_player`
  pick, value = `tiered_pick_value(season, round, tier_by_user.get(asset.original_owner_user_id, ""), tiered_values, round_avg)` instead of the flat round lookup.
  **`ignore_drafted_player` at-trade path keeps the round-average** (per the
  scope decision) — only the snapshot path (`ignore_drafted_player=False`) tiers.
- `grader.py` passes `tier_by_user` + the tiered table into `grade_trade`.
- Reuse the same `tier_by_user` for Phase 1's Draft Capital (single source).

### Phase 2 tests
- `_ktc_value`: an unresolved pick whose original owner is a weak team (early
  tier) values higher than one from a strong team (late tier); resolved picks
  unchanged; the at-trade (`ignore_drafted_player=True`) path stays round-average.
- `grade_snapshot_value`: a side receiving an early-tier future pick shows a
  larger swing than the round-average baseline.

## Data flow

```
refresh → build_pick_value_table_tiered (ktc.py) into supporting
        → tier_by_user = strength_tiers(current roster KTC)   [computed before grading]
grade_trade(... tier_by_user, tiered_values)  →  snapshot Trade Value (Phase 2)
rating_signals.pick_holdings_value(... tier_by_roster, tiered_values) → draft_capital (Phase 1)
```

## Error handling

- Missing tiered value → round-average → 0. Unknown original owner → round-average.
- <3 owners → all "mid" (no meaningful ranking). All existing try/except refresh
  guards remain; tiering never throws on missing data.

## Blast radius (Phase 2)

`grade_snapshot_value` feeds: the trade page "Trade Value", owner rollups, the GM
rating trade-impact **value** signal, and became-grades. Tiering shifts these
numbers (more accurately). Verified by re-grading on prod and confirming Trade
Value moved sensibly (early-pick hauls up, late-pick hauls down), not broken.

## Out of scope (YAGNI)

- Tiering the at-trade historical value (no historical roster strength stored).
- Projecting tier per future season separately (one current-strength tier per
  team, applied to all outlook seasons).
- Tiering resolved picks (already valued as the drafted player).

## Files touched

**Shared / Phase 1**
- `src/sleeper_dynasty/api/ktc.py` — capturing tier group, `parse_pick_name_tiered`, `build_pick_value_table_tiered`
- `src/sleeper_dynasty/engine/draft_signals.py` — `strength_tiers`, `tiered_pick_value`, `pick_holdings_value` tier args
- `api/app/services/grader_io.py` — `pick_value_table_tiered` into `supporting`
- `api/app/services/rating_signals.py` — tiers + tiered table into `pick_holdings_value`
- `web/components/Leaderboard.tsx` — `draft_capital` help mentions tiering
- tests: `tests/test_ktc*.py` (or new), `tests/test_draft_signals.py`, `api/tests/test_rating_signals_draft.py`

**Phase 2**
- `src/sleeper_dynasty/engine/trade_grader.py` — `_ktc_value` / `grade_snapshot_value` / `grade_trade` tier args
- `api/app/services/grader.py` — compute `tier_by_user` before grading, thread into `grade_trade`
- tests: `tests/test_trade_grader*.py`
