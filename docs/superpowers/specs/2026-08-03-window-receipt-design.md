# Window Receipt — Design

**Date:** 2026-08-03
**Status:** Approved

## Problem

The Window chip (Competing now / Peaking / Ascending / Descending / Rebuilding) on the
Franchise Rankings table ships with no receipt. `classify_window`
(`engine/dynasty.py`) computes a Strength score and a Trajectory score from six
weighted inputs, applies hard thresholds, and returns **only the label string**. A
user staring at "Descending" on a 24-18 team has no way to see why. This is the one
verdict-style chip without the traceability standard set by Franchise Rating
(`compute_gm_ratings` returns pillar → signal → raw/z/weight/contribution).

Secondary defect: the StandingsTable Window header tooltip misstates the formula
(omits playoff rate, draft skill, and YoY momentum).

## Decisions (from brainstorm)

- **Surface:** clicking the Window chip navigates to the owner page's Outlook tab,
  which gains a Window section as its first block. No popover, no methodology
  calculator.
- **Depth:** full input breakdown — both axis scores AND their six weighted inputs.
- **Visualization:** quadrant map (Strength × Trajectory with stage regions) plus
  per-input contribution bars.
- **LLM:** none. The explanatory sentence is deterministic, templated from the
  numbers in frontend code. Keeps LLM spend flat.
- **Computation site:** engine, persisted with the outlook (Approach A). The
  API-recompute alternative was rejected because the formula would live in two
  places and the receipt could drift from the label — fatal for a validation
  feature.

## Architecture

### 1. Engine (`src/sleeper_dynasty/engine/dynasty.py`)

The axis score is **derived from** the receipt, not computed alongside it, so the
two can never disagree.

New dataclasses:

```python
@dataclass
class WindowInput:
    key: str            # e.g. "roster_value_rank", "playoff_rate", "draft_skill",
                        # "draft_capital", "youth", "yoy_momentum"
    raw: float          # the input as consumed (pct, z-score, delta…)
    score: float        # normalized 0–100
    weight: float       # 0.0–1.0 within its axis
    contribution: float # weight * score

@dataclass
class WindowBreakdown:
    strength_score: float          # == sum of strength_inputs contributions
    trajectory_score: float        # == sum of trajectory_inputs contributions
    strength_inputs: list[WindowInput]    # 2 rows
    trajectory_inputs: list[WindowInput]  # 4 rows
    capital_status: str            # "pick-rich" | "neutral" | "pick-poor"
                                   # (the Rebuilding-vs-Descending tiebreaker)
```

New builders `strength_inputs(...) -> list[WindowInput]` and
`trajectory_inputs(...) -> list[WindowInput]` own the normalization;
`compute_strength_score` / `compute_trajectory_score` keep their signatures but
become thin sums over the builders' contributions, so existing callers and tests
keep working. `build_dynasty_outlook` attaches the result as
`DynastyOutlook.window_breakdown: WindowBreakdown | None = None`.
`outlook_to_dict` (`engine/outlook_build.py`) serializes it under
`"window_breakdown"`.

Classification thresholds in `classify_window` are unchanged. Labels for input
keys live in the frontend; the engine carries stable keys only.

### 2. API (`api/app/models/owner.py`, `api/app/services/owner_view.py`)

`OutlookView` gains optional fields:

- `strength_score: float | None`
- `trajectory_score: float | None`
- `window_breakdown: WindowBreakdownView | None` (mirror of the engine shape;
  `WindowInputView` rows)

`owner_view` passes them through from the cached outlook dict. Rides the existing
`dynasty_outlooks` value layer — recomputed on every refresh, so **no
`SCHEMA_VERSION` bump**. A pre-upgrade cached entry yields `None` until its next
refresh; the UI degrades to the current label-only view.

### 3. Frontend

**`web/components/ownerdeepdive/WindowSection.tsx`** — new, rendered as the first
block of the Outlook tab (so `?tab=outlook` lands on it; no hash-scroll
machinery). Renders nothing beyond the existing label stat when
`window_breakdown` is absent. Content, top to bottom:

1. Window chip + deterministic templated sentence from the numbers, e.g.
   "Strength 34 — bottom-tier roster value despite a 40% playoff rate;
   Trajectory 38 — thin draft capital outweighs solid draft skill →
   **Descending**."
2. Quadrant map: SVG, x = Trajectory (0–100), y = Strength (0–100). The five
   stage regions shaded rectilinearly per `classify_window`'s exact thresholds
   (strength ≥60 band split at trajectory 50; strength <40 band with the ≥68
   Ascending cut; middle 40–60 band split at 40/60); the weak/low-trajectory
   cell annotated with the capital-status tiebreak (Rebuilding if pick-rich,
   else Descending). Team plotted as a dot with its scores.
3. Input bars: two groups (Strength: 2 rows, Trajectory: 4 rows). Each row:
   label, formatted raw value, contribution bar, weight caption. Styled with the
   existing CSS-token palette; consult the dataviz skill before implementing the
   chart pieces.

**`web/components/StandingsTable.tsx`:**

- The Window chip becomes a click-target *inside* the existing row-level `Link`
  (button with `stopPropagation`/`preventDefault` → `router.push` to
  `/league/{leagueId}/owner/{user_id}?tab=outlook`), with a hover affordance so
  it reads as clickable.
- Header tooltip body corrected to the real formula: Strength (roster value +
  playoff rate) × Trajectory (draft skill, draft capital, youth, momentum), plus
  "click a chip for the full breakdown."

**`web/lib/types.ts`:** `WindowInput` / `WindowBreakdown` types; `OutlookView`
additions mirrored.

### Data flow

refresh → `build_outlooks_by_owner` → `build_dynasty_outlook` (builds breakdown)
→ `outlook_to_dict` → `ChainCacheEntry.dynasty_outlooks` → `owner_view` →
`OutlookView.window_breakdown` → owner page Outlook tab → `WindowSection`.

## Error handling

- Missing breakdown (stale cache): every layer treats it as `None`; the Outlook
  tab shows the existing label-only stat. No 500s, no placeholder junk.
- Missing signals at build time (e.g. no draft-skill history): inputs default as
  today (0.0 / 0.5 neutral); the receipt shows those neutral values honestly
  rather than hiding rows.

## Testing

- **Engine (pytest):** each axis's rows sum exactly to its score; weights per
  axis sum to 1.0; classification output unchanged against existing fixtures;
  `outlook_to_dict` round-trips the breakdown.
- **API (pytest):** `owner_view` passthrough; tolerance test with a cached
  outlook dict lacking `window_breakdown`.
- **Frontend (vitest):** WindowSection renders 2+4 rows and positions the dot
  from a fixture breakdown; renders fallback without one; StandingsTable chip
  navigates with the tab param and the row link is not triggered; tooltip text
  assertion updated.

## Out of scope

- LLM narrative for the window (deterministic sentence only).
- Popover/inline breakdown on the rankings table.
- Methodology-page live calculator.
- Any change to `classify_window` thresholds or the window taxonomy.
