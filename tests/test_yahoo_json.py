import json
import pathlib

import pytest

from sleeper_dynasty.api.yahoo_json import collection, merge_fragments, unwrap

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "yahoo"


def _fixture(name):
    path = FIXTURES / f"{name}.json"
    if not path.exists():
        pytest.skip(f"fixture {name}.json not recorded")
    return json.loads(path.read_text())


def test_collection_reads_the_numeric_key_encoding():
    node = {"0": {"a": 1}, "1": {"a": 2}, "count": 2}
    assert collection(node) == [{"a": 1}, {"a": 2}]


def test_collection_orders_numerically_not_lexically():
    """"10" sorts before "2" as a string — that would silently reorder a
    12-team league's rosters."""
    node = {str(i): {"i": i} for i in range(12)}
    node["count"] = 12
    assert [d["i"] for d in collection(node)] == list(range(12))


def test_collection_ignores_the_count_key():
    assert collection({"0": {"a": 1}, "count": 1}) == [{"a": 1}]


def test_collection_of_a_plain_list_is_that_list():
    assert collection([{"a": 1}]) == [{"a": 1}]


def test_collection_of_none_or_empty_is_empty():
    assert collection(None) == []
    assert collection({}) == []
    assert collection({"count": 0}) == []


def test_merge_fragments_flattens_a_list_of_partial_dicts():
    """Yahoo splits one resource across several dicts in a list."""
    assert merge_fragments([
        {"team_key": "461.l.1.t.3"}, {"name": "Team Rocket"}, [],
    ]) == {"team_key": "461.l.1.t.3", "name": "Team Rocket"}


def test_merge_fragments_recurses_into_nested_lists():
    assert merge_fragments([[{"a": 1}], [{"b": 2}]]) == {"a": 1, "b": 2}


def test_merge_fragments_keeps_the_first_value_on_a_key_collision():
    assert merge_fragments([{"a": 1}, {"a": 2}]) == {"a": 1}


def test_merge_fragments_passes_a_dict_through():
    assert merge_fragments({"a": 1}) == {"a": 1}


def test_unwrap_walks_a_key_path():
    payload = {"fantasy_content": {"league": [{"name": "X"}]}}
    assert unwrap(payload, "fantasy_content", "league") == [{"name": "X"}]


def test_unwrap_returns_none_for_a_missing_path():
    assert unwrap({"fantasy_content": {}}, "fantasy_content", "league") is None


def test_unwrap_returns_none_rather_than_raising_on_a_non_dict():
    assert unwrap({"fantasy_content": 3}, "fantasy_content", "league") is None


def test_real_league_payload_yields_a_league_name():
    payload = _fixture("league_meta")
    league = merge_fragments(unwrap(payload, "fantasy_content", "league"))
    assert isinstance(league.get("name"), str) and league["name"]
    assert league.get("league_key")


def test_real_teams_payload_yields_every_team():
    payload = _fixture("teams")
    node = unwrap(payload, "fantasy_content", "league")
    teams = collection(merge_fragments(node).get("teams"))
    assert len(teams) >= 2
    assert all(merge_fragments(t.get("team")).get("team_key") for t in teams)
