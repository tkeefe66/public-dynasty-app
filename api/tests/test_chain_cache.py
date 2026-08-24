from __future__ import annotations

import pytest

from app.services.chain_cache import ChainCache, ChainCacheEntry


@pytest.fixture
def cache(tmp_path):
    return ChainCache(cache_dir=tmp_path)


def test_chain_cache_round_trip(cache):
    entry = ChainCacheEntry(
        league_id="L1",
        chain=[{"league_id": "L1", "season": 2026, "name": "Bros"}],
        resolved_trades=[{"transaction_id": "tx1"}],
        grades={"tx1": {"snapshot_value_swing": {"u1": 100}}},
        owners={"u1": {"owner_name": "Tom", "team_name": None, "avatar_url": None}},
        playoff_weeks_by_league={"L1": 15},
        roster_to_user_by_league={"L1": {1: "u1"}},
        league_name_by_id={"L1": "Bros"},
        league_season_by_id={"L1": 2026},
        cached_at="2026-05-28T12:00:00Z",
        warnings=[],
    )
    cache.write("L1", entry)
    got = cache.read("L1")
    assert got is not None
    assert got.resolved_trades[0]["transaction_id"] == "tx1"
    assert got.owners["u1"]["owner_name"] == "Tom"


def test_chain_cache_expires(cache):
    entry = ChainCacheEntry(
        league_id="L1", chain=[], resolved_trades=[], grades={},
        owners={}, playoff_weeks_by_league={},
        roster_to_user_by_league={}, league_name_by_id={},
        league_season_by_id={}, cached_at="2026-01-01T00:00:00Z",
        warnings=[],
    )
    cache.write("L1", entry)
    expired = cache.read("L1", max_age_seconds=0)
    assert expired is None


def test_chain_cache_miss(cache):
    assert cache.read("doesnotexist") is None


def test_chain_cache_invalidate(cache):
    entry = ChainCacheEntry(
        league_id="L1", chain=[], resolved_trades=[], grades={},
        owners={}, playoff_weeks_by_league={},
        roster_to_user_by_league={}, league_name_by_id={},
        league_season_by_id={}, cached_at="2026-05-28T12:00:00Z",
        warnings=[],
    )
    cache.write("L1", entry)
    cache.invalidate("L1")
    assert cache.read("L1") is None


def test_chain_cache_legacy_entry_without_owners_is_a_miss(cache, tmp_path):
    import json
    path = tmp_path / "chain_Llegacy.json"
    path.write_text(json.dumps({
        "league_id": "Llegacy", "chain": [], "resolved_trades": [], "grades": {},
        "display_names": {"u1": "Tom"}, "playoff_weeks_by_league": {},
        "roster_to_user_by_league": {}, "league_name_by_id": {},
        "league_season_by_id": {}, "cached_at": "2026-05-28T12:00:00Z", "warnings": [],
    }))
    assert cache.read("Llegacy") is None


# ---------------------------------------------------------------------------
# T8 — schema_version bump
# ---------------------------------------------------------------------------

def _make_entry(league_id="L1"):
    return ChainCacheEntry(
        league_id=league_id,
        chain=[],
        resolved_trades=[],
        grades={},
        owners={"u1": {"owner_name": "Tom", "team_name": None, "avatar_url": None}},
        playoff_weeks_by_league={league_id: 15},
        roster_to_user_by_league={league_id: {1: "u1"}},
        league_name_by_id={league_id: "Test League"},
        league_season_by_id={league_id: 2025},
        cached_at="2026-06-01T00:00:00Z",
        warnings=[],
    )


def test_schema_version_round_trips(cache):
    from app.services.chain_cache import SCHEMA_VERSION
    entry = _make_entry()
    cache.write("L1", entry)
    got = cache.read("L1")
    assert got is not None
    assert got.schema_version == SCHEMA_VERSION


def test_missing_schema_version_is_a_miss(cache, tmp_path):
    import json
    # Hand-written dict with no schema_version (old v1 format)
    path = tmp_path / "chain_Lv1.json"
    path.write_text(json.dumps({
        "league_id": "Lv1", "chain": [], "resolved_trades": [], "grades": {},
        "owners": {"u1": {"owner_name": "Tom", "team_name": None, "avatar_url": None}},
        "playoff_weeks_by_league": {}, "roster_to_user_by_league": {},
        "league_name_by_id": {}, "league_season_by_id": {},
        "cached_at": "2026-05-01T00:00:00Z", "warnings": [],
    }))
    assert cache.read("Lv1") is None


