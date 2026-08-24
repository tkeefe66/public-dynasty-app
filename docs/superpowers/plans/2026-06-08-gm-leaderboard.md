# GM Leaderboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`).

**Goal:** A league-wide **GM Rating** leaderboard (composite, league-relative, 1500-centered) with all-time + per-season boards, ▲▼ weekly movement, a tap-to-see breakdown, and an OG share card.

**Architecture:** A pure engine function turns each owner's already-aggregated four-metric net swings into a rating + breakdown. A snapshot store keeps weekly ratings for trend. A leaderboard service assembles the board from the existing `_aggregate_owner_rows`. UI renders the board + share card.

**Tech Stack:** Python/pytest (engine + api), FastAPI/Pydantic, Next.js/vitest, `next/og`.

**Reference spec:** `docs/superpowers/specs/2026-06-08-gm-leaderboard-design.md`. **Mirror these existing patterns** (read them first): `api/app/services/aggregations.py` (`_aggregate_owner_rows`, `_filter_trades_by_year`, `build_dashboard` route shape), `api/app/services/ktc_snapshot_store.py` (the snapshot-store pattern), `web/app/league/[id]/opengraph-image.tsx` + `web/lib/og-card.tsx` + `web/lib/og-card-data.ts` (share cards), the dashboard route + `web/lib/types.ts`.

**Conventions:** engine tests in repo-root `tests/` (`python3.11 -m pytest tests/`), api tests in `api/` (`cd api && python3.11 -m pytest`), web from `web/` (`npx vitest run --config tests/vitest.config.ts`). Match surrounding style. Commit per task.

**THE FORMULA (memorize):** per weighted metric (Playoff/Started/Value — bench is weight 0), z-score across the league's owners; `Z = 0.40·z_playoff + 0.35·z_started + 0.25·z_value`; `rating = round(1500 + 275·Z)` clamped `[800,2200]`; breakdown contribution per metric = `275·weight·z` (sums to rating−1500). sd==0 → that metric contributes 0.

---

## Task 1: Engine — `compute_gm_ratings` (pure)

**Files:** Create `src/sleeper_dynasty/engine/gm_rating.py`; Test `tests/test_gm_rating.py`

- [ ] **Step 1: Write failing tests** in `tests/test_gm_rating.py`:

```python
from sleeper_dynasty.engine.gm_rating import compute_gm_ratings, BASE


def _owners(**kw):
    # kw: uid -> (value, started, playoff)
    return {uid: {"value": v, "started": s, "playoff": p}
            for uid, (v, s, p) in kw.items()}


def test_all_equal_league_everyone_base():
    out = compute_gm_ratings(_owners(a=(0, 0, 0), b=(0, 0, 0), c=(0, 0, 0)))
    assert all(r["rating"] == BASE for r in out.values())


def test_clear_winner_outranks_and_centers():
    out = compute_gm_ratings(_owners(
        win=(1000, 800, 400), mid=(0, 0, 0), lose=(-1000, -800, -400)))
    assert out["win"]["rating"] > out["mid"]["rating"] > out["lose"]["rating"]
    assert out["mid"]["rating"] == BASE                  # the average sits at 1500
    assert out["win"]["rating"] + out["lose"]["rating"] == 2 * BASE  # symmetric


def test_breakdown_sums_to_rating_minus_base():
    out = compute_gm_ratings(_owners(
        a=(500, 300, 200), b=(-200, -100, 50), c=(-300, -200, -250)))
    for r in out.values():
        bd = r["breakdown"]
        assert abs((bd["playoff"] + bd["started"] + bd["value"])
                   - (r["rating"] - BASE)) <= 1      # rounding tolerance


def test_zero_sd_metric_contributes_zero():
    # value identical for all (sd 0) -> value contributes 0; ranking driven by playoff
    out = compute_gm_ratings(_owners(
        a=(100, 0, 50), b=(100, 0, -50), c=(100, 0, 0)))
    assert out["a"]["breakdown"]["value"] == 0
    assert out["a"]["rating"] > out["c"]["rating"] > out["b"]["rating"]


def test_playoff_weighted_over_value():
    # owner P leads only on playoff; owner V leads only on value (same magnitude z)
    out = compute_gm_ratings(_owners(
        P=(0, 0, 100), V=(100, 0, 0), z=(-100, 0, -100)))
    assert out["P"]["rating"] > out["V"]["rating"]   # 0.40 > 0.25
```

