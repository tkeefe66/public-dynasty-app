import copy
import json

import httpx
import pytest

from sleeper_dynasty.api.score_authority import reconcile_scores, ScoreConflict


def evidence():
    league = {"settings": {"last_scored_leg": 1, "playoff_week_start": 15}}
    rows = [{"roster_id": 1, "matchup_id": 1, "points": "133.66", "custom_points": None,
             "starters": ["p"], "players_points": {"p": "17.2"}},
            {"roster_id": 2, "matchup_id": 1, "points": "132.72", "custom_points": None,
             "starters": ["q"], "players_points": {"q": "22"}}]
    rosters = [{"roster_id": 1, "settings": {"wins": 1, "losses": 0, "ties": 0,
                "fpts": 133, "fpts_decimal": 66, "fpts_against": 132, "fpts_against_decimal": 72}},
               {"roster_id": 2, "settings": {"wins": 0, "losses": 1, "ties": 0,
                "fpts": 132, "fpts_decimal": 72, "fpts_against": 133, "fpts_against_decimal": 66}}]
    return league, rosters, {"1": rows}


def test_late_player_stat_does_not_reverse_official_result():
    league, rosters, original = evidence()
    current = copy.deepcopy(original)
    current["1"][0].update(points="132.66", players_points={"p": "16.2"})
    got = reconcile_scores(league, rosters, current, original)
    assert got["1"][0]["points"] == "133.66"
    assert got["1"][0]["players_points"]["p"] == "16.2"
    assert got["1"][0]["score_authority"]["api_points"] == "132.66"
    assert current["1"][0]["points"] == "132.66"


def test_actual_official_correction_advances_without_manual_override():
    league, rosters, original = evidence()
    current = copy.deepcopy(original)
    current["1"][0]["points"] = "132.66"
    rosters[0]["settings"].update(fpts=132, wins=0, losses=1)
    rosters[1]["settings"].update(fpts_against=132, wins=1, losses=0)
    assert reconcile_scores(league, rosters, current, original)["1"][0]["points"] == "132.66"


@pytest.mark.parametrize("change", ["missing", "lineup", "opponent", "official", "zero_override"])
def test_conflicts_fail_explicitly_instead_of_selecting_unverified_scores(change):
    league, rosters, saved = evidence()
    current = copy.deepcopy(saved)
    current["1"][0]["points"] = "132.66"
    if change == "missing":
        saved = {}
    if change == "lineup":
        current["1"][0]["starters"] = ["replacement"]
    if change == "opponent":
        current["1"][0]["matchup_id"] = 2
    if change == "official":
        rosters[0]["settings"]["fpts"] = 140
    if change == "zero_override":
        current["1"][0]["custom_points"] = 0
    with pytest.raises(ScoreConflict):
        reconcile_scores(league, rosters, current, saved)


def test_subpoint_disagreement_is_not_rounded_away():
    league, rosters, current = evidence()
    current["1"][0]["points"] = "133.65"
    with pytest.raises(ScoreConflict):
        reconcile_scores(league, rosters, current, {})


def test_official_correction_and_unsettled_player_change_coexist():
    league, rosters, saved = evidence()
    current = copy.deepcopy(saved)
    current["1"][0]["points"] = "132.66"  # Not an official result change.
    current["1"][1]["points"] = "131.72"  # This correction is official.
    rosters[1]["settings"]["fpts"] = 131
    rosters[0]["settings"]["fpts_against"] = 131
    got = reconcile_scores(league, rosters, current, saved)
    assert [r["points"] for r in got["1"]] == ["133.66", "131.72"]


def test_same_roster_can_have_official_and_unsettled_changes_in_different_weeks():
    league, rosters, saved = evidence()
    league["settings"]["last_scored_leg"] = 2
    saved["2"] = copy.deepcopy(saved["1"])
    current = copy.deepcopy(saved)
    current["1"][0]["points"] = "132.66"
    current["2"][0]["points"] = "134.66"
    rosters[0]["settings"].update(fpts=268, fpts_decimal=32, fpts_against=265, fpts_against_decimal=44, wins=2)
    rosters[1]["settings"].update(fpts=265, fpts_decimal=44, fpts_against=268, fpts_against_decimal=32, losses=2)
    got = reconcile_scores(league, rosters, current, saved)
    assert got["1"][0]["points"] == "133.66"
    assert got["2"][0]["points"] == "134.66"


