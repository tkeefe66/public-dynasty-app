from sleeper_dynasty.models.trade_story import (
    PlayerArc, PickOutcome, OwnerStrategyFacts, TradeStoryFacts, facts_hash,
)


def _facts() -> TradeStoryFacts:
    return TradeStoryFacts(
        trade_id="t1", season=2024, is_offseason=True,
        winner_user_id="u_mike", lopsidedness=0.82,
        margins={"ktc": 1840.0, "production": 41.2, "impact": 6.0},
        sides=[
            {"user_id": "u_mike", "owner_name": "Mike",
             "player_arcs": [PlayerArc(
                 player="Bijan Robinson", position="RB", received_by="u_mike",
                 starter_weeks=14, points_total=210.0,
                 season_high_points=34.0, season_high_week=14,
                 season_high_is_playoff=True,
                 playoff_vs_regular_pct=12.0, decisive_starts=3,
                 benched_weeks=0).to_dict()],
             "pick_outcomes": []},
            {"user_id": "u_tom", "owner_name": "Tom",
             "player_arcs": [],
             "pick_outcomes": [PickOutcome(
                 season=2025, round=1, became_player="Rookie X",
                 points_per_game=9.1).to_dict()]},
        ],
        owners={
            "u_mike": OwnerStrategyFacts(
                user_id="u_mike", owner_name="Mike", trades_count=12,
                net_picks=-4, players_for_picks_count=7,
                picks_for_players_count=2, first_round_picks_sent=1,
                tilt="win-now", net_ktc=3200.0,
                tendencies=["buys win-now help with picks"]).to_dict(),
            "u_tom": OwnerStrategyFacts(
                user_id="u_tom", owner_name="Tom", trades_count=9,
                net_picks=5, players_for_picks_count=1,
                picks_for_players_count=4, first_round_picks_sent=3,
                tilt="rebuild", net_ktc=-1800.0,
                tendencies=["sold a 1st in 3 of last 4 deals"]).to_dict(),
        },
    )


def test_to_dict_is_json_serializable_and_round_trips():
    import json
    d = _facts().to_dict()
    s = json.dumps(d)  # must not raise
    assert json.loads(s)["winner_user_id"] == "u_mike"
    assert d["sides"][0]["player_arcs"][0]["season_high_week"] == 14
    assert d["owners"]["u_tom"]["tilt"] == "rebuild"


def test_facts_hash_is_stable_and_order_independent():
    a = facts_hash(_facts())
    b = facts_hash(_facts())
    assert a == b and len(a) == 16


def test_player_arc_to_dict_carries_dropped_and_last_rostered_week():
    arc = PlayerArc(
        player="Bust Guy", position="WR", received_by="u_a",
        starter_weeks=0, points_total=0.0, season_high_points=None,
        season_high_week=None, season_high_is_playoff=False,
        playoff_vs_regular_pct=None, decisive_starts=0, benched_weeks=0,
        phantom_points=0.0, flipped=False, dropped=True,
        last_rostered_week=None,
    )
    d = arc.to_dict()
    assert d["dropped"] is True
    assert d["last_rostered_week"] is None


def test_pick_outcome_to_dict_carries_terminal_state_and_drop_week():
    po = PickOutcome(
        season=2026, round=1, became_player="Cut Guy",
        points_per_game=None, flipped_for=None,
        terminal_state="dropped", dropped_before_week=0,
    )
    d = po.to_dict()
    assert d["terminal_state"] == "dropped"
    assert d["dropped_before_week"] == 0
