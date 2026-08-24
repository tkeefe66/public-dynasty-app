> _Historical doc — paths/names have changed. Repo is now `Code Apps/public-dynasty` (GitHub `tkeefe66/public-dynasty-app`), Railway project **shimmering-nature**, live at https://ffbdynasty.com. Ignore stale refs to `sleeper-dynasty` / `sleeper-trade-grader` / `web-production-f949`._

# Context-Aware Riser Card Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the "Biggest Weekly Rise" KPI card context-aware — showing the right label and computing the right baseline comparison based on whether the user is viewing an active season, a completed past season, the off-season, or all-time.

**Architecture:** During refresh, compute year-scoped GM ratings for every season in the chain and cache them on `ChainCacheEntry.season_ratings`. At dashboard request time, pick the right mode (weekly / year-riser / off-season / all-time) from the `year` param + current month, select the appropriate baseline rating snapshot, and return a dynamic label alongside the existing trend computation. Label is passed back to the frontend via a new `label` field on `HeroStat`.

**Tech Stack:** Python/FastAPI (backend), Next.js 14/TypeScript (frontend), pytest

---

## Mode Matrix

| Condition | Baseline | Label |
|---|---|---|
| `year == current_season` and NFL months (Sep–Jan) | Previous weekly snapshot (`prev_ratings`) | "Biggest Weekly Rise" |
| `year == current_season` and off-season | `season_ratings[str(prev_completed_season)]` | "Biggest Off-Season Riser" |
| `year` is a past completed season | `season_ratings[str(year - 1)]` | "Biggest Year Riser" |
| `year == "all"` | `season_ratings[str(first_season)]` | "Biggest All-Time Riser" |

In-season months: `{9, 10, 11, 12, 1}` (Sep through Jan).

---

## File Map

| File | Change |
|---|---|
| `api/app/services/chain_cache.py` | Add `season_ratings` field; bump `SCHEMA_VERSION` to 6 |
| `api/app/services/leaderboard.py` | Add `compute_season_ratings(entry)` public function |
| `api/app/services/refresh_service.py` | Call `compute_season_ratings` after grader runs; store on entry before cache write |
| `api/app/models/league.py` | Add `label: str \| None = None` to `HeroStat` |
| `api/app/services/aggregations.py` | Add `_rise_hero_stat()`; update `build_dashboard()` to accept `is_in_season: bool` |
| `api/app/routes/league.py` | Detect `is_in_season` from current month; pass to `build_dashboard()` |
| `api/tests/test_aggregations.py` | Add `season_ratings` to fixture; add four mode tests |
| `web/lib/types.ts` | Add `label?: string` to `HeroStat` |
| `web/components/HeroStatsRow.tsx` | Use `biggest_weekly_rise.label` as card title when present |

---

## Task 1: Add `season_ratings` to ChainCacheEntry

**Files:**
- Modify: `api/app/services/chain_cache.py`

- [ ] **Step 1: Add field and bump schema version**

In `api/app/services/chain_cache.py`, change `SCHEMA_VERSION = 5` to `SCHEMA_VERSION = 6`, then add the new field after `franchise_blurbs`:

```python
SCHEMA_VERSION = 6
```

```python
    franchise_blurbs: dict[str, dict[str, Any]] = field(default_factory=dict)
    # str(year) -> {uid: rating} — synthetic per-season GM ratings computed at refresh.
    # Used as historical baselines for the context-aware riser KPI card.
    season_ratings: dict[str, dict[str, int]] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION
```

- [ ] **Step 2: Verify schema bump invalidates old cache**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && make test-api 2>&1 | tail -5
```

Expected: all passing (schema bump doesn't break tests since fixture entries don't set `schema_version`).

- [ ] **Step 3: Commit**

```bash
git add api/app/services/chain_cache.py
git commit -m "feat(cache): add season_ratings field to ChainCacheEntry; bump schema to v6"
```

---

## Task 2: Add `compute_season_ratings()` to leaderboard service

**Files:**
- Modify: `api/app/services/leaderboard.py`
- Test: `api/tests/test_leaderboard.py`

- [ ] **Step 1: Write the failing test**

Add to `api/tests/test_leaderboard.py` (import the function at the top once it exists):

```python
def test_compute_season_ratings_returns_per_season_dict():
    entry = _sample_entry()  # already has outcome_signals + outlook_signals
    from app.services.leaderboard import compute_season_ratings
    result = compute_season_ratings(entry)
    # sample entry has seasons 2024 and 2026
    assert "2024" in result
    assert "2026" in result
    # each value is uid -> int rating
    for uid in ["u_alice", "u_bob", "u_carol"]:
        assert uid in result["2024"]
        assert isinstance(result["2024"][uid], int)


