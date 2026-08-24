from datetime import date

from app.services.ktc_snapshot_store import KtcSnapshotStore
from sleeper_dynasty.models.player import KTCValue


def _v(name: str, sf: int) -> KTCValue:
    return KTCValue(name=name, normalized_name=name.lower(),
                    position="WR", superflex_value=sf)


def test_value_extremes_min_max_across_snapshots(tmp_path):
    store = KtcSnapshotStore(cache_dir=tmp_path)
    store.capture({"a": _v("Aida", 3000)}, date(2026, 5, 1))
    store.capture({"a": _v("Aida", 5000)}, date(2026, 5, 8))
    store.capture({"a": _v("Aida", 4200)}, date(2026, 5, 15))
    ext = store.value_extremes()
    assert ext["aida"] == (3000.0, 5000.0)


def test_value_extremes_empty_when_no_snapshots(tmp_path):
    store = KtcSnapshotStore(cache_dir=tmp_path)
    assert store.value_extremes() == {}


def test_value_extremes_ignores_none_values(tmp_path):
    store = KtcSnapshotStore(cache_dir=tmp_path)
    store.capture({"a": _v("Aida", 3000)}, date(2026, 5, 1))
    store.capture({"b": KTCValue(name="Bo", normalized_name="bo",
                                 position="RB", superflex_value=None)},
                  date(2026, 5, 8))
    ext = store.value_extremes()
    assert ext["aida"] == (3000.0, 3000.0)
    assert "bo" not in ext
