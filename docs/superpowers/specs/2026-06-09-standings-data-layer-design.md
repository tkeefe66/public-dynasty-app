# Standings Data Layer — Design

**Date:** 2026-06-09
**Status:** Approved (brainstorm) → ready for implementation plan
**Sub-project:** A of the "owner/season analyzer" vision

## Context & motivation

The app started as a trade grader, but the goal is broader: **analyze an owner's
season and moves, then grade (and roast) the GM.** Trades are the first lens;
standings, injuries, picks, and waivers come later.

A recurring objection to the current GM Rating exposed the gap: we grade trades on
**points produced**, but owners don't trade to out-score the other side — they trade
to **move up the standings**, build for the future, and acquire picks. Season final
results are what matter. To reason about "did this trade move them up or down the
table," we need standings — specifically **standings as of any week**, which Sleeper
does not expose historically.

Today we capture **no** as-of-week standings. The `Trade` model has only `week` and
`traded_at`. Standings exist only as a *current/end-of-season* snapshot read straight
off Sleeper's `Roster` settings (`recap.py::build_standings`, `aggregations.py::_records`).

This spec builds the **standings data layer**: a pure as-of-week reconstruction plus a
persisted snapshot store, wired into refresh, with one thin consumer (as-of-trade
standing on the trade detail response) to prove the wiring end-to-end.

## Scope boundary

**In scope:** engine reconstruction, snapshot store, refresh wiring, as-of-trade
standing on the trade API response, tests.

**Explicitly out of scope (tracked, separate efforts):**
- **Sub-project B — standings → GM Rating attribution.** *How* standings movement
  feeds the rating (per-trade delta vs. season-outcome blend vs. counterfactual sim).
  Its own brainstorm, deferred until we can look at real reconstructed numbers.
  Standings movement is heavily confounded (one trade vs. many, injuries, variance);
  the attribution model deserves its own design.
- **One-sided metric reframe.** Separate decision already reached: drop the
  phantom-subtraction term on the phase-split production metrics so Regular / Playoff /
  Toilet (and Total Points) become **received-only** tallies ("what my haul produced")
  instead of `received − given` swings — only **Trade Value** stays a swing. This fixes
  the category error where a traded-away player's bracket phase is the *receiving* team's
  fate, not yours. Plus the open **toilet-sign** question (neutral vs. negative weight in
  GM Rating). Small, self-contained engine + copy change; specced/implemented separately.

## Key decisions (from brainstorm)

1. **Persist stored snapshots** (not derive-on-demand), mirroring
   `rating_snapshot_store.py`.
2. **Full per-week table, every completed week** — store every owner's full standing
   row for each completed NFL week of the whole chain. Richest substrate; unblocks
   season trend, as-of-trade lookup, and future analysis for free.
3. **Owner-keyed (`user_id`)**, applying `roster_to_user` at snapshot time, so standings
   stay continuous across seasons even as roster IDs churn — matching how trades and GM
   Rating are already owner-centric.
4. **Self-validate against Sleeper's authoritative record.** Sleeper's `Roster`
   wins/losses/pf already bake in median/division rules. Our reconstruction *through the
   latest completed week* must equal it; mismatch logs a warning (not a crash) so
   non-standard leagues surface empirically rather than scoring silently wrong.
5. **Include one consumer:** as-of-trade standing on the trade detail response.

## Architecture

```
matchups (already pulled + cached for the whole chain)
        │
        ▼
engine/standings.py            ── pure reconstruction, no IO
  standings_as_of(...)         → list[StandingRow]
  standings_history(...)       → {week_key: list[StandingRow]}
  validate_against_roster(...) → logs deltas on mismatch
        │
        ▼
refresh_service.refresh_league ── compute history across every league-season
        │                          in the chain, write completed weeks
        ▼
StandingsSnapshotStore         ── one JSON per entry-league, week-keyed
  read / write / as_of / latest
        │
        ▼
trade_view → TradeDetailResp   ── as-of-trade standing per side (consumer)
```

## Components

### 1. Engine — pure reconstruction (`src/sleeper_dynasty/engine/standings.py`, new)

