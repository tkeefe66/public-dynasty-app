from app.models.owner import DraftPickResult
from app.services.chain_cache import ChainCacheEntry
from app.services.owner_view import build_owner_detail


def _entry_with_pick(pick_overrides: dict) -> ChainCacheEntry:
    pick = {
        "player_id": "p1", "full_name": "Aida", "position": "WR",
        "drafter_id": "U", "round": 1, "slot": 1, "picks_in_round": 12,
        "draft_season": 2025, "acquired_via_trade": False,
        "current_value": 5000.0, "lowest_value": 3000.0, "highest_value": 6000.0,
        "avg_slot_value": 4000.0, "production_total": 220.0,
        "production_regular": 100.0, "production_playoff": 0.0,
        "production_toilet": 13.0,
        **pick_overrides,
    }
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
        drafted_picks=[pick],
    )


def test_production_started_threads_through_owner_view():
    """Not just the model — the VIEW must actually read `production_started`
    off the drafted_picks blob and put it on the response row. A model that
    accepts the field proves nothing about owner_view.py supplying one."""
    entry = _entry_with_pick({"production_started": 150.0})
    detail = build_owner_detail(entry, "U")
    assert detail is not None
    row = detail.draft_picks_by_season["2025"][0]
    assert row.production_started == 150.0


def test_production_started_defaults_through_owner_view_when_key_absent():
    """A pre-feature drafted_picks blob carries no `production_started` key at
    all — the view must default to 0.0, not raise."""
    entry = _entry_with_pick({})
    detail = build_owner_detail(entry, "U")
    assert detail is not None
    row = detail.draft_picks_by_season["2025"][0]
    assert row.production_started == 0.0


def test_draft_pick_result_carries_started_points():
    r = DraftPickResult(
        player_id="p", full_name="X", position="RB", round=1, slot=1,
        picks_in_round=12, draft_season=2025, acquired_via_trade=False,
        current_value=0.0, lowest_value=0.0, highest_value=0.0,
        avg_slot_value=0.0, production_total=100.0, production_started=60.0,
        production_regular=10.0, production_playoff=20.0, production_toilet=0.0)
    assert r.production_started == 60.0


def test_production_started_defaults_for_pre_feature_rows():
    r = DraftPickResult(
        player_id="p", full_name="X", position="RB", round=1, slot=1,
        picks_in_round=12, draft_season=2025, acquired_via_trade=False,
        current_value=0.0, lowest_value=0.0, highest_value=0.0,
        avg_slot_value=0.0, production_total=0.0, production_regular=0.0,
        production_playoff=0.0, production_toilet=0.0)
    assert r.production_started == 0.0
