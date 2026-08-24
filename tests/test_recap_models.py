from sleeper_dynasty.models.recap import (
    MatchupRecap, PlayerLine, BenchRegret, LuckNote, RecapFacts,
    MatchupPreview, ByeTrouble, WeatherNote, PlayoffStake, OutlookFacts,
)


def test_matchup_recap_to_dict_roundtrips():
    m = MatchupRecap(
        winner="Team A", loser="Team B", winner_points=142.3,
        loser_points=98.1, margin=44.2, blowout=True, nailbiter=False,
    )
    d = m.to_dict()
    assert d["winner"] == "Team A"
    assert d["margin"] == 44.2
    assert d["blowout"] is True


def test_recap_facts_to_dict_nests_sections():
    facts = RecapFacts(
        week=9,
        league_name="Dynasty Bros",
        standings=[{"owner": "Team A", "wins": 6, "losses": 2}],
        matchups=[],
        high_scorer={"owner": "Team A", "points": 158.0},
        low_scorer={"owner": "Team B", "points": 71.2},
        bench_regret=[],
        lucky=[],
        unlucky=[],
        heroes=[],
        goats=[],
        busts=[],
    )
    d = facts.to_dict()
    assert d["week"] == 9
    assert d["high_scorer"]["points"] == 158.0
    assert "matchups" in d


def test_outlook_facts_to_dict():
    o = OutlookFacts(
        week=10,
        matchups=[MatchupPreview("A", "B", 115.0, 102.0, "A", 13.0)],
        byes=[ByeTrouble("A", ["Josh Allen (QB, BUF)"],
                         "Backup Guy (QB, CHI)", 6.0)],
        weather=[WeatherNote("BUF @ NE", 22, 28, "snow",
                             ["a kicker"])],
        playoff_stakes=[PlayoffStake("A", "must-win")],
    )
    d = o.to_dict()
    assert d["week"] == 10
    assert d["matchups"][0]["favorite"] == "A"
    assert d["byes"][0]["likely_replacement"] == "Backup Guy (QB, CHI)"
    assert d["weather"][0]["precip"] == "snow"
    assert d["playoff_stakes"][0]["status"] == "must-win"
