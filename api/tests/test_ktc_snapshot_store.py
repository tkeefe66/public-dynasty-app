from __future__ import annotations

from datetime import date

from app.services.ktc_snapshot_store import KtcSnapshotStore
from sleeper_dynasty.models.player import KTCValue


def _vals(qb=8000):
    return {
        "josh allen": KTCValue(name="Josh Allen", normalized_name="josh allen",
                               position="QB", superflex_value=qb, one_qb_value=qb - 100),
        "2027 1st": KTCValue(name="2027 Early 1st", normalized_name="2027 early 1st",
                             position="PICK", superflex_value=6000, one_qb_value=5800),
    }


def test_capture_writes_once_per_day(tmp_path):
    store = KtcSnapshotStore(cache_dir=tmp_path)
    assert store.capture(_vals(), date(2026, 5, 31)) is True
    assert store.capture(_vals(qb=1), date(2026, 5, 31)) is False  # already exists
    snap = store._load(store._path(date(2026, 5, 31)))
    assert snap["josh allen"].superflex_value == 8000  # not overwritten


def test_capture_skips_empty(tmp_path):
    store = KtcSnapshotStore(cache_dir=tmp_path)
    assert store.capture({}, date(2026, 5, 31)) is False
    assert store.list_dates() == []


def test_match_returns_latest_on_or_before(tmp_path):
    store = KtcSnapshotStore(cache_dir=tmp_path)
    store.capture(_vals(qb=7000), date(2026, 5, 20))
    store.capture(_vals(qb=8000), date(2026, 5, 28))
    snap, d, approx = store.match(date(2026, 5, 30), cutoff=date(2026, 5, 1))
    assert d == date(2026, 5, 28) and approx is False
    assert snap["josh allen"].superflex_value == 8000


def test_match_backfill_uses_earliest_when_post_cutoff(tmp_path):
    store = KtcSnapshotStore(cache_dir=tmp_path)
    store.capture(_vals(), date(2026, 5, 31))           # only a later snapshot exists
    snap, d, approx = store.match(date(2026, 5, 3), cutoff=date(2026, 5, 1))
    assert d == date(2026, 5, 31) and approx is True    # earliest, flagged approx
    assert snap is not None


def test_match_blank_before_cutoff(tmp_path):
    store = KtcSnapshotStore(cache_dir=tmp_path)
    store.capture(_vals(), date(2026, 5, 31))
    snap, d, approx = store.match(date(2026, 3, 15), cutoff=date(2026, 5, 1))
    assert snap is None and d is None and approx is False


def test_corrupt_file_ignored(tmp_path):
    store = KtcSnapshotStore(cache_dir=tmp_path)
    store.capture(_vals(), date(2026, 5, 31))
    (tmp_path / "snapshots" / "ktc_2026-05-31.json").write_text("{ not json")
    assert store.match(date(2026, 5, 31), cutoff=date(2026, 5, 1)) == (None, None, False)
