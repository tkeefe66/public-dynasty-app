from app.services.chain_cache import ChainCacheEntry
from app.services.owner_view import build_owner_detail


def _entry_with_picks():
    pick = {
        "player_id": "p1", "full_name": "Aida", "position": "WR",
        "drafter_id": "U", "round": 1, "slot": 1, "picks_in_round": 12,
        "draft_season": 2025, "acquired_via_trade": False,
        "current_value": 5000.0, "lowest_value": 3000.0, "highest_value": 6000.0,
        "avg_slot_value": 4000.0, "production_total": 220.0,
        "production_regular": 100.0, "production_playoff": 0.0,
        "production_toilet": 13.0,
    }
    other = {**pick, "player_id": "p9", "drafter_id": "OTHER"}
    return ChainCacheEntry(
        league_id="L",
        chain=[],
        resolved_trades=[],
        grades={},
        owners={"U": {"user_id": "U", "display_name": "Tom"}},
        playoff_weeks_by_league={},
        roster_to_user_by_league={},
        league_name_by_id={},
        league_season_by_id={},
        cached_at="2026-06-15T00:00:00Z",
        drafted_picks=[pick, other],
    )


def test_draft_picks_grouped_by_season_for_owner_only():
    detail = build_owner_detail(_entry_with_picks(), "U")
    assert detail is not None
    assert set(detail.draft_picks_by_season) == {"2025"}
    rows = detail.draft_picks_by_season["2025"]
    assert len(rows) == 1                      # OTHER's pick excluded
    assert rows[0].player_id == "p1"
    assert rows[0].current_value == 5000.0
    assert rows[0].production_total == 220.0
    assert rows[0].production_toilet == 13.0


def test_draft_pick_unmatched_adp_round_trips_as_none_not_zero():
    """An unmatched pick is *ungraded* on the ADP baseline, which is not the
    same as scoring zero — adp/adp_delta/projected_points must survive as
    None rather than being coerced to 0.0/0."""
    pick = {
        "player_id": "p1", "full_name": "Aida", "position": "WR",
        "drafter_id": "U", "round": 1, "slot": 1, "picks_in_round": 12,
        "draft_season": 2025, "acquired_via_trade": False,
        "current_value": 5000.0, "lowest_value": 3000.0, "highest_value": 6000.0,
        "avg_slot_value": 4000.0, "production_total": 220.0,
        "production_regular": 100.0, "production_playoff": 0.0,
        "production_toilet": 13.0,
        "is_keeper": True, "pick_no": 3, "adp": None, "adp_delta": None,
        "projected_points": None,
    }
    entry = ChainCacheEntry(
        league_id="L",
        chain=[],
        resolved_trades=[],
        grades={},
        owners={"U": {"user_id": "U", "display_name": "Tom"}},
        playoff_weeks_by_league={},
        roster_to_user_by_league={},
        league_name_by_id={},
        league_season_by_id={},
        cached_at="2026-06-15T00:00:00Z",
        drafted_picks=[pick],
    )
    detail = build_owner_detail(entry, "U")
    assert detail is not None
    row = detail.draft_picks_by_season["2025"][0]
    assert row.is_keeper is True
    assert row.pick_no == 3
    assert row.adp is None
    assert row.adp_delta is None
    assert row.projected_points is None


def test_draft_pick_matched_adp_passes_through_unconverted():
    pick = {
        "player_id": "p1", "full_name": "Aida", "position": "WR",
        "drafter_id": "U", "round": 1, "slot": 1, "picks_in_round": 12,
        "draft_season": 2025, "acquired_via_trade": False,
        "current_value": 5000.0, "lowest_value": 3000.0, "highest_value": 6000.0,
        "avg_slot_value": 4000.0, "production_total": 220.0,
        "production_regular": 100.0, "production_playoff": 0.0,
        "production_toilet": 13.0,
        "is_keeper": False, "pick_no": 12, "adp": 8.5, "adp_delta": 3.5,
        "projected_points": 210.4,
    }
    entry = ChainCacheEntry(
        league_id="L",
        chain=[],
        resolved_trades=[],
        grades={},
        owners={"U": {"user_id": "U", "display_name": "Tom"}},
        playoff_weeks_by_league={},
        roster_to_user_by_league={},
        league_name_by_id={},
        league_season_by_id={},
        cached_at="2026-06-15T00:00:00Z",
        drafted_picks=[pick],
    )
    detail = build_owner_detail(entry, "U")
    assert detail is not None
    row = detail.draft_picks_by_season["2025"][0]
    assert row.is_keeper is False
    assert row.pick_no == 12
    assert row.adp == 8.5
    assert row.adp_delta == 3.5
    assert row.projected_points == 210.4


def test_owner_detail_carries_the_league_format():
    """The UI drops the value-arc columns by ASKING the format, not by
    inferring it from all-zero data — redraft rows carry real FantasyCalc
    values, so the zero heuristic let a "dynasty market value" column render
    over a redraft class."""
    entry = _entry_with_picks()
    entry.capabilities = {"format": "redraft"}
    assert build_owner_detail(entry, "U").format == "redraft"


def test_owner_detail_format_defaults_to_dynasty_on_a_pre_feature_cache():
    assert build_owner_detail(_entry_with_picks(), "U").format == "dynasty"
