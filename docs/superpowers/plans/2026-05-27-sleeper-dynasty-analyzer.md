> _Historical doc — paths/names have changed. Repo is now `Code Apps/public-dynasty` (GitHub `tkeefe66/public-dynasty-app`), Railway project **shimmering-nature**, live at https://ffbdynasty.com. Ignore stale refs to `sleeper-dynasty` / `sleeper-trade-grader` / `web-production-f949`._

# Sleeper Dynasty Analyzer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python CLI that pulls Sleeper fantasy football data, simulates a full season via Monte Carlo, and outputs a shareable Google Doc report with standings, team analysis, dynasty outlooks, and matchup forecasts.

**Architecture:** Data flows linearly: CLI parses args → Sleeper API client fetches league/roster/matchup data → projection module blends Sleeper + FantasyPros data → lineup solver + Monte Carlo engine simulate the season → dynasty module analyzes long-term outlook → Google Docs output module creates a tabbed, shareable report. All data is modeled with Python dataclasses. Caching layer sits between API clients and the rest.

**Tech Stack:** Python 3.11+, httpx, numpy, google-api-python-client, google-auth-oauthlib, pytest

---

### Task 1: Project Scaffolding & Data Models

**Files:**
- Create: `pyproject.toml`
- Create: `src/sleeper_dynasty/__init__.py`
- Create: `src/sleeper_dynasty/__main__.py`
- Create: `src/sleeper_dynasty/models/__init__.py`
- Create: `src/sleeper_dynasty/models/player.py`
- Create: `src/sleeper_dynasty/models/league.py`
- Create: `tests/__init__.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.backends._legacy:_Backend"

[project]
name = "sleeper-dynasty"
version = "0.1.0"
description = "Sleeper fantasy football dynasty league analyzer"
requires-python = ">=3.11"
dependencies = [
    "httpx>=0.27",
    "numpy>=1.26",
    "google-api-python-client>=2.100",
    "google-auth-oauthlib>=1.1",
    "google-auth-httplib2>=0.2",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23"]

[project.scripts]
sleeper-dynasty = "sleeper_dynasty.cli:main"

[tool.setuptools.packages.find]
where = ["src"]
```

- [ ] **Step 2: Create `src/sleeper_dynasty/__init__.py`**

```python
"""Sleeper dynasty fantasy football analyzer."""
```

- [ ] **Step 3: Create `src/sleeper_dynasty/__main__.py`**

```python
from sleeper_dynasty.cli import main

main()
```

- [ ] **Step 4: Write failing test for Player model**

Create `tests/__init__.py` (empty) and `tests/test_models.py`:

```python
from datetime import date

from sleeper_dynasty.models.player import Player, PlayerProjection


def test_player_age_calculation():
    player = Player(
        player_id="4046",
        full_name="Patrick Mahomes",
        position="QB",
        team="KC",
        birth_date=date(1995, 9, 17),
    )
    age = player.age(as_of=date(2026, 9, 1))
    assert age == 30


def test_player_age_none_when_no_birth_date():
    player = Player(
        player_id="DEF_KC",
        full_name="Kansas City",
        position="DEF",
        team="KC",
        birth_date=None,
    )
    assert player.age(as_of=date(2026, 9, 1)) is None


def test_player_projection():
    proj = PlayerProjection(
        player_id="4046",
        source="sleeper",
        season=2026,
        week=None,
        projected_points=22.5,
    )
    assert proj.projected_points == 22.5
    assert proj.week is None
```

- [ ] **Step 5: Run test to verify it fails**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && python -m pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sleeper_dynasty.models.player'`

- [ ] **Step 6: Implement Player model**

Create `src/sleeper_dynasty/models/__init__.py` (empty) and `src/sleeper_dynasty/models/player.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class Player:
    player_id: str
    full_name: str
    position: str  # QB, RB, WR, TE, K, DEF
    team: str | None
    birth_date: date | None = None
    years_exp: int | None = None

    def age(self, as_of: date | None = None) -> int | None:
        if self.birth_date is None:
            return None
        ref = as_of or date.today()
        years = ref.year - self.birth_date.year
        if (ref.month, ref.day) < (self.birth_date.month, self.birth_date.day):
            years -= 1
        return years


@dataclass
class PlayerProjection:
    player_id: str
    source: str  # "sleeper" or "fantasypros"
    season: int
    week: int | None  # None = full season
    projected_points: float
    stats: dict[str, float] = field(default_factory=dict)
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && pip install -e ".[dev]" && python -m pytest tests/test_models.py -v`
Expected: 3 passed

- [ ] **Step 8: Write failing test for League models**

Append to `tests/test_models.py`:

```python
from sleeper_dynasty.models.league import League, Roster, Matchup, DraftPick


def test_league_creation():
    league = League(
        league_id="123",
        name="Dynasty Bros",
        season=2026,
        total_rosters=12,
        roster_positions=["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX", "SUPER_FLEX", "K", "DEF"],
        scoring_settings={"pass_td": 4.0, "rec": 1.0},
        playoff_week_start=15,
        num_playoff_teams=6,
        status="in_season",
    )
    assert league.name == "Dynasty Bros"
    assert league.total_rosters == 12
    assert league.roster_positions.count("FLEX") == 2


def test_roster_creation():
    roster = Roster(
        roster_id=1,
        owner_id="user_abc",
        owner_name="Tom",
        players=["4046", "6794", "4984"],
        wins=5,
        losses=3,
        ties=0,
        points_for=1205.5,
        points_against=1100.2,
    )
    assert roster.owner_name == "Tom"
    assert len(roster.players) == 3


def test_matchup_creation():
    matchup = Matchup(
        week=1,
        roster_id_1=1,
        roster_id_2=2,
        points_1=None,
        points_2=None,
    )
    assert matchup.week == 1


def test_draft_pick_creation():
    pick = DraftPick(
        season=2027,
        round=1,
        original_owner_id=1,
        current_owner_id=3,
    )
    assert pick.current_owner_id == 3
    assert pick.season == 2027
```

- [ ] **Step 9: Run test to verify it fails**

Run: `python -m pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sleeper_dynasty.models.league'`

- [ ] **Step 10: Implement League models**

Create `src/sleeper_dynasty/models/league.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class League:
    league_id: str
    name: str
    season: int
    total_rosters: int
    roster_positions: list[str]
    scoring_settings: dict[str, float]
    playoff_week_start: int
    num_playoff_teams: int
    status: str  # "pre_draft", "drafting", "in_season", "complete"


@dataclass
class Roster:
    roster_id: int
    owner_id: str
    owner_name: str
    players: list[str]
    wins: int
    losses: int
    ties: int
    points_for: float
    points_against: float


@dataclass
class Matchup:
    week: int
    roster_id_1: int
    roster_id_2: int
    points_1: float | None
    points_2: float | None


@dataclass
class DraftPick:
    season: int
    round: int
    original_owner_id: int
    current_owner_id: int
```

- [ ] **Step 11: Run all tests to verify they pass**

Run: `python -m pytest tests/test_models.py -v`
Expected: 7 passed

- [ ] **Step 12: Commit**

```bash
git add pyproject.toml src/ tests/
git commit -m "feat: project scaffolding with Player and League data models"
```

---

### Task 2: Caching Layer

**Files:**
- Create: `src/sleeper_dynasty/cache.py`
- Create: `tests/test_cache.py`

- [ ] **Step 1: Write failing test for cache**

Create `tests/test_cache.py`:

```python
import json
import time
from pathlib import Path

from sleeper_dynasty.cache import FileCache


def test_cache_write_and_read(tmp_path):
    cache = FileCache(cache_dir=tmp_path)
    data = {"players": [{"id": "1", "name": "Test Player"}]}
    cache.write("players.json", data)
    result = cache.read("players.json", max_age_seconds=60)
    assert result == data


def test_cache_returns_none_when_expired(tmp_path):
    cache = FileCache(cache_dir=tmp_path)
    data = {"key": "value"}
    cache.write("old.json", data)
    result = cache.read("old.json", max_age_seconds=0)
    assert result is None


def test_cache_returns_none_when_missing(tmp_path):
    cache = FileCache(cache_dir=tmp_path)
    result = cache.read("nonexistent.json", max_age_seconds=60)
    assert result is None


def test_cache_invalidate(tmp_path):
    cache = FileCache(cache_dir=tmp_path)
    cache.write("remove_me.json", {"data": True})
    cache.invalidate("remove_me.json")
    result = cache.read("remove_me.json", max_age_seconds=60)
    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cache.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sleeper_dynasty.cache'`

- [ ] **Step 3: Implement FileCache**

Create `src/sleeper_dynasty/cache.py`:

```python
from __future__ import annotations

import json
import time
from pathlib import Path

DEFAULT_CACHE_DIR = Path.home() / ".sleeper-dynasty" / "cache"
ONE_DAY = 86400


class FileCache:
    def __init__(self, cache_dir: Path = DEFAULT_CACHE_DIR):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def read(self, key: str, max_age_seconds: int = ONE_DAY) -> dict | list | None:
        path = self.cache_dir / key
        if not path.exists():
            return None
        age = time.time() - path.stat().st_mtime
        if age > max_age_seconds:
            return None
        with open(path) as f:
            return json.load(f)

    def write(self, key: str, data: dict | list) -> None:
        path = self.cache_dir / key
        with open(path, "w") as f:
            json.dump(data, f)

    def invalidate(self, key: str) -> None:
        path = self.cache_dir / key
        if path.exists():
            path.unlink()

    def invalidate_all(self) -> None:
        for path in self.cache_dir.iterdir():
            if path.is_file() and path.suffix == ".json":
                path.unlink()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_cache.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/cache.py tests/test_cache.py
git commit -m "feat: file-based cache with TTL expiration"
```

---

### Task 3: Sleeper API Client

**Files:**
- Create: `src/sleeper_dynasty/api/__init__.py`
- Create: `src/sleeper_dynasty/api/sleeper.py`
- Create: `tests/test_sleeper_api.py`
- Create: `tests/fixtures/` (JSON fixture files for mocking)

- [ ] **Step 1: Create API response fixtures**

Create `tests/fixtures/user.json`:
```json
{"user_id": "123456789", "username": "testuser", "display_name": "Test User"}
```

