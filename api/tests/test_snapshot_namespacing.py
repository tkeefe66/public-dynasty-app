"""Redraft snapshots must accrue in their own namespace.

The Critical finding during the redraft build was that `KtcSnapshotStore` is
scoped per *install*, not per league, so dynasty prices reached redraft grades.
That was closed by handing redraft chains no store at all — correct, but it also
meant redraft leagues could never accrue at-trade history.

This is the deferred half: a source-namespaced store, so redraft values are
captured and matched without ever touching the dynasty table. Values are only
ever read back from the same namespace they were written to.
"""

from datetime import date

from app.services.ktc_snapshot_store import KtcSnapshotStore
from sleeper_dynasty.models.player import KTCValue


def _val(name: str, sf: int) -> KTCValue:
    return KTCValue(
        name=name, normalized_name=name.lower(), position="WR",
        superflex_value=sf, one_qb_value=sf,
    )


def test_default_namespace_is_unchanged(tmp_path):
    """Existing installs keep writing to snapshots/ktc_*.json — no migration."""
    store = KtcSnapshotStore(cache_dir=tmp_path)
    store.capture({"a": _val("A", 100)}, date(2026, 1, 2))
    assert (tmp_path / "snapshots" / "ktc_2026-01-02.json").exists()


def test_redraft_namespace_is_a_separate_directory(tmp_path):
    redraft = KtcSnapshotStore(cache_dir=tmp_path, source="redraft")
    redraft.capture({"a": _val("A", 100)}, date(2026, 1, 2))
    assert (tmp_path / "snapshots-redraft" / "ktc_2026-01-02.json").exists()
    # ...and did not land in the dynasty namespace.
    assert not (tmp_path / "snapshots" / "ktc_2026-01-02.json").exists()


def test_namespaces_do_not_read_each_others_values(tmp_path):
    """The whole point: a dynasty price must never surface for a redraft league."""
    dynasty = KtcSnapshotStore(cache_dir=tmp_path)
    redraft = KtcSnapshotStore(cache_dir=tmp_path, source="redraft")
    dynasty.capture({"a": _val("Bijan", 9000)}, date(2026, 1, 2))
    redraft.capture({"a": _val("Bijan", 4000)}, date(2026, 1, 2))

    assert dynasty.list_dates() == [date(2026, 1, 2)]
    assert redraft.list_dates() == [date(2026, 1, 2)]
    cutoff = date(2026, 1, 1)
    d_snap, _, _ = dynasty.match(date(2026, 1, 2), cutoff)
    r_snap, _, _ = redraft.match(date(2026, 1, 2), cutoff)
    assert d_snap and d_snap["bijan"].superflex_value == 9000
    assert r_snap and r_snap["bijan"].superflex_value == 4000


def test_an_empty_redraft_namespace_matches_nothing(tmp_path):
    """Day one: no snapshots yet, so callers fall back to live values rather
    than borrowing the dynasty table."""
    redraft = KtcSnapshotStore(cache_dir=tmp_path, source="redraft")
    KtcSnapshotStore(cache_dir=tmp_path).capture({"a": _val("A", 100)}, date(2026, 1, 2))
    assert redraft.list_dates() == []
    assert redraft.match(date(2026, 1, 2), date(2026, 1, 1)) == (None, None, False)