- [ ] **Step 2: Run** `python3.11 -m pytest tests/test_gm_rating.py -v` → fails (module missing).

- [ ] **Step 3: Implement** `src/sleeper_dynasty/engine/gm_rating.py`:

```python
"""Composite, league-relative GM Rating from each owner's four-metric net swings.

Realized-impact-first: Playoff Points and Points Started dominate, Trade Value is
secondary, bench (Total) is ignored. Each metric is z-scored across the league
(so KTC units and points combine), blended, and scaled to a 1500-centered rating.
Pure + fully unit-testable.
"""

from __future__ import annotations

WEIGHTS = {"playoff": 0.40, "started": 0.35, "value": 0.25}
BASE = 1500
SCALE = 275
CLAMP = (800, 2200)


def _stats(xs: list[float]) -> tuple[float, float]:
    n = len(xs)
    if n == 0:
        return 0.0, 0.0
    mean = sum(xs) / n
    var = sum((x - mean) ** 2 for x in xs) / n      # population sd
    return mean, var ** 0.5


def compute_gm_ratings(
    owners: dict[str, dict[str, float]],
) -> dict[str, dict]:
    """uid -> {"rating": int, "breakdown": {"playoff","started","value": int}}."""
    uids = list(owners)
    stats = {
        m: _stats([float(owners[u].get(m, 0.0)) for u in uids]) for m in WEIGHTS
    }
    out: dict[str, dict] = {}
    for u in uids:
        breakdown: dict[str, int] = {}
        composite_pts = 0.0
        for m, w in WEIGHTS.items():
            mean, sd = stats[m]
            z = 0.0 if sd == 0 else (float(owners[u].get(m, 0.0)) - mean) / sd
            contrib = SCALE * w * z
            breakdown[m] = round(contrib)
            composite_pts += contrib
        rating = round(BASE + composite_pts)
        rating = max(CLAMP[0], min(CLAMP[1], rating))
        out[u] = {"rating": rating, "breakdown": breakdown}
    return out
```

- [ ] **Step 4: Run** `python3.11 -m pytest tests/test_gm_rating.py -v` → all pass. (Note: `test_breakdown_sums` uses the unclamped path; if a clamp ever triggers in a future fixture the tolerance won't hold — current fixtures don't clamp.)

- [ ] **Step 5: Commit** `feat(engine): compute_gm_ratings (league-relative composite rating)`.

---

## Task 2: Rating snapshot store (for ▲▼ trend)

**Files:** Create `api/app/services/rating_snapshot_store.py`; Test `api/tests/test_rating_snapshot_store.py`

> **Read `api/app/services/ktc_snapshot_store.py` first** and mirror its structure (cache_dir, per-league JSON file, read/write). This store keeps, per league, one rating snapshot **per NFL week**.

- [ ] **Step 1: Write failing tests:** writing a snapshot for `week_key="2024-09"` then reading returns `{uid: rating}`; writing a second week appends a key; `latest_before(week_key)` returns the most recent snapshot strictly before the given week (or `{}` if none); history is capped (e.g. keep last 20 week keys).

- [ ] **Step 2: Implement** `RatingSnapshotStore(cache_dir)` mirroring `ktc_snapshot_store`:
  - `_path(league_id) -> cache_dir / f"ratings_{league_id}.json"`.
  - `write(league_id, week_key: str, ratings: dict[str, int])` — load, set `data[week_key] = ratings`, trim to the last 20 keys (sorted), dump.
  - `read(league_id) -> dict[str, dict[str, int]]` (`{}` if absent).
  - `latest_before(league_id, week_key: str) -> dict[str, int]` — among keys `< week_key`, return the max key's ratings, else `{}`.

- [ ] **Step 3: Run** the tests → green. **Step 4: Commit** `feat(api): rating snapshot store (per-NFL-week ratings for trend)`.

---

## Task 3: Leaderboard service + models + route

**Files:** Create `api/app/services/leaderboard.py`, `api/app/models/leaderboard.py`, `api/app/routes/leaderboard.py`; register router in `api/app/main.py`; Test `api/tests/test_leaderboard.py`

