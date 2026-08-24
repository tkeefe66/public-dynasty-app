> _Historical doc — paths/names have changed. Repo is now `Code Apps/public-dynasty` (GitHub `tkeefe66/public-dynasty-app`), Railway project **shimmering-nature**, live at https://ffbdynasty.com. Ignore stale refs to `sleeper-dynasty` / `sleeper-trade-grader` / `web-production-f949`._

# Incremental Raw-Data Caching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the API refresh from re-pulling sealed historical seasons — cache the raw fetch bundle per `status == "complete"` league, re-fetch only the current season, and re-grade everything in memory each refresh.

**Architecture:** A new `LeagueRawCache` (JSON on the cache volume, one file per league) stores two bundles — a *trade bundle* (from the engine's `_fetch_league_season_data`) and a *matchup bundle* (from the API's `pull_supporting_data` per-league loop). Both fetchers gain an optional, duck-typed `league_cache` param and load-or-fetch gated on `league.status`. The engine stays decoupled (never imports the API cache — it just calls methods on whatever object it's handed). `GraderService.run` constructs the cache and threads it in, plus a `force` bypass and a `get_players()` de-duplication. The `ChainCacheEntry` output blob and the 409/SSE contract are unchanged.

**Tech Stack:** Python 3.11, dataclasses, pytest + pytest-asyncio. Engine: `src/sleeper_dynasty/`. API: `api/app/`. Spec: `docs/superpowers/specs/2026-05-31-incremental-raw-data-caching-design.md`.

---

## File Structure

- `api/app/services/league_raw_cache.py` — **new.** `LeagueRawCache` + `SCHEMA_VERSION`. Typed read/write for the two bundles, handling tuple-keyed matchups and int-keyed rosters.
- `src/sleeper_dynasty/engine/trade_history.py` — `_fetch_league_season_data` and `build_trade_history` gain optional `league_cache`.
- `api/app/services/grader_io.py` — `pull_supporting_data` gains `league_cache` + `players`; per-league loop refactored into a cache-aware helper.
- `api/app/services/grader.py` — `GraderService.run` gains `cache_dir` + `force`, builds the cache, threads it + the players blob into both fetchers.
- `api/app/routes/refresh.py` — accept `?force=1`, pass cache dir + force into `run`.
- Tests: `api/tests/test_league_raw_cache.py` (new), `tests/test_trade_history.py`, `api/tests/test_grader_io.py`, `api/tests/test_grader_service.py`.

Engine tests run via the project venv: `.venv/bin/python -m pytest tests/ -q --import-mode=importlib`. API tests: `cd api && ../.venv/bin/python -m pytest -q`.

---

## Bundle shapes (reference — used across tasks)

**Trade bundle** (what `_fetch_league_season_data` returns, minus `league`):
```python
{
    "users": dict[str, dict],                  # uid -> sleeper user info
    "roster_to_user": dict[int, str],          # roster_id -> uid   (int keys!)
    "raw_trades": list[dict],
    "drafts": list[dict],
    "draft_picks_by_draft_id": dict[str, list[dict]],
}
```

**Matchup bundle** (per-league slice of `pull_supporting_data`):
```python
{
    "matchups": dict[tuple[str, int, int], dict],  # (league_id, week, roster_id) -> entry  (tuple keys!)
    "playoff_week_start": int,
    "roster_to_user": dict[int, str],              # int keys!
    "league_name": str,
    "season": int,
    "display_names": dict[str, str],               # this league's uid -> display name
}
```

JSON can't hold tuple keys or int keys, so `LeagueRawCache` converts both on the way in/out (Task 1).

---

## Task 1: `LeagueRawCache`

**Files:**
- Create: `api/app/services/league_raw_cache.py`
- Test: `api/tests/test_league_raw_cache.py`

- [ ] **Step 1: Write the failing tests**

Create `api/tests/test_league_raw_cache.py`:

```python
from __future__ import annotations

from app.services.league_raw_cache import LeagueRawCache, SCHEMA_VERSION


def _trade_bundle():
    return {
        "users": {"u_a": {"display_name": "Alice"}},
        "roster_to_user": {1: "u_a", 2: "u_b"},
        "raw_trades": [{"transaction_id": "t1"}],
        "drafts": [{"draft_id": "d1", "status": "complete"}],
        "draft_picks_by_draft_id": {"d1": [{"round": 1, "player_id": "p1"}]},
    }


def _matchup_bundle():
    return {
        "matchups": {
            ("L1", 5, 1): {"starters": ["p1"], "players": ["p1"],
                           "players_points": {"p1": 20.0},
                           "team_points": 100.0, "opponent_points": 90.0},
            ("L1", 5, 2): {"starters": ["p2"], "players": ["p2"],
                           "players_points": {"p2": 10.0},
                           "team_points": 90.0, "opponent_points": 100.0},
        },
        "playoff_week_start": 15,
        "roster_to_user": {1: "u_a", 2: "u_b"},
        "league_name": "Bros",
        "season": 2024,
        "display_names": {"u_a": "Alice", "u_b": "Bob"},
    }


def test_trade_bundle_round_trip_coerces_int_keys(tmp_path):
    cache = LeagueRawCache(cache_dir=tmp_path)
    cache.write_trade_bundle("L1", _trade_bundle())
    got = cache.read_trade_bundle("L1")
    assert got == _trade_bundle()           # int roster keys restored
    assert all(isinstance(k, int) for k in got["roster_to_user"])


def test_matchup_bundle_round_trip_rebuilds_tuple_keys(tmp_path):
    cache = LeagueRawCache(cache_dir=tmp_path)
    cache.write_matchup_bundle("L1", _matchup_bundle())
    got = cache.read_matchup_bundle("L1")
    assert got == _matchup_bundle()         # tuple matchup keys + int roster keys restored
    assert all(isinstance(k, tuple) and len(k) == 3 for k in got["matchups"])


def test_writing_one_bundle_preserves_the_other(tmp_path):
    cache = LeagueRawCache(cache_dir=tmp_path)
    cache.write_trade_bundle("L1", _trade_bundle())
    cache.write_matchup_bundle("L1", _matchup_bundle())   # must not clobber trade bundle
    assert cache.read_trade_bundle("L1") == _trade_bundle()
    assert cache.read_matchup_bundle("L1") == _matchup_bundle()


def test_missing_file_and_missing_bundle_return_none(tmp_path):
    cache = LeagueRawCache(cache_dir=tmp_path)
    assert cache.read_trade_bundle("nope") is None
    cache.write_trade_bundle("L1", _trade_bundle())
    assert cache.read_matchup_bundle("L1") is None       # file exists, bundle absent


def test_schema_version_mismatch_is_a_miss(tmp_path):
    import json
    cache = LeagueRawCache(cache_dir=tmp_path)
    cache.write_trade_bundle("L1", _trade_bundle())
    path = tmp_path / "raw_L1.json"
    raw = json.loads(path.read_text())
    raw["schema_version"] = SCHEMA_VERSION + 999
    path.write_text(json.dumps(raw))
    assert cache.read_trade_bundle("L1") is None


def test_force_bypasses_reads_but_still_writes(tmp_path):
    cache = LeagueRawCache(cache_dir=tmp_path)
    cache.write_trade_bundle("L1", _trade_bundle())
    forced = LeagueRawCache(cache_dir=tmp_path, force=True)
    assert forced.read_trade_bundle("L1") is None        # read bypassed
    forced.write_trade_bundle("L1", _trade_bundle())     # write still happens
    assert LeagueRawCache(cache_dir=tmp_path).read_trade_bundle("L1") == _trade_bundle()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/api" && ../.venv/bin/python -m pytest tests/test_league_raw_cache.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.league_raw_cache'`

- [ ] **Step 3: Implement `LeagueRawCache`**

Create `api/app/services/league_raw_cache.py`:

```python
"""Per-league raw-fetch cache for sealed (status == "complete") seasons.

Stores two independently-readable bundles per league in one JSON file:
  - trade_bundle: output of the engine's _fetch_league_season_data (minus League)
  - matchup_bundle: the per-league slice of pull_supporting_data

Sealed-season raw data is immutable, so there is no TTL; a SCHEMA_VERSION
mismatch is treated as a miss so a format change can't be misread. ``force``
bypasses reads (writes still happen) for operator-triggered re-pulls.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1


class LeagueRawCache:
    def __init__(self, cache_dir: Path, force: bool = False):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.force = force

    def _path(self, league_id: str) -> Path:
        return self.cache_dir / f"raw_{league_id}.json"

    def _load_file(self, league_id: str) -> dict[str, Any] | None:
        path = self._path(league_id)
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text())
        except (OSError, ValueError) as e:
            log.warning("raw cache unreadable for %s (%s); ignoring", league_id, e)
            return None
        if raw.get("schema_version") != SCHEMA_VERSION:
            return None
        return raw

    def _write_bundle(self, league_id: str, key: str, payload: dict[str, Any]) -> None:
        existing = self._load_file(league_id) or {
            "schema_version": SCHEMA_VERSION, "league_id": league_id,
            "trade_bundle": None, "matchup_bundle": None,
        }
        existing["schema_version"] = SCHEMA_VERSION
        existing["league_id"] = league_id
        existing[key] = payload
        self._path(league_id).write_text(json.dumps(existing))

    # -- trade bundle ------------------------------------------------------

    def read_trade_bundle(self, league_id: str) -> dict[str, Any] | None:
        if self.force:
            return None
        raw = self._load_file(league_id)
        if raw is None or raw.get("trade_bundle") is None:
            return None
        b = raw["trade_bundle"]
        b["roster_to_user"] = {int(k): v for k, v in b["roster_to_user"].items()}
        return b

    def write_trade_bundle(self, league_id: str, bundle: dict[str, Any]) -> None:
        # roster_to_user int keys JSON-stringify on dump; read coerces back.
        self._write_bundle(league_id, "trade_bundle", bundle)

    # -- matchup bundle ----------------------------------------------------

    def read_matchup_bundle(self, league_id: str) -> dict[str, Any] | None:
        if self.force:
            return None
        raw = self._load_file(league_id)
        if raw is None or raw.get("matchup_bundle") is None:
            return None
        b = dict(raw["matchup_bundle"])
        b["roster_to_user"] = {int(k): v for k, v in b["roster_to_user"].items()}
        b["matchups"] = {
            (league_id, int(r["week"]), int(r["roster_id"])): r["entry"]
            for r in b["matchups"]
        }
        return b

    def write_matchup_bundle(self, league_id: str, bundle: dict[str, Any]) -> None:
        payload = dict(bundle)
        payload["matchups"] = [
            {"week": wk, "roster_id": rid, "entry": entry}
            for (_lg, wk, rid), entry in bundle["matchups"].items()
        ]
        self._write_bundle(league_id, "matchup_bundle", payload)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/api" && ../.venv/bin/python -m pytest tests/test_league_raw_cache.py -q`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add api/app/services/league_raw_cache.py api/tests/test_league_raw_cache.py
git commit -m "feat: LeagueRawCache stores per-league trade + matchup bundles"
```

---

## Task 2: Cache the trade bundle in the engine

**Files:**
- Modify: `src/sleeper_dynasty/engine/trade_history.py` (`_fetch_league_season_data` ~317-360; `build_trade_history` ~363-411)
- Test: `tests/test_trade_history.py`

The engine must NOT import the API cache. `league_cache` is any object exposing
`read_trade_bundle(league_id)` / `write_trade_bundle(league_id, bundle)`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_trade_history.py`:

```python
def test_fetch_league_season_data_uses_cache_for_sealed_league():
    import asyncio
    from types import SimpleNamespace
    from sleeper_dynasty.engine.trade_history import _fetch_league_season_data

    class FakeCache:
        def __init__(self, stored): self.stored = stored; self.writes = []
        def read_trade_bundle(self, lid): return self.stored.get(lid)
        def write_trade_bundle(self, lid, b): self.writes.append((lid, b))

    class FailClient:
        # Any network access is a test failure for the sealed/cached path.
        async def get_users(self, *a): raise AssertionError("network hit")
        async def get_rosters(self, *a): raise AssertionError("network hit")
        async def get_transactions(self, *a): raise AssertionError("network hit")
        async def get_drafts(self, *a): raise AssertionError("network hit")
        async def get_draft_picks(self, *a): raise AssertionError("network hit")

    sealed = SimpleNamespace(league_id="L1", season=2024, name="Bros",
                             status="complete")
    bundle = {
        "users": {"u_a": {}}, "roster_to_user": {1: "u_a"},
        "raw_trades": [], "drafts": [], "draft_picks_by_draft_id": {},
    }
    cache = FakeCache({"L1": dict(bundle)})

    out = asyncio.run(_fetch_league_season_data(FailClient(), sealed, cache))
    # League re-attached; rest comes straight from cache; nothing written.
    assert out["league"] is sealed
    assert out["raw_trades"] == [] and out["roster_to_user"] == {1: "u_a"}
    assert cache.writes == []


def test_fetch_league_season_data_fetches_and_stores_when_sealed_and_uncached():
    import asyncio
    from types import SimpleNamespace
    from sleeper_dynasty.engine.trade_history import _fetch_league_season_data

    class FakeCache:
        def __init__(self): self.store = {}; self.writes = 0
        def read_trade_bundle(self, lid): return self.store.get(lid)
        def write_trade_bundle(self, lid, b): self.store[lid] = b; self.writes += 1

    class StubClient:
        async def get_users(self, lid): return {"u_a": {}}
        async def get_rosters(self, lid):
            return [SimpleNamespace(roster_id=1, owner_id="u_a")]
        async def get_transactions(self, lid, w): return []
        async def get_drafts(self, lid): return []
        async def get_draft_picks(self, did): return []

    sealed = SimpleNamespace(league_id="L1", season=2024, name="Bros",
                             status="complete")
    cache = FakeCache()
    out = asyncio.run(_fetch_league_season_data(StubClient(), sealed, cache))
    assert out["roster_to_user"] == {1: "u_a"}
    assert cache.writes == 1
    assert "league" not in cache.store["L1"]   # League object excluded from cache


def test_fetch_league_season_data_never_caches_current_season():
    import asyncio
    from types import SimpleNamespace
    from sleeper_dynasty.engine.trade_history import _fetch_league_season_data

    class FakeCache:
        def __init__(self): self.reads = 0; self.writes = 0
        def read_trade_bundle(self, lid): self.reads += 1; return None
        def write_trade_bundle(self, lid, b): self.writes += 1

    class StubClient:
        async def get_users(self, lid): return {}
        async def get_rosters(self, lid): return []
        async def get_transactions(self, lid, w): return []
        async def get_drafts(self, lid): return []
        async def get_draft_picks(self, did): return []

    current = SimpleNamespace(league_id="L1", season=2026, name="Bros",
                              status="in_season")
    cache = FakeCache()
    asyncio.run(_fetch_league_season_data(StubClient(), current, cache))
    assert cache.reads == 0 and cache.writes == 0  # status gating skips cache entirely
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_trade_history.py::test_fetch_league_season_data_uses_cache_for_sealed_league -q`
Expected: FAIL with `TypeError: _fetch_league_season_data() takes 2 positional arguments but 3 were given`

- [ ] **Step 3: Add caching to `_fetch_league_season_data`**

Replace the `_fetch_league_season_data` function in `src/sleeper_dynasty/engine/trade_history.py` with:

```python
async def _fetch_league_season_data(
    client,
    league,
    league_cache=None,
) -> dict:
    """Pull everything we need for one league-season.

    Returns a dict bundling users, roster_to_user, raw transactions (only
    trades), drafts, and draft_picks_by_draft_id, plus the ``league`` object.

    When ``league_cache`` is provided and the league is sealed
    (``status == "complete"``), the bundle (minus the League object) is loaded
    from / stored in the cache, avoiding all network fetches for that season.
    The current/incomplete season is always fetched and never cached.
    """
    sealed = league_cache is not None and getattr(league, "status", None) == "complete"
    if sealed:
        cached = league_cache.read_trade_bundle(league.league_id)
        if cached is not None:
            return {"league": league, **cached}

    users = await client.get_users(league.league_id)
    rosters = await client.get_rosters(league.league_id)
    roster_to_user = {r.roster_id: r.owner_id for r in rosters}

    async def _one_week(w: int) -> list[dict]:
        return await client.get_transactions(league.league_id, w)

    weeks = range(1, _MAX_WEEK + 1)
    tx_chunks = await asyncio.gather(*(_one_week(w) for w in weeks))
    raw_trades: list[dict] = []
    for week_txs in tx_chunks:
        for tx in week_txs or []:
            if tx.get("type") == "trade" and tx.get("status") == "complete":
                tx_id = str(tx.get("transaction_id", ""))
                if tx_id in BLACKLISTED_TRANSACTION_IDS:
                    log.info("Skipping blacklisted transaction %s", tx_id)
                    continue
                raw_trades.append(tx)

    drafts = await client.get_drafts(league.league_id)
    draft_picks_by_draft_id: dict[str, list[dict]] = {}
    for d in drafts:
        if d.get("status") == "complete":
            picks = await client.get_draft_picks(d["draft_id"])
            draft_picks_by_draft_id[d["draft_id"]] = picks

    bundle = {
        "users": users,
        "roster_to_user": roster_to_user,
        "raw_trades": raw_trades,
        "drafts": drafts,
        "draft_picks_by_draft_id": draft_picks_by_draft_id,
    }
    if sealed:
        league_cache.write_trade_bundle(league.league_id, bundle)
    return {"league": league, **bundle}
```

- [ ] **Step 4: Thread `league_cache` through `build_trade_history`**

In `build_trade_history`, change the signature and the fetch call. Replace the
signature line and the `_logged_fetch` helper:

```python
async def build_trade_history(
    client,
    current_league_id: str,
    player_names: dict[str, str],
    league_cache=None,
) -> list[ResolvedTrade]:
```

and

```python
    async def _logged_fetch(league):
        log.info("Fetching trades for season %d (%s)", league.season, league.name)
        return await _fetch_league_season_data(client, league, league_cache)
```

Leave the docstring's Args list updated to mention `league_cache` (optional;
duck-typed cache for sealed seasons). Everything else in `build_trade_history`
is unchanged.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_trade_history.py -q --import-mode=importlib`
Expected: PASS (the 3 new tests plus all existing trade-history tests)

- [ ] **Step 6: Commit**

```bash
git add src/sleeper_dynasty/engine/trade_history.py tests/test_trade_history.py
git commit -m "feat: cache the per-league trade bundle for sealed seasons"
```

---

## Task 3: Cache the matchup bundle + de-dup get_players

**Files:**
- Modify: `api/app/services/grader_io.py` (`pull_supporting_data` ~54-151; per-league loop ~117-139)
- Test: `api/tests/test_grader_io.py`

- [ ] **Step 1: Write the failing test**

Append to `api/tests/test_grader_io.py` (if the file doesn't exist, create it with
`from __future__ import annotations` + the imports below):

```python
import pytest
from types import SimpleNamespace

