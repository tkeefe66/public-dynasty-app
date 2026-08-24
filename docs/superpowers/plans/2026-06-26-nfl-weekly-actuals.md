# NFL Weekly Actuals — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fetch NFL-wide weekly fantasy points for every player (scored to the league's settings, cached), and use it to make `production_after_drop` (drop regret) real — the points a dropped player piled up over the 10 NFL weeks after the owner cut him.

**Architecture:** A pure scoring/window module (`engine/nfl_actuals.py`) + a Sleeper `get_stats` fetch + a cached league-scored lookup built in `pull_supporting_data` → threaded into `grade_trade`/`build_asset_breakdown`, where the dormant matchup-based `production_after_drop` is replaced with a rolling-window NFL-actuals sum.

**Tech Stack:** Python 3.11, pytest, httpx (Sleeper), FileCache; React/vitest for the insight threshold.

## Global Constraints

- Drop-regret **window = 10 NFL weeks** after `last_rostered_week`, rolling across the 18-week season boundary ((Y,18)→(Y+1,1)).
- Points basis: NFL weekly fantasy points scored to the **league's `scoring_settings`** via `projections.normalize_projection(raw_stats, scoring)` — NOT Sleeper's standard `pts_*`.
- Insight surfaces at **≥ 100** league points over the window.
- Raw stats cached **per (season, week), league-agnostic** (`nfl_stats_{season}_{week}.json`); completed weeks effectively infinite TTL, current in-progress week short TTL.
- A stats-fetch failure logs and contributes **0** for that week — grading never fails on it (consistent with how stories/blurbs degrade).
- `nfl_points` is data passed into the pure engine; it defaults to `{}` so CLI/tests without it still work and produce `production_after_drop = 0`.
- Engine tests from repo root: `.venv/bin/python -m pytest`; API tests from `api/` with `../.venv/bin/python -m pytest`; FE: `cd web && npx vitest run --config tests/vitest.config.ts` and `npx tsc --noEmit`. Commit after each task.

---

### Task 1: `engine/nfl_actuals.py` — pure scoring + window

**Files:**
- Create: `src/sleeper_dynasty/engine/nfl_actuals.py`
- Test: `tests/test_nfl_actuals.py`

**Interfaces:**
- Produces:
  - `score_week(raw_stats: list[dict], scoring: dict[str, float]) -> dict[str, float]`
  - `next_n_weeks(start: tuple[int, int], n: int, weeks_per_season: int = 18) -> list[tuple[int, int]]`
  - `points_after_drop(pid: str, last_week: tuple[int, int], nfl_points: dict[tuple[int, int], dict[str, float]], window: int = 10) -> float`

- [ ] **Step 1: Write the failing tests**

`tests/test_nfl_actuals.py`:

```python
from sleeper_dynasty.engine.nfl_actuals import (
    score_week, next_n_weeks, points_after_drop,
)


def test_score_week_applies_league_scoring():
    raw = [
        {"player_id": "p1", "stats": {"rec": 5.0, "rec_yd": 80.0, "rec_td": 1.0}},
        {"player_id": "p2", "stats": {"rush_yd": 100.0}},
        {"stats": {"rec": 9.0}},          # no player_id -> skipped
        {"player_id": "p3"},               # no stats -> skipped
    ]
    scoring = {"rec": 1.0, "rec_yd": 0.1, "rec_td": 6.0, "rush_yd": 0.1}
    pts = score_week(raw, scoring)
    assert pts["p1"] == 19.0      # 5*1 + 80*0.1 + 1*6 = 5 + 8 + 6
    assert pts["p2"] == 10.0      # 100*0.1
    assert "p3" not in pts and len(pts) == 2


def test_next_n_weeks_rolls_over_season_boundary():
    assert next_n_weeks((2024, 16), 3) == [(2024, 17), (2024, 18), (2025, 1)]
    assert len(next_n_weeks((2024, 5), 10)) == 10
    assert next_n_weeks((2024, 5), 10)[-1] == (2024, 15)


def test_points_after_drop_sums_only_the_window():
    nfl = {
        (2024, 9): {"p1": 20.0, "x": 5.0},
        (2024, 10): {"p1": 18.0},
        (2024, 19): {"p1": 99.0},   # outside a 10-week window from wk8 -> capped at wk18
    }
    # last owned week 8; window weeks 9..18; wk19 (would be next season wk1) at n=10 is wk18
    total = points_after_drop("p1", (2024, 8), nfl, window=10)
    assert total == 38.0          # 20 + 18; the (2024,19) entry is outside weeks 9-18
    # a player with no data in the window -> 0
    assert points_after_drop("ghost", (2024, 8), nfl, window=10) == 0.0
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_nfl_actuals.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sleeper_dynasty.engine.nfl_actuals'`.