def test_compute_season_ratings_alice_outranks_carol():
    from app.services.leaderboard import compute_season_ratings
    result = compute_season_ratings(_sample_entry())
    # alice has better signals in the fixture -> higher rating -> lower rank number
    alice_2024 = result["2024"]["u_alice"]
    carol_2024 = result["2024"]["u_carol"]
    assert alice_2024 > carol_2024  # higher rating = better
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && make test-api 2>&1 | grep "compute_season_ratings" | head -5
```

Expected: ImportError (function not defined yet).

- [ ] **Step 3: Implement `compute_season_ratings` in `leaderboard.py`**

Add after `all_time_ratings`:

```python
def compute_season_ratings(entry: ChainCacheEntry) -> dict[str, dict[str, int]]:
    """Per-season scoped GM ratings keyed by str(year).

    For each season in the chain, aggregates only that year's trade data for
    the trade_impact pillar (outcomes + outlook are always all-time). Returns
    {str(year): {uid: int_rating}} — the synthetic historical baseline used
    by the context-aware riser KPI card on the dashboard."""
    seasons = sorted({lg["season"] for lg in entry.chain})
    result: dict[str, dict[str, int]] = {}
    for year in seasons:
        rows = _aggregate_owner_rows(entry, _filter_trades_by_year(entry, year))
        ratings = compute_gm_ratings(owner_pillars(rows, entry))
        result[str(year)] = {uid: r["rating"] for uid, r in ratings.items()}
    return result
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && make test-api 2>&1 | grep -E "compute_season|PASSED|FAILED" | head -10
```

Expected: both new tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add api/app/services/leaderboard.py api/tests/test_leaderboard.py
git commit -m "feat(leaderboard): add compute_season_ratings() for historical GM rating baselines"
```

---

## Task 3: Populate `season_ratings` during refresh

**Files:**
- Modify: `api/app/services/refresh_service.py`
- Test: `api/tests/test_refresh_service.py`

- [ ] **Step 1: Add import and call in refresh_league**

In `api/app/services/refresh_service.py`, add the import:

```python
from app.services.leaderboard import all_time_ratings, compute_season_ratings
```

Then in `refresh_league`, add one line between `GraderService().run()` and `ChainCache.write()`:

```python
async def refresh_league(
    client,
    league_id: str,
    *,
    cache_dir: Path,
    force: bool = False,
    progress_cb=None,
):
    """Refresh one league: run the grader, write the ChainCache. Returns the entry."""
    entry = await GraderService().run(
        client=client, current_league_id=league_id,
        progress_cb=progress_cb or _noop_progress,
        cache_dir=cache_dir, force=force,
    )
    entry.season_ratings = compute_season_ratings(entry)
    ChainCache(cache_dir=cache_dir).write(league_id, entry)
    await _snapshot_ratings(client, league_id, entry, cache_dir)
    return entry
```

- [ ] **Step 2: Run the refresh service tests**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && make test-api 2>&1 | grep -E "refresh_service|PASSED|FAILED" | tail -10
```

Expected: all passing — `compute_season_ratings` is a pure function with no side effects so existing refresh tests are unaffected.

- [ ] **Step 3: Commit**

```bash
git add api/app/services/refresh_service.py
git commit -m "feat(refresh): populate entry.season_ratings during refresh for riser card baselines"
```

---

## Task 4: Add `label` field to `HeroStat`

**Files:**
- Modify: `api/app/models/league.py`
- Modify: `web/lib/types.ts`

- [ ] **Step 1: Add `label` to Python model**

In `api/app/models/league.py`, add to `HeroStat`:

```python
class HeroStat(BaseModel):
    value: str
    context: str
    label: str | None = None   # dynamic card title; None = use frontend default
    owner: str | None = None
    owner_user_id: str | None = None
    trade_id: str | None = None
    date: str | None = None
    counterparty: str | None = None
    counterparty_user_id: str | None = None
```

- [ ] **Step 2: Add `label` to TypeScript type**

In `web/lib/types.ts`, add to `HeroStat`:

```typescript
export interface HeroStat {
  value: string;
  context: string;
  label?: string;
  owner?: string;
  owner_user_id?: string;
  trade_id?: string;
  date?: string;
  counterparty?: string;
  counterparty_user_id?: string;
}
```

- [ ] **Step 3: Typecheck**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/web" && npx tsc --noEmit 2>&1 | head -5
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add api/app/models/league.py web/lib/types.ts
git commit -m "feat(models): add optional label field to HeroStat for dynamic card titles"
```

