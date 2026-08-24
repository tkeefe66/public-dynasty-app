# Bracket-Aware Playoff Grading & Production Phase Taxonomy — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make "Playoff Points" count only production from real, title-contending playoff-bracket games, and partition started production into Regular Season / Playoff / Toilet Bowl across the engine, API, web, and became-grade.

**Architecture:** A new pure engine module `playoff_phase.py` interprets Sleeper winners/losers brackets into a `(week, roster) → phase` map. The grader consumes that map instead of a calendar threshold. A consistent `started_<phase>` field taxonomy replaces the old single all-weeks "started" field. GM Rating gains a Toilet Bowl term and reweights. A cache-schema bump forces a one-time re-grade.

**Tech Stack:** Python 3.11 (engine + FastAPI), pytest/pytest-asyncio, Next.js 14 + Vitest (web). Sleeper public API.

**Spec:** `docs/superpowers/specs/2026-06-08-playoff-phase-grading-design.md`

---

## File Structure

**New files:**
- `src/sleeper_dynasty/engine/playoff_phase.py` — pure bracket → phase classifier.
- `tests/test_playoff_phase.py` — golden + synthetic classifier tests.
- `scripts/audit_playoff_phases.py` — human-readable validation report.

**Modified (engine/CLI):** `engine/trade_grader.py`, `engine/gm_rating.py`, `engine/regrade.py`, `models/trade.py`, `api/sleeper.py` (client), `output/google_sheets.py`, `engine/trade_story.py`.

**Modified (API):** `app/services/grader_io.py`, `app/services/grader.py`, `app/services/chain_cache.py`, `app/services/aggregations.py`, `app/services/leaderboard.py`, `app/services/trade_view.py`, `app/models/trade.py`, `app/models/leaderboard.py`.

**Modified (web):** `web/lib/types.ts`, `web/components/Leaderboard.tsx`, `web/components/TradeBecame.tsx`, trade detail page, `web/lib/og-card-data.ts`.

**Modified (docs):** `README.md`, `CLAUDE.md`.

**Naming convention (used throughout):**
- Per-trade swing fields on `TradeGrade`: `hindsight_started_regular_swing`, `hindsight_started_playoff_swing` (kept), `hindsight_started_toilet_swing`.
- Per-owner fields: `net_production_started_regular`, `net_production_started_playoff` (kept), `net_production_started_toilet`.
- The old `hindsight_started_swing` / `net_production_started` (all-weeks started) are **removed**.
- GM-rating metric keys: `regular`, `playoff`, `value`, `toilet`.
- Labels: **Regular Season Points**, **Playoff Points**, **Toilet Bowl Points**.

---

## Phase 1 — Pure phase classifier (`playoff_phase.py`)

This is the heart. No I/O; exhaustively unit-tested with the real 2025 brackets.

### Task 1: Round → week helper

**Files:**
- Create: `src/sleeper_dynasty/engine/playoff_phase.py`
- Test: `tests/test_playoff_phase.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_playoff_phase.py
from sleeper_dynasty.engine.playoff_phase import weeks_for_round


def test_weeks_for_round_type0_one_week_each():
    assert weeks_for_round(1, 15, 0) == [15]
    assert weeks_for_round(3, 15, 0) == [17]


def test_weeks_for_round_type2_two_weeks_each():
    assert weeks_for_round(1, 15, 2) == [15, 16]
    assert weeks_for_round(2, 15, 2) == [17, 18]


def test_weeks_for_round_type1_two_week_final_only():
    # Final round (we pass total_rounds) spans two weeks; earlier rounds one.
    assert weeks_for_round(1, 15, 1, total_rounds=3) == [15]
    assert weeks_for_round(3, 15, 1, total_rounds=3) == [17, 18]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_playoff_phase.py -v`
Expected: FAIL — `ModuleNotFoundError` / `weeks_for_round` undefined.

- [ ] **Step 3: Write minimal implementation**

```python
# src/sleeper_dynasty/engine/playoff_phase.py
"""Interpret Sleeper winners/losers brackets into a per-week phase map.

Pure + fully unit-testable: no I/O, no Sleeper types — raw bracket dicts in,
``(week, roster_id) -> phase`` out. "phase" is "playoff" (live title-path
winners game) or "toilet" (any losers-bracket game). Anything absent is a
dropped week (bye, winners placement game) or regular season (handled by the
caller via week < playoff_week_start).
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def weeks_for_round(
    r: int,
    playoff_week_start: int,
    playoff_round_type: int,
    total_rounds: int | None = None,
) -> list[int]:
    """NFL week(s) a bracket round occupies.

    round_type 0: one week per round.
    round_type 2: two weeks per round.
    round_type 1: one week per round, except the final round spans two weeks.
    """
    if playoff_round_type == 2:
        first = playoff_week_start + 2 * (r - 1)
        return [first, first + 1]
    if playoff_round_type == 1 and total_rounds is not None and r == total_rounds:
        first = playoff_week_start + (r - 1)
        return [first, first + 1]
    return [playoff_week_start + (r - 1)]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_playoff_phase.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/playoff_phase.py tests/test_playoff_phase.py
git commit -m "feat(engine): playoff_phase.weeks_for_round (round -> NFL week mapping)"
```

### Task 2: `classify_playoff_phases` — title-path + toilet sets

**Files:**
- Modify: `src/sleeper_dynasty/engine/playoff_phase.py`
- Test: `tests/test_playoff_phase.py`

- [ ] **Step 1: Write the failing test (golden, from the real 2025 brackets)**