from app.services.grader_io import pull_supporting_data
from app.services.league_raw_cache import LeagueRawCache


class _SealedMatchupClient:
    """Fails on any matchup/roster/user fetch — proves the sealed path is cache-only."""
    async def get_players(self):  # should NOT be called when players= is passed
        raise AssertionError("get_players called despite players= passed")
    async def get_rosters(self, lid): raise AssertionError("network hit (rosters)")
    async def get_users(self, lid): raise AssertionError("network hit (users)")
    @property
    def _client(self):
        raise AssertionError("network hit (matchups)")


@pytest.mark.asyncio
async def test_sealed_league_matchups_served_from_cache(tmp_path, monkeypatch):
    # Stub the global value fetchers so we isolate the per-league path.
    import app.services.grader_io as mod
    async def _no_ktc(): return {}
    async def _no_fc(): return {}
    monkeypatch.setattr(mod, "fetch_ktc_values", _no_ktc)
    monkeypatch.setattr(mod, "fetch_fantasycalc_values", _no_fc)

    cache = LeagueRawCache(cache_dir=tmp_path)
    cache.write_matchup_bundle("L1", {
        "matchups": {("L1", 5, 1): {"starters": ["p1"], "players": ["p1"],
                                    "players_points": {"p1": 20.0},
                                    "team_points": 100.0, "opponent_points": 90.0}},
        "playoff_week_start": 15,
        "roster_to_user": {1: "u_a"},
        "league_name": "Bros",
        "season": 2024,
        "display_names": {"u_a": "Alice"},
    })

    sealed = SimpleNamespace(league_id="L1", season=2024, name="Bros",
                             playoff_week_start=15, status="complete")
    out = await pull_supporting_data(
        _SealedMatchupClient(), [sealed],
        players={}, league_cache=cache,
    )
    assert out["matchups"][("L1", 5, 1)]["players_points"] == {"p1": 20.0}
    assert out["roster_to_user_by_league"]["L1"] == {1: "u_a"}
    assert out["playoff_weeks_by_league"]["L1"] == 15
    assert out["league_season_by_id"]["L1"] == 2024
    assert out["display_names"]["u_a"] == "Alice"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/api" && ../.venv/bin/python -m pytest tests/test_grader_io.py::test_sealed_league_matchups_served_from_cache -q`
