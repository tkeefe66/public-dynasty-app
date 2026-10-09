from unittest.mock import AsyncMock

import pytest

from tests.test_analyst import setup_league
from sleeper_dynasty.models.player import build_players
from sleeper_dynasty.models.scoring import ThresholdBonus


@pytest.mark.asyncio
async def test_preview_uses_next_week_projections_and_skips_missing_data(monkeypatch):
    # Mutation: fetch recap-week projections, or invent zero-point predictions.
    from app.services.analyst_outlook import upcoming_outlook
    client, _, _ = setup_league()
    league, _ = await client.get_league("123")
    league.scoring_settings = {"pass_td": 4}
    rosters = await client.get_rosters("123")
    players = build_players(await client.get_players())
    async def projections(season, week):
        return {"p1": {"pass_td": 8 if week == 2 else 1}, "p2": {"pass_td": 2}}
    client.get_projections.side_effect = projections
    monkeypatch.setattr("app.services.analyst_outlook.fetch_week_schedule", AsyncMock(return_value=[]))
    result = await upcoming_outlook(client, league, 2, rosters, players)
    assert result.week == 2
    assert result.matchups[0].home_projected == 32
    assert result.matchups[0].away_projected == 8
    client.get_projections.side_effect = None
    client.get_projections.return_value = {}
    assert await upcoming_outlook(client, league, 2, rosters, players) is None


@pytest.mark.asyncio
async def test_washington_alias_and_unknown_teams_are_not_byes(monkeypatch):
    # Mutation: compare raw WAS to ESPN WSH, or classify unknown teams as idle.
    from app.services.analyst_outlook import upcoming_outlook
    from sleeper_dynasty.api.nfl_schedule import NFL_TEAMS
    client, _, _ = setup_league()
    league, _ = await client.get_league("123")
    rosters = await client.get_rosters("123")
    raw = await client.get_players()
    raw["p1"]["team"] = "WAS"
    raw["p2"]["team"] = "FA"
    teams = sorted(NFL_TEAMS)
    games = [{"home": teams[i], "away": teams[i+1], "indoor": True}
             for i in range(0, 32, 2)]
    client.get_projections.return_value = {"p1": {"pass_td": 1}, "p2": {"pass_td": 1}}
    monkeypatch.setattr("app.services.analyst_outlook.fetch_week_schedule", AsyncMock(return_value=games))
    result = await upcoming_outlook(client, league, 2, rosters, build_players(raw))
    assert result.byes == []


@pytest.mark.asyncio
@pytest.mark.parametrize("rule_format", ["typed", "legacy"])
@pytest.mark.parametrize("bonus_points, preview_available", [(None, True), (0, True), (3, False), (-2, False)])
async def test_threshold_bonus_forecasts_are_omitted_without_inventing_base_only_totals(
    monkeypatch, bonus_points, preview_available, rule_format,
):
    from app.services.analyst_outlook import upcoming_outlook

    client, _, _ = setup_league()
    league, _ = await client.get_league("123")
    league.scoring_settings = {"pass_td": 4}
    if bonus_points is not None:
        if rule_format == "legacy":
            league.scoring_settings["bonus_gte:pass_yd:300"] = bonus_points
        else:
            league.scoring_bonuses = [ThresholdBonus(("pass_yd",), 300, bonus_points)]
    rosters = await client.get_rosters("123")
    players = build_players(await client.get_players())
    client.get_projections.return_value = {"p1": {"pass_td": 3}, "p2": {"pass_td": 2}}
    schedule = AsyncMock(return_value=[])
    monkeypatch.setattr("app.services.analyst_outlook.fetch_week_schedule", schedule)

    result = await upcoming_outlook(client, league, 2, rosters, players)
    if preview_available:
        assert result.matchups[0].home_projected == 12
        assert result.matchups[0].away_projected == 8
        client.get_projections.assert_awaited_once_with(2026, 2)
    else:
        assert result is None
        client.get_projections.assert_not_awaited()
        client.get_matchup_results.assert_not_awaited()
        schedule.assert_not_awaited()
