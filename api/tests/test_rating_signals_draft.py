from app.services.rating_signals import compute_rating_signals
from sleeper_dynasty.engine.draft_signals import DraftedPick
from sleeper_dynasty.models.league import DraftPick


class _KTC:
    def __init__(self, v):
        self.superflex_value = v
        self.one_qb_value = v


def _supporting():
    return {
        "matchups": {
            ("L", 1, 1): {"players_points": {"win": 200.0, "bust": 5.0}},
            ("L", 1, 2): {"players_points": {"mid": 90.0}},
        },
        "roster_to_user_by_league": {"L": {1: "uA", 2: "uB"}},
        "league_season_by_id": {"L": 2026},
        "playoff_week_start_by_league": {"L": 15},
        "winners_bracket_by_league": {"L": []},
        "num_playoff_teams_by_league": {"L": 0},
        "ktc_by_player_id": {"win": _KTC(9000), "bust": _KTC(100), "mid": _KTC(3000)},
        "player_ages": {},
        "owners": {"uA": {}, "uB": {}},
        "pick_value_table": {(2027, 1): _KTC(1000), (2027, 2): _KTC(400)},
    }


def test_draft_capital_is_live_and_reflects_holdings():
    tp = [DraftPick(season=2027, round=1, original_owner_id=2, current_owner_id=1)]
    _, outlook, _, _ = compute_rating_signals(
        _supporting(), current_holders={}, traded_picks=tp, rookie_picks=[],
        num_draft_rounds=2)
    assert outlook["uA"]["draft_capital"] > outlook["uB"]["draft_capital"]
    assert outlook["uA"]["draft_capital"] > 0


def test_draft_skill_signal_present_and_separates():
    picks = [
        DraftedPick("d", 1, 1, 2, "win", "uA"),
        DraftedPick("d", 1, 2, 2, "bust", "uB"),
    ]
    _, outlook, _, _ = compute_rating_signals(
        _supporting(), current_holders={}, traded_picks=[], rookie_picks=picks,
        num_draft_rounds=2)
    assert "draft_skill" in outlook["uA"]
    assert outlook["uA"]["draft_skill"] >= outlook["uB"]["draft_skill"]


def test_skill_zero_and_capital_equal_without_inputs():
    _, outlook, _, _ = compute_rating_signals(_supporting(), current_holders={})
    assert outlook["uA"]["draft_skill"] == 0.0
    assert outlook["uB"]["draft_skill"] == 0.0
    assert outlook["uA"]["draft_capital"] == outlook["uB"]["draft_capital"]


def test_draft_capital_tiered_by_roster_strength():
    # 3 owners so strength_tiers produces early/mid/late (it returns all "mid"
    # for fewer than 3). uB strongest -> late picks; uA weakest -> early picks.
    s = _supporting()
    s["roster_to_user_by_league"] = {"L": {1: "uA", 2: "uB", 3: "uC"}}
    s["owners"] = {"uA": {}, "uB": {}, "uC": {}}
    s["pick_value_table"] = {(2027, 1): _KTC(6500)}
    s["pick_value_table_tiered"] = {
        (2027, 1, "early"): _KTC(9000), (2027, 1, "mid"): _KTC(6500),
        (2027, 1, "late"): _KTC(4000)}
    s["ktc_by_player_id"].update({"b1": _KTC(9000), "b2": _KTC(9000),
                                  "c1": _KTC(5000), "a1": _KTC(100)})
    holders = {"b1": "uB", "b2": "uB", "c1": "uC", "a1": "uA"}
    _, outlook, _, _ = compute_rating_signals(
        s, current_holders=holders, traded_picks=[], rookie_picks=[],
        num_draft_rounds=1)
    assert outlook["uA"]["draft_capital"] > outlook["uB"]["draft_capital"]