- [ ] **Step 3: Implement the module**

`src/sleeper_dynasty/engine/nfl_actuals.py`:

```python
"""NFL-wide weekly actuals: score any player's week to the league, and sum a
dropped player's production over a rolling post-drop window. Pure — no I/O."""

from __future__ import annotations

from sleeper_dynasty.api.projections import normalize_projection


def score_week(
    raw_stats: list[dict], scoring: dict[str, float]
) -> dict[str, float]:
    """{player_id: league fantasy points} for one NFL week's raw stat list.

    Each item is a Sleeper stats row: {"player_id": str, "stats": {stat: val}}.
    Rows lacking a player_id or stats are skipped.
    """
    out: dict[str, float] = {}
    for item in raw_stats:
        pid = item.get("player_id")
        stats = item.get("stats")
        if not pid or not stats:
            continue
        out[pid] = normalize_projection(stats, scoring)
    return out


def next_n_weeks(
    start: tuple[int, int], n: int, weeks_per_season: int = 18
) -> list[tuple[int, int]]:
    """The n (season, week) keys strictly after `start`, rolling across the
    season boundary (after (Y, weeks_per_season) comes (Y+1, 1))."""
    out: list[tuple[int, int]] = []
    season, week = start
    for _ in range(n):
        week += 1
        if week > weeks_per_season:
            season += 1
            week = 1
        out.append((season, week))
    return out


def points_after_drop(
    pid: str,
    last_week: tuple[int, int],
    nfl_points: dict[tuple[int, int], dict[str, float]],
    window: int = 10,
) -> float:
    """League points `pid` scored over the `window` NFL weeks after `last_week`."""
    total = 0.0
    for wk in next_n_weeks(last_week, window):
        total += float((nfl_points.get(wk) or {}).get(pid, 0.0) or 0.0)
    return round(total, 2)
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_nfl_actuals.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/nfl_actuals.py tests/test_nfl_actuals.py
git commit -m "feat(nfl-actuals): pure scoring + rolling post-drop window"
```

---

### Task 2: Sleeper `get_stats` + cached league-scored `nfl_points`

**Files:**
- Modify: `src/sleeper_dynasty/api/sleeper.py` (add `get_stats`, after `get_projections` ~272-281)
- Modify: `api/app/services/grader_io.py` (add `fetch_nfl_points`; call it in `pull_supporting_data`, add `nfl_points` to the returned dict)
- Test: `api/tests/test_nfl_points_fetch.py`

**Interfaces:**
- Consumes: `score_week` (Task 1).
- Produces: `SleeperClient.get_stats(season, week) -> list[dict]`; `fetch_nfl_points(client, season_weeks, scoring, cache, *, current_sw=None) -> dict[tuple[int,int], dict[str,float]]`; `supporting["nfl_points"]` (same shape).

- [ ] **Step 1: Add `get_stats` to the Sleeper client**

In `src/sleeper_dynasty/api/sleeper.py`, after `get_projections`:

```python
    async def get_stats(self, season: int, week: int) -> list:
        """Raw NFL stats for ALL players in one regular-season week."""
        resp = await self._client.get(f"/stats/nfl/regular/{season}/{week}")
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else []
```

- [ ] **Step 2: Write the failing test for `fetch_nfl_points`**

`api/tests/test_nfl_points_fetch.py`:

```python
import asyncio
from app.services.grader_io import fetch_nfl_points


class FakeClient:
    def __init__(self):
        self.calls = []
        self.weeks = {
            (2024, 9): [{"player_id": "p1", "stats": {"rec": 5.0}}],
            (2024, 10): [{"player_id": "p1", "stats": {"rec": 3.0}}],
        }

    async def get_stats(self, season, week):
        self.calls.append((season, week))
        return self.weeks.get((season, week), [])


class FailClient(FakeClient):
    async def get_stats(self, season, week):
        self.calls.append((season, week))
        raise RuntimeError("sleeper down")


def test_fetch_scores_and_caches(tmp_path):
    from sleeper_dynasty.cache import FileCache
    cache = FileCache(cache_dir=tmp_path)
    client = FakeClient()
    scoring = {"rec": 1.0}
    pts = asyncio.run(fetch_nfl_points(
        client, [(2024, 9), (2024, 10)], scoring, cache))
    assert pts[(2024, 9)]["p1"] == 5.0
    assert pts[(2024, 10)]["p1"] == 3.0
    assert len(client.calls) == 2
    # second run: completed weeks served from cache, no new fetches
    client2 = FakeClient()
    pts2 = asyncio.run(fetch_nfl_points(
        client2, [(2024, 9), (2024, 10)], scoring, cache))
    assert pts2[(2024, 9)]["p1"] == 5.0
    assert client2.calls == []


def test_fetch_failure_degrades_to_zero(tmp_path):
    from sleeper_dynasty.cache import FileCache
    cache = FileCache(cache_dir=tmp_path)
    client = FailClient()
    pts = asyncio.run(fetch_nfl_points(client, [(2024, 9)], {"rec": 1.0}, cache))
    assert pts[(2024, 9)] == {}        # failed fetch -> empty, no exception
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd api && ../.venv/bin/python -m pytest tests/test_nfl_points_fetch.py -v`
Expected: FAIL — `cannot import name 'fetch_nfl_points'`.

- [ ] **Step 4: Implement `fetch_nfl_points`**

In `api/app/services/grader_io.py`, add near the top imports:

```python
from sleeper_dynasty.cache import FileCache, ONE_DAY
from sleeper_dynasty.engine.nfl_actuals import score_week
```

and the function (module level):

```python
_NFL_STATS_TTL_HISTORICAL = 10 ** 9  # completed weeks never change


async def fetch_nfl_points(
    client,
    season_weeks: list[tuple[int, int]],
    scoring: dict[str, float],
    cache: "FileCache | None",
    *,
    current_sw: tuple[int, int] | None = None,
) -> dict[tuple[int, int], dict[str, float]]:
    """{(season, week): {player_id: league points}} for the given weeks.

    Raw stats cached league-agnostically per week; the current in-progress week
    uses a short TTL, completed weeks effectively never expire. A failed fetch
    contributes an empty week (0 for everyone), never raises.
    """
    out: dict[tuple[int, int], dict[str, float]] = {}
    for sw in season_weeks:
        season, week = sw
        key = f"nfl_stats_{season}_{week}.json"
        ttl = ONE_DAY if sw == current_sw else _NFL_STATS_TTL_HISTORICAL
        raw = cache.read(key, max_age_seconds=ttl) if cache is not None else None
        if raw is None:
            try:
                raw = await client.get_stats(season, week)
            except Exception as e:
                log.warning("NFL stats fetch failed for %s wk%s: %s", season, week, e)
                raw = []
            if cache is not None and raw:
                cache.write(key, raw)
        out[sw] = score_week(raw or [], scoring)
    return out
```

- [ ] **Step 5: Run the test (green)**

Run: `cd api && ../.venv/bin/python -m pytest tests/test_nfl_points_fetch.py -v`
Expected: PASS.

- [ ] **Step 6: Wire `nfl_points` into `pull_supporting_data`**

In `pull_supporting_data` (`grader_io.py`), after the matchup loop populates `matchups` + `league_season_by_id` (after line ~215), add:

```python
    # NFL-wide weekly actuals, scored to THIS league, for drop regret.
    season_weeks = sorted({
        (league_season_by_id.get(lg, 0), wk)
        for (lg, wk, _rid) in matchups.keys()
        if league_season_by_id.get(lg, 0)
    })
    scoring = chain[0].scoring_settings if chain else {}
    current_sw = None
    try:
        st = await client.get_nfl_state()
        if st.get("season") and st.get("week"):
            current_sw = (int(st["season"]), int(st["week"]))
    except Exception:
        pass
    nfl_cache = FileCache(getattr(league_cache, "cache_dir", None) or DEFAULT_CACHE_DIR)
    try:
        nfl_points = await fetch_nfl_points(
            client, season_weeks, scoring, nfl_cache, current_sw=current_sw)
    except Exception as e:
        log.warning("NFL points unavailable: %s", e)
        nfl_points = {}
```

