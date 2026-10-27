from copy import deepcopy
from types import SimpleNamespace

import pytest
from app.services import current_rating_verification as verification


def inputs():
    league = SimpleNamespace(league_id="L", season=2026, total_rosters=2,
                             format="keeper", effective_format_verified=True,
                             format_evidence={})
    draft = {"draft_id": "D", "league_id": "L", "season": "2026",
             "status": "complete", "type": "snake",
             "settings": {"teams": 2, "rounds": 3, "player_type": 0}}
    # Shape matches Sleeper's public draft/picks payload; identifiers synthetic.
    picks = [{"pick_no": i, "round": (i - 1) // 2 + 1,
              "roster_id": (i - 1) % 2 + 1, "player_id": str(i),
              "is_keeper": i == 1, "metadata": {"position": "WR"}}
             for i in range(1, 7)]
    support = {"positions": {str(i): "WR" for i in range(1, 7)},
               "ktc_by_player_id": {str(i): SimpleNamespace(superflex_value=v)
                                    for i, v in enumerate([9999, 6000, 3000, 1000, 4000, 0], 1)},
               "pick_value_table": {(2027, 1): SimpleNamespace(superflex_value=1)},
               "pick_value_table_tiered": {(2027, 1, "early"): SimpleNamespace(superflex_value=99999)}}
    return league, draft, picks, support


def build(league, draft, picks, support):
    from app.services.full_player_pick_values import with_full_player_pick_values
    return with_full_player_pick_values(league, [draft], {"D": picks}, support,
                                       prices_as_of="2026-10-27")


def test_full_player_estimates_exclude_keepers_and_rookie_tiers():
    # Mutation: include keeper values, or retain rookie tier overrides.
    league, draft, picks, support = inputs()
    result = build(league, draft, picks, support)
    assert result["pick_value_table"][(2027, 1)].superflex_value == 6000
    assert result["pick_value_table"][(2029, 3)].superflex_value == 2000
    assert result["pick_value_table_tiered"] == {}
    assert support["pick_value_table"][(2027, 1)].superflex_value == 1
    receipt = result["full_player_pick_valuation"]
    assert receipt["status"] == "ready"
    assert receipt["keeper_count"] == 1
    assert len(receipt["rounds"]) == 3


def test_sleeper_null_keeper_flag_is_an_ordinary_selection():
    # Mutation: reject Sleeper's captured null (rather than false) flags.
    league, draft, picks, support = inputs()
    for p in picks[1:]:
        p["is_keeper"] = None
    result = build(league, draft, picks, support)
    assert result["full_player_pick_valuation"]["status"] == "ready"
    assert result["pick_value_table"][(2027, 1)].superflex_value == 6000


def test_round_noise_is_pooled_and_defense_prices_are_explicitly_excluded():
    # Mutation: skip adjacent pooling or count an excluded defense's price.
    league, draft, picks, support = inputs()
    support["ktc_by_player_id"]["3"].superflex_value = 1000
    support["ktc_by_player_id"]["5"].superflex_value = 6000
    support["ktc_by_player_id"]["6"].superflex_value = 99999
    support["positions"]["6"] = "DEF"
    result = build(league, draft, picks, support)
    assert result["pick_value_table"][(2027, 2)].superflex_value == 2000
    assert result["pick_value_table"][(2027, 3)].superflex_value == 2000
    assert result["full_player_pick_valuation"]["selections"][-1]["source"] == "excluded-position"


@pytest.mark.parametrize("damage", ["missing_price", "missing_pick", "duplicate_slot",
                                    "duplicate_player", "all_keepers", "wrong_year",
                                    "auction", "rookie", "unknown_position", "nonfinite"])
def test_unverified_full_drafts_never_fall_back_to_rookie_values(damage):
    # Mutation: a failed model leaves the old rookie table available for rating.
    league, draft, picks, support = inputs()
    if damage == "missing_price": del support["ktc_by_player_id"]["3"]
    if damage == "missing_pick": picks.pop()
    if damage == "duplicate_slot": picks[-1]["pick_no"] = 5
    if damage == "duplicate_player": picks[-1]["player_id"] = "5"
    if damage == "all_keepers": picks[1]["is_keeper"] = True
    if damage == "wrong_year": draft["season"] = "2025"
    if damage == "auction": draft["type"] = "auction"
    if damage == "rookie": draft["settings"]["player_type"] = 1
    if damage == "unknown_position": support["positions"].pop("3")
    if damage == "nonfinite": support["ktc_by_player_id"]["3"].superflex_value = float("nan")
    result = build(league, draft, picks, support)
    assert result["full_player_pick_valuation"]["status"] == "unavailable"
    assert result["pick_value_table"] == {}
    rosters = [SimpleNamespace(roster_id=i, owner_id=f"u{i}", players=[str(i)]) for i in (1, 2)]
    audit = verification.verify_current_assets(league, rosters, result,
                                               picks_verified=True, draft_rounds=3)
    assert audit["status"] == "unavailable"


def test_model_only_current_ratings_are_provisional_and_bound_to_assets():
    # Mutation: modeled assets are presented as ready or stale assets accepted.
    from app.services.full_player_pick_values import bind_pick_valuation
    from app.services.season_ratings import build_season_rating_inputs, rating_scope

    from ._grader_fixtures import _v2_entry
    league, draft, picks, support = inputs()
    support = build(league, draft, picks, support)
    rosters = [SimpleNamespace(roster_id=i, owner_id=f"u{i}", players=[str(i)]) for i in (1, 2)]
    e = _v2_entry(capabilities={"format": "keeper"})
    e.league_season_by_id = {"L": 2026}
    e.roster_to_user_by_league = {"L": {1: "u1", 2: "u2"}}
    e.current_rating_verification = verification.verify_current_assets(
        league, rosters, support, picks_verified=True, draft_rounds=3)
    bind_pick_valuation(e)
    e.season_rating_inputs = build_season_rating_inputs(e, {})
    for year in ("all", 2026):
        scope = rating_scope(e, year)
        assert scope["status"] == "provisional", scope
        assert "full-player" in scope["current_valuation_note"]
    original = deepcopy(e)
    e.outlook_signals["u1"]["draft_capital"] += 1
    assert rating_scope(e, "all")["status"] == "unavailable"
    e = original
    e.current_rating_verification["pick_valuation"]["rounds"][0]["value"] += 1
    assert rating_scope(e, 2026)["status"] == "unavailable"
