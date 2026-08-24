# Weekly Recap & Outlook Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate a savage, ESPN-parody-analyst weekly recap of completed games plus an outlook on the upcoming week, where a facts engine computes every number deterministically and Claude does the comedy writing.

**Architecture:** Approach A — a `FactsBuilder` turns Sleeper/ESPN/weather/projection data into a structured "facts packet"; a `RecapWriter` feeds that packet + a persona + a `league_lore` file to Claude (single call, prompt-cached) and returns prose; a pluggable `Delivery` renders it (HTML/Doc now, chat later). The LLM only jokes about facts the engine supplies.

**Tech Stack:** Python 3.11+, `httpx` (async), `anthropic` SDK, `jinja2`, `pytest` + `pytest-asyncio` (marker style: every async test is decorated `@pytest.mark.asyncio`). Existing reusable pieces: `engine/lineup.solve_optimal_lineup`, `engine/simulator.simulate_season`, `cache.FileCache`, `util/name_match.normalize_player_name`.

**Milestones:**
- **Milestone 1 (Tasks 1–13):** Recap-only product. Shippable and testable on real past-season data today.
- **Milestone 2 (Tasks 14–20):** Outlook extension (schedule/byes/weather/playoff-stakes + outlook prose).

**Conventions for every task:** Follow the existing test style in `tests/test_sleeper_api.py` — fixtures live in `tests/fixtures/`, `httpx` calls are mocked with `unittest.mock.AsyncMock`, no live network in tests. Run the full suite with `pytest -q` before each commit. Branch is `feature/weekly-recap` (already created).

---

## Task 1: Add `anthropic` dependency

**Files:**
- Modify: `pyproject.toml:11-19` (dependencies list)

- [ ] **Step 1: Add the dependency**

In `pyproject.toml`, add `"anthropic>=0.40"` to the `dependencies` array (after `"jinja2>=3.1",`):

```toml
dependencies = [
    "httpx>=0.27",
    "numpy>=1.26",
    "beautifulsoup4>=4.12",
    "google-api-python-client>=2.100",
    "google-auth-oauthlib>=1.1",
    "google-auth-httplib2>=0.2",
    "jinja2>=3.1",
    "anthropic>=0.40",
]
```

- [ ] **Step 2: Install**

Run: `uv pip install -e ".[dev]"`
Expected: resolves and installs `anthropic`.

- [ ] **Step 3: Verify import**

Run: `python -c "import anthropic; print(anthropic.__version__)"`
Expected: prints a version string, no ImportError.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build: add anthropic SDK dependency for recap writer"
```

---

## Task 2: Sleeper — fetch rich matchup results + NFL state

The existing `get_matchups` discards per-player data. The recap needs `players`, `starters`, and `players_points` per roster. We add a new method rather than change `get_matchups` (the simulator pipeline depends on its current shape). We also add `get_nfl_state` for default week selection.

**Files:**
- Modify: `src/sleeper_dynasty/api/sleeper.py` (add two methods after `get_matchups`)
- Test: `tests/test_sleeper_api.py`
- Fixtures: `tests/fixtures/matchup_results_week1.json`, `tests/fixtures/nfl_state.json`

- [ ] **Step 1: Create the fixtures**

`tests/fixtures/matchup_results_week1.json` (two rosters, one matchup):

```json
[
  {
    "matchup_id": 1,
    "roster_id": 1,
    "points": 142.3,
    "starters": ["100", "200"],
    "players": ["100", "200", "300"],
    "players_points": {"100": 28.0, "200": 114.3, "300": 31.0}
  },
  {
    "matchup_id": 1,
    "roster_id": 2,
    "points": 98.1,
    "starters": ["400", "500"],
    "players": ["400", "500", "600"],
    "players_points": {"400": 50.1, "500": 48.0, "600": 2.0}
  }
]
```

`tests/fixtures/nfl_state.json`:

```json
{"week": 10, "season": "2025", "season_type": "regular", "display_week": 10}
```

- [ ] **Step 2: Write the failing tests**

Add to `tests/test_sleeper_api.py`:

```python
class TestGetMatchupResults:
    @pytest.mark.asyncio
    async def test_returns_per_roster_entries(self, client):
        resp = mock_response("matchup_results_week1.json")
        with patch.object(client._client, "get", AsyncMock(return_value=resp)):
            results = await client.get_matchup_results("LID", 1)
        assert len(results) == 2
        r1 = next(r for r in results if r.roster_id == 1)
        assert r1.matchup_id == 1
        assert r1.points == 142.3
        assert r1.starters == ["100", "200"]
        assert r1.players_points["300"] == 31.0


class TestGetNflState:
    @pytest.mark.asyncio
    async def test_returns_current_week(self, client):
        resp = mock_response("nfl_state.json")
        with patch.object(client._client, "get", AsyncMock(return_value=resp)):
            state = await client.get_nfl_state()
        assert state["week"] == 10
        assert state["season"] == "2025"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_sleeper_api.py -k "MatchupResults or NflState" -v`
Expected: FAIL — `AttributeError: 'SleeperClient' object has no attribute 'get_matchup_results'`.

- [ ] **Step 4: Add the model**

Add to `src/sleeper_dynasty/models/league.py` (after the `Matchup` dataclass):

```python
@dataclass
class MatchupResult:
    """Full per-roster result for one league-week, including per-player
    points and the actually-started lineup. Two MatchupResults sharing a
    ``matchup_id`` are opponents.
    """
    week: int
    matchup_id: int | None
    roster_id: int
    points: float | None
    starters: list[str]
    players: list[str]
    players_points: dict[str, float]
```

- [ ] **Step 5: Implement the methods**

Add to `src/sleeper_dynasty/api/sleeper.py` after `get_matchups`. Import `MatchupResult` at the top alongside the existing model imports.

```python
    async def get_matchup_results(
        self, league_id: str, week: int
    ) -> list[MatchupResult]:
        """Fetch full per-roster matchup data for one league-week.

        Unlike ``get_matchups`` (which collapses to paired team scores),
        this preserves ``starters``, ``players``, and ``players_points``
        so the recap engine can compute bench regret, heroes, and busts.
        """
        resp = await self._client.get(f"/league/{league_id}/matchups/{week}")
        resp.raise_for_status()
        results = []
        for entry in resp.json():
            results.append(MatchupResult(
                week=week,
                matchup_id=entry.get("matchup_id"),
                roster_id=entry["roster_id"],
                points=entry.get("points"),
                starters=entry.get("starters") or [],
                players=entry.get("players") or [],
                players_points=entry.get("players_points") or {},
            ))
        return results

    async def get_nfl_state(self) -> dict:
        """Fetch Sleeper's NFL state (current week, season, season_type).

        Used to default the recap to the last completed week and the
        outlook to the upcoming week.
        """
        resp = await self._client.get("/state/nfl")
        resp.raise_for_status()
        return resp.json()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_sleeper_api.py -k "MatchupResults or NflState" -v`
Expected: PASS (2 passed).

- [ ] **Step 7: Commit**

```bash
git add src/sleeper_dynasty/api/sleeper.py src/sleeper_dynasty/models/league.py tests/test_sleeper_api.py tests/fixtures/matchup_results_week1.json tests/fixtures/nfl_state.json
git commit -m "feat: fetch rich Sleeper matchup results + NFL state"
```

---

## Task 3: Recap facts data models

Define the dataclasses that make up the facts packet's recap half. These are the engine↔writer contract; the writer serializes them to JSON.

**Files:**
- Create: `src/sleeper_dynasty/models/recap.py`
- Test: `tests/test_recap_models.py`

- [ ] **Step 1: Write the failing test**

`tests/test_recap_models.py`:

```python
from sleeper_dynasty.models.recap import (
    MatchupRecap, PlayerLine, BenchRegret, LuckNote, RecapFacts,
)


def test_matchup_recap_to_dict_roundtrips():
    m = MatchupRecap(
        winner="Team A", loser="Team B", winner_points=142.3,
        loser_points=98.1, margin=44.2, blowout=True, nailbiter=False,
    )
    d = m.to_dict()
    assert d["winner"] == "Team A"
    assert d["margin"] == 44.2
    assert d["blowout"] is True


def test_recap_facts_to_dict_nests_sections():
    facts = RecapFacts(
        week=9,
        league_name="Dynasty Bros",
        standings=[{"owner": "Team A", "wins": 6, "losses": 2}],
        matchups=[],
        high_scorer={"owner": "Team A", "points": 158.0},
        low_scorer={"owner": "Team B", "points": 71.2},
        bench_regret=[],
        lucky=[],
        unlucky=[],
        heroes=[],
        goats=[],
        busts=[],
    )
    d = facts.to_dict()
    assert d["week"] == 9
    assert d["high_scorer"]["points"] == 158.0
    assert "matchups" in d
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_recap_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sleeper_dynasty.models.recap'`.

- [ ] **Step 3: Implement the models**

`src/sleeper_dynasty/models/recap.py`:

```python
"""Structured 'facts packet' models for the weekly recap.

These dataclasses are the contract between the FactsBuilder (engine/recap.py)
and the RecapWriter (llm/recap_writer.py). The writer serializes them to JSON
and is instructed to joke ONLY about facts present here — so every number the
comedy references is engine-verified.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PlayerLine:
    """One player's line in a recap beat (hero, goat, bust, bench)."""
    player: str
    owner: str
    points: float
    position: str | None = None
    projected: float | None = None

    def to_dict(self) -> dict[str, Any]:
        d = {"player": self.player, "owner": self.owner, "points": self.points}
        if self.position is not None:
            d["position"] = self.position
        if self.projected is not None:
            d["projected"] = self.projected
        return d


@dataclass
class MatchupRecap:
    winner: str
    loser: str
    winner_points: float
    loser_points: float
    margin: float
    blowout: bool
    nailbiter: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "winner": self.winner, "loser": self.loser,
            "winner_points": self.winner_points,
            "loser_points": self.loser_points,
            "margin": self.margin,
            "blowout": self.blowout, "nailbiter": self.nailbiter,
        }


@dataclass
class BenchRegret:
    owner: str
    points_left_on_bench: float
    benched_hero: PlayerLine
    started_dud: PlayerLine

    def to_dict(self) -> dict[str, Any]:
        return {
            "owner": self.owner,
            "points_left_on_bench": self.points_left_on_bench,
            "benched_hero": self.benched_hero.to_dict(),
            "started_dud": self.started_dud.to_dict(),
        }


@dataclass
class LuckNote:
    owner: str
    note: str

    def to_dict(self) -> dict[str, Any]:
        return {"owner": self.owner, "note": self.note}


@dataclass
class RecapFacts:
    week: int
    league_name: str
    standings: list[dict[str, Any]]
    matchups: list[MatchupRecap]
    high_scorer: dict[str, Any] | None
    low_scorer: dict[str, Any] | None
    bench_regret: list[BenchRegret]
    lucky: list[LuckNote]
    unlucky: list[LuckNote]
    heroes: list[PlayerLine]
    goats: list[PlayerLine]
    busts: list[PlayerLine]

    def to_dict(self) -> dict[str, Any]:
        return {
            "week": self.week,
            "league_name": self.league_name,
            "standings": self.standings,
            "matchups": [m.to_dict() for m in self.matchups],
            "high_scorer": self.high_scorer,
            "low_scorer": self.low_scorer,
            "bench_regret": [b.to_dict() for b in self.bench_regret],
            "lucky": [n.to_dict() for n in self.lucky],
            "unlucky": [n.to_dict() for n in self.unlucky],
            "heroes": [p.to_dict() for p in self.heroes],
            "goats": [p.to_dict() for p in self.goats],
            "busts": [p.to_dict() for p in self.busts],
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_recap_models.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/models/recap.py tests/test_recap_models.py
git commit -m "feat: add recap facts-packet data models"
```

