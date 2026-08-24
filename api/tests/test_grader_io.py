from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.grader_io import _assemble_played_matchups, pull_supporting_data
from app.services.league_raw_cache import LeagueRawCache


def test_assemble_played_matchups_skips_zero_point_placeholders():
    raw_per_week = {
        3: [
            {"matchup_id": 1, "roster_id": 1, "points": 105.5,
             "starters": ["p1"], "players": ["p1"],
             "players_points": {"p1": 22.0}},
            {"matchup_id": 1, "roster_id": 2, "points": 92.0,
             "starters": ["p2"], "players": ["p2"],
             "players_points": {"p2": 14.0}},
        ],
        4: [
            {"matchup_id": 2, "roster_id": 1, "points": 0.0,
             "starters": ["p1"], "players": ["p1"],
             "players_points": {"p1": 0.0}},
            {"matchup_id": 2, "roster_id": 2, "points": 0.0,
             "starters": ["p2"], "players": ["p2"],
             "players_points": {"p2": 0.0}},
        ],
    }
    out = _assemble_played_matchups(raw_per_week, league_id="L")
    assert ("L", 3, 1) in out
    assert ("L", 4, 1) not in out


def test_assemble_played_matchups_counts_one_sided_shutout():
    raw_per_week = {
        5: [
            {"matchup_id": 1, "roster_id": 1, "points": 80.0,
             "starters": [], "players": [], "players_points": {}},
            {"matchup_id": 1, "roster_id": 2, "points": 0.0,
             "starters": [], "players": [], "players_points": {}},
        ],
    }
    out = _assemble_played_matchups(raw_per_week, league_id="L")
    assert ("L", 5, 1) in out
    assert ("L", 5, 2) in out


def test_assemble_played_matchups_carries_opponent_roster_id():
    """Each roster-week records its opponent's roster_id so head-to-head records
    can resolve the opposing owner (the backend matchup path, used in prod)."""
    raw_per_week = {
        6: [
            {"matchup_id": 1, "roster_id": 1, "points": 100.0,
             "starters": [], "players": [], "players_points": {}},
            {"matchup_id": 1, "roster_id": 2, "points": 90.0,
             "starters": [], "players": [], "players_points": {}},
        ],
    }
    out = _assemble_played_matchups(raw_per_week, league_id="L")
    assert out[("L", 6, 1)]["opponent_roster_id"] == 2
    assert out[("L", 6, 2)]["opponent_roster_id"] == 1


@pytest.mark.asyncio
async def test_sealed_league_matchups_served_from_cache(tmp_path, monkeypatch):
    # Stub the global value fetchers so we isolate the per-league path.
    import app.services.grader_io as mod
    async def _no_ktc(): return {}
    async def _no_fc(*, dynasty=True): return {}
    monkeypatch.setattr(mod, "fetch_ktc_values", _no_ktc)
    monkeypatch.setattr(mod, "fetch_fantasycalc_values", _no_fc)

    from app.services.league_raw_cache import LeagueRawCache
    cache = LeagueRawCache(cache_dir=tmp_path)
    cache.write_matchup_bundle("L1", {
        "matchups": {("L1", 5, 1): {"starters": ["p1"], "players": ["p1"],
                                    "players_points": {"p1": 20.0},
                                    "team_points": 100.0, "opponent_points": 90.0}},
        "playoff_week_start": 15,
        "roster_to_user": {1: "u_a"},
        "league_name": "Bros",
        "season": 2024,
        "owners": {"u_a": {"owner_name": "Alice", "team_name": None, "avatar_url": None}},
        "winners_bracket": [],
        "losers_bracket": [],
        "playoff_round_type": 0,
    })

    from types import SimpleNamespace
    class SealedMatchupClient:
        async def get_players(self):
            raise AssertionError("get_players called despite players= passed")
        async def get_rosters(self, lid): raise AssertionError("network hit (rosters)")
        async def get_users(self, lid): raise AssertionError("network hit (users)")
        async def get_raw_matchups(self, lid, week):
            raise AssertionError("network hit (matchups)")

    sealed = SimpleNamespace(league_id="L1", season=2024, name="Bros",
                             playoff_week_start=15, status="complete", format="dynasty")
    out = await pull_supporting_data(
        SealedMatchupClient(), [sealed],
        players={}, league_cache=cache,
    )
    assert out["matchups"][("L1", 5, 1)]["players_points"] == {"p1": 20.0}
    assert out["roster_to_user_by_league"]["L1"] == {1: "u_a"}
    assert out["playoff_weeks_by_league"]["L1"] == 15
    assert out["league_season_by_id"]["L1"] == 2024
    assert out["owners"]["u_a"]["owner_name"] == "Alice"


