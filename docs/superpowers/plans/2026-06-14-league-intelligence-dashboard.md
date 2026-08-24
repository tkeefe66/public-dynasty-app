> _Historical doc — paths/names have changed. Repo is now `Code Apps/public-dynasty` (GitHub `tkeefe66/public-dynasty-app`), Railway project **shimmering-nature**, live at https://ffbdynasty.com. Ignore stale refs to `sleeper-dynasty` / `sleeper-trade-grader` / `web-production-f949`._

# League Intelligence Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reframe the Dashboard tab from "trade highlights" to league-wide competitive intelligence — replacing the 4 KPI hero cards with GM-intelligence spotlights and adding GM Rating, Window, and Draft Capital columns to the standings table.

**Architecture:** Enrich `StandingRow` in the existing dashboard endpoint with 5 new fields (`gm_rating`, `gm_rank`, `gm_trend`, `window`, `draft_capital_value`) computed from data already cached on `ChainCacheEntry`. Replace `HeroStats` with 4 intelligence-focused fields. No new endpoints.

**Tech Stack:** Python/FastAPI (backend), Next.js 14/TypeScript/Tailwind (frontend), pytest, vitest

---

## File Map

| File | Change |
|---|---|
| `api/app/models/league.py` | Add 5 fields to `StandingRow`; replace 4 `HeroStats` fields |
| `api/app/services/leaderboard.py` | Make `_prev_ratings` public as `load_prev_ratings` |
| `api/app/services/aggregations.py` | Replace `_hero_stats()` with `_intel_hero_stats()`; add GM enrichment to `build_dashboard()` |
| `api/app/routes/league.py` | Import `load_prev_ratings`, pass to `build_dashboard()` |
| `api/tests/test_aggregations.py` | Update fixtures + old tests; add new intel tests |
| `web/lib/types.ts` | Update `HeroStats` shape; add fields to `StandingRow` |
| `web/lib/url-state.ts` | Change default sort from `net_ktc` to `gm_rating` |
| `web/lib/standings-filter.ts` | Add `gm_rating`, `gm_rank`, `draft_capital_value` to `NUMERIC_COLUMNS` |
| `web/components/HeroStatsRow.tsx` | Replace 4 old cards with 4 intelligence cards |
| `web/components/StandingsTable.tsx` | Add 3 new columns, Window pill, footer note, rename title |
| `web/components/DashboardClient.tsx` | Update section header/subtitle |

---

## Task 1: Backend model changes

**Files:**
- Modify: `api/app/models/league.py`

- [ ] **Step 1: Add new fields to `StandingRow` and replace `HeroStats`**

Open `api/app/models/league.py`. Make these two edits:

**StandingRow** — add 5 fields after `net_ktc_aged`:
```python
class StandingRow(BaseModel):
    rank: int
    user_id: str
    owner: OwnerRef
    net_ktc: float
    production_total: float
    production_regular: float = 0.0
    production_playoff: float = 0.0
    production_toilet: float = 0.0
    trades: int
    grade: str
    net_ktc_at_trade: float = 0.0
    net_ktc_aged: float = 0.0
    # GM intelligence fields (None when entry has no signals yet)
    gm_rating: int | None = None
    gm_rank: int | None = None
    gm_trend: int = 0
    window: str | None = None
    draft_capital_value: float = 0.0
```

**HeroStats** — replace 4 old fields with 4 new ones:
```python
class HeroStats(BaseModel):
    top_gm: HeroStat
    biggest_weekly_rise: HeroStat
    best_roster: HeroStat
    draft_ace: HeroStat
```

- [ ] **Step 2: Verify existing tests still run (they'll fail on hero_stats access — that's expected)**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && python -m pytest api/tests/test_aggregations.py -x -q 2>&1 | head -30
```

Expected: failures on `hero_stats.biggest_win`, `hero_stats.activity`, `hero_stats.best_pickup`, `hero_stats.most_active` — confirms the model change landed.

- [ ] **Step 3: Commit the model-only change**

```bash
git add api/app/models/league.py
git commit -m "feat(models): add GM intelligence fields to StandingRow; replace HeroStats with intel fields"
```

---

## Task 2: Make `load_prev_ratings` a public function

**Files:**
- Modify: `api/app/services/leaderboard.py`

The leaderboard route has a private `_prev_ratings` helper. Both the leaderboard and dashboard routes need it. Promote it to a public function.

- [ ] **Step 1: Rename `_prev_ratings` → `load_prev_ratings` and add `Path` import if missing**

In `api/app/services/leaderboard.py`, the current private function is inside the route file, not the service. Check the leaderboard **route** (`api/app/routes/leaderboard.py`) — the function is there. Move it to the leaderboard **service** as a public function.

Add to the bottom of `api/app/services/leaderboard.py`:

```python
from pathlib import Path
from app.services.rating_snapshot_store import RatingSnapshotStore


