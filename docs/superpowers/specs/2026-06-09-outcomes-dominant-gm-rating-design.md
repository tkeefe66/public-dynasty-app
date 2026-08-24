# Outcomes-Dominant GM Rating (Sub-Project B) — Design

**Date:** 2026-06-09
**Status:** Approved (brainstorm) → ready for implementation plan
**Brief:** `docs/superpowers/specs/2026-06-09-sub-project-b-gm-rating-kickoff.md`

## Goal

Evolve the GM Rating from a trade-portfolio score into a holistic **dynasty GM rating**
across three pillars — **past results, trade output, and future positioning** — fully
**transparent** (every rating point traceable to a signal).

## Architecture

```
GM Rating = scale₁₅₀₀( 0.45·Outcomes_z + 0.30·TradeImpact_z + 0.25·Outlook_z )
```

Each pillar subscore is a weighted blend of its signals, **each signal z-scored across the
league** (so a pillar reads "how this owner compares to the league"). The composite is
scaled to the existing 1500-centered rating (`BASE=1500`, `SCALE` tuned, clamped 800–2200),
reusing today's `gm_rating.py` machinery. Career-cumulative across the whole league chain,
with the existing per-NFL-week snapshot trend retained.

### Pillar weights (decided)
Outcomes **0.45** · Trade Impact **0.30** · Outlook **0.25**.

### Pillar 1 — Outcomes (career; from standings substrate + bracket classification)
Five z-scored signals, internal weights (tunable defaults):

| Signal | Weight | Source |
| --- | --- | --- |
| Championships (titles won) | 0.35 | winners-bracket final, `playoff_phase` |
| Playoff depth (rounds won / runner-ups) | 0.25 | winners-bracket progression |
| Made-playoffs rate | 0.15 | bracket participation / final seed vs `num_playoff_teams` |
| Final regular-season seed (avg rank) | 0.15 | `standings.py` final standings (inverted: 1st = best) |
| Points-for rank (regular season) | 0.10 | `standings.py` points_for rank |

### Pillar 2 — Trade Impact (career; the existing received-only grades)
**Unchanged from today's GM Rating** — keep the tuned internal weights:
playoff **0.40** · regular **0.30** · value **0.22** · toilet **0.08** (toilet stays a small
positive per the decision). This pillar *is* the current rating, demoted to 30% of the whole.

### Pillar 3 — Outlook (current snapshot; from `engine/dynasty.py`)
Three z-scored signals, internal weights (tunable defaults):

| Signal | Weight | Source |
| --- | --- | --- |
| Roster value (current KTC of the roster) | 0.40 | current_holders × KTC |
| Draft capital (net future picks vs league avg) | 0.35 | `DraftCapital.net_vs_average` |
| Youth (inverse avg age / young-core size) | 0.25 | `AgeProfile.overall_avg_age` / `core_young` |

> Note: Outcomes and Trade Impact are career aggregates; Outlook is a present-day snapshot
> (inherently forward-looking). This mix is intentional — "what you've done" + "where you're
> headed." It does mean Outlook moves as rosters/picks change (good for the trend).

### Why the confounding problem is gone
We never attribute standings movement to individual trades (the brutally-confounded
"did this trade move them up" math). Outcomes are **season-level career aggregates**, Trade
Impact is the **trade portfolio's realized output**, Outlook is a **current snapshot**. No
per-trade standings-delta anywhere.

## Transparency (first-class)

`compute_gm_ratings` returns, per owner, the rating **and a full breakdown**:

```python
{
  "rating": 1620,
  "pillars": {
    "outcomes": {
      "weight": 0.45, "z": 1.42, "contribution": 176,   # rating points from this pillar
      "signals": {
        "championships": {"raw": 2, "z": 1.8, "weight": 0.35, "contribution": 88},
        "playoff_depth": {"raw": 5, "z": 0.9, "weight": 0.25, ...},
        ...
      },
    },
    "trade_impact": { ... },
    "outlook": { ... },
  },
}
```

Every rating point is traceable: pillar → signal → (raw value, league-relative z, weight,
points contributed). The numbers sum: signal contributions → pillar contribution → (with
BASE) the rating.

**UI:** the `/gm` tab gains a per-owner **score breakdown** drill-down — the composite, the
three pillar bars (with their point contributions), and within each pillar the signals with
raw value + league rank (z) + points. Reads like a receipt: "1,620 = 1500 base +176 outcomes
+72 trade impact −28 outlook," then each pillar expands to its signals. The current "GM
Rating explainer" copy is rewritten to describe the three pillars + transparency.

## Components & changes

### Engine (`src/sleeper_dynasty/engine/`)
- `gm_rating.py`: rewrite `compute_gm_ratings` to take three per-owner signal dicts (outcomes,
  trade_impact, outlook), z-score each signal across the league, blend by internal weights →
  pillar z, blend pillars by 0.45/0.30/0.25 → composite → scale. Return the full breakdown
  structure above. Constants (`PILLAR_WEIGHTS`, per-pillar `*_WEIGHTS`, `BASE`, `SCALE`,
  `CLAMP`) live here. Pure + exhaustively unit-tested (a hand-computed fixture validates the
  whole pipeline and the breakdown sums).
- New `engine/gm_signals.py` (or extend existing): pure extractors —
  - `outcome_signals(...)` from final standings + bracket classification (championships,
    depth, made-playoffs, seed, pf-rank), aggregated per owner across seasons.
  - `outlook_signals(...)` from the dynasty analysis (roster value, draft capital, youth).
  - trade-impact signals already exist (the received-only owner rollups).

### Backend (`api/app/services/leaderboard.py`, models)
- The leaderboard service assembles the three signal sets (standings via the snapshot store +
  final standings; dynasty analysis via the existing engine; trade grades) and calls
  `compute_gm_ratings`. The `GMRow` / leaderboard response gains the pillar subscores +
  breakdown. The per-week rating snapshot store continues (snapshots the composite).
- A per-owner breakdown is exposed (on the leaderboard row or a dedicated endpoint).

### Frontend (`web/`)
- `/gm` leaderboard: show the composite + three pillar contributions per row; a drill-down
  (expand / detail) renders the full signal breakdown.
- Rewrite the GM Rating explainer copy for the three pillars + transparency.

## Testing

- **Engine:** hand-computed three-pillar fixture — verify pillar z-scores, the 45/30/25 blend,
  scaling/clamping, and that the breakdown contributions sum to the rating. Signal extractors
  tested against synthetic standings/brackets and synthetic dynasty analysis (e.g. a pick-poor
  vs pick-rich owner; a champion vs a cellar-dweller).
- **API:** leaderboard returns the composite + pillar subscores + breakdown; snapshot trend
  intact.
- **Web:** the breakdown drill-down renders pillars + signals with raw/z/contribution.
- All suites green.

## Migration / rollout

- This changes every GM Rating number (three pillars vs one). Expected. The rating is derived
  at leaderboard-build time from cached grades + standings snapshots + a dynasty analysis, so
  no grade-cache schema change is strictly required; confirm the dynasty analysis is available
  at leaderboard time (compute or cache it during refresh if not).
- Internal weights are constants — tunable without a data migration.

## Out of scope
- Recency weighting of seasons (career equal-weight for the first cut).
- Injury-aware analysis (future; keep the outcome/outlook models extensible).
- Per-trade standings attribution (deliberately avoided).