Expected: FAIL with `TypeError: pull_supporting_data() got an unexpected keyword argument 'players'`

- [ ] **Step 3: Refactor the per-league loop into a cache-aware helper**

In `api/app/services/grader_io.py`, add this helper above `pull_supporting_data`:

```python
async def _league_matchup_bundle(client, lg, league_cache) -> dict:
    """Build (or load from cache) the per-league matchup bundle.

    Sealed leagues (status == "complete") are loaded from / stored in
    ``league_cache``; the current season is always fetched and never cached.
    """
    sealed = league_cache is not None and getattr(lg, "status", None) == "complete"
    if sealed:
        cached = league_cache.read_matchup_bundle(lg.league_id)
        if cached is not None:
            return cached

    rosters = await client.get_rosters(lg.league_id)
    roster_to_user = {r.roster_id: r.owner_id for r in rosters}
    users = await client.get_users(lg.league_id)
    display_names = {
        uid: (info.get("team_name") or info.get("display_name") or uid)
        for uid, info in users.items()
    }
    raw_per_week: dict[int, list[dict]] = {}
    for week in range(1, 19):
        resp = await client._client.get(f"/league/{lg.league_id}/matchups/{week}")
        resp.raise_for_status()
        raw_per_week[week] = resp.json() or []
    matchups = _assemble_played_matchups(raw_per_week, lg.league_id)

    bundle = {
        "matchups": matchups,
        "playoff_week_start": lg.playoff_week_start,
        "roster_to_user": roster_to_user,
        "league_name": lg.name,
        "season": lg.season,
        "display_names": display_names,
    }
    if sealed:
        league_cache.write_matchup_bundle(lg.league_id, bundle)
    return bundle
```