---

## Task 5: Implement `_rise_hero_stat()` and update `build_dashboard()`

**Files:**
- Modify: `api/app/services/aggregations.py`
- Test: `api/tests/test_aggregations.py`

- [ ] **Step 1: Write failing tests for all four modes**

Add to `api/tests/test_aggregations.py`. First update `_sample_entry()` to include `season_ratings` (it already has `outcome_signals`, `outlook_signals`, `dynasty_outlooks` from the previous feature):

```python
# Add inside _sample_entry(), after dynasty_outlooks block:
season_ratings={
    "2024": {"u_alice": 1700, "u_bob": 1500, "u_carol": 1300},
    "2026": {"u_alice": 1800, "u_bob": 1500, "u_carol": 1200},
},
```

Then add the mode tests:

```python
def test_rise_card_all_time_label_and_value():
    """year='all' -> Biggest All-Time Riser, baseline = first season scoped."""
    e = _sample_entry()
    resp = build_dashboard(e, year="all", lens="ktc", is_in_season=False)
    card = resp.hero_stats.biggest_weekly_rise
    assert card.label == "Biggest All-Time Riser"
    # alice went from rank 1 in 2024 to rank 1 now — no rise; bob stayed; carol dropped
    # alice had highest 2024 rating (1700) -> rank 1 baseline
    # alice has highest current rating -> rank 1 current -> 0 rise
    # We just verify label and that value is a string
    assert card.value in ("—", "▲1", "▲2")


def test_rise_card_past_season_label():
    """viewing year=2024 (past completed) -> Biggest Year Riser."""
    e = _sample_entry()
    resp = build_dashboard(e, year=2024, lens="ktc", is_in_season=False)
    card = resp.hero_stats.biggest_weekly_rise
    assert card.label == "Biggest Year Riser"
    # No season_ratings["2023"] exists -> baseline empty -> value="—"
    assert card.value == "—"


def test_rise_card_off_season_label():
    """current season, off-season months -> Biggest Off-Season Riser."""
    e = _sample_entry()
    # current season = max chain season = 2026; is_in_season=False
    resp = build_dashboard(e, year=2026, lens="ktc", is_in_season=False)
    card = resp.hero_stats.biggest_weekly_rise
    assert card.label == "Biggest Off-Season Riser"
    # baseline = season_ratings["2024"]; compare vs current all-time
    # carol: 2024 rank 3 -> current rank 3 = 0; bob: rank 2 -> rank 2 = 0;
    # alice: rank 1 -> rank 1 = 0. So all flat -> "—" (no one truly rose)
    assert card.value in ("—", "▲1", "▲2")


def test_rise_card_in_season_label():
    """current season + in-season months -> Biggest Weekly Rise."""
    e = _sample_entry()
    prev = {"u_carol": 1800, "u_bob": 1500, "u_alice": 1200}  # alice was rank 3
    resp = build_dashboard(e, year=2026, lens="ktc", is_in_season=True, prev_ratings=prev)
    card = resp.hero_stats.biggest_weekly_rise
    assert card.label == "Biggest Weekly Rise"
    assert card.owner == "Alice"  # alice climbed from rank 3 to rank 1 = +2
    assert card.value == "▲2"
```

- [ ] **Step 2: Run to confirm failures**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && make test-api 2>&1 | grep -E "rise_card|TypeError|FAILED" | head -10
```

Expected: failures — `build_dashboard` doesn't accept `is_in_season` yet.

- [ ] **Step 3: Add `_rise_hero_stat()` to `aggregations.py`**

Add this function after `_compute_gm_trends`:

```python
_RISE_IN_SEASON_MONTHS: frozenset[int] = frozenset({9, 10, 11, 12, 1})