def load_prev_ratings(cache_dir: Path, league_id: str) -> dict[str, int]:
    """Prior-week uid→rating snapshot for trend computation. Empty on first refresh."""
    store = RatingSnapshotStore(cache_dir=cache_dir)
    weeks = store.read(league_id)
    if len(weeks) < 2:
        return {}
    latest_key = max(weeks)
    return store.latest_before(league_id, latest_key)
```

- [ ] **Step 2: Update the leaderboard route to import from the service**

In `api/app/routes/leaderboard.py`, replace the local `_prev_ratings` helper with an import:

```python
from app.services.leaderboard import build_leaderboard, load_prev_ratings
```

And replace the `_prev_ratings(cache_dir, league_id)` call in the route with `load_prev_ratings(cache_dir, league_id)`. Delete the old local `_prev_ratings` function body.

- [ ] **Step 3: Verify leaderboard tests still pass**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && python -m pytest api/tests/test_leaderboard.py -q 2>&1 | tail -10
```

Expected: all passing.

- [ ] **Step 4: Commit**

```bash
git add api/app/services/leaderboard.py api/app/routes/leaderboard.py
git commit -m "refactor: extract load_prev_ratings to leaderboard service (shared with dashboard route)"
```

---

## Task 3: Update test fixture and fix broken tests

**Files:**
- Modify: `api/tests/test_aggregations.py`

The `_sample_entry()` fixture needs `outcome_signals` and `outlook_signals` so GM ratings produce meaningful values. The broken tests referencing old `HeroStats` fields need updating.

- [ ] **Step 1: Add signals to `_sample_entry()` in `test_aggregations.py`**

Find `_sample_entry()` in `api/tests/test_aggregations.py` and add these fields before `cached_at`:

```python
outcome_signals={
    "u_alice": {"championships": 2, "playoff_depth": 4, "made_playoffs": 1.0,
                "final_seed": 3.0, "points_for_rank": 3.0},
    "u_bob":   {"championships": 0, "playoff_depth": 0, "made_playoffs": 0.0,
                "final_seed": 1.0, "points_for_rank": 1.0},
},
outlook_signals={
    "u_alice": {"roster_value": 60000.0, "draft_capital": 3200.0,
                "draft_skill": 0.82, "youth": -25.0},
    "u_bob":   {"roster_value": 30000.0, "draft_capital": 800.0,
                "draft_skill": 0.10, "youth": -29.0},
},
dynasty_outlooks={
    "u_alice": {"window": "Contending", "trajectory": "Peak"},
    "u_bob":   {"window": "Rebuilding", "trajectory": "Declining"},
},
```

- [ ] **Step 2: Fix `test_build_dashboard_lens_switches_hero_stats_value`**

Replace the old lens test (which referenced `biggest_win`) with a test that confirms the new hero stats are lens-independent:

```python
def test_build_dashboard_hero_stats_top_gm_set():
    e = _sample_entry()
    resp = build_dashboard(e, year="all", lens="ktc")
    # Alice has stronger signals -> highest GM rating -> top_gm
    assert resp.hero_stats.top_gm.owner == "Alice"
    assert resp.hero_stats.top_gm.owner_user_id == "u_alice"
    assert resp.hero_stats.top_gm.value != "—"
    # Best roster: alice has higher roster_value signal
    assert resp.hero_stats.best_roster.owner == "Alice"
    # Draft ace: alice has higher draft_skill signal
    assert resp.hero_stats.draft_ace.owner == "Alice"
```

- [ ] **Step 3: Run tests to confirm only the expected failures remain**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && python -m pytest api/tests/test_aggregations.py -q 2>&1 | head -30
```

Expected: failures on `build_dashboard` calls that reference new `HeroStats` fields not yet implemented (the implementation comes in Task 4).

---

## Task 4: Implement `_intel_hero_stats()` and update `build_dashboard()`

**Files:**
- Modify: `api/app/services/aggregations.py`

- [ ] **Step 1: Add imports at top of `aggregations.py`**

Add after existing imports:

```python
from app.services.leaderboard import all_time_ratings
```

- [ ] **Step 2: Add `_compute_gm_trends()` helper**

Add after `_aggregate_owner_rows`:

```python
def _compute_gm_trends(
    ratings: dict[str, int], prev_ratings: dict[str, int]
) -> dict[str, int]:
    """prev_rank − current_rank per uid (positive = climbed). Zero when no prior snapshot."""
    if not prev_ratings:
        return {uid: 0 for uid in ratings}
    prev_rank = {
        uid: i + 1
        for i, (uid, _) in enumerate(
            sorted(prev_ratings.items(), key=lambda kv: kv[1], reverse=True)
        )
    }
    current_rank = {
        uid: i + 1
        for i, (uid, _) in enumerate(
            sorted(ratings.items(), key=lambda kv: kv[1], reverse=True)
        )
    }
    return {uid: (prev_rank.get(uid, 0) - current_rank[uid]) for uid in ratings}