```python
@dataclass
class StandingRow:
    owner_id: str
    roster_id: int
    wins: int
    losses: int
    ties: int
    points_for: float
    points_against: float
    rank: int   # 1-based, after sort

def standings_as_of(
    matchups,                      # (league_id, week, roster_id) -> matchup entry
    *,
    league_id: str,
    season: int,
    through_week: int,
    roster_to_user: dict[int, str],
    total_rosters: int,
) -> list[StandingRow]: ...

def standings_history(
    matchups, *, league_id, season, completed_weeks, roster_to_user, total_rosters,
) -> dict[str, list[StandingRow]]:   # week_key "{season}-{week:02d}" -> rows

def validate_against_roster(
    reconstructed_latest: list[StandingRow], rosters: list[Roster],
) -> list[str]:   # human-readable deltas; [] when exact
```

**Algorithm.** For weeks `1..through_week`: group roster-weeks by `matchup_id`, the
higher `points` is a win, equal is a tie (skip weeks with missing/None points — not yet
played). Accumulate W/L/T, points-for, points-against. Rank by
`(wins desc, points_for desc)` — Sleeper's default tiebreak. Pure; no IO.

**Data requirement.** Reconstruction needs per-roster-week `matchup_id` + `points` to
pair opponents. Confirm the `matchups` entry shape already carries `matchup_id`
(`MatchupResult` does); if the grader's `matchups` dict drops it, thread it through.

**Edge cases:** bye weeks / odd team counts (unpaired roster-week scores no game),
ties, weeks not yet played (None points → skipped), co-owners (one `user_id` per
roster via `roster_to_user`), `through_week` past season end (clamps to played weeks).

### 2. Backend — snapshot store (`api/app/services/standings_snapshot_store.py`, new)

Mirrors `RatingSnapshotStore` structure (cache_dir, per-league JSON, read/write).

- File: `standings_<entry_league_id>.json` → `{week_key: [row, ...]}`,
  `week_key = "{season}-{week:02d}"` (season-scoped so chain seasons don't collide).
- Rows are owner-keyed dicts (serialized `StandingRow`).
- **Not capped** (full chain history — as-of-trade can be years back).
- Completed weeks are **immutable / write-once**; the in-progress current week is
  rewritten each refresh.
- Methods: `read(league_id)`, `write(league_id, week_key, rows)`,
  `as_of(league_id, season, week)` (the snapshot for that week, or the latest ≤ it),
  `latest(league_id)`.

### 3. Refresh wiring (`api/app/services/refresh_service.py`)

After the chain's matchups are assembled and graded, for each league-season in the
chain: compute `standings_history`, write each completed week's snapshot (idempotent —
skip frozen weeks already persisted), and run `validate_against_roster` on the latest
completed week, logging any deltas. Manual `/refresh` and the auto-refresh scheduler
share this path (already true), so both keep standings warm.

### 4. Consumer — as-of-trade standing (`api/app/models/trade.py`, `trade_view.py`)

Add to `TradeSideView`:

```python
at_trade_standing: StandingAtTrade | None = None

class StandingAtTrade(BaseModel):
    rank: int
    wins: int
    losses: int
    ties: int
    points_for: float
    total_teams: int
```

`trade_view` populates it via `store.as_of(entry_league_id, resp.season, resp.week)`,
looked up by each side's `user_id`. Null when no snapshot exists (e.g. trade predates
week-1 completion, or refresh hasn't run). Backend only; UI rendering ("they sat 6th
when they made this") is a later/optional follow-up.

## Testing

- **Pure unit tests** for `standings_as_of` with synthetic matchups: clear
  win/loss/tie, bye week / odd team count, mid-season `through_week` cutoff,
  tiebreak by points-for, weeks-not-yet-played skipped.
- **Validation test:** load a real cached league, assert reconstruction through the
  latest completed week equals Sleeper's `Roster` record (catches median/division
  leagues — and documents which ones, if any, need extra handling).
- **Store round-trip tests** mirroring the rating-snapshot-store tests
  (write → read → `as_of` → `latest`, immutability of frozen weeks, season-scoped keys).
- **Consumer test:** trade detail response carries `at_trade_standing` for a known
  cached trade.

## Open questions

None blocking. Median/division handling is intentionally deferred to "if the
validation self-check trips" rather than built speculatively.