def test_legacy_unknown_field_is_dropped_not_500(cache, tmp_path):
    """A persisted entry carrying a since-removed field (e.g. the retired
    `trade_value_series`) must load by dropping the unknown key, not raise
    TypeError. Guards against a schema change 500ing prod read endpoints."""
    import json

    from app.services.chain_cache import SCHEMA_VERSION

    path = tmp_path / "chain_Llegacyfield.json"
    path.write_text(json.dumps({
        "league_id": "Llegacyfield", "chain": [], "resolved_trades": [],
        "grades": {},
        "owners": {"u1": {"owner_name": "Tom", "team_name": None, "avatar_url": None}},
        "playoff_weeks_by_league": {}, "roster_to_user_by_league": {},
        "league_name_by_id": {}, "league_season_by_id": {},
        "cached_at": "2026-06-24T00:00:00Z", "warnings": [],
        "schema_version": SCHEMA_VERSION,
        # since-removed field that must be tolerated:
        "trade_value_series": {"tx1": {"u1": [[2025, 3, 100.0]]}},
    }))
    got = cache.read("Llegacyfield")
    assert got is not None
    assert got.league_id == "Llegacyfield"
    assert not hasattr(got, "trade_value_series")


def test_stale_schema_version_is_a_miss(cache, tmp_path):
    import json
    # Hand-written dict with schema_version=1 (pre-bracket grades)
    path = tmp_path / "chain_Lstale.json"
    path.write_text(json.dumps({
        "league_id": "Lstale", "chain": [], "resolved_trades": [], "grades": {},
        "owners": {"u1": {"owner_name": "Tom", "team_name": None, "avatar_url": None}},
        "playoff_weeks_by_league": {}, "roster_to_user_by_league": {},
        "league_name_by_id": {}, "league_season_by_id": {},
        "cached_at": "2026-05-01T00:00:00Z", "warnings": [],
        "schema_version": 1,
    }))
    assert cache.read("Lstale") is None


# ---------------------------------------------------------------------------
# Task 5 — production timeline fields
# ---------------------------------------------------------------------------

def test_entry_carries_production_fields():
    e = _make_entry()
    e.trade_production_series = {"t1": {"u1": {"total": [[2024, 5, 10.0]]}}}
    e.production_week_axis = [[2024, 5]]
    assert e.trade_production_series["t1"]["u1"]["total"] == [[2024, 5, 10.0]]
    assert e.production_week_axis == [[2024, 5]]


def test_production_fields_round_trip_through_disk(cache):
    """New production fields survive write→read through JSON."""
    entry = _make_entry()
    entry.trade_production_series = {"tx1": {"u1": {"total": [[2025, 3, 42.5]]}}}
    entry.trade_production_verdict = {"tx1": {"total": {"winner": "u1"}}}
    entry.owner_production_series = {"u1": {"received": {"total": [[2025, 3, 42.5]]}, "given": {}}}
    entry.owner_production_verdict = {"u1": {"total": {"verdict": "winning"}}}
    entry.production_week_axis = [[2025, 1], [2025, 2], [2025, 3]]
    cache.write("L1", entry)
    got = cache.read("L1")
    assert got is not None
    assert got.trade_production_series["tx1"]["u1"]["total"] == [[2025, 3, 42.5]]
    assert got.trade_production_verdict["tx1"]["total"]["winner"] == "u1"
    assert got.owner_production_series["u1"]["received"]["total"] == [[2025, 3, 42.5]]
    assert got.owner_production_verdict["u1"]["total"]["verdict"] == "winning"
    assert got.production_week_axis == [[2025, 1], [2025, 2], [2025, 3]]


# ---------------------------------------------------------------------------
# Task 14 — drill series fields
# ---------------------------------------------------------------------------

