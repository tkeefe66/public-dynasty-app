"""Tests for the KeepTradeCut HTML parser."""

import json

from sleeper_dynasty.api.ktc import parse_ktc_html

# Hand-crafted HTML matching the KTC layout: <script> with
# ``var playersArray = [...]; var other = ...;``. We test that the
# parser pulls just the players array out and converts to KTCValue.
_KTC_HTML_TEMPLATE = """
<html><body>
<script>
    var leagueType = 1;
    var playersArray = {players_json};
    var nextThing = "foo";
</script>
</body></html>
"""


def _make_player(
    name: str,
    position: str,
    sf_value: int | None,
    one_qb_value: int | None,
    sf_rank: int | None = None,
    one_qb_rank: int | None = None,
) -> dict:
    return {
        "playerName": name,
        "playerID": 1,
        "slug": name.lower().replace(" ", "-"),
        "position": position,
        "positionID": 1,
        "team": "BUF",
        "rookie": False,
        "age": 25.0,
        "superflexValues": {
            "value": sf_value,
            "rank": 1,
            "positionalRank": sf_rank,
        },
        "oneQBValues": {
            "value": one_qb_value,
            "rank": 1,
            "positionalRank": one_qb_rank,
        },
    }


def _make_html(players: list[dict]) -> str:
    return _KTC_HTML_TEMPLATE.format(players_json=json.dumps(players))


def test_parses_basic_players():
    html = _make_html([
        _make_player("Josh Allen", "QB", 9999, 7650, sf_rank=1, one_qb_rank=1),
        _make_player("Bijan Robinson", "RB", 9989, 9994, sf_rank=1, one_qb_rank=1),
    ])
    out = parse_ktc_html(html)
    assert len(out) == 2

    josh = out["josh allen"]
    assert josh.name == "Josh Allen"
    assert josh.position == "QB"
    assert josh.superflex_value == 9999
    assert josh.one_qb_value == 7650
    assert josh.superflex_position_rank == 1
    assert josh.one_qb_position_rank == 1


def test_normalized_keys_collapse_punctuation():
    html = _make_html([
        _make_player("Ja'Marr Chase", "WR", 9800, 9700),
    ])
    out = parse_ktc_html(html)
    assert "jamarr chase" in out
    assert out["jamarr chase"].name == "Ja'Marr Chase"


def test_includes_rookie_picks():
    html = _make_html([
        _make_player("2026 1.01", "RDP", 8500, 8000),
    ])
    out = parse_ktc_html(html)
    assert "2026 101" in out  # period stripped from "1.01"
    assert out["2026 101"].position == "RDP"


def test_missing_players_array_returns_empty():
    html = "<html><body>no script here</body></html>"
    assert parse_ktc_html(html) == {}


def test_malformed_json_returns_empty():
    html = "<script>var playersArray = [not valid json];</script>"
    assert parse_ktc_html(html) == {}


def test_player_without_required_fields_skipped():
    # Missing playerName -> drop. Missing position -> drop.
    html = _make_html([
        {"playerName": "", "position": "QB"},
        {"position": "RB"},
        _make_player("Good Player", "TE", 5000, 4800),
    ])
    out = parse_ktc_html(html)
    assert len(out) == 1
    assert "good player" in out


def test_handles_null_value_fields():
    # KTC sometimes returns null for a value blob when no data exists
    # for that format (e.g. an obscure rookie pick).
    html = _make_html([
        {
            "playerName": "Niche Pick",
            "position": "RDP",
            "superflexValues": {"value": 1000, "positionalRank": 99},
            "oneQBValues": {"value": None, "positionalRank": None},
        },
    ])
    out = parse_ktc_html(html)
    p = out["niche pick"]
    assert p.superflex_value == 1000
    assert p.one_qb_value is None
    assert p.one_qb_position_rank is None


def test_build_pick_value_table_groups_and_averages_by_round():
    from sleeper_dynasty.api.ktc import build_pick_value_table
    from sleeper_dynasty.models.player import KTCValue

    def pick(name, sf, one):
        return KTCValue(
            name=name, normalized_name=name.lower(), position="PICK",
            superflex_value=sf, one_qb_value=one,
        )

    values = {
        "a": pick("2025 Early 1st", 6000, 5800),
        "b": pick("2025 Mid 1st", 5000, 4800),
        "c": pick("2025 Late 1st", 4000, 3800),
        "d": pick("2025 Early 2nd", 2400, 2200),
        # A real player must be ignored.
        "e": KTCValue(name="Bijan", normalized_name="bijan", position="RB",
                      superflex_value=7500, one_qb_value=7400),
    }

    table = build_pick_value_table(values)

    # 2025 round 1 = average of early/mid/late = (6000+5000+4000)/3 = 5000.
    assert table[(2025, 1)].superflex_value == 5000
    assert table[(2025, 1)].one_qb_value == 4800  # (5800+4800+3800)/3
    # 2025 round 2 = single entry passes through.
    assert table[(2025, 2)].superflex_value == 2400
    # No player leaked in.
    assert (0, 0) not in table
    # Original 2 priced entries; extension adds far-future fallbacks.
    assert len(table) >= 2
    # Fallback for round 1 in a future season uses the latest priced values.
    assert table[(2026, 1)].superflex_value == 5000
    assert table[(2026, 2)].superflex_value == 2400


def test_build_pick_value_table_ignores_unparseable_names():
    from sleeper_dynasty.api.ktc import build_pick_value_table
    from sleeper_dynasty.models.player import KTCValue

    values = {
        "x": KTCValue(name="2025 1st", normalized_name="2025 1st", position="PICK",
                      superflex_value=5500, one_qb_value=5300),
        "y": KTCValue(name="Mystery Pick", normalized_name="mystery pick",
                      position="PICK", superflex_value=999, one_qb_value=999),
    }
    table = build_pick_value_table(values)
    # "2025 1st" (no Early/Mid/Late) parses to (2025, 1); "Mystery Pick" is dropped.
    assert table[(2025, 1)].superflex_value == 5500
    # Extension adds 3 future-year fallbacks for round 1.
    assert len(table) >= 1
    assert table[(2026, 1)].superflex_value == 5500