```

- [ ] **Step 3: Replace `_hero_stats()` with `_intel_hero_stats()`**

Delete the entire old `_hero_stats` function (lines 150–227 in aggregations.py). Replace with:

```python
def _intel_hero_stats(
    entry: ChainCacheEntry,
    ratings: dict[str, int],
    gm_rank_by_uid: dict[str, int],
    gm_trend_by_uid: dict[str, int],
) -> HeroStats:
    """Four intelligence-focused KPI cards: Top GM, Biggest Weekly Rise, Best Roster, Draft Ace."""
    outlook = entry.outlook_signals or {}

    def _owner_href(uid: str) -> str | None:
        return uid  # caller builds the full href; stored on HeroStat as owner_user_id

    # Top GM ----------------------------------------------------------------
    if ratings:
        top_uid = max(ratings, key=lambda u: ratings[u])
        top_gm = HeroStat(
            value=f"{ratings[top_uid]:,}",
            context="GM Rating",
            owner=owner_name(entry, top_uid),
            owner_user_id=top_uid,
        )
    else:
        top_gm = HeroStat(value="—", context="GM Rating")

    # Biggest Weekly Rise ----------------------------------------------------
    if gm_trend_by_uid:
        rise_uid = max(gm_trend_by_uid, key=lambda u: gm_trend_by_uid[u])
        rise = gm_trend_by_uid[rise_uid]
        if rise > 0:
            biggest_weekly_rise = HeroStat(
                value=f"▲{rise}",
                context="GM Rating positions gained",
                owner=owner_name(entry, rise_uid),
                owner_user_id=rise_uid,
            )
        else:
            biggest_weekly_rise = HeroStat(value="—", context="GM Rating positions gained")
    else:
        biggest_weekly_rise = HeroStat(value="—", context="GM Rating positions gained")

    # Best Roster ------------------------------------------------------------
    roster_vals = {uid: float(outlook.get(uid, {}).get("roster_value") or 0) for uid in entry.owners}
    if any(v > 0 for v in roster_vals.values()):
        roster_uid = max(roster_vals, key=lambda u: roster_vals[u])
        best_roster = HeroStat(
            value=f"{int(roster_vals[roster_uid]):,}",
            context="KTC roster value",
            owner=owner_name(entry, roster_uid),
            owner_user_id=roster_uid,
        )
    else:
        best_roster = HeroStat(value="—", context="KTC roster value")

    # Draft Ace --------------------------------------------------------------
    skill_vals = {uid: float(outlook.get(uid, {}).get("draft_skill") or 0) for uid in entry.owners}
    if any(v > 0 for v in skill_vals.values()):
        ace_uid = max(skill_vals, key=lambda u: skill_vals[u])
        draft_ace = HeroStat(
            value=f"+{skill_vals[ace_uid]:.2f}",
            context="draft skill score",
            owner=owner_name(entry, ace_uid),
            owner_user_id=ace_uid,
        )
    else:
        draft_ace = HeroStat(value="—", context="draft skill score")

    return HeroStats(
        top_gm=top_gm,
        biggest_weekly_rise=biggest_weekly_rise,
        best_roster=best_roster,
        draft_ace=draft_ace,
    )
```

- [ ] **Step 4: Update `build_dashboard()` signature and body**

Replace the current `build_dashboard` function:

```python
def build_dashboard(
    entry: ChainCacheEntry,
    year: Year,
    lens: Literal["ktc", "production"],
    prev_ratings: dict[str, int] | None = None,
) -> DashboardResp:
    """Produce a DashboardResp from a cached chain entry + query params."""
    trades = _filter_trades_by_year(entry, year)
    rows = _aggregate_owner_rows(entry, trades)

    # All-time GM ratings (independent of year filter)
    ratings = all_time_ratings(entry)  # {uid: int}
    gm_rank_by_uid: dict[str, int] = {
        uid: i + 1
        for i, (uid, _) in enumerate(
            sorted(ratings.items(), key=lambda kv: kv[1], reverse=True)
        )
    }
    gm_trend_by_uid = _compute_gm_trends(ratings, prev_ratings or {})

    # Standings: primary sort by GM rating, tiebreak by net_ktc
    sorted_rows = sorted(
        rows.values(),
        key=lambda r: (ratings.get(r["user_id"], 0), r["net_ktc"]),
        reverse=True,
    )
    grade_by_uid = _letter_grade({r["user_id"]: r["net_ktc"] for r in sorted_rows})

    dynasty_outlooks = entry.dynasty_outlooks or {}
    outlook_signals = entry.outlook_signals or {}

    standings = [
        StandingRow(
            rank=i + 1,
            user_id=r["user_id"],
            owner=owner_ref(entry, r["user_id"]),
            net_ktc=r["net_ktc"],
            production_total=r["production_total"],
            production_regular=r["production_regular"],
            production_playoff=r["production_playoff"],
            production_toilet=r["production_toilet"],
            trades=r["trades"],
            grade=grade_by_uid.get(r["user_id"], "B"),
            net_ktc_at_trade=r["net_ktc_at_trade"],
            net_ktc_aged=r["net_ktc_today_subset"] - r["net_ktc_at_trade"],
            gm_rating=ratings.get(r["user_id"]),
            gm_rank=gm_rank_by_uid.get(r["user_id"]),
            gm_trend=gm_trend_by_uid.get(r["user_id"], 0),
            window=(dynasty_outlooks.get(r["user_id"]) or {}).get("window"),
            draft_capital_value=float(
                (outlook_signals.get(r["user_id"]) or {}).get("draft_capital") or 0
            ),
        )
        for i, r in enumerate(sorted_rows)
    ]

    seasons = sorted({lg["season"] for lg in entry.chain})
    league = LeagueSummary(
        league_id=entry.league_id,
        name=next(
            (lg["name"] for lg in entry.chain if lg["league_id"] == entry.league_id),
            entry.league_id,
        ),
        season=max(seasons) if seasons else 0,
        total_rosters=next(
            (lg["total_rosters"] for lg in entry.chain
             if lg["league_id"] == entry.league_id), 0
        ),
        status="active",
        seasons=seasons,
        last_refreshed=entry.cached_at,
    )

    return DashboardResp(
        league=league,
        selected_year=year,
        selected_lens=lens,
        hero_stats=_intel_hero_stats(entry, ratings, gm_rank_by_uid, gm_trend_by_uid),
        standings=standings,
        latest_trades=_latest_trades(entry, trades),
        records=_records(entry, rows),
        warnings=entry.warnings,
    )
