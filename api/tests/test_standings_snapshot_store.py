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