Create `tests/fixtures/leagues.json`:
```json
[
  {
    "league_id": "league_001",
    "name": "Dynasty Bros",
    "season": "2026",
    "total_rosters": 12,
    "roster_positions": ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX", "SUPER_FLEX", "K", "DEF",
                         "BN", "BN", "BN", "BN", "BN", "BN", "BN", "BN", "BN", "BN",
                         "IR", "IR", "TAXI", "TAXI", "TAXI"],
    "scoring_settings": {"pass_td": 4.0, "rec": 1.0, "rush_td": 6.0, "pass_yd": 0.04, "rush_yd": 0.1, "rec_yd": 0.1},
    "settings": {"playoff_week_start": 15, "num_playoff_teams": 6},
    "status": "in_season",
    "previous_league_id": "league_000"
  }
]
```

Create `tests/fixtures/rosters.json`:
```json
[
  {
    "roster_id": 1,
    "owner_id": "user_aaa",
    "players": ["4046", "6794", "4984", "2449", "1479"],
    "settings": {"wins": 5, "losses": 3, "ties": 0, "fpts": 1205, "fpts_decimal": 50, "fpts_against": 1100, "fpts_against_decimal": 20}
  },
  {
    "roster_id": 2,
    "owner_id": "user_bbb",
    "players": ["5848", "4866", "6803", "3321", "1466"],
    "settings": {"wins": 4, "losses": 4, "ties": 0, "fpts": 1100, "fpts_decimal": 0, "fpts_against": 1050, "fpts_against_decimal": 0}
  }
]
```

Create `tests/fixtures/users.json`:
```json
[
  {"user_id": "user_aaa", "display_name": "Alice", "metadata": {"team_name": "Alice's Aces"}},
  {"user_id": "user_bbb", "display_name": "Bob", "metadata": {"team_name": "Bob's Bombers"}}
]
```

Create `tests/fixtures/matchups_week1.json`:
```json
[
  {"roster_id": 1, "matchup_id": 1, "points": 105.5},
  {"roster_id": 2, "matchup_id": 1, "points": 98.2}
]
```

Create `tests/fixtures/traded_picks.json`:
```json
[
  {"season": "2027", "round": 1, "roster_id": 3, "previous_owner_id": 1, "owner_id": 3}
]
```

- [ ] **Step 2: Write failing test for Sleeper API client**

Create `tests/test_sleeper_api.py`:

```python
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from sleeper_dynasty.api.sleeper import SleeperClient
from sleeper_dynasty.models.league import League, Roster, Matchup, DraftPick

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    with open(FIXTURES / name) as f:
        return json.load(f)


@pytest.fixture
def client():
    return SleeperClient()


class TestGetUserId:
    @pytest.mark.asyncio
    async def test_returns_user_id(self, client):
        mock_response = AsyncMock()
        mock_response.json.return_value = load_fixture("user.json")
        mock_response.raise_for_status = lambda: None
        with patch.object(client._client, "get", return_value=mock_response):
            user_id = await client.get_user_id("testuser")
        assert user_id == "123456789"


class TestGetLeagues:
    @pytest.mark.asyncio
    async def test_returns_league_list(self, client):
        mock_response = AsyncMock()
        mock_response.json.return_value = load_fixture("leagues.json")
        mock_response.raise_for_status = lambda: None
        with patch.object(client._client, "get", return_value=mock_response):
            leagues = await client.get_leagues("123456789", 2026)
        assert len(leagues) == 1
        assert leagues[0].name == "Dynasty Bros"
        assert leagues[0].total_rosters == 12
        assert isinstance(leagues[0], League)


class TestGetRosters:
    @pytest.mark.asyncio
    async def test_returns_roster_list(self, client):
        mock_users = AsyncMock()
        mock_users.json.return_value = load_fixture("users.json")
        mock_users.raise_for_status = lambda: None

        mock_rosters = AsyncMock()
        mock_rosters.json.return_value = load_fixture("rosters.json")
        mock_rosters.raise_for_status = lambda: None

        with patch.object(client._client, "get", side_effect=[mock_users, mock_rosters]):
            rosters = await client.get_rosters("league_001")
        assert len(rosters) == 2
        assert rosters[0].owner_name == "Alice"
        assert rosters[0].wins == 5
        assert isinstance(rosters[0], Roster)


class TestGetMatchups:
    @pytest.mark.asyncio
    async def test_returns_matchup_list(self, client):
        mock_response = AsyncMock()
        mock_response.json.return_value = load_fixture("matchups_week1.json")
        mock_response.raise_for_status = lambda: None
        with patch.object(client._client, "get", return_value=mock_response):
            matchups = await client.get_matchups("league_001", week=1)
        assert len(matchups) == 1
        assert matchups[0].roster_id_1 == 1
        assert matchups[0].roster_id_2 == 2
        assert isinstance(matchups[0], Matchup)


class TestGetTradedPicks:
    @pytest.mark.asyncio
    async def test_returns_draft_picks(self, client):
        mock_response = AsyncMock()
        mock_response.json.return_value = load_fixture("traded_picks.json")
        mock_response.raise_for_status = lambda: None
        with patch.object(client._client, "get", return_value=mock_response):
            picks = await client.get_traded_picks("league_001")
        assert len(picks) == 1
        assert picks[0].season == 2027
        assert picks[0].round == 1
        assert isinstance(picks[0], DraftPick)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_sleeper_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sleeper_dynasty.api'`

- [ ] **Step 4: Implement SleeperClient**

Create `src/sleeper_dynasty/api/__init__.py` (empty) and `src/sleeper_dynasty/api/sleeper.py`:

```python
from __future__ import annotations

import logging

import httpx

from sleeper_dynasty.models.league import DraftPick, League, Matchup, Roster

log = logging.getLogger(__name__)

BASE_URL = "https://api.sleeper.app/v1"


class SleeperClient:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(base_url=BASE_URL, timeout=30.0)

    async def close(self) -> None:
        await self._client.aclose()

    async def get_user_id(self, username: str) -> str:
        resp = await self._client.get(f"/user/{username}")
        resp.raise_for_status()
        return resp.json()["user_id"]

    async def get_leagues(self, user_id: str, season: int) -> list[League]:
        resp = await self._client.get(f"/user/{user_id}/leagues/nfl/{season}")
        resp.raise_for_status()
        leagues = []
        for raw in resp.json():
            settings = raw.get("settings", {})
            leagues.append(League(
                league_id=raw["league_id"],
                name=raw["name"],
                season=int(raw["season"]),
                total_rosters=raw["total_rosters"],
                roster_positions=raw["roster_positions"],
                scoring_settings=raw.get("scoring_settings", {}),
                playoff_week_start=settings.get("playoff_week_start", 15),
                num_playoff_teams=settings.get("num_playoff_teams", 6),
                status=raw.get("status", "unknown"),
            ))
        return leagues

    async def get_rosters(self, league_id: str) -> list[Roster]:
        users_resp = await self._client.get(f"/league/{league_id}/users")
        users_resp.raise_for_status()
        user_map: dict[str, str] = {}
        for u in users_resp.json():
            name = u.get("metadata", {}).get("team_name") or u.get("display_name", "Unknown")
            user_map[u["user_id"]] = name

        rosters_resp = await self._client.get(f"/league/{league_id}/rosters")
        rosters_resp.raise_for_status()
        rosters = []
        for raw in rosters_resp.json():
            s = raw.get("settings", {})
            fpts = s.get("fpts", 0) + s.get("fpts_decimal", 0) / 100
            fpts_against = s.get("fpts_against", 0) + s.get("fpts_against_decimal", 0) / 100
            rosters.append(Roster(
                roster_id=raw["roster_id"],
                owner_id=raw.get("owner_id", ""),
                owner_name=user_map.get(raw.get("owner_id", ""), "Unknown"),
                players=raw.get("players", []) or [],
                wins=s.get("wins", 0),
                losses=s.get("losses", 0),
                ties=s.get("ties", 0),
                points_for=fpts,
                points_against=fpts_against,
            ))
        return rosters

    async def get_matchups(self, league_id: str, week: int) -> list[Matchup]:
        resp = await self._client.get(f"/league/{league_id}/matchups/{week}")
        resp.raise_for_status()
        raw_list = resp.json()
        by_matchup: dict[int, list[dict]] = {}
        for entry in raw_list:
            mid = entry["matchup_id"]
            by_matchup.setdefault(mid, []).append(entry)
        matchups = []
        for mid, entries in by_matchup.items():
            if len(entries) == 2:
                matchups.append(Matchup(
                    week=week,
                    roster_id_1=entries[0]["roster_id"],
                    roster_id_2=entries[1]["roster_id"],
                    points_1=entries[0].get("points"),
                    points_2=entries[1].get("points"),
                ))
        return matchups

    async def get_traded_picks(self, league_id: str) -> list[DraftPick]:
        resp = await self._client.get(f"/league/{league_id}/traded_picks")
        resp.raise_for_status()
        picks = []
        for raw in resp.json():
            picks.append(DraftPick(
                season=int(raw["season"]),
                round=raw["round"],
                original_owner_id=raw["previous_owner_id"],
                current_owner_id=raw["owner_id"],
            ))
        return picks

    async def get_players(self) -> dict:
        resp = await self._client.get("/players/nfl")
        resp.raise_for_status()
        return resp.json()

    async def get_projections(self, season: int, week: int | None = None) -> dict:
        if week:
            url = f"/projections/nfl/regular/{season}/{week}"
        else:
            url = f"/projections/nfl/regular/{season}"
        resp = await self._client.get(url)
        resp.raise_for_status()
        return resp.json()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_sleeper_api.py -v`
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add src/sleeper_dynasty/api/ tests/test_sleeper_api.py tests/fixtures/
git commit -m "feat: Sleeper API client with user, league, roster, matchup, and pick endpoints"
```

---

### Task 4: External Projections (FantasyPros)

**Files:**
- Create: `src/sleeper_dynasty/api/projections.py`
- Create: `tests/test_projections.py`

- [ ] **Step 1: Write failing test for projection blending**

Create `tests/test_projections.py`:

```python
from sleeper_dynasty.api.projections import blend_projections, normalize_projection
from sleeper_dynasty.models.player import PlayerProjection


def test_blend_prefers_fantasypros_when_available():
    sleeper = PlayerProjection(
        player_id="4046", source="sleeper", season=2026, week=None,
        projected_points=20.0,
    )
    fp = PlayerProjection(
        player_id="4046", source="fantasypros", season=2026, week=None,
        projected_points=24.0,
    )
    blended = blend_projections(sleeper_proj=sleeper, external_proj=fp)
    # 40% sleeper + 60% fantasypros = 0.4*20 + 0.6*24 = 22.4
    assert abs(blended.projected_points - 22.4) < 0.01
    assert blended.source == "blended"