```

Note: after pasting the new `build_dashboard`, delete these now-dead functions from `aggregations.py`:
- `_trade_swing` (top-level function, was used only by old `_hero_stats`)
- The old `_hero_stats` function itself (and its nested helpers `_hero`, `_best_pickup_stat`)

The `lens` parameter stays in `build_dashboard` — it's still passed through to `DashboardResp.selected_lens`.

- [ ] **Step 5: Run failing tests to see them pass**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && python -m pytest api/tests/test_aggregations.py -q 2>&1 | tail -15
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add api/app/services/aggregations.py api/tests/test_aggregations.py
git commit -m "feat(dashboard): replace trade hero stats with GM intelligence cards; enrich StandingRow with GM fields"
```

---

## Task 5: Add GM enrichment tests

**Files:**
- Modify: `api/tests/test_aggregations.py`

- [ ] **Step 1: Add tests for the new StandingRow fields**

Add after the existing tests in `test_aggregations.py`:

```python
def test_standings_gm_rating_and_rank_populated():
    e = _sample_entry()
    resp = build_dashboard(e, year="all", lens="ktc")
    # All rows should have gm_rating and gm_rank set
    for row in resp.standings:
        assert row.gm_rating is not None
        assert row.gm_rank is not None
    # Alice has stronger signals -> should rank higher
    alice = next(r for r in resp.standings if r.user_id == "u_alice")
    bob = next(r for r in resp.standings if r.user_id == "u_bob")
    assert alice.gm_rank < bob.gm_rank
    assert alice.gm_rating > bob.gm_rating


def test_standings_window_and_draft_capital_populated():
    e = _sample_entry()
    resp = build_dashboard(e, year="all", lens="ktc")
    alice = next(r for r in resp.standings if r.user_id == "u_alice")
    bob = next(r for r in resp.standings if r.user_id == "u_bob")
    assert alice.window == "Contending"
    assert bob.window == "Rebuilding"
    assert alice.draft_capital_value == 3200.0
    assert bob.draft_capital_value == 800.0


def test_standings_gm_trend_zero_without_prev_ratings():
    e = _sample_entry()
    resp = build_dashboard(e, year="all", lens="ktc")
    assert all(r.gm_trend == 0 for r in resp.standings)


def test_standings_gm_trend_with_prev_ratings():
    e = _sample_entry()
    # Prior snapshot had bob #1, alice #2 -> alice climbed, bob dropped
    prev = {"u_bob": 2000, "u_alice": 1000}
    resp = build_dashboard(e, year="all", lens="ktc", prev_ratings=prev)
    alice = next(r for r in resp.standings if r.user_id == "u_alice")
    bob = next(r for r in resp.standings if r.user_id == "u_bob")
    assert alice.gm_trend > 0   # moved up
    assert bob.gm_trend < 0    # moved down


def test_standings_sorted_by_gm_rating_by_default():
    e = _sample_entry()
    resp = build_dashboard(e, year="all", lens="ktc")
    ratings = [r.gm_rating for r in resp.standings]
    assert ratings == sorted(ratings, reverse=True)


def test_hero_stats_biggest_weekly_rise_flat_without_prev():
    e = _sample_entry()
    resp = build_dashboard(e, year="all", lens="ktc")
    assert resp.hero_stats.biggest_weekly_rise.value == "—"


def test_hero_stats_biggest_weekly_rise_with_prev():
    e = _sample_entry()
    prev = {"u_bob": 2000, "u_alice": 1000}
    resp = build_dashboard(e, year="all", lens="ktc", prev_ratings=prev)
    # Alice climbed (was rank 2, now rank 1) -> biggest rise
    assert resp.hero_stats.biggest_weekly_rise.owner == "Alice"
    assert resp.hero_stats.biggest_weekly_rise.value.startswith("▲")
```