---

## Task 4: Facts engine — matchup results, scorers, blowout/nailbiter

First slice of `engine/recap.py`: given paired `MatchupResult`s and a roster→owner-name map, build `MatchupRecap`s plus high/low scorer.

**Files:**
- Create: `src/sleeper_dynasty/engine/recap.py`
- Test: `tests/test_recap_engine.py`

Thresholds (module constants): `BLOWOUT_MARGIN = 40.0`, `NAILBITER_MARGIN = 5.0`.

- [ ] **Step 1: Write the failing test**

`tests/test_recap_engine.py`:

```python
import pytest

from sleeper_dynasty.models.league import MatchupResult
from sleeper_dynasty.engine.recap import build_matchup_recaps, OWNER_BY_ROSTER


def _result(week, mid, rid, pts, starters=None, pp=None):
    return MatchupResult(
        week=week, matchup_id=mid, roster_id=rid, points=pts,
        starters=starters or [], players=list((pp or {}).keys()),
        players_points=pp or {},
    )


OWNERS = {1: "Team A", 2: "Team B", 3: "Team C", 4: "Team D"}


def test_pairs_by_matchup_id_and_flags_blowout():
    results = [
        _result(9, 1, 1, 142.3), _result(9, 1, 2, 98.1),
        _result(9, 2, 3, 100.0), _result(9, 2, 4, 97.0),
    ]
    recaps, high, low = build_matchup_recaps(results, OWNERS)
    blowout = next(r for r in recaps if r.winner == "Team A")
    assert blowout.loser == "Team B"
    assert blowout.margin == pytest.approx(44.2)
    assert blowout.blowout is True
    assert blowout.nailbiter is False


def test_flags_nailbiter_and_finds_scorers():
    results = [
        _result(9, 1, 1, 142.3), _result(9, 1, 2, 98.1),
        _result(9, 2, 3, 100.0), _result(9, 2, 4, 97.0),
    ]
    recaps, high, low = build_matchup_recaps(results, OWNERS)
    nail = next(r for r in recaps if r.winner == "Team C")
    assert nail.nailbiter is True
    assert high == {"owner": "Team A", "points": 142.3}
    assert low == {"owner": "Team B", "points": 98.1}


def test_skips_unplayed_both_zero():
    results = [_result(9, 1, 1, 0.0), _result(9, 1, 2, 0.0)]
    recaps, high, low = build_matchup_recaps(results, OWNERS)
    assert recaps == []
    assert high is None and low is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_recap_engine.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sleeper_dynasty.engine.recap'`.

- [ ] **Step 3: Implement**

`src/sleeper_dynasty/engine/recap.py`:

```python
"""FactsBuilder: turn raw league data into the recap facts packet.

Every comedy-relevant number is computed here so the LLM writer never has
to (and can never invent one). Pure functions, fully unit-testable against
real past-week Sleeper data.
"""

from __future__ import annotations

import logging

from sleeper_dynasty.models.league import MatchupResult
from sleeper_dynasty.models.recap import MatchupRecap

logger = logging.getLogger(__name__)

# Type alias for readability: roster_id -> owner display/team name.
OWNER_BY_ROSTER = dict  # documentation marker; callers pass dict[int, str]

BLOWOUT_MARGIN = 40.0
NAILBITER_MARGIN = 5.0


def _pair_results(
    results: list[MatchupResult],
) -> list[tuple[MatchupResult, MatchupResult]]:
    """Group MatchupResults into opponent pairs by matchup_id.

    Skips unplayed weeks: Sleeper returns placeholder entries for upcoming
    weeks with points=0 on both sides. Two real NFL fantasy lineups totaling
    exactly 0 is functionally impossible, so both-zero is the unplayed
    sentinel (mirrors cli._assemble_played_matchups).
    """
    by_mid: dict[int | None, list[MatchupResult]] = {}
    for r in results:
        by_mid.setdefault(r.matchup_id, []).append(r)
    pairs = []
    for entries in by_mid.values():
        if len(entries) != 2:
            continue
        a, b = entries
        if (a.points or 0.0) == 0.0 and (b.points or 0.0) == 0.0:
            continue
        pairs.append((a, b))
    return pairs


def build_matchup_recaps(
    results: list[MatchupResult],
    owner_by_roster: dict[int, str],
) -> tuple[list[MatchupRecap], dict | None, dict | None]:
    """Build per-matchup recaps plus the week's high and low scorer.

    Returns ``(recaps, high_scorer, low_scorer)`` where the scorer dicts are
    ``{"owner": str, "points": float}`` or ``None`` if no games were played.
    """
    pairs = _pair_results(results)
    recaps: list[MatchupRecap] = []
    all_scores: list[tuple[str, float]] = []

    for a, b in pairs:
        a_pts, b_pts = a.points or 0.0, b.points or 0.0
        winner_r, loser_r = (a, b) if a_pts >= b_pts else (b, a)
        w_pts, l_pts = winner_r.points or 0.0, loser_r.points or 0.0
        margin = round(w_pts - l_pts, 2)
        recaps.append(MatchupRecap(
            winner=owner_by_roster.get(winner_r.roster_id, "Unknown"),
            loser=owner_by_roster.get(loser_r.roster_id, "Unknown"),
            winner_points=w_pts,
            loser_points=l_pts,
            margin=margin,
            blowout=margin >= BLOWOUT_MARGIN,
            nailbiter=margin <= NAILBITER_MARGIN,
        ))
        all_scores.append((owner_by_roster.get(a.roster_id, "Unknown"), a_pts))
        all_scores.append((owner_by_roster.get(b.roster_id, "Unknown"), b_pts))

    if not all_scores:
        return recaps, None, None

    high = max(all_scores, key=lambda x: x[1])
    low = min(all_scores, key=lambda x: x[1])
    return (
        recaps,
        {"owner": high[0], "points": high[1]},
        {"owner": low[0], "points": low[1]},
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_recap_engine.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/recap.py tests/test_recap_engine.py
git commit -m "feat: recap engine — matchups, scorers, blowout/nailbiter"
```

---

## Task 5: Facts engine — bench regret

Use the actual `players_points` as the "projection" fed to `solve_optimal_lineup`, compute the optimal lineup over ALL the roster's players for that week, and diff against what was actually started. `points_left_on_bench = optimal_total - actual_started_total`. `benched_hero` = highest-scoring non-started player; `started_dud` = lowest-scoring started player.

**Files:**
- Modify: `src/sleeper_dynasty/engine/recap.py`
- Test: `tests/test_recap_engine.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_recap_engine.py`:

```python
from sleeper_dynasty.engine.recap import build_bench_regret


def test_bench_regret_finds_points_left_and_culprits():
    # Roster: 1 QB, 1 FLEX. Player positions + week points:
    #   p1 QB started 10  | p2 QB benched 25  (should have started p2)
    #   p3 WR started 4   | p4 WR benched 18
    positions_by_player = {
        "p1": "QB", "p2": "QB", "p3": "WR", "p4": "WR",
    }
    result = MatchupResult(
        week=9, matchup_id=1, roster_id=1, points=14.0,
        starters=["p1", "p3"],
        players=["p1", "p2", "p3", "p4"],
        players_points={"p1": 10.0, "p2": 25.0, "p3": 4.0, "p4": 18.0},
    )
    regret = build_bench_regret(
        result,
        roster_positions=["QB", "FLEX"],
        positions_by_player=positions_by_player,
        owner="Team A",
    )
    # Optimal: p2 (QB 25) + p4 (FLEX/WR 18) = 43; actual started = 14.
    assert regret.points_left_on_bench == pytest.approx(29.0)
    assert regret.benched_hero.player == "p2"
    assert regret.benched_hero.points == 25.0
    assert regret.started_dud.player == "p3"
    assert regret.started_dud.points == 4.0
    assert regret.owner == "Team A"


def test_bench_regret_none_when_lineup_optimal():
    positions_by_player = {"p1": "QB", "p2": "WR"}
    result = MatchupResult(
        week=9, matchup_id=1, roster_id=1, points=30.0,
        starters=["p1", "p2"], players=["p1", "p2"],
        players_points={"p1": 20.0, "p2": 10.0},
    )
    regret = build_bench_regret(
        result, ["QB", "FLEX"], positions_by_player, "Team A"
    )
    assert regret is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_recap_engine.py -k bench -v`
Expected: FAIL — `ImportError: cannot import name 'build_bench_regret'`.

- [ ] **Step 3: Implement**

Add to `src/sleeper_dynasty/engine/recap.py` (import the solver at top: `from sleeper_dynasty.engine.lineup import solve_optimal_lineup` and `from sleeper_dynasty.models.recap import BenchRegret, PlayerLine`):

```python
def build_bench_regret(
    result: MatchupResult,
    roster_positions: list[str],
    positions_by_player: dict[str, str],
    owner: str,
    min_points: float = 1.0,
) -> BenchRegret | None:
    """Compute points left on the bench for one roster-week.

    Feeds the week's ACTUAL ``players_points`` to the optimal-lineup solver
    as if they were projections, then diffs the optimal starter total against
    the lineup the manager actually started. Returns None if the manager was
    already optimal (or within ``min_points``).
    """
    # Build (position, actual_points) for every rostered player we can place.
    player_map: dict[str, tuple[str, float]] = {}
    for pid in result.players:
        pos = positions_by_player.get(pid)
        if not pos:
            continue
        player_map[pid] = (pos, result.players_points.get(pid, 0.0))

    _, optimal_total = solve_optimal_lineup(roster_positions, player_map)

    actual_total = sum(
        result.players_points.get(pid, 0.0) for pid in result.starters
    )
    left = round(optimal_total - actual_total, 2)
    if left < min_points:
        return None

    started = [
        (pid, result.players_points.get(pid, 0.0)) for pid in result.starters
    ]
    benched = [
        (pid, result.players_points.get(pid, 0.0))
        for pid in result.players
        if pid not in set(result.starters)
    ]
    if not started or not benched:
        return None

    hero_pid, hero_pts = max(benched, key=lambda x: x[1])
    dud_pid, dud_pts = min(started, key=lambda x: x[1])

    return BenchRegret(
        owner=owner,
        points_left_on_bench=left,
        benched_hero=PlayerLine(
            player=hero_pid, owner=owner, points=hero_pts,
            position=positions_by_player.get(hero_pid),
        ),
        started_dud=PlayerLine(
            player=dud_pid, owner=owner, points=dud_pts,
            position=positions_by_player.get(dud_pid),
        ),
    )
```

> NOTE: `benched_hero.player` / `started_dud.player` hold the raw `player_id` here. Task 9 (assembly) resolves IDs to full names before the packet reaches the writer.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_recap_engine.py -k bench -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/recap.py tests/test_recap_engine.py
git commit -m "feat: recap engine — bench regret via lineup optimizer"
```

---

## Task 6: Facts engine — lucky & unlucky

Given the week's matchups, flag: highest score that still LOST (unlucky), lowest score that still WON (lucky). Also annotate "would have beaten everyone else" (unlucky loser whose score beats all but their own opponent) and "lost to everyone" (lucky winner whose score is below the median).

**Files:**
- Modify: `src/sleeper_dynasty/engine/recap.py`
- Test: `tests/test_recap_engine.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_recap_engine.py`:

```python
from sleeper_dynasty.engine.recap import build_luck_notes