Add `from sleeper_dynasty.cache import DEFAULT_CACHE_DIR` to the imports (alongside `FileCache, ONE_DAY`). Then add `"nfl_points": nfl_points,` to the `return { ... }` dict (the one near line 231).

- [ ] **Step 7: Run the grader_io / supporting tests**

Run: `cd api && ../.venv/bin/python -m pytest tests/test_nfl_points_fetch.py tests/ -k "supporting or grader_io or nfl" -q`
Expected: PASS (new test + any existing supporting-data tests still pass; `nfl_points` key added is additive).

- [ ] **Step 8: Commit**

```bash
git add src/sleeper_dynasty/api/sleeper.py api/app/services/grader_io.py api/tests/test_nfl_points_fetch.py
git commit -m "feat(nfl-actuals): get_stats + cached league-scored nfl_points in supporting"
```

---

### Task 3: True `production_after_drop` in the engine

**Files:**
- Modify: `src/sleeper_dynasty/engine/trade_grader.py` (replace `_points_after_owned`; add `nfl_points` to `build_asset_breakdown` + `grade_trade`)
- Modify: `api/app/services/grader.py` (pass `nfl_points` to `grade_trade`, ~471-483)
- Test: `tests/test_trade_grader.py` (replace the old after-drop test)

**Interfaces:**
- Consumes: `points_after_drop` (Task 1); `supporting["nfl_points"]` (Task 2).
- Produces: `build_asset_breakdown(..., nfl_points={})` and `grade_trade(..., nfl_points={})`; `AssetLine.production_after_drop` = league points scored over the 10 weeks after the player's last owned week.

- [ ] **Step 1: Replace the old after-drop engine test**

In `tests/test_trade_grader.py`, replace `test_production_after_drop_counts_post_departure_started_points` with an NFL-actuals version:

```python
def test_production_after_drop_uses_nfl_actuals_window():
    # Mike rosters p1 weeks 5-6, then no longer; p1's NFL actuals after wk6 (the
    # 10-week window 7..16) are summed regardless of any league roster.
    rt = _started_trade()
    matchups = {
        ("L", 5, 1): {"players": ["p1"], "starters": ["p1"],
                      "players_points": {"p1": 10.0},
                      "team_points": 100.0, "opponent_points": 90.0},
        ("L", 6, 1): {"players": ["p1"], "starters": [],
                      "players_points": {"p1": 4.0},
                      "team_points": 100.0, "opponent_points": 90.0},
    }
    nfl_points = {
        (2024, 7): {"p1": 18.0},
        (2024, 8): {"p1": 22.0},
        (2024, 17): {"p1": 50.0},   # outside the 10-week window (7..16) -> excluded
    }
    grade = grade_trade(
        rt, ktc_values={}, matchups=matchups,
        roster_to_user_by_league={"L": {1: "u_mike"}},
        playoff_week_start_by_league={"L": 15}, phase_by_lwr={},
        league_season_by_id={"L": 2024}, nfl_points=nfl_points,
    )
    line = grade.breakdown["u_mike"][0]
    assert line.production_after_drop == 40.0   # 18 + 22; wk17 excluded
    # no nfl_points -> 0 (CLI/back-compat path)
    g2 = grade_trade(
        rt, ktc_values={}, matchups=matchups,
        roster_to_user_by_league={"L": {1: "u_mike"}},
        playoff_week_start_by_league={"L": 15}, phase_by_lwr={},
        league_season_by_id={"L": 2024},
    )
    assert g2.breakdown["u_mike"][0].production_after_drop == 0.0
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_trade_grader.py::test_production_after_drop_uses_nfl_actuals_window -v`
Expected: FAIL — `grade_trade() got an unexpected keyword argument 'nfl_points'`.

- [ ] **Step 3: Replace `_points_after_owned` with the NFL-actuals version**

In `src/sleeper_dynasty/engine/trade_grader.py`, replace the `_points_after_owned` function body with one that uses the lookup. It needs the player's last owned (season, week); compute it from `player_week_points`, fall back to the trade's (season, week) when the player never appeared (drafted-then-cut-before-playing):