- [ ] **Step 2: Run new tests**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && python -m pytest api/tests/test_aggregations.py -q 2>&1 | tail -15
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add api/tests/test_aggregations.py
git commit -m "test(dashboard): add GM enrichment and hero stats tests"
```

---

## Task 6: Update dashboard route

**Files:**
- Modify: `api/app/routes/league.py`

- [ ] **Step 1: Import `load_prev_ratings` and `RatingSnapshotStore`**

At the top of `api/app/routes/league.py`, add:

```python
from app.services.leaderboard import load_prev_ratings
```

- [ ] **Step 2: Add `_cache_dir` helper reference and update the route handler**

Update the `league` route function to load prev_ratings and pass them:

```python
@router.get("/api/league/{league_id}", response_model=DashboardResp)
def league(
    league_id: str,
    year: str = Query("all"),
    lens: Literal["ktc", "production"] = Query("ktc"),
) -> DashboardResp:
    cache_dir = _cache_dir()
    cache = ChainCache(cache_dir=cache_dir)
    entry = cache.read(league_id)
    if entry is None:
        raise HTTPException(
            status_code=409,
            detail="cache cold: kick off refresh via POST /api/league/{id}/refresh",
        )
    overrides = NameOverrideStore(cache_dir=cache_dir).read(league_id)
    if overrides:
        apply_name_overrides(entry, overrides)
    if year == "all":
        year_val: int | Literal["all"] = "all"
    else:
        try:
            year_val = int(year)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid year")
    prev_ratings = load_prev_ratings(cache_dir, league_id)
    return build_dashboard(entry, year=year_val, lens=lens, prev_ratings=prev_ratings)
```

- [ ] **Step 3: Run the route test to verify**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && python -m pytest api/tests/test_league.py -q 2>&1 | tail -15
```

Expected: all passing.

- [ ] **Step 4: Commit**

```bash
git add api/app/routes/league.py
git commit -m "feat(route): pass prev_ratings to build_dashboard for GM trend computation"
```

---

## Task 7: Frontend types

**Files:**
- Modify: `web/lib/types.ts`

- [ ] **Step 1: Update `HeroStats` and `StandingRow`**

In `web/lib/types.ts`, replace the `HeroStats` interface:

```typescript
export interface HeroStats {
  top_gm: HeroStat;
  biggest_weekly_rise: HeroStat;
  best_roster: HeroStat;
  draft_ace: HeroStat;
}
```

Add new fields to `StandingRow` (after `grade`):

```typescript
export interface StandingRow {
  rank: number;
  user_id: string;
  owner: OwnerRef;
  net_ktc: number;
  net_ktc_at_trade: number;
  net_ktc_aged: number;
  production_total: number;
  production_regular: number;
  production_playoff: number;
  production_toilet: number;
  trades: number;
  grade: string;
  gm_rating?: number;
  gm_rank?: number;
  gm_trend?: number;
  window?: string;
  draft_capital_value?: number;
}
```

- [ ] **Step 2: Run TypeScript check**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/web" && npx tsc --noEmit 2>&1 | head -30
```

Expected: errors on `HeroStatsRow.tsx` and `StandingsTable.tsx` referencing removed fields — these will be fixed in later tasks.

- [ ] **Step 3: Commit**

```bash
git add web/lib/types.ts
git commit -m "feat(types): update HeroStats to intelligence fields; add GM fields to StandingRow"
```

---

## Task 8: Default sort and standings filter

**Files:**
- Modify: `web/lib/url-state.ts`
- Modify: `web/lib/standings-filter.ts`

- [ ] **Step 1: Change default sort in `url-state.ts`**

In `web/lib/url-state.ts`, change the `DEFAULTS` object:

```typescript
const DEFAULTS: DashboardState = {
  year: "all",
  lens: "ktc",
  sort: { column: "gm_rating", direction: "desc" },
  filters: {},
};
```

- [ ] **Step 2: Add new numeric columns to `standings-filter.ts`**

In `web/lib/standings-filter.ts`, update `NUMERIC_COLUMNS`:

```typescript
const NUMERIC_COLUMNS = new Set<string>([
  "rank", "net_ktc", "production_total",
  "production_regular", "production_playoff", "production_toilet",
  "trades", "gm_rating", "gm_rank", "draft_capital_value",
]);
```

Note: change the type from `Set<keyof StandingRow>` to `Set<string>` since `gm_rank` is optional and TS strict mode won't accept optional keys here.

- [ ] **Step 3: Commit**

```bash
git add web/lib/url-state.ts web/lib/standings-filter.ts
git commit -m "feat(dashboard): default sort → gm_rating; add GM columns to standings filter"
```

---

## Task 9: Replace HeroStatsRow with intelligence cards

**Files:**
- Modify: `web/components/HeroStatsRow.tsx`

- [ ] **Step 1: Rewrite `HeroStatsRow.tsx`**

Replace the entire file content:

```tsx
import { HeroStatCard } from "./HeroStatCard";
import { DashboardResp } from "@/lib/types";

