from app.models.owner import DraftPickResult, OwnerDetailResp


def test_draft_pick_result_shape():
    r = DraftPickResult(
        player_id="p1", full_name="Aida", position="WR", round=1, slot=1,
        picks_in_round=12, draft_season=2025, acquired_via_trade=False,
        current_value=5000.0, lowest_value=3000.0, highest_value=6000.0,
        avg_slot_value=4000.0, production_total=220.0, production_regular=100.0,
        production_playoff=0.0, production_toilet=13.0)
    assert r.current_value == 5000.0
    assert r.draft_season == 2025
    assert r.production_total == 220.0
    assert r.production_toilet == 13.0


def test_owner_detail_defaults_draft_picks_empty():
    d = OwnerDetailResp(
        league_id="L", user_id="U",
        owner={"user_id": "U", "owner_name": "Tom"},
        totals_by_lens={}, career_arc=[], best_trade_id=None, worst_trade_id=None)
    assert d.draft_picks_by_season == {}
