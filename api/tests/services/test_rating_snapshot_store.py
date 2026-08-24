from __future__ import annotations

from app.services.rating_snapshot_store import RatingSnapshotStore


def test_write_then_read_round_trips(tmp_path):
    store = RatingSnapshotStore(cache_dir=tmp_path)
    store.write("L1", "2024-09", {"u_a": 1700, "u_b": 1300}, model="v2_dynasty")
    assert store.read("L1") == {"v2_dynasty:2024-09": {"u_a": 1700, "u_b": 1300}}


def test_read_absent_is_empty(tmp_path):
    store = RatingSnapshotStore(cache_dir=tmp_path)
    assert store.read("nope") == {}
    assert store.latest_before("nope", "2024-09", model="v2_dynasty") == {}


def test_second_week_appends_key(tmp_path):
    store = RatingSnapshotStore(cache_dir=tmp_path)
    store.write("L1", "2024-09", {"u_a": 1600}, model="v2_dynasty")
    store.write("L1", "2024-10", {"u_a": 1650}, model="v2_dynasty")
    data = store.read("L1")
    assert set(data) == {"v2_dynasty:2024-09", "v2_dynasty:2024-10"}
    assert data["v2_dynasty:2024-10"] == {"u_a": 1650}


def test_write_same_week_overwrites(tmp_path):
    store = RatingSnapshotStore(cache_dir=tmp_path)
    store.write("L1", "2024-09", {"u_a": 1600}, model="v2_dynasty")
    store.write("L1", "2024-09", {"u_a": 1700}, model="v2_dynasty")
    assert store.read("L1") == {"v2_dynasty:2024-09": {"u_a": 1700}}


def test_latest_before_returns_most_recent_earlier_week(tmp_path):
    store = RatingSnapshotStore(cache_dir=tmp_path)
    store.write("L1", "2024-08", {"u_a": 1500}, model="v2_dynasty")
    store.write("L1", "2024-09", {"u_a": 1600}, model="v2_dynasty")
    store.write("L1", "2024-11", {"u_a": 1800}, model="v2_dynasty")
    # strictly before 2024-11 -> 2024-09
    assert store.latest_before("L1", "2024-11", model="v2_dynasty") == {"u_a": 1600}
    # strictly before 2024-09 -> 2024-08
    assert store.latest_before("L1", "2024-09", model="v2_dynasty") == {"u_a": 1500}
    # nothing before the earliest
    assert store.latest_before("L1", "2024-08", model="v2_dynasty") == {}


def test_history_capped_at_20_weeks(tmp_path):
    store = RatingSnapshotStore(cache_dir=tmp_path)
    for i in range(1, 26):  # 25 weeks across two seasons
        store.write("L1", f"2024-{i:02d}", {"u_a": 1500 + i}, model="v2_dynasty")
    data = store.read("L1")
    assert len(data) == 20
    # oldest keys trimmed; newest retained
    assert "v2_dynasty:2024-25" in data
    assert "v2_dynasty:2024-01" not in data


def test_latest_before_ignores_a_different_model(tmp_path):
    # A v1 rating and a v2 rating are not comparable quantities -- a snapshot
    # written under one model must never surface as another model's trend
    # baseline, even though both are stored in the same per-league file.
    store = RatingSnapshotStore(tmp_path)
    store.write("L", "2025-14", {"ua": 1600}, model="results_led")
    assert store.latest_before("L", "2026-01", model="v2_dynasty") == {}


def test_latest_before_finds_the_same_model(tmp_path):
    store = RatingSnapshotStore(tmp_path)
    store.write("L", "2026-01", {"ua": 1450}, model="v2_dynasty")
    assert store.latest_before("L", "2026-02", model="v2_dynasty") == {"ua": 1450}