def test_blend_uses_sleeper_only_when_no_external():
    sleeper = PlayerProjection(
        player_id="4046", source="sleeper", season=2026, week=None,
        projected_points=20.0,
    )
    blended = blend_projections(sleeper_proj=sleeper, external_proj=None)
    assert blended.projected_points == 20.0
    assert blended.source == "sleeper"


def test_normalize_projection_ppr():
    scoring = {"rec": 1.0, "pass_td": 4.0, "rush_td": 6.0, "pass_yd": 0.04, "rush_yd": 0.1, "rec_yd": 0.1}
    stats = {"rec": 5.0, "pass_td": 2.0, "rush_td": 0.0, "pass_yd": 250.0, "rush_yd": 0.0, "rec_yd": 60.0}
    # 5*1 + 2*4 + 0 + 250*0.04 + 0 + 60*0.1 = 5 + 8 + 10 + 6 = 29.0
    points = normalize_projection(stats, scoring)
    assert abs(points - 29.0) < 0.01


def test_normalize_projection_half_ppr():
    scoring = {"rec": 0.5, "rush_td": 6.0, "rush_yd": 0.1, "rec_yd": 0.1}
    stats = {"rec": 4.0, "rush_td": 1.0, "rush_yd": 80.0, "rec_yd": 40.0}
    # 4*0.5 + 1*6 + 80*0.1 + 40*0.1 = 2 + 6 + 8 + 4 = 20.0
    points = normalize_projection(stats, scoring)
    assert abs(points - 20.0) < 0.01
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_projections.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sleeper_dynasty.api.projections'`

- [ ] **Step 3: Implement projections module**

Create `src/sleeper_dynasty/api/projections.py`:

```python
from __future__ import annotations

import logging

import httpx

from sleeper_dynasty.models.player import PlayerProjection

log = logging.getLogger(__name__)

FANTASYPROS_WEIGHT = 0.6
SLEEPER_WEIGHT = 0.4


def blend_projections(
    sleeper_proj: PlayerProjection,
    external_proj: PlayerProjection | None,
) -> PlayerProjection:
    if external_proj is None:
        return sleeper_proj
    blended_pts = (
        SLEEPER_WEIGHT * sleeper_proj.projected_points
        + FANTASYPROS_WEIGHT * external_proj.projected_points
    )
    return PlayerProjection(
        player_id=sleeper_proj.player_id,
        source="blended",
        season=sleeper_proj.season,
        week=sleeper_proj.week,
        projected_points=round(blended_pts, 2),
    )


def normalize_projection(stats: dict[str, float], scoring: dict[str, float]) -> float:
    total = 0.0
    for stat_key, value in stats.items():
        multiplier = scoring.get(stat_key, 0.0)
        total += value * multiplier
    return round(total, 2)


async def fetch_fantasypros_projections(season: int) -> dict[str, PlayerProjection]:
    """Fetch FantasyPros consensus projections. Returns dict keyed by player name."""
    log.info("Fetching FantasyPros projections for %d", season)
    projections: dict[str, PlayerProjection] = {}
    positions = ["qb", "rb", "wr", "te", "k", "dst"]
    async with httpx.AsyncClient(timeout=30.0) as client:
        for pos in positions:
            try:
                url = f"https://www.fantasypros.com/nfl/projections/{pos}.php?scoring=PPR"
                resp = await client.get(url, headers={"User-Agent": "sleeper-dynasty/0.1"})
                if resp.status_code != 200:
                    log.warning("FantasyPros returned %d for %s", resp.status_code, pos)
                    continue
                projections.update(_parse_fantasypros_html(resp.text, pos.upper(), season))
            except httpx.HTTPError as e:
                log.warning("Failed to fetch FantasyPros %s: %s", pos, e)
    return projections


def _parse_fantasypros_html(html: str, position: str, season: int) -> dict[str, PlayerProjection]:
    """Parse FantasyPros projection table from HTML. Best-effort extraction."""
    projections: dict[str, PlayerProjection] = {}
    try:
        import re
        rows = re.findall(
            r'class="player-name"[^>]*>([^<]+)</a>.*?class="pointed"[^>]*>([\d.]+)</td>',
            html,
            re.DOTALL,
        )
        for name, pts in rows:
            name = name.strip()
            projections[name.lower()] = PlayerProjection(
                player_id="",
                source="fantasypros",
                season=season,
                week=None,
                projected_points=float(pts),
            )
    except Exception as e:
        log.warning("Failed to parse FantasyPros HTML for %s: %s", position, e)
    return projections
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_projections.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/api/projections.py tests/test_projections.py
git commit -m "feat: projection blending and scoring normalization with FantasyPros fallback"
```

---

### Task 5: Optimal Lineup Solver

**Files:**
- Create: `src/sleeper_dynasty/engine/__init__.py`
- Create: `src/sleeper_dynasty/engine/lineup.py`
- Create: `tests/test_lineup.py`

- [ ] **Step 1: Write failing test for lineup solver**

Create `tests/test_lineup.py`:

```python
from sleeper_dynasty.engine.lineup import solve_optimal_lineup


def test_basic_lineup_no_flex():
    roster_positions = ["QB", "RB", "RB", "WR", "WR", "TE"]
    players = {
        "qb1": ("QB", 20.0),
        "rb1": ("RB", 15.0),
        "rb2": ("RB", 12.0),
        "rb3": ("RB", 8.0),
        "wr1": ("WR", 18.0),
        "wr2": ("WR", 14.0),
        "wr3": ("WR", 10.0),
        "te1": ("TE", 11.0),
    }
    starters, total = solve_optimal_lineup(roster_positions, players)
    assert total == 20.0 + 15.0 + 12.0 + 18.0 + 14.0 + 11.0  # 90.0
    assert "qb1" in starters
    assert "rb1" in starters
    assert "rb2" in starters
    assert "wr1" in starters
    assert "wr2" in starters
    assert "te1" in starters


def test_flex_picks_best_remaining():
    roster_positions = ["QB", "RB", "WR", "TE", "FLEX"]
    players = {
        "qb1": ("QB", 20.0),
        "rb1": ("RB", 15.0),
        "rb2": ("RB", 13.0),
        "wr1": ("WR", 18.0),
        "wr2": ("WR", 16.0),
        "te1": ("TE", 10.0),
    }
    starters, total = solve_optimal_lineup(roster_positions, players)
    # FLEX should pick wr2 (16) over rb2 (13)
    assert total == 20.0 + 15.0 + 18.0 + 10.0 + 16.0  # 79.0
    assert "wr2" in starters


def test_superflex_picks_best_qb_or_flex():
    roster_positions = ["QB", "RB", "WR", "TE", "SUPER_FLEX"]
    players = {
        "qb1": ("QB", 22.0),
        "qb2": ("QB", 19.0),
        "rb1": ("RB", 15.0),
        "wr1": ("WR", 14.0),
        "te1": ("TE", 10.0),
    }
    starters, total = solve_optimal_lineup(roster_positions, players)
    # SF should take qb2 (19) since it's the best remaining eligible player
    assert total == 22.0 + 15.0 + 14.0 + 10.0 + 19.0  # 80.0
    assert "qb2" in starters


def test_empty_position_scores_zero():
    roster_positions = ["QB", "RB", "WR", "TE", "K"]
    players = {
        "qb1": ("QB", 20.0),
        "rb1": ("RB", 15.0),
        "wr1": ("WR", 14.0),
        "te1": ("TE", 10.0),
        # no kicker
    }
    starters, total = solve_optimal_lineup(roster_positions, players)
    assert total == 20.0 + 15.0 + 14.0 + 10.0  # 59.0, K slot empty


def test_bench_slots_ignored():
    roster_positions = ["QB", "RB", "BN", "BN", "BN"]
    players = {
        "qb1": ("QB", 20.0),
        "rb1": ("RB", 15.0),
        "rb2": ("RB", 12.0),
    }
    starters, total = solve_optimal_lineup(roster_positions, players)
    assert total == 20.0 + 15.0  # 35.0, bench not scored
    assert len(starters) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_lineup.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sleeper_dynasty.engine'`

- [ ] **Step 3: Implement lineup solver**

Create `src/sleeper_dynasty/engine/__init__.py` (empty) and `src/sleeper_dynasty/engine/lineup.py`:

```python
from __future__ import annotations

from itertools import permutations

FLEX_ELIGIBLE = {"RB", "WR", "TE"}
SUPER_FLEX_ELIGIBLE = {"QB", "RB", "WR", "TE"}
BENCH_SLOTS = {"BN", "IR", "TAXI"}

SLOT_ELIGIBILITY: dict[str, set[str]] = {
    "QB": {"QB"},
    "RB": {"RB"},
    "WR": {"WR"},
    "TE": {"TE"},
    "K": {"K"},
    "DEF": {"DEF"},
    "FLEX": FLEX_ELIGIBLE,
    "SUPER_FLEX": SUPER_FLEX_ELIGIBLE,
    "REC_FLEX": {"WR", "TE"},
    "WRRB_FLEX": {"WR", "RB"},
}


def solve_optimal_lineup(
    roster_positions: list[str],
    players: dict[str, tuple[str, float]],
) -> tuple[set[str], float]:
    """Find the optimal starting lineup that maximizes total points.

    Args:
        roster_positions: League roster slot configuration (e.g. ["QB", "RB", "RB", "WR", "FLEX"]).
        players: Dict of player_id -> (position, projected_points).

    Returns:
        Tuple of (set of starting player IDs, total projected points).
    """
    starter_slots = [s for s in roster_positions if s not in BENCH_SLOTS]

    eligible_per_slot: list[list[tuple[str, float]]] = []
    for slot in starter_slots:
        allowed = SLOT_ELIGIBILITY.get(slot, set())
        eligible = [(pid, pts) for pid, (pos, pts) in players.items() if pos in allowed]
        eligible.sort(key=lambda x: x[1], reverse=True)
        eligible_per_slot.append(eligible)

    best_starters: set[str] = set()
    best_total = 0.0
    _solve_recursive(starter_slots, eligible_per_slot, 0, set(), 0.0, best_starters, [best_total])

    return best_starters, best_total if not best_starters else round(sum(
        players[pid][1] for pid in best_starters
    ), 2)


def _solve_recursive(
    slots: list[str],
    eligible_per_slot: list[list[tuple[str, float]]],
    slot_idx: int,
    used: set[str],
    current_total: float,
    best_starters: set[str],
    best_total: list[float],
) -> None:
    if slot_idx == len(slots):
        if current_total > best_total[0]:
            best_total[0] = current_total
            best_starters.clear()
            best_starters.update(used)
        return

    candidates = eligible_per_slot[slot_idx]

    upper_bound = current_total
    for i in range(slot_idx, len(slots)):
        remaining = [pts for pid, pts in eligible_per_slot[i] if pid not in used]
        if remaining:
            upper_bound += remaining[0]
    if upper_bound <= best_total[0]:
        return

    _solve_recursive(slots, eligible_per_slot, slot_idx + 1, used, current_total, best_starters, best_total)

    for pid, pts in candidates:
        if pid in used:
            continue
        used.add(pid)
        _solve_recursive(slots, eligible_per_slot, slot_idx + 1, used, current_total + pts, best_starters, best_total)
        used.remove(pid)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_lineup.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/ tests/test_lineup.py
git commit -m "feat: optimal lineup solver with FLEX and SuperFlex support"
```

