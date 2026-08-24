# Window Classification v2 — Design Spec

**Date:** 2026-06-14
**Status:** Approved

## Goal

Replace the current 3-signal decision tree (KTC rank, avg age, draft capital status) with a two-axis framework — **Strength** × **Trajectory** — that incorporates draft skill (are their picks panning out?) and recent competitive history (have they proven they can win?). Keep the same 5 labels: Competing now / Ascending / Peaking / Descending / Rebuilding.

## Why the Current System Falls Short

The current `classify_window` uses:
1. KTC roster rank percentile
2. Average age of skill-position players
3. Draft capital status (pick-rich / neutral / pick-poor)

What it ignores that we already have:
- **Draft skill** (`outlook_signals["draft_skill"]`) — a team sitting on 10 picks with a −0.3 skill score is not the same as one with +0.8. Both are currently "pick-rich."
- **Proven competitive history** (`outcome_signals["made_playoffs"]`) — a team that has made the playoffs every season with their current core deserves more Strength credit than an identically-valued roster that's never made it.
- **Youth quality** — average age treats a roster with 2 elite 23-year-olds and 8 aging vets the same as a uniformly young roster. What matters is what **fraction of KTC value** is in players ≤25.
- **Momentum** — direction of travel matters. A team whose GM rating rose 150 points last season is different from one that fell 150.

---

## Signal Definitions

### Strength Signals

| Signal | Formula | Source |
|---|---|---|
| KTC roster rank score | `(1 − rank_pct) × 100` | `roster_ranks[uid]` on ChainCacheEntry |
| Playoff rate | `made_playoffs_rate × 100` | `outcome_signals[uid]["made_playoffs"]` (0.0–1.0 fraction of seasons made playoffs) |

### Trajectory Signals

| Signal | Formula | Source |
|---|---|---|
| Youth quality % | `young_ktc / total_ktc × 100` where young = players ≤25 | Computed in `build_dynasty_outlook` from `ktc_value_by_player` + player ages |
| Draft skill z-score | `max(0, min(100, 50 + z × 25))` | `outlook_signals[uid]["draft_skill"]` (already a z-score) |
| Draft capital rank | `(1 − draft_capital_pct_rank) × 100` | Cross-league percentile rank of `outlook_signals[uid]["draft_capital"]` value |
| YoY GM rating change | `max(0, min(100, (delta + 200) / 4))` | `season_ratings[current_year][uid] − season_ratings[prev_year][uid]`; ±200 → 0–100 |

---

## Score Functions

```python
def compute_strength_score(roster_rank_pct: float, playoff_rate: float) -> float:
    """0–100. roster_rank_pct: 0.0=best, 1.0=worst. playoff_rate: 0.0–1.0."""
    return 0.60 * (1 - roster_rank_pct) * 100 + 0.40 * playoff_rate * 100


def compute_trajectory_score(
    youth_quality_pct: float,      # 0.0–1.0
    draft_skill_z: float,          # league z-score, typically −2 to +2
    draft_capital_pct_rank: float, # 0.0=most capital, 1.0=least
    yoy_rating_delta: float,       # raw GM rating change, typically −300 to +300
) -> float:
    """0–100."""
    youth_score         = min(100.0, youth_quality_pct * 250)   # 40% young = 100
    draft_skill_score   = max(0.0, min(100.0, 50 + draft_skill_z * 25))
    draft_capital_score = (1 - draft_capital_pct_rank) * 100
    yoy_score           = max(0.0, min(100.0, (yoy_rating_delta + 200) / 4))
    return (
        0.35 * youth_score +
        0.30 * draft_skill_score +
        0.25 * draft_capital_score +
        0.10 * yoy_score
    )
```

---

## Updated `classify_window`

```python
def classify_window(
    strength: float,
    trajectory: float,
    draft_capital_status: str,  # "pick-rich" | "neutral" | "pick-poor"
) -> str:
    if strength >= 60:
        return "Competing now" if trajectory >= 50 else "Peaking"
    if strength < 40:
        if trajectory >= 55:
            return "Ascending"
        return "Rebuilding" if draft_capital_status == "pick-rich" else "Descending"
    # Middle zone (40–60 strength)
    if trajectory >= 60:
        return "Ascending"
    if trajectory < 40:
        return "Descending"
    return "Ascending"  # default optimistic for mid-pack
```

---

## Data Model Changes

### `DynastyOutlook` (engine/dynasty.py)

Add two fields:

```python
@dataclass
class DynastyOutlook:
    window: str
    age_profile: AgeProfile
    draft_capital: DraftCapital
    draft_needs: list[DraftNeed]
    trajectory: str
    strength_score: float = 0.0      # NEW: 0–100 Strength axis value
    trajectory_score: float = 0.0    # NEW: 0–100 Trajectory axis value
```

