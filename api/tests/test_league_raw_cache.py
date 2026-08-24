from __future__ import annotations

from app.services.league_raw_cache import LeagueRawCache, SCHEMA_VERSION


def _trade_bundle():
    return {
        "users": {"u_a": {"display_name": "Alice"}},
        "roster_to_user": {1: "u_a", 2: "u_b"},
        "raw_trades": [{"transaction_id": "t1"}],
        "raw_drops": [],
        "raw_roster_txs": [{"transaction_id": "t1"}, {"transaction_id": "t2"}],
        "drafts": [{"draft_id": "d1", "status": "complete"}],
        "draft_picks_by_draft_id": {"d1": [{"round": 1, "player_id": "p1"}]},
    }


def _matchup_bundle():
    return {
        "matchups": {
            ("L1", 5, 1): {"starters": ["p1"], "players": ["p1"],
                           "players_points": {"p1": 20.0},
                           "team_points": 100.0, "opponent_points": 90.0},
            ("L1", 5, 2): {"starters": ["p2"], "players": ["p2"],
                           "players_points": {"p2": 10.0},
                           "team_points": 90.0, "opponent_points": 100.0},
        },
        "playoff_week_start": 15,
        "roster_to_user": {1: "u_a", 2: "u_b"},
        "league_name": "Bros",
        "season": 2024,
        "owners": {"u_a": {"owner_name": "Alice", "team_name": None, "avatar_url": None}, "u_b": {"owner_name": "Bob", "team_name": None, "avatar_url": None}},
    }


def test_trade_bundle_round_trip_coerces_int_keys(tmp_path):
    cache = LeagueRawCache(cache_dir=tmp_path)
    cache.write_trade_bundle("L1", _trade_bundle())
    got = cache.read_trade_bundle("L1")
    assert got == _trade_bundle()           # int roster keys restored
    assert all(isinstance(k, int) for k in got["roster_to_user"])


def test_matchup_bundle_round_trip_rebuilds_tuple_keys(tmp_path):
    cache = LeagueRawCache(cache_dir=tmp_path)
    cache.write_matchup_bundle("L1", _matchup_bundle())
    got = cache.read_matchup_bundle("L1")
    assert got == _matchup_bundle()         # tuple matchup keys + int roster keys restored
    assert all(isinstance(k, tuple) and len(k) == 3 for k in got["matchups"])


def test_writing_one_bundle_preserves_the_other(tmp_path):
    cache = LeagueRawCache(cache_dir=tmp_path)
    cache.write_trade_bundle("L1", _trade_bundle())
    cache.write_matchup_bundle("L1", _matchup_bundle())   # must not clobber trade bundle
    assert cache.read_trade_bundle("L1") == _trade_bundle()
    assert cache.read_matchup_bundle("L1") == _matchup_bundle()


def test_missing_file_and_missing_bundle_return_none(tmp_path):
    cache = LeagueRawCache(cache_dir=tmp_path)
    assert cache.read_trade_bundle("nope") is None
    cache.write_trade_bundle("L1", _trade_bundle())
    assert cache.read_matchup_bundle("L1") is None       # file exists, bundle absent


def test_schema_version_mismatch_is_a_miss(tmp_path):
    import json
    cache = LeagueRawCache(cache_dir=tmp_path)
    cache.write_trade_bundle("L1", _trade_bundle())
    path = tmp_path / "raw_L1.json"
    raw = json.loads(path.read_text())
    raw["schema_version"] = SCHEMA_VERSION + 999
    path.write_text(json.dumps(raw))
    assert cache.read_trade_bundle("L1") is None


def test_a_bundle_without_raw_roster_txs_reads_as_a_miss(tmp_path):
    """Every sealed-season bundle written before this feature lacks the key.
    Without a guard it returns successfully with zero roster transactions and
    no error — the reconstruction downstream would silently be built on
    nothing."""
    cache = LeagueRawCache(tmp_path)
    cache.write_trade_bundle("L1", {
        "users": {}, "roster_to_user": {}, "raw_trades": [], "raw_drops": [],
        "drafts": [], "draft_picks_by_draft_id": {},
    })  # note: no raw_roster_txs
    assert cache.read_trade_bundle("L1") is None


def test_force_bypasses_reads_but_still_writes(tmp_path):
    cache = LeagueRawCache(cache_dir=tmp_path)
    cache.write_trade_bundle("L1", _trade_bundle())
    forced = LeagueRawCache(cache_dir=tmp_path, force=True)
    assert forced.read_trade_bundle("L1") is None        # read bypassed
    forced.write_trade_bundle("L1", _trade_bundle())     # write still happens
    assert LeagueRawCache(cache_dir=tmp_path).read_trade_bundle("L1") == _trade_bundle()