def test_entry_carries_drill_fields():
    e = _make_entry()
    e.trade_production_players = {"t1": {"u1": [{"player_id": "p1", "byMetric": {"total": [[2024, 5, 10.0]]}}]}}
    e.owner_production_trades = {"u1": [{"trade_id": "t1", "byMetric": {"total": [[2024, 5, 10.0]]}}]}
    assert e.trade_production_players["t1"]["u1"][0]["player_id"] == "p1"
    assert e.owner_production_trades["u1"][0]["trade_id"] == "t1"


def test_drill_fields_round_trip_through_disk(cache):
    """Drill series fields survive write→read through JSON."""
    entry = _make_entry()
    entry.trade_production_players = {"tx1": {"u1": [{"player_id": "p1", "byMetric": {"total": [[2025, 3, 42.5]]}}]}}
    entry.owner_production_trades = {"u1": [{"trade_id": "tx1", "byMetric": {"total": [[2025, 3, 42.5]]}}]}
    cache.write("L1", entry)
    got = cache.read("L1")
    assert got is not None
    assert got.trade_production_players["tx1"]["u1"][0]["player_id"] == "p1"
    assert got.owner_production_trades["u1"][0]["trade_id"] == "tx1"


# ---------------------------------------------------------------------------
# Task 6 — injury context field
# ---------------------------------------------------------------------------

def test_entry_carries_injury_field():
    from app.services.chain_cache import ChainCacheEntry
    e = _make_entry()
    e.trade_injury = {"t1": {"u1": {"p1": {"games_missed": {"regular": 1, "playoff": 0, "toilet": 0},
                                           "missed_weeks": [[2024, 6, "high"]],
                                           "currently_out": False, "out_detail": None}}}}
    assert e.trade_injury["t1"]["u1"]["p1"]["games_missed"]["regular"] == 1


def test_injury_field_round_trips_through_disk(cache):
    """trade_injury survives write→read through JSON."""
    entry = _make_entry()
    entry.trade_injury = {"tx1": {"u1": {"p1": {"games_missed": {"regular": 2, "playoff": 0, "toilet": 0},
                                                "missed_weeks": [[2024, 6, "high"], [2024, 7, "soft"]],
                                                "currently_out": True, "out_detail": "IR (knee) since 2024-10-01"}}}}
    cache.write("L1", entry)
    got = cache.read("L1")
    assert got is not None
    assert got.trade_injury["tx1"]["u1"]["p1"]["games_missed"]["regular"] == 2
    assert got.trade_injury["tx1"]["u1"]["p1"]["currently_out"] is True
    assert got.trade_injury["tx1"]["u1"]["p1"]["out_detail"] == "IR (knee) since 2024-10-01"


# ---------------------------------------------------------------------------
# Phase 5 Task 6 — draft_needs field (chain-cache-field quartet, 1 of 2:
# round-trip + pre-feature default; grader-stamps and view-fallback live in
# test_grader_service.py / test_draft_board_view.py respectively)
# ---------------------------------------------------------------------------

def test_entry_defaults_draft_needs_to_empty_dict():
    """A pre-feature entry (constructed without draft_needs, exactly what a
    JSON blob written before this field existed decodes into) must default
    to `{}`, not raise. Mutation this catches: dropping `default_factory`
    from the field (or removing the field's default entirely) would make
    this constructor call raise TypeError for a missing required arg."""
    e = _make_entry()
    assert e.draft_needs == {}


def test_draft_needs_round_trips_through_disk(cache):
    """draft_needs survives write -> JSON -> read. Keyed by str(season)
    (JSON object keys are always strings), values are OwnerNeedsResp-shaped
    dicts with no `starters_by_slot` -- the wire model deliberately drops it.
    Mutation this catches: omitting draft_needs from the ChainCacheEntry
    dataclass (or from the asdict() write path) would make `got.draft_needs`
    either raise AttributeError or come back {}."""
    entry = _make_entry()
    entry.draft_needs = {
        "2026": [
            {"user_id": "u1", "holes": ["QB", "TE"], "drafted_into": ["TE"],
             "started": 1, "drafted_into_count": 1},
        ],
    }
    cache.write("L1", entry)
    got = cache.read("L1")
    assert got is not None
    assert got.draft_needs["2026"][0]["user_id"] == "u1"
    assert got.draft_needs["2026"][0]["holes"] == ["QB", "TE"]
    assert got.draft_needs["2026"][0]["drafted_into_count"] == 1
    assert "starters_by_slot" not in got.draft_needs["2026"][0]