```python
# tests/test_playoff_phase.py  (append)
from sleeper_dynasty.engine.playoff_phase import classify_playoff_phases

# Real 2025 winners_bracket (league 1191785397019561984), round_type 0, pw_start 15.
WINNERS_2025 = [
    {"m": 1, "r": 1, "t1": 6, "t2": 12, "w": 6, "l": 12},
    {"m": 2, "r": 1, "t1": 2, "t2": 5, "w": 5, "l": 2},
    {"m": 3, "r": 2, "t1": 1, "t2": 6, "w": 1, "l": 6},
    {"m": 4, "r": 2, "t1": 10, "t2": 5, "w": 10, "l": 5},
    {"m": 5, "p": 5, "r": 2, "t1": 12, "t2": 2, "w": 12, "l": 2},
    {"m": 6, "p": 1, "r": 3, "t1": 1, "t2": 10, "w": 1, "l": 10},
    {"m": 7, "p": 3, "r": 3, "t1": 6, "t2": 5, "w": 5, "l": 6},
]
LOSERS_2025 = [
    {"m": 1, "r": 1, "t1": 9, "t2": 8, "w": 9, "l": 8},
    {"m": 2, "r": 1, "t1": 4, "t2": 3, "w": 3, "l": 4},
    {"m": 3, "r": 2, "t1": 11, "t2": 9, "w": 11, "l": 9},
    {"m": 4, "r": 2, "t1": 7, "t2": 3, "w": 7, "l": 3},
    {"m": 5, "p": 5, "r": 2, "t1": 8, "t2": 4, "w": 4, "l": 8},
    {"m": 6, "p": 1, "r": 3, "t1": 11, "t2": 7, "w": 7, "l": 11},
    {"m": 7, "p": 3, "r": 3, "t1": 9, "t2": 3, "w": 9, "l": 3},
]


def test_classify_real_2025():
    phases = classify_playoff_phases(WINNERS_2025, LOSERS_2025, 15, 0)

    # Quarterfinals wk15: title-path, both teams.
    assert phases[(15, 6)] == "playoff"
    assert phases[(15, 12)] == "playoff"
    assert phases[(15, 2)] == "playoff"
    assert phases[(15, 5)] == "playoff"

    # Byes wk15: rosters 1 and 10 played no wk15 game -> absent.
    assert (15, 1) not in phases
    assert (15, 10) not in phases

    # Semifinals wk16: title-path.
    assert phases[(16, 1)] == "playoff"
    assert phases[(16, 10)] == "playoff"

    # 5th-place game wk16 (p=5): NOT title-path -> rosters 12, 2 absent at wk16.
    assert (16, 12) not in phases
    assert (16, 2) not in phases

    # Championship wk17 (p=1): title-path.
    assert phases[(17, 1)] == "playoff"
    assert phases[(17, 10)] == "playoff"

    # 3rd-place game wk17 (p=3): NOT title-path -> rosters 6, 5 absent at wk17.
    assert (17, 6) not in phases
    assert (17, 5) not in phases

    # Losers bracket -> toilet, every game (incl. its placement games).
    assert phases[(15, 9)] == "toilet"
    assert phases[(15, 8)] == "toilet"
    assert phases[(16, 11)] == "toilet"
    assert phases[(17, 7)] == "toilet"


def test_classify_skips_unresolved_and_empty():
    # Live bracket with a not-yet-seeded slot (null roster) is skipped, no crash.
    wb = [{"m": 1, "r": 1, "t1": 3, "t2": None}]
    phases = classify_playoff_phases(wb, [], 15, 0)
    assert phases == {(15, 3): "playoff"}
    assert classify_playoff_phases([], [], 15, 0) == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_playoff_phase.py::test_classify_real_2025 -v`
Expected: FAIL — `classify_playoff_phases` undefined.

- [ ] **Step 3: Write minimal implementation**

```python
# src/sleeper_dynasty/engine/playoff_phase.py  (append)

def _is_title_path(entry: dict) -> bool:
    """A winners-bracket game on the path to the championship: no placement
    marker, or the championship itself (p == 1). Placement games (p >= 3)
    are not title-path."""
    p = entry.get("p")
    return p is None or p == 1


def _rosters(entry: dict) -> list[int]:
    out = []
    for k in ("t1", "t2"):
        v = entry.get(k)
        if isinstance(v, int):
            out.append(v)
    return out


def classify_playoff_phases(
    winners_bracket: list[dict],
    losers_bracket: list[dict],
    playoff_week_start: int,
    playoff_round_type: int,
) -> dict[tuple[int, int], str]:
    """(week, roster_id) -> "playoff" | "toilet". See module docstring."""
    out: dict[tuple[int, int], str] = {}

    w_rounds = [e.get("r") for e in winners_bracket if isinstance(e.get("r"), int)]
    total_w = max(w_rounds) if w_rounds else 0
    for e in winners_bracket:
        if not _is_title_path(e):
            continue
        r = e.get("r")
        if not isinstance(r, int):
            continue
        for wk in weeks_for_round(r, playoff_week_start, playoff_round_type, total_w):
            for rid in _rosters(e):
                out[(wk, rid)] = "playoff"

    l_rounds = [e.get("r") for e in losers_bracket if isinstance(e.get("r"), int)]
    total_l = max(l_rounds) if l_rounds else 0
    for e in losers_bracket:
        r = e.get("r")
        if not isinstance(r, int):
            continue
        for wk in weeks_for_round(r, playoff_week_start, playoff_round_type, total_l):
            for rid in _rosters(e):
                # Winners (playoff) wins any conflict; rosters never appear in both.
                out.setdefault((wk, rid), "toilet")

    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_playoff_phase.py -v`
Expected: PASS (all). Confirms byes drop, placement games drop, losers → toilet.

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/playoff_phase.py tests/test_playoff_phase.py
git commit -m "feat(engine): classify_playoff_phases (title-path winners + losers->toilet)"
```

---

## Phase 2 — Sleeper client bracket fetch

### Task 3: `get_winners_bracket` / `get_losers_bracket`

**Files:**
- Modify: `src/sleeper_dynasty/api/sleeper.py` (add two methods near `get_matchups`, ~line 91)
- Test: `tests/test_sleeper_api.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sleeper_api.py  (append; follow the existing respx/httpx mock style in this file)
import pytest


