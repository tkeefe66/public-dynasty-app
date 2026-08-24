# GM Leaderboard — Design Spec

**Date:** 2026-06-08
**Epic:** Ammunition (re-sequenced roadmap). Lead build after became-grade.
**Status:** Design approved in brainstorming — pending spec review before plan.

## Problem & strategy

The product's job is to **manufacture paste-able ammunition** for arguments that
happen organically in the league's group chat (iMessage — no bot, no push; a
human chooses to paste). The single most universal piece of ammunition is a
**league-wide ranking everyone is on**: #1 pastes to flex, everyone dunks on
last. This is that artifact — an authoritative **GM Rating** leaderboard with a
share card and a deep-link, plus a weekly **▲▼ movement** engine that makes it
worth re-checking without any notification.

## Decisions locked during brainstorming

| Decision | Choice |
|---|---|
| Ranking | A single composite **GM Rating** (not four separate boards). One authoritative number per GM. |
| Philosophy | **Realized-impact first.** Weights: **Playoff Points 0.40, Points Started 0.35, Trade Value 0.25, Total/bench 0.00.** "Your rating is how much your trades helped you *win*, against your league." |
| Scale | **League-relative, centered at 1500, ELO-flavored.** Trade swings are ~zero-sum within a league, so 1500 = "broke even vs your league"; above = net-fleeced people, below = got fleeced. |
| Transparency | **Tap-to-break-down** is mandatory — it's the meta-argument killer. Every rating shows its component points (1840 = 1500 + 220 playoff + 80 started + 40 value). |
| Boards | **All-time** (headline) **+ per-season** toggle ("2024 GM of the Year"). |
| Movement | **▲▼ weekly rank trend** in v1 (the recurring-habit hook). |
| Everyone shown | Yes. Non-traders sit near a neutral 1500. |
| Share | A leaderboard **OG share card** + deep-link (the paste artifact). |
| Out of scope (v1) | 🏆 championship badges + the season-finish data layer (deferred to the Awards build, which needs it anyway). Single composite only — no per-metric boards. |

## The GM Rating model

Inputs per owner (already produced by `aggregations._aggregate_owner_rows`):
`net_ktc` (Trade Value), `net_production_started` (Points Started),
`net_production_started_playoff` (Playoff Points). `net_production` (Total/bench)
is intentionally **unused** (weight 0).

Computation (pure, league-relative z-scores so different units — KTC vs points —
combine cleanly):

1. For each of the three weighted metrics, across all owners in scope: compute
   `mean` and population `sd`. If `sd == 0` (≤1 owner, or all equal), that
   metric contributes 0 for everyone.
2. Per owner `i`, per metric `m`: `z[m][i] = (value[m][i] - mean[m]) / sd[m]`.
3. Composite: `Z[i] = 0.40·z_playoff[i] + 0.35·z_started[i] + 0.25·z_value[i]`.
4. Rating: `rating[i] = round(1500 + SCALE · Z[i])`, `SCALE = 275`
   (a +1σ composite GM ≈ 1775). Clamp to `[800, 2200]` as an outlier guard.
5. **Breakdown** (for transparency UI): each metric's signed point contribution
   `contrib[m][i] = SCALE · weight[m] · z[m][i]`; these sum to `rating[i] − 1500`
   (modulo the clamp). Returned alongside the rating.

Ranks are assigned by `rating` desc; ties broken by `net_production_started_playoff`
desc, then `net_ktc` desc.

Per-season ratings use the same math on that season's trades only (standardized
within that season's spread).

### Engine — `src/sleeper_dynasty/engine/gm_rating.py` (net-new, pure)

```python
WEIGHTS = {"playoff": 0.40, "started": 0.35, "value": 0.25}
BASE, SCALE, CLAMP = 1500, 275, (800, 2200)

def compute_gm_ratings(
    owners: dict[str, dict[str, float]],   # uid -> {"value","started","playoff"}
) -> dict[str, dict]:
    """uid -> {"rating": int, "breakdown": {"playoff":int,"started":int,"value":int}}.
    League-relative z-scores; sd==0 metric contributes 0. Pure + fully testable."""
```

Unit tests: a clear-winner/clear-loser spread ranks correctly and centers ~1500;
an all-equal league → everyone 1500; a single metric with sd 0 contributes 0;
breakdown sums to `rating − 1500`; weights favor playoff over value (a
playoff-heavy owner outranks an equal-value-only owner).

## Trend (▲▼ weekly movement)

- **Snapshot store** mirroring `ktc_snapshot_store.py`: persist, per league, one
  rating snapshot **per NFL week** — `{week_key: {uid: rating}}` (overwrite
  within the same week; new key when the week advances). NFL week from
  `SleeperClient.get_nfl_state` (already fetched during refresh).
- Written during refresh (the all-time board's ratings) right after grading.
- **Trend per owner** = `prev_rank − current_rank` against the most recent
  snapshot from an *earlier* week (▲ up, ▼ down, — flat / new). Computed in the
  leaderboard service, not stored on the row.
- Capped history (e.g. last 20 weeks). First-ever snapshot → all "—".

## API — `app/services/leaderboard.py` + route + models

- `build_leaderboard(entry, *, year, prev_snapshot) -> LeaderboardResp`:
  reuse `_aggregate_owner_rows(entry, _filter_trades_by_year(entry, year))`, map
  to the `{value, started, playoff}` shape, call `compute_gm_ratings`, sort,
  assign rank, attach trend from `prev_snapshot`.
- Models (`app/models/leaderboard.py`): `GMRow(rank, user_id, owner, rating,
  breakdown, trend, trades, net_ktc, net_started, net_playoff)` and
  `LeaderboardResp(league_id, scope ("all"|season), rows, generated_at)`.
- Route `GET /api/league/{id}/leaderboard?year=all|<season>` (409 cache cold,
  same contract as the dashboard).

## Frontend — `web/components/Leaderboard.tsx` + tab/route + card

- A leaderboard surface (tab on the league dashboard and/or `/league/[id]/gm`):
  ranked rows — **rank · owner · GM Rating · ▲▼ · trades**. #1 visually crowned,
  last visually roasted (consistent with brand, but no slur tokens).
- **Tap a row → the breakdown** (the 1500 + playoff/started/value points), so the
  number is defensible on the spot.
- **All-time / per-season** toggle (reuses the existing year selector pattern).
- TS types in `web/lib/types.ts`; vitest render tests (rows, trend arrows,
  breakdown expand, empty/no-trades league).

### Share card — leaderboard OG route

- A `next/og` route (mirror the existing trade/owner/league `opengraph-image.tsx`
  + `web/lib/og-card.tsx`): the top GMs with ratings (and the last-place dunk),
  league name, "as of week N". Deep-link unfurls to the live board.

## Testing

- **Engine:** `compute_gm_ratings` cases above (pure, no fixtures).
- **API:** `build_leaderboard` ranks by rating, attaches trend from a prior
  snapshot, handles year filter + cold/empty league; snapshot store round-trips
  and keys by NFL week.
- **Frontend:** vitest render (rows, ▲▼, breakdown expand, empty league); OG card
  data mapper; `next build` clean.

## Out of scope

🏆 championships + season-finish layer (Awards build), per-metric boards,
head-to-head (its own build), any push/notification/digest delivery (the product
never sends — pure pull + manual share), owner-season-stories (later retention
layer).

## Open questions (tune during implementation)

`SCALE`/`CLAMP` exact values; whether the leaderboard is a new tab vs a new
route vs both; snapshot cadence storage (cache field vs dedicated store file —
leaning dedicated store, mirroring `ktc_snapshot_store`).