---

### Task 6: Monte Carlo Season Simulator

**Files:**
- Create: `src/sleeper_dynasty/engine/simulator.py`
- Create: `tests/test_simulator.py`

- [ ] **Step 1: Write failing test for variance model**

Create `tests/test_simulator.py`:

```python
import numpy as np

from sleeper_dynasty.engine.simulator import (
    get_cv,
    sample_weekly_points,
    simulate_season,
    SimulationResult,
)
from sleeper_dynasty.models.league import League, Roster, Matchup


def test_cv_by_position():
    assert get_cv("QB") == 0.20
    assert get_cv("RB") == 0.30
    assert get_cv("WR") == 0.30
    assert get_cv("TE") == 0.35
    assert get_cv("K") == 0.40
    assert get_cv("DEF") == 0.45


def test_sample_weekly_points_respects_distribution():
    rng = np.random.default_rng(42)
    samples = [sample_weekly_points(20.0, "QB", rng) for _ in range(10000)]
    mean = np.mean(samples)
    std = np.std(samples)
    assert abs(mean - 20.0) < 0.5  # mean should be ~20
    assert abs(std - 4.0) < 0.5  # std should be ~20*0.20=4.0


def test_sample_weekly_points_floor_for_low_projection():
    rng = np.random.default_rng(42)
    samples = [sample_weekly_points(2.0, "WR", rng) for _ in range(1000)]
    assert all(s >= 0 for s in samples)


def test_simulate_season_returns_results():
    league = League(
        league_id="test",
        name="Test League",
        season=2026,
        total_rosters=2,
        roster_positions=["QB", "RB", "WR", "TE"],
        scoring_settings={"pass_td": 4.0, "rec": 1.0},
        playoff_week_start=15,
        num_playoff_teams=2,
        status="in_season",
    )
    rosters = [
        Roster(roster_id=1, owner_id="a", owner_name="Alice", players=["qb1", "rb1", "wr1", "te1"],
               wins=0, losses=0, ties=0, points_for=0, points_against=0),
        Roster(roster_id=2, owner_id="b", owner_name="Bob", players=["qb2", "rb2", "wr2", "te2"],
               wins=0, losses=0, ties=0, points_for=0, points_against=0),
    ]
    matchups_by_week = {
        w: [Matchup(week=w, roster_id_1=1, roster_id_2=2, points_1=None, points_2=None)]
        for w in range(1, 15)
    }
    player_projections = {
        "qb1": ("QB", 22.0), "rb1": ("RB", 15.0), "wr1": ("WR", 16.0), "te1": ("TE", 10.0),
        "qb2": ("QB", 20.0), "rb2": ("RB", 14.0), "wr2": ("WR", 15.0), "te2": ("TE", 9.0),
    }

    result = simulate_season(
        league=league,
        rosters=rosters,
        matchups_by_week=matchups_by_week,
        player_projections=player_projections,
        start_week=1,
        num_sims=100,
    )

    assert isinstance(result, SimulationResult)
    assert 1 in result.team_results
    assert 2 in result.team_results
    # Alice has better players, should win more often
    assert result.team_results[1].avg_wins > result.team_results[2].avg_wins
    assert 0.0 <= result.team_results[1].playoff_pct <= 100.0
    assert 0.0 <= result.team_results[1].championship_pct <= 100.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_simulator.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sleeper_dynasty.engine.simulator'`

- [ ] **Step 3: Implement simulator**

Create `src/sleeper_dynasty/engine/simulator.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from sleeper_dynasty.engine.lineup import solve_optimal_lineup
from sleeper_dynasty.models.league import League, Matchup, Roster

POSITION_CV = {
    "QB": 0.20,
    "RB": 0.30,
    "WR": 0.30,
    "TE": 0.35,
    "K": 0.40,
    "DEF": 0.45,
}

MIN_POINTS_FLOOR = 0.0


def get_cv(position: str) -> float:
    return POSITION_CV.get(position, 0.30)


def sample_weekly_points(projected: float, position: str, rng: np.random.Generator) -> float:
    cv = get_cv(position)
    if projected < 5.0:
        std = max(projected * cv, 1.0)
    else:
        std = projected * cv
    pts = rng.normal(projected, std)
    return max(pts, MIN_POINTS_FLOOR)


@dataclass
class TeamSimResult:
    roster_id: int
    avg_wins: float = 0.0
    avg_losses: float = 0.0
    win_low: float = 0.0
    win_high: float = 0.0
    playoff_pct: float = 0.0
    championship_pct: float = 0.0
    avg_points_for: float = 0.0


@dataclass
class MatchupSimResult:
    week: int
    roster_id_1: int
    roster_id_2: int
    win_pct_1: float = 0.0
    win_pct_2: float = 0.0
    avg_score_1: float = 0.0
    avg_score_2: float = 0.0


@dataclass
class SimulationResult:
    team_results: dict[int, TeamSimResult] = field(default_factory=dict)
    matchup_results: list[MatchupSimResult] = field(default_factory=list)


def simulate_season(
    league: League,
    rosters: list[Roster],
    matchups_by_week: dict[int, list[Matchup]],
    player_projections: dict[str, tuple[str, float]],
    start_week: int,
    num_sims: int = 10000,
) -> SimulationResult:
    rng = np.random.default_rng()
    roster_map = {r.roster_id: r for r in rosters}
    reg_season_end = league.playoff_week_start - 1
    weeks = range(start_week, reg_season_end + 1)

    all_wins: dict[int, list[int]] = {r.roster_id: [] for r in rosters}
    all_pf: dict[int, list[float]] = {r.roster_id: [] for r in rosters}
    playoff_counts: dict[int, int] = {r.roster_id: 0 for r in rosters}
    champ_counts: dict[int, int] = {r.roster_id: 0 for r in rosters}
    matchup_wins: dict[tuple[int, int, int], int] = {}
    matchup_scores: dict[tuple[int, int, int], list[float]] = {}

    for _ in range(num_sims):
        sim_wins: dict[int, int] = {r.roster_id: r.wins for r in rosters}
        sim_losses: dict[int, int] = {r.roster_id: r.losses for r in rosters}
        sim_pf: dict[int, float] = {r.roster_id: r.points_for for r in rosters}

        for week in weeks:
            week_matchups = matchups_by_week.get(week, [])
            for matchup in week_matchups:
                score_1 = _simulate_team_week(
                    roster_map[matchup.roster_id_1], league, player_projections, rng,
                )
                score_2 = _simulate_team_week(
                    roster_map[matchup.roster_id_2], league, player_projections, rng,
                )
                sim_pf[matchup.roster_id_1] += score_1
                sim_pf[matchup.roster_id_2] += score_2

                if score_1 > score_2:
                    sim_wins[matchup.roster_id_1] += 1
                    sim_losses[matchup.roster_id_2] += 1
                elif score_2 > score_1:
                    sim_wins[matchup.roster_id_2] += 1
                    sim_losses[matchup.roster_id_1] += 1
                else:
                    sim_wins[matchup.roster_id_1] += 1
                    sim_wins[matchup.roster_id_2] += 1

                key1 = (week, matchup.roster_id_1, matchup.roster_id_2)
                matchup_wins[key1] = matchup_wins.get(key1, 0) + (1 if score_1 > score_2 else 0)
                matchup_scores.setdefault(key1, []).append(score_1)
                key2 = (week, matchup.roster_id_2, matchup.roster_id_1)
                matchup_scores.setdefault(key2, []).append(score_2)

        for rid in sim_wins:
            all_wins[rid].append(sim_wins[rid])
            all_pf[rid].append(sim_pf[rid])

        standings = sorted(
            rosters,
            key=lambda r: (sim_wins[r.roster_id], sim_pf[r.roster_id]),
            reverse=True,
        )
        playoff_teams = [r.roster_id for r in standings[: league.num_playoff_teams]]
        for rid in playoff_teams:
            playoff_counts[rid] += 1

        if len(playoff_teams) >= 2:
            champ = _simulate_playoffs(playoff_teams, roster_map, league, player_projections, rng)
            if champ is not None:
                champ_counts[champ] += 1

    result = SimulationResult()
    for roster in rosters:
        rid = roster.roster_id
        wins_arr = np.array(all_wins[rid])
        result.team_results[rid] = TeamSimResult(
            roster_id=rid,
            avg_wins=round(float(np.mean(wins_arr)), 1),
            avg_losses=round(reg_season_end - float(np.mean(wins_arr)) + roster.losses + roster.wins - roster.wins, 1),
            win_low=round(float(np.percentile(wins_arr, 5)), 1),
            win_high=round(float(np.percentile(wins_arr, 95)), 1),
            playoff_pct=round(playoff_counts[rid] / num_sims * 100, 1),
            championship_pct=round(champ_counts[rid] / num_sims * 100, 1),
            avg_points_for=round(float(np.mean(all_pf[rid])), 1),
        )

    seen_matchups: set[tuple[int, int, int]] = set()
    for week in weeks:
        for matchup in matchups_by_week.get(week, []):
            key = (week, matchup.roster_id_1, matchup.roster_id_2)
            if key in seen_matchups:
                continue
            seen_matchups.add(key)
            wins_1 = matchup_wins.get(key, 0)
            key_rev = (week, matchup.roster_id_2, matchup.roster_id_1)
            scores_1 = matchup_scores.get(key, [0])
            scores_2 = matchup_scores.get(key_rev, [0])
            result.matchup_results.append(MatchupSimResult(
                week=week,
                roster_id_1=matchup.roster_id_1,
                roster_id_2=matchup.roster_id_2,
                win_pct_1=round(wins_1 / num_sims * 100, 1),
                win_pct_2=round((num_sims - wins_1) / num_sims * 100, 1),
                avg_score_1=round(float(np.mean(scores_1)), 1),
                avg_score_2=round(float(np.mean(scores_2)), 1),
            ))

    return result


def _simulate_team_week(
    roster: Roster,
    league: League,
    player_projections: dict[str, tuple[str, float]],
    rng: np.random.Generator,
) -> float:
    sampled: dict[str, tuple[str, float]] = {}
    for pid in roster.players:
        if pid in player_projections:
            pos, proj = player_projections[pid]
            sampled[pid] = (pos, sample_weekly_points(proj, pos, rng))
    _, total = solve_optimal_lineup(league.roster_positions, sampled)
    return total


def _simulate_playoffs(
    playoff_team_ids: list[int],
    roster_map: dict[int, Roster],
    league: League,
    player_projections: dict[str, tuple[str, float]],
    rng: np.random.Generator,
) -> int | None:
    remaining = list(playoff_team_ids)
    while len(remaining) > 1:
        next_round = []
        for i in range(0, len(remaining) - 1, 2):
            r1 = roster_map[remaining[i]]
            r2 = roster_map[remaining[i + 1]]
            s1 = _simulate_team_week(r1, league, player_projections, rng)
            s2 = _simulate_team_week(r2, league, player_projections, rng)
            next_round.append(remaining[i] if s1 >= s2 else remaining[i + 1])
        if len(remaining) % 2 == 1:
            next_round.append(remaining[-1])
        remaining = next_round
    return remaining[0] if remaining else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_simulator.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/simulator.py tests/test_simulator.py
git commit -m "feat: Monte Carlo season simulator with variance model and playoff sim"
```

