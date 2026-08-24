import pytest

from sleeper_dynasty.engine.results_signals import (
    decayed_mean, latest_played_season, owners_with_completed_season,
    results_signals, season_weight,
)


def test_season_weight_halves_every_two_seasons():
    assert season_weight(2025, 2025) == 1.0
    assert season_weight(2024, 2025) == pytest.approx(0.7071, abs=1e-4)
    assert season_weight(2023, 2025) == pytest.approx(0.5)


def test_season_weight_is_clamped_at_one_for_future_seasons():
    # draft_skill_by_season already holds a 2026 class while 2025 is the
    # anchor. Unclamped this returns 1.414 and the least-played evidence
    # outweighs the anchor.
    assert season_weight(2026, 2025) == 1.0


def test_decayed_mean_weights_recent_seasons_more():
    out = decayed_mean({2023: 0.0, 2024: 0.0, 2025: 1.0}, 2025)
    # 1.0 / (1.0 + 0.7071 + 0.5)
    assert out == pytest.approx(1.0 / 2.2071, abs=1e-4)


def test_decayed_mean_of_nothing_is_zero():
    assert decayed_mean({}, 2025) == 0.0


def test_latest_played_season_ignores_a_season_under_the_week_floor():
    records = {
        2025: {"u": {"wins": 7, "losses": 7, "ties": 0}},
        2026: {"u": {"wins": 1, "losses": 1, "ties": 0}},   # 2 games, below floor
    }
    assert latest_played_season(records, min_weeks=4) == 2025


def test_latest_played_season_is_none_when_nothing_has_been_played():
    assert latest_played_season({2026: {"u": {"wins": 0, "losses": 0, "ties": 0}}}) is None


def test_results_signals_computes_the_trio():
    all_play = {2025: {"ua": 0.75, "ub": 0.25}}
    records = {
        2025: {
            "ua": {"wins": 7, "losses": 7, "ties": 0, "made_playoffs": True,
                   "rounds_won": 2, "champion": True},
            "ub": {"wins": 7, "losses": 7, "ties": 0, "made_playoffs": False,
                   "rounds_won": 0, "champion": False},
        }
    }
    out = results_signals(
        all_play_by_season=all_play, season_records=records,
        owners=["ua", "ub"], latest_played_season=2025)

    assert out["ua"]["expected_wins"] == pytest.approx(0.75)
    # 0.5 berth + 1.0 * 2 rounds + 1.5 championship
    assert out["ua"]["playoff_success"] == pytest.approx(4.0)
    # actual .500 minus expected .750
    assert out["ua"]["luck"] == pytest.approx(-0.25)

    assert out["ub"]["playoff_success"] == pytest.approx(0.0)
    assert out["ub"]["luck"] == pytest.approx(0.25)


def test_luck_is_orthogonal_to_expected_wins_by_construction():
    # An owner who scores well and loses close games has NEGATIVE luck; the
    # signal isolates schedule noise instead of re-injecting it.
    all_play = {2025: {"ua": 0.90}}
    records = {2025: {"ua": {"wins": 7, "losses": 7, "ties": 0,
                             "made_playoffs": False, "rounds_won": 0,
                             "champion": False}}}
    out = results_signals(all_play_by_season=all_play, season_records=records,
                          owners=["ua"], latest_played_season=2025)
    assert out["ua"]["luck"] < 0


def test_results_signals_gives_every_requested_owner_a_row():
    out = results_signals(
        all_play_by_season={}, season_records={}, owners=["ua"],
        latest_played_season=2025)
    assert out == {"ua": {"expected_wins": 0.0, "playoff_success": 0.0, "luck": 0.0}}


def test_owners_with_completed_season_excludes_a_manager_who_never_played():
    records = {
        2025: {"veteran": {"wins": 7, "losses": 7, "ties": 0}},
        # The preseason shape: 2026 rows exist for everyone, nobody has played.
        2026: {"veteran": {"wins": 0, "losses": 0, "ties": 0},
               "rookie_gm": {"wins": 0, "losses": 0, "ties": 0}},
    }
    assert owners_with_completed_season(records) == {"veteran"}


def test_owners_with_completed_season_applies_the_same_week_floor_as_the_anchor():
    records = {2026: {"u": {"wins": 1, "losses": 1, "ties": 0}}}   # 2 games
    assert owners_with_completed_season(records, min_weeks=4) == set()


def test_owners_with_completed_season_is_empty_when_the_league_has_played_nothing():
    assert owners_with_completed_season({}) == set()
