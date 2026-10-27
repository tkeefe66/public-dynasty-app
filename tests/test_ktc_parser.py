"""Tests for the KeepTradeCut HTML parser."""

import json

import pytest

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
    html = _make_html(
        [
            _make_player("Josh Allen", "QB", 9999, 7650, sf_rank=1, one_qb_rank=1),
            _make_player("Bijan Robinson", "RB", 9989, 9994, sf_rank=1, one_qb_rank=1),
        ]
    )
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
    html = _make_html(
        [
            _make_player("Ja'Marr Chase", "WR", 9800, 9700),
        ]
    )
    out = parse_ktc_html(html)
    assert "jamarr chase" in out
    assert out["jamarr chase"].name == "Ja'Marr Chase"


def test_includes_rookie_picks():
    html = _make_html(
        [
            _make_player("2026 1.01", "RDP", 8500, 8000),
        ]
    )
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
    html = _make_html(
        [
            {"playerName": "", "position": "QB"},
            {"position": "RB"},
            _make_player("Good Player", "TE", 5000, 4800),
        ]
    )
    out = parse_ktc_html(html)
    assert len(out) == 1
    assert "good player" in out


def test_handles_null_value_fields():
    # KTC sometimes returns null for a value blob when no data exists
    # for that format (e.g. an obscure rookie pick).
    html = _make_html(
        [
            {
                "playerName": "Niche Pick",
                "position": "RDP",
                "superflexValues": {"value": 1000, "positionalRank": 99},
                "oneQBValues": {"value": None, "positionalRank": None},
            },
        ]
    )
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
            name=name,
            normalized_name=name.lower(),
            position="PICK",
            superflex_value=sf,
            one_qb_value=one,
        )

    values = {
        "a": pick("2025 Early 1st", 6000, 5800),
        "b": pick("2025 Mid 1st", 5000, 4800),
        "c": pick("2025 Late 1st", 4000, 3800),
        "d": pick("2025 Early 2nd", 2400, 2200),
        # A real player must be ignored.
        "e": KTCValue(
            name="Bijan",
            normalized_name="bijan",
            position="RB",
            superflex_value=7500,
            one_qb_value=7400,
        ),
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
        "x": KTCValue(
            name="2025 1st",
            normalized_name="2025 1st",
            position="PICK",
            superflex_value=5500,
            one_qb_value=5300,
        ),
        "y": KTCValue(
            name="Mystery Pick",
            normalized_name="mystery pick",
            position="PICK",
            superflex_value=999,
            one_qb_value=999,
        ),
    }
    table = build_pick_value_table(values)
    # "2025 1st" (no Early/Mid/Late) parses to (2025, 1); "Mystery Pick" is dropped.
    assert table[(2025, 1)].superflex_value == 5500
    # Extension adds 3 future-year fallbacks for round 1.
    assert len(table) >= 1
    assert table[(2026, 1)].superflex_value == 5500


def test_parses_json_script_payload_with_attribute_order_and_legacy_fallback():
    players = [_make_player("Example Runner", "RB", 532, 677)]
    html = '<script type="application/json" id="unrelated">[]</script>'
    html += "<script data-test='1' id='ktc-players' type='application/json'>"
    html += json.dumps(players) + "</script>"
    out = parse_ktc_html(html)
    assert out["example runner"].superflex_value == 532
    assert out["example runner"].one_qb_value == 677
    assert parse_ktc_html(_make_html(players)) == out


def test_invalid_json_script_payload_fails_closed():
    for payload in ("not json", "{}", '[null, 1, "bad"]'):
        assert (
            parse_ktc_html(
                f'<script id="ktc-players" type="application/json">{payload}</script>'
            )
            == {}
        )


def test_profile_value_requires_matching_identity():
    from sleeper_dynasty.api.ktc import parse_ktc_profile

    raw = _make_player("Example Reserve", "TE", 276, 212)
    raw["slug"] = "example-reserve-fixture"
    html = "<script>var player = " + json.dumps(raw) + ";</script>"
    expected = {"slug": raw["slug"], "name": raw["playerName"], "position": "TE"}
    assert parse_ktc_profile(html, expected).superflex_value == 276
    for field, bad in [("slug", "wrong"), ("name", "Other Player"), ("position", "RB")]:
        assert parse_ktc_profile(html, {**expected, field: bad}) is None
    assert parse_ktc_profile("<html>unavailable</html>", expected) is None


@pytest.mark.asyncio
async def test_fetches_configured_profile_without_overriding_ranked_value(monkeypatch):
    import httpx

    from sleeper_dynasty.api import ktc

    real_client = httpx.AsyncClient
    raw = _make_player("Example Reserve", "TE", 276, 212)
    raw["slug"] = "example-reserve-fixture"
    monkeypatch.setenv(
        "KTC_SUPPLEMENTAL_PROFILES",
        json.dumps(
            [
                {"slug": raw["slug"], "name": raw["playerName"], "position": "TE"},
            ]
        ),
    )
    requests = []

    def handler(request):
        requests.append(str(request.url))
        if "/players/" in request.url.path:
            return httpx.Response(
                200, text="<script>var player = " + json.dumps(raw) + ";</script>"
            )
        return httpx.Response(200, text=_make_html([]))

    monkeypatch.setattr(
        ktc.httpx,
        "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )
    values = await ktc.fetch_ktc_values()
    assert values["example reserve"].superflex_value == 276
    assert len(requests) == 3
    raw["position"] = "RB"
    assert await ktc.fetch_ktc_values() == {}


def test_malformed_profile_value_blob_does_not_abort_import():
    from sleeper_dynasty.api.ktc import parse_ktc_profile

    raw = _make_player("Example Reserve", "TE", 276, 212)
    raw["slug"] = "example-reserve-fixture"
    raw["superflexValues"] = "invalid"
    expected = {"slug": raw["slug"], "name": raw["playerName"], "position": "TE"}
    assert (
        parse_ktc_profile(
            "<script>var player = " + json.dumps(raw) + ";</script>", expected
        )
        is None
    )