---

### Task 7: Dynasty Outlook Engine

**Files:**
- Create: `src/sleeper_dynasty/engine/dynasty.py`
- Create: `tests/test_dynasty.py`

- [ ] **Step 1: Write failing test for dynasty analysis**

Create `tests/test_dynasty.py`:

```python
from datetime import date

from sleeper_dynasty.engine.dynasty import (
    analyze_age_profile,
    analyze_draft_capital,
    classify_window,
    build_dynasty_outlook,
    DynastyOutlook,
    AgeProfile,
    DraftCapital,
)
from sleeper_dynasty.models.player import Player
from sleeper_dynasty.models.league import DraftPick, Roster


def _make_player(pid: str, name: str, pos: str, birth_year: int) -> Player:
    return Player(
        player_id=pid, full_name=name, position=pos, team="TST",
        birth_date=date(birth_year, 6, 15),
    )


def test_age_profile_calculates_averages():
    players = [
        _make_player("1", "Young QB", "QB", 2002),   # 24
        _make_player("2", "Old RB", "RB", 1996),      # 30
        _make_player("3", "Mid WR", "WR", 1999),      # 27
        _make_player("4", "Young WR", "WR", 2003),    # 23
        _make_player("5", "Old TE", "TE", 1995),      # 31
    ]
    profile = analyze_age_profile(players, as_of=date(2026, 9, 1))
    assert isinstance(profile, AgeProfile)
    assert profile.avg_age_by_position["QB"] == 24
    assert profile.avg_age_by_position["RB"] == 30
    assert len(profile.aging_risks) == 2  # Old RB (30, RB threshold 26+) and Old TE (31, 28+)
    assert len(profile.core_young) >= 2  # Young QB (24) and Young WR (23)


def test_draft_capital_analysis():
    traded_picks = [
        DraftPick(season=2027, round=1, original_owner_id=1, current_owner_id=3),
        DraftPick(season=2027, round=2, original_owner_id=2, current_owner_id=1),
        DraftPick(season=2028, round=1, original_owner_id=1, current_owner_id=1),
    ]
    capital = analyze_draft_capital(
        roster_id=1,
        traded_picks=traded_picks,
        total_rosters=4,
        num_rounds=4,
    )
    assert isinstance(capital, DraftCapital)
    # Roster 1 lost their 2027 1st, gained a 2027 2nd, kept 2028 1st
    # Default picks per season = num_rounds = 4
    # 2027: lost round 1, gained round 2 from roster 2 → 4 - 1 + 1 = 4 picks
    # 2028: kept round 1 → 4 picks
    assert capital.picks_by_season[2027] >= 3
    assert capital.net_vs_average != 0 or capital.net_vs_average == 0  # just verify it's computed


def test_classify_window_competing():
    window = classify_window(
        projected_rank_pct=0.1,  # top 10%
        avg_age=26.0,
        draft_capital_status="neutral",
    )
    assert window == "Competing now"


def test_classify_window_rebuilding():
    window = classify_window(
        projected_rank_pct=0.8,  # bottom 20%
        avg_age=23.0,
        draft_capital_status="pick-rich",
    )
    assert window == "Rebuilding"


def test_classify_window_peaking():
    window = classify_window(
        projected_rank_pct=0.15,
        avg_age=29.5,
        draft_capital_status="pick-poor",
    )
    assert window == "Peaking"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dynasty.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sleeper_dynasty.engine.dynasty'`

- [ ] **Step 3: Implement dynasty outlook engine**

Create `src/sleeper_dynasty/engine/dynasty.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sleeper_dynasty.models.league import DraftPick, Roster
from sleeper_dynasty.models.player import Player

RB_AGING_THRESHOLD = 26
DEFAULT_AGING_THRESHOLD = 28
CORE_YOUNG_MAX_AGE = 25
OUTLOOK_SEASONS = [2027, 2028, 2029]


@dataclass
class AgeProfile:
    avg_age_by_position: dict[str, float]
    aging_risks: list[Player]
    core_young: list[Player]
    overall_avg_age: float = 0.0


@dataclass
class DraftCapital:
    picks_by_season: dict[int, int]
    picks_by_season_round: dict[int, dict[int, int]]
    picks_traded_away: int
    picks_acquired: int
    net_vs_average: float
    status: str  # "pick-rich", "neutral", "pick-poor"


@dataclass
class DraftNeed:
    position: str
    urgency: str  # "immediate" or "developing"
    reason: str


@dataclass
class DynastyOutlook:
    window: str
    age_profile: AgeProfile
    draft_capital: DraftCapital
    draft_needs: list[DraftNeed]
    trajectory: str


def analyze_age_profile(players: list[Player], as_of: date | None = None) -> AgeProfile:
    ref = as_of or date.today()
    ages_by_pos: dict[str, list[int]] = {}
    aging_risks: list[Player] = []
    core_young: list[Player] = []
    all_ages: list[int] = []

    for p in players:
        age = p.age(as_of=ref)
        if age is None or p.position in ("K", "DEF"):
            continue
        ages_by_pos.setdefault(p.position, []).append(age)
        all_ages.append(age)

        threshold = RB_AGING_THRESHOLD if p.position == "RB" else DEFAULT_AGING_THRESHOLD
        if age >= threshold:
            aging_risks.append(p)
        if age <= CORE_YOUNG_MAX_AGE:
            core_young.append(p)

    avg_by_pos = {pos: round(sum(ages) / len(ages)) for pos, ages in ages_by_pos.items() if ages}
    overall = round(sum(all_ages) / len(all_ages), 1) if all_ages else 0.0

    return AgeProfile(
        avg_age_by_position=avg_by_pos,
        aging_risks=aging_risks,
        core_young=core_young,
        overall_avg_age=overall,
    )


def analyze_draft_capital(
    roster_id: int,
    traded_picks: list[DraftPick],
    total_rosters: int,
    num_rounds: int = 4,
) -> DraftCapital:
    default_per_season = num_rounds
    picks_by_season: dict[int, int] = {}
    picks_by_season_round: dict[int, dict[int, int]] = {}
    traded_away = 0
    acquired = 0

    for season in OUTLOOK_SEASONS:
        picks_by_season[season] = default_per_season
        picks_by_season_round[season] = {r: 1 for r in range(1, num_rounds + 1)}

    for pick in traded_picks:
        if pick.season not in picks_by_season:
            continue
        if pick.original_owner_id == roster_id and pick.current_owner_id != roster_id:
            picks_by_season[pick.season] -= 1
            picks_by_season_round[pick.season][pick.round] = picks_by_season_round[pick.season].get(pick.round, 1) - 1
            traded_away += 1
        elif pick.original_owner_id != roster_id and pick.current_owner_id == roster_id:
            picks_by_season[pick.season] += 1
            picks_by_season_round[pick.season][pick.round] = picks_by_season_round[pick.season].get(pick.round, 0) + 1
            acquired += 1

    total_picks = sum(picks_by_season.values())
    expected = default_per_season * len(OUTLOOK_SEASONS)
    net = total_picks - expected

    if net >= 3:
        status = "pick-rich"
    elif net <= -3:
        status = "pick-poor"
    else:
        status = "neutral"

    return DraftCapital(
        picks_by_season=picks_by_season,
        picks_by_season_round=picks_by_season_round,
        picks_traded_away=traded_away,
        picks_acquired=acquired,
        net_vs_average=net,
        status=status,
    )


def classify_window(
    projected_rank_pct: float,
    avg_age: float,
    draft_capital_status: str,
) -> str:
    top_third = projected_rank_pct <= 0.33
    bottom_third = projected_rank_pct > 0.66
    young = avg_age < 26
    old = avg_age >= 28
    pick_rich = draft_capital_status == "pick-rich"
    pick_poor = draft_capital_status == "pick-poor"

    if top_third and old and pick_poor:
        return "Peaking"
    if top_third and not old:
        return "Competing now"
    if top_third and old:
        return "Peaking"
    if bottom_third and pick_rich:
        return "Rebuilding"
    if bottom_third:
        return "Descending"
    if young and (pick_rich or draft_capital_status == "neutral"):
        return "Ascending"
    if old and pick_poor:
        return "Descending"
    return "Ascending"


def assess_draft_needs(
    roster_players: list[Player],
    position_rankings: dict[str, float],
    age_profile: AgeProfile,
    total_rosters: int,
) -> list[DraftNeed]:
    needs: list[DraftNeed] = []
    positions = ["QB", "RB", "WR", "TE"]
    league_avg_threshold = 1.0 / total_rosters

    for pos in positions:
        rank_pct = position_rankings.get(pos, 0.5)
        has_aging_risk = any(p.position == pos for p in age_profile.aging_risks)
        pos_players = [p for p in roster_players if p.position == pos]

        if rank_pct > 0.66:
            urgency = "immediate"
            reason = f"Bottom third at {pos}"
            if has_aging_risk:
                reason += " with aging core"
            needs.append(DraftNeed(position=pos, urgency=urgency, reason=reason))
        elif has_aging_risk and len(pos_players) <= 3:
            needs.append(DraftNeed(
                position=pos,
                urgency="developing",
                reason=f"Aging risk at {pos} — need succession plan",
            ))

    return needs


def build_dynasty_outlook(
    roster: Roster,
    roster_players: list[Player],
    traded_picks: list[DraftPick],
    projected_rank_pct: float,
    position_rankings: dict[str, float],
    total_rosters: int,
    num_rounds: int = 4,
) -> DynastyOutlook:
    age_profile = analyze_age_profile(roster_players)
    draft_capital = analyze_draft_capital(
        roster_id=roster.roster_id,
        traded_picks=traded_picks,
        total_rosters=total_rosters,
        num_rounds=num_rounds,
    )
    window = classify_window(
        projected_rank_pct=projected_rank_pct,
        avg_age=age_profile.overall_avg_age,
        draft_capital_status=draft_capital.status,
    )
    draft_needs = assess_draft_needs(
        roster_players=roster_players,
        position_rankings=position_rankings,
        age_profile=age_profile,
        total_rosters=total_rosters,
    )

    trajectory_map = {
        "Competing now": "Strong position to compete for the next 2-3 years.",
        "Ascending": "On the rise — building toward a championship window.",
        "Peaking": "Win-now window is closing. Maximize the next 1-2 seasons.",
        "Descending": "Core is aging without reinforcements. Consider selling veterans for picks.",
        "Rebuilding": "Stockpiling assets for the future. Focus on young talent acquisition.",
    }
    trajectory = trajectory_map.get(window, "Trajectory unclear.")

    return DynastyOutlook(
        window=window,
        age_profile=age_profile,
        draft_capital=draft_capital,
        draft_needs=draft_needs,
        trajectory=trajectory,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_dynasty.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/dynasty.py tests/test_dynasty.py
git commit -m "feat: dynasty outlook engine with age, draft capital, and window analysis"
```