@pytest.mark.asyncio
async def test_get_winners_bracket(respx_mock):
    from sleeper_dynasty.api.sleeper import SleeperClient
    respx_mock.get("https://api.sleeper.app/v1/league/L1/winners_bracket").respond(
        json=[{"m": 1, "r": 1, "t1": 6, "t2": 12, "w": 6, "l": 12}]
    )
    client = SleeperClient()
    out = await client.get_winners_bracket("L1")
    await client.close()
    assert out == [{"m": 1, "r": 1, "t1": 6, "t2": 12, "w": 6, "l": 12}]


@pytest.mark.asyncio
async def test_get_losers_bracket_error_returns_empty(respx_mock):
    from sleeper_dynasty.api.sleeper import SleeperClient
    respx_mock.get("https://api.sleeper.app/v1/league/L1/losers_bracket").respond(500)
    client = SleeperClient()
    out = await client.get_losers_bracket("L1")
    await client.close()
    assert out == []
```

> If `tests/test_sleeper_api.py` uses a different mocking helper than `respx_mock`, match that file's existing pattern instead — read the top of the file first.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sleeper_api.py -k bracket -v`
Expected: FAIL — methods undefined.

- [ ] **Step 3: Write minimal implementation**

```python
# src/sleeper_dynasty/api/sleeper.py  (add after get_matchups)
    async def get_winners_bracket(self, league_id: str) -> list[dict]:
        """Raw Sleeper winners (championship) bracket. [] on any error."""
        return await self._get_bracket(league_id, "winners_bracket")

    async def get_losers_bracket(self, league_id: str) -> list[dict]:
        """Raw Sleeper losers (toilet bowl) bracket. [] on any error."""
        return await self._get_bracket(league_id, "losers_bracket")

    async def _get_bracket(self, league_id: str, which: str) -> list[dict]:
        try:
            resp = await self._client.get(f"/league/{league_id}/{which}")
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else []
        except Exception as e:  # best-effort; missing-bracket guard downstream
            log.warning("%s fetch failed for %s: %s", which, league_id, e)
            return []
```

> Confirm `log` exists at module top in `sleeper.py`; if not, add `import logging` + `log = logging.getLogger(__name__)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_sleeper_api.py -k bracket -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/api/sleeper.py tests/test_sleeper_api.py
git commit -m "feat(api-client): get_winners_bracket / get_losers_bracket (best-effort)"
```

---

## Phase 3 — Phase-aware grader + the taxonomy rename

This phase changes `TradeGrade`, `OwnerTradeRecord`, the grader, and **every engine/CLI consumer** of the old `started` field in one cohesive set of commits so the engine suite stays green.

### Task 4: Phase-aware production in `grade_hindsight_production`

**Files:**
- Modify: `src/sleeper_dynasty/engine/trade_grader.py` (`grade_hindsight_production`, ~120–207)
- Test: `tests/test_trade_grader.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_trade_grader.py  (append)
def test_hindsight_phase_gate_counts_only_listed_weeks(_trade_factory=None):
    """A started week counts toward 'playoff' only when phase_by_lwr marks it."""
    from sleeper_dynasty.engine.trade_grader import grade_hindsight_production
    # Build a minimal ResolvedTrade where uid 'A' received player 'p1'.
    # (Reuse this file's existing helper for constructing ResolvedTrade +
    #  matchups; mirror an existing started-production test.)
    rt, matchups, r2u = _phase_fixture()  # see helper below / existing fixtures
    # p1 started for A's roster in wk15 (playoff) and wk16 (not listed).
    phase = {("L1", 15, 1): "playoff"}
    swing = grade_hindsight_production(
        rt, matchups, r2u, starters_only=True,
        phase_filter="playoff", phase_by_lwr=phase,
    )
    assert swing["A"] == 10.0  # only wk15's 10 pts; wk16 excluded
```

> Read the existing started-production tests in `tests/test_trade_grader.py` and reuse their ResolvedTrade/matchup construction helper for `_phase_fixture()` rather than inventing a new one. The matchup entry shape is `{"starters": [...], "players": [...], "players_points": {pid: pts}}` keyed `(league_id, week, roster_id)`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_trade_grader.py -k phase_gate -v`
Expected: FAIL — `grade_hindsight_production` has no `phase_filter`/`phase_by_lwr`.

- [ ] **Step 3: Implement — replace the `playoff_only` gate with phase lookup**

In `grade_hindsight_production`, replace the signature params `playoff_only` / `playoff_weeks_by_league` with `phase_filter` / `phase_by_lwr`, and rewrite `_counts`:

```python
def grade_hindsight_production(
    rt: ResolvedTrade,
    matchups: dict[tuple[str, int, int], dict],
    roster_to_user_by_league: dict[str, dict[int, str]],
    league_season_by_id: dict[str, int] | None = None,
    starters_only: bool = False,
    phase_filter: str | None = None,            # "playoff" | "toilet" | "regular"
    phase_by_lwr: dict[tuple[str, int, int], str] | None = None,
    playoff_week_start_by_league: dict[str, int] | None = None,
) -> dict[str, float]:
    league_season_by_id = league_season_by_id or {}
    phase_by_lwr = phase_by_lwr or {}
    playoff_week_start_by_league = playoff_week_start_by_league or {}
    roster_field = "starters" if starters_only else "players"

    def _phase(lg: str, wk: int, rid: int) -> str:
        """Phase of a (league, week, roster) game for the started buckets."""
        ps = playoff_week_start_by_league.get(lg, 15)
        if wk < ps:
            return "regular"
        return phase_by_lwr.get((lg, wk, rid), "dropped")
