# Per-Player Stat Tables (A-frontend) — Design

**Date:** 2026-06-09
**Status:** Approved (brainstorm) → ready for implementation plan
**Supersedes:** the original "A-frontend" (simple colored two-card). This is the
version the user actually wants; it folds the colored two-card into a richer feature.

## Context & motivation

A-backend made production metrics received-only (each side its own tally). The trade
detail UI still renders them in the old swing-shaped layout. While iterating on a
"head-to-head bars" scoreboard, the user pointed at the existing **"What it became"**
card (`TradeBecame.tsx`) — two side-by-side cards, each owner showing its **own** value
for all five metrics (Trade Value included, as a gross per-side KTC, not a swing) — and
said that layout reads better, just needs winner colors. They also asked for the **big
unlock: break every metric down by player.**

So this feature turns each side's card into a **player-first stat sheet**: metrics as
columns, the haul's players as rows, side totals on top, winner-highlighted. It applies
to **both** the direct trade grade and the became grade. "Receipts over opinions": you
can now see exactly which player drove each number.

## Decisions (from brainstorm)

1. **Card = stat table.** Rows are players; columns are the five metrics
   (Trade Value/KTC, Total, Regular, Playoff, Toilet). A bold TOTAL row per side.
2. **Each team's own value, uniform** — no swings anywhere, Trade Value included. The
   TOTAL row is what gets **winner color** when compared to the other side.
3. **Both grades** get the stat table: direct (received players/picks) and became
   (terminal players).
4. **Picks** (direct only) render as a row with KTC and `—` for points (they hadn't
   played). Sorted to the bottom by KTC.
5. **Player sort:** by Total Points desc; pick rows sink below, by KTC desc.
6. **Mobile:** collapse to **Player · KTC · Total**; tap a player to reveal the
   Regular/Playoff/Toilet splits.
7. The scrapped head-to-head bar scoreboard is removed.

## Data model

A single per-asset row shape, shared by both grades:

```python
@dataclass
class AssetLine:
    label: str                 # "Davante Adams" or "2027 1st"
    kind: str                  # "player" | "pick"
    player_id: str | None
    ktc: float                 # gross current KTC value of this asset
    production_total: float    # received-only, while owned by this side
    production_regular: float
    production_playoff: float
    production_toilet: float
```

A side's column totals are the sum of its rows. Two of the four production totals already
exist on the grades; the **gross received KTC** is new for the direct grade (today we only
store the `snapshot_value_swing` = received − given). The became grade's `ktc` is already
gross per-side, so it needs no new total — only the per-player rows.

## Components & changes

### Engine

**Direct grade (`engine/trade_grader.py`, `models/trade.py`):**
- Refactor the received-side production walk to retain **per received asset** rows, not
  just the per-side sum. Produce `breakdown: list[AssetLine]` per side.
  - PlayerAsset → `ktc` (today's KTC) + `production_*` (received-only, per phase, while
    owned — exactly what `_received_points` already computes, kept per-player).
  - PickAsset → `ktc` (pick-table or drafted-player value, as `_ktc_value` already does)
    + all `production_* = 0.0`.
- Add per-side **`received_ktc`** (gross sum of received-asset KTC). Keep
  `snapshot_value_swing` (still used elsewhere / for the won-value framing if ever needed).
- The existing per-side `production_*` totals stay (they already equal the row sums).

**Became grade (`engine/regrade.py`):**
- Refactor `build_became_grade`'s inner loop to retain **per terminal asset** rows
  (`AssetLine`) instead of summing into scalars. The existing `ktc`/`production`/`regular`/
  `playoff`/`toilet` totals stay (row sums); add `breakdown: list[AssetLine]`.
  `terminal_labels` becomes redundant with the rows' labels — keep it for back-compat or
  derive in the API.

### Cache (`api/app/services/chain_cache.py`)
- Bump `SCHEMA_VERSION` 3 → 4 (grade payload gains breakdown + received_ktc). Re-grade on
  next read; cold-start contract handles it.

### API (`api/app/models/trade.py`, `api/app/services/trade_view.py`)
- `TradeSideView` gains `received_ktc: float` and `breakdown: list[AssetLine]` (Pydantic
  model mirroring the dataclass).
- `BecameMetrics` gains `breakdown: list[AssetLine]`.
- `trade_view` maps the engine breakdown rows onto the response.

### Frontend

**New `web/components/TradeStatTable.tsx`:**
- Props: `owner`, `rows: AssetLine[]`, `totals` (the five column totals), and an optional
  `compare` (the other side's totals) for winner highlighting.
- Desktop: full 6-column table (Player | KTC | Tot | Reg | Ply | Toi), bold TOTAL row.
- Winner highlight: for each column, if this side's total beats `compare`, the TOTAL cell
  is emphasized (`text-pos` or a subtle winning tint — restrained, product register).
- Mobile (`< sm`): show Player · KTC · Total; each player row is tappable (native
  `<details>` or a small client toggle) to reveal Reg/Ply/Toi. Totals row always visible.
- Sorting handled in the component (Total desc; picks last by KTC). Picks show `—` for
  point columns.
- Tabular numerals, existing tokens (`bg-surface`, `border-divider`, `text-dim/ink`,
  `--pos`), `font-mono` for the column eyebrow. AA contrast both themes.

**Wire-in:**
- **Direct trade page** (`app/league/[id]/trade/[tid]/page.tsx`): render a `TradeStatTable`
  per side (using `side.breakdown`, totals from `received_ktc` + `production_*`, comparing
  against the other side). Keep the **"Gave"** list (shipped-out assets aren't in the
  received table). Retire `TradeSidePanel`'s metric/points/market sections (fold the
  assets-received into the table; keep Gave). `TradeSidePanel` either shrinks to "Gave +
  owner header" or is replaced.
- **Became card** (`web/components/TradeBecame.tsx`): replace its five-row metric list
  with a `TradeStatTable` per side using `became.breakdown`.
- Update `web/lib/types.ts` (`AssetLine`, `received_ktc`, `breakdown` on TradeSideView and
  BecameMetrics).

### Removal
- Delete the scrapped `TradeScoreboard.tsx` and the `app/dev/scoreboard` preview (already
  removed on this branch).

## Testing

- **Engine:** per-player breakdown sums to the side totals (direct + became); a pick row
  has KTC and zero points; a flipped received player's direct row counts only
  while-owned points; became rows cover terminal players. (`tests/test_trade_grader.py`,
  `tests/test_regrade.py`).
- **API:** trade detail response carries `received_ktc` + `breakdown` per side and
  `breakdown` on became; row sums equal totals (`api/tests/test_trade.py`).
- **Web:** `TradeStatTable` renders rows + totals, highlights the winning column, sorts
  picks last, and collapses on mobile (tap reveals splits). Update existing
  `TradeSidePanel`/`TradeBecame`/OG tests.
- Full suites green: `tests/`, `api/`, `web/`.

## Open questions / iterate-live

- Exact desktop density of two 6-column tables side by side (may stack on narrower
  laptops). Resolve with live mockups during the build.
- Winner-highlight treatment (color vs subtle bg tint). Try both live.
- Whether `TradeSidePanel` is slimmed or fully replaced — decide when wiring the page.

## Out of scope (still B)

The outcomes-dominant GM Rating redesign and the toilet sign. Untouched here.