const TOOLTIPS = {
  top_gm: {
    title: "Top GM",
    body: "Owner with the highest all-time GM Rating — the composite of Outcomes, Trade Impact, and Outlook pillars.",
  },
  biggest_weekly_rise: {
    title: "Biggest Weekly Rise",
    body: "Owner who gained the most GM Rating positions since last week's snapshot.",
  },
  best_roster: {
    title: "Best Roster",
    body: "Owner with the highest current KTC roster value across all rostered players.",
    align: "right" as const,
  },
  draft_ace: {
    title: "Draft Ace",
    body: "Owner with the best rookie draft skill score — how their picks panned out vs their slot tier.",
    align: "right" as const,
  },
};

interface Props {
  data: DashboardResp;
  leagueId: string;
}

export function HeroStatsRow({ data, leagueId }: Props) {
  const { top_gm, biggest_weekly_rise, best_roster, draft_ace } = data.hero_stats;

  const ownerHref = (uid?: string | null) =>
    uid ? `/league/${leagueId}/owner/${uid}` : undefined;

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3.5 mb-7">
      <HeroStatCard
        title="Top GM"
        headline={top_gm.owner ?? undefined}
        value={top_gm.value}
        valueColor="ink"
        footer={top_gm.context}
        tooltip={TOOLTIPS.top_gm}
        href={ownerHref(top_gm.owner_user_id)}
      />
      <HeroStatCard
        title="Biggest Weekly Rise"
        headline={biggest_weekly_rise.owner ?? undefined}
        value={biggest_weekly_rise.value}
        valueColor={biggest_weekly_rise.value !== "—" ? "pos" : "ink"}
        footer={biggest_weekly_rise.context}
        tooltip={TOOLTIPS.biggest_weekly_rise}
        href={ownerHref(biggest_weekly_rise.owner_user_id)}
      />
      <HeroStatCard
        title="Best Roster"
        headline={best_roster.owner ?? undefined}
        value={best_roster.value}
        footer={best_roster.context}
        tooltip={TOOLTIPS.best_roster}
        href={ownerHref(best_roster.owner_user_id)}
      />
      <HeroStatCard
        title="Draft Ace"
        headline={draft_ace.owner ?? undefined}
        value={draft_ace.value}
        valueColor="ink"
        footer={draft_ace.context}
        tooltip={TOOLTIPS.draft_ace}
        href={ownerHref(draft_ace.owner_user_id)}
      />
    </div>
  );
}
```

- [ ] **Step 2: Update the `HeroStatsRow` call in `DashboardClient.tsx`**

In `web/components/DashboardClient.tsx`, the current call is:
```tsx
<HeroStatsRow data={data} profiles={profiles} leagueId={leagueId} />
```

Change to (remove `profiles`):
```tsx
<HeroStatsRow data={data} leagueId={leagueId} />
```

- [ ] **Step 3: Run TypeScript check**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/web" && npx tsc --noEmit 2>&1 | head -30
```

Expected: remaining errors only in `StandingsTable.tsx`.

- [ ] **Step 4: Commit**

```bash
git add web/components/HeroStatsRow.tsx web/components/DashboardClient.tsx
git commit -m "feat(dashboard): replace trade hero cards with GM intelligence KPI cards"
```

---

## Task 10: Update StandingsTable with new columns

**Files:**
- Modify: `web/components/StandingsTable.tsx`

- [ ] **Step 1: Replace the `COLS` definition**

In `web/components/StandingsTable.tsx`, replace the `COLS` array with:

```typescript
const COLS: {
  key: string;
  plain: string;
  tooltip?: { title: string; body: string; formula?: string; align?: "left" | "right" };
}[] = [
  { key: "gm_rank", plain: "#" },
  { key: "owner_name", plain: "Owner" },
  {
    key: "gm_rating", plain: "GM Rating",
    tooltip: { title: "GM Rating", body: "Composite franchise rating: 0.45·Outcomes + 0.30·Trade Impact + 0.25·Outlook, z-scored across the league and scaled to 1500. Always all-time — not affected by year filter." },
  },
  {
    key: "window", plain: "Window",
    tooltip: { title: "Dynasty Window", body: "Current franchise stage based on roster age, KTC value, and draft capital: Contending, Building, or Rebuilding." },
  },
  {
    key: "draft_capital_value", plain: "Draft Capital",
    tooltip: { title: "Draft Capital", body: "KTC value of all future rookie picks currently held. Not affected by year filter." },
  },
  {
    key: "net_ktc", plain: "Trade Value",
    tooltip: { title: "Trade value (realized)", body: "Realized market value of what this owner's trades brought in: each received asset valued at what they got for it — today's KTC if still held, its value when they flipped it, or 0 if dropped. Responds to year filter.", formula: "Σ realized value of received assets" },
  },
  {
    key: "production_regular", plain: "Reg Pts",
    tooltip: { title: "Regular season points", body: "Started points in regular-season weeks for received players. Responds to year filter." },
  },
  {
    key: "production_playoff", plain: "Playoff Pts",
    tooltip: { title: "Playoff points", body: "Started points in real title-bracket weeks only. Responds to year filter." },
  },
  {
    key: "grade", plain: "Grade",
    tooltip: { title: "Letter grade", body: "Trade Value grade relative to league peers.", align: "right" },
  },
];
```