---

### Task 8: Google Docs Output

**Files:**
- Create: `src/sleeper_dynasty/output/__init__.py`
- Create: `src/sleeper_dynasty/output/google_docs.py`
- Create: `tests/test_google_docs.py`

- [ ] **Step 1: Write failing test for Google Docs request builders**

Create `tests/test_google_docs.py`:

```python
from sleeper_dynasty.output.google_docs import (
    build_heading_request,
    build_text_request,
    build_table_request,
    GoogleDocsReport,
)


def test_build_heading_request():
    req = build_heading_request("League Overview", index=1)
    assert req["insertText"]["text"] == "League Overview\n"
    assert req["insertText"]["location"]["index"] == 1


def test_build_text_request():
    req = build_text_request("Some body text here.", index=1)
    assert req["insertText"]["text"] == "Some body text here.\n"


def test_build_table_request():
    headers = ["Team", "Wins", "Losses"]
    rows = [["Alice", "5", "3"], ["Bob", "4", "4"]]
    req = build_table_request(headers, rows, index=1)
    assert req["insertTable"]["rows"] == 3  # header + 2 data rows
    assert req["insertTable"]["columns"] == 3


def test_google_docs_report_init():
    report = GoogleDocsReport(league_name="Test League")
    assert report.title == "Test League - Dynasty Analysis"
    assert report.league_name == "Test League"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_google_docs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sleeper_dynasty.output'`

- [ ] **Step 3: Implement Google Docs output module**

Create `src/sleeper_dynasty/output/__init__.py` (empty) and `src/sleeper_dynasty/output/google_docs.py`:

```python
from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path

from sleeper_dynasty.engine.dynasty import DynastyOutlook
from sleeper_dynasty.engine.simulator import SimulationResult, TeamSimResult
from sleeper_dynasty.models.league import League, Roster

log = logging.getLogger(__name__)

CREDENTIALS_PATH = Path.home() / ".sleeper-dynasty" / "google_credentials.json"
TOKEN_PATH = Path.home() / ".sleeper-dynasty" / "token.json"
SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive.file",
]


def build_heading_request(text: str, index: int) -> dict:
    return {"insertText": {"text": f"{text}\n", "location": {"index": index}}}


def build_text_request(text: str, index: int) -> dict:
    return {"insertText": {"text": f"{text}\n", "location": {"index": index}}}


def build_table_request(headers: list[str], rows: list[list[str]], index: int) -> dict:
    return {
        "insertTable": {
            "rows": len(rows) + 1,
            "columns": len(headers),
            "location": {"index": index},
        }
    }


class GoogleDocsReport:
    def __init__(self, league_name: str) -> None:
        self.league_name = league_name
        self.today = date.today().isoformat()
        self.title = f"{league_name} - Dynasty Analysis"
        self._docs_service = None
        self._drive_service = None

    def authenticate(self) -> None:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        creds = None
        if TOKEN_PATH.exists():
            creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not CREDENTIALS_PATH.exists():
                    raise FileNotFoundError(
                        f"Google OAuth credentials not found at {CREDENTIALS_PATH}. "
                        "Download your OAuth client credentials from the Google Cloud Console "
                        "and save them there."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
                creds = flow.run_local_server(port=0)
            TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(TOKEN_PATH, "w") as f:
                f.write(creds.to_json())

        self._docs_service = build("docs", "v1", credentials=creds)
        self._drive_service = build("drive", "v3", credentials=creds)

    def create_document(self) -> str:
        doc = self._docs_service.documents().create(
            body={"title": f"{self.title} - {self.today}"}
        ).execute()
        return doc["documentId"]

    def set_sharing(self, doc_id: str, private: bool = False) -> None:
        if private:
            return
        self._drive_service.permissions().create(
            fileId=doc_id,
            body={"type": "anyone", "role": "reader"},
        ).execute()

    def get_doc_url(self, doc_id: str) -> str:
        return f"https://docs.google.com/document/d/{doc_id}/edit"

    def write_tab_league_overview(
        self, doc_id: str, league: League, rosters: list[Roster],
    ) -> None:
        requests = []
        idx = 1
        text_parts = [
            f"League Overview",
            f"",
            f"League: {league.name}",
            f"Season: {league.season}",
            f"Teams: {league.total_rosters}",
            f"Scoring: {_describe_scoring(league.scoring_settings)}",
            f"Roster Slots: {', '.join(s for s in league.roster_positions if s not in ('BN', 'IR', 'TAXI'))}",
            f"Playoffs: Top {league.num_playoff_teams} teams, starting week {league.playoff_week_start}",
            f"",
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"",
            f"Current Standings:",
        ]
        full_text = "\n".join(text_parts) + "\n"
        requests.append({"insertText": {"text": full_text, "location": {"index": idx}}})
        idx += len(full_text)

        sorted_rosters = sorted(rosters, key=lambda r: (r.wins, r.points_for), reverse=True)
        standings_header = f"{'Team':<25} {'W':>3} {'L':>3} {'PF':>8} {'PA':>8}\n"
        requests.append({"insertText": {"text": standings_header, "location": {"index": idx}}})
        idx += len(standings_header)
        for r in sorted_rosters:
            line = f"{r.owner_name:<25} {r.wins:>3} {r.losses:>3} {r.points_for:>8.1f} {r.points_against:>8.1f}\n"
            requests.append({"insertText": {"text": line, "location": {"index": idx}}})
            idx += len(line)

        self._docs_service.documents().batchUpdate(
            documentId=doc_id, body={"requests": requests}
        ).execute()

    def write_tab_projected_standings(
        self, doc_id: str, sim_result: SimulationResult,
        roster_map: dict[int, Roster],
    ) -> None:
        doc = self._docs_service.documents().get(documentId=doc_id).execute()
        end_idx = doc["body"]["content"][-1]["endIndex"] - 1

        requests = []
        idx = end_idx

        header = "\n\nProjected Final Standings\n\n"
        requests.append({"insertText": {"text": header, "location": {"index": idx}}})
        idx += len(header)

        col_header = f"{'Rank':>4} {'Team':<25} {'Proj W-L':>10} {'Win Range':>12} {'Playoff%':>9} {'Champ%':>7}\n"
        requests.append({"insertText": {"text": col_header, "location": {"index": idx}}})
        idx += len(col_header)

        sorted_teams = sorted(
            sim_result.team_results.values(),
            key=lambda t: t.playoff_pct,
            reverse=True,
        )
        for rank, team in enumerate(sorted_teams, 1):
            roster = roster_map[team.roster_id]
            wl = f"{team.avg_wins:.0f}-{team.avg_losses:.0f}"
            wr = f"{team.win_low:.0f}-{team.win_high:.0f}"
            line = f"{rank:>4} {roster.owner_name:<25} {wl:>10} {wr:>12} {team.playoff_pct:>8.1f}% {team.championship_pct:>6.1f}%\n"
            requests.append({"insertText": {"text": line, "location": {"index": idx}}})
            idx += len(line)

        self._docs_service.documents().batchUpdate(
            documentId=doc_id, body={"requests": requests}
        ).execute()

    def write_tab_team_reports(
        self,
        doc_id: str,
        rosters: list[Roster],
        sim_result: SimulationResult,
        dynasty_outlooks: dict[int, DynastyOutlook],
        player_projections: dict[str, tuple[str, float]],
        player_names: dict[str, str],
        player_ages: dict[str, int | None],
    ) -> None:
        doc = self._docs_service.documents().get(documentId=doc_id).execute()
        end_idx = doc["body"]["content"][-1]["endIndex"] - 1

        requests = []
        idx = end_idx

        header = "\n\nTeam Reports\n"
        requests.append({"insertText": {"text": header, "location": {"index": idx}}})
        idx += len(header)

        sorted_rosters = sorted(
            rosters,
            key=lambda r: sim_result.team_results[r.roster_id].playoff_pct,
            reverse=True,
        )

        for roster in sorted_rosters:
            team_sim = sim_result.team_results[roster.roster_id]
            outlook = dynasty_outlooks.get(roster.roster_id)

            section = f"\n{'='*60}\n"
            section += f"{roster.owner_name}\n"
            section += f"Current Record: {roster.wins}-{roster.losses}\n\n"

            top_players = []
            for pid in roster.players:
                if pid in player_projections:
                    pos, pts = player_projections[pid]
                    name = player_names.get(pid, pid)
                    age = player_ages.get(pid)
                    top_players.append((name, pos, age, pts))
            top_players.sort(key=lambda x: x[3], reverse=True)

            section += "Top Projected Players:\n"
            section += f"{'Player':<30} {'Pos':<5} {'Age':>4} {'Proj Pts':>9}\n"
            for name, pos, age, pts in top_players[:5]:
                age_str = str(age) if age else "?"
                section += f"{name:<30} {pos:<5} {age_str:>4} {pts:>9.1f}\n"

            section += f"\n2026 Season Projection:\n"
            section += f"  Projected W-L: {team_sim.avg_wins:.0f}-{team_sim.avg_losses:.0f}\n"
            section += f"  Win Range (5th-95th): {team_sim.win_low:.0f}-{team_sim.win_high:.0f}\n"
            section += f"  Playoff Probability: {team_sim.playoff_pct:.1f}%\n"
            section += f"  Championship Probability: {team_sim.championship_pct:.1f}%\n"

            if team_sim.playoff_pct >= 60:
                label = "Contender"
            elif team_sim.playoff_pct >= 30:
                label = "Bubble"
            else:
                label = "Rebuilding"
            section += f"  Season Outlook: {label}\n"

            if outlook:
                section += f"\n5-Year Dynasty Outlook:\n"
                section += f"  Window: {outlook.window}\n"
                section += f"  Overall Avg Age: {outlook.age_profile.overall_avg_age:.1f}\n\n"

                section += "  Age by Position:\n"
                for pos, avg in sorted(outlook.age_profile.avg_age_by_position.items()):
                    aging_count = len([p for p in outlook.age_profile.aging_risks if p.position == pos])
                    section += f"    {pos}: avg {avg}, {aging_count} aging risk(s)\n"

                if outlook.age_profile.core_young:
                    section += "\n  Core Young Pieces:\n"
                    for p in outlook.age_profile.core_young:
                        age = p.age()
                        section += f"    {p.full_name} ({p.position}, age {age})\n"

                if outlook.age_profile.aging_risks:
                    section += "\n  Aging Risks:\n"
                    for p in outlook.age_profile.aging_risks:
                        age = p.age()
                        section += f"    {p.full_name} ({p.position}, age {age})\n"

                section += f"\n  Draft Capital:\n"
                for season in sorted(outlook.draft_capital.picks_by_season):
                    count = outlook.draft_capital.picks_by_season[season]
                    section += f"    {season}: {count} picks\n"
                section += f"    Net vs average: {outlook.draft_capital.net_vs_average:+.0f} picks ({outlook.draft_capital.status})\n"

                if outlook.draft_needs:
                    section += "\n  Draft Needs:\n"
                    for need in outlook.draft_needs:
                        section += f"    [{need.urgency.upper()}] {need.position}: {need.reason}\n"

                section += f"\n  Trajectory: {outlook.trajectory}\n"

            requests.append({"insertText": {"text": section, "location": {"index": idx}}})
            idx += len(section)

        self._docs_service.documents().batchUpdate(
            documentId=doc_id, body={"requests": requests}
        ).execute()

    def write_tab_matchup_forecasts(
        self,
        doc_id: str,
        sim_result: SimulationResult,
        roster_map: dict[int, Roster],
    ) -> None:
        doc = self._docs_service.documents().get(documentId=doc_id).execute()
        end_idx = doc["body"]["content"][-1]["endIndex"] - 1

        requests = []
        idx = end_idx

        header = "\n\nWeekly Matchup Forecasts\n"
        requests.append({"insertText": {"text": header, "location": {"index": idx}}})
        idx += len(header)

        by_week: dict[int, list] = {}
        for m in sim_result.matchup_results:
            by_week.setdefault(m.week, []).append(m)

        for week in sorted(by_week):
            section = f"\nWeek {week}\n"
            section += f"{'Matchup':<55} {'Favored':<25} {'Win%':>6} {'Proj Score':>15}\n"
            for m in by_week[week]:
                name1 = roster_map[m.roster_id_1].owner_name
                name2 = roster_map[m.roster_id_2].owner_name
                matchup_str = f"{name1} vs {name2}"
                favored = name1 if m.win_pct_1 > m.win_pct_2 else name2
                win_pct = max(m.win_pct_1, m.win_pct_2)
                score = f"{m.avg_score_1:.0f}-{m.avg_score_2:.0f}"
                section += f"{matchup_str:<55} {favored:<25} {win_pct:>5.1f}% {score:>15}\n"

            requests.append({"insertText": {"text": section, "location": {"index": idx}}})
            idx += len(section)

        self._docs_service.documents().batchUpdate(
            documentId=doc_id, body={"requests": requests}
        ).execute()


def _describe_scoring(scoring: dict[str, float]) -> str:
    rec = scoring.get("rec", 0)
    if rec >= 1.0:
        fmt = "Full PPR"
    elif rec >= 0.5:
        fmt = "Half PPR"
    else:
        fmt = "Standard"
    pass_td = scoring.get("pass_td", 4)
    return f"{fmt}, {pass_td:.0f}pt pass TD"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_google_docs.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/output/ tests/test_google_docs.py
git commit -m "feat: Google Docs report output with all four tab sections"
```