```

Then in `_received_points`, after resolving `owner`/membership, gate on phase when a filter is set. **Important:** the phase depends on `rid`, so it must be checked per-`(lg, wk, rid)`:

```python
    def _received_points(pid: str, target_uid: str) -> float:
        total = 0.0
        for (lg, wk, rid), entry in matchups.items():
            if not _is_post_trade(lg, wk, rt, league_season_by_id):
                continue
            if phase_filter and _phase(lg, wk, rid) != phase_filter:
                continue
            if roster_to_user_by_league.get(lg, {}).get(rid) != target_uid:
                continue
            if pid not in (entry.get(roster_field) or []):
                continue
            total += float((entry.get("players_points") or {}).get(pid, 0.0) or 0.0)
        return total

    def _phantom_points(pid: str) -> float:
        total = 0.0
        for (lg, wk, rid), entry in matchups.items():
            if not _is_post_trade(lg, wk, rt, league_season_by_id):
                continue
            if phase_filter and _phase(lg, wk, rid) != phase_filter:
                continue
            if pid not in (entry.get(roster_field) or []):
                continue
            total += float((entry.get("players_points") or {}).get(pid, 0.0) or 0.0)
        return total
```

The `_counts` helper and its `playoff_only` references are removed; `_is_post_trade` is still called directly (it was previously inside `_counts`).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_trade_grader.py -k phase_gate -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/trade_grader.py tests/test_trade_grader.py
git commit -m "feat(engine): phase-gated hindsight production (playoff/toilet/regular by (lg,wk,roster))"
```

### Task 5: Taxonomy on `TradeGrade` / `OwnerTradeRecord` + `grade_trade` wiring

**Files:**
- Modify: `src/sleeper_dynasty/models/trade.py:112-139`
- Modify: `src/sleeper_dynasty/engine/trade_grader.py` (`grade_trade` 210-245, `aggregate_owner_records` 248-278)
- Modify: `src/sleeper_dynasty/output/google_sheets.py:269-271`
- Modify: `src/sleeper_dynasty/engine/trade_story.py:212,217`
- Test: `tests/test_trade_grader.py`, existing `tests/test_trade_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_trade_grader.py  (append)
def test_grade_trade_emits_three_started_phases():
    from sleeper_dynasty.engine.trade_grader import grade_trade
    g = grade_trade(*_grade_trade_args_with_phase())  # reuse existing grade_trade fixture
    assert set(vars(g)) >= {
        "hindsight_started_regular_swing",
        "hindsight_started_playoff_swing",
        "hindsight_started_toilet_swing",
    }
    assert not hasattr(g, "hindsight_started_swing")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_trade_grader.py -k three_started_phases -v`
Expected: FAIL — field still named `hindsight_started_swing`.

- [ ] **Step 3: Implement the model + wiring changes**

`models/trade.py` — `TradeGrade`:

```python
    snapshot_value_swing: dict[str, float] = field(default_factory=dict)
    hindsight_production_swing: dict[str, float] = field(default_factory=dict)
    hindsight_started_regular_swing: dict[str, float] = field(default_factory=dict)
    hindsight_started_playoff_swing: dict[str, float] = field(default_factory=dict)
    hindsight_started_toilet_swing: dict[str, float] = field(default_factory=dict)
```

`models/trade.py` — `OwnerTradeRecord`:

```python
    net_production_started_regular: float = 0.0
    net_production_started_playoff: float = 0.0
    net_production_started_toilet: float = 0.0
```

`trade_grader.py` — `grade_trade` now takes `phase_by_lwr` + `playoff_week_start_by_league` (replacing `playoff_weeks_by_league`) and computes three started buckets:

```python
def grade_trade(
    rt, ktc_values, matchups, roster_to_user_by_league,
    playoff_week_start_by_league: dict[str, int],
    phase_by_lwr: dict[tuple[str, int, int], str] | None = None,
    league_season_by_id=None, fmt="superflex", pick_values=None,
) -> TradeGrade:
    league_season_by_id = league_season_by_id or {}
    common = dict(
        matchups=matchups, roster_to_user_by_league=roster_to_user_by_league,
        league_season_by_id=league_season_by_id,
    )
    snapshot = grade_snapshot_value(rt, ktc_values, fmt=fmt, pick_values=pick_values)
    total = grade_hindsight_production(rt, **common)
    started_common = dict(
        starters_only=True, phase_by_lwr=phase_by_lwr or {},
        playoff_week_start_by_league=playoff_week_start_by_league, **common,
    )
    return TradeGrade(
        trade_id=rt.trade.transaction_id,
        snapshot_value_swing=snapshot,
        hindsight_production_swing=total,
        hindsight_started_regular_swing=grade_hindsight_production(rt, phase_filter="regular", **started_common),
        hindsight_started_playoff_swing=grade_hindsight_production(rt, phase_filter="playoff", **started_common),
        hindsight_started_toilet_swing=grade_hindsight_production(rt, phase_filter="toilet", **started_common),
    )
```

`trade_grader.py` — `aggregate_owner_records` accumulation block (replace lines 268-271):

```python
            rec.net_production_started_regular += g.hindsight_started_regular_swing.get(uid, 0.0)
            rec.net_production_started_playoff += g.hindsight_started_playoff_swing.get(uid, 0.0)
            rec.net_production_started_toilet += g.hindsight_started_toilet_swing.get(uid, 0.0)
```

`output/google_sheets.py:269-271` — update field names + add a Toilet column value:

```python
                    points_started = f"{grade.hindsight_started_regular_swing.get(uid, 0):+.1f}"
                    points_playoff = f"{grade.hindsight_started_playoff_swing.get(uid, 0):+.1f}"
                    points_toilet = f"{grade.hindsight_started_toilet_swing.get(uid, 0):+.1f}"
```

