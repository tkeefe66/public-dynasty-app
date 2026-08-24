# Draft Capital (live) + Draft Skill (new) — Design

**Date:** 2026-06-10
**Status:** Approved (pending spec review)

## Goal

Make the GM rating's **Outlook** pillar account for the draft properly, in two ways:

1. **Draft Capital** — go live (it's currently stubbed at `0.0`). Value the future
   rookie-draft picks each owner holds, KTC-weighted.
2. **Draft Skill** — new signal. Judge how well the players an owner actually
   drafted have panned out, measured against what their draft slot usually
   returns, so a hoarder of high picks who drafts badly rates below a sharp
   drafter with the same capital.

Both are surfaced as their own traceable rows in the breakdown panel and worked
into the LLM blurb's forward-look.

## Decisions (all confirmed)

| Topic | Decision |
|---|---|
| Draft Capital valuation | KTC-weighted: value the picks an owner holds across the outlook seasons by the KTC pick-value table. |
| Draft Skill — structure | **Separate** Outlook signal alongside Draft Capital (not a discount multiplier). |
| Draft Skill — drafts counted | **Rookie drafts only.** The inaugural startup draft (chain's origin season) is excluded — it's a different skill. Surfaced in the UI help tip. |
| Draft Skill — measure | **Vs slot tier**: per-pick outcome minus the expected outcome for that pick's **early / mid / late tier within its round** (not whole-round, not exact slot). |
| Draft Skill — outcome metric | **Blend**: `0.5·z(current KTC) + 0.5·z(total career production)`. Production is total `players_points` across all roster-weeks (benched included), NOT owner-started points. |
| Draft Skill — credit | **Whoever made the selection** (`picked_by`, fallback to the slot roster's current owner). |
| Outlook weights | Roster Value **0.35**, Draft Capital **0.25**, Draft Skill **0.20**, Youth **0.20** (was 0.40 / 0.35 / — / 0.25). |
| Rollout | **Both together**: one spec, one plan, one deploy; Outlook rebalanced once. |
| Outlook season window | **Dynamic**: next 3 seasons after the league's current season (no longer hardcoded `[2027,2028,2029]`). |

## Existing machinery (confirmed)

- Sleeper client already has `get_traded_picks`, `get_drafts`, `get_draft_picks`
  (`src/sleeper_dynasty/api/sleeper.py`).
- Draft-pick rows carry `player_id`, `round`, `draft_slot`, `roster_id`,
  `picked_by`.
- `ktc_by_player_id` (current KTC) and `pick_value_table` (`(season,round) -> KTCValue`)
  are already in `supporting`.
- `Matchup.players_points: dict[player_id -> float]` (benched included) is pulled,
  so per-player total production is a sum across all matchup roster-weeks.
- The stub: `api/app/services/rating_signals.py` sets `draft_capital: 0.0`.
- Outlook signal weights: `engine/gm_rating.py` `SIGNAL_WEIGHTS["outlook"]`.

## Architecture

### New engine module: `src/sleeper_dynasty/engine/draft_signals.py`

Two pure, unit-tested functions (no I/O).

**1. `pick_holdings_value(...)` — Draft Capital**

```
pick_holdings_value(
    traded_picks: list[DraftPick],     # current league's traded picks
    roster_ids: list[int],
    seasons: list[int],                # the outlook window
    num_rounds: int,
    pick_values: dict[tuple[int,int], float],  # (season,round) -> KTC superflex value
) -> dict[int, float]                   # roster_id -> total KTC value of held picks
```

- Start from the default slate: every roster owns its own `(season, round)` pick
  for each `season` in the window and each `round` in `1..num_rounds`.
- Apply `traded_picks`: a pick is identified by `(season, round, original_roster)`;
  its owner becomes `current_owner_id`. (Reassign, no double-count — this is the
  reason for a fresh helper rather than the engine's count-based
  `analyze_draft_capital`, which double-counts a re-acquired own pick.)
- Value = Σ `pick_values[(season, round)]` over the picks each roster holds.
  Missing `(season,round)` in the table → 0 (far-future picks KTC hasn't published).

**2. `draft_skill(...)` — Draft Skill**

```
draft_skill(
    picks: list[DraftedPick],   # rookie-draft picks: {draft_id, round, slot, picks_in_round, player_id, drafter_id}
    ktc_by_player: dict[str, float],
    production_by_player: dict[str, float],
    shrink_k: float = 3.0,
) -> dict[str, float]            # drafter_id -> shrunk average skill-vs-expectation
```

Input is **rookie-draft picks only** (startup excluded upstream — see refresh
wiring). `slot` is the 1-based pick position within the round; `picks_in_round`
is that round's size (number of teams).

Steps:
1. **Outcome per drafted player** (comparable units): z-score `ktc_by_player`
   and `production_by_player` across the rookie-drafted set, blend
   `outcome = 0.5·z_ktc + 0.5·z_prod`. A player absent from KTC → KTC term from
   0; production defaults 0.
2. **Tier:** split each round into thirds by `slot` → `early` (first third),
   `mid`, `late` (last third). `tier_index = min(2, (slot - 1) * 3 // picks_in_round)`.
3. **Expectation:** group picks by `(draft_id, round, tier)`; expectation = mean
   `outcome` within that group. Grouping per draft removes season-to-season class
   strength; the tier split means a late-first is judged against other late-firsts.
   If a `(draft, round, tier)` group has fewer than 2 picks, widen it to
   `(draft, round)` so the expectation isn't a player compared only to itself.
4. **Per-pick skill** = `outcome − expectation`.
5. **Per-owner** = `Σ skill / (n_picks + shrink_k)` (shrinks small samples toward
   0). Owners with no rookie picks → 0.

Returned values are raw; `compute_gm_ratings` z-scores them across owners like
every other signal.

### Refresh wiring (`api/app/services/grader.py` + `grader_io.py`)

Alongside the existing current-roster fetch, fetch (each wrapped so failure
degrades to a neutral signal + a warning, never fails refresh):

- `traded_picks = await client.get_traded_picks(current_league_id)` (capital).
- For each league in the chain: `get_drafts` → for each completed draft,
  `get_draft_picks`. **Exclude the inaugural startup draft** — the draft in the
  chain's origin (earliest) season; every later season's completed draft is a
  rookie draft. Normalize each rookie pick to
  `{draft_id, round, slot, picks_in_round, player_id, drafter_id}` where `slot`
  is `draft_slot` (position in the round), `picks_in_round` is that round's team
  count, and `drafter_id` = `picked_by`'s uid, falling back to the slot roster's
  current owner via `roster_to_user_by_league`. Read `settings.rounds` from the
  most recent rookie draft for `num_rounds` (else 4).

Thread `traded_picks`, the normalized `draft_picks`, and `num_rounds` into
`compute_rating_signals`.

### `compute_rating_signals` (`api/app/services/rating_signals.py`)

- **Outlook season window:** `current = max(league_season_by_id.values())`;
  `outlook_seasons = [current+1, current+2, current+3]`.
- **Draft Capital:** call `pick_holdings_value(...)`, map `roster_id -> uid`,
  emit per-owner value (replaces the `0.0` stub).
- **Production map:** `production_by_player[pid] = Σ players_points[pid]` across
  every matchup roster-week in `supporting["matchups"]`.
- **Draft Skill:** call `draft_skill(...)` with the normalized picks, current KTC,
  and the production map; emit per-owner value.
- Outlook signal dict becomes `{roster_value, draft_capital, draft_skill, youth}`.

### `engine/gm_rating.py`

`SIGNAL_WEIGHTS["outlook"] = {"roster_value": 0.35, "draft_capital": 0.25, "draft_skill": 0.20, "youth": 0.20}`.

### Blurb coupling

- `engine/gm_rating_blurb.py`: add `draft_skill: "Draft Skill"` to `SIGNAL_LABELS`;
  set the facts' `draft_capital_counted = True` (both draft signals now live).
- `llm/prompts/gm_rating_blurb_persona.md`: remove the "do not mention draft
  capital (not counted)" rule; allow the forward-look to reference pick-rich /
  pick-poor capital and sharp / poor drafting. Blurbs regenerate next refresh.

### Frontend (`web/components/Leaderboard.tsx`)

- `SIGNAL_LABELS`: add `draft_skill: "Draft Skill"` (Draft Capital already labeled).
- `SIGNAL_HELP`: new copy for `draft_skill` — must state it's judged on **rookie
  drafts only** and measured against the pick's slot tier (e.g. "How your rookie
  picks panned out vs what their draft slot usually returns. Rookie drafts only —
  the startup draft doesn't count."). **Update** `draft_capital` help (remove
  "not wired up yet — currently 0 for everyone"). The breakdown renders signals
  dynamically, so the new row appears automatically with its `?` help.

## Data flow

```
refresh → fetch traded_picks (current league) + drafts/picks (chain)
        → rating_signals: outlook_seasons (dynamic), production map (matchups)
        → draft_signals.pick_holdings_value  -> draft_capital per owner
        → draft_signals.draft_skill          -> draft_skill per owner
        → outlook_signals {roster_value, draft_capital, draft_skill, youth}
compute_gm_ratings (z-score each, Outlook weights 0.35/0.25/0.20/0.20)
        → GMRow.pillars.outlook  → panel rows + blurb facts → blurb
```

## Error handling

- Any draft/pick/traded-pick fetch failure: that signal degrades to 0 for all
  owners (neutral) + a warning; refresh always completes (mirrors the existing
  rating-signal and blurb stages, both already try/except-wrapped).
- Player missing from KTC → 0 KTC term; missing from production → 0. Owners with
  no drafts → draft_skill 0. `(season,round)` missing from pick table → 0 value.

## Testing

- `engine/draft_signals.py`:
  - `pick_holdings_value`: default slate valued correctly; a traded-away pick
    moves value to the acquirer; re-acquired own pick is not double-counted;
    missing `(season,round)` → 0.
  - `draft_skill`: a late-tier steal scores positive, an early-tier bust
    negative; tier grouping (a late-first is judged vs other late-firsts, not
    early-firsts); the small-tier fallback to `(draft, round)`; KTC/production
    blend; small-sample shrinkage; no-rookie-pick owner → 0.
  - rookie-draft selection: the origin-season startup draft is excluded.
- `rating_signals`: integration test that `draft_capital` and `draft_skill` are
  non-zero and rank pick-rich/sharp owners above pick-poor/weak ones (fake
  matchups, drafts, traded_picks, KTC).
- `gm_rating`: Outlook still sums correctly with 4 signals and new weights.
- Blurb facts test: `draft_capital_counted` now `True`.
- Frontend: tsc; the new `Draft Skill` row + `?` render.

## Out of scope (YAGNI)

- Recency weighting of older drafts (all rookie drafts weighted equally for now).
- Exact-slot expectation (we use early/mid/late tiers within a round, not the
  exact pick number — sample-stable).
- KTC-weighting the Draft *Capital* by exact pick slot beyond the round-level
  pick-value table (the table is round-level; that's sufficient).

## Files touched

**New**
- `src/sleeper_dynasty/engine/draft_signals.py` (`pick_holdings_value`, `draft_skill`)
- `tests/test_draft_signals.py`

**Modified**
- `api/app/services/grader.py` and/or `grader_io.py` — fetch traded picks + drafts/picks, thread through
- `api/app/services/rating_signals.py` — dynamic window, production map, both signals, un-stub
- `src/sleeper_dynasty/engine/gm_rating.py` — Outlook weights + `draft_skill`
- `src/sleeper_dynasty/engine/gm_rating_blurb.py` — `draft_skill` label, `draft_capital_counted` True
- `src/sleeper_dynasty/llm/prompts/gm_rating_blurb_persona.md` — allow draft mentions
- `web/components/Leaderboard.tsx` — `draft_skill` label + help, update `draft_capital` help
- `api/tests/test_rating_signals*.py`, blurb-facts test — coverage
```
