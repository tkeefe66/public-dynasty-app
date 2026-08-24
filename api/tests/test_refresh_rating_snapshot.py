from __future__ import annotations

import asyncio
from pathlib import Path

from app.services.chain_cache import ChainCacheEntry
from app.services.rating_snapshot_store import RatingSnapshotStore
from app.services import refresh_service


def _entry() -> ChainCacheEntry:
    return ChainCacheEntry(
        league_id="L1",
        chain=[{"league_id": "L1", "season": 2024, "name": "Bros",
                "total_rosters": 3, "playoff_week_start": 15}],
        resolved_trades=[
            {"trade": {"transaction_id": "tx", "league_id": "L1", "season": 2024,
                       "week": 2, "traded_at": "2024-09-12T00:00:00+00:00",
                       "sides": {}}, "sides": {}},
        ],
        grades={
            "tx": {
                "snapshot_value_swing": {"u_a": 1000.0, "u_b": 0.0, "u_c": -1000.0},
                "received_ktc": {"u_a": 1000.0, "u_b": 0.0, "u_c": -1000.0},
                "production_total": {"u_a": 800.0, "u_b": 0.0, "u_c": -800.0},
                "production_regular": {"u_a": 800.0, "u_b": 0.0, "u_c": -800.0},
                "production_toilet": {"u_a": 0.0, "u_b": 0.0, "u_c": 0.0},
                "production_playoff": {"u_a": 400.0, "u_b": 0.0, "u_c": -400.0},
            },
        },
        owners={
            "u_a": {"owner_name": "A", "team_name": None, "avatar_url": None},
            "u_b": {"owner_name": "B", "team_name": None, "avatar_url": None},
            "u_c": {"owner_name": "C", "team_name": None, "avatar_url": None},
        },
        playoff_weeks_by_league={"L1": 15},
        roster_to_user_by_league={"L1": {1: "u_a", 2: "u_b", 3: "u_c"}},
        league_name_by_id={"L1": "Bros"},
        league_season_by_id={"L1": 2024},
        cached_at="2024-09-12T00:00:00Z",
        warnings=[],
        # v2 tree signals, symmetric around u_b so it sits exactly at the
        # 1500 base (mean of a/b/c == b's own value on every signal) while
        # a/c still diverge above/below it -- the shape the a>b>c assertion
        # below needs now that the old skill-pillar (net_ktc-derived) signal
        # is gone.
        outcome_signals={
            "u_a": {"expected_wins": 0.7, "playoff_success": 0.8, "luck": 0.2},
            "u_b": {"expected_wins": 0.5, "playoff_success": 0.5, "luck": 0.0},
            "u_c": {"expected_wins": 0.3, "playoff_success": 0.2, "luck": -0.2},
        },
        outlook_signals={
            "u_a": {"roster_value_share": 0.6, "young_core_share": 0.6, "draft_capital": 0.6},
            "u_b": {"roster_value_share": 0.4, "young_core_share": 0.4, "draft_capital": 0.4},
            "u_c": {"roster_value_share": 0.2, "young_core_share": 0.2, "draft_capital": 0.2},
        },
        # A completed 2024 for all three: live_ratings rates only owners with a
        # season behind them (franchise_redesign.rated_owners), so without this
        # the league is unrated and the snapshot is empty.
        season_records={
            "2024": {
                "u_a": {"wins": 10, "losses": 4, "ties": 0},
                "u_b": {"wins": 7, "losses": 7, "ties": 0},
                "u_c": {"wins": 4, "losses": 10, "ties": 0},
            },
        },
    )


class _FakeGrader:
    def __init__(self, entry):
        self._entry = entry

    async def run(self, **kwargs):
        return self._entry


def _patch_grader(monkeypatch, entry):
    monkeypatch.setattr(
        refresh_service, "GraderService", lambda: _FakeGrader(entry)
    )


def test_refresh_writes_rating_snapshot_keyed_by_nfl_week(tmp_path: Path, monkeypatch):
    entry = _entry()
    _patch_grader(monkeypatch, entry)

    class Client:
        async def get_nfl_state(self):
            return {"season": 2024, "week": 9}

    asyncio.run(refresh_service.refresh_league(
        Client(), "L1", cache_dir=tmp_path))

    data = RatingSnapshotStore(cache_dir=tmp_path).read("L1")
    # Stored under the v2_dynasty model prefix (entry.capabilities is empty
    # here, which reads as full dynasty) -- see rating_snapshot_store.py's
    # module docstring for why the model is part of the key.
    assert "v2_dynasty:2024-09" in data
    snap = data["v2_dynasty:2024-09"]
    assert set(snap) == {"u_a", "u_b", "u_c"}
    assert all(isinstance(v, int) for v in snap.values())
    # symmetric league: u_b sits at base, u_a tops, u_c bottoms
    assert snap["u_a"] > snap["u_b"] > snap["u_c"]
    assert snap["u_b"] == 1500


def test_refresh_without_nfl_state_skips_snapshot(tmp_path: Path, monkeypatch):
    entry = _entry()
    _patch_grader(monkeypatch, entry)

    class Client:  # no get_nfl_state attribute
        pass

    # Must not raise, and must not write a snapshot file.
    asyncio.run(refresh_service.refresh_league(
        Client(), "L1", cache_dir=tmp_path))
    assert RatingSnapshotStore(cache_dir=tmp_path).read("L1") == {}


def test_refresh_snapshot_failure_does_not_fail_refresh(tmp_path: Path, monkeypatch):
    entry = _entry()
    _patch_grader(monkeypatch, entry)

    class Client:
        async def get_nfl_state(self):
            raise RuntimeError("boom")

    # Refresh still completes and returns the entry.
    result = asyncio.run(refresh_service.refresh_league(
        Client(), "L1", cache_dir=tmp_path))
    assert result.league_id == "L1"
    assert RatingSnapshotStore(cache_dir=tmp_path).read("L1") == {}