> Check the surrounding header/row-append code in `google_sheets.py` and add a "Toilet Bowl Points" column header + the `points_toilet` cell so the sheet stays column-aligned. Read ~20 lines around 269 first.

`engine/trade_story.py:212,217` — these read grade dicts by key; rename:

```python
            (grade.get("hindsight_started_regular_swing") or {}).get(winner, 0.0)
            ...
            (grade.get("hindsight_started_playoff_swing") or {}).get(winner, 0.0)
```

- [ ] **Step 4: Run the engine suite**

Run: `pytest tests/ -q`
Expected: PASS. Fix any test that referenced `hindsight_started_swing` / `net_production_started` by renaming to `_regular`. Search: `grep -rn "hindsight_started_swing\|net_production_started\b" tests/ src/`.

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty tests/
git commit -m "feat(engine): started production taxonomy regular/playoff/toilet; rename started->started_regular"
```

---

## Phase 4 — GM Rating reweight

### Task 6: Toilet term + new weights in `gm_rating.py`

**Files:**
- Modify: `src/sleeper_dynasty/engine/gm_rating.py:11`
- Test: `tests/test_gm_rating.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gm_rating.py  (append)
def test_weights_and_breakdown_keys():
    from sleeper_dynasty.engine.gm_rating import compute_gm_ratings, WEIGHTS
    assert WEIGHTS == {"playoff": 0.40, "regular": 0.30, "value": 0.22, "toilet": 0.08}
    out = compute_gm_ratings({
        "A": {"playoff": 100, "regular": 50, "value": 800, "toilet": 0},
        "B": {"playoff": 0, "regular": 0, "value": 0, "toilet": 200},
    })
    assert set(out["A"]["breakdown"]) == {"playoff", "regular", "value", "toilet"}
    assert out["A"]["rating"] > out["B"]["rating"]  # A: real production > B: toilet only
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gm_rating.py -k weights_and_breakdown -v`
Expected: FAIL — `WEIGHTS` still 3 keys with `started`.

- [ ] **Step 3: Implement**

```python
# src/sleeper_dynasty/engine/gm_rating.py:11
WEIGHTS = {"playoff": 0.40, "regular": 0.30, "value": 0.22, "toilet": 0.08}
```

No other change — `compute_gm_ratings` iterates `WEIGHTS`, so the breakdown keys and z-score blend follow automatically. Update the module docstring (lines 1-6) to list the four contributing metrics.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_gm_rating.py -v`
Expected: PASS. Update any existing gm_rating test that passed `{"playoff","started","value"}` keys to the new `{"playoff","regular","value","toilet"}` shape.

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/gm_rating.py tests/test_gm_rating.py
git commit -m "feat(engine): GM Rating adds Toilet Bowl term; weights P.40/R.30/V.22/TB.08"
```

---

## Phase 5 — Backend wiring (grader_io, cache version, grader)

### Task 7: Fetch brackets + build `phase_by_lwr` in the matchup bundle

**Files:**
- Modify: `api/app/services/grader_io.py` (`_league_matchup_bundle` ~25-93; supporting-data assembly ~166-194)
- Modify: `api/app/services/grader.py` (calls to `grade_trade`, ~86-121, 198, 260)
- Test: `api/tests/test_grader_io.py` (or the nearest existing grader_io/supporting test)

- [ ] **Step 1: Write the failing test**

```python
# api/tests/test_grader_io.py  (append; match existing async + fake-client style)
@pytest.mark.asyncio
async def test_bundle_includes_phase_map(fake_client_with_brackets):
    from app.services.grader_io import _league_matchup_bundle
    b = await _league_matchup_bundle(fake_client_with_brackets, _league_2025(), None)
    # roster 6 played the wk15 QF (title-path) in 2025.
    assert b["phase_by_lwr"][(_LID_2025, 15, 6)] == "playoff"
    # a losers-bracket roster -> toilet
    assert b["phase_by_lwr"][(_LID_2025, 15, 9)] == "toilet"
```

> Build `fake_client_with_brackets` by extending the existing grader_io test fake to also answer `get_winners_bracket`/`get_losers_bracket` with `WINNERS_2025`/`LOSERS_2025` from the spec. Reuse the bracket fixtures from `tests/test_playoff_phase.py` (import or duplicate the literals).

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest api/tests/test_grader_io.py -k phase_map -v`
Expected: FAIL — bundle has no `phase_by_lwr`.

- [ ] **Step 3: Implement**

In `_league_matchup_bundle`, after fetching matchups, fetch both brackets and classify:

```python
    from sleeper_dynasty.engine.playoff_phase import classify_playoff_phases
    winners = await client.get_winners_bracket(lg.league_id)
    losers = await client.get_losers_bracket(lg.league_id)
    phase_local = classify_playoff_phases(
        winners, losers, lg.playoff_week_start, getattr(lg, "playoff_round_type", 0),
    )
    phase_by_lwr = {(lg.league_id, wk, rid): ph for (wk, rid), ph in phase_local.items()}
```

Add `winners`, `losers`, and `phase_by_lwr` to the returned bundle dict, and include them in the sealed cached bundle (`write_matchup_bundle` / `read_matchup_bundle`) so historical seasons don't refetch. (JSON-serialize `phase_by_lwr` as a list of `[wk, rid, phase]` rows; the keys aren't JSON-native.)

In the supporting-data loop (~174-194), accumulate a chain-wide `phase_by_lwr` and `playoff_week_start_by_league`, and add both to the returned supporting dict (replacing `playoff_weeks_by_league` for grading; you may keep `playoff_weeks_by_league` if other consumers still need it).

> `League` needs a `playoff_round_type` field. Add it to `models/league.py` (default 0) and set it in `sleeper.py`'s `get_league`/`get_leagues` from `settings.get("playoff_round_type", 0)`. Small sub-edit — do it in this task.