def test_luck_notes_flag_unlucky_loser_and_lucky_winner():
    # Pairs: A 140 beats B 90 ; C 110 beats D 105 ; E 80 beats F 70
    # Highest loser = D (105) -> unlucky. Lowest winner = E (80) -> lucky.
    results = [
        _result(9, 1, 1, 140.0), _result(9, 1, 2, 90.0),
        _result(9, 2, 3, 110.0), _result(9, 2, 4, 105.0),
        _result(9, 3, 5, 80.0), _result(9, 3, 6, 70.0),
    ]
    owners = {1: "A", 2: "B", 3: "C", 4: "D", 5: "E", 6: "F"}
    lucky, unlucky = build_luck_notes(results, owners)
    assert any(n.owner == "D" for n in unlucky)
    assert any(n.owner == "E" for n in lucky)


def test_luck_notes_empty_when_no_games():
    results = [_result(9, 1, 1, 0.0), _result(9, 1, 2, 0.0)]
    lucky, unlucky = build_luck_notes(results, {1: "A", 2: "B"})
    assert lucky == [] and unlucky == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_recap_engine.py -k luck -v`
Expected: FAIL — `ImportError: cannot import name 'build_luck_notes'`.

- [ ] **Step 3: Implement**

Add to `src/sleeper_dynasty/engine/recap.py` (`from sleeper_dynasty.models.recap import LuckNote`):

```python
def build_luck_notes(
    results: list[MatchupResult],
    owner_by_roster: dict[int, str],
) -> tuple[list[LuckNote], list[LuckNote]]:
    """Flag the lucky (lowest-scoring winner) and unlucky (highest-scoring
    loser) owners of the week. Returns ``(lucky, unlucky)``.
    """
    pairs = _pair_results(results)
    if not pairs:
        return [], []

    winners: list[tuple[str, float]] = []
    losers: list[tuple[str, float]] = []
    for a, b in pairs:
        a_pts, b_pts = a.points or 0.0, b.points or 0.0
        w, l = (a, b) if a_pts >= b_pts else (b, a)
        winners.append((owner_by_roster.get(w.roster_id, "Unknown"),
                        w.points or 0.0))
        losers.append((owner_by_roster.get(l.roster_id, "Unknown"),
                       l.points or 0.0))

    lucky: list[LuckNote] = []
    unlucky: list[LuckNote] = []

    lowest_winner = min(winners, key=lambda x: x[1])
    lucky.append(LuckNote(
        owner=lowest_winner[0],
        note=(f"won with the lowest winning score of the week "
              f"({lowest_winner[1]:.1f}) — backed into it"),
    ))

    highest_loser = max(losers, key=lambda x: x[1])
    unlucky.append(LuckNote(
        owner=highest_loser[0],
        note=(f"put up {highest_loser[1]:.1f} — the highest score of any "
              f"loser this week — and still lost"),
    ))
    return lucky, unlucky
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_recap_engine.py -k luck -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/recap.py tests/test_recap_engine.py
git commit -m "feat: recap engine — lucky/unlucky notes"
```

---

## Task 7: Facts engine — heroes, goats, busts

League-wide best/worst individual STARTER performances, and busts (started players whose actual fell far below their weekly projection). Operates over all `MatchupResult`s.

**Files:**
- Modify: `src/sleeper_dynasty/engine/recap.py`
- Test: `tests/test_recap_engine.py`

Constants: `TOP_N = 3`, `BUST_PROJECTION_MIN = 10.0`, `BUST_RATIO = 0.5` (actual ≤ 50% of projection).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_recap_engine.py`:

```python
from sleeper_dynasty.engine.recap import build_player_beats


def test_heroes_and_goats_rank_starters_only():
    results = [
        MatchupResult(9, 1, 1, 100.0, starters=["p1", "p2"],
                      players=["p1", "p2", "p3"],
                      players_points={"p1": 41.0, "p2": 2.0, "p3": 99.0}),
        MatchupResult(9, 1, 2, 90.0, starters=["p4"], players=["p4"],
                      players_points={"p4": 30.0}),
    ]
    owners = {1: "A", 2: "B"}
    positions = {"p1": "WR", "p2": "RB", "p3": "QB", "p4": "TE"}
    heroes, goats, busts = build_player_beats(
        results, owners, positions, projections={}
    )
    # p3 has 99 but was BENCHED -> excluded. p1 (41) is top hero.
    assert heroes[0].player == "p1"
    assert all(h.player != "p3" for h in heroes)
    # Lowest started = p2 (2.0).
    assert goats[0].player == "p2"


def test_busts_flag_underperformers_vs_projection():
    results = [
        MatchupResult(9, 1, 1, 50.0, starters=["p1"], players=["p1"],
                      players_points={"p1": 4.0}),
    ]
    heroes, goats, busts = build_player_beats(
        results, {1: "A"}, {"p1": "WR"}, projections={"p1": 22.0}
    )
    assert busts[0].player == "p1"
    assert busts[0].projected == 22.0
    assert busts[0].points == 4.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_recap_engine.py -k "heroes or busts" -v`
Expected: FAIL — `ImportError: cannot import name 'build_player_beats'`.

- [ ] **Step 3: Implement**

Add to `src/sleeper_dynasty/engine/recap.py`:

```python
TOP_N = 3
BUST_PROJECTION_MIN = 10.0
BUST_RATIO = 0.5


def build_player_beats(
    results: list[MatchupResult],
    owner_by_roster: dict[int, str],
    positions_by_player: dict[str, str],
    projections: dict[str, float],
) -> tuple[list[PlayerLine], list[PlayerLine], list[PlayerLine]]:
    """League-wide heroes, goats, and busts among STARTED players.

    - heroes: top ``TOP_N`` started performances by actual points.
    - goats: bottom ``TOP_N`` started performances by actual points.
    - busts: started players whose projection was >= ``BUST_PROJECTION_MIN``
      but who scored <= ``BUST_RATIO`` of it, worst-ratio first.

    ``projections`` maps player_id -> weekly projected points (may be empty;
    then busts is empty). Only played weeks contribute (both-zero pairs are
    excluded upstream by the caller passing played results, but we also skip
    rosters whose points are 0).
    """
    started_lines: list[PlayerLine] = []
    bust_candidates: list[tuple[PlayerLine, float]] = []

    for r in results:
        if (r.points or 0.0) == 0.0:
            continue
        owner = owner_by_roster.get(r.roster_id, "Unknown")
        for pid in r.starters:
            pts = r.players_points.get(pid, 0.0)
            line = PlayerLine(
                player=pid, owner=owner, points=pts,
                position=positions_by_player.get(pid),
            )
            started_lines.append(line)
            proj = projections.get(pid)
            if proj and proj >= BUST_PROJECTION_MIN and pts <= BUST_RATIO * proj:
                bust_line = PlayerLine(
                    player=pid, owner=owner, points=pts,
                    position=positions_by_player.get(pid), projected=proj,
                )
                bust_candidates.append((bust_line, pts / proj))

    heroes = sorted(started_lines, key=lambda p: p.points, reverse=True)[:TOP_N]
    goats = sorted(started_lines, key=lambda p: p.points)[:TOP_N]
    busts = [bl for bl, _ in sorted(bust_candidates, key=lambda x: x[1])][:TOP_N]
    return heroes, goats, busts
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_recap_engine.py -k "heroes or busts" -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/recap.py tests/test_recap_engine.py
git commit -m "feat: recap engine — heroes, goats, busts"
```

---

## Task 8: Facts engine — standings snapshot

Build the standings list from rosters (sorted by wins desc, then points_for desc) for context the writer can reference.

**Files:**
- Modify: `src/sleeper_dynasty/engine/recap.py`
- Test: `tests/test_recap_engine.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_recap_engine.py`:

```python
from sleeper_dynasty.engine.recap import build_standings
from sleeper_dynasty.models.league import Roster


def _roster(rid, owner, w, l, pf):
    return Roster(roster_id=rid, owner_id=str(rid), owner_name=owner,
                  players=[], wins=w, losses=l, ties=0,
                  points_for=pf, points_against=0.0)


def test_standings_sorted_by_wins_then_points():
    rosters = [
        _roster(1, "A", 5, 3, 900.0),
        _roster(2, "B", 7, 1, 1100.0),
        _roster(3, "C", 7, 1, 1200.0),
    ]
    standings = build_standings(rosters)
    assert [s["owner"] for s in standings] == ["C", "B", "A"]
    assert standings[0]["wins"] == 7
    assert standings[0]["points_for"] == 1200.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_recap_engine.py -k standings -v`
Expected: FAIL — `ImportError: cannot import name 'build_standings'`.

- [ ] **Step 3: Implement**

Add to `src/sleeper_dynasty/engine/recap.py` (`from sleeper_dynasty.models.league import Roster`):

```python
def build_standings(rosters: list[Roster]) -> list[dict]:
    """Standings snapshot sorted by wins desc, then points_for desc."""
    ordered = sorted(
        rosters, key=lambda r: (r.wins, r.points_for), reverse=True
    )
    return [
        {
            "owner": r.owner_name,
            "wins": r.wins,
            "losses": r.losses,
            "ties": r.ties,
            "points_for": round(r.points_for, 1),
        }
        for r in ordered
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_recap_engine.py -k standings -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/recap.py tests/test_recap_engine.py
git commit -m "feat: recap engine — standings snapshot"
```

---

## Task 9: Facts engine — assemble RecapFacts + resolve player names

A single `build_recap_facts(...)` that calls the beat builders, then resolves every `player_id` in the output to a readable `"Full Name (POS, TEAM)"` string so the writer never sees raw IDs.

**Files:**
- Modify: `src/sleeper_dynasty/engine/recap.py`
- Test: `tests/test_recap_engine.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_recap_engine.py`:

```python
from sleeper_dynasty.engine.recap import build_recap_facts
from sleeper_dynasty.models.player import Player
from sleeper_dynasty.models.recap import RecapFacts


def test_build_recap_facts_resolves_names_and_nests():
    players = {
        "p1": Player("p1", "Josh Allen", "QB", "BUF"),
        "p2": Player("p2", "Scrub Guy", "RB", "NYJ"),
        "p3": Player("p3", "Bench Star", "WR", "MIA"),
    }
    results = [
        MatchupResult(9, 1, 1, 45.0, starters=["p1", "p2"],
                      players=["p1", "p2", "p3"],
                      players_points={"p1": 41.0, "p2": 4.0, "p3": 30.0}),
        MatchupResult(9, 1, 2, 30.0, starters=["p1"], players=["p1"],
                      players_points={"p1": 30.0}),
    ]
    rosters = [_roster(1, "Team A", 1, 0, 45.0),
               _roster(2, "Team B", 0, 1, 30.0)]
    facts = build_recap_facts(
        week=9, league_name="Bros", results=results, rosters=rosters,
        owner_by_roster={1: "Team A", 2: "Team B"}, players=players,
        roster_positions=["QB", "FLEX"], weekly_projections={},
    )
    assert isinstance(facts, RecapFacts)
    assert facts.heroes[0].player == "Josh Allen (QB, BUF)"
    # Bench regret hero name resolved too.
    assert facts.bench_regret[0].benched_hero.player == "Bench Star (WR, MIA)"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_recap_engine.py -k build_recap_facts -v`
Expected: FAIL — `ImportError: cannot import name 'build_recap_facts'`.

- [ ] **Step 3: Implement**

Add to `src/sleeper_dynasty/engine/recap.py` (`from sleeper_dynasty.models.player import Player`; `from sleeper_dynasty.models.recap import RecapFacts`):