- [ ] **Step 2: Add `windowPillClass` helper and update the grid template**

Add after `gradePillClass`:

```typescript
function windowPillClass(window: string): { bg: string; text: string } {
  if (window === "Contending") return { bg: "rgba(74,222,128,0.12)", text: "var(--pos)" };
  if (window === "Building") return { bg: "rgba(129,140,248,0.12)", text: "#818cf8" };
  return { bg: "rgba(248,113,113,0.10)", text: "var(--neg)" };
}
```

Update both desktop and mobile grid column templates. The desktop grid currently has 9 columns:
```
grid-cols-[24px_1.7fr_1.1fr_1.1fr_1.1fr_1.1fr_1.1fr_0.7fr_60px]
```

Replace with (same 9 columns, new proportions for the new column set):
```
grid-cols-[24px_1.7fr_0.9fr_0.9fr_0.9fr_1fr_0.9fr_0.9fr_56px]
```

- [ ] **Step 3: Replace the desktop row render**

In the `visible.map()` block for desktop (the `hidden sm:block` section), replace the row content:

```tsx
{visible.map((r) => (
  <Link
    key={r.user_id}
    href={`/league/${leagueId}/owner/${r.user_id}`}
    className="min-w-[1100px] grid grid-cols-[24px_1.7fr_0.9fr_0.9fr_0.9fr_1fr_0.9fr_0.9fr_56px] gap-2 py-2.5 border-b border-[var(--divider)] last:border-b-0 hover:bg-bg items-center cursor-pointer"
  >
    <div className="text-dim text-[11px]">{r.gm_rank ?? r.rank}</div>
    <div className="min-w-0">
      <OwnerLabel owner={r.owner} variant="full" />
    </div>
    <div className="font-mono text-[12px] font-semibold" style={{ color: "var(--accent, #818cf8)" }}>
      {r.gm_rating != null ? r.gm_rating.toLocaleString() : "—"}
    </div>
    <div>
      {r.window ? (
        <span
          className="px-2 py-0.5 rounded text-[11px] font-semibold"
          style={windowPillClass(r.window)}
        >
          {r.window}
        </span>
      ) : (
        <span className="text-dim text-[11px]">—</span>
      )}
    </div>
    <div className="font-mono text-[12px]">
      {r.draft_capital_value ? Math.round(r.draft_capital_value).toLocaleString() : "—"}
    </div>
    <div className={r.net_ktc > 0 ? "text-pos font-semibold" : r.net_ktc < 0 ? "text-neg font-semibold" : "text-dim"}>
      {r.net_ktc > 0 ? "+" : ""}{Math.round(r.net_ktc).toLocaleString()}
    </div>
    <div className={r.production_regular > 0 ? "text-pos font-semibold" : r.production_regular < 0 ? "text-neg font-semibold" : "text-dim"}>
      {r.production_regular > 0 ? "+" : ""}{r.production_regular.toFixed(1)}
    </div>
    <div className={r.production_playoff > 0 ? "text-pos font-semibold" : r.production_playoff < 0 ? "text-neg font-semibold" : "text-dim"}>
      {r.production_playoff > 0 ? "+" : ""}{r.production_playoff.toFixed(1)}
    </div>
    <div>
      <span className="px-2 py-0.5 rounded font-bold text-[11px] font-sans"
        style={{
          background: `var(--pill-${gradePillClass(r.grade)}-bg)`,
          borderColor: `var(--pill-${gradePillClass(r.grade)}-border)`,
          color: `var(--pill-${gradePillClass(r.grade)}-text)`,
          border: "1px solid",
        }}
      >
        {r.grade}
      </span>
    </div>
  </Link>
))}
```

- [ ] **Step 4: Update mobile row (4-column compact view)**

The mobile view currently shows rank, owner, trade value, grade. Update to show gm_rank, owner, gm_rating, grade:

