"""Composed provider-neutral fixtures; exercise persisted roster contract."""
from copy import deepcopy

import pytest

from app.services.chain_cache import ChainCacheEntry
from app.services.identity import owner_ref


def entry_for(format="redraft"):
    return ChainCacheEntry(
        league_id="new", chain=[
            {"league_id": "old", "season": 2023, "total_rosters": 2},
            {"league_id": "new", "season": 2024, "total_rosters": 2},
        ], resolved_trades=[], grades={},
        owners={u: {"owner_name": u} for u in ["returning", "former", "newcomer", "unknown"]},
        playoff_weeks_by_league={},
        roster_to_user_by_league={"old": {1: "returning", 2: "former"},
                                  "new": {1: "newcomer", 2: "returning"}},
        league_name_by_id={}, league_season_by_id={"old": 2023, "new": 2024},
        cached_at="2024-10-01T00:00:00Z", capabilities={"format": format},
    )


@pytest.mark.parametrize("format", ["redraft", "keeper", "dynasty"])
def test_membership_uses_latest_rosters_preserving_history(format):
    # Mutation: union all historical owners into current membership.
    entry = entry_for(format)
    before = deepcopy(entry)
    assert owner_ref(entry, "former").membership_status == "former"
    assert owner_ref(entry, "former").last_active_season == 2023
    assert owner_ref(entry, "returning").membership_status == "current"
    assert owner_ref(entry, "newcomer").membership_status == "current"
    assert owner_ref(entry, "unknown").membership_status == "unverified"
    assert entry == before


@pytest.mark.parametrize("rosters", [None, {}, {1: "newcomer"}, {1: "newcomer", 2: None},
                                     {1: "newcomer", 2: "newcomer"}])
def test_incomplete_snapshot_cannot_establish_former(rosters):
    # Mutation: absence in a partial roster means former.
    entry = entry_for()
    if rosters is None:
        del entry.roster_to_user_by_league["new"]
    else:
        entry.roster_to_user_by_league["new"] = rosters
    assert owner_ref(entry, "former").membership_status == "unverified"


def test_confirmed_alias_and_returning_owner_resolve_to_current():
    # Mutation: compare raw season IDs instead of canonical owners.
    entry = entry_for()
    entry.owner_aliases = {"provider-new": "returning", "provider-old": "former"}
    entry.roster_to_user_by_league["new"][2] = "provider-new"
    entry.roster_to_user_by_league["old"][2] = "provider-old"
    assert owner_ref(entry, "provider-new").membership_status == "current"
    assert owner_ref(entry, "provider-old").membership_status == "former"


def test_newest_season_without_assignments_does_not_fall_back():
    # Mutation: choose newest populated roster instead of newest league season.
    entry = entry_for()
    entry.chain.append({"league_id": "future", "season": 2025, "total_rosters": 2})
    entry.league_season_by_id["future"] = 2025
    assert owner_ref(entry, "former").membership_status == "unverified"


def test_placeholder_records_do_not_claim_last_played_or_departure():
    # Mutation: any record key, including a zero-game placeholder, means played.
    entry = entry_for()
    entry.season_records = {"2024": {"former": {"wins": 0, "losses": 0}, "unknown": {}}}
    assert owner_ref(entry, "former").last_active_season == 2023
    assert owner_ref(entry, "unknown").membership_status == "unverified"
    assert owner_ref(entry, "unknown").last_active_season is None


def test_current_highlights_do_not_promote_a_former_owner():
    # Mutation: current Top GM selects a departed owner from career ratings.
    from app.services.aggregations import _intel_hero_stats
    entry = entry_for()
    stats = _intel_hero_stats(entry, {"former": 1900, "returning": 1500})
    assert stats.top_gm.owner_user_id == "returning"


@pytest.mark.parametrize("format", ["redraft", "keeper", "dynasty"])
def test_history_remains_accessible_with_membership_on_every_reference(format):
    # Mutation: discard former owners from cache to fix the current list.
    from tests.test_aggregations import _sample_entry
    from app.services.aggregations import build_dashboard
    from app.services.owner_view import build_owner_detail
    from app.services.trade_view import build_trade_detail
    entry = _sample_entry()
    entry.capabilities = {"format": format}
    entry.owners["replacement"] = {"owner_name": "Replacement"}
    entry.roster_to_user_by_league["L_current"] = {1: "u_alice", 2: "replacement"}
    dashboard = build_dashboard(entry, "all", "ktc")
    departed = next(r for r in dashboard.standings if r.user_id == "u_bob")
    assert departed.owner.membership_status == "former"
    assert departed.trades == 2
    historical = build_dashboard(entry, 2024, "ktc")
    assert "u_bob" in {r.user_id for r in historical.standings}
    profile = build_owner_detail(entry, "u_bob")
    assert profile.owner.membership_status == "former"
    assert len(profile.trades) == 2
    trade = build_trade_detail(entry, "tx_2024")
    assert next(s for s in trade.sides if s.user_id == "u_bob").membership_status == "former"


@pytest.mark.parametrize("format", ["redraft", "keeper", "dynasty"])
def test_draft_history_keeps_former_drafters_and_status_on_picks_and_owners(format):
    # Mutation: filter historical draft rows to current owners, or omit status from picks.
    from app.services.draft_board_view import build_draft_board
    from tests.test_draft_board_view import _pick
    entry = entry_for(format)
    entry.drafted_picks = [_pick("p1", "former", 1, season=2023, production_total=100),
                           _pick("p2", "returning", 2, season=2023, production_total=50),
                           _pick("p3", "newcomer", 1, season=2024)]
    board = build_draft_board(entry, season=2023)
    assert {o.user_id for o in board.owners} == {"former", "returning"}
    assert board.picks[0].owner.membership_status == "former"
    former = next(o for o in board.owners if o.user_id == "former")
    assert former.owner.membership_status == "former"
    assert former.production_total == 100
