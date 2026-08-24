> _Historical doc — paths/names have changed. Repo is now `Code Apps/public-dynasty` (GitHub `tkeefe66/public-dynasty-app`), Railway project **shimmering-nature**, live at https://ffbdynasty.com. Ignore stale refs to `sleeper-dynasty` / `sleeper-trade-grader` / `web-production-f949`._

# Trade Story — Realized Haul in the Facts Packet

**Date:** 2026-06-13
**Status:** Design approved, pending spec review

## Problem

A trade's LLM story currently reads "day-of": it describes what each side
*received* at the moment of the trade, but is blind to what those assets
*became*. Concrete report:

> In [this trade](https://web-production-f949.up.railway.app/league/9000000000000000001/trade/1356766106819256320),
> ChocGummyBear received 2 picks, drafted a player, and dropped him before the
> season even started. The story never mentions this.

Two failures, one root cause:

1. **No re-fire on the drop.** Stories regenerate when the trade's
   `facts_hash` changes (`api/app/services/story_gen.py:62-66` diffs the
   freshly-built `TradeStoryFacts` against the cached one and skips on a match).
   The drop never changes the packet, so it never triggers a regen.
2. **No fact to tell.** Even on the next natural regen, the writer has nothing
   to say: the picks appear only as `PickOutcome` rows with
   `became_player="<drafted player>"` and `points_per_game=None`. There is no
   "was he dropped / did he ever play / what did he score" signal anywhere in
   the packet.

The engine *already computes* the drop everywhere else:
`engine/lineage.py::_terminal_node` tags `terminal_state="dropped"` when the
owner no longer holds the terminal player, and `realized_received_values` prices
a dropped player at `0.0`. The became-grade and the trade-detail journey both
surface it. **The story facts builder simply never consumes it.**

## Decisions (from brainstorming)

- **Scope: general, not a point patch.** Feed every received asset's *realized
  terminal fate* into the packet (kept on roster / flipped / dropped /
  undrafted, plus the production the haul actually scored). The
  drafted-then-dropped case falls out for free, and any future lineage
  evolution (a pick resolving, a player flipped, an asset dropped)
  auto-re-fires the story with the new beat.
- **Narrative stance: always tell the current truth.** The regenerated story
  reflects how the deal looks *now*; each regen fully replaces the prior story.
  The packet stays **stateless** — no memory of past versions, no then-vs-now
  diffing. This matches how `facts_hash` already works.
- **Additive, not replacement.** Keep the existing day-of `player_arcs` /
  `pick_outcomes` (they anchor the "what each side gave up" framing) and *layer*
  the realized view on top. The writer selects the current truth from both.

## Architecture

One idea: the facts packet should describe what each side's assets *became*,
reusing the exact bounded lineage walk the became-grade already uses
(`engine/lineage.py::terminal_assets` / `build_trade_lineage`). Because the
regen trigger keys off the packet's contents, surfacing the realized fate gives
us both halves at once — the drop changes the hash (→ re-fire) **and** gives the
writer a fact to tell.

No new lineage walk is introduced. The facts builder already constructs the
lineage tree (`flipped_tree` in `build_trade_story_facts`); we extend that same
pass to read terminal state and build production arcs for terminal players.

### 1. Model — `src/sleeper_dynasty/models/trade_story.py`

**`PickOutcome`** — add the missing realized fate:

- `terminal_state: str` — one of `"kept"` | `"dropped"` | `"flipped"` |
  `"undrafted"`.
  - `kept` — pick drafted into a player the owner still rosters (or rostered
    through the season).
  - `dropped` — pick drafted into a player the owner cut.
  - `flipped` — pick (or its draftee) was traded on again; pairs with the
    existing `flipped_for`.
  - `undrafted` — future pick not yet drafted.
- Populate `points_per_game` (currently always `None`) with what the drafted
  player actually scored for this owner.
- `dropped_before_week: int | None` — the NFL week the player was dropped, so
  "cut before Week 1" reads differently from "cut in Week 9." `None` when not
  dropped or not determinable.

**`PlayerArc`** — add `dropped: bool`. Today a kept-then-cut player is
indistinguishable from a kept-but-benched one (both show `starter_weeks=0`).
`dropped` makes the cut explicit. (`flipped` already exists and is unchanged.)

**`TradeStoryFacts` side dict** — add `realized_players: list[PlayerArc dict]`:
production arcs for the *terminal* players a side's picks/flips ultimately
landed (not just the directly-received players). This is what makes "the pick
became a player who scored 180" tellable. Additive to the existing
`player_arcs` / `pick_outcomes`.

All new fields flow through `to_dict()` and therefore through `facts_hash`
(`json.dumps(..., sort_keys=True)`), so any change to a realized fate changes
the hash → re-fire.

### 2. Facts builder — `src/sleeper_dynasty/engine/trade_story.py`

In `build_trade_story_facts`, extend the existing lineage pass:

- It already builds `flipped_tree = build_trade_lineage(...)` and maps each
  received asset to its lineage node (`node_of`). Read each node's terminal
  leaf `terminal_state` and stamp it onto the corresponding `PickOutcome` /
  `PlayerArc`.
- Call `lineage.terminal_assets(resolved_dicts, trade_id)` for the side and run
  the existing `build_player_arc` over each terminal *player* to produce
  `realized_players`. `dropped_before_week` derives from the player's last
  rostered week in `matchups` versus when he disappears (the same
  matchup-scan `build_player_arc` already does).
- `PickOutcome.points_per_game` / `points_total` come from the terminal
  player's arc.

Reuses `terminal_assets` — the same bounded "anti-spiderweb" walk the
became-grade consumes — so the story and the became-grade tell one story.

### 3. Writer persona — `src/sleeper_dynasty/llm/prompts/trade_story_persona.md`

Teach the realized-fate vocabulary: call out busts and cuts, frame what a pick
*actually became*, note when a haul evaporated. Remains strictly grounded — the
writer may reference only facts present in the packet (existing rule unchanged).

### 4. Regeneration — no code change

`story_gen.py` already re-fires on any `facts_hash` change. Once the realized
fate is *in* the packet, the existing incremental machinery does the rest.

**Known consequence (accepted):** this widens what contributes to the hash —
lineage-derived terminal players now factor in, alongside the directly-rostered
player arcs that already change weekly during the season. Same weekly-during-
season regen cost profile that rostered-player arcs already incur; no new cost
class.

### 5. Tests

- **Engine** (`tests/test_trade_story_engine.py`): fixture where a received
  pick is drafted into a player who is dropped before Week 1. Assert the packet
  carries `terminal_state="dropped"` and `dropped_before_week=<pre-season>` on
  the pick outcome, and that `facts_hash` of the realized packet **differs**
  from the day-of packet (proves the re-fire fires).
- **Engine**: fixture where a pick is kept and produces — assert
  `terminal_state="kept"` and non-zero `points_per_game` / a `realized_players`
  arc.
- **Writer** (`tests/test_trade_story_writer.py`): assert the realized-fate
  facts reach the serialized prompt.

## Out of scope (YAGNI)

- Then-vs-now / "how the trade aged" narration (explicitly decided against —
  stateless current-truth only).
- Persisting past story versions or a story changelog.
- Any UI change — this is engine + writer only; the trade-detail page already
  renders the journey from the became-grade.

## Files touched

- `src/sleeper_dynasty/models/trade_story.py` — new fields on `PickOutcome`,
  `PlayerArc`; `realized_players` in the side dict.
- `src/sleeper_dynasty/engine/trade_story.py` — populate realized fate from the
  existing lineage pass + `terminal_assets`.
- `src/sleeper_dynasty/llm/prompts/trade_story_persona.md` — vocabulary for
  busts/cuts/realized hauls.
- `tests/test_trade_story_engine.py`, `tests/test_trade_story_writer.py` — new
  cases.

No API or web changes; no cache-schema break (new packet fields are additive,
and a changed `facts_hash` simply triggers a one-time regen on next refresh).