def _rise_hero_stat(
    entry: ChainCacheEntry,
    current_ratings: dict[str, int],
    year: Year,
    is_in_season: bool,
    prev_ratings: dict[str, int],
) -> HeroStat:
    """Context-aware 'Biggest Riser' KPI card.

    Picks label and baseline from four modes:
      weekly      — in-season + current year → week-over-week snapshot
      off_season  — off-season + current year → end-of-last-season baseline
      year_riser  — past completed year → year-minus-1 baseline
      all_time    — all-years view → first-season baseline
    """
    season_ratings = entry.season_ratings or {}
    seasons_with_data = sorted(int(k) for k in season_ratings if k.isdigit())
    chain_seasons = sorted({lg["season"] for lg in entry.chain})
    current_season = max(chain_seasons) if chain_seasons else None

    # --- Determine mode, label, baselines ---
    if year == "all":
        label = "Biggest All-Time Riser"
        context = "GM Rating positions gained all-time"
        first = min(seasons_with_data) if seasons_with_data else None
        baseline = season_ratings.get(str(first), {}) if first else {}
        compare = current_ratings

    elif isinstance(year, int) and year == current_season and is_in_season:
        label = "Biggest Weekly Rise"
        context = "GM Rating positions gained"
        baseline = prev_ratings
        compare = current_ratings

    elif isinstance(year, int) and year == current_season and not is_in_season:
        label = "Biggest Off-Season Riser"
        context = "GM Rating positions gained since last season"
        prev_season = max((s for s in seasons_with_data if s < year), default=None)
        baseline = season_ratings.get(str(prev_season), {}) if prev_season else {}
        compare = current_ratings

    else:  # past completed year
        label = "Biggest Year Riser"
        context = f"GM Rating positions gained in {year}"
        prev_year = max((s for s in seasons_with_data if s < year), default=None)
        baseline = season_ratings.get(str(prev_year), {}) if prev_year else {}
        compare = season_ratings.get(str(year), {})

    # --- Compute trends and find biggest riser ---
    if not baseline or not compare:
        return HeroStat(value="—", context=context, label=label)

    baseline_rank = {
        uid: i + 1
        for i, (uid, _) in enumerate(
            sorted(baseline.items(), key=lambda kv: kv[1], reverse=True)
        )
    }
    current_rank = {
        uid: i + 1
        for i, (uid, _) in enumerate(
            sorted(compare.items(), key=lambda kv: kv[1], reverse=True)
        )
    }
    trends = {
        uid: (baseline_rank.get(uid, current_rank[uid]) - current_rank[uid])
        for uid in compare
    }
    if not trends:
        return HeroStat(value="—", context=context, label=label)

    rise_uid = max(trends, key=lambda u: trends[u])
    rise = trends[rise_uid]
    if rise > 0:
        return HeroStat(
            value=f"▲{rise}",
            context=context,
            label=label,
            owner=owner_name(entry, rise_uid),
            owner_user_id=rise_uid,
        )
    return HeroStat(value="—", context=context, label=label)
```

- [ ] **Step 4: Update `_intel_hero_stats` to use `_rise_hero_stat`**

`_intel_hero_stats` currently computes `biggest_weekly_rise` inline. Change its signature to accept the mode params and delegate:

Replace the current `_intel_hero_stats` signature and `biggest_weekly_rise` block:

```python
def _intel_hero_stats(
    entry: ChainCacheEntry,
    ratings: dict[str, int],
    gm_trend_by_uid: dict[str, int],
    year: Year = "all",
    is_in_season: bool = False,
    prev_ratings: dict[str, int] | None = None,
) -> HeroStats:
    """Four intelligence-focused KPI cards: Top GM, Biggest Riser, Best Roster, Draft Ace."""
    outlook = entry.outlook_signals or {}

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

    # Biggest Riser (context-aware) -----------------------------------------
    biggest_weekly_rise = _rise_hero_stat(
        entry, ratings, year, is_in_season, prev_ratings or {}
    )

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

- [ ] **Step 5: Update `build_dashboard()` signature and `_intel_hero_stats` call**

Add `is_in_season: bool = False` to `build_dashboard` and thread it through:

```python
def build_dashboard(
    entry: ChainCacheEntry,
    year: Year,
    lens: Literal["ktc", "production"],
    prev_ratings: dict[str, int] | None = None,
    is_in_season: bool = False,
) -> DashboardResp:
```

And update the `_intel_hero_stats` call inside `build_dashboard`:

```python
    return DashboardResp(
        league=league,
        selected_year=year,
        selected_lens=lens,
        hero_stats=_intel_hero_stats(
            entry, ratings,
            gm_trend_by_uid=gm_trend_by_uid,
            year=year, is_in_season=is_in_season, prev_ratings=prev_ratings,
        ),
        standings=standings,
        latest_trades=_latest_trades(entry, trades),
        records=_records(entry, rows),
        total_trades=len(trades),
        warnings=entry.warnings,
    )
```

