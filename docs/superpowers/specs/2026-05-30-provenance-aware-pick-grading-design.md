# Provenance-Aware Pick Grading — Design

**Date:** 2026-05-30
**Status:** Approved, ready for implementation plan
**Scope:** Phase 1 of a two-phase effort. Phase 2 (incremental caching of sealed
historical seasons) is deliberately out of scope here — see "Relationship to
Phase 2" at the end.

## Problem

A traded draft pick currently resolves to the player drafted with it in **every
trade that pick ever appeared in**, because resolution (`trade_history.py:128`)
is keyed only on `(original_owner_user_id, season, round)` and is blind to *who
was holding the pick when the draft actually happened*.

Concrete failure case — the pick is flipped before it is used:

> Team A trades a player **and a pick** to Team B. Team B never drafts with the
> pick — they flip it to Team C for a player. Team C drafts the player.

Today, the pick resolves to that drafted player in **both** the A↔B trade and
the B↔C trade. Consequences:

- **Display:** the A↔B trade shows Team B receiving a player they never rostered.
- **Production / impact phantom (`trade_grader.py:125`, `215`):** the given-side
  phantom logic penalizes **both** A and B for the full production of the drafted
  player. A pick A traded away — two steps removed from the drafter — haunts A.
- **Snapshot:** this lens already telescopes to zero in the per-owner aggregate
  (the pick comes in `+` in A↔B and goes out `−` in B↔C), so the *aggregate* is
  not wrong — but the per-trade attribution and display still are.

## Grading philosophy (decided)

**Self-contained, today's market value, provenance-aware resolution.**

- Each trade is judged on the assets literally exchanged. A flipped pick is
  valued **as a pick**, not as the player some later team drafted with it.
