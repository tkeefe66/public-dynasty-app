# Future & Draft Tab Redesign — Design Spec

**Date:** 2026-06-15
**Status:** Approved

## Goal

Redesign the Future & Draft owner tab to tell a clear, simple story: how good is this owner at drafting, what do they need, and what ammunition do they have. Replace the disconnected four-card layout with a narrative flow that puts the verdict first and the evidence second.

Also add URL-based tab navigation (`?tab=future`) so the Draft Ace KPI card can deep-link directly to this tab.

---

## New Tab Structure

### Section 1 — Draft Skill Verdict (hero)

A single clean block at the top. Two elements only:

1. **Rank statement** — plain counting: "#3 of 12 in the league" or "9th of 12 in the league"
2. **One plain-English sentence** explaining why — no z-scores, no percentiles, no formulas beyond basic counting. Examples:
   - "More of your picks have outperformed their draft slot than missed. Your 2024 class was especially strong."
   - "More of your picks have underperformed their slot than exceeded it, though recent classes show improvement."

Nothing else in this section. No bars, no score numbers, no math beyond rank/count.

---

### Section 2 — Draft Needs

Unchanged from current: position · urgency · reason list. No redesign.

---

### Section 3 — Pick Arsenal

Two sub-sections in one card, flowing top-to-bottom:

#### Part A: Future picks

Current season-card layout unchanged (chips by round per season). Shows all held future picks.

#### Part B: Past picks table

Year tabs defaulting to the most recent completed rookie draft. One tab per completed rookie draft season in the league chain (e.g., 2024 · 2025). Startup draft excluded (per existing `build_rookie_picks` logic).

**Columns (left → right):**

| Column | Key | Tooltip |
|---|---|---|
| Player | player name | — |
| Rnd | round (1st, 2nd, 3rd…) | — |
| Acquired | "Owned" or "via trade" | — |
| Current | current value | "Today's dynasty market value." |
| Lowest | lowest tracked value | "Lowest value this player has hit since we began tracking (May 2026). Shows where the arc bottomed out." |
| Highest | highest tracked value | "Highest value this player has hit since we began tracking (May 2026). Shows the arc's peak." |
| Avg Pick Value | +/− delta vs slot average | "How much this pick is worth compared to what a player at this slot typically produces. Positive means the pick outperformed its draft position." |
| Reg Pts | started regular-season pts | "Started points in regular-season weeks while on this roster" |
| Playoff Pts | started title-bracket pts | "Started points in real title-bracket games only" |

**Acquired logic:**
- "Owned" — pick was made with the owner's original draft slot
- "via trade" — the pick was acquired via a trade before the draft

**Current / Lowest / Highest Value (the "career arc"):**
- Three fields per pick that track the asset's value trajectory: a pick/player ideally starts low/medium, spikes high, then gradually declines. One number can't show that; three can.
- **Current** = today's value. **Lowest** / **Highest** = min / max value observed across the stored daily snapshot history.
- **History constraint (must surface honestly):** value history only exists from **~May 2026 forward** — when the app began capturing daily KTC snapshots (`KtcSnapshotStore`). There is **no backfill**. For picks drafted in 2023–2025, Lowest/Highest reflect only the window since May 2026, not the pick's true career low/high. For an asset with only one snapshot, all three values are equal.
- Display: each as a plain value number. Lowest/Highest are dim relative to Current so Current reads as the headline.

**Avg Pick Value:**
- Definition: `current value − average current value of all players drafted in the same round and tier in that year's league draft`
- Display: `+1,000` (green) or `−2,800` (red). Zero = dim.
- Column header has right-aligned tooltip to prevent overflow.

**Reg Pts / Playoff Pts:**
- Same "received-only, while on roster" semantics as the dashboard columns — started points accrued to this owner since the player was drafted to their team.
- Right-aligned tooltips.

**Sort:** default by Avg Pick Value descending (best picks first). All columns sortable.

**Rows:** sorted by Avg Pick Value desc by default. Players with no KTC value (retired, dropped before KTC coverage) show Value = 0 and Avg Pick Value using 0 as current value.

---

## URL-Based Tab Navigation

Add `?tab=<key>` query param support to the owner page. On load, read `?tab` and pass as `initialTab` to `OwnerDeepDive`. Valid values: `overview`, `roster`, `future`, `trades`. Defaults to `overview` if absent or invalid.

**Draft Ace KPI card href:** `/league/{id}/owner/{uid}?tab=future`

---

## Data Requirements

### New backend fields needed

The pick table requires per-pick data not currently exposed. Add a new field to `OwnerDetailResp`:

```typescript
draft_picks_by_season: {
  [season: string]: DraftPickResult[]
}
```

Where `DraftPickResult`:
```typescript
interface DraftPickResult {
  player_id: string;
  full_name: string;
  position: string;
  round: number;
  slot: number;           // 1-based within the round
  picks_in_round: number; // total teams in the draft
  draft_season: number;
  acquired_via_trade: bool;
  current_value: number;  // today's superflex value
  lowest_value: number;   // min value across snapshot history (May 2026 forward)
  highest_value: number;  // max value across snapshot history (May 2026 forward)
  avg_slot_value: number; // average current value for players at this (round, tier) in that draft
  production_regular: number;   // started reg-season pts while on roster
  production_playoff: number;   // started playoff pts while on roster
}
```

### Computation

`current_value`: today's superflex value for the drafted player (the existing single value, renamed).

`lowest_value` / `highest_value`: min and max of the player's value across the stored daily snapshot history. Source: `KtcSnapshotStore` (the same store that powers historical price lookups). Because the store only goes back to ~May 2026, these are window-min/max, not true career extremes for 2023–2025 picks. If only one snapshot exists, `lowest_value == highest_value == current_value`. Compute during refresh alongside the other per-pick fields and store on the serialized pick (see below).

`avg_slot_value`: compute during owner detail build from `entry.draft_skill_by_season[str(season)]` raw pick data. Specifically: group all picks in `(season, round, tier)` by their current value; `avg_slot_value` = mean of that group.

`acquired_via_trade`: `DraftedPick.drafter_id` picked the player. Cross-reference with the original slot ownership via the `traded_picks` list — if the slot's original owner != the drafter, it was acquired.

`production_regular` / `production_playoff`: filter `entry.grades` for trades where this player was `received` by this owner, sum `production_regular` and `production_playoff` contributed by that player.

### Where to compute

In `api/app/services/owner_view.py::build_owner_detail`. The `rookie_picks` data is already on the engine (computed in `grader.py` and accessible via `entry`). Need to store `DraftedPick` list on `ChainCacheEntry` during refresh, or recompute from stored data.

**Simpler alternative:** add `drafted_picks: list[dict]` to `ChainCacheEntry` (serialized `DraftedPick` objects, each carrying `current_value` / `lowest_value` / `highest_value` resolved at refresh time) during refresh. `build_owner_detail` reads this and builds the per-owner, per-season table. Resolving lowest/highest at refresh (not request) time keeps the snapshot-history scan off the hot path.

### Follow-on (out of scope here, tracked separately)

The same career-arc value lens (Current / Lowest / Highest) is intended to extend to **trade analysis** — e.g. "was the player sold near his peak or still rising; did the receiver buy near the bottom?" That is an explicit follow-on, not part of this tab. Captured in memory (`asset-value-career-arc`).

---

## Non-Goals

- No redesign of Overview, Roster & Health, or Trades tabs.
- No changes to the hero band.
- No mobile-specific layout for the pick table (horizontal scroll acceptable on mobile).
- Startup draft picks not shown (consistent with current draft skill computation).
