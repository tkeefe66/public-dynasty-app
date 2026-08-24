from app.services.aggregations import _asset_label, _format_assets_short


def test_player_asset_uses_name():
    assert _asset_label({"player_id": "p1", "name": "Bijan Robinson"}) == "Bijan Robinson"


def test_unresolved_pick_renders_slot_not_question_mark():
    assert _asset_label({"season": 2026, "round": 3}) == "2026 3rd"
    assert _asset_label({"season": 2027, "round": 1}) == "2027 1st"
    assert _asset_label({"season": 2027, "round": 4}) == "2027 4th"


def test_resolved_pick_prefers_drafted_player_name():
    a = {"season": 2026, "round": 2, "drafted_player_name": "Ty Simpson"}
    assert _asset_label(a) == "Ty Simpson"


def test_faab_asset():
    assert _asset_label({"amount": 50}) == "$50 FAAB"


def test_format_assets_short_no_bare_question_mark_for_picks():
    side = {"received": [
        {"player_id": "p1", "name": "Malachi Fields"},
        {"season": 2026, "round": 3},
    ]}
    assert _format_assets_short(side) == "Malachi Fields; 2026 3rd"


def test_format_assets_short_empty_side():
    assert _format_assets_short({"received": []}) == "—"