> Reuse `aggregations._aggregate_owner_rows` and `_filter_trades_by_year` (import them). Route mirrors the dashboard's cold-start contract (409 when the chain cache is cold).

- [ ] **Step 1: Models** (`api/app/models/leaderboard.py`):

```python
from __future__ import annotations
from pydantic import BaseModel
from app.models.common import OwnerRef


class RatingBreakdown(BaseModel):
    playoff: int
    started: int
    value: int


class GMRow(BaseModel):
    rank: int
    user_id: str
    owner: OwnerRef
    rating: int
    breakdown: RatingBreakdown
    trend: int            # prev_rank - rank: +up, -down, 0 flat/new
    trades: int
    net_ktc: float
    net_started: float
    net_playoff: float


class LeaderboardResp(BaseModel):
    league_id: str
    scope: str            # "all" or the season as a string
    rows: list[GMRow]
    generated_at: str
```

- [ ] **Step 2: Service** (`api/app/services/leaderboard.py`):

```python
from __future__ import annotations
from app.models.leaderboard import GMRow, LeaderboardResp, RatingBreakdown
from app.services.aggregations import _aggregate_owner_rows, _filter_trades_by_year
from app.services.chain_cache import ChainCacheEntry
from app.services.identity import owner_ref
from sleeper_dynasty.engine.gm_rating import compute_gm_ratings


def build_leaderboard(
    entry: ChainCacheEntry, *, year, prev_ratings: dict[str, int],
) -> LeaderboardResp:
    rows = _aggregate_owner_rows(entry, _filter_trades_by_year(entry, year))
    metrics = {
        uid: {"value": r["net_ktc"],
              "started": r["net_production_started"],
              "playoff": r["net_production_started_playoff"]}
        for uid, r in rows.items()
    }
    ratings = compute_gm_ratings(metrics)
    ordered = sorted(
        rows.values(),
        key=lambda r: (ratings[r["user_id"]]["rating"],
                       r["net_production_started_playoff"], r["net_ktc"]),
        reverse=True,
    )
    # Prior ranks from the prev snapshot (rank by prior rating desc).
    prev_rank = {uid: i + 1 for i, (uid, _) in enumerate(
        sorted(prev_ratings.items(), key=lambda kv: kv[1], reverse=True))}
    out_rows = []
    for i, r in enumerate(ordered):
        uid = r["user_id"]
        rt = ratings[uid]
        pr = prev_rank.get(uid)
        out_rows.append(GMRow(
            rank=i + 1, user_id=uid, owner=owner_ref(entry, uid),
            rating=rt["rating"], breakdown=RatingBreakdown(**rt["breakdown"]),
            trend=(pr - (i + 1)) if pr else 0,
            trades=r["trades"], net_ktc=r["net_ktc"],
            net_started=r["net_production_started"],
            net_playoff=r["net_production_started_playoff"],
        ))
    return LeaderboardResp(
        league_id=entry.league_id,
        scope="all" if year == "all" else str(year),
        rows=out_rows, generated_at=entry.cached_at,
    )
```

- [ ] **Step 3: Route** (`api/app/routes/leaderboard.py`) — mirror the dashboard route: read the chain cache (409 if cold), parse `year` (`"all"` or int), load `RatingSnapshotStore.read(league_id)` and pass the latest snapshot's ratings as `prev_ratings` (use `latest_before` keyed off the entry's current NFL week if available, else the most recent snapshot), return `build_leaderboard(...)`. Register `from app.routes import leaderboard; app.include_router(leaderboard.router)` in `main.py`.

- [ ] **Step 4: Tests** (`api/tests/test_leaderboard.py`): with a small fabricated `ChainCacheEntry` (mirror existing api test fixtures), `build_leaderboard` ranks by rating, assigns ranks 1..n, computes `trend` from a supplied `prev_ratings`, and respects the `year` filter. Run → green.

- [ ] **Step 5: Commit** `feat(api): GM leaderboard service + route + models`.

---

## Task 4: Write a rating snapshot during refresh

**Files:** Modify `api/app/services/grader.py` (or wherever the cache entry is written in `GraderService.run` / refresh path); Test `api/tests/test_grader_rating_snapshot.py`

> After the entry is built/graded (all-time scope), compute the all-time ratings and persist a snapshot keyed by the **current NFL week**.