In `grader.py`, update the three `grade_trade(...)` call sites to pass `playoff_week_start_by_league=supporting["playoff_week_start_by_league"]` and `phase_by_lwr=supporting["phase_by_lwr"]` (instead of `playoff_weeks_by_league=...`).

- [ ] **Step 4: Run tests**

Run: `pytest api/tests/test_grader_io.py -v && pytest api/tests/ -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/app/services/grader_io.py api/app/services/grader.py src/sleeper_dynasty/models/league.py src/sleeper_dynasty/api/sleeper.py api/tests/
git commit -m "feat(api): fetch winners/losers brackets, build phase_by_lwr, pass to grader"
```

### Task 8: Cache schema bump (force one-time re-grade)

**Files:**
- Modify: `api/app/services/chain_cache.py` (schema/version constant + the matchup-bundle cache key)
- Test: `api/tests/test_chain_cache.py`

- [ ] **Step 1: Write the failing test**

```python
# api/tests/test_chain_cache.py  (append)
def test_schema_version_bumped():
    from app.services.chain_cache import SCHEMA_VERSION
    assert SCHEMA_VERSION >= 2  # bumped for bracket-aware grading
```

> If `chain_cache.py` has no explicit `SCHEMA_VERSION`, introduce one and incorporate it into the cache filename or a stored `schema` field so old caches are treated as misses. Read the current read/write to choose the least-invasive mechanism.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest api/tests/test_chain_cache.py -k schema_version -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

Add `SCHEMA_VERSION = 2` (or bump existing). In `read`, treat an entry whose stored `schema` differs from `SCHEMA_VERSION` as a miss (returns `None` → triggers refresh). Do the same for the matchup-bundle cache so brackets get pulled on first refresh after deploy.

- [ ] **Step 4: Run tests**

Run: `pytest api/tests/test_chain_cache.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/app/services/chain_cache.py api/tests/test_chain_cache.py
git commit -m "chore(api): bump cache schema to force bracket-aware re-grade"
```

---

## Phase 6 — API response surface (aggregations, leaderboard, trade_view, models)

### Task 9: Owner aggregation buckets

**Files:**
- Modify: `api/app/services/aggregations.py` (`_aggregate_owner_rows` 54-86; `_records`/standings ~208-256)
- Test: `api/tests/test_aggregations.py` (or nearest)

- [ ] **Step 1: Write the failing test**

```python
def test_owner_rows_have_three_started_phases(sample_entry):
    from app.services.aggregations import _aggregate_owner_rows, _filter_trades_by_year
    rows = _aggregate_owner_rows(sample_entry, _filter_trades_by_year(sample_entry, "all"))
    r = next(iter(rows.values()))
    assert {"net_production_started_regular", "net_production_started_playoff",
            "net_production_started_toilet"} <= set(r)
    assert "net_production_started" not in r
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest api/tests/test_aggregations.py -k three_started_phases -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

`_blank()` (lines 57-64):

```python
        return {
            "user_id": uid,
            "net_ktc": 0.0, "net_production": 0.0,
            "net_production_started_regular": 0.0,
            "net_production_started_playoff": 0.0,
            "net_production_started_toilet": 0.0,
            "trades": 0,
            "net_ktc_at_trade": 0.0, "net_ktc_today_subset": 0.0,
        }
```

Accumulation (replace lines 79-84):

```python
            row["net_production_started_regular"] += float(
                (g.get("hindsight_started_regular_swing") or {}).get(uid, 0) or 0)
            row["net_production_started_playoff"] += float(
                (g.get("hindsight_started_playoff_swing") or {}).get(uid, 0) or 0)
            row["net_production_started_toilet"] += float(
                (g.get("hindsight_started_toilet_swing") or {}).get(uid, 0) or 0)
```

In `_records`/standings (~243-256), any `net_production_started` reference becomes `net_production_started_regular`; add `net_production_started_toilet` to emitted standings rows.

- [ ] **Step 4: Run tests**

Run: `pytest api/tests/test_aggregations.py -q && pytest api/tests/ -q`
Expected: PASS (fix downstream references surfaced by the run).

- [ ] **Step 5: Commit**

```bash
git add api/app/services/aggregations.py api/tests/
git commit -m "feat(api): owner rows carry regular/playoff/toilet started production"
```

### Task 10: Leaderboard metrics + breakdown model

**Files:**
- Modify: `api/app/models/leaderboard.py:8-26`
- Modify: `api/app/services/leaderboard.py` (`owner_metrics` 24-37; `GMRow` build 81-93)
- Test: `api/tests/test_leaderboard.py`

- [ ] **Step 1: Write the failing test**

```python
def test_owner_metrics_maps_four_keys():
    from app.services.leaderboard import owner_metrics
    m = owner_metrics({"A": {
        "net_ktc": 100, "net_production_started_regular": 50,
        "net_production_started_playoff": 30, "net_production_started_toilet": 5}})
    assert m["A"] == {"value": 100, "regular": 50, "playoff": 30, "toilet": 5}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest api/tests/test_leaderboard.py -k four_keys -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

`owner_metrics` (leaderboard.py 30-37):

```python
    return {
        uid: {
            "value": r["net_ktc"],
            "regular": r["net_production_started_regular"],
            "playoff": r["net_production_started_playoff"],
            "toilet": r["net_production_started_toilet"],
        }
        for uid, r in rows.items()
    }
```

`models/leaderboard.py` `RatingBreakdown`:

```python
class RatingBreakdown(BaseModel):
    playoff: int
    regular: int
    value: int
    toilet: int
```

`GMRow` — replace `net_started` with `net_regular` and add `net_toilet`:

```python
    net_ktc: float
    net_regular: float
    net_playoff: float
    net_toilet: float
```

`build_leaderboard` (leaderboard.py 81-93) — set the renamed/added fields:

```python
                net_ktc=r["net_ktc"],
                net_regular=r["net_production_started_regular"],
                net_playoff=r["net_production_started_playoff"],
                net_toilet=r["net_production_started_toilet"],
```

Also `all_time_ratings` (40-47) is unchanged (it only reads `rating`).

- [ ] **Step 4: Run tests**

Run: `pytest api/tests/test_leaderboard.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/app/models/leaderboard.py api/app/services/leaderboard.py api/tests/test_leaderboard.py
git commit -m "feat(api): leaderboard breakdown + rows carry regular/playoff/value/toilet"
```

### Task 11: Trade detail view fields

**Files:**
- Modify: `api/app/models/trade.py:17-18`
- Modify: `api/app/services/trade_view.py:48-52` (and the became block ~69)
- Test: `api/tests/test_trade_view.py`

- [ ] **Step 1: Write the failing test**

```python
def test_trade_view_exposes_three_started_phases(sample_entry_with_trade):
    from app.services.trade_view import build_trade_view
    v = build_trade_view(sample_entry_with_trade, _TRADE_ID)
    side = v.sides[0]
    assert hasattr(side, "hindsight_started_regular_swing")
    assert hasattr(side, "hindsight_started_toilet_swing")
    assert not hasattr(side, "hindsight_started_swing")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest api/tests/test_trade_view.py -k three_started -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

`api/app/models/trade.py` (17-18) — replace/add:

```python
    hindsight_started_regular_swing: float = 0.0
    hindsight_started_playoff_swing: float = 0.0
    hindsight_started_toilet_swing: float = 0.0
```

`trade_view.py` (48-52) — map the three:

```python
            hindsight_started_regular_swing=float(
                (grade.get("hindsight_started_regular_swing") or {}).get(uid, 0) or 0),
            hindsight_started_playoff_swing=float(
                (grade.get("hindsight_started_playoff_swing") or {}).get(uid, 0) or 0),
            hindsight_started_toilet_swing=float(
                (grade.get("hindsight_started_toilet_swing") or {}).get(uid, 0) or 0),
```

- [ ] **Step 4: Run tests**

Run: `pytest api/tests/test_trade_view.py -q && pytest api/tests/ -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/app/models/trade.py api/app/services/trade_view.py api/tests/test_trade_view.py
git commit -m "feat(api): trade detail exposes regular/playoff/toilet started swings"
```

---

## Phase 7 — became-grade taxonomy

### Task 12: `build_became_grade` phase buckets

**Files:**
- Modify: `src/sleeper_dynasty/engine/regrade.py` (`_production_while_owned` ~60-90, `build_became_grade` 94-147)
- Modify: `api/app/services/grader.py:233-240` (became compute call)
- Modify: `api/app/services/trade_view.py:69` (became surface) + became response model
- Test: `tests/test_regrade.py`, `api/tests/test_became_view.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_regrade.py (append)
def test_became_grade_emits_phase_buckets():
    from sleeper_dynasty.engine.regrade import build_became_grade
    out = build_became_grade(*_became_args_with_phase())  # reuse existing fixture + add phase_by_lwr
    side = next(iter(out.values()))
    assert {"regular", "playoff", "toilet", "value"} <= set(side)
    assert "started" not in side
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_regrade.py -k phase_buckets -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

`regrade.py` `_production_while_owned` (60-90) currently takes `playoff_weeks_by_league` + `playoff_only`. Replace with `phase_by_lwr` + `phase_filter` + `playoff_week_start_by_league`, mirroring the Task-4 phase logic (regular = `wk < ps`, else `phase_by_lwr.get((lg,wk,rid),"dropped")`). `build_became_grade` (94-147) computes `regular`/`playoff`/`toilet` via three filtered calls instead of `started`/`playoff`, returning keys `{"ktc"/"value", "production", "regular", "playoff", "toilet"}` per the existing return shape (rename `started` → `regular`, add `toilet`).

`grader.py:233-240` — pass `phase_by_lwr` + `playoff_week_start_by_league` into `build_became_grade` from `supporting`.

`trade_view.py:69` + the became response model — surface `regular`/`playoff`/`toilet` (replace `started`).

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_regrade.py -q && pytest api/tests/test_became_view.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/regrade.py api/app/services/grader.py api/app/services/trade_view.py tests/ api/tests/
git commit -m "feat: became-grade adopts regular/playoff/toilet taxonomy"
```

---

## Phase 8 — Web

### Task 13: Types

**Files:**
- Modify: `web/lib/types.ts` (`RatingBreakdown`, `GMRow`, trade-side + became shapes)
- Test: `web/tests/` (type-level; covered by component tests below)

- [ ] **Step 1: Implement**

`RatingBreakdown`: `{ playoff: number; regular: number; value: number; toilet: number }`.
`GMRow`: replace `net_started` with `net_regular`, add `net_toilet`.
Trade-side + became shapes: replace `hindsight_started_swing`/`started` with `hindsight_started_regular_swing`/`regular`, add `*_toilet`/`toilet`.

- [ ] **Step 2: Commit**

```bash
git add web/lib/types.ts
git commit -m "feat(web): types for regular/playoff/toilet metrics"
```

### Task 14: Leaderboard breakdown rows

**Files:**
- Modify: `web/components/Leaderboard.tsx` (breakdown block 111-129; the failing `1500` assertion area already handled)
- Test: `web/tests/Leaderboard.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// web/tests/Leaderboard.test.tsx — extend the breakdown test's row to include toilet
breakdown: { playoff: 220, regular: 80, value: 40, toilet: 15 },
// ...after expanding:
expect(screen.getByText(/Toilet Bowl/i)).toBeInTheDocument();
expect(screen.getByText(/\+15/)).toBeInTheDocument();
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run --config tests/vitest.config.ts tests/Leaderboard.test.tsx`
Expected: FAIL — no Toilet Bowl row.

- [ ] **Step 3: Implement**

In the expanded breakdown (Leaderboard.tsx 113-124), render four `BreakdownRow`s under Base:

```tsx
            <BreakdownRow label="Playoff Points" points={r.breakdown.playoff} />
            <BreakdownRow label="Regular Season Points" points={r.breakdown.regular} />
            <BreakdownRow label="Trade Value" points={r.breakdown.value} />
            <BreakdownRow label="Toilet Bowl Points" points={r.breakdown.toilet} />
