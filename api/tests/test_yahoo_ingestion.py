"""Platform routing and phase-map integration at the grader boundary."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.services import grader_io


@pytest.mark.asyncio
async def test_yahoo_bundle_uses_platform_phases_without_bracket_methods():
    # Mutation: calling Sleeper-only brackets fails before Yahoo can be graded.
    client = SimpleNamespace(
        get_rosters=AsyncMock(return_value=[]),
        get_users=AsyncMock(return_value={}),
        get_raw_matchups=AsyncMock(return_value=[]),
        get_phase_map=AsyncMock(return_value={(16, 2): "playoff", (16, 7): "toilet"}),
        get_postseason_results=AsyncMock(return_value={2: {"champion": True}}),
    )
    league = SimpleNamespace(
        league_id="470.l.100000001",
        status="complete",
        playoff_week_start=16,
        name="Example",
        season=2026,
    )
    bundle = await grader_io._league_matchup_bundle(client, league, None)
    assert bundle["phase_map"] == {"16:2": "playoff", "16:7": "toilet"}
    assert bundle["winners_bracket"] == []
    assert bundle["postseason_results"] == {"2": {"champion": True}}


@pytest.mark.asyncio
@pytest.mark.parametrize("phases", [{}, {"16:2": "toilet"}])
async def test_stored_phase_map_is_authoritative_even_when_empty(
    monkeypatch, tmp_path, phases
):
    # Mutation: `if stored` incorrectly falls back to stale brackets for {}.
    monkeypatch.setattr(grader_io, "fetch_ktc_values", AsyncMock(return_value={}))
    monkeypatch.setattr(
        grader_io, "fetch_fantasycalc_values", AsyncMock(return_value={})
    )
    monkeypatch.setattr(grader_io, "fetch_nfl_points", AsyncMock(return_value={}))
    bundle = {
        "league_name": "Example",
        "season": 2026,
        "playoff_week_start": 16,
        "roster_to_user": {},
        "owners": {},
        "matchups": {},
        "phase_map": phases,
        "winners_bracket": [{"r": 1, "t1": 2, "t2": 3, "w": 2, "l": 3}],
        "postseason_results": {"2": {"champion": True}},
    }
    monkeypatch.setattr(
        grader_io, "_league_matchup_bundle", AsyncMock(return_value=bundle)
    )
    league = SimpleNamespace(league_id="470.l.100000001", format="keeper", season=2026)
    out = await grader_io.pull_supporting_data(
        SimpleNamespace(),
        [league],
        players={},
        league_cache=SimpleNamespace(cache_dir=tmp_path),
    )
    expected = {(league.league_id, 16, 2): "toilet"} if phases else {}
    assert out["phase_by_lwr"] == expected
    assert out["postseason_results_by_league"][league.league_id] == {
        2: {"champion": True}
    }


@pytest.mark.asyncio
async def test_factory_requires_explicit_yahoo_credentials(monkeypatch):
    # Mutation: server-wide developer token silently grants another user access.
    from app.services.platform_client import YahooCredentialsMissing, client_for_league

    from sleeper_dynasty.api.sleeper import SleeperClient
    from sleeper_dynasty.api.yahoo import YahooAdapter

    monkeypatch.setenv("YAHOO_DEV_ACCESS_TOKEN", "must-not-be-used")
    with pytest.raises(YahooCredentialsMissing):
        client_for_league("470.l.100000001")
    with pytest.raises(ValueError):
        client_for_league("470.l.100000001/../../other")
    yahoo = client_for_league("470.l.100000001", access_token="synthetic")
    sleeper = client_for_league("100000001")
    try:
        assert isinstance(yahoo, YahooAdapter)
        assert isinstance(sleeper, SleeperClient)
    finally:
        await yahoo.close()
        await sleeper.close()


def test_normalized_postseason_results_reach_record_and_rating_signals():
    # Regression: Yahoo phases existed but bracket-only consumers gave every
    # champion zero postseason credit and hid every playoff appearance.
    from app.services.rating_signals import compute_rating_signals

    key = "461.l.100000002"
    outcomes = {
        3: {
            "champion": True,
            "runner_up": False,
            "made_playoffs": True,
            "rounds_won": 2,
            "playoff_place": 1,
        },
        2: {
            "champion": False,
            "runner_up": True,
            "made_playoffs": True,
            "rounds_won": 1,
            "playoff_place": 2,
        },
        7: {
            "champion": False,
            "runner_up": False,
            "made_playoffs": True,
            "rounds_won": 0,
            "playoff_place": 3,
        },
        9: {
            "champion": False,
            "runner_up": False,
            "made_playoffs": False,
            "rounds_won": 0,
            "made_toilet": True,
            "toilet_place": 1,
        },
    }
    owners = {rid: f"owner{rid}" for rid in outcomes}
    supporting = {
        "matchups": {
            (key, w, rid): {"team_points": 100 + rid, "opponent_points": 100}
            for w in range(1, 16)
            for rid in owners
        },
        "roster_to_user_by_league": {key: owners},
        "league_season_by_id": {key: 2025},
        "playoff_week_start_by_league": {key: 16},
        "num_playoff_teams_by_league": {key: 4},
        "postseason_results_by_league": {key: outcomes},
        "owners": {u: {} for u in owners.values()},
    }
    signals, _, _, records = compute_rating_signals(supporting, {})
    assert records["2025"]["owner3"]["champion"]
    assert records["2025"]["owner2"]["runner_up"]
    assert records["2025"]["owner7"]["made_playoffs"]
    assert records["2025"]["owner9"]["toilet_place"] == 1
    assert (
        signals["owner3"]["playoff_success"]
        > signals["owner2"]["playoff_success"]
        > signals["owner7"]["playoff_success"]
        > signals["owner9"]["playoff_success"]
    )