- [ ] **Step 1: Failing test:** after a `run` with a fake client whose `get_nfl_state` returns `{"season":2024,"week":9}`, the `RatingSnapshotStore` for the league has a key `"2024-09"` mapping each owner to an int rating.

- [ ] **Step 2: Implement:** in the refresh path, derive `week_key = f"{state['season']:04d}-{state['week']:02d}"` (get_nfl_state is already fetched during refresh — reuse it; if absent, skip snapshotting, don't fail). Build all-time metrics exactly as `build_leaderboard` does (extract a shared helper `owner_metrics(rows)` in `leaderboard.py` to avoid duplication), call `compute_gm_ratings`, write `{uid: rating}` via `RatingSnapshotStore`. Best-effort: a snapshot failure logs and never fails refresh.

- [ ] **Step 3: Run → green. Step 4: Commit** `feat(api): snapshot GM ratings per NFL week during refresh`.

---

## Task 5: Web — types + Leaderboard component + surface

**Files:** Modify `web/lib/types.ts`; Create `web/components/Leaderboard.tsx`; add a surface (a tab in the dashboard client and/or a route `web/app/league/[id]/gm/page.tsx` — match how existing tabs/routes are wired); Test `web/tests/Leaderboard.test.tsx`

- [ ] **Step 1: Types:** `RatingBreakdown`, `GMRow`, `LeaderboardResp` in `web/lib/types.ts` mirroring the Pydantic shapes.

- [ ] **Step 2: Failing test** (`web/tests/Leaderboard.test.tsx`): renders one row per GM with rank + owner + rating; shows ▲/▼/— per `trend` sign; clicking a row reveals the breakdown (1500 + playoff/started/value); renders an empty-state for a league with no rows.

- [ ] **Step 3: Implement `Leaderboard.tsx`:** ranked rows — **rank · owner · rating · trend arrow · trades**; #1 crowned, last visually roasted (brand tone, NO slur tokens); tap-to-expand breakdown; an all-time / per-season toggle reusing the existing year-selector pattern (fetch `/api/league/[id]/leaderboard?year=`). Use the Tailwind token classes (`--ink`, `--pos`, `--neg`, etc.) like sibling components.

- [ ] **Step 4: Wire the surface** (tab and/or route) following the existing dashboard tab pattern. **Step 5:** `npx vitest run` green + `npm run build` clean. **Step 6: Commit** per file group.

---

## Task 6: Leaderboard OG share card

**Files:** Create `web/app/league/[id]/gm/opengraph-image.tsx` (or extend the league OG route); add a leaderboard mapper to `web/lib/og-card-data.ts`; Test `web/tests/og-card-data.test.ts` (extend)

> Mirror `web/app/league/[id]/opengraph-image.tsx` + `web/lib/og-card.tsx`. The card: league name, "GM Rankings · as of week N", the top ~5 GMs with ratings, and the last-place dunk. Deep-link unfurls to the live board.

- [ ] **Step 1:** add `leaderboardCard(resp)` data mapper + a vitest case (top row + last row present). **Step 2:** implement the OG route reusing `og-card.tsx` primitives + the cached font loader. **Step 3:** `npm run build` clean. **Step 4: Commit** `feat(web): GM leaderboard OG share card`.

---

## Final verification

- [ ] `python3.11 -m pytest tests/test_gm_rating.py -q` (root) → PASS, and full `tests/` suite no-regress.
- [ ] `cd api && python3.11 -m pytest -q` → PASS (new leaderboard/snapshot/refresh tests + existing).
- [ ] from `web/`: `npx vitest run --config tests/vitest.config.ts` + `npm run build` → PASS.
- [ ] Post-deploy (outside this plan): a refresh populates a snapshot; the board ranks by rating, the breakdown reconciles, and a second refresh in a later NFL week produces ▲▼.

## Self-review (author)
- The rating math lives in ONE pure engine function (Task 1); the service (Task 3) and the refresh snapshot (Task 4) both feed it the same `{value,started,playoff}` shape via a shared `owner_metrics` helper → no drift.
- Trend is derived (prev snapshot ranks − current), never stored on the row.
- 🏆/season-finish intentionally absent (Awards build). No push/notification anywhere (pure pull + share).
- Cache/stores are additive (new files), so no migration of `ChainCacheEntry`; snapshots simply start accumulating on first refresh.
