from types import SimpleNamespace

from app.services.current_rating_verification import verify_current_assets
from app.services.franchise_redesign import live_ratings
from app.services.season_ratings import build_season_rating_inputs, rating_scope

from ._grader_fixtures import _v2_entry


def verified_assets():
    league = SimpleNamespace(
        league_id="L",
        season=2026,
        format="keeper",
        effective_format_verified=True,
        total_rosters=2,
        format_evidence={"future_picks_retained": False},
    )
    rosters = [
        SimpleNamespace(roster_id=1, owner_id="u1", players=["a"]),
        SimpleNamespace(roster_id=2, owner_id=None, players=["b"]),
    ]
    support = {
        "positions": {"a": "RB", "b": "WR"},
        "ktc_by_player_id": {
            p: SimpleNamespace(superflex_value=100) for p in ("a", "b")
        },
    }
    return league, rosters, support


def test_unassigned_roster_does_not_block_verified_owner_current_and_all():
    league, rosters, support = verified_assets()
    audit = verify_current_assets(league, rosters, support, picks_verified=True)
    assert audit["status"] == "ready"
    entry = _v2_entry(capabilities={"format": "keeper"})
    entry.league_season_by_id = {"L": 2026}
    entry.roster_to_user_by_league = {"L": {1: "u1"}}
    entry.current_rating_verification = audit
    entry.season_rating_inputs = build_season_rating_inputs(entry, {})
    from app.services.owner_membership import owner_membership
    entry.chain = [{"league_id": "L", "season": 2026, "total_rosters": 2}]
    assert owner_membership(entry, "u1")["membership_status"] == "current"
    assert owner_membership(entry, "u2")["membership_status"] == "unverified"
    assert set(live_ratings(entry)) == {"u1"}
    for year in ("all", 2026):
        scope = rating_scope(entry, year)
        assert scope["status"] == "provisional"
        assert scope["verified_owner_count"] == 1
        assert scope["excluded_rosters"] == [
            {"roster_id": 2, "reason": "Current owner is unassigned."}
        ]
    from app.services.owner_view import build_owner_detail

    detail = build_owner_detail(entry, "u2")
    assert detail.rating_scope.status == "unavailable"
    assert detail.roster_rank is None
    # Previously excluded roster gains an owner: receipt must be refreshed.
    entry.roster_to_user_by_league["L"][2] = "u2"
    assert live_ratings(entry) == {}
    assert rating_scope(entry, 2026)["status"] == "unavailable"


def test_unassigned_roster_still_requires_prices_for_shared_asset_denominator():
    league, rosters, support = verified_assets()
    del support["ktc_by_player_id"]["b"]
    result = verify_current_assets(league, rosters, support, picks_verified=True)
    assert result["status"] == "unavailable"
    assert result["missing_price_player_ids"] == ["b"]


def test_partial_ownership_does_not_bypass_unpriced_future_picks():
    league, rosters, support = verified_assets()
    league.format_evidence = {}
    result = verify_current_assets(
        league, rosters, support, picks_verified=True, draft_rounds=17
    )
    assert result["status"] == "unavailable"
    assert "pick prices" in result["reason"]
    assert result["owner_coverage"]["excluded_rosters"][0]["roster_id"] == 2


def test_unassigned_team_keeps_its_asset_share_and_traded_pick_value():
    from app.services.rating_signals import compute_rating_signals

    from sleeper_dynasty.models.league import DraftPick

    def value(v):
        return SimpleNamespace(superflex_value=v)

    support = {
        "owners": {"u1": {}, "u2": {}},
        "league_season_by_id": {"L": 2026},
        "roster_to_user_by_league": {"L": {1: "u1", 2: "u2"}},
        "current_roster_players": {1: ["a"], 2: ["b"], 3: ["c"]},
        "ktc_by_player_id": {"a": value(300), "b": value(200), "c": value(100)},
        "pick_value_table": {(2027, 1): value(20)},
        "pick_value_table_tiered": {
            (2027, 1, "early"): value(30),
            (2027, 1, "mid"): value(20),
            (2027, 1, "late"): value(10),
        },
    }
    _, assets, _, _ = compute_rating_signals(
        support,
        {"a": "u1", "b": "u2", "c": None},
        traded_picks=[
            DraftPick(season=2027, round=1, original_owner_id=3, current_owner_id=1)
        ],
        num_draft_rounds=1,
    )
    assert assets["u1"]["roster_value_share"] == 0.5
    assert (
        assets["u1"]["draft_capital"] == 40
    )  # own late pick + vacant team's early pick
