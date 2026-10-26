from copy import deepcopy

import pytest

from app.services.aggregations import build_dashboard
from app.services.leaderboard import build_leaderboard
from app.services.franchise_redesign import live_ratings
from tests.test_aggregations import _sample_entry


@pytest.mark.parametrize("rosters", [None, {}, {1: "u_alice"}])
def test_missing_season_membership_is_unverified_not_ranked(rosters):
    # Mutation: missing/partial season roster falls back to all historical owners.
    entry = _sample_entry()
    entry.owners["unknown"] = {"owner_name": "Unknown participant"}
    if rosters is None:
        del entry.roster_to_user_by_league["L_prev"]
    else:
        entry.roster_to_user_by_league["L_prev"] = rosters
    before = deepcopy(entry)
    result = build_dashboard(entry, 2024, "ktc")
    assert {r.user_id for r in result.standings} == {"u_alice", "u_bob"}
    assert [o.user_id for o in result.unverified_season_owners] == ["unknown"]
    assert entry == before
    assert "unknown" in {r.user_id for r in build_dashboard(entry, "all", "ktc").standings}


def test_no_evidence_has_no_rankings_and_no_highlights():
    # Mutation: use another season's participation when requested year is unknown.
    entry = _sample_entry()
    result = build_dashboard(entry, 2025, "ktc")
    assert result.standings == []
    assert {o.user_id for o in result.unverified_season_owners} == set(entry.owners)
    assert result.hero_stats.top_gm.owner_user_id is None
    assert result.hero_stats.best_roster.owner_user_id is None


def test_complete_roster_absence_is_not_an_unverified_participant():
    # Mutation: list every historical owner as unverified, even with complete evidence.
    entry = _sample_entry()
    entry.owners["not_in_year"] = {"owner_name": "Not in this year"}
    result = build_dashboard(entry, 2024, "ktc")
    assert "not_in_year" not in {r.user_id for r in result.standings}
    assert result.unverified_season_owners == []


@pytest.mark.parametrize("format", ["dynasty", "keeper", "redraft"])
def test_unknown_participation_cannot_influence_ratings(format):
    # Mutation: hide unknown rows after calculating grades against their signals.
    entry = _sample_entry()
    entry.owners["unknown"] = {"owner_name": "Unknown participant"}
    entry.roster_to_user_by_league = {}
    signals = {uid: {"expected_wins": value, "playoff_success": value, "luck": value}
               for uid, value in [("u_alice", .7), ("u_bob", .4), ("unknown", 100)]}
    assets = {uid: {"roster_value_share": value, "young_core_share": value, "draft_capital": value}
              for uid, value in [("u_alice", .6), ("u_bob", .4), ("unknown", 100)]}
    entry.season_rating_inputs = {"2024": {
        "version": 1, "status": "ready", "format": format,
        "owners": list(signals), "outcome_signals": signals, "outlook_signals": assets,
        # Career evidence for unknown is from 2023, not the requested 2024.
        "season_records": {"2023": {uid: {"wins": 8, "losses": 6, "rank": 1, "total_teams": 3} for uid in signals}},
        "roster_ranks": {"unknown": {"rank": 1, "of": 3}, "u_alice": {"rank": 2, "of": 3}, "u_bob": {"rank": 3, "of": 3}},
    }}
    expected = deepcopy(entry)
    expected.season_rating_inputs["2024"]["owners"] = ["u_alice", "u_bob"]
    assert live_ratings(entry, year=2024) == live_ratings(expected, year=2024)
    board = build_leaderboard(entry, year=2024, prev_ratings={})
    assert {r.user_id for r in board.rows} == {"u_alice", "u_bob"}
    assert [o.user_id for o in board.unverified_season_owners] == ["unknown"]
    if format != "redraft":
        assert {r.user_id: (r.roster_rank, r.roster_of) for r in board.rows} == {
            "u_alice": (1, 2), "u_bob": (2, 2)}


def test_season_evidence_resolves_aliases_and_rejects_empty_records():
    # Mutation: raw seasonal IDs fail matching, or a zero placeholder proves activity.
    from app.services.owner_membership import season_membership
    entry = _sample_entry()
    entry.resolved_trades = []
    entry.roster_to_user_by_league = {"L_prev": {1: "season-alias"}}
    entry.owner_aliases = {"season-alias": "u_alice"}
    entry.season_records = {"2024": {"u_bob": {"wins": 0, "losses": 0, "ties": 0}}}
    assert season_membership(entry, 2024) == {"u_alice": "active", "u_bob": "unverified"}
    entry.season_records["2024"]["u_bob"]["losses"] = 1
    assert season_membership(entry, 2024)["u_bob"] == "active"
