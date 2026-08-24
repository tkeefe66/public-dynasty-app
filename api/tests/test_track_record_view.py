from __future__ import annotations

from app.services.track_record_view import build_track_record


def _rec(wins, losses, rank, *, champ=False, ru=False, made=False,
         rounds=0, place=None):
    return {
        "wins": wins, "losses": losses, "ties": 0, "rank": rank,
        "total_teams": 3, "champion": champ, "runner_up": ru,
        "made_playoffs": made, "rounds_won": rounds, "playoff_place": place,
        "toilet_place": None,
    }


SEASON_RECORDS = {
    "2024": {
        "a": _rec(10, 3, 1, champ=True, made=True, rounds=2, place=1),
        "b": _rec(7, 6, 2, ru=True, made=True, rounds=1, place=2),
        "c": _rec(2, 11, 3),
    },
    "2025": {
        "a": _rec(8, 5, 2, ru=True, made=True, rounds=1, place=2),
        "b": _rec(9, 4, 1, champ=True, made=True, rounds=2, place=1),
        "c": _rec(3, 10, 3),
    },
}


def test_seasons_are_chronological_with_finish_and_bracket():
    tr = build_track_record(SEASON_RECORDS, "a")
    assert [s.season for s in tr.seasons] == [2024, 2025]
    s24 = tr.seasons[0]
    assert s24.rank == 1 and s24.of == 3
    assert s24.champion is True and s24.made_playoffs is True
    assert s24.playoff_place == 1
    assert tr.seasons[1].runner_up is True


def test_career_rollups():
    a = build_track_record(SEASON_RECORDS, "a")
    assert a.titles == 1
    assert a.runner_ups == 1
    assert a.playoff_appearances == 2
    assert a.seasons_played == 2
    assert a.best_finish == 1            # best playoff placement
    assert a.career_wins == 18
    assert a.career_losses == 8


def test_owner_who_never_made_playoffs_has_no_best_finish():
    c = build_track_record(SEASON_RECORDS, "c")
    assert c.titles == 0
    assert c.playoff_appearances == 0
    assert c.best_finish is None
    assert c.seasons_played == 2
    assert all(s.made_playoffs is False for s in c.seasons)


def test_absent_owner_is_empty():
    g = build_track_record(SEASON_RECORDS, "ghost")
    assert g.seasons == []
    assert g.seasons_played == 0
    assert g.titles == 0
    assert g.best_finish is None