```tsx
{/* Mobile: 4 columns — gm rank, owner, gm rating, grade */}
<div className="sm:hidden">
  <div className="grid grid-cols-[24px_minmax(0,1fr)_80px_54px] gap-2 pb-2 border-b border-divider font-mono text-[9px] uppercase tracking-wide text-dim">
    <div>#</div>
    <div>Owner</div>
    <div className="text-right">GM Rating</div>
    <div className="text-right">Grade</div>
  </div>
  {visible.map((r) => (
    <Link
      key={r.user_id}
      href={`/league/${leagueId}/owner/${r.user_id}`}
      className="grid grid-cols-[24px_minmax(0,1fr)_80px_54px] gap-2 py-2.5 border-b border-divider last:border-b-0 hover:bg-bg items-center cursor-pointer"
    >
      <div className="font-mono text-[11px] text-dim">{r.gm_rank ?? r.rank}</div>
      <div className="min-w-0">
        <OwnerLabel owner={r.owner} variant="full" />
      </div>
      <div className="text-right font-mono text-[13px] font-semibold" style={{ color: "var(--accent, #818cf8)" }}>
        {r.gm_rating != null ? r.gm_rating.toLocaleString() : "—"}
      </div>
      <div className="flex justify-end">
        <span
          className="px-2 py-0.5 rounded font-bold text-[11px] font-sans"
          style={{
            background: `var(--pill-${gradePillClass(r.grade)}-bg)`,
            borderColor: `var(--pill-${gradePillClass(r.grade)}-border)`,
            color: `var(--pill-${gradePillClass(r.grade)}-text)`,
            border: "1px solid",
          }}
        >
          {r.grade}
        </span>
      </div>
    </Link>
  ))}
</div>
```

- [ ] **Step 5: Rename the table title and add the footer note**

In the `tbl-hdr` div, change the title:
```tsx
<div className="flex justify-between items-baseline mb-3.5">
  <div className="text-[14px] font-bold tracking-tight">Owner Rankings</div>
  <div className="font-mono text-[10px] text-dim">{visible.length} rows</div>
</div>
```

Add a footer note after the `</div>` closing the `hidden sm:block` div:
```tsx
<div className="mt-3 font-mono text-[10px] text-dim">
  GM Rating · Window · Draft Capital are current-state and not affected by the year filter.
</div>
```

- [ ] **Step 6: Run TypeScript check — expect clean**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/web" && npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add web/components/StandingsTable.tsx
git commit -m "feat(dashboard): add GM Rating, Window, Draft Capital columns to Owner Rankings table"
```

---

## Task 11: Update DashboardClient section header

**Files:**
- Modify: `web/components/DashboardClient.tsx`

- [ ] **Step 1: Replace the section header text**

In `web/components/DashboardClient.tsx`, find the dashboard section header block:

```tsx
{initialTab === "dashboard" && (
  <>
    <div className="mb-3">
      <div className="text-[13px] font-semibold tracking-tight">
        Trade highlights {data.selected_year === "all"
          ? "(all years)"
          : `for ${data.selected_year}`}
      </div>
      <div className="text-[11px] text-dim">
        Ranked by Trade Value — today&apos;s market value (KTC)
      </div>
    </div>
```

Replace with:

```tsx
{initialTab === "dashboard" && (
  <>
    <div className="mb-3">
      <div className="text-[13px] font-semibold tracking-tight">
        League Intelligence
      </div>
      <div className="text-[11px] text-dim">
        GM Rating, roster outlook, and trade performance
        {data.selected_year !== "all" && ` · ${data.selected_year}`}
      </div>
    </div>
```

- [ ] **Step 2: Run TypeScript check**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/web" && npx tsc --noEmit 2>&1 | head -10
```

Expected: no errors.

- [ ] **Step 3: Run full test suite**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && make test 2>&1 | tail -20
```

Expected: all passing.

- [ ] **Step 4: Commit**

```bash
git add web/components/DashboardClient.tsx
git commit -m "feat(dashboard): section header → 'League Intelligence'"
```

---

## Task 12: Smoke test the full feature

- [ ] **Step 1: Start dev servers**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && make dev-api &
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && make dev-web
```

- [ ] **Step 2: Open the dashboard tab and verify**

Navigate to `http://localhost:3000/league/<your_league_id>` (Dashboard tab).

Check:
- [ ] Section header reads "League Intelligence"
- [ ] 4 KPI cards show: Top GM / Biggest Weekly Rise / Best Roster / Draft Ace
- [ ] Top GM card has an owner name headline and a numeric GM Rating value
- [ ] Biggest Weekly Rise shows "▲N" or "—" if no prior snapshot
- [ ] Table title reads "Owner Rankings"
- [ ] Table columns (left to right): # · Owner · GM Rating · Window · Draft Capital · Trade Value · Reg Pts · Playoff Pts · Grade
- [ ] GM Rating column shows numbers in accent color
- [ ] Window column shows colored pills (green/blue/red) or "—"
- [ ] Draft Capital column shows numeric values
- [ ] Clicking a column header sorts the table
- [ ] Footer note appears below the desktop table
- [ ] Year tab change updates Trade Value / Reg Pts / Playoff Pts / Grade but NOT GM Rating, Window, Draft Capital
- [ ] Each row links to the owner detail page on click

- [ ] **Step 3: Final commit if any fixups made**

```bash
git add -p
git commit -m "fix(dashboard): smoke test fixups"
```
