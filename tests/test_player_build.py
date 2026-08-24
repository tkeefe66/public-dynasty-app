from datetime import date

from sleeper_dynasty.models.player import build_players, parse_birth_date


def test_parse_birth_date_iso_string():
    assert parse_birth_date("1996-07-26") == date(1996, 7, 26)


def test_parse_birth_date_malformed_is_none():
    assert parse_birth_date("not-a-date") is None
    assert parse_birth_date(None) is None


def test_build_players_maps_fields_and_skips_non_dicts():
    raw = {
        "p1": {"full_name": "Bijan Robinson", "position": "RB",
               "team": "ATL", "birth_date": "2001-12-30", "years_exp": 2},
        "p2": {"first_name": "Sam", "last_name": "LaPorta", "position": "TE"},
        "junk": ["not", "a", "dict"],
    }
    players = build_players(raw)
    assert "junk" not in players
    assert players["p1"].full_name == "Bijan Robinson"
    assert players["p1"].position == "RB"
    assert players["p1"].birth_date == date(2001, 12, 30)
    # full_name falls back to "first last"
    assert players["p2"].full_name == "Sam LaPorta"
