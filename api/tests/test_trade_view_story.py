from app.services.chain_cache import ChainCacheEntry
from app.services.trade_view import build_trade_detail


def _entry():
    rt = {"trade": {"transaction_id": "t1", "traded_at": "2024-06-01T00:00:00",
                    "week": 1, "season": 2024, "league_id": "L"},
          "sides": {"u_mike": {"received": [], "given": []}}}
    return ChainCacheEntry(
        league_id="L", chain=[], resolved_trades=[rt], grades={},
        owners={"u_mike": {"owner_name": "Mike"}},
        playoff_weeks_by_league={}, roster_to_user_by_league={},
        league_name_by_id={"L": "Bros"}, league_season_by_id={"L": 2024},
        cached_at="now",
        trade_stories={"t1": {"verdict": "Mike robbed Tom.", "body": "Nope.",
                              "lede": "Mike won big.", "beats": ["beat1", "beat2"],
                              "facts_hash": "h", "generated_at": "now"}},
    )


def _two_side_entry(mike_ktc: float, tom_ktc: float):
    """Trade with two sides so winner_user_id / lopsidedness can be tested."""
    rt = {"trade": {"transaction_id": "t2", "traded_at": "2024-06-01T00:00:00",
                    "week": 1, "season": 2024, "league_id": "L"},
          "sides": {"u_mike": {"received": [], "given": []},
                    "u_tom":  {"received": [], "given": []}}}
    return ChainCacheEntry(
        league_id="L", chain=[], resolved_trades=[rt], grades={
            "t2": {
                "received_ktc": {"u_mike": mike_ktc, "u_tom": tom_ktc},
                "snapshot_value_swing": {"u_mike": mike_ktc - tom_ktc, "u_tom": tom_ktc - mike_ktc},
                "production_total": {"u_mike": 0.0, "u_tom": 0.0},
            }
        },
        owners={"u_mike": {"owner_name": "Mike"}, "u_tom": {"owner_name": "Tom"}},
        playoff_weeks_by_league={}, roster_to_user_by_league={},
        league_name_by_id={"L": "Bros"}, league_season_by_id={"L": 2024},
        cached_at="now",
    )


def test_detail_includes_story_when_present():
    resp = build_trade_detail(_entry(), "t1")
    assert resp.story is not None
    assert resp.story.verdict == "Mike robbed Tom."


def test_detail_story_none_when_absent():
    e = _entry(); e.trade_stories = {}
    resp = build_trade_detail(e, "t1")
    assert resp.story is None


def test_detail_story_carries_lede_and_beats():
    resp = build_trade_detail(_entry(), "t1")
    assert resp.story is not None
    assert resp.story.lede == "Mike won big."
    assert resp.story.beats == ["beat1", "beat2"]


def test_winner_user_id_is_higher_received_ktc_side():
    resp = build_trade_detail(_two_side_entry(mike_ktc=3000.0, tom_ktc=500.0), "t2")
    assert resp.winner_user_id == "u_mike"


def test_lopsidedness_is_clamped_between_0_and_1():
    resp = build_trade_detail(_two_side_entry(mike_ktc=3000.0, tom_ktc=500.0), "t2")
    assert 0.0 <= resp.lopsidedness <= 1.0


def test_lopsidedness_is_zero_when_tied():
    resp = build_trade_detail(_two_side_entry(mike_ktc=1000.0, tom_ktc=1000.0), "t2")
    assert resp.winner_user_id is None
    assert resp.lopsidedness == 0.0


def test_lopsidedness_scales_with_margin():
    # A 2500-point margin is a blowout (lopsidedness == 1.0).
    resp_blowout = build_trade_detail(_two_side_entry(mike_ktc=3000.0, tom_ktc=500.0), "t2")
    resp_edge = build_trade_detail(_two_side_entry(mike_ktc=1500.0, tom_ktc=1000.0), "t2")
    assert resp_blowout.lopsidedness > resp_edge.lopsidedness
