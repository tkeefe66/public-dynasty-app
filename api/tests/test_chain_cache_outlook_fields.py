from app.services.chain_cache import ChainCacheEntry


def _min_raw():
    # A pre-feature entry dict: every required (non-default) field, none of the new ones.
    return dict(
        league_id="L",
        chain=[],
        resolved_trades=[],
        grades={},
        owners={},
        playoff_weeks_by_league={},
        roster_to_user_by_league={},
        league_name_by_id={},
        league_season_by_id={},
        cached_at="2026-01-01",
    )


def test_pre_feature_entry_deserializes_with_default_outlook_fields():
    entry = ChainCacheEntry(**_min_raw())
    assert entry.dynasty_outlooks == {}
    assert entry.roster_ranks == {}


def test_new_fields_round_trip():
    raw = _min_raw()
    raw["dynasty_outlooks"] = {"uA": {"window": "Ascending"}}
    raw["roster_ranks"] = {"uA": {"rank": 1, "of": 12}}
    entry = ChainCacheEntry(**raw)
    assert entry.dynasty_outlooks["uA"]["window"] == "Ascending"
    assert entry.roster_ranks["uA"] == {"rank": 1, "of": 12}


def test_pre_feature_entry_defaults_week_recap_empty():
    entry = ChainCacheEntry(**_min_raw())
    assert entry.week_recap == {}


def test_week_recap_round_trips():
    raw = _min_raw()
    raw["week_recap"] = {
        "season": "2026", "week": 4,
        "high_score": {"user_id": "uA", "points": 140.0},
        "blowout": {"winner_user_id": "uA", "loser_user_id": "uB", "margin": 50.0},
        "traded_points": None,
    }
    entry = ChainCacheEntry(**raw)
    assert entry.week_recap["week"] == 4
    assert entry.week_recap["blowout"]["margin"] == 50.0
    assert entry.week_recap["traded_points"] is None
