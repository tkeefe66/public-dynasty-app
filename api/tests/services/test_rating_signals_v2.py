"""v2 signals reach the refresh output without disturbing the v1 keys."""

from app.services.rating_signals import compute_rating_signals


def _supporting():
    # Four regular-season weeks, not two: standings_as_of needs opponent_points
    # on every entry (it does not re-pair rosters within a week itself -- the
    # docstring's "already opponent-paired" is an upstream assembly contract),
    # and results_signals.latest_played_season won't anchor a season with
    # fewer than MIN_ANCHOR_WEEKS=4 games behind it. Weeks 1/3 and 2/4 repeat
    # the same ua-wins / ua-loses pattern so the all-play win pct this models
    # ("ua beat ub once, lost once, over the season") stays exactly 0.5.
    return {
        "matchups": {
            ("L1", 1, 1): {"team_points": 100.0, "opponent_points": 80.0},
            ("L1", 1, 2): {"team_points": 80.0, "opponent_points": 100.0},
            ("L1", 2, 1): {"team_points": 90.0, "opponent_points": 95.0},
            ("L1", 2, 2): {"team_points": 95.0, "opponent_points": 90.0},
            ("L1", 3, 1): {"team_points": 100.0, "opponent_points": 80.0},
            ("L1", 3, 2): {"team_points": 80.0, "opponent_points": 100.0},
            ("L1", 4, 1): {"team_points": 90.0, "opponent_points": 95.0},
            ("L1", 4, 2): {"team_points": 95.0, "opponent_points": 90.0},
        },
        "roster_to_user_by_league": {"L1": {1: "ua", 2: "ub"}},
        "league_season_by_id": {"L1": 2025},
        "playoff_week_start_by_league": {"L1": 5},
        "winners_bracket_by_league": {"L1": []},
        "losers_bracket_by_league": {"L1": []},
        "num_playoff_teams_by_league": {"L1": 1},
        "ktc_by_player_id": {},
        "player_ages": {"p1": 24, "p2": 31},
        "owners": {"ua": {}, "ub": {}},
    }


def test_v2_results_keys_are_emitted():
    osig, olsig, _lineup, _seasons = compute_rating_signals(
        _supporting(), current_holders={"p1": "ua", "p2": "ub"})
    for uid in ("ua", "ub"):
        assert {"expected_wins", "playoff_success", "luck"} <= set(osig[uid])


def test_v1_outcome_keys_survive_for_their_non_scoring_consumers():
    # grader._playoff_rate_by_uid and gm_rating_blurb both read these. Dropping
    # them would silently tell a champion's blurb writer he has no titles.
    osig, _olsig, _lineup, _seasons = compute_rating_signals(
        _supporting(), current_holders={})
    assert {"championships", "made_playoffs", "final_seed", "points_for_rank"} <= set(osig["ua"])


def test_v2_asset_keys_are_emitted_alongside_the_old_ones():
    _osig, olsig, _lineup, _seasons = compute_rating_signals(
        _supporting(), current_holders={"p1": "ua", "p2": "ub"})
    assert {"roster_value_share", "young_core_share"} <= set(olsig["ua"])
    assert {"roster_value", "draft_capital", "youth"} <= set(olsig["ua"])


def _supporting_three_way():
    # Three rosters, not two: with only one possible opponent, all-play and
    # head-to-head win rate are the same number every week, so a two-roster
    # fixture can't tell expected_wins apart from a head-to-head swap-in. Here
    # ub scores 2nd-highest (of three) every week -- strong on all-play -- but
    # is paired head-to-head against the week's top scorer (ua) every week, so
    # its actual W-L is poor. That's the exact regression this guards: if
    # expected_wins were ever wired to a head-to-head rate instead of
    # all_play_win_pct, ub's number below would read 0.0, not 0.5.
    matchups = {}
    for wk in range(1, 5):
        matchups[("L1", wk, 1)] = {"team_points": 100.0, "opponent_points": 90.0}   # ua
        matchups[("L1", wk, 2)] = {"team_points": 90.0, "opponent_points": 100.0}   # ub
        matchups[("L1", wk, 3)] = {"team_points": 50.0, "opponent_points": 90.0}    # uc
    return {
        "matchups": matchups,
        "roster_to_user_by_league": {"L1": {1: "ua", 2: "ub", 3: "uc"}},
        "league_season_by_id": {"L1": 2025},
        "playoff_week_start_by_league": {"L1": 5},
        "winners_bracket_by_league": {"L1": []},
        "losers_bracket_by_league": {"L1": []},
        "num_playoff_teams_by_league": {"L1": 1},
        "ktc_by_player_id": {},
        "player_ages": {},
        "owners": {"ua": {}, "ub": {}, "uc": {}},
    }


def test_expected_wins_is_all_play_not_head_to_head():
    # By hand, per week: ua beats both others (all-play 2/2), ub beats uc but
    # loses to ua (all-play 1/2 = 0.5), uc loses to both (0/2). Identical every
    # week, so the season aggregate matches: ub's all-play win pct is 0.5.
    #
    # ub's *head-to-head* record (its fabricated opponent_points, always set
    # to ua's score) is 0-4 -- a 0.0 win pct. If expected_wins ever reads that
    # instead of all-play, this assertion catches it.
    osig, _olsig, _lineup, _seasons = compute_rating_signals(
        _supporting_three_way(), current_holders={})
    assert osig["ub"]["expected_wins"] == 0.5
    # luck = actual (head-to-head, 0.0) - expected (all-play, 0.5): the two
    # readings diverge by exactly the gap a head-to-head swap-in would erase.
    assert osig["ub"]["luck"] == -0.5