def test_new_week_retains_prior_verified_result_and_reconciles_new_official_record():
    league, rosters, saved = evidence()
    league["settings"]["last_scored_leg"] = 2
    current = copy.deepcopy(saved)
    current["1"][0]["points"] = "132.66"
    current["2"] = copy.deepcopy(saved["1"])
    for r in rosters:
        s = r["settings"]
        for whole, fraction in [("fpts", "fpts_decimal"), ("fpts_against", "fpts_against_decimal")]:
            cents = 2 * (s[whole] * 100 + s[fraction])
            s[whole], s[fraction] = divmod(cents, 100)
        s["wins"] *= 2
        s["losses"] *= 2
    got = reconcile_scores(league, rosters, current, saved)
    assert got["1"][0]["points"] == got["2"][0]["points"] == "133.66"


@pytest.mark.asyncio
async def test_all_ingestion_paths_share_authority_and_restart_keeps_verified_result(tmp_path):
    from sleeper_dynasty.api.sleeper import SleeperClient
    league, rosters, current = evidence()
    league.update(status="in_season", season="2026")
    async def route(request):
        path = request.url.path
        data = current["1"] if "/matchups/" in path else rosters if path.endswith("/rosters") else league
        return httpx.Response(200, json=data)
    async def client():
        c = SleeperClient(score_cache_dir=tmp_path)
        await c._client.aclose()
        c._client = httpx.AsyncClient(transport=httpx.MockTransport(route), base_url="https://api.sleeper.app/v1")
        return c
    first = await client()
    assert (await first.get_raw_matchups("10001", 1))[0]["points"] == 133.66
    await first.close()
    current["1"][0].update(points="132.66", players_points={"p": "16.2"})
    restarted = await client()
    try:
        assert (await restarted.get_matchups("10001", 1))[0].points_1 == 133.66
        assert (await restarted.get_matchup_results("10001", 1))[0].points == 133.66
        source = await restarted.get_recap_source("/league/10001/matchups/1")
        assert source["ok"] and source["data"][0]["points"] == "133.66"
        assert source["data"][0]["players_points"]["p"] == "16.2"
        assert json.loads(source["raw"])[0]["points"] == "132.66"
        assert source["score_verification"]["through_week"] == 1
        assert (await restarted.get_recap_source("/league/10001/matchups/15"))["score_verification"] == {}
    finally:
        await restarted.close()


@pytest.mark.asyncio
async def test_unknown_conflict_invalidates_recap_source_without_baseline(tmp_path):
    from sleeper_dynasty.api.sleeper import SleeperClient
    league, rosters, current = evidence()
    league.update(status="in_season", season="2026")
    current["1"][0]["points"] = "132.66"
    def route(request):
        path = request.url.path
        return httpx.Response(200, json=current["1"] if "/matchups/" in path else rosters if path.endswith("/rosters") else league)
    c = SleeperClient(score_cache_dir=tmp_path)
    await c._client.aclose()
    c._client = httpx.AsyncClient(transport=httpx.MockTransport(route), base_url="https://api.sleeper.app/v1")
    try:
        assert (await c.get_recap_source("/league/10001/matchups/1"))["error"] == "score_source_conflict"
        with pytest.raises(ScoreConflict):
            await c.get_raw_matchups("10001", 1)
        # Conflicting completed results must not block upcoming/postseason reads.
        assert (await c.get_raw_matchups("10001", 2))[0]["points"] == "132.66"
        assert (await c.get_raw_matchups("10001", 15))[0]["points"] == "132.66"
        assert not list(tmp_path.rglob("*.json"))
    finally:
        await c.close()