- [ ] **Step 6: Run tests**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && make test-api 2>&1 | tail -5
```

Expected: all passing, including the 4 new mode tests.

- [ ] **Step 7: Commit**

```bash
git add api/app/services/aggregations.py api/tests/test_aggregations.py
git commit -m "feat(dashboard): context-aware riser card — weekly/year/off-season/all-time modes"
```

---

## Task 6: Pass `is_in_season` from the dashboard route

**Files:**
- Modify: `api/app/routes/league.py`

- [ ] **Step 1: Add `is_in_season` detection and pass to `build_dashboard`**

In `api/app/routes/league.py`, add at the top:

```python
from datetime import datetime
```

Then in the `league` route handler, add one line before the `build_dashboard` call:

```python
    prev_ratings = load_prev_ratings(cache_dir, league_id)
    is_in_season = datetime.now().month in {9, 10, 11, 12, 1}
    return build_dashboard(
        entry, year=year_val, lens=lens,
        prev_ratings=prev_ratings, is_in_season=is_in_season,
    )
```

- [ ] **Step 2: Run route tests**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && make test-api 2>&1 | grep -E "test_league|PASSED|FAILED" | head -10
```

Expected: all passing.

- [ ] **Step 3: Commit**

```bash
git add api/app/routes/league.py
git commit -m "feat(route): pass is_in_season to build_dashboard for context-aware riser card"
```

---

## Task 7: Use dynamic label in the frontend

**Files:**
- Modify: `web/components/HeroStatsRow.tsx`

- [ ] **Step 1: Update the card 2 title to use the backend label**

In `web/components/HeroStatsRow.tsx`, change the `HeroStatCard` for `biggest_weekly_rise` — replace the hardcoded `title="Biggest Weekly Rise"` with the dynamic label:

```tsx
      <HeroStatCard
        title={biggest_weekly_rise.label ?? "Biggest Weekly Rise"}
        headline={biggest_weekly_rise.owner ?? undefined}
        value={biggest_weekly_rise.value}
        valueColor={biggest_weekly_rise.value !== "—" ? "pos" : "ink"}
        footer={biggest_weekly_rise.context}
        tooltip={TOOLTIPS.biggest_weekly_rise}
        href={ownerHref(biggest_weekly_rise.owner_user_id)}
      />
```

Also update the TOOLTIPS entry to match the general "Riser" concept (not just weekly):

```tsx
  biggest_weekly_rise: {
    title: "Biggest Riser",
    body: "Biggest GM Rating rank gain. In-season: week-over-week. Off-season: since last season ended. Past year: gain during that season. All years: since league start.",
  },
```

- [ ] **Step 2: Typecheck**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/web" && npx tsc --noEmit 2>&1 | head -5
```

Expected: no errors.

- [ ] **Step 3: Run full test suite**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && make test 2>&1 | tail -5
```

Expected: all passing.

- [ ] **Step 4: Commit**

```bash
git add web/components/HeroStatsRow.tsx
git commit -m "feat(dashboard): use dynamic backend label for riser card title"
```

---

## Task 8: Force refresh + smoke test

- [ ] **Step 1: Trigger a force refresh to populate `season_ratings`**

```bash
curl -s -N "http://localhost:8000/api/league/9000000000000000001/refresh?force=true" | grep -E "stage.*done|error"
```

Expected: `{"stage": "done"}` event appears.

- [ ] **Step 2: Verify `season_ratings` is now populated on the dashboard response**

```bash
curl -s "http://localhost:8000/api/league/9000000000000000001" | python3 -c "
import sys, json
d = json.load(sys.stdin)
card = d['hero_stats']['biggest_weekly_rise']
print('label:', card.get('label'))
print('value:', card['value'])
print('context:', card['context'])
"
```

Expected (in June, off-season, all-years default):
- `label`: `"Biggest All-Time Riser"` (on `year=all` default)
- `value`: `"▲N"` or `"—"` depending on whether season_ratings differ between first and current

- [ ] **Step 3: Verify year-tab context switching**

```bash
# Off-season (current year, June)
curl -s "http://localhost:8000/api/league/9000000000000000001?year=2026" | python3 -c "
import sys,json; d=json.load(sys.stdin); c=d['hero_stats']['biggest_weekly_rise']; print('label:', c.get('label'), '| value:', c['value'])"

# Past year
curl -s "http://localhost:8000/api/league/9000000000000000001?year=2025" | python3 -c "
import sys,json; d=json.load(sys.stdin); c=d['hero_stats']['biggest_weekly_rise']; print('label:', c.get('label'), '| value:', c['value'])"
```

Expected:
- `year=2026` → `label: "Biggest Off-Season Riser"`
- `year=2025` → `label: "Biggest Year Riser"`

- [ ] **Step 4: Commit any fixups, push, and deploy**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && git push origin main
railway up --service api --detach -m "feat: context-aware riser card with season_ratings"
railway up --service web --detach -m "feat: dynamic riser card title from backend"
```