```python
from sleeper_dynasty.engine.nfl_actuals import points_after_drop as _pad


def _points_after_owned(
    pid: str,
    uid: str,
    *,
    matchups: dict[tuple[str, int, int], dict],
    roster_to_user_by_league: dict[str, dict[int, str]],
    rt: ResolvedTrade,
    league_season_by_id: dict[str, int] | None = None,
    nfl_points: dict[tuple[int, int], dict[str, float]] | None = None,
    **_ignore,
) -> float:
    """League points `pid` scored over the 10 NFL weeks after the last week
    `uid` rostered him post-trade — the drop-regret figure. 0 without nfl_points."""
    if not nfl_points:
        return 0.0
    league_season_by_id = league_season_by_id or {}
    owned = player_week_points(
        pid, uid, matchups=matchups,
        roster_to_user_by_league=roster_to_user_by_league,
        rt=rt, league_season_by_id=league_season_by_id,
    )
    last_week = max(owned.keys()) if owned else (rt.trade.season, rt.trade.week)
    return _pad(pid, last_week, nfl_points, window=10)
```

(Delete the old loop-over-matchups body.)

- [ ] **Step 4: Thread `nfl_points` through `build_asset_breakdown` and `grade_trade`**

In `build_asset_breakdown`, add a parameter `nfl_points: dict[tuple[int, int], dict[str, float]] | None = None,` (after `tiered_values`), include it in the per-player `common` dict so it reaches `_points_after_owned`:

```python
                common = dict(
                    matchups=matchups,
                    roster_to_user_by_league=roster_to_user_by_league,
                    rt=rt, league_season_by_id=league_season_by_id,
                    phase_by_lwr=phase_by_lwr,
                    playoff_week_start_by_league=playoff_week_start_by_league,
                    nfl_points=nfl_points,
                )
```

(`_points_while_owned` already swallows unknown kwargs via its explicit signature — confirm it does NOT receive `nfl_points`: it has a fixed signature, so passing `nfl_points` via `**common` would error. Fix: keep a separate dict. See Step 4a.)

- [ ] **Step 4a: Keep `nfl_points` out of `_points_while_owned`'s kwargs**

`_points_while_owned` has a fixed signature and will reject `nfl_points`. So do NOT add `nfl_points` to `common`. Instead pass it only to the after-drop call:

```python
                    production_started=_points_while_owned(
                        a.player_id, uid, starters_only=True, **common),
                    production_after_drop=_points_after_owned(
                        a.player_id, uid, nfl_points=nfl_points, **common),
```

(`_points_after_owned` already accepts `**_ignore`, so the extra phase kwargs in `common` are harmless to it.) Leave `common` as it was (no `nfl_points` key).

In `grade_trade`, add `nfl_points: dict[tuple[int, int], dict[str, float]] | None = None,` to the signature and pass it to `build_asset_breakdown(..., nfl_points=nfl_points)`.

- [ ] **Step 5: Pass `nfl_points` from the API grader**

In `api/app/services/grader.py`, the `grade_trade(...)` call (~471), add:

```python
                nfl_points=supporting.get("nfl_points") or {},
```

- [ ] **Step 6: Run the engine + grader tests**

Run: `.venv/bin/python -m pytest tests/test_trade_grader.py -q`
Expected: PASS (new after-drop test + existing grader tests; `production_started` etc. unchanged).

- [ ] **Step 7: Commit**

```bash
git add src/sleeper_dynasty/engine/trade_grader.py api/app/services/grader.py tests/test_trade_grader.py
git commit -m "feat(nfl-actuals): production_after_drop = NFL actuals over the post-drop window"
```

---

### Task 4: Repopulate on deploy + light up the insight

**Files:**
- Modify: `api/app/services/chain_cache.py` (`SCHEMA_VERSION`)
- Modify: `web/components/TradeHero.tsx` (drop-regret threshold + wording)
- Test: `web/tests/TradeHero.test.tsx`

**Interfaces:**
- Consumes: `AssetLine.production_after_drop` (now real, Task 3) on the trade-detail response.

- [ ] **Step 1: Bump the cache schema**

In `api/app/services/chain_cache.py`, increment `SCHEMA_VERSION` by 1 and update its inline comment to note "production_after_drop now from NFL actuals". This forces a re-grade on deploy so the field repopulates with true values.

- [ ] **Step 2: Write/adjust the FE insight test**

In `web/tests/TradeHero.test.tsx`, add a test that the drop-regret insight renders when a dropped player has `production_after_drop >= 100`:

```python
  it("surfaces drop regret when a dropped player balled afterward", () => {
    const dropped = {
      label: "Geno Smith", kind: "player" as const, player_id: "g",
      ktc: 0, production_total: 0, production_regular: 0, production_playoff: 0,
      production_toilet: 0, production_started: 0, production_after_drop: 180,
      terminal_state: "dropped" as const,
    };
    const winner = makeSide({ user_id: "u1", owner_name: "Mikey", received_ktc: 9000, production_started: 700 });
    const loser = makeSide({ user_id: "u2", owner_name: "Tom", received_ktc: 1000, production_started: 100, breakdown: [dropped] });
    render(
      <TradeHero sides={[winner, loser]} story={story} lopsidedness={0.9}
                 winner_user_id="u1" twist={null} />,
    );
    expect(screen.getByText(/dropped Geno Smith, who put up 180 over the next 10 weeks/i)).toBeTruthy();
  });
```

(Note: this is a `.tsx` test — use the TS arrow-fn syntax shown, not Python.)

- [ ] **Step 3: Run to verify it fails**

Run: `cd web && npx vitest run --config tests/vitest.config.ts tests/TradeHero.test.tsx`
Expected: FAIL — the dormant generator's threshold/wording doesn't match (it referenced the old `production_after_drop` semantics; update it).

- [ ] **Step 4: Update the drop-regret generator**

In `web/components/TradeHero.tsx`, set the drop-regret generator to fire at `>= 100` with the window wording. Find the existing drop-regret block in `buildInsights` and make it:

```tsx
  // Drop regret — a player the loser cut who then piled up NFL points.
  let regret: { label: string; after: number } | null = null;
  for (const r of loser.breakdown ?? []) {
    const realized = r.flip?.became?.length ? r.flip.became : [r];
    for (const a of realized) {
      const after = a.production_after_drop ?? 0;
      if (a.terminal_state === "dropped" && after >= 100) {
        if (!regret || after > regret.after) regret = { label: a.label, after };
      }
    }
  }
  if (regret) {
    out.push({
      stat: `${fmtInt(regret.after)} pts`,
      text: `${loser.owner_name} dropped ${regret.label}, who put up ${fmtInt(regret.after)} over the next 10 weeks`,
      tone: "neg",
    });
  }
```

- [ ] **Step 5: Verify FE green + typecheck + build**

Run: `cd web && npx vitest run --config tests/vitest.config.ts && npx tsc --noEmit && npm run build`
Expected: all PASS (do NOT run `npm run build` against a live `next dev`).

- [ ] **Step 6: Commit**

```bash
git add api/app/services/chain_cache.py web/components/TradeHero.tsx web/tests/TradeHero.test.tsx
git commit -m "feat(nfl-actuals): repopulate via schema bump + drop-regret insight at 100+ over 10 weeks"
```

---

## Self-Review

**Spec coverage:** substrate (get_stats + cached league-scored lookup) → Tasks 1+2; drop regret over 10-week rolling window scored to league → Tasks 1+3; insight at ≥100 → Task 4; league-agnostic raw-stats cache + completed-vs-current TTL → Task 2; failure-degrades-to-0 → Task 2; SCHEMA_VERSION repopulate → Task 4; nfl_points defaults to {} for CLI/back-compat → Tasks 2/3. Scoring caveat (normalize_projection) — covered by reuse; the implementer should log unmatched scoring keys against a sample week (noted in spec; optional diagnostic, not a task gate). Deferred FA-pickup/phantom — out of scope ✓.

**Placeholder scan:** Step 4/4a of Task 3 reference "the per-player `common` dict" and "find the existing drop-regret block" rather than pasting the whole function — acceptable: exact insertion code + the surrounding anchor are given, and Step 4a explicitly resolves the `_points_while_owned` kwargs hazard. No TBD/TODO.

**Type consistency:** `nfl_points: dict[tuple[int,int], dict[str,float]]` is used identically across `fetch_nfl_points` (Task 2), `points_after_drop`/`_points_after_owned` (Tasks 1/3), `build_asset_breakdown`/`grade_trade` (Task 3), and `supporting["nfl_points"]` (Task 2). `production_after_drop: float` matches the existing AssetLine field. The FE generator reads `a.production_after_drop` (optional number, already in the FE type). Consistent.

**One verification for the implementer:** confirm `chain[0]` is the entry/current league (so its `scoring_settings` is the right one); if `walk_league_history` orders oldest-first, use the league whose `league_id == current_league_id` instead.