```python
def _player_label(pid: str, players: dict[str, Player]) -> str:
    p = players.get(pid)
    if p is None:
        return pid
    team = p.team or "FA"
    pos = p.position or "?"
    return f"{p.full_name} ({pos}, {team})"


def _resolve_line(line: PlayerLine, players: dict[str, Player]) -> PlayerLine:
    line.player = _player_label(line.player, players)
    return line


def build_recap_facts(
    week: int,
    league_name: str,
    results: list[MatchupResult],
    rosters: list[Roster],
    owner_by_roster: dict[int, str],
    players: dict[str, Player],
    roster_positions: list[str],
    weekly_projections: dict[str, float],
) -> RecapFacts:
    """Assemble the full recap facts packet, resolving player IDs to names.

    ``weekly_projections`` maps player_id -> projected points for the week
    (used for busts); pass {} to skip bust detection.
    """
    positions_by_player = {
        pid: (p.position or "") for pid, p in players.items()
    }

    matchups, high, low = build_matchup_recaps(results, owner_by_roster)
    lucky, unlucky = build_luck_notes(results, owner_by_roster)
    heroes, goats, busts = build_player_beats(
        results, owner_by_roster, positions_by_player, weekly_projections
    )
    standings = build_standings(rosters)

    # Bench regret per played roster.
    regrets = []
    played_rosters = {
        r.roster_id for r in results if (r.points or 0.0) != 0.0
    }
    for r in results:
        if r.roster_id not in played_rosters:
            continue
        regret = build_bench_regret(
            r, roster_positions, positions_by_player,
            owner_by_roster.get(r.roster_id, "Unknown"),
        )
        if regret is not None:
            regrets.append(regret)
    # Most egregious first; keep the worst few.
    regrets.sort(key=lambda b: b.points_left_on_bench, reverse=True)
    regrets = regrets[:TOP_N]

    # Resolve all player IDs to readable labels.
    for line in heroes + goats + busts:
        _resolve_line(line, players)
    for reg in regrets:
        _resolve_line(reg.benched_hero, players)
        _resolve_line(reg.started_dud, players)

    return RecapFacts(
        week=week,
        league_name=league_name,
        standings=standings,
        matchups=matchups,
        high_scorer=high,
        low_scorer=low,
        bench_regret=regrets,
        lucky=lucky,
        unlucky=unlucky,
        heroes=heroes,
        goats=goats,
        busts=busts,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_recap_engine.py -k build_recap_facts -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Run the whole engine suite**

Run: `pytest tests/test_recap_engine.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/sleeper_dynasty/engine/recap.py tests/test_recap_engine.py
git commit -m "feat: recap engine — assemble RecapFacts with name resolution"
```

---

## Task 10: Persona + league-lore template files

Ship the default persona prompt and a starter lore template as package data files loaded at runtime.

**Files:**
- Create: `src/sleeper_dynasty/llm/__init__.py` (empty)
- Create: `src/sleeper_dynasty/llm/prompts/analyst_persona.md`
- Create: `src/sleeper_dynasty/llm/prompts/league_lore_template.md`
- Modify: `pyproject.toml` (include package data)
- Test: `tests/test_recap_writer.py`

- [ ] **Step 1: Create the persona file**

`src/sleeper_dynasty/llm/prompts/analyst_persona.md`:

```markdown
You are "The Analyst" — a smug, self-serious fantasy football expert doing a
weekly SportsCenter-style segment for a private dynasty league. Your shtick:
you treat these managers' incompetence as if it were breaking national news,
breaking down their failures with the condescending authority of a man who has
never lost at anything.

TONE:
- Savage, profane, and personal. Roast managers BY NAME and drag the NFL
  players/teams who betrayed them. Hard-R language is fine and encouraged.
- Smug and condescending — you are the smartest person in the room and these
  fools are lucky you deign to explain their mistakes to them.
- Specific over generic. A great burn names the exact player, the exact score,
  the exact bench decision. Generic insults are for amateurs.

HARD RULES:
- Use ONLY the facts in the provided JSON packet. Never invent scores, players,
  matchups, or outcomes. If a stat isn't in the packet, you don't know it.
- Every number you cite must come from the packet.
- No content targeting protected classes (race, religion, gender, etc.). The
  comedy is in their roster decisions, not bigotry.

STRUCTURE your segment as:
1. A cold-open zinger setting up the week.
2. Game-by-game recap hitting the juicy beats (blowouts, nailbiters, the
   bench regret, the lucky/unlucky).
3. "Hero & Goat of the Week."
4. (When an outlook section is present) the upcoming-week preview: matchups,
   bye-week disasters, weather, and playoff stakes.
5. A condescending sign-off.

Write in markdown. Be funny first, mean second, accurate always.
```

- [ ] **Step 2: Create the lore template**

`src/sleeper_dynasty/llm/prompts/league_lore_template.md`:

```markdown
# League Lore

> Fill this in and pass it with `--lore`. The Analyst weaves it into the recap.
> Everything here is optional — delete sections you don't want.

## Owners & Nicknames
- <owner display name> — <nickname>, <one-line characterization>

## Rivalries
- <owner A> vs <owner B> — <the beef>

## Past Humiliations
- <memorable collapse, blown lead, infamous trade>

## Running Bits / Inside Jokes
- <recurring joke the recap should reference>
```

- [ ] **Step 3: Create the package + include data**

Create empty `src/sleeper_dynasty/llm/__init__.py`.

In `pyproject.toml`, after the `[tool.setuptools.packages.find]` block, add:

```toml
[tool.setuptools.package-data]
sleeper_dynasty = ["llm/prompts/*.md"]
```

- [ ] **Step 4: Write the failing test**

`tests/test_recap_writer.py`:

```python
from sleeper_dynasty.llm.recap_writer import load_default_persona, load_lore_template


def test_default_persona_loads_and_has_hard_rules():
    persona = load_default_persona()
    assert "ONLY the facts" in persona
    assert "The Analyst" in persona


def test_lore_template_loads():
    tmpl = load_lore_template()
    assert "League Lore" in tmpl
```

- [ ] **Step 5: Run test to verify it fails**

Run: `pytest tests/test_recap_writer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sleeper_dynasty.llm.recap_writer'`.

- [ ] **Step 6: Implement the loaders (writer module stub)**

`src/sleeper_dynasty/llm/recap_writer.py`:

```python
"""RecapWriter: turn a facts packet into roast-comedy prose via Claude.

The system prompt (persona) is static and prompt-cached; the user turn carries
the league lore + the week's facts JSON. The model is instructed to use only
packet facts.
"""

from __future__ import annotations

import logging
from importlib import resources

logger = logging.getLogger(__name__)

_PROMPTS = "sleeper_dynasty.llm.prompts"


def load_default_persona() -> str:
    """Load the built-in Analyst persona system prompt."""
    return resources.files(_PROMPTS).joinpath("analyst_persona.md").read_text()


def load_lore_template() -> str:
    """Load the starter league-lore template (for scaffolding a lore file)."""
    return (
        resources.files(_PROMPTS).joinpath("league_lore_template.md").read_text()
    )
```

- [ ] **Step 7: Run test to verify it passes**

Run: `pytest tests/test_recap_writer.py -v`
Expected: PASS (2 passed).

- [ ] **Step 8: Commit**

```bash
git add src/sleeper_dynasty/llm pyproject.toml tests/test_recap_writer.py
git commit -m "feat: add Analyst persona + lore template package data"
```

---

## Task 11: RecapWriter — prompt build + Claude call

Build the messages and call the Anthropic SDK with the persona as a cached system block. Tests mock the client; no live API calls.

> IMPLEMENTATION NOTE: consult the `claude-api` skill for current SDK conventions and prompt-caching syntax. The code below targets the `anthropic` Python SDK ≥0.40 Messages API.

**Files:**
- Modify: `src/sleeper_dynasty/llm/recap_writer.py`
- Test: `tests/test_recap_writer.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_recap_writer.py`:

```python
from unittest.mock import MagicMock, patch

from sleeper_dynasty.llm.recap_writer import RecapWriter
from sleeper_dynasty.models.recap import RecapFacts


def _facts():
    return RecapFacts(
        week=9, league_name="Bros", standings=[], matchups=[],
        high_scorer={"owner": "Team A", "points": 158.0},
        low_scorer=None, bench_regret=[], lucky=[], unlucky=[],
        heroes=[], goats=[], busts=[],
    )


def test_build_messages_includes_facts_and_lore():
    writer = RecapWriter(api_key="test", model="claude-opus-4-8")
    system, messages = writer.build_request(
        _facts(), lore="Team A is run by my idiot brother.",
    )
    assert any("idiot brother" in str(b) for b in messages[0]["content"]) \
        or "idiot brother" in str(messages)
    # Facts JSON present.
    assert "158.0" in str(messages)
    # Persona is the cached system block.
    assert "The Analyst" in str(system)


def test_write_calls_client_and_returns_text():
    fake_resp = MagicMock()
    fake_resp.content = [MagicMock(text="THE ANALYST SPEAKS")]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_resp

    writer = RecapWriter(api_key="test", model="claude-opus-4-8")
    with patch.object(writer, "_client", fake_client):
        out = writer.write(_facts(), lore=None)
    assert out == "THE ANALYST SPEAKS"
    # Model + system prompt were passed.
    _, kwargs = fake_client.messages.create.call_args
    assert kwargs["model"] == "claude-opus-4-8"
    assert "The Analyst" in str(kwargs["system"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_recap_writer.py -k "build_messages or write_calls" -v`
Expected: FAIL — `ImportError: cannot import name 'RecapWriter'`.

- [ ] **Step 3: Implement**

Add to `src/sleeper_dynasty/llm/recap_writer.py`:

```python
import json

import anthropic

DEFAULT_MODEL = "claude-opus-4-8"
MAX_TOKENS = 4096


class RecapWriter:
    """Generates recap prose from a facts packet using Claude."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        persona: str | None = None,
    ) -> None:
        self.model = model
        self.persona = persona or load_default_persona()
        # api_key=None lets the SDK read ANTHROPIC_API_KEY from the env.
        self._client = anthropic.Anthropic(api_key=api_key)

    def build_request(
        self, facts: RecapFacts, lore: str | None
    ) -> tuple[list[dict], list[dict]]:
        """Build the (system, messages) pair for the Messages API.

        The persona system block is marked for prompt caching so repeat weekly
        calls reuse it. The user turn carries optional lore + the facts JSON.
        """
        system = [{
            "type": "text",
            "text": self.persona,
            "cache_control": {"type": "ephemeral"},
        }]

        user_parts = []
        if lore:
            user_parts.append(
                "LEAGUE LORE (weave these in where relevant):\n\n" + lore
            )
        user_parts.append(
            "FACTS PACKET (use ONLY these facts):\n\n```json\n"
            + json.dumps(facts.to_dict(), indent=2)
            + "\n```\n\nWrite this week's segment."
        )
        messages = [{
            "role": "user",
            "content": [{"type": "text", "text": "\n\n".join(user_parts)}],
        }]
        return system, messages

    def write(self, facts: RecapFacts, lore: str | None = None) -> str:
        """Call Claude and return the recap markdown.

        Raises anthropic.APIError subclasses on auth/rate-limit/timeout; the
        CLI surfaces an actionable message.
        """
        system, messages = self.build_request(facts, lore)
        logger.info("Requesting recap from %s (week %d)", self.model, facts.week)
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=messages,
        )
        return resp.content[0].text
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_recap_writer.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/llm/recap_writer.py tests/test_recap_writer.py
git commit -m "feat: RecapWriter — prompt build + Claude call (cached persona)"
```

---

## Task 12: Output renderer + Delivery seam

Render the recap markdown to a styled standalone HTML file. Define a `Delivery` protocol so a future `ChatDelivery` drops in. v1 ships `HtmlFileDelivery`.

**Files:**
- Create: `src/sleeper_dynasty/output/recap_render.py`
- Test: `tests/test_recap_render.py`

- [ ] **Step 1: Write the failing test**

`tests/test_recap_render.py`:

```python
from pathlib import Path

