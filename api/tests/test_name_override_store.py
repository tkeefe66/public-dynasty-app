from pathlib import Path
from app.services.name_override_store import NameOverrideStore


def test_read_returns_empty_dict_when_file_absent(tmp_path):
    store = NameOverrideStore(cache_dir=tmp_path)
    assert store.read("L1") == {}


def test_write_then_read_round_trips(tmp_path):
    store = NameOverrideStore(cache_dir=tmp_path)
    overrides = {"u_tom": "Tom", "u_jake": "Jake"}
    store.write("L1", overrides)
    assert store.read("L1") == overrides


def test_write_creates_parent_dir(tmp_path):
    deep = tmp_path / "nested" / "dir"
    store = NameOverrideStore(cache_dir=deep)
    store.write("L1", {"u_tom": "Tom"})
    assert store.read("L1") == {"u_tom": "Tom"}


def test_write_overwrites_previous(tmp_path):
    store = NameOverrideStore(cache_dir=tmp_path)
    store.write("L1", {"u_tom": "Tommy"})
    store.write("L1", {"u_tom": "Tom"})
    assert store.read("L1") == {"u_tom": "Tom"}


def test_separate_leagues_dont_collide(tmp_path):
    store = NameOverrideStore(cache_dir=tmp_path)
    store.write("L1", {"u_tom": "Tom"})
    store.write("L2", {"u_tom": "Thomas"})
    assert store.read("L1") == {"u_tom": "Tom"}
    assert store.read("L2") == {"u_tom": "Thomas"}


def test_read_returns_empty_dict_on_corrupt_json(tmp_path):
    store = NameOverrideStore(cache_dir=tmp_path)
    (tmp_path / "owner_name_overrides_L1.json").write_text("not valid json{{{")
    assert store.read("L1") == {}


from app.services.identity import apply_name_overrides
from app.services.chain_cache import ChainCacheEntry


def _make_entry(owners: dict) -> ChainCacheEntry:
    return ChainCacheEntry(
        league_id="L1",
        chain=[],
        resolved_trades=[],
        grades={},
        owners=owners,
        playoff_weeks_by_league={},
        roster_to_user_by_league={},
        league_name_by_id={},
        league_season_by_id={},
        cached_at="2026-01-01T00:00:00Z",
    )


def test_apply_name_overrides_mutates_owner_name():
    entry = _make_entry({"u_tom": {"owner_name": "tkeefe66", "team_name": None, "avatar_url": None}})
    apply_name_overrides(entry, {"u_tom": "Tom"})
    assert entry.owners["u_tom"]["owner_name"] == "Tom"


def test_apply_name_overrides_ignores_unknown_uids():
    entry = _make_entry({"u_tom": {"owner_name": "tkeefe66", "team_name": None, "avatar_url": None}})
    apply_name_overrides(entry, {"u_unknown": "Ghost"})
    assert entry.owners["u_tom"]["owner_name"] == "tkeefe66"


def test_apply_name_overrides_preserves_other_fields():
    entry = _make_entry({"u_tom": {"owner_name": "tkeefe66", "team_name": "Eagles", "avatar_url": "http://x.com/a.png"}})
    apply_name_overrides(entry, {"u_tom": "Tom"})
    assert entry.owners["u_tom"]["team_name"] == "Eagles"
    assert entry.owners["u_tom"]["avatar_url"] == "http://x.com/a.png"


def test_apply_name_overrides_empty_overrides_is_noop():
    entry = _make_entry({"u_tom": {"owner_name": "tkeefe66", "team_name": None, "avatar_url": None}})
    apply_name_overrides(entry, {})
    assert entry.owners["u_tom"]["owner_name"] == "tkeefe66"
