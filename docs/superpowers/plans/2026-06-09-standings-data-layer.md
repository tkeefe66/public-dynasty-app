# Standings Data Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reconstruct and persist per-week regular-season standings for an entire league chain, and surface each side's as-of-trade standing on the trade detail API response.

**Architecture:** A pure engine function reconstructs standings as-of any week from the already-assembled `matchups` dict (W/L/T read straight from each roster-week's `team_points` vs `opponent_points`). A backend snapshot store (mirroring `RatingSnapshotStore`) persists one JSON per entry-league, keyed by `"{season}-{week:02d}"`. `GraderService.run` computes the full history during refresh (best-effort) and writes it. The trade route reads the store to attach an `at_trade_standing` to each `TradeSideView`.

**Tech Stack:** Python 3, dataclasses, pytest (engine suite at repo root; API suite under `api/`), FastAPI + Pydantic v2.

**Spec:** `docs/superpowers/specs/2026-06-09-standings-data-layer-design.md`

---

## File structure

| File | Responsibility | New? |
| --- | --- | --- |
| `src/sleeper_dynasty/engine/standings.py` | Pure reconstruction: `StandingRow`, `standings_as_of`, `standings_history`, `validate_against_roster` | Create |
| `tests/test_standings.py` | Engine unit tests | Create |
| `api/app/services/standings_snapshot_store.py` | Persisted per-league snapshot store | Create |
| `api/tests/test_standings_snapshot_store.py` | Store round-trip tests | Create |
| `api/app/services/grader.py` | Add best-effort `_snapshot_standings`, call it in `run` | Modify |
| `api/tests/test_grader_standings.py` | Test the snapshot helper writes correct rows | Create |
| `api/app/models/trade.py` | Add `StandingAtTrade` model + field on `TradeSideView` | Modify |
| `api/app/services/trade_view.py` | Populate `at_trade_standing` from the store | Modify |
| `api/app/routes/trade.py` | Inject the store into `build_trade_detail` | Modify |
| `api/tests/test_trade_standing.py` | Consumer test: response carries `at_trade_standing` | Create |

**Key invariant:** standings count **regular-season weeks only** (`week < playoff_week_start`), so reconstruction matches Sleeper's authoritative `Roster` W/L (which excludes playoff bracket games).

---

## Task 1: Engine — `standings_as_of` (pure reconstruction)

**Files:**
- Create: `src/sleeper_dynasty/engine/standings.py`
- Test: `tests/test_standings.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_standings.py
from __future__ import annotations

from sleeper_dynasty.engine.standings import StandingRow, standings_as_of


def _mk(team_points, opp_points):
    return {"team_points": team_points, "opponent_points": opp_points}


# Two-team league, weeks 1-3. r1 beats r2 twice, loses once.
MATCHUPS = {
    ("L", 1, 1): _mk(100.0, 90.0),
    ("L", 1, 2): _mk(90.0, 100.0),
    ("L", 2, 1): _mk(80.0, 110.0),
    ("L", 2, 2): _mk(110.0, 80.0),
    ("L", 3, 1): _mk(120.0, 100.0),
    ("L", 3, 2): _mk(100.0, 120.0),
}
R2U = {1: "ua", 2: "ub"}


def test_through_week_2_counts_one_win_one_loss_each():
    rows = standings_as_of(
        MATCHUPS, league_id="L", through_week=2,
        playoff_week_start=15, roster_to_user=R2U,
    )
    by_owner = {r.owner_id: r for r in rows}
    assert by_owner["ua"].wins == 1 and by_owner["ua"].losses == 1
    assert by_owner["ua"].points_for == 180.0  # 100 + 80
    assert by_owner["ub"].wins == 1 and by_owner["ub"].losses == 1


def test_full_season_ranks_r1_first_by_record():
    rows = standings_as_of(
        MATCHUPS, league_id="L", through_week=3,
        playoff_week_start=15, roster_to_user=R2U,
    )
    assert [r.owner_id for r in rows] == ["ua", "ub"]
    assert rows[0].rank == 1 and rows[1].rank == 2
    assert rows[0].wins == 2 and rows[0].losses == 1


def test_tie_when_equal_points():
    m = {("L", 1, 1): _mk(100.0, 100.0), ("L", 1, 2): _mk(100.0, 100.0)}
    rows = standings_as_of(
        m, league_id="L", through_week=1,
        playoff_week_start=15, roster_to_user={1: "ua", 2: "ub"},
    )
    assert all(r.ties == 1 and r.wins == 0 and r.losses == 0 for r in rows)


def test_playoff_weeks_excluded():
    # Week 15 is a playoff week and must not affect the regular-season record.
    m = dict(MATCHUPS)
    m[("L", 15, 1)] = _mk(200.0, 10.0)
    m[("L", 15, 2)] = _mk(10.0, 200.0)
    rows = standings_as_of(
        m, league_id="L", through_week=15,
        playoff_week_start=15, roster_to_user=R2U,
    )
    by_owner = {r.owner_id: r for r in rows}
    assert by_owner["ua"].wins == 2  # unchanged by the week-15 blowout


def test_unplayed_week_skipped():
    m = {("L", 1, 1): _mk(None, None), ("L", 1, 2): _mk(None, None)}
    rows = standings_as_of(
        m, league_id="L", through_week=5,
        playoff_week_start=15, roster_to_user={1: "ua", 2: "ub"},
    )
    assert all(r.wins == 0 and r.losses == 0 and r.points_for == 0.0 for r in rows)


def test_other_league_rows_ignored():
    m = dict(MATCHUPS)
    m[("OTHER", 1, 1)] = _mk(999.0, 0.0)
    rows = standings_as_of(
        m, league_id="L", through_week=3,
        playoff_week_start=15, roster_to_user=R2U,
    )
    assert all(r.points_for < 500 for r in rows)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_standings.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sleeper_dynasty.engine.standings'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/sleeper_dynasty/engine/standings.py
"""Pure regular-season standings reconstruction from assembled matchups.

W/L/T is read directly from each roster-week's ``team_points`` vs
``opponent_points`` (the matchups dict is already opponent-paired by
``grader_io._assemble_played_matchups``), so no matchup_id re-pairing is needed.

Standings count REGULAR-SEASON weeks only (``week < playoff_week_start``) to match
Sleeper's authoritative ``Roster`` record, which excludes playoff bracket games.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class StandingRow:
    owner_id: str
    roster_id: int
    wins: int
    losses: int
    ties: int
    points_for: float
    points_against: float
    rank: int = 0


def standings_as_of(
    matchups: dict[tuple[str, int, int], dict],
    *,
    league_id: str,
    through_week: int,
    playoff_week_start: int,
    roster_to_user: dict[int, str],
) -> list[StandingRow]:
    """Regular-season standings for one league through ``through_week`` inclusive.

    Counts only weeks ``1 <= week <= through_week`` and ``week < playoff_week_start``.
    Roster-weeks with missing points (unplayed) are skipped. Ranks by
    (wins desc, points_for desc) — Sleeper's default tiebreak.
    """
    acc: dict[int, StandingRow] = {}
    for (lg, wk, rid), entry in matchups.items():
        if lg != league_id or wk > through_week or wk >= playoff_week_start:
            continue
        tp = entry.get("team_points")
        op = entry.get("opponent_points")
        if tp is None or op is None:
            continue
        row = acc.get(rid)
        if row is None:
            row = StandingRow(
                owner_id=roster_to_user.get(rid, str(rid)),
                roster_id=rid, wins=0, losses=0, ties=0,
                points_for=0.0, points_against=0.0,
            )
            acc[rid] = row
        tp, op = float(tp), float(op)
        row.points_for += tp
        row.points_against += op
        if tp > op:
            row.wins += 1
        elif tp < op:
            row.losses += 1
        else:
            row.ties += 1
    rows = sorted(acc.values(), key=lambda r: (-r.wins, -r.points_for))
    for i, r in enumerate(rows, start=1):
        r.rank = i
    return rows
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_standings.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/standings.py tests/test_standings.py
git commit -m "feat(engine): standings_as_of — pure regular-season reconstruction"
```

---

## Task 2: Engine — `standings_history` + `validate_against_roster`

**Files:**
- Modify: `src/sleeper_dynasty/engine/standings.py`
- Test: `tests/test_standings.py`

- [ ] **Step 1: Write the failing test (append to `tests/test_standings.py`)**

```python
from sleeper_dynasty.engine.standings import (
    standings_history,
    validate_against_roster,
)
from sleeper_dynasty.models.league import Roster


def test_standings_history_keys_and_values():
    hist = standings_history(
        MATCHUPS, league_id="L", season=2024,
        playoff_week_start=15, roster_to_user=R2U,
    )
    assert set(hist) == {"2024-01", "2024-02", "2024-03"}
    # By week 3, ua has 2 wins.
    by_owner = {r.owner_id: r for r in hist["2024-03"]}
    assert by_owner["ua"].wins == 2


def _roster(rid, owner, w, l, pf):
    return Roster(
        roster_id=rid, owner_id=owner, owner_name=owner, players=[],
        wins=w, losses=l, ties=0, points_for=pf, points_against=0.0,
    )


def test_validate_matches_returns_empty():
    rows = standings_as_of(
        MATCHUPS, league_id="L", through_week=3,
        playoff_week_start=15, roster_to_user=R2U,
    )
    rosters = [_roster(1, "ua", 2, 1, 300.0), _roster(2, "ub", 1, 2, 280.0)]
    assert validate_against_roster(rows, rosters) == []


def test_validate_reports_record_mismatch():
    rows = standings_as_of(
        MATCHUPS, league_id="L", through_week=3,
        playoff_week_start=15, roster_to_user=R2U,
    )
    rosters = [_roster(1, "ua", 3, 0, 300.0), _roster(2, "ub", 1, 2, 280.0)]
    deltas = validate_against_roster(rows, rosters)
    assert any("roster 1" in d for d in deltas)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_standings.py -v`
Expected: FAIL — `ImportError: cannot import name 'standings_history'`

- [ ] **Step 3: Add the implementation (append to `src/sleeper_dynasty/engine/standings.py`)**

```python
def standings_history(
    matchups: dict[tuple[str, int, int], dict],
    *,
    league_id: str,
    season: int,
    playoff_week_start: int,
    roster_to_user: dict[int, str],
) -> dict[str, list[StandingRow]]:
    """Standings after each completed regular-season week of one league-season.

    Returns ``{"{season}-{week:02d}": [StandingRow, ...]}`` for every regular-season
    week present in ``matchups`` for ``league_id``.
    """
    weeks = sorted({
        wk for (lg, wk, _rid) in matchups
        if lg == league_id and wk < playoff_week_start
    })
    out: dict[str, list[StandingRow]] = {}
    for wk in weeks:
        out[f"{season:04d}-{wk:02d}"] = standings_as_of(
            matchups, league_id=league_id, through_week=wk,
            playoff_week_start=playoff_week_start, roster_to_user=roster_to_user,
        )
    return out


def validate_against_roster(
    reconstructed: list[StandingRow], rosters: list
) -> list[str]:
    """Compare a fully-reconstructed regular-season table against Sleeper's
    authoritative ``Roster`` records. Returns human-readable deltas ([] when exact).

    Sleeper's roster wins/losses already account for median/division rules, so a
    mismatch flags a league whose standings need extra handling. Points-for is
    compared with a small tolerance (rounding).
    """
    by_rid = {r.roster_id: r for r in reconstructed}
    deltas: list[str] = []
    for roster in rosters:
        got = by_rid.get(roster.roster_id)
        if got is None:
            deltas.append(f"roster {roster.roster_id}: no reconstructed row")
            continue
        if got.wins != roster.wins or got.losses != roster.losses:
            deltas.append(
                f"roster {roster.roster_id}: record {got.wins}-{got.losses} "
                f"!= sleeper {roster.wins}-{roster.losses}"
            )
        if abs(got.points_for - float(roster.points_for)) > 1.0:
            deltas.append(
                f"roster {roster.roster_id}: pf {got.points_for:.1f} "
                f"!= sleeper {float(roster.points_for):.1f}"
            )
    return deltas
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_standings.py -v`
Expected: PASS (10 tests total)

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/standings.py tests/test_standings.py
git commit -m "feat(engine): standings_history + validate_against_roster"
```

---

## Task 3: Backend — `StandingsSnapshotStore`

**Files:**
- Create: `api/app/services/standings_snapshot_store.py`
- Test: `api/tests/test_standings_snapshot_store.py`

- [ ] **Step 1: Write the failing test**

```python
# api/tests/test_standings_snapshot_store.py
from __future__ import annotations

from app.services.standings_snapshot_store import StandingsSnapshotStore


def _rows():
    return [
        {"owner_id": "ua", "roster_id": 1, "wins": 2, "losses": 1, "ties": 0,
         "points_for": 300.0, "points_against": 280.0, "rank": 1},
        {"owner_id": "ub", "roster_id": 2, "wins": 1, "losses": 2, "ties": 0,
         "points_for": 280.0, "points_against": 300.0, "rank": 2},
    ]


def test_write_then_read_round_trips(tmp_path):
    store = StandingsSnapshotStore(cache_dir=tmp_path)
    store.write("L1", "2024-03", _rows())
    assert store.read("L1") == {"2024-03": _rows()}


def test_read_absent_is_empty(tmp_path):
    store = StandingsSnapshotStore(cache_dir=tmp_path)
    assert store.read("nope") == {}
    assert store.as_of("nope", 2024, 5) == []


def test_as_of_returns_latest_at_or_before(tmp_path):
    store = StandingsSnapshotStore(cache_dir=tmp_path)
    store.write("L1", "2024-01", _rows())
    store.write("L1", "2024-03", _rows())
    # Week 2 has no snapshot -> falls back to 2024-01.
    assert store.as_of("L1", 2024, 2) == _rows()
    # Exact hit.
    assert store.as_of("L1", 2024, 3) == _rows()
    # Before any snapshot -> empty.
    assert store.as_of("L1", 2023, 17) == []


def test_keeps_all_weeks_across_seasons(tmp_path):
    store = StandingsSnapshotStore(cache_dir=tmp_path)
    for season in range(2018, 2025):
        store.write("L1", f"{season}-05", _rows())
    assert len(store.read("L1")) == 7  # not capped
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest tests/test_standings_snapshot_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.standings_snapshot_store'`

- [ ] **Step 3: Write minimal implementation**

```python
# api/app/services/standings_snapshot_store.py
"""Per-week regular-season standings snapshots for a whole league chain.

One JSON file per entry-league (standings_<league_id>.json) mapping a season-scoped
week key ("{season}-{week:02d}") to the full standings table (list of owner rows).
Written during refresh from the reconstructed history; read by the trade view to
attach each side's as-of-trade standing.

Mirrors ``rating_snapshot_store`` in structure, but is NOT capped — as-of-trade
lookups can reach years back, and completed weeks are immutable.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)


class StandingsSnapshotStore:
    def __init__(self, cache_dir: Path):
        self.dir = Path(cache_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, league_id: str) -> Path:
        return self.dir / f"standings_{league_id}.json"

    def read(self, league_id: str) -> dict[str, list[dict]]:
        """{week_key: [row, ...]} for the league ({} if absent/unreadable)."""
        path = self._path(league_id)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError) as e:
            log.warning("standings snapshot unreadable (%s); ignoring", e)
            return {}

    def write(self, league_id: str, week_key: str, rows: list[dict]) -> None:
        """Set (overwrite) the snapshot for ``week_key``. Uncapped."""
        data = self.read(league_id)
        data[week_key] = list(rows)
        self._path(league_id).write_text(json.dumps(data))

    def write_many(self, league_id: str, history: dict[str, list[dict]]) -> None:
        """Merge a full {week_key: rows} history in one write."""
        data = self.read(league_id)
        data.update(history)
        self._path(league_id).write_text(json.dumps(data))

    def as_of(self, league_id: str, season: int, week: int) -> list[dict]:
        """Standings table for the latest snapshot at or before ``season``-``week``
        ([] if none exists at or before it)."""
        key = f"{int(season):04d}-{int(week):02d}"
        data = self.read(league_id)
        candidates = [k for k in data if k <= key]
        if not candidates:
            return []
        return data[max(candidates)]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && python -m pytest tests/test_standings_snapshot_store.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add api/app/services/standings_snapshot_store.py api/tests/test_standings_snapshot_store.py
git commit -m "feat(api): StandingsSnapshotStore — uncapped per-week standings store"
```

---

## Task 4: Refresh wiring — `GraderService._snapshot_standings`

**Files:**
- Modify: `api/app/services/grader.py` (add method, call in `run` before building the entry)
- Test: `api/tests/test_grader_standings.py`

Context: `GraderService.run` builds `supporting` (line ~108) carrying `matchups`,
`roster_to_user_by_league`, `league_season_by_id`, `playoff_week_start_by_league`.
We add a best-effort helper that reconstructs each league-season's history and writes
it to the entry-league file, then call it right before `entry = ChainCacheEntry(...)`
(line ~193). Best-effort: never fail refresh on a snapshot error.

- [ ] **Step 1: Write the failing test**

```python
# api/tests/test_grader_standings.py
from __future__ import annotations

from app.services.grader import GraderService
from app.services.standings_snapshot_store import StandingsSnapshotStore


def test_snapshot_standings_writes_history(tmp_path):
    supporting = {
        "matchups": {
            ("LG", 1, 1): {"team_points": 100.0, "opponent_points": 90.0},
            ("LG", 1, 2): {"team_points": 90.0, "opponent_points": 100.0},
            ("LG", 2, 1): {"team_points": 120.0, "opponent_points": 80.0},
            ("LG", 2, 2): {"team_points": 80.0, "opponent_points": 120.0},
        },
        "roster_to_user_by_league": {"LG": {1: "ua", 2: "ub"}},
        "league_season_by_id": {"LG": 2024},
        "playoff_week_start_by_league": {"LG": 15},
    }
    GraderService()._snapshot_standings(
        supporting=supporting, current_league_id="ENTRY", cache_dir=tmp_path,
    )
    store = StandingsSnapshotStore(cache_dir=tmp_path)
    data = store.read("ENTRY")
    assert set(data) == {"2024-01", "2024-02"}
    wk2 = {r["owner_id"]: r for r in data["2024-02"]}
    assert wk2["ua"]["wins"] == 2 and wk2["ua"]["rank"] == 1


def test_snapshot_standings_swallows_errors(tmp_path):
    # Malformed supporting must not raise.
    GraderService()._snapshot_standings(
        supporting={"matchups": None}, current_league_id="X", cache_dir=tmp_path,
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest tests/test_grader_standings.py -v`
Expected: FAIL — `AttributeError: 'GraderService' object has no attribute '_snapshot_standings'`

- [ ] **Step 3: Add the method and call it**

Add this method to `GraderService` in `api/app/services/grader.py` (e.g. after `_compute_became`):

```python
    def _snapshot_standings(
        self,
        *,
        supporting: dict,
        current_league_id: str,
        cache_dir,
    ) -> None:
        """Reconstruct per-week regular-season standings for every league-season in
        the chain and persist them under the entry league. Best-effort: any failure
        logs and is swallowed so refresh never fails on standings.
        """
        if cache_dir is None:
            return
        try:
            from dataclasses import asdict

            from sleeper_dynasty.engine.standings import standings_history

            from app.services.standings_snapshot_store import StandingsSnapshotStore

            matchups = supporting.get("matchups") or {}
            r2u_by_league = supporting.get("roster_to_user_by_league") or {}
            season_by_league = supporting.get("league_season_by_id") or {}
            pws_by_league = supporting.get("playoff_week_start_by_league") or {}

            merged: dict[str, list[dict]] = {}
            for league_id, season in season_by_league.items():
                hist = standings_history(
                    matchups,
                    league_id=league_id,
                    season=int(season),
                    playoff_week_start=int(pws_by_league.get(league_id, 15)),
                    roster_to_user=r2u_by_league.get(league_id, {}),
                )
                for week_key, rows in hist.items():
                    merged[week_key] = [asdict(r) for r in rows]

            if merged:
                StandingsSnapshotStore(cache_dir=cache_dir).write_many(
                    current_league_id, merged
                )
                log.info(
                    "snapshotted standings for league %s (%d weeks)",
                    current_league_id, len(merged),
                )
        except Exception:
            log.exception("standings snapshot skipped for league %s", current_league_id)
```

Then call it in `run`, immediately before `entry = ChainCacheEntry(` (around line 192):

```python
        self._snapshot_standings(
            supporting=supporting,
            current_league_id=current_league_id,
            cache_dir=cache_dir,
        )
        await progress_cb("done", "Building dashboard payload")
        entry = ChainCacheEntry(
```

(Move the existing `await progress_cb("done", ...)` line to directly follow the snapshot call as shown — the snapshot is part of finalizing.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && python -m pytest tests/test_grader_standings.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add api/app/services/grader.py api/tests/test_grader_standings.py
git commit -m "feat(api): write per-week standings snapshots during refresh"
```

---

## Task 5: Consumer — `at_trade_standing` on the trade response

**Files:**
- Modify: `api/app/models/trade.py` (add `StandingAtTrade`, field on `TradeSideView`)
- Modify: `api/app/services/trade_view.py` (populate from the store)
- Modify: `api/app/routes/trade.py` (inject the store)
- Test: `api/tests/test_trade_standing.py`

- [ ] **Step 1: Write the failing test**

```python
# api/tests/test_trade_standing.py
from __future__ import annotations

from types import SimpleNamespace

from app.services.standings_snapshot_store import StandingsSnapshotStore
from app.services.trade_view import build_trade_detail


def _entry():
    rt = {
        "trade": {
            "transaction_id": "t1", "traded_at": "2024-10-01T00:00:00+00:00",
            "week": 4, "season": 2024, "league_id": "LG",
        },
        "sides": {
            "ua": {"received": [], "given": []},
            "ub": {"received": [], "given": []},
        },
    }
    return SimpleNamespace(
        league_id="ENTRY",
        resolved_trades=[rt],
        grades={"t1": {}},
        trade_stories={},
        became_grades={},
        current_holders={},
        league_name_by_id={"LG": "My League"},
        owners={"ua": {"owner_name": "A"}, "ub": {"owner_name": "B"}},
    )


def test_at_trade_standing_attached(tmp_path):
    store = StandingsSnapshotStore(cache_dir=tmp_path)
    store.write("ENTRY", "2024-03", [
        {"owner_id": "ua", "roster_id": 1, "wins": 3, "losses": 0, "ties": 0,
         "points_for": 320.0, "points_against": 250.0, "rank": 1},
        {"owner_id": "ub", "roster_id": 2, "wins": 0, "losses": 3, "ties": 0,
         "points_for": 250.0, "points_against": 320.0, "rank": 2},
    ])
    detail = build_trade_detail(_entry(), "t1", standings_store=store)
    by_owner = {s.user_id: s for s in detail.sides}
    assert by_owner["ua"].at_trade_standing.rank == 1
    assert by_owner["ua"].at_trade_standing.wins == 3
    assert by_owner["ua"].at_trade_standing.total_teams == 2
    assert by_owner["ub"].at_trade_standing.rank == 2


def test_at_trade_standing_null_without_snapshot(tmp_path):
    store = StandingsSnapshotStore(cache_dir=tmp_path)
    detail = build_trade_detail(_entry(), "t1", standings_store=store)
    assert detail.sides[0].at_trade_standing is None


def test_build_trade_detail_without_store_is_backward_compatible():
    detail = build_trade_detail(_entry(), "t1")
    assert all(s.at_trade_standing is None for s in detail.sides)
```

Note: `owner_ref` is imported by `trade_view`; the `SimpleNamespace` entry above
provides the `owners` / `league_name_by_id` attributes it reads. If `owner_ref`
needs additional attributes, add them to `_entry()` to match (e.g. empty dicts).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest tests/test_trade_standing.py -v`
Expected: FAIL — `TypeError: build_trade_detail() got an unexpected keyword argument 'standings_store'`

- [ ] **Step 3a: Add the model** (`api/app/models/trade.py`)

Add above `TradeSideView`:

```python
class StandingAtTrade(BaseModel):
    rank: int
    wins: int
    losses: int
    ties: int
    points_for: float
    total_teams: int
```

Add this field to `TradeSideView` (after `at_trade_snapshot_date`):

```python
    at_trade_standing: StandingAtTrade | None = None
```

- [ ] **Step 3b: Populate in `trade_view.py`**

Update the signature and imports:

```python
from app.models.trade import (
    BecameMetrics, LineageNode, StandingAtTrade, TradeDetailResp,
    TradeSideView, TradeStory,
)
from app.services.standings_snapshot_store import StandingsSnapshotStore


def build_trade_detail(
    entry, trade_id: str, *, standings_store: StandingsSnapshotStore | None = None
) -> TradeDetailResp | None:
```

After `rt` is resolved and before the `for uid, side in ...` loop, build a per-owner
standing lookup for this trade's week:

```python
    standing_by_owner: dict[str, StandingAtTrade] = {}
    if standings_store is not None:
        rows = standings_store.as_of(
            entry.league_id,
            int(rt["trade"]["season"]),
            int(rt["trade"]["week"]),
        )
        total = len(rows)
        for row in rows:
            standing_by_owner[row["owner_id"]] = StandingAtTrade(
                rank=int(row["rank"]),
                wins=int(row["wins"]),
                losses=int(row["losses"]),
                ties=int(row["ties"]),
                points_for=float(row["points_for"]),
                total_teams=total,
            )
```

Then pass it when constructing each `TradeSideView` (add to the existing call):

```python
            at_trade_standing=standing_by_owner.get(uid),
```

- [ ] **Step 3c: Inject the store in the route** (`api/app/routes/trade.py`)

```python
from app.services.standings_snapshot_store import StandingsSnapshotStore
```

In `trade(...)`, replace the `build_trade_detail` call:

```python
    detail = build_trade_detail(
        entry, trade_id,
        standings_store=StandingsSnapshotStore(cache_dir=_cache_dir()),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && python -m pytest tests/test_trade_standing.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Run the full suites to confirm no regressions**

Run: `pytest tests/test_standings.py -v && cd api && python -m pytest tests/test_standings_snapshot_store.py tests/test_grader_standings.py tests/test_trade_standing.py tests/test_trade.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add api/app/models/trade.py api/app/services/trade_view.py api/app/routes/trade.py api/tests/test_trade_standing.py
git commit -m "feat(api): attach as-of-trade standing to the trade detail response"
```

---

## Final verification

- [ ] Run the engine suite: `pytest -q`
- [ ] Run the API suite: `cd api && python -m pytest -q`
- [ ] Confirm a real refresh writes a `standings_<league_id>.json` and the trade
      endpoint returns `at_trade_standing` (manual smoke, optional):
      `make dev-api`, refresh a known league, then
      `GET /api/league/<id>/trade/<tid>` and check the `sides[].at_trade_standing`.

## Self-review notes (addressed)

- **Spec coverage:** engine reconstruction (Tasks 1-2), snapshot store (Task 3),
  refresh wiring (Task 4), as-of-trade consumer (Task 5), validation function +
  tests (Task 2), self-validation against Sleeper records (`validate_against_roster`,
  available for an optional in-refresh log — kept out of the hot path to avoid extra
  roster fetches; exercised by tests against synthetic + real data).
- **Regular-season-only invariant** enforced in `standings_as_of` via
  `week < playoff_week_start`, matching Sleeper's authoritative record.
- **Backward compatibility:** `build_trade_detail`'s new arg is keyword-only and
  optional; existing callers/tests keep working (Task 5 test asserts this).
- **Out of scope (tracked):** GM Rating attribution (sub-project B) and the one-sided
  metric reframe + toilet sign — separate efforts, not in this plan.