### `outlook_to_dict` (engine/outlook_build.py)

Export the two new scores:

```python
"strength_score": outlook.strength_score,
"trajectory_score": outlook.trajectory_score,
```

### `ChainCacheEntry.dynasty_outlooks`

No structural change — `outlook_to_dict` already produces a plain dict, and the two new keys land there automatically. Old caches (missing the keys) return `None` gracefully via `.get()`.

---

## Architecture: Data Flow

```
grader.py
  ├─ compute_rating_signals(...)      → outcome_signals, outlook_signals
  ├─ build_outlooks_by_owner(...)     ← gains 3 new optional params:
  │     draft_skill_by_uid            from outlook_signals["draft_skill"]
  │     playoff_rate_by_uid           from outcome_signals["made_playoffs"]
  │     season_ratings                from entry.season_ratings (already set)
  └─ stores dynasty_outlooks on entry (now includes strength_score, trajectory_score)
```

### `build_outlooks_by_owner` new params (all optional, default empty)

```python
def build_outlooks_by_owner(
    *,
    rosters: list[Roster],
    players: dict[str, Player],
    traded_picks: list[DraftPick],
    positions: dict[str, str],
    ktc_value_by_player: dict[str, float],
    roster_to_user: dict[int, str],
    total_rosters: int,
    num_rounds: int = 4,
    # New:
    draft_skill_by_uid: dict[str, float] | None = None,
    playoff_rate_by_uid: dict[str, float] | None = None,
    yoy_rating_by_uid: dict[str, float] | None = None,
) -> dict[str, DynastyOutlook]:
```

Inside, before per-owner loop:
1. Compute `draft_capital_pct_rank_by_uid` by ranking `outlook_signals[uid]["draft_capital"]` values descending across all owners; owner with most capital gets rank 0 (pct = 0.0), least gets pct = 1.0. `outlook_signals` is passed in from grader.py where it's already available.

### `build_dynasty_outlook` new params (all optional)

```python
def build_dynasty_outlook(
    ...existing params...,
    draft_skill: float = 0.0,
    playoff_rate: float = 0.0,
    yoy_rating_delta: float = 0.0,
    draft_capital_pct_rank: float = 0.5,
) -> DynastyOutlook:
```

Inside, after `analyze_age_profile` and `analyze_draft_capital`:
1. Compute `youth_quality_pct` from `ktc_value_by_player` and player ages
2. Call `compute_strength_score(projected_rank_pct, playoff_rate)`
3. Call `compute_trajectory_score(youth_quality_pct, draft_skill, draft_capital_pct_rank, yoy_rating_delta)`
4. Call `classify_window(strength, trajectory, draft_capital.status)`
5. Store `strength_score` and `trajectory_score` on `DynastyOutlook`

---

## Methodology Page Updates

Add three new explanations to `/methodology`:

**Window** — "A team's dynasty stage, computed from two scores. Strength (60% KTC roster rank + 40% all-time playoff rate) measures how good the team is right now. Trajectory (35% youth quality, 30% draft skill, 25% draft capital, 10% year-over-year momentum) measures which way they're headed. The five stages — Competing now, Ascending, Peaking, Descending, Rebuilding — map from the intersection of those two scores."

**Draft Capital** — "KTC market value of all future rookie picks currently held, tiered by the originating team's current roster strength (weaker team → early pick → more valuable). Not year-scoped — always reflects today's holdings."

**Grade** — "Letter grade (A through D) derived from your Trade Value relative to your leaguemates. All owners are z-scored against the league mean and bucketed: A ≥ +1.25σ, A− ≥ +0.75σ, B+ ≥ +0.25σ, B near 0, B− ≥ −0.75σ, C ≥ −1.25σ, D below."

---

## Non-Goals

- No recency weighting of `playoff_rate` (uses all-time rate for now; can be refined later)
- No changes to `trajectory` (the text narrative field) — it stays as-is
- No new API endpoints
- No UI changes beyond what already exists (Window pill, methodology page)
- No changes to how Window is displayed (still the same colored pill)

---

## Edge Cases

- **No season_ratings** (first refresh, no prior year): `yoy_rating_delta = 0` → YoY score = 50 (neutral)
- **No draft skill** (startup-only league, no rookie drafts): `draft_skill_z = 0` → score = 50 (neutral)
- **No playoff history** (new league, 0 seasons): `playoff_rate = 0` → reduced Strength score, correctly
- **All picks held by one owner**: draft capital rank still works (other owners rank 0 capital at bottom)