- The reason lineage ("credit B with the player they eventually got for the
  pick") is *wrong*: every owner's record is already the sum of **all** their
  trades (`aggregate_owner_records`, `trade_grader.py:261`). B's gain from the
  player they got in B↔C is already counted in the B↔C trade. Crediting it back
  into A↔B double-counts it.
- Because a pick is valued **identically** whether shown as a pick or as the
  drafted player (today's KTC of the drafted player), the snapshot lens
  **telescopes to zero** for any team that merely passed the pick through.
  Provenance therefore does **not** change snapshot aggregate math — it fixes
  **(a)** the display and **(b)** the production/impact phantom attribution.
- **Snapshot uses today's value** (matching how player KTC is already applied),
  not value-at-trade-time.

## Resolution rule

A pick resolves to its drafted player in **exactly one trade**: the trade that
delivered it to the team that actually drafted with it ("the resolution trade").
In every earlier trade the pick stays a pick.

- **Pick identity:** `(original_owner_user_id, season, round)`.
- **Final holder:** for each pick identity, collect every normalized trade
  touching it ordered by `traded_at`; the receiver of the chronologically last
  trade is the final holder, and that last trade is the resolution trade.
- **Cross-check (non-fatal):** the `roster_id` on the matching Sleeper drafted-
  pick row (mapped to a user via that season's `roster_to_user`) should equal the
  final holder. On mismatch, log a warning and trust the timeline — do not crash.

## Components

### 1. Provenance pass — *new, `engine/trade_history.py`*

After normalization, before resolution, build a map
`pick_identity -> resolution_trade_id` from the chronologically-ordered trades
touching each pick identity. Feed this into `resolve_assets` so it knows which
single trade may upgrade a `PickAsset` to a `PlayerAsset`.

### 2. `PickAsset` model change — *`models/trade.py`*

Add two optional fields, populated whenever the pick's draft is complete
**regardless of whether this is the resolution trade**:

- `drafted_player_id: str | None`
- `drafted_player_name: str | None`

Used purely for snapshot valuation of non-resolution-trade picks. Production and
impact continue to gate on `isinstance(asset, PlayerAsset)`, so a `PickAsset`
carrying these fields still contributes **zero** to those lenses.

### 3. Resolution — *modified `resolve_assets` / `_resolve_one_asset`*

- In the **resolution trade**: upgrade `PickAsset` → `PlayerAsset` (with the
  existing `via_pick` back-reference). Counts for all three lenses.
- In **every other trade**: keep it a `PickAsset`, but annotate
  `drafted_player_id` / `drafted_player_name` when the draft is complete.
- Future / undrafted / forfeited picks: stay `PickAsset` with no drafted player.

### 4. Snapshot valuation — *modified `trade_grader.py:_ktc_value`*

| Asset | Snapshot value |
|---|---|
| `PlayerAsset` | today's KTC by `player_id` (unchanged) |
| `PickAsset` **with** `drafted_player_id` | today's KTC of that player |
| `PickAsset` **without** (future/undrafted) | round-level KTC pick value (new lookup) |
| `FaabAsset` | 0 (unchanged) |

Valuing a drafted-but-unresolved pick at the drafted player's current KTC is what
makes the snapshot lens telescope to zero across pass-through teams.

### 5. Pick-value lookup — *new, small (KTC side)*

Parse KTC pick entries (`position == "PICK"`, names like `"2025 Early 1st"`) into
a `(season, round) -> value` table, **averaging early/mid/late** within a round
(we cannot know the slot until end-of-season standings set it). Provides values
for **future/undrafted** picks only. Missing data → `0` plus a warning, matching
the existing defensive posture for unmatched players.

### 6. Production / impact — *no logic change*

`trade_grader.py` production (`grade_hindsight_production`) and impact
(`grade_realized_impact`) are left as-is. They become correct for free: because
non-resolution picks are now `PickAsset`s, the `isinstance(asset, PlayerAsset)`
guards skip them — Team B gets 0 for a flipped pick, and only the resolution-
trade giver carries the phantom production cost.

## Data flow

```
build_trade_history
  └─ walk_league_history + fetch each season
  └─ normalize_trade (per trade)
  └─ PROVENANCE PASS (new): pick_identity -> resolution_trade_id
  └─ resolve_assets (modified): upgrade to PlayerAsset only in the
       resolution trade; annotate drafted_player_id elsewhere
  └─ grade_trade (snapshot valuation updated; production/impact unchanged)
```

## Worked example (A → B → C flip)

| Trade | B receives | B gives | B snapshot | B production |
|---|---|---|---|---|
| A↔B | A's player + **pick** | (sent to A) | `+A_KTC +X_KTC` | A-player pts on B |
| B↔C | C's player | **pick → X** | `+C_KTC −X_KTC` | C-player pts on B |
| **B net** | | | `pick cancels` | both real players |

The pick resolves to player **X** only in B↔C. In A↔B it is a `PickAsset` valued
at `X`'s current KTC (drafted) → 0 production for B. Across B's two trades the
pick nets to zero in snapshot; B is credited the production of only the players
they actually rostered; only B (the giver in the resolution trade) carries X's
phantom cost.

## Edge cases

- **Future pick** (draft incomplete) — no `drafted_player_id`; round-level pick value.
- **Forfeited / undrafted pick** (`player_id` null) — never resolves; pick-table value.
- **Traded out then re-acquired by the same team** — timeline handles it; the
  resolution trade is the re-acquisition.
- **Original owner left the league** — existing `"Owner #<roster_id>"` fallback
  identity; valuation still works.
- **Pick never traded** — appears in no trade; nothing to grade.
- **Provenance / draft-data mismatch** — warn, trust the trade timeline.

## Testing

- **Provenance unit test (the flip):** assert the pick resolves **only** in B↔C;
  A↔B shows a `PickAsset` with **0 production** for B; B's snapshot **telescopes
  to 0** across the two trades; only the B↔C giver carries phantom.
- **Pick-value lookup:** name parsing (`"2025 Early 1st"` → season 2025, round 1),
  early/mid/late round averaging, missing data → 0 + warning.
- **Resolution-trade selection:** trade-out-then-reacquire picks the re-acquisition.
- **Regression:** existing `resolve_assets` and grader tests still pass.
- Follow `superpowers:test-driven-development` — tests precede implementation.

## Out of scope

- **Value-at-trade-time snapshots.** The snapshot lens uses *today's* values
  throughout (players and picks); historical point-in-time KTC is not introduced.
- **Slot-precise future-pick values.** Future picks use a round-level average,
  not an early/mid/late estimate from projected standings.
- **Lineage / transitive grading.** Explicitly rejected (double-counts the
  aggregate).

## Relationship to Phase 2 (incremental caching)

Phase 2 will persist sealed historical seasons and re-pull/re-grade only the
current season. It depends on the resolution semantics pinned down here, because
a pick traded in an early season only *resolves* once a **later** season's draft
completes — so a stored early-season grade must invalidate when a later-season
draft lands. Locking resolution semantics first makes those invalidation rules
tractable. Phase 2 gets its own spec.