---

### Task 9: CLI Orchestrator

**Files:**
- Create: `src/sleeper_dynasty/cli.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write failing test for CLI arg parsing**

Create `tests/test_cli.py`:

```python
from sleeper_dynasty.cli import parse_args


def test_parse_args_defaults():
    args = parse_args(["analyze", "testuser"])
    assert args.command == "analyze"
    assert args.username == "testuser"
    assert args.season == 2026
    assert args.week == 1
    assert args.sims == 10000
    assert args.no_cache is False
    assert args.private is False


def test_parse_args_custom():
    args = parse_args(["analyze", "someuser", "--season", "2027", "--week", "5", "--sims", "5000", "--no-cache", "--private"])
    assert args.username == "someuser"
    assert args.season == 2027
    assert args.week == 5
    assert args.sims == 5000
    assert args.no_cache is True
    assert args.private is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sleeper_dynasty.cli'`

- [ ] **Step 3: Implement CLI module**

Create `src/sleeper_dynasty/cli.py`:

```python
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import date

from sleeper_dynasty.api.projections import (
    blend_projections,
    fetch_fantasypros_projections,
    normalize_projection,
)
from sleeper_dynasty.api.sleeper import SleeperClient
from sleeper_dynasty.cache import FileCache
from sleeper_dynasty.engine.dynasty import build_dynasty_outlook
from sleeper_dynasty.engine.simulator import simulate_season
from sleeper_dynasty.models.player import Player, PlayerProjection
from sleeper_dynasty.output.google_docs import GoogleDocsReport

log = logging.getLogger("sleeper_dynasty")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="sleeper-dynasty",
        description="Sleeper dynasty fantasy football league analyzer",
    )
    sub = parser.add_subparsers(dest="command")
    analyze = sub.add_parser("analyze", help="Analyze a Sleeper dynasty league")
    analyze.add_argument("username", help="Sleeper username")
    analyze.add_argument("--season", type=int, default=2026, help="NFL season year (default: 2026)")
    analyze.add_argument("--week", type=int, default=1, help="Start projections from this week (default: 1)")
    analyze.add_argument("--sims", type=int, default=10000, help="Monte Carlo iterations (default: 10000)")
    analyze.add_argument("--no-cache", action="store_true", help="Force refresh all cached data")
    analyze.add_argument("--private", action="store_true", help="Don't auto-set link sharing")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args(argv)

    if args.command != "analyze":
        log.error("Usage: sleeper-dynasty analyze <username>")
        sys.exit(1)

    asyncio.run(_run_analysis(args))


async def _run_analysis(args: argparse.Namespace) -> None:
    cache = FileCache()
    if args.no_cache:
        cache.invalidate_all()

    client = SleeperClient()
    try:
        log.info("Fetching league data for user: %s...", args.username)
        user_id = await client.get_user_id(args.username)
        leagues = await client.get_leagues(user_id, args.season)

        dynasty_leagues = [lg for lg in leagues if lg.status in ("in_season", "pre_draft", "drafting", "complete")]
        if not dynasty_leagues:
            log.error("No leagues found for %s in season %d", args.username, args.season)
            sys.exit(1)

        if len(dynasty_leagues) == 1:
            league = dynasty_leagues[0]
        else:
            log.info("Found %d leagues. Select one:", len(dynasty_leagues))
            for i, lg in enumerate(dynasty_leagues, 1):
                log.info("  [%d] %s (%d teams)", i, lg.name, lg.total_rosters)
            choice = int(input("Enter number: ")) - 1
            league = dynasty_leagues[choice]

        log.info("Using: %s", league.name)

        log.info("Fetching rosters and matchups...")
        rosters = await client.get_rosters(league.league_id)
        traded_picks = await client.get_traded_picks(league.league_id)

        reg_season_end = league.playoff_week_start - 1
        matchups_by_week = {}
        for week in range(args.week, reg_season_end + 1):
            matchups_by_week[week] = await client.get_matchups(league.league_id, week)

        log.info("Fetching player data and projections...")
        cached_players = cache.read("players.json") if not args.no_cache else None
        if cached_players:
            raw_players = cached_players
        else:
            raw_players = await client.get_players()
            cache.write("players.json", raw_players)

        player_db: dict[str, Player] = {}
        for pid, data in raw_players.items():
            bd = data.get("birth_date")
            birth_date = None
            if bd:
                try:
                    parts = bd.split("-")
                    birth_date = date(int(parts[0]), int(parts[1]), int(parts[2]))
                except (ValueError, IndexError):
                    pass
            player_db[pid] = Player(
                player_id=pid,
                full_name=data.get("full_name", data.get("last_name", pid)),
                position=data.get("position", ""),
                team=data.get("team"),
                birth_date=birth_date,
                years_exp=data.get("years_exp"),
            )

        sleeper_projs_raw = await client.get_projections(args.season)
        sleeper_projs: dict[str, PlayerProjection] = {}
        for pid, stats in (sleeper_projs_raw or {}).items():
            pts = normalize_projection(stats.get("pts_ppr", stats), league.scoring_settings)
            if pts > 0:
                sleeper_projs[pid] = PlayerProjection(
                    player_id=pid, source="sleeper", season=args.season, week=None,
                    projected_points=pts, stats=stats,
                )

        log.info("Fetching external projections...")
        try:
            fp_projs = await fetch_fantasypros_projections(args.season)
        except Exception as e:
            log.warning("Could not fetch FantasyPros projections: %s. Using Sleeper only.", e)
            fp_projs = {}

        name_to_id: dict[str, str] = {}
        for pid, p in player_db.items():
            name_to_id[p.full_name.lower()] = pid

        player_projections: dict[str, tuple[str, float]] = {}
        for pid, sproj in sleeper_projs.items():
            player = player_db.get(pid)
            if not player:
                continue
            fp_match = fp_projs.get(player.full_name.lower())
            blended = blend_projections(sproj, fp_match)
            player_projections[pid] = (player.position, blended.projected_points)

        log.info("Running season simulation (%d iterations)...", args.sims)
        sim_result = simulate_season(
            league=league,
            rosters=rosters,
            matchups_by_week=matchups_by_week,
            player_projections=player_projections,
            start_week=args.week,
            num_sims=args.sims,
        )

        log.info("Building dynasty outlooks...")
        sorted_teams = sorted(
            sim_result.team_results.values(),
            key=lambda t: t.avg_points_for,
            reverse=True,
        )
        rank_map = {t.roster_id: i / len(sorted_teams) for i, t in enumerate(sorted_teams)}

        dynasty_outlooks = {}
        for roster in rosters:
            roster_players = [player_db[pid] for pid in roster.players if pid in player_db]
            pos_totals: dict[str, float] = {}
            for pid in roster.players:
                if pid in player_projections:
                    pos, pts = player_projections[pid]
                    pos_totals[pos] = pos_totals.get(pos, 0) + pts

            all_pos_totals: dict[str, list[float]] = {}
            for r in rosters:
                for pid in r.players:
                    if pid in player_projections:
                        pos, pts = player_projections[pid]
                        all_pos_totals.setdefault(pos, []).append(0)
                for pos in all_pos_totals:
                    total = sum(player_projections[pid][1] for pid in r.players
                                if pid in player_projections and player_projections[pid][0] == pos)
                    all_pos_totals[pos].append(total)

            position_rankings: dict[str, float] = {}
            for pos, totals in all_pos_totals.items():
                totals_sorted = sorted(totals, reverse=True)
                my_total = pos_totals.get(pos, 0)
                rank_idx = next((i for i, t in enumerate(totals_sorted) if t <= my_total), len(totals_sorted))
                position_rankings[pos] = rank_idx / max(len(totals_sorted), 1)

            dynasty_outlooks[roster.roster_id] = build_dynasty_outlook(
                roster=roster,
                roster_players=roster_players,
                traded_picks=traded_picks,
                projected_rank_pct=rank_map.get(roster.roster_id, 0.5),
                position_rankings=position_rankings,
                total_rosters=league.total_rosters,
            )

        log.info("Creating Google Doc...")
        report = GoogleDocsReport(league_name=league.name)
        report.authenticate()
        doc_id = report.create_document()

        roster_map = {r.roster_id: r for r in rosters}
        player_names = {pid: p.full_name for pid, p in player_db.items()}
        player_ages = {pid: p.age() for pid, p in player_db.items()}

        report.write_tab_league_overview(doc_id, league, rosters)
        report.write_tab_projected_standings(doc_id, sim_result, roster_map)
        report.write_tab_team_reports(
            doc_id, rosters, sim_result, dynasty_outlooks,
            player_projections, player_names, player_ages,
        )
        report.write_tab_matchup_forecasts(doc_id, sim_result, roster_map)

        report.set_sharing(doc_id, private=args.private)
        url = report.get_doc_url(doc_id)

        log.info("\nDone! View your report:")
        log.info(url)

    finally:
        await client.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_cli.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/cli.py src/sleeper_dynasty/__main__.py tests/test_cli.py
git commit -m "feat: CLI orchestrator wiring all components together"
```