def test_resolve_ktc_to_player_id_matches_by_name():
    from app.services.grader_io import resolve_ktc_to_player_id
    from sleeper_dynasty.models.player import KTCValue

    ktc = {"josh allen": KTCValue(name="Josh Allen", normalized_name="josh allen",
                                  position="QB", superflex_value=8000, one_qb_value=7900)}
    raw_players = {"p_allen": {"full_name": "Josh Allen", "position": "QB"},
                   "p_other": {"full_name": "Nobody KTC", "position": "WR"}}
    out = resolve_ktc_to_player_id(ktc, raw_players)
    assert out["p_allen"].superflex_value == 8000
    assert "p_other" not in out


@pytest.mark.asyncio
async def test_pull_supporting_data_captures_snapshot(tmp_path, monkeypatch):
    import app.services.grader_io as mod
    async def _ktc():
        from sleeper_dynasty.models.player import KTCValue
        return {"josh allen": KTCValue(name="Josh Allen", normalized_name="josh allen",
                                       position="QB", superflex_value=8000, one_qb_value=7900)}
    async def _fc(*, dynasty=True): return {}
    monkeypatch.setattr(mod, "fetch_ktc_values", _ktc)
    monkeypatch.setattr(mod, "fetch_fantasycalc_values", _fc)

    from app.services.ktc_snapshot_store import KtcSnapshotStore
    store = KtcSnapshotStore(cache_dir=tmp_path)

    class _StubClientNoLeagues:
        async def get_players(self): return {}

    await pull_supporting_data(_StubClientNoLeagues(), [],
                               players={"p_allen": {"full_name": "Josh Allen"}},
                               snapshot_store=store)
    assert len(store.list_dates()) == 1   # today's snapshot written


# ---------------------------------------------------------------------------
# T7 — phase map wired through pull_supporting_data
# ---------------------------------------------------------------------------

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

LID = "league_2025"


@pytest.mark.asyncio
async def test_phase_map_built_from_brackets(monkeypatch):
    """pull_supporting_data builds phase_by_lwr from winners/losers brackets."""
    import app.services.grader_io as mod

    async def _no_ktc():
        return {}

    async def _no_fc(*, dynasty=True):
        return {}

    monkeypatch.setattr(mod, "fetch_ktc_values", _no_ktc)
    monkeypatch.setattr(mod, "fetch_fantasycalc_values", _no_fc)

    # Fake HTTP responses for matchup weeks (all empty — we only care about phases)
    class _FakeHTTPResp:
        def raise_for_status(self): pass
        def json(self): return []

    class _FakeHTTPClient:
        async def get(self, url):
            return _FakeHTTPResp()

    class _FakeBracketClient:
        async def get_raw_matchups(self, lid, week):
            return []

        async def get_rosters(self, lid):
            return [SimpleNamespace(roster_id=6, owner_id="u6"),
                    SimpleNamespace(roster_id=9, owner_id="u9")]

        async def get_users(self, lid):
            return {
                "u6": {"display_name": "Owner6", "team_name": None, "avatar_url": None},
                "u9": {"display_name": "Owner9", "team_name": None, "avatar_url": None},
            }

        async def get_winners_bracket(self, lid):
            return WINNERS_2025

        async def get_losers_bracket(self, lid):
            return LOSERS_2025

        async def get_players(self):
            return {}

    lg = SimpleNamespace(
        league_id=LID, season=2025, name="Test League",
        playoff_week_start=15, status="in_season",
        playoff_round_type=0, format="dynasty",
    )

    out = await pull_supporting_data(_FakeBracketClient(), [lg], players={})

    phase = out["phase_by_lwr"]

    # Winners round 1 (week 15), roster 6 is title-path → playoff
    assert phase.get((LID, 15, 6)) == "playoff", (
        f"Expected 'playoff' for (LID, 15, 6), got {phase.get((LID, 15, 6))!r}"
    )

    # Losers round 1 (week 15), roster 9 → toilet
    assert phase.get((LID, 15, 9)) == "toilet", (
        f"Expected 'toilet' for (LID, 15, 9), got {phase.get((LID, 15, 9))!r}"
    )

    # Roster 8 also in losers round 1 (week 15) → toilet
    assert phase.get((LID, 15, 8)) == "toilet"