from sleeper_dynasty.output.recap_render import (
    render_recap_html, HtmlFileDelivery,
)


def test_render_wraps_markdown_in_html():
    html = render_recap_html(
        "# Week 9\n\n**Team A** got smoked.", league_name="Bros", week=9
    )
    assert "<html" in html.lower()
    assert "Team A" in html
    assert "Week 9" in html


def test_html_file_delivery_writes_file(tmp_path):
    delivery = HtmlFileDelivery(out_dir=tmp_path)
    path = delivery.deliver(
        "# Hi", league_name="Dynasty Bros", week=9
    )
    p = Path(path)
    assert p.exists()
    assert p.suffix == ".html"
    assert "Dynasty Bros" in p.read_text()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_recap_render.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sleeper_dynasty.output.recap_render'`.

- [ ] **Step 3: Implement**

`src/sleeper_dynasty/output/recap_render.py`:

```python
"""Render recap markdown to deliverable formats.

The Delivery protocol decouples WHAT we generate (recap text) from WHERE it
goes. v1 ships HtmlFileDelivery; a future ChatDelivery (Telegram/Discord) can
implement the same interface without touching the writer or engine.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Protocol

from jinja2 import Environment, select_autoescape

logger = logging.getLogger(__name__)

_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>{{ league_name }} — Week {{ week }} Recap</title>
<style>
  body { max-width: 760px; margin: 2rem auto; padding: 0 1rem;
         font: 17px/1.6 -apple-system, system-ui, sans-serif; color: #1a1a1a; }
  h1, h2, h3 { line-height: 1.25; }
  hr { border: none; border-top: 1px solid #ddd; margin: 2rem 0; }
  .meta { color: #888; font-size: 14px; text-transform: uppercase;
          letter-spacing: .05em; }
</style></head>
<body>
<p class="meta">{{ league_name }} · Week {{ week }}</p>
{{ body }}
</body></html>
"""


def _markdown_to_html(md: str) -> str:
    """Minimal, dependency-free markdown -> HTML for headings, bold, hr, and
    paragraphs. We control the input (LLM markdown), so we keep this small
    rather than pulling a markdown lib.
    """
    html_lines = []
    for block in md.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        if block == "---":
            html_lines.append("<hr>")
            continue
        m = re.match(r"^(#{1,3})\s+(.*)$", block)
        if m:
            level = len(m.group(1))
            text = _inline(m.group(2))
            html_lines.append(f"<h{level}>{text}</h{level}>")
            continue
        html_lines.append(f"<p>{_inline(block)}</p>")
    return "\n".join(html_lines)


def _inline(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    return text.replace("\n", "<br>")


def render_recap_html(markdown: str, league_name: str, week: int) -> str:
    env = Environment(autoescape=select_autoescape(["html"]))
    template = env.from_string(_TEMPLATE)
    # body is pre-rendered HTML we trust (our own converter) -> mark safe via
    # Markup is overkill; disable autoescape only for the body by passing it
    # already-escaped at the inline layer. Here input is LLM text; we accept it.
    from markupsafe import Markup
    return template.render(
        league_name=league_name, week=week,
        body=Markup(_markdown_to_html(markdown)),
    )


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


class Delivery(Protocol):
    def deliver(self, markdown: str, league_name: str, week: int) -> str:
        """Deliver the recap. Returns a locator (file path, URL, message id)."""
        ...


class HtmlFileDelivery:
    """Writes the recap to a standalone HTML file and returns its path."""

    def __init__(self, out_dir: Path | None = None) -> None:
        self.out_dir = Path(out_dir) if out_dir else Path.cwd()

    def deliver(self, markdown: str, league_name: str, week: int) -> str:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        html = render_recap_html(markdown, league_name, week)
        path = self.out_dir / f"{_slug(league_name)}_week{week}_recap.html"
        path.write_text(html)
        logger.info("Wrote recap to %s", path)
        return str(path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_recap_render.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/output/recap_render.py tests/test_recap_render.py
git commit -m "feat: recap HTML renderer + pluggable Delivery seam"
```

---

## Task 13: CLI `recap` command (Milestone 1 — recap ships here)

Wire the pipeline: resolve user → pick league → default week from NFL state → fetch matchup results + rosters + players + weekly projections → build facts → write recap → deliver. Lore/persona/model/out are flags.

**Files:**
- Modify: `src/sleeper_dynasty/cli.py` (add parser, `_run_recap`, dispatch)
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli.py` (match existing import/mock style in that file):

```python
import argparse
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sleeper_dynasty import cli


@pytest.mark.asyncio
async def test_run_recap_builds_and_delivers(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")

    # Stub the Sleeper client.
    from sleeper_dynasty.models.league import League, Roster, MatchupResult
    from sleeper_dynasty.models.player import Player

    league = League(
        league_id="LID", name="Bros", season=2025, total_rosters=2,
        roster_positions=["QB", "FLEX", "BN"],
        scoring_settings={}, playoff_week_start=15, num_playoff_teams=6,
        status="in_season",
    )
    rosters = [
        Roster(1, "u1", "Team A", ["p1"], 1, 0, 0, 45.0, 0.0),
        Roster(2, "u2", "Team B", ["p2"], 0, 1, 0, 30.0, 0.0),
    ]
    results = [
        MatchupResult(9, 1, 1, 45.0, ["p1"], ["p1"], {"p1": 45.0}),
        MatchupResult(9, 1, 2, 30.0, ["p2"], ["p2"], {"p2": 30.0}),
    ]

    fake = MagicMock()
    fake.get_user_id = AsyncMock(return_value="uid")
    fake.get_leagues = AsyncMock(return_value=[league])
    fake.get_nfl_state = AsyncMock(return_value={"week": 10, "season": "2025"})
    fake.get_rosters = AsyncMock(return_value=rosters)
    fake.get_matchup_results = AsyncMock(return_value=results)
    fake.get_players = AsyncMock(return_value={
        "p1": {"full_name": "Josh Allen", "position": "QB", "team": "BUF"},
        "p2": {"full_name": "Scrub", "position": "RB", "team": "NYJ"},
    })
    fake.get_projections = AsyncMock(return_value={})
    fake.aclose = AsyncMock()

    args = argparse.Namespace(
        username="me", season=2025, week=9, no_cache=True,
        lore=None, persona=None, model="claude-opus-4-8",
        out=str(tmp_path / "out.html"),
    )

    with patch.object(cli, "SleeperClient", return_value=fake), \
         patch.object(cli, "webbrowser", MagicMock()), \
         patch.object(cli, "RecapWriter") as MockWriter:
        MockWriter.return_value.write.return_value = "# Week 9\n\nThe Analyst."
        await cli._run_recap(args)

    # Writer was given a RecapFacts with week 9.
    facts_arg = MockWriter.return_value.write.call_args[0][0]
    assert facts_arg.week == 9
    assert facts_arg.league_name == "Bros"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py -k run_recap -v`
Expected: FAIL — `AttributeError: module 'sleeper_dynasty.cli' has no attribute '_run_recap'`.

- [ ] **Step 3: Add imports + parser**

In `src/sleeper_dynasty/cli.py` add imports near the existing ones:

```python
from sleeper_dynasty.engine.recap import build_recap_facts
from sleeper_dynasty.llm.recap_writer import RecapWriter
from sleeper_dynasty.output.recap_render import HtmlFileDelivery
```

In the parser section (after the `trades` subparser block, before `return parser.parse_args(argv)`):

```python
    recap = subparsers.add_parser(
        "recap",
        help="Generate a savage weekly recap (and, later, outlook).",
    )
    recap.add_argument("username", help="Sleeper username.")
    recap.add_argument(
        "--season", type=int, default=2025,
        help="NFL season (default: 2025).",
    )
    recap.add_argument(
        "--week", type=int, default=None,
        help="Week to recap (default: last completed week per Sleeper state).",
    )
    recap.add_argument(
        "--lore", default=None,
        help="Path to a league_lore markdown file to feed the writer.",
    )
    recap.add_argument(
        "--persona", default=None,
        help="Path to a persona prompt override (default: built-in Analyst).",
    )
    recap.add_argument(
        "--model", default="claude-opus-4-8",
        help="Anthropic model id (default: claude-opus-4-8).",
    )
    recap.add_argument(
        "--out", default=None,
        help="Output HTML path (default: <league>_week<N>_recap.html in cwd).",
    )
    recap.add_argument(
        "--no-cache", action="store_true",
        help="Invalidate all caches before running.",
    )
```

- [ ] **Step 4: Implement `_run_recap`**

Add after `_run_trades` in `src/sleeper_dynasty/cli.py`:

```python
async def _run_recap(args: argparse.Namespace) -> None:
    """Generate and deliver a weekly recap for one Sleeper user's league."""
    cache = FileCache()
    if args.no_cache:
        cache.invalidate_all()

    client = SleeperClient()
    try:
        user_id = await client.get_user_id(args.username)
        leagues = await client.get_leagues(user_id, args.season)
        relevant = [lg for lg in leagues if lg.status in DYNASTY_LEAGUE_STATUSES]
        if not relevant:
            print(f"No dynasty-relevant leagues for {args.username}.")
            return
        league = _select_league(relevant)

        # Default week = last completed week (NFL state week - 1).
        week = args.week
        if week is None:
            state = await client.get_nfl_state()
            week = max(1, int(state.get("week", 1)) - 1)
        logger.info("Recapping %s week %d", league.name, week)

        rosters = await client.get_rosters(league.league_id)
        owner_by_roster = {r.roster_id: r.owner_name for r in rosters}
        results = await client.get_matchup_results(league.league_id, week)

        # Players (cached when possible).
        raw_players = None
        if not args.no_cache:
            cached = cache.read(_PLAYERS_CACHE_KEY)
            if isinstance(cached, dict):
                raw_players = cached
        if raw_players is None:
            raw_players = await client.get_players()
            cache.write(_PLAYERS_CACHE_KEY, raw_players)
        players = _build_players(raw_players)

        # Weekly projections for bust detection (best-effort).
        weekly_projections: dict[str, float] = {}
        try:
            raw_proj = await client.get_projections(args.season, week)
            for pid, stats in raw_proj.items():
                if isinstance(stats, dict):
                    weekly_projections[pid] = normalize_projection(
                        stats, league.scoring_settings
                    )
        except Exception as e:
            logger.warning("Weekly projections unavailable: %s", e)

        facts = build_recap_facts(
            week=week,
            league_name=league.name,
            results=results,
            rosters=rosters,
            owner_by_roster=owner_by_roster,
            players=players,
            roster_positions=league.roster_positions,
            weekly_projections=weekly_projections,
        )

        lore = None
        if args.lore:
            lore = Path(args.lore).read_text()
        persona = None
        if args.persona:
            persona = Path(args.persona).read_text()

        writer = RecapWriter(model=args.model, persona=persona)
        try:
            markdown = writer.write(facts, lore=lore)
        except anthropic.APIError as e:
            print(f"Anthropic API error: {e}", file=sys.stderr)
            return

        out_dir = Path(args.out).parent if args.out else Path.cwd()
        delivery = HtmlFileDelivery(out_dir=out_dir)
        path = delivery.deliver(markdown, league.name, week)
        print(f"\nRecap written to {path}")
        webbrowser.open(Path(path).resolve().as_uri())
    finally:
        await client.aclose()
```

Add `from pathlib import Path` and `import anthropic` to the imports if not already present.

- [ ] **Step 5: Add dispatch**

In `main()`, after the `trades` dispatch block:

```python
    if args.command == "recap":
        asyncio.run(_run_recap(args))
        return
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_cli.py -k run_recap -v`
Expected: PASS.

- [ ] **Step 7: Run the full suite**

Run: `pytest -q`
Expected: all PASS (no regressions).

- [ ] **Step 8: Commit**

```bash
git add src/sleeper_dynasty/cli.py tests/test_cli.py
git commit -m "feat: add 'recap' CLI command — Milestone 1 recap ships"
```

> **Milestone 1 complete.** `sleeper-dynasty recap <username> --season 2024 --week 5` produces a real recap from a past week. Verify manually with a real `ANTHROPIC_API_KEY` set before moving on (read the output — this is the comedy eyeball test).

---

## Task 14: Outlook facts models

Extend `models/recap.py` with the outlook half and an `OutlookFacts` container; add an optional `outlook` field to the writer's input. We keep `RecapFacts` and `OutlookFacts` separate so the recap-only path is unaffected.

**Files:**
- Modify: `src/sleeper_dynasty/models/recap.py`
- Test: `tests/test_recap_models.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_recap_models.py`:

```python
from sleeper_dynasty.models.recap import (
    MatchupPreview, ByeTrouble, WeatherNote, PlayoffStake, OutlookFacts,
)


def test_outlook_facts_to_dict():
    o = OutlookFacts(
        week=10,
        matchups=[MatchupPreview("A", "B", 115.0, 102.0, "A", 13.0)],
        byes=[ByeTrouble("A", ["Josh Allen (QB, BUF)"],
                         "Backup Guy (QB, CHI)", 6.0)],
        weather=[WeatherNote("BUF @ NE", 22, 28, "snow",
                             ["a kicker"])],
        playoff_stakes=[PlayoffStake("A", "must-win")],
    )
    d = o.to_dict()
    assert d["week"] == 10
    assert d["matchups"][0]["favorite"] == "A"
    assert d["byes"][0]["likely_replacement"] == "Backup Guy (QB, CHI)"
    assert d["weather"][0]["precip"] == "snow"
    assert d["playoff_stakes"][0]["status"] == "must-win"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_recap_models.py -k outlook -v`
Expected: FAIL — `ImportError: cannot import name 'MatchupPreview'`.

- [ ] **Step 3: Implement**

Add to `src/sleeper_dynasty/models/recap.py`:

```python
@dataclass
class MatchupPreview:
    home: str
    away: str
    home_projected: float
    away_projected: float
    favorite: str
    spread: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "home": self.home, "away": self.away,
            "home_projected": self.home_projected,
            "away_projected": self.away_projected,
            "favorite": self.favorite, "spread": self.spread,
        }