```

- [ ] **Step 4: Run tests**

Run: `cd web && npx vitest run --config tests/vitest.config.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/components/Leaderboard.tsx web/tests/Leaderboard.test.tsx
git commit -m "feat(web): leaderboard breakdown shows Regular + Toilet Bowl"
```

### Task 15: Trade detail + TradeBecame + OG card

**Files:**
- Modify: `web/components/TradeBecame.tsx`, trade detail metric rows, `web/lib/og-card-data.ts`
- Test: `web/tests/TradeBecame.test.tsx`, `web/tests/og-card-data.test.ts`

- [ ] **Step 1: Write the failing test**

```tsx
// web/tests/TradeBecame.test.tsx — assert the three started phases render with new labels
expect(screen.getByText(/Regular Season Points/i)).toBeInTheDocument();
expect(screen.getByText(/Toilet Bowl Points/i)).toBeInTheDocument();
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run --config tests/vitest.config.ts tests/TradeBecame.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement**

Render Regular/Playoff/Toilet rows wherever the trade page + `TradeBecame` previously showed "Points Started"/"Playoff Points". Update `og-card-data.ts` to read the renamed fields and include Toilet Bowl if the card lists the breakdown.

- [ ] **Step 4: Run tests**

Run: `cd web && npx vitest run --config tests/vitest.config.ts`
Expected: PASS (all web suites).

- [ ] **Step 5: Commit**

```bash
git add web/components/TradeBecame.tsx web/lib/og-card-data.ts web/app/league/'[id]'/trade web/tests/
git commit -m "feat(web): trade + became views show Regular/Playoff/Toilet; OG card updated"
```

---

## Phase 9 — Docs

### Task 16: README + CLAUDE.md vocabulary

**Files:**
- Modify: `README.md` (metrics table ~35-45, GM Ratings section), `CLAUDE.md` (Key conventions "Four metrics" bullet)

- [ ] **Step 1: Implement**

Update the metrics vocabulary from four to five: **Trade Value, Total Points, Regular Season Points, Playoff Points, Toilet Bowl Points**, with the new internal field names and the bracket-aware playoff definition. Update the GM Rating weights to P.40/R.30/V.22/TB.08. Note the became-grade uses the same taxonomy.

- [ ] **Step 2: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "docs: five-metric taxonomy + bracket-aware playoff definition + new GM weights"
```

---

## Phase 10 — Validation

### Task 17: Audit report script

**Files:**
- Create: `scripts/audit_playoff_phases.py`

- [ ] **Step 1: Implement** a script that, for league `9000000000000000001`, walks the chain and for each season prints: winners-bracket vs losers-bracket roster→owner membership, per-owner Regular/Playoff/Toilet net production, and assertions:
  - every roster appears in exactly one bracket per season (or is logged),
  - each season champion's acquired-and-started players show `playoff > 0`,
  - owners whose teams missed the playoffs show `playoff == 0` and (if they traded) `toilet != 0` possible.

It runs against the live cache (post-refresh) or fetches read-only from Sleeper. Print a clear PASS/REVIEW summary per assertion.

- [ ] **Step 2: Run it**

Run: `python scripts/audit_playoff_phases.py`
Expected: prints per-season tables; all structural assertions PASS. **Human-eyeball** the per-owner numbers against what actually happened in 2023–25.

- [ ] **Step 3: Commit**

```bash
git add scripts/audit_playoff_phases.py
git commit -m "test: playoff-phase audit report for human validation"
```

### Task 18: Full-suite + live verification

- [ ] **Step 1:** `pytest tests/ -q` (engine) — expect green.
- [ ] **Step 2:** `cd api && pytest -q` — expect green.
- [ ] **Step 3:** `cd web && npx vitest run --config tests/vitest.config.ts` — expect green.
- [ ] **Step 4:** Start the app (`make dev-api` + `make dev-web`), trigger a refresh for the league, open the **GM Ratings** tab (verify the breakdown shows Playoff/Regular/Value/Toilet and ratings shifted) and two trade pages (verify Regular/Playoff/Toilet render, and a non-playoff owner's trade shows 0 playoff points). Use the `verify` skill if helpful.
- [ ] **Step 5:** Final commit if any fixups:

```bash
git add -A && git commit -m "test: green full suite + live verification for bracket-aware grading"
```

---

## Self-Review Notes (for the executor)

- **Reconciliation:** after Task 9, optionally assert in an api test that `regular + playoff + toilet <= started_total` for a fixture where you also compute the all-weeks started sum — proves nothing is double-counted.
- **Symmetry:** the same `phase_filter`/`phase_by_lwr` gates both `_received_points` and `_phantom_points` (Task 4) — do not special-case one side.
- **Missing-bracket guard:** `classify_playoff_phases([], [], ...) == {}` (Task 2) ⇒ all playoff/toilet credit becomes 0 for that season and `_phase` returns `"dropped"`; never falls back to calendar. Log a WARN in `grader_io` when a sealed season yields an empty bracket.
- **Don't forget the CLI consumers:** `output/google_sheets.py` and `engine/trade_story.py` reference the old field names — Task 5 updates them; `grep -rn "hindsight_started_swing\|net_production_started\b" src/ api/ web/` must return nothing after Phase 8.