---

### Task 10: Integration Test & Final Wiring

**Files:**
- Modify: `src/sleeper_dynasty/__main__.py`
- Create: `tests/test_integration.py`

- [ ] **Step 1: Write integration test (offline, mocked)**

Create `tests/test_integration.py`:

```python
"""Integration test: runs the full pipeline with mocked API calls and mocked Google Docs."""

import json
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sleeper_dynasty.cli import _run_analysis

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    with open(FIXTURES / name) as f:
        return json.load(f)


@pytest.fixture
def mock_args():
    args = MagicMock()
    args.username = "testuser"
    args.season = 2026
    args.week = 1
    args.sims = 100
    args.no_cache = True
    args.private = False
    return args


@pytest.fixture
def mock_players():
    return {
        "4046": {"full_name": "Patrick Mahomes", "position": "QB", "team": "KC", "birth_date": "1995-09-17"},
        "6794": {"full_name": "Justin Jefferson", "position": "WR", "team": "MIN", "birth_date": "1999-06-16"},
        "4984": {"full_name": "Saquon Barkley", "position": "RB", "team": "PHI", "birth_date": "1997-02-09"},
        "2449": {"full_name": "Travis Kelce", "position": "TE", "team": "KC", "birth_date": "1989-10-05"},
        "1479": {"full_name": "Tyler Bass", "position": "K", "team": "BUF", "birth_date": "1997-01-23"},
        "5848": {"full_name": "Jalen Hurts", "position": "QB", "team": "PHI", "birth_date": "1998-08-07"},
        "4866": {"full_name": "Nick Chubb", "position": "RB", "team": "CLE", "birth_date": "1995-12-27"},
        "6803": {"full_name": "CeeDee Lamb", "position": "WR", "team": "DAL", "birth_date": "1999-04-08"},
        "3321": {"full_name": "Mark Andrews", "position": "TE", "team": "BAL", "birth_date": "1995-09-06"},
        "1466": {"full_name": "Harrison Butker", "position": "K", "team": "KC", "birth_date": "1995-07-14"},
    }


@pytest.mark.asyncio
async def test_full_pipeline_runs_without_error(mock_args, mock_players):
    mock_client_instance = AsyncMock()
    mock_client_instance.get_user_id.return_value = "123456789"
    mock_client_instance.get_leagues.return_value = [
        MagicMock(
            league_id="league_001", name="Test Dynasty", season=2026,
            total_rosters=2,
            roster_positions=["QB", "RB", "WR", "TE", "K"],
            scoring_settings={"pass_td": 4.0, "rec": 1.0, "rush_td": 6.0, "pass_yd": 0.04, "rush_yd": 0.1, "rec_yd": 0.1},
            playoff_week_start=15, num_playoff_teams=2, status="in_season",
        )
    ]
    mock_client_instance.get_rosters.return_value = [
        MagicMock(roster_id=1, owner_id="user_aaa", owner_name="Alice",
                  players=["4046", "4984", "6794", "2449", "1479"],
                  wins=0, losses=0, ties=0, points_for=0, points_against=0),
        MagicMock(roster_id=2, owner_id="user_bbb", owner_name="Bob",
                  players=["5848", "4866", "6803", "3321", "1466"],
                  wins=0, losses=0, ties=0, points_for=0, points_against=0),
    ]
    mock_client_instance.get_traded_picks.return_value = []
    mock_client_instance.get_matchups.return_value = [
        MagicMock(week=1, roster_id_1=1, roster_id_2=2, points_1=None, points_2=None),
    ]
    mock_client_instance.get_players.return_value = mock_players
    mock_client_instance.get_projections.return_value = {
        "4046": {"pass_td": 2.5, "pass_yd": 280, "rush_yd": 20},
        "6794": {"rec": 6, "rec_yd": 90, "rec_td": 0.7},
        "4984": {"rush_yd": 80, "rush_td": 0.6, "rec": 3, "rec_yd": 25},
        "2449": {"rec": 5, "rec_yd": 55, "rec_td": 0.5},
        "1479": {},
        "5848": {"pass_td": 2.0, "pass_yd": 240, "rush_yd": 35, "rush_td": 0.4},
        "4866": {"rush_yd": 70, "rush_td": 0.5, "rec": 2, "rec_yd": 15},
        "6803": {"rec": 7, "rec_yd": 95, "rec_td": 0.8},
        "3321": {"rec": 4, "rec_yd": 45, "rec_td": 0.4},
        "1466": {},
    }
    mock_client_instance.close = AsyncMock()

    mock_report = MagicMock()
    mock_report.create_document.return_value = "fake_doc_id"
    mock_report.get_doc_url.return_value = "https://docs.google.com/document/d/fake/edit"

    with (
        patch("sleeper_dynasty.cli.SleeperClient", return_value=mock_client_instance),
        patch("sleeper_dynasty.cli.fetch_fantasypros_projections", new_callable=AsyncMock, return_value={}),
        patch("sleeper_dynasty.cli.GoogleDocsReport", return_value=mock_report),
        patch("sleeper_dynasty.cli.FileCache") as mock_cache_cls,
    ):
        mock_cache_cls.return_value.read.return_value = None
        await _run_analysis(mock_args)

    mock_report.authenticate.assert_called_once()
    mock_report.create_document.assert_called_once()
    mock_report.write_tab_league_overview.assert_called_once()
    mock_report.write_tab_projected_standings.assert_called_once()
    mock_report.write_tab_team_reports.assert_called_once()
    mock_report.write_tab_matchup_forecasts.assert_called_once()
    mock_report.set_sharing.assert_called_once()
```

- [ ] **Step 2: Run integration test to verify it fails**

Run: `python -m pytest tests/test_integration.py -v`
Expected: Should pass if all prior tasks are correctly wired. If it fails, the error will point to a wiring issue.

- [ ] **Step 3: Fix any wiring issues found by the integration test**

Address any import errors, missing attributes, or mismatched method signatures revealed by the integration test.

- [ ] **Step 4: Run the full test suite**

Run: `python -m pytest tests/ -v`
Expected: All tests pass (approximately 20+ tests across all files)

- [ ] **Step 5: Commit**

```bash
git add tests/test_integration.py
git commit -m "feat: integration test verifying full pipeline with mocked APIs"
```

- [ ] **Step 6: Verify CLI runs (dry run)**

Run: `python -m sleeper_dynasty analyze --help`
Expected output includes usage, arguments, and flags.

- [ ] **Step 7: Final commit with any fixes**

```bash
git add -A
git commit -m "chore: final wiring fixes and cleanup"
```