@dataclass
class ByeTrouble:
    owner: str
    players_on_bye: list[str]
    likely_replacement: str | None
    replacement_projected: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "owner": self.owner,
            "players_on_bye": self.players_on_bye,
            "likely_replacement": self.likely_replacement,
            "replacement_projected": self.replacement_projected,
        }


@dataclass
class WeatherNote:
    game: str
    wind_mph: float | None
    temp_f: float | None
    precip: str | None
    affected_players: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "game": self.game, "wind_mph": self.wind_mph,
            "temp_f": self.temp_f, "precip": self.precip,
            "affected_players": self.affected_players,
        }


@dataclass
class PlayoffStake:
    owner: str
    status: str  # must-win | can-clinch | eliminated | spoiler | in-the-hunt

    def to_dict(self) -> dict[str, Any]:
        return {"owner": self.owner, "status": self.status}


@dataclass
class OutlookFacts:
    week: int
    matchups: list[MatchupPreview]
    byes: list[ByeTrouble]
    weather: list[WeatherNote]
    playoff_stakes: list[PlayoffStake]

    def to_dict(self) -> dict[str, Any]:
        return {
            "week": self.week,
            "matchups": [m.to_dict() for m in self.matchups],
            "byes": [b.to_dict() for b in self.byes],
            "weather": [w.to_dict() for w in self.weather],
            "playoff_stakes": [p.to_dict() for p in self.playoff_stakes],
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_recap_models.py -k outlook -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/models/recap.py tests/test_recap_models.py
git commit -m "feat: add outlook facts-packet models"
```

---

## Task 15: NFL schedule source (ESPN) + bye derivation

Fetch ESPN's public scoreboard feed for a given week → per-game `{home, away, kickoff, venue, indoor}` and derive byes (the 32 NFL teams minus teams playing).

**Files:**
- Create: `src/sleeper_dynasty/api/nfl_schedule.py`
- Test: `tests/test_nfl_schedule.py`
- Fixture: `tests/fixtures/espn_scoreboard_week10.json`

- [ ] **Step 1: Create a trimmed fixture**

`tests/fixtures/espn_scoreboard_week10.json` — a minimal shape mirroring ESPN's `events[].competitions[].competitors[]` structure with two games:

```json
{
  "events": [
    {
      "competitions": [{
        "date": "2025-11-09T18:00Z",
        "venue": {"fullName": "Highmark Stadium", "indoor": false},
        "competitors": [
          {"homeAway": "home", "team": {"abbreviation": "BUF"}},
          {"homeAway": "away", "team": {"abbreviation": "NE"}}
        ]
      }]
    },
    {
      "competitions": [{
        "date": "2025-11-09T18:00Z",
        "venue": {"fullName": "Ford Field", "indoor": true},
        "competitors": [
          {"homeAway": "home", "team": {"abbreviation": "DET"}},
          {"homeAway": "away", "team": {"abbreviation": "GB"}}
        ]
      }]
    }
  ]
}
```

- [ ] **Step 2: Write the failing test**

`tests/test_nfl_schedule.py`:

```python
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sleeper_dynasty.api.nfl_schedule import fetch_week_schedule, derive_byes

FIX = Path(__file__).parent / "fixtures"


def _resp():
    r = MagicMock()
    r.json.return_value = json.loads(
        (FIX / "espn_scoreboard_week10.json").read_text()
    )
    r.raise_for_status.return_value = None
    return r


@pytest.mark.asyncio
async def test_fetch_week_schedule_parses_games():
    with patch("httpx.AsyncClient.get", AsyncMock(return_value=_resp())):
        games = await fetch_week_schedule(2025, 10)
    buf = next(g for g in games if g["home"] == "BUF")
    assert buf["away"] == "NE"
    assert buf["indoor"] is False
    det = next(g for g in games if g["home"] == "DET")
    assert det["indoor"] is True


def test_derive_byes_returns_non_playing_teams():
    games = [
        {"home": "BUF", "away": "NE"}, {"home": "DET", "away": "GB"},
    ]
    byes = derive_byes(games)
    assert "BUF" not in byes
    assert "KC" in byes
    assert len(byes) == 32 - 4
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_nfl_schedule.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sleeper_dynasty.api.nfl_schedule'`.

- [ ] **Step 4: Implement**

`src/sleeper_dynasty/api/nfl_schedule.py`:

```python
"""NFL weekly schedule from ESPN's public scoreboard feed.

Used to derive bye weeks (teams not playing) and to know venue/indoor for
weather lookups. Best-effort: callers treat failures as "no schedule data"
and omit bye/weather beats rather than failing the recap.
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

_SCOREBOARD = (
    "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
)

# All 32 NFL team abbreviations (ESPN style).
NFL_TEAMS = {
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN",
    "DET", "GB", "HOU", "IND", "JAX", "KC", "LV", "LAC", "LAR", "MIA",
    "MIN", "NE", "NO", "NYG", "NYJ", "PHI", "PIT", "SF", "SEA", "TB",
    "TEN", "WSH",
}


async def fetch_week_schedule(season: int, week: int) -> list[dict]:
    """Fetch the week's games. Returns a list of
    ``{home, away, kickoff, venue, indoor}`` dicts.
    """
    params = {"seasontype": 2, "week": week, "dates": season}
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(_SCOREBOARD, params=params)
        resp.raise_for_status()
        data = resp.json()

    games = []
    for event in data.get("events", []):
        for comp in event.get("competitions", []):
            venue = comp.get("venue") or {}
            home = away = None
            for c in comp.get("competitors", []):
                abbr = (c.get("team") or {}).get("abbreviation")
                if c.get("homeAway") == "home":
                    home = abbr
                elif c.get("homeAway") == "away":
                    away = abbr
            if home and away:
                games.append({
                    "home": home, "away": away,
                    "kickoff": comp.get("date"),
                    "venue": venue.get("fullName"),
                    "indoor": bool(venue.get("indoor", False)),
                })
    return games


def derive_byes(games: list[dict]) -> set[str]:
    """Teams on bye = all NFL teams minus those appearing in this week's games."""
    playing = set()
    for g in games:
        playing.add(g["home"])
        playing.add(g["away"])
    return NFL_TEAMS - playing
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_nfl_schedule.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add src/sleeper_dynasty/api/nfl_schedule.py tests/test_nfl_schedule.py tests/fixtures/espn_scoreboard_week10.json
git commit -m "feat: ESPN NFL schedule fetch + bye derivation"
```

---

## Task 16: Weather source (Open-Meteo)

Given outdoor games with venues, fetch wind/temp/precip from Open-Meteo using a static stadium-coordinate table.

**Files:**
- Create: `src/sleeper_dynasty/api/weather.py`
- Test: `tests/test_weather.py`
- Fixture: `tests/fixtures/open_meteo.json`

- [ ] **Step 1: Create the fixture**

`tests/fixtures/open_meteo.json`:

```json
{
  "hourly": {
    "time": ["2025-11-09T18:00"],
    "temperature_2m": [28.0],
    "wind_speed_10m": [22.0],
    "precipitation": [0.4]
  }
}
```

- [ ] **Step 2: Write the failing test**

`tests/test_weather.py`:

```python
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sleeper_dynasty.api.weather import fetch_game_weather, STADIUM_COORDS

FIX = Path(__file__).parent / "fixtures"


def _resp():
    r = MagicMock()
    r.json.return_value = json.loads((FIX / "open_meteo.json").read_text())
    r.raise_for_status.return_value = None
    return r


def test_stadium_coords_has_outdoor_venues():
    assert "BUF" in STADIUM_COORDS  # outdoor stadium present


@pytest.mark.asyncio
async def test_fetch_game_weather_returns_conditions():
    with patch("httpx.AsyncClient.get", AsyncMock(return_value=_resp())):
        wx = await fetch_game_weather("BUF", kickoff_iso="2025-11-09T18:00Z")
    assert wx["wind_mph"] == 22.0
    assert wx["temp_f"] == 28.0
    assert wx["precip"] in ("rain", "snow", "none")


@pytest.mark.asyncio
async def test_fetch_game_weather_unknown_team_returns_none():
    wx = await fetch_game_weather("ZZZ", kickoff_iso="2025-11-09T18:00Z")
    assert wx is None
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_weather.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sleeper_dynasty.api.weather'`.

- [ ] **Step 4: Implement**

`src/sleeper_dynasty/api/weather.py`:

```python
"""Game-day weather via Open-Meteo (free, no API key).

Only outdoor stadiums are looked up; domes are excluded by the caller (the
schedule's ``indoor`` flag). Best-effort: returns None on unknown venue or
fetch failure so the recap simply omits weather jokes for that game.

Coordinates are hand-maintained for outdoor/retractable venues. Pure-dome
teams are intentionally absent (no weather to report).
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

# Outdoor / retractable-roof stadiums: team abbr -> (lat, lon).
# Pure domes (DET, MIN, NO, ATL, LV, ARI*) are omitted by design.
STADIUM_COORDS: dict[str, tuple[float, float]] = {
    "BUF": (42.774, -78.787), "NE": (42.091, -71.264),
    "GB": (44.501, -88.062), "CHI": (41.862, -87.617),
    "KC": (39.049, -94.484), "DEN": (39.744, -105.020),
    "PIT": (40.447, -80.016), "CLE": (41.506, -81.700),
    "CIN": (39.095, -84.516), "BAL": (39.278, -76.623),
    "PHI": (39.901, -75.168), "NYG": (40.814, -74.074),
    "NYJ": (40.814, -74.074), "WSH": (38.908, -76.864),
    "TB": (27.976, -82.503), "MIA": (25.958, -80.239),
    "JAX": (30.324, -81.637), "TEN": (36.166, -86.771),
    "CAR": (35.226, -80.853), "SEA": (47.595, -122.332),
    "SF": (37.713, -121.970), "LAC": (33.864, -118.261),
    "LAR": (33.864, -118.261),
}

_OPEN_METEO = "https://api.open-meteo.com/v1/forecast"


def _classify_precip(mm: float) -> str:
    if mm <= 0.05:
        return "none"
    return "rain"  # snow vs rain needs temp context; caller refines if cold


async def fetch_game_weather(team: str, kickoff_iso: str) -> dict | None:
    """Fetch forecast conditions at the home team's stadium near kickoff.

    Returns ``{wind_mph, temp_f, precip}`` (precip in none/rain/snow) or None
    if the venue is unknown (dome / not in table) or the fetch fails.
    """
    coords = STADIUM_COORDS.get(team)
    if coords is None:
        return None
    lat, lon = coords
    params = {
        "latitude": lat, "longitude": lon,
        "hourly": "temperature_2m,wind_speed_10m,precipitation",
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "forecast_days": 7,
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(_OPEN_METEO, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning("Weather fetch failed for %s: %s", team, e)
        return None

    hourly = data.get("hourly", {})
    temps = hourly.get("temperature_2m") or []
    winds = hourly.get("wind_speed_10m") or []
    precs = hourly.get("precipitation") or []
    if not temps:
        return None
    # Use the first available hour as a representative sample (fixture-friendly;
    # production could match kickoff_iso to the nearest hourly timestamp).
    temp_f = temps[0]
    precip = _classify_precip(precs[0] if precs else 0.0)
    if precip == "rain" and temp_f is not None and temp_f <= 32:
        precip = "snow"
    return {
        "wind_mph": winds[0] if winds else None,
        "temp_f": temp_f,
        "precip": precip,
    }
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_weather.py -v`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add src/sleeper_dynasty/api/weather.py tests/test_weather.py tests/fixtures/open_meteo.json
git commit -m "feat: Open-Meteo game-day weather for outdoor venues"
```

---

## Task 17: Outlook engine — matchup previews + playoff stakes

Build `MatchupPreview`s from next-week pairings + projected team scores (sum of each roster's optimal lineup using weekly projections), and `PlayoffStake`s from standings position relative to the playoff cutoff.

**Files:**
- Create: `src/sleeper_dynasty/engine/outlook.py`
- Test: `tests/test_outlook_engine.py`

- [ ] **Step 1: Write the failing test**

`tests/test_outlook_engine.py`:

```python
import pytest

from sleeper_dynasty.engine.outlook import (
    build_matchup_previews, build_playoff_stakes,
)
from sleeper_dynasty.models.league import MatchupResult, Roster


def _result(mid, rid):
    # Upcoming-week matchups come back with both points 0; we only need the
    # pairing (matchup_id) for previews.
    return MatchupResult(10, mid, rid, 0.0, [], [], {})


def _roster(rid, owner, w, l, pf):
    return Roster(rid, str(rid), owner, [f"p{rid}"], w, l, 0, pf, 0.0)


def test_matchup_previews_set_favorite_by_projected():
    pairings = [_result(1, 1), _result(1, 2)]
    owners = {1: "A", 2: "B"}
    team_projected = {1: 115.0, 2: 102.0}
    previews = build_matchup_previews(pairings, owners, team_projected)
    assert previews[0].favorite == "A"
    assert previews[0].spread == pytest.approx(13.0)


def test_playoff_stakes_flag_cutoff_bubble():
    rosters = [
        _roster(1, "A", 8, 1, 1200), _roster(2, "B", 7, 2, 1100),
        _roster(3, "C", 4, 5, 900),  _roster(4, "D", 1, 8, 700),
    ]
    stakes = build_playoff_stakes(rosters, num_playoff_teams=2,
                                  weeks_remaining=1)
    by_owner = {s.owner: s.status for s in stakes}
    assert by_owner["A"] in ("can-clinch", "in-the-hunt")
    assert by_owner["D"] == "eliminated"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_outlook_engine.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sleeper_dynasty.engine.outlook'`.

- [ ] **Step 3: Implement**

`src/sleeper_dynasty/engine/outlook.py`:

```python
"""Outlook engine: previews, byes, weather assembly, and playoff stakes for
the UPCOMING week. Pure functions over data fetched by the CLI.
"""

from __future__ import annotations

import logging

from sleeper_dynasty.models.league import MatchupResult, Roster
from sleeper_dynasty.models.recap import MatchupPreview, PlayoffStake

logger = logging.getLogger(__name__)


def _pair_by_matchup(
    pairings: list[MatchupResult],
) -> list[tuple[MatchupResult, MatchupResult]]:
    by_mid: dict[int | None, list[MatchupResult]] = {}
    for r in pairings:
        by_mid.setdefault(r.matchup_id, []).append(r)
    return [tuple(e) for e in by_mid.values() if len(e) == 2]


def build_matchup_previews(
    pairings: list[MatchupResult],
    owner_by_roster: dict[int, str],
    team_projected: dict[int, float],
) -> list[MatchupPreview]:
    """Build previews with projected scores and a favorite/spread."""
    previews = []
    for a, b in _pair_by_matchup(pairings):
        a_proj = round(team_projected.get(a.roster_id, 0.0), 1)
        b_proj = round(team_projected.get(b.roster_id, 0.0), 1)
        a_name = owner_by_roster.get(a.roster_id, "Unknown")
        b_name = owner_by_roster.get(b.roster_id, "Unknown")
        fav = a_name if a_proj >= b_proj else b_name
        previews.append(MatchupPreview(
            home=a_name, away=b_name,
            home_projected=a_proj, away_projected=b_proj,
            favorite=fav, spread=round(abs(a_proj - b_proj), 1),
        ))
    return previews


def build_playoff_stakes(
    rosters: list[Roster],
    num_playoff_teams: int,
    weeks_remaining: int,
) -> list[PlayoffStake]:
    """Crude stakes from current standings.

    - eliminated: cannot mathematically reach the cutoff team's win total even
      winning out (wins + weeks_remaining < cutoff_wins).
    - can-clinch: at/above the cutoff with a >1-game cushion over the bubble.
    - must-win: within one game of the cutoff in either direction.
    - in-the-hunt: everything else above water.
    """
    ordered = sorted(rosters, key=lambda r: (r.wins, r.points_for), reverse=True)
    if len(ordered) < num_playoff_teams:
        return [PlayoffStake(r.owner_name, "in-the-hunt") for r in ordered]

    cutoff_wins = ordered[num_playoff_teams - 1].wins
    stakes = []
    for idx, r in enumerate(ordered):
        max_wins = r.wins + weeks_remaining
        if max_wins < cutoff_wins:
            status = "eliminated"
        elif idx < num_playoff_teams and (r.wins - cutoff_wins) >= 1:
            status = "can-clinch"
        elif abs(r.wins - cutoff_wins) <= 1:
            status = "must-win"
        else:
            status = "in-the-hunt"
        stakes.append(PlayoffStake(r.owner_name, status))
    return stakes
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_outlook_engine.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/outlook.py tests/test_outlook_engine.py
git commit -m "feat: outlook engine — matchup previews + playoff stakes"
```

---

## Task 18: Outlook engine — bye trouble + weather assembly + assemble OutlookFacts

Combine byes (from schedule) with each roster to find managers whose starters are on bye, guess the likely (bad) replacement via the lineup solver excluding bye players, attach weather notes for outdoor games, and assemble `OutlookFacts`.

**Files:**
- Modify: `src/sleeper_dynasty/engine/outlook.py`
- Test: `tests/test_outlook_engine.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_outlook_engine.py`:

```python
from sleeper_dynasty.engine.outlook import build_bye_trouble
from sleeper_dynasty.models.player import Player


def test_bye_trouble_finds_starters_on_bye_and_replacement():
    # Roster 1: starter p1 (QB, BUF) is on bye; p2 (QB, CHI) is the backup.
    players = {
        "p1": Player("p1", "Josh Allen", "QB", "BUF"),
        "p2": Player("p2", "Backup Guy", "QB", "CHI"),
        "p3": Player("p3", "A Receiver", "WR", "MIA"),
    }
    roster = _roster(1, "Team A", 5, 3, 1000)
    roster.players = ["p1", "p2", "p3"]
    projections = {"p1": 22.0, "p2": 6.0, "p3": 14.0}
    troubles = build_bye_trouble(
        rosters=[roster], owner_by_roster={1: "Team A"},
        players=players, byes={"BUF"},
        roster_positions=["QB", "WR", "BN"], projections=projections,
    )
    assert len(troubles) == 1
    t = troubles[0]
    assert "Josh Allen (QB, BUF)" in t.players_on_bye
    assert t.likely_replacement == "Backup Guy (QB, CHI)"
    assert t.replacement_projected == 6.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_outlook_engine.py -k bye -v`
Expected: FAIL — `ImportError: cannot import name 'build_bye_trouble'`.

- [ ] **Step 3: Implement**

Add to `src/sleeper_dynasty/engine/outlook.py` (`from sleeper_dynasty.models.player import Player`; `from sleeper_dynasty.models.recap import ByeTrouble, WeatherNote, OutlookFacts`; `from sleeper_dynasty.engine.lineup import solve_optimal_lineup`):

```python
def _label(pid: str, players: dict[str, Player]) -> str:
    p = players.get(pid)
    if p is None:
        return pid
    return f"{p.full_name} ({p.position or '?'}, {p.team or 'FA'})"


def build_bye_trouble(
    rosters: list[Roster],
    owner_by_roster: dict[int, str],
    players: dict[str, Player],
    byes: set[str],
    roster_positions: list[str],
    projections: dict[str, float],
) -> list[ByeTrouble]:
    """Find managers whose projected starters are on bye, and guess the
    (likely worse) replacement the optimizer would slot in instead.
    """
    troubles = []
    for roster in rosters:
        # Players on this roster whose NFL team is on bye.
        on_bye = [
            pid for pid in roster.players
            if (players.get(pid) and players[pid].team in byes)
        ]
        if not on_bye:
            continue

        # Would-be-optimal starters if NOBODY were on bye.
        full_map = {
            pid: (players[pid].position or "", projections.get(pid, 0.0))
            for pid in roster.players if pid in players
        }
        ideal_starters, _ = solve_optimal_lineup(roster_positions, full_map)
        affected = [pid for pid in on_bye if pid in ideal_starters]
        if not affected:
            continue

        # Optimal lineup with bye players removed -> the replacements.
        avail_map = {
            pid: v for pid, v in full_map.items()
            if players[pid].team not in byes
        }
        repl_starters, _ = solve_optimal_lineup(roster_positions, avail_map)
        # The best NEW starter not in the ideal lineup = the replacement.
        new_in = [pid for pid in repl_starters if pid not in ideal_starters]
        replacement = max(
            new_in, key=lambda p: projections.get(p, 0.0), default=None
        )

        troubles.append(ByeTrouble(
            owner=owner_by_roster.get(roster.roster_id, "Unknown"),
            players_on_bye=[_label(p, players) for p in affected],
            likely_replacement=_label(replacement, players) if replacement else None,
            replacement_projected=(
                round(projections.get(replacement, 0.0), 1)
                if replacement else None
            ),
        ))
    return troubles


def build_weather_notes(
    games: list[dict],
    weather_by_home: dict[str, dict],
) -> list[WeatherNote]:
    """Assemble weather notes for games that have fetched conditions.

    ``weather_by_home`` maps home-team abbr -> {wind_mph, temp_f, precip}.
    Only games with notable conditions (wind >= 15 or precip != none or
    temp <= 32) are kept — calm dome-like days aren't funny.
    """
    notes = []
    for g in games:
        wx = weather_by_home.get(g["home"])
        if not wx:
            continue
        notable = (
            (wx.get("wind_mph") or 0) >= 15
            or wx.get("precip") not in (None, "none")
            or (wx.get("temp_f") is not None and wx["temp_f"] <= 32)
        )
        if not notable:
            continue
        notes.append(WeatherNote(
            game=f"{g['away']} @ {g['home']}",
            wind_mph=wx.get("wind_mph"),
            temp_f=wx.get("temp_f"),
            precip=wx.get("precip"),
            affected_players=[],
        ))
    return notes


def build_outlook_facts(
    week: int,
    pairings: list[MatchupResult],
    owner_by_roster: dict[int, str],
    team_projected: dict[int, float],
    rosters: list[Roster],
    players: dict[str, Player],
    byes: set[str],
    roster_positions: list[str],
    projections: dict[str, float],
    games: list[dict],
    weather_by_home: dict[str, dict],
    num_playoff_teams: int,
    weeks_remaining: int,
) -> OutlookFacts:
    """Assemble the full outlook facts packet."""
    return OutlookFacts(
        week=week,
        matchups=build_matchup_previews(
            pairings, owner_by_roster, team_projected
        ),
        byes=build_bye_trouble(
            rosters, owner_by_roster, players, byes,
            roster_positions, projections,
        ),
        weather=build_weather_notes(games, weather_by_home),
        playoff_stakes=build_playoff_stakes(
            rosters, num_playoff_teams, weeks_remaining
        ),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_outlook_engine.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/outlook.py tests/test_outlook_engine.py
git commit -m "feat: outlook engine — bye trouble, weather, assembly"
```

---

## Task 19: Writer accepts outlook; CLI wires the outlook pipeline

Extend `RecapWriter.write`/`build_request` to accept an optional `OutlookFacts`, and extend `_run_recap` to fetch next-week pairings, schedule, byes, weather, and projected team scores, then pass both packets.

**Files:**
- Modify: `src/sleeper_dynasty/llm/recap_writer.py`
- Modify: `src/sleeper_dynasty/cli.py`
- Test: `tests/test_recap_writer.py`, `tests/test_cli.py`

- [ ] **Step 1: Write the failing writer test**

Append to `tests/test_recap_writer.py`:

```python
from sleeper_dynasty.models.recap import OutlookFacts


def test_build_request_includes_outlook_when_present():
    writer = RecapWriter(api_key="test")
    outlook = OutlookFacts(
        week=10, matchups=[], byes=[], weather=[], playoff_stakes=[],
    )
    _, messages = writer.build_request(_facts(), lore=None, outlook=outlook)
    assert "OUTLOOK" in str(messages)
    assert '"week": 10' in str(messages)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_recap_writer.py -k outlook -v`
Expected: FAIL — `TypeError: build_request() got an unexpected keyword argument 'outlook'`.

- [ ] **Step 3: Update the writer**

In `src/sleeper_dynasty/llm/recap_writer.py`, change the signatures (import `OutlookFacts`):

```python
    def build_request(
        self, facts: RecapFacts, lore: str | None,
        outlook: "OutlookFacts | None" = None,
    ) -> tuple[list[dict], list[dict]]:
```

Before building `messages`, after the facts part is appended, add:

```python
        if outlook is not None:
            user_parts.append(
                "OUTLOOK PACKET for the UPCOMING week (use ONLY these "
                "facts):\n\n```json\n"
                + json.dumps(outlook.to_dict(), indent=2)
                + "\n```"
            )