- [ ] **Step 4: Update `pull_supporting_data` signature, players de-dup, and the loop**

Change the signature:

```python
async def pull_supporting_data(
    client, chain, players=None, league_cache=None,
) -> dict[str, Any]:
```

Replace the `raw_players = await client.get_players()` line (currently ~line 80)
with:

```python
    raw_players = players if players is not None else await client.get_players()
```

Replace the entire per-league loop (currently the `for lg in chain:` block,
~lines 117-139) with:

```python
    for lg in chain:
        b = await _league_matchup_bundle(client, lg, league_cache)
        league_name_by_id[lg.league_id] = b["league_name"]
        playoff_weeks_by_league[lg.league_id] = b["playoff_week_start"]
        league_season_by_id[lg.league_id] = b["season"]
        roster_to_user_by_league[lg.league_id] = b["roster_to_user"]
        for uid, name in b["display_names"].items():
            display_names.setdefault(uid, name)
        matchups.update(b["matchups"])
```

(The `matchups`, `playoff_weeks_by_league`, `roster_to_user_by_league`,
`league_name_by_id`, `league_season_by_id`, `display_names` locals are still
initialized just above the loop, unchanged. The `return {...}` block is
unchanged.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/api" && ../.venv/bin/python -m pytest tests/test_grader_io.py -q`
Expected: PASS. Then run the whole api suite to catch any existing `pull_supporting_data` caller: `../.venv/bin/python -m pytest -q`. The new params default to `None`, so existing callers and tests keep working unchanged.

- [ ] **Step 6: Commit**

```bash
git add api/app/services/grader_io.py api/tests/test_grader_io.py
git commit -m "feat: cache per-league matchup bundle; accept pre-fetched players"
```

---

## Task 4: Wire the cache into `GraderService.run`

**Files:**
- Modify: `api/app/services/grader.py` (`run` ~47-123)
- Test: `api/tests/test_grader_service.py` (update existing fakes for new kwargs)

- [ ] **Step 1: Update the run signature and construction**

In `api/app/services/grader.py`, add imports at top:

```python
from pathlib import Path
from app.services.league_raw_cache import LeagueRawCache
```

Change the `run` signature to add `cache_dir` and `force` (keep the existing
injection params):

```python
    async def run(
        self,
        *,
        client,
        current_league_id: str,
        progress_cb: ProgressCallback,
        cache_dir: Path | None = None,
        force: bool = False,
        _build_trade_history: Callable[..., Awaitable[list]] = build_trade_history,
        _pull_supporting_data: Callable[..., Awaitable[dict]] | None = None,
    ) -> ChainCacheEntry:
```

Right after the `_pull_supporting_data` default is resolved (after the
`if _pull_supporting_data is None:` block), add:

```python
        league_cache = (
            LeagueRawCache(cache_dir=cache_dir, force=force)
            if cache_dir is not None else None
        )
```

- [ ] **Step 2: Thread the cache + players into both fetchers**

Replace the `_build_trade_history(...)` call with:

```python
        resolved = await _build_trade_history(
            client, current_league_id=current_league_id, player_names=player_names,
            league_cache=league_cache,
        )
```

Replace the `_pull_supporting_data(client, chain)` call with:

```python
        supporting = await _pull_supporting_data(
            client, chain, players=raw_players, league_cache=league_cache,
        )
```

- [ ] **Step 3: Update the existing test fakes for the new kwargs**

In `api/tests/test_grader_service.py`, the two fake functions must accept the new
keyword args. Change `fake_build_trade_history` / `fake_build` signatures to end
with `**kwargs`, and `fake_pull_supporting_data` / `fake_pull` likewise:

```python
    async def fake_build_trade_history(client, current_league_id, player_names, **kwargs):
        return []
```
```python
    async def fake_pull_supporting_data(client, chain, **kwargs):
        return {
            "matchups": {},
            "ktc_by_player_id": {},
            "pick_value_table": {},
            "playoff_weeks_by_league": {"L1": 15},
            "roster_to_user_by_league": {"L1": {1: "u_a"}},
            "league_name_by_id": {"L1": "Bros"},
            "league_season_by_id": {"L1": 2026},
            "display_names": {"u_a": "Alice"},
            "warnings": [],
        }
```

Apply the same `**kwargs` change to `fake_build` and `fake_pull` in
`test_grader_service_handles_empty_chain_gracefully`.

- [ ] **Step 4: Run the api suite**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/api" && ../.venv/bin/python -m pytest -q`
Expected: PASS (existing grader-service tests still pass; nothing else broke).

- [ ] **Step 5: Commit**

```bash
git add api/app/services/grader.py api/tests/test_grader_service.py
git commit -m "feat: GraderService.run builds LeagueRawCache and threads it through"
```

---

## Task 5: `?force=1` on the refresh route

**Files:**
- Modify: `api/app/routes/refresh.py`
- Test: `api/tests/test_refresh.py`

- [ ] **Step 1: Write the failing test**

Append to `api/tests/test_refresh.py` (mirror the import/style already in that
file; it likely uses FastAPI's `TestClient`). Add:

```python
def test_refresh_passes_force_to_grader(monkeypatch):
    import app.routes.refresh as refresh_mod

    captured = {}

    class FakeGrader:
        async def run(self, *, client, current_league_id, progress_cb,
                      cache_dir=None, force=False, **kwargs):
            captured["force"] = force
            captured["cache_dir"] = cache_dir
            await progress_cb("done", "ok")
            from app.services.chain_cache import ChainCacheEntry
            return ChainCacheEntry(
                league_id=current_league_id, chain=[], resolved_trades=[],
                grades={}, display_names={}, playoff_weeks_by_league={},
                roster_to_user_by_league={}, league_name_by_id={},
                league_season_by_id={}, cached_at="t", warnings=[],
            )

    monkeypatch.setattr(refresh_mod, "GraderService", FakeGrader)

    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    # Consume the SSE stream so the handler runs to completion.
    with client.stream("GET", "/api/league/L1/refresh?force=1") as r:
        for _ in r.iter_lines():
            pass
    assert captured["force"] is True
    assert captured["cache_dir"] is not None
```

(If `app.main:app` isn't the import path used elsewhere in `test_refresh.py`,
match whatever that file already imports.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/api" && ../.venv/bin/python -m pytest tests/test_refresh.py::test_refresh_passes_force_to_grader -q`
Expected: FAIL (`captured["force"]` is `False` — the route doesn't read the param yet).

- [ ] **Step 3: Add the `force` query param and pass cache_dir + force**

In `api/app/routes/refresh.py`, update the route. Add `Query` import:

```python
from fastapi import APIRouter, Query
```

Change the handler signature and the `svc.run(...)` call:

```python
@router.get("/api/league/{league_id}/refresh")
async def refresh(league_id: str, force: bool = Query(False)) -> EventSourceResponse:
    async def event_stream():
        client = SleeperClient()
        try:
            queue: list[dict] = []

            async def progress_cb(stage: str, message: str, **extra):
                queue.append({"stage": stage, "message": message, **extra})

            svc = GraderService()
            entry = await svc.run(
                client=client, current_league_id=league_id,
                progress_cb=progress_cb,
                cache_dir=_cache_dir(), force=force,
            )
```

(The rest of `event_stream` — draining progress, `ChainCache.write`, done/error
events, `finally: await client.close()` — is unchanged.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/api" && ../.venv/bin/python -m pytest tests/test_refresh.py -q`
Expected: PASS (new test plus existing refresh tests).

- [ ] **Step 5: Commit**

```bash
git add api/app/routes/refresh.py api/tests/test_refresh.py
git commit -m "feat: refresh route accepts ?force=1 to bypass the raw cache"
```

---

## Task 6: Cold == warm equivalence (headline correctness test)

**Files:**
- Test: `api/tests/test_grader_service.py`

Proves the whole point: a warm run served from the raw cache produces identical
grades and resolved trades to a cold run that fetched everything. Uses a fake
client whose fetch methods count calls, with a sealed multi-season chain.

- [ ] **Step 1: Write the test**

Append to `api/tests/test_grader_service.py`:

```python
@pytest.mark.asyncio
async def test_cold_and_warm_runs_produce_identical_output(tmp_path):
    from types import SimpleNamespace
    from app.services.grader import GraderService

    # Two-season sealed chain. Season 2023 trades a player; season 2024 exists.
    leagues = [
        SimpleNamespace(league_id="L2024", season=2024, name="Bros",
                        playoff_week_start=15, total_rosters=2, status="complete"),
        SimpleNamespace(league_id="L2023", season=2023, name="Bros",
                        playoff_week_start=15, total_rosters=2, status="complete"),
    ]

    trade_tx = {
        "transaction_id": "tx1", "type": "trade", "status": "complete",
        "leg": 2, "created": 1690000000000,
        "roster_ids": [1, 2], "adds": {"p1": 2}, "drops": {"p1": 1},
        "draft_picks": [], "waiver_budget": [],
    }

    class CountingClient:
        def __init__(self): self.calls = 0
        async def walk_league_history(self, lid): return leagues
        async def get_players(self):
            self.calls += 1
            return {"p1": {"full_name": "Player One", "position": "RB"}}
        async def get_users(self, lid):
            self.calls += 1; return {"u_a": {"display_name": "Alice"},
                                     "u_b": {"display_name": "Bob"}}
        async def get_rosters(self, lid):
            self.calls += 1
            return [SimpleNamespace(roster_id=1, owner_id="u_a"),
                    SimpleNamespace(roster_id=2, owner_id="u_b")]
        async def get_transactions(self, lid, w):
            self.calls += 1
            return [trade_tx] if (lid == "L2023" and w == 2) else []
        async def get_drafts(self, lid): self.calls += 1; return []
        async def get_draft_picks(self, did): self.calls += 1; return []
        @property
        def _client(self):
            client = self
            class _HTTP:
                async def get(self, url):
                    client.calls += 1
                    class _R:
                        def raise_for_status(self): pass
                        def json(self): return []
                    return _R()
            return _HTTP()

    async def progress_cb(stage, message, **extra): pass

    # Stub global value fetchers to no-ops so only Sleeper calls are counted.
    import app.services.grader_io as gio
    async def _no_ktc(): return {}
    async def _no_fc(): return {}
    orig_ktc, orig_fc = gio.fetch_ktc_values, gio.fetch_fantasycalc_values
    gio.fetch_ktc_values, gio.fetch_fantasycalc_values = _no_ktc, _no_fc
    try:
        cold_client = CountingClient()
        cold = await GraderService().run(
            client=cold_client, current_league_id="L2024",
            progress_cb=progress_cb, cache_dir=tmp_path,
        )
        cold_calls = cold_client.calls

        warm_client = CountingClient()
        warm = await GraderService().run(
            client=warm_client, current_league_id="L2024",
            progress_cb=progress_cb, cache_dir=tmp_path,
        )
        warm_calls = warm_client.calls
    finally:
        gio.fetch_ktc_values, gio.fetch_fantasycalc_values = orig_ktc, orig_fc

    # Identical graded output.
    assert warm.grades == cold.grades
    assert warm.resolved_trades == cold.resolved_trades
    assert warm.roster_to_user_by_league == cold.roster_to_user_by_league
    # Warm hit the network strictly less (sealed seasons served from cache).
    assert warm_calls < cold_calls
```

- [ ] **Step 2: Run the test**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/api" && ../.venv/bin/python -m pytest tests/test_grader_service.py::test_cold_and_warm_runs_produce_identical_output -q`
Expected: PASS. If `warm.grades != cold.grades`, do NOT weaken the assertion —
it means caching changed results; investigate the serialization round-trip
(int/tuple keys) and report.

- [ ] **Step 3: Commit**

```bash
git add api/tests/test_grader_service.py
git commit -m "test: cold and warm refresh produce identical graded output"
```

---

## Task 7: Full verification

- [ ] **Step 1: Engine suite**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && .venv/bin/python -m pytest tests/ -q --import-mode=importlib`
Expected: all PASS.

- [ ] **Step 2: API suite**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/api" && ../.venv/bin/python -m pytest -q`
Expected: all PASS.

- [ ] **Step 3: Commit any verification stragglers**

```bash
git status
# commit anything outstanding with an appropriate message
```

---

## Notes / out of scope (per spec)

- No caching of graded output, KTC, or FantasyCalc (must stay fresh).
- `ChainCache` blob shape, its 24h TTL, and the 409/SSE contract are unchanged.
- CLI is unaffected (`league_cache=None`); it already caches via `FileCache`.
- Per-week in-season matchup deltas (only re-fetch the latest week) are a
  possible future phase, not included here.
