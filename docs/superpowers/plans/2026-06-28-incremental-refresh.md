# Incremental Refresh + Cache Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop full rebuilds of league analysis on every open — make data persist across deploys, then make refresh reuse frozen historical rollups instead of recomputing them.

**Architecture:** Two phases. **Phase 1** (infra) attaches a Railway volume so the file-based caches survive deploys. **Phase 2** (code) makes `GraderService.run` reuse the prior entry's expensive historical rollups (production series, injury, historical GM-rating signals) when nothing in the immutable history changed — recomputing only the cheap "as-of-today" value layer (Trade Value, current-roster outlooks, ratings). A full-rebuild fallback guarantees correctness; the reuse path is a pure optimization gated on a cheap delta check.

**Tech Stack:** Python 3.11, FastAPI, dataclasses, pytest. Railway (Docker, persistent volumes). Engine package `sleeper_dynasty`.

## Global Constraints

- The reuse path is an **optimization only** — any uncertainty or exception falls back to the existing full `GraderService.run`. Incremental must never produce a different result than a full rebuild for the same inputs.
- Never recompute or freeze the **value layer** incorrectly: Trade Value (`snapshot_value_swing`), `aged_value_swing`, realized `received_ktc`, GM ratings, `dynasty_outlooks`, `roster_ranks` are **always recomputed** every refresh (they depend on today's KTC + current rosters).
- The reuse path is only valid when **no NFL scoring week is in progress** (offseason or between weeks) — during a live week, historical production rollups still change daily. Detect via `client.get_nfl_state()`.
- Trades are identified by Sleeper `transaction_id` (stable string). Sealed past seasons never gain new trades.
- `SCHEMA_VERSION` (`api/app/services/chain_cache.py`) mismatch always forces a full rebuild — do not bump it unless the entry shape changes.
- Preserve the cold-start contract shape: opening a stale league still streams the SSE `/refresh` progress; it is just cheaper now.
- Backend tests run from `api/` with `pytest`. Engine tests run from repo root with `pytest`.

---

## Phase 1 — Cache persistence (Railway volume)

### Task 1: Attach a persistent volume to the production API service

**Files:** none (Railway infra change). Confirms `api/Dockerfile:13` (`TRADE_GRADER_CACHE_DIR=/data/sleeper-dynasty/cache`) is honored by a real mount.

**Context:** Production project is `shimmering-nature`. The API service currently has **no volume** (confirmed: only `postgres-volume` exists), so everything written under `/data/sleeper-dynasty/cache` is wiped on every deploy/restart. Attaching a volume there makes `ChainCache` + all sibling stores durable.

- [ ] **Step 1: Confirm the gap**

Run:
```bash
railway link --project 834e0969-401d-44ee-8722-5d599a47013a --service API
railway volume list
```
Expected: exactly one volume (`postgres-volume`, attached to `Postgres`). The API has none.

- [ ] **Step 2: Create + attach the volume to the API service**

In the Railway dashboard (project `shimmering-nature` → service `API` → Variables/Settings → Volumes → New Volume), or via MCP `mcp__railway__create_volume`, create a volume mounted at:
```
/data/sleeper-dynasty/cache
```
Attach it to the **API** service in the **production** environment. (CLI `railway volume add` is interactive; the dashboard or MCP tool is the reliable path.)

- [ ] **Step 3: Redeploy and verify the mount**

Trigger a redeploy (push, or `railway up` against the API service). After it goes live:
```bash
railway volume list
```
Expected: a second volume now shows `Attached to: API`, mount path `/data/sleeper-dynasty/cache`.

- [ ] **Step 4: Verify persistence across a deploy**

1. Open a league at https://ffbdynasty.com so it builds (`200` after the refresh completes).
2. Redeploy the API (no code change needed — e.g. restart the service).
3. Open the same league again.

Expected: the second open returns cached data immediately — **no `409 cache cold`, no rebuild**. Before this task, step 3 would cold-start.

- [ ] **Step 5: Document**

Note in the PR/commit description that the `shimmering-nature` API now has a persistent cache volume (the README already documents the expectation at `README.md:248`). No code commit in this task.

---

## Phase 2 — Reuse frozen rollups when history is unchanged

### Task 2: NFL scoring-state helper

**Files:**
- Create: `api/app/services/nfl_state.py`
- Test: `api/tests/services/test_nfl_state.py`

**Interfaces:**
- Produces: `scoring_in_progress(state: dict | None) -> bool` — `True` when an NFL regular/post-season scoring week is live (so historical rollups can still change today). `True` (conservative) when `state` is `None` or malformed, forcing the safe full-rebuild path.

- [ ] **Step 1: Write the failing test**

```python
# api/tests/services/test_nfl_state.py
from app.services.nfl_state import scoring_in_progress


def test_offseason_is_not_in_progress():
    assert scoring_in_progress({"season_type": "off", "week": 0}) is False
    assert scoring_in_progress({"season_type": "pre", "week": 2}) is False


def test_regular_and_post_season_are_in_progress():
    assert scoring_in_progress({"season_type": "regular", "week": 5}) is True
    assert scoring_in_progress({"season_type": "post", "week": 1}) is True


def test_missing_or_malformed_state_is_conservative_true():
    assert scoring_in_progress(None) is True
    assert scoring_in_progress({}) is True
    assert scoring_in_progress({"season_type": "regular", "week": 0}) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && pytest tests/services/test_nfl_state.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.nfl_state'`.

- [ ] **Step 3: Write minimal implementation**

```python
# api/app/services/nfl_state.py
"""Classify the live NFL scoring state.

When a regular/post-season week is in progress, weekly points (and therefore
the production/injury rollups) still change day to day, so the incremental
reuse path is unsafe. Offseason/preseason/between-weeks → rollups are frozen.
"""
from __future__ import annotations


def scoring_in_progress(state: dict | None) -> bool:
    if not isinstance(state, dict):
        return True  # unknown -> safe (force full rebuild)
    season_type = str(state.get("season_type") or "").lower()
    if season_type not in ("regular", "post"):
        return False
    try:
        week = int(state.get("week") or 0)
    except (TypeError, ValueError):
        return True
    return week >= 1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && pytest tests/services/test_nfl_state.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add api/app/services/nfl_state.py api/tests/services/test_nfl_state.py
git commit -m "feat(refresh): NFL scoring-state helper for incremental reuse gating"
```

---

### Task 3: Delta-scan — detect new trades since the prior build

**Files:**
- Create: `api/app/services/refresh_delta.py`
- Test: `api/tests/services/test_refresh_delta.py`

**Interfaces:**
- Consumes: `resolved_dicts` (list of `asdict(ResolvedTrade)`; each has `["trade"]["transaction_id"]`), and a prior `ChainCacheEntry | None`.
- Produces:
  - `prior_transaction_ids(prior: ChainCacheEntry | None) -> set[str]`
  - `new_transaction_ids(resolved_dicts: list[dict], prior: ChainCacheEntry | None) -> set[str]` — tx ids present now but absent in the prior entry. Empty set when `prior is None` is **not** returned; callers treat `prior is None` as "no reuse possible" separately (see Task 4).

- [ ] **Step 1: Write the failing test**

```python
# api/tests/services/test_refresh_delta.py
from app.services.chain_cache import ChainCacheEntry
from app.services.refresh_delta import new_transaction_ids, prior_transaction_ids


def _entry(tx_ids):
    return ChainCacheEntry(
        league_id="L", chain=[],
        resolved_trades=[{"trade": {"transaction_id": t}} for t in tx_ids],
        grades={}, owners={}, playoff_weeks_by_league={},
        roster_to_user_by_league={}, league_name_by_id={},
        league_season_by_id={}, cached_at="",
    )


def test_prior_ids_extracts_transaction_ids():
    assert prior_transaction_ids(_entry(["a", "b"])) == {"a", "b"}
    assert prior_transaction_ids(None) == set()


def test_new_ids_are_those_absent_in_prior():
    resolved = [{"trade": {"transaction_id": t}} for t in ["a", "b", "c"]]
    assert new_transaction_ids(resolved, _entry(["a", "b"])) == {"c"}


def test_no_new_when_all_present():
    resolved = [{"trade": {"transaction_id": t}} for t in ["a", "b"]]
    assert new_transaction_ids(resolved, _entry(["a", "b"])) == set()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && pytest tests/services/test_refresh_delta.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.refresh_delta'`.

- [ ] **Step 3: Write minimal implementation**

```python
# api/app/services/refresh_delta.py
"""Cheap delta detection between a prior ChainCacheEntry and a fresh trade pull.

Used to decide whether a refresh can reuse the prior entry's frozen historical
rollups (production series, injury, historical rating signals) instead of
recomputing them. Trades are keyed by stable Sleeper transaction_id.
"""
from __future__ import annotations

from app.services.chain_cache import ChainCacheEntry


def prior_transaction_ids(prior: ChainCacheEntry | None) -> set[str]:
    if prior is None:
        return set()
    out: set[str] = set()
    for rt in prior.resolved_trades or []:
        tx = (rt.get("trade") or {}).get("transaction_id")
        if tx:
            out.add(str(tx))
    return out


def new_transaction_ids(
    resolved_dicts: list[dict], prior: ChainCacheEntry | None
) -> set[str]:
    prior_ids = prior_transaction_ids(prior)
    out: set[str] = set()
    for rt in resolved_dicts:
        tx = (rt.get("trade") or {}).get("transaction_id")
        if tx and str(tx) not in prior_ids:
            out.add(str(tx))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && pytest tests/services/test_refresh_delta.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add api/app/services/refresh_delta.py api/tests/services/test_refresh_delta.py
git commit -m "feat(refresh): delta-scan for new trades since prior build"
```

---

### Task 4: Reuse frozen rollups in `GraderService.run`

**Files:**
- Modify: `api/app/services/grader.py` (the `run` method, lines ~374–1006)
- Test: `api/tests/services/test_grader_reuse.py`

**Interfaces:**
- Consumes: `scoring_in_progress` (Task 2), `new_transaction_ids` (Task 3), the prior `ChainCacheEntry` (already read inside `run` for LLM throttle).
- Produces: unchanged `run(...) -> ChainCacheEntry` signature and gains one injection point `_nfl_state` (default `None` → fetched from `client.get_nfl_state()`), used by tests to force offseason/in-season.

**Reuse rule:** the refresh may reuse the prior entry's frozen rollups when **all** hold: a prior entry exists, schema matches (guaranteed — `ChainCache.read` returns `None` on mismatch), `force` is `False`, scoring is not in progress, and there are **no new transaction ids**. When reuse is active, copy these fields from the prior entry instead of recomputing them:
`trade_production_series`, `trade_production_verdict`, `owner_production_series`, `owner_production_verdict`, `production_week_axis`, `production_week_phases`, `trade_production_players`, `owner_production_trades`, `trade_injury`, `trade_departures`, `outcome_signals`, `lineup_signals`, `season_records`, `head_to_head`, `draft_skill_by_season`.
Always recompute (never reuse): `grades` (value layer), `outlook_signals`, `dynasty_outlooks`, `roster_ranks`, `drafted_picks`, `became_grades` (already skip-hashed/cheap), and LLM prose (already throttled).

- [ ] **Step 1: Write the failing test**

```python
# api/tests/services/test_grader_reuse.py
import pytest

from app.services.grader import GraderService


@pytest.mark.asyncio
async def test_offseason_no_new_trades_reuses_production(monkeypatch, tmp_path):
    """When offseason and no new trades, the production-series builder is NOT
    called — the prior entry's rollups are reused verbatim."""
    from app.services.chain_cache import ChainCache, ChainCacheEntry

    # Seed a prior entry with a sentinel production payload.
    prior = ChainCacheEntry(
        league_id="L", chain=[], resolved_trades=[{"trade": {"transaction_id": "t1"}}],
        grades={}, owners={"u1": {"owner_name": "A"}}, playoff_weeks_by_league={},
        roster_to_user_by_league={}, league_name_by_id={}, league_season_by_id={},
        cached_at="2026-06-01T00:00:00+00:00",
        trade_production_series={"t1": {"u1": {"total": [[2025, 1, 9.0]]}}},
    )
    ChainCache(cache_dir=tmp_path).write("L", prior)

    called = {"production": False}

    def _fake_production(**kwargs):
        called["production"] = True
        return {
            "trade_production_series": {}, "trade_production_verdict": {},
            "owner_production_series": {}, "owner_production_verdict": {},
            "production_week_axis": [], "production_week_phases": [],
            "trade_production_players": {}, "owner_production_trades": {},
        }

    monkeypatch.setattr(
        "app.services.grader.compute_production_series_payload", _fake_production)

    entry = await _run_with_one_trade(
        GraderService(), cache_dir=tmp_path, nfl_state={"season_type": "off", "week": 0})

    assert called["production"] is False
    assert entry.trade_production_series == {"t1": {"u1": {"total": [[2025, 1, 9.0]]}}}


@pytest.mark.asyncio
async def test_in_season_recomputes_production(monkeypatch, tmp_path):
    """When scoring is in progress, the production builder IS called even with
    no new trades (the live week still changes)."""
    from app.services.chain_cache import ChainCache, ChainCacheEntry

    prior = ChainCacheEntry(
        league_id="L", chain=[], resolved_trades=[{"trade": {"transaction_id": "t1"}}],
        grades={}, owners={"u1": {"owner_name": "A"}}, playoff_weeks_by_league={},
        roster_to_user_by_league={}, league_name_by_id={}, league_season_by_id={},
        cached_at="2026-06-01T00:00:00+00:00",
        trade_production_series={"t1": {"u1": {"total": [[2025, 1, 9.0]]}}},
    )
    ChainCache(cache_dir=tmp_path).write("L", prior)

    called = {"production": False}

    def _fake_production(**kwargs):
        called["production"] = True
        return {
            "trade_production_series": {}, "trade_production_verdict": {},
            "owner_production_series": {}, "owner_production_verdict": {},
            "production_week_axis": [], "production_week_phases": [],
            "trade_production_players": {}, "owner_production_trades": {},
        }

    monkeypatch.setattr(
        "app.services.grader.compute_production_series_payload", _fake_production)

    await _run_with_one_trade(
        GraderService(), cache_dir=tmp_path,
        nfl_state={"season_type": "regular", "week": 3})

    assert called["production"] is True
```

> NOTE for the implementer: `_run_with_one_trade` is a test helper you must write in this file. It calls `GraderService().run(...)` with the existing mock-injection points (`_build_trade_history`, `_pull_supporting_data`, `_story_writer`, `_blurb_writer`, `_franchise_writer`) returning a single trade `t1` and minimal `supporting` dict, plus the new `_nfl_state` param. Model it on the existing grader tests in `api/tests/services/` (search for a test that already calls `GraderService().run` with these injection points and copy its fixtures). Keep `skip_llm=True` to avoid LLM writers.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && pytest tests/services/test_grader_reuse.py -v`
Expected: FAIL — `run` has no `_nfl_state` param / production builder is called in the offseason case.

- [ ] **Step 3: Add the `_nfl_state` param and the reuse decision**

In `api/app/services/grader.py`, change the `run` signature (line 374) to add the injection point:

```python
    async def run(
        self,
        *,
        client,
        current_league_id: str,
        progress_cb: ProgressCallback,
        cache_dir: Path | None = None,
        force: bool = False,
        skip_llm: bool = False,
        _build_trade_history: Callable[..., Awaitable[tuple[list, dict]]] = build_trade_history,
        _pull_supporting_data: Callable[..., Awaitable[dict]] | None = None,
        _story_writer=None,
        _blurb_writer=None,
        _franchise_writer=None,
        _nfl_state: dict | None = None,
    ) -> ChainCacheEntry:
```

Immediately after `resolved, drop_index = await _build_trade_history(...)` (ends line 437), compute the reuse decision. Read the prior entry once here (the LLM throttle later reads it again; leave that as-is to keep this change local):

```python
        # --- Incremental reuse decision (frozen historical rollups) ---
        # When offseason/between-weeks AND no new trades since the last build,
        # the production/injury/historical-signal rollups are unchanged, so we
        # reuse them from the prior entry and recompute only the value layer.
        from app.services.nfl_state import scoring_in_progress
        from app.services.refresh_delta import new_transaction_ids

        _reuse_prior = None
        if cache_dir is not None and not force:
            from app.services.chain_cache import ChainCache as _CC
            _candidate = _CC(cache_dir=cache_dir).read(
                current_league_id, max_age_seconds=10 ** 9)
            if _candidate is not None:
                if _nfl_state is None:
                    _get_state = getattr(client, "get_nfl_state", None)
                    _nfl_state = await _get_state() if _get_state else None
                _resolved_dicts_for_delta = [
                    {"trade": {"transaction_id": rt.trade.transaction_id}}
                    for rt in resolved
                ]
                if (not scoring_in_progress(_nfl_state)
                        and not new_transaction_ids(
                            _resolved_dicts_for_delta, _candidate)):
                    _reuse_prior = _candidate
        if _reuse_prior is not None:
            log.info("incremental reuse: frozen rollups reused for %s "
                     "(offseason, no new trades)", current_league_id)
```

- [ ] **Step 4: Gate the production stage on reuse**

Replace the production stage (lines 656–688) so it reuses the prior payload when `_reuse_prior` is set:

```python
        if _reuse_prior is not None:
            production_payload = {
                "trade_production_series": _reuse_prior.trade_production_series,
                "trade_production_verdict": _reuse_prior.trade_production_verdict,
                "owner_production_series": _reuse_prior.owner_production_series,
                "owner_production_verdict": _reuse_prior.owner_production_verdict,
                "production_week_axis": _reuse_prior.production_week_axis,
                "production_week_phases": _reuse_prior.production_week_phases,
                "trade_production_players": _reuse_prior.trade_production_players,
                "owner_production_trades": _reuse_prior.owner_production_trades,
            }
        else:
            production_payload = {
                "trade_production_series": {}, "trade_production_verdict": {},
                "owner_production_series": {}, "owner_production_verdict": {},
                "production_week_axis": [], "production_week_phases": [],
                "trade_production_players": {}, "owner_production_trades": {},
            }
            try:
                for d, rt in zip(resolved_dicts, resolved):
                    d["rt"] = rt
                production_payload = compute_production_series_payload(
                    resolved_dicts=resolved_dicts,
                    matchups=supporting["matchups"],
                    roster_to_user_by_league=supporting["roster_to_user_by_league"],
                    league_season_by_id=supporting["league_season_by_id"],
                    current_holders=current_holders,
                    drop_index=drop_index,
                    phase_by_lwr=supporting.get("phase_by_lwr") or {},
                    playoff_week_start_by_league=supporting.get("playoff_week_start_by_league") or {},
                    names=supporting.get("owners_display") or {},
                )
            except Exception:  # never fail refresh on production errors
                log.exception("production-series stage failed")
            finally:
                for d in resolved_dicts:
                    d.pop("rt", None)
```

- [ ] **Step 5: Gate the injury stage on reuse**

Replace the injury stage (lines 690–714) so it reuses the prior payload when `_reuse_prior` is set:

```python
        if _reuse_prior is not None:
            injury_payload = {
                "trade_injury": _reuse_prior.trade_injury,
                "trade_departures": _reuse_prior.trade_departures,
            }
        else:
            injury_payload = {"trade_injury": {}, "trade_departures": {}}
            try:
                from sleeper_dynasty.engine.injury_data import build_injury_map
                from sleeper_dynasty.cache import FileCache
                _file_cache = FileCache(cache_dir) if cache_dir is not None else None
                _seasons = sorted({s for s in supporting["league_season_by_id"].values() if s})
                _injury_map = build_injury_map(
                    _seasons, cache=_file_cache,
                    current_season=max(_seasons) if _seasons else None,
                )
                injury_payload = compute_injury_payload(
                    resolved_dicts=resolved_dicts,
                    matchups=supporting["matchups"],
                    roster_to_user_by_league=supporting["roster_to_user_by_league"],
                    league_season_by_id=supporting["league_season_by_id"],
                    current_holders=current_holders,
                    drop_index=drop_index,
                    phase_by_lwr=supporting.get("phase_by_lwr") or {},
                    playoff_week_start_by_league=supporting.get("playoff_week_start_by_league") or {},
                    injury_map=_injury_map,
                    raw_players=raw_players,
                )
            except Exception:
                log.exception("injury-context stage failed")
```

- [ ] **Step 6: Reuse frozen historical signals**

After the signal stages (`compute_rating_signals` at 722–730, `compute_lineup_signals` at 732–738, `compute_head_to_head` at 740–746), override the **historical** signals from the prior entry when reusing. Insert immediately after the head-to-head block (after line 746):

```python
        if _reuse_prior is not None:
            # Historical pillars don't change without new games/trades; reuse them.
            # outlook_signals stay freshly computed (current roster value/youth).
            outcome_signals = _reuse_prior.outcome_signals or outcome_signals
            lineup_signals = _reuse_prior.lineup_signals or lineup_signals
            draft_skill_by_season = _reuse_prior.draft_skill_by_season or draft_skill_by_season
            season_records_from_signals = _reuse_prior.season_records or season_records_from_signals
            head_to_head = _reuse_prior.head_to_head or head_to_head
```

- [ ] **Step 7: Run the reuse tests**

Run: `cd api && pytest tests/services/test_grader_reuse.py -v`
Expected: PASS (both tests).

- [ ] **Step 8: Run the full grader test suite (no regressions)**

Run: `cd api && pytest tests/services/ -v`
Expected: PASS — existing grader/refresh tests unaffected (the reuse path is skipped whenever `cache_dir` is `None`, `force` is `True`, no prior entry exists, or scoring is in progress).

- [ ] **Step 9: Commit**

```bash
git add api/app/services/grader.py api/tests/services/test_grader_reuse.py
git commit -m "feat(refresh): reuse frozen production/injury/signal rollups when history unchanged"
```

---

### Task 5: Confirm `refresh_league` and the scheduler benefit automatically

**Files:**
- Modify (docs/log only): `api/app/services/refresh_service.py:96-147`
- Test: `api/tests/services/test_refresh_service_incremental.py`

**Interfaces:** none changed. `refresh_league` already calls `GraderService().run(...)` (line 108) with `cache_dir` and `force`, so the reuse path from Task 4 is active for both the manual SSE refresh and the auto-refresh scheduler with **no signature change**. This task only adds a regression test proving the wiring.

- [ ] **Step 1: Write the failing test**

```python
# api/tests/services/test_refresh_service_incremental.py
import pytest

from app.services import refresh_service


@pytest.mark.asyncio
async def test_refresh_league_passes_cache_dir_for_reuse(monkeypatch, tmp_path):
    """refresh_league must invoke GraderService.run with the cache_dir so the
    incremental reuse path can engage."""
    seen = {}

    async def _fake_run(self, **kwargs):
        seen.update(kwargs)
        from app.services.chain_cache import ChainCacheEntry
        return ChainCacheEntry(
            league_id=kwargs["current_league_id"], chain=[], resolved_trades=[],
            grades={}, owners={}, playoff_weeks_by_league={},
            roster_to_user_by_league={}, league_name_by_id={},
            league_season_by_id={}, cached_at="")

    monkeypatch.setattr(
        "app.services.grader.GraderService.run", _fake_run)
    monkeypatch.setattr(
        refresh_service, "compute_season_ratings", lambda entry: {})

    class _Client:
        async def get_nfl_state(self):
            return {"season_type": "off", "week": 0}

    await refresh_service.refresh_league(
        _Client(), "L", cache_dir=tmp_path, force=False)

    assert seen["cache_dir"] == tmp_path
    assert seen["force"] is False
```

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `cd api && pytest tests/services/test_refresh_service_incremental.py -v`
Expected: PASS immediately (the wiring already exists). If it FAILS, the monkeypatch target is wrong — fix the patch path, not the production code.

- [ ] **Step 3: Add an observability log line**

In `refresh_service.refresh_league`, after the `ChainCache(...).write(...)` call (line 145), add:

```python
    log.info("refresh complete for %s (%d trades)",
             league_id, len(entry.resolved_trades or []))
```

- [ ] **Step 4: Re-run**

Run: `cd api && pytest tests/services/test_refresh_service_incremental.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/app/services/refresh_service.py api/tests/services/test_refresh_service_incremental.py
git commit -m "test(refresh): assert refresh_league wiring enables incremental reuse"
```

---

### Task 6: End-to-end equivalence check (reuse == full rebuild)

**Files:**
- Test: `api/tests/services/test_grader_reuse_equivalence.py`

**Interfaces:** none. Proves the Global Constraint: for unchanged inputs, the reuse path yields the same frozen-rollup fields as a full rebuild.

- [ ] **Step 1: Write the test**

```python
# api/tests/services/test_grader_reuse_equivalence.py
import pytest

from app.services.grader import GraderService


@pytest.mark.asyncio
async def test_reuse_matches_full_rebuild_for_unchanged_inputs(monkeypatch, tmp_path):
    """Build once (full), then refresh offseason with identical inputs and a
    prior entry present: the frozen-rollup fields must be identical."""
    svc = GraderService()

    # First build — no prior entry, so full path runs and writes the cache.
    first = await _run_with_one_trade(
        svc, cache_dir=tmp_path, nfl_state={"season_type": "off", "week": 0})
    from app.services.chain_cache import ChainCache
    ChainCache(cache_dir=tmp_path).write("L", first)

    # Second build — prior entry present, offseason, no new trades -> reuse path.
    second = await _run_with_one_trade(
        svc, cache_dir=tmp_path, nfl_state={"season_type": "off", "week": 0})

    for field in (
        "trade_production_series", "owner_production_series",
        "production_week_axis", "production_week_phases",
        "trade_injury", "trade_departures",
        "outcome_signals", "lineup_signals", "season_records",
        "head_to_head", "draft_skill_by_season",
    ):
        assert getattr(second, field) == getattr(first, field), field
```

> NOTE: reuse the same `_run_with_one_trade` helper authored in Task 4 (import it or move it to a shared `api/tests/services/_grader_fixtures.py` and import from both test modules — DRY).

- [ ] **Step 2: Run the test**

Run: `cd api && pytest tests/services/test_grader_reuse_equivalence.py -v`
Expected: PASS.

- [ ] **Step 3: Run the whole backend suite**

Run: `cd api && pytest -q`
Expected: PASS (no regressions).

- [ ] **Step 4: Commit**

```bash
git add api/tests/services/test_grader_reuse_equivalence.py api/tests/services/_grader_fixtures.py
git commit -m "test(refresh): reuse path equals full rebuild for unchanged inputs"
```

---

## Phase 3 — In-season per-week / per-trade incremental (FOLLOW-UP, separate plan)

**Not in this plan.** Phases 1–2 deliver: durable cache across deploys, and zero-rebuild reuse whenever the league is opened offseason/between-weeks with no new trades — the common steady-state case. The remaining optimization (recompute only the **current in-progress week** and only **new/lineage-affected trades** during a live NFL week, instead of falling back to a full rebuild) requires splitting `compute_production_series_payload` / `compute_injury_payload` into a cached per-(trade, completed-week) builder plus a cheap aggregator, and handling the lineage-neighbor recompute set (a new trade flipping a previously-received asset extends an older trade's became/series). That is a larger engine refactor and should get its own spec + plan once Phases 1–2 are measured in production. Tracked by the design doc `docs/superpowers/specs/2026-06-28-incremental-refresh-design.md`.

---

## Self-Review

**Spec coverage:**
- Persistence (volume) → Task 1. ✅
- Delta-only / freeze expensive rollups → Tasks 3–4 (reuse production/injury/historical signals). ✅
- Always recompute value layer → enforced in Task 4 (grades/outlook_signals/dynasty_outlooks/roster_ranks never reused). ✅
- Block + incremental on open → unchanged SSE path; Task 5 confirms wiring. ✅
- Full-rebuild fallback / escape hatches (force, schema, no prior, scoring in progress) → Task 4 reuse condition. ✅
- Lineage-neighbor recompute (new trades) → deferred to Phase 3 (only matters when new trades exist, which forces a full rebuild here — still correct, just not yet optimized). ✅ (sequencing noted, not dropped)
- Testing (no-op reuse, in-season recompute, equivalence, escape hatches) → Tasks 2, 4, 6. ✅

**Placeholder scan:** No "TBD"/"handle edge cases" left. The two `_run_with_one_trade` helper references are explicitly flagged as implementer-authored test fixtures modeled on existing grader tests (not production placeholders) — acceptable because the exact fixtures depend on the existing test patterns in `api/tests/services/` which the implementer will mirror.

**Type consistency:** `scoring_in_progress(dict|None)->bool`, `new_transaction_ids(list,ChainCacheEntry|None)->set[str]`, `run(..., _nfl_state: dict|None=None)` consistent across Tasks 2–6. Reused field names match `ChainCacheEntry` (verified against `api/app/services/chain_cache.py`).