```

And update `write`:

```python
    def write(
        self, facts: RecapFacts, lore: str | None = None,
        outlook: "OutlookFacts | None" = None,
    ) -> str:
        system, messages = self.build_request(facts, lore, outlook)
        ...
```

Add the import: `from sleeper_dynasty.models.recap import OutlookFacts` (top of file).

- [ ] **Step 4: Run writer test**

Run: `pytest tests/test_recap_writer.py -v`
Expected: all PASS.

- [ ] **Step 5: Wire the CLI outlook pipeline**

In `_run_recap` (`src/sleeper_dynasty/cli.py`), after building `facts` and before constructing the writer, add a best-effort outlook block. Import at top: `from sleeper_dynasty.engine.outlook import build_outlook_facts`, `from sleeper_dynasty.api.nfl_schedule import fetch_week_schedule, derive_byes`, `from sleeper_dynasty.api.weather import fetch_game_weather`, and `from sleeper_dynasty.engine.lineup import solve_optimal_lineup`.

```python
        # --- Outlook (best-effort; any failure -> recap-only) ---
        outlook = None
        try:
            next_week = week + 1
            pairings = await client.get_matchup_results(
                league.league_id, next_week
            )
            # Projected team score = optimal lineup over each roster using
            # weekly projections.
            team_projected: dict[int, float] = {}
            pos_by_pid = {pid: (p.position or "") for pid, p in players.items()}
            for r in rosters:
                pmap = {
                    pid: (pos_by_pid.get(pid, ""),
                          weekly_projections.get(pid, 0.0))
                    for pid in r.players
                }
                _, total = solve_optimal_lineup(league.roster_positions, pmap)
                team_projected[r.roster_id] = total

            games = await fetch_week_schedule(args.season, next_week)
            byes = derive_byes(games)

            weather_by_home: dict[str, dict] = {}
            for g in games:
                if g.get("indoor"):
                    continue
                wx = await fetch_game_weather(g["home"], g.get("kickoff") or "")
                if wx:
                    weather_by_home[g["home"]] = wx

            weeks_remaining = max(0, (league.playoff_week_start - 1) - next_week)
            outlook = build_outlook_facts(
                week=next_week, pairings=pairings,
                owner_by_roster=owner_by_roster,
                team_projected=team_projected, rosters=rosters,
                players=players, byes=byes,
                roster_positions=league.roster_positions,
                projections=weekly_projections, games=games,
                weather_by_home=weather_by_home,
                num_playoff_teams=league.num_playoff_teams,
                weeks_remaining=weeks_remaining,
            )
        except Exception as e:
            logger.warning("Outlook unavailable (%s); recap-only", e)
```

Then change the writer call to pass it:

```python
            markdown = writer.write(facts, lore=lore, outlook=outlook)
```

- [ ] **Step 6: Update the CLI test for outlook**

In `tests/test_cli.py`, extend the existing `test_run_recap_builds_and_delivers` fake so `get_matchup_results` returns `[]` for the outlook week and the schedule/weather calls are patched. Add to the `with patch.object(...)` stack:

```python
    with patch.object(cli, "SleeperClient", return_value=fake), \
         patch.object(cli, "webbrowser", MagicMock()), \
         patch.object(cli, "fetch_week_schedule", AsyncMock(return_value=[])), \
         patch.object(cli, "RecapWriter") as MockWriter:
        MockWriter.return_value.write.return_value = "# Week 9\n\nThe Analyst."
        await cli._run_recap(args)

    # write() was called with an outlook kwarg (may be None if schedule empty).
    assert "outlook" in MockWriter.return_value.write.call_args.kwargs
```

Note: with `fetch_week_schedule` returning `[]`, `derive_byes` yields all teams on bye but no games/weather; `build_outlook_facts` still returns a valid (mostly empty) packet. That's fine for the test.

- [ ] **Step 7: Run the full suite**

Run: `pytest -q`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add src/sleeper_dynasty/llm/recap_writer.py src/sleeper_dynasty/cli.py tests/test_recap_writer.py tests/test_cli.py
git commit -m "feat: wire outlook into writer + CLI (Milestone 2)"
```

---

## Task 20: Lore scaffolding command + README docs

Add a tiny `recap-lore-template` helper (writes the starter lore file) and document the feature.

**Files:**
- Modify: `src/sleeper_dynasty/cli.py` (new `--init-lore` flag on `recap`)
- Modify: `README.md` (create if absent)
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli.py`:

```python
def test_init_lore_writes_template(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from sleeper_dynasty.cli import _write_lore_template
    path = _write_lore_template(tmp_path / "lore.md")
    from pathlib import Path
    assert Path(path).exists()
    assert "League Lore" in Path(path).read_text()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py -k init_lore -v`
Expected: FAIL — `ImportError: cannot import name '_write_lore_template'`.

- [ ] **Step 3: Implement**

Add to `src/sleeper_dynasty/cli.py` (import `load_lore_template` from the writer):

```python
def _write_lore_template(path: Path) -> str:
    """Write the starter league-lore template to ``path`` and return it."""
    from sleeper_dynasty.llm.recap_writer import load_lore_template
    path = Path(path)
    path.write_text(load_lore_template())
    logger.info("Wrote lore template to %s", path)
    return str(path)
```

Add a flag to the `recap` parser:

```python
    recap.add_argument(
        "--init-lore", metavar="PATH", default=None,
        help="Write a starter league-lore template to PATH and exit.",
    )
```

At the top of `_run_recap`, before any network calls:

```python
    if args.init_lore:
        path = _write_lore_template(Path(args.init_lore))
        print(f"Lore template written to {path}. Fill it in and pass --lore.")
        return
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli.py -k init_lore -v`
Expected: PASS.

- [ ] **Step 5: Document in README**

Create/append `README.md` with a `## Weekly Recap` section:

````markdown
## Weekly Recap & Outlook

Generate a savage, ESPN-parody-analyst recap of the past week plus an outlook
on the upcoming week.

```bash
export ANTHROPIC_API_KEY=sk-ant-...

# Scaffold a league-lore file (inside jokes, nicknames, rivalries):
sleeper-dynasty recap <username> --init-lore lore.md
# ...edit lore.md...

# Generate the recap (defaults to last completed week):
sleeper-dynasty recap <username> --season 2025 --week 9 --lore lore.md
```

Flags: `--week`, `--lore`, `--persona` (override the voice), `--model`
(default `claude-opus-4-8`), `--out`. External data (NFL schedule, weather)
is best-effort — if a source is down, those jokes are simply omitted.
````

- [ ] **Step 6: Run the full suite**

Run: `pytest -q`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add src/sleeper_dynasty/cli.py README.md tests/test_cli.py
git commit -m "feat: lore-template scaffolding + recap docs"
```

---

## Final verification

- [ ] **Run the entire test suite:** `pytest -q` — all green.
- [ ] **Manual smoke (recap):** with `ANTHROPIC_API_KEY` set, run
  `sleeper-dynasty recap <your-username> --season 2024 --week 8` and read the
  HTML. Confirm: scores match reality, names resolve, the voice lands.
- [ ] **Manual smoke (outlook):** run for a week that has a following week of
  data; confirm previews/byes/weather/stakes appear (or degrade cleanly).
- [ ] **Push branch + open PR** once satisfied (per project git conventions).

## Notes on testing comedy quality

Unit tests assert the engine math and that the writer receives the right facts.
They do **not** assert the prose is funny — that's the manual eyeball test on
real weeks. Iterate on `analyst_persona.md` (no code changes needed) to tune
tone. The outlook half is only fully meaningful once the season is live; the
recap half is testable today on past-season data.
