"""Reviewed reconstruction must not turn arbitrary unpriced picks into keepers."""

from copy import deepcopy

import pytest

from .test_historical_full_player_picks import evidence


def proof():
    args = evidence()
    draft = args["draft"]
    draft.update(league_id="L", start_time=10000, last_picked=20000)
    picks = args["picks"]
    for pick in picks:
        pick["draft_id"] = draft["draft_id"]
    # The first selection was a placeholder, not an actual priced acquisition.
    picks[0].update(player_id="placeholder", is_keeper=None, roster_id=1)
    for p in picks[1:]:
        p.setdefault("roster_id", 2)
    row = {
        "league": {"league_id": "L", "season": "2025", "previous_league_id": "P"},
        "previous_league": {
            "league_id": "P",
            "season": "2024",
            "settings": {"last_scored_leg": 17},
        },
        "draft": deepcopy(draft),
        "picks": deepcopy(picks),
        "rosters": [
            {"roster_id": 1, "owner_id": "a"},
            {"roster_id": 2, "owner_id": "b"},
        ],
        "previous_rosters": [
            {"roster_id": 9, "owner_id": "a"},
            {"roster_id": 8, "owner_id": "b"},
        ],
        "previous_final_week": 17,
        "previous_final": [
            {"roster_id": 9, "players": ["keeper"]},
            {"roster_id": 8, "players": []},
        ],
        "opening": [
            {"roster_id": 1, "players": ["keeper"]},
            {"roster_id": 2, "players": []},
        ],
        "previous_draft": {
            "league_id": "P",
            "season": "2024",
            "draft_id": "PD",
            "status": "complete",
        },
        "previous_picks": [{"player_id": "keeper", "round": 2, "draft_id": "PD"}],
        "transactions": [
            {
                "transaction_id": "drop",
                "status": "complete",
                "status_updated": 21000,
                "type": "free_agent",
                "drops": {"placeholder": 1},
                "adds": None,
            }
        ],
        "mappings": [
            {"placeholder": "placeholder", "keeper": "keeper", "roster_id": 1}
        ],
    }
    args["reconstruction"] = {
        "version": 1,
        "reviewed_by": "test-review",
        "basis": "Public roster and transaction evidence",
        "cost_rule": "prior-round-minus-one-floor-one",
        "seasons": [row],
    }
    return args


def test_reconstruction_prices_only_real_selections_preserves_raw_and_replays():
    from app.services.historical_full_player_picks import estimate, validate

    args = proof()
    original = deepcopy(args)
    result = estimate(**args)
    assert args == original
    assert result["picks"][0]["is_keeper"] is None
    assert result["estimate"]["keeper_count"] == 1
    assert result["estimate"]["rounds"][0]["value"] == 6000
    assert result["reconstruction"] == args["reconstruction"]
    validate(result)


@pytest.mark.parametrize(
    "damage",
    [
        "owner",
        "acquired",
        "drafted",
        "round",
        "late",
        "missing_mapping",
        "wrong_season",
        "wrong_picks",
        "reused",
        "prior_roster",
        "added_in_exchange",
    ],
)
def test_reconstruction_rejects_unsupported_exclusions(damage):
    from app.services.historical_full_player_picks import estimate

    args = proof()
    row = args["reconstruction"]["seasons"][0]
    if damage == "owner":
        row["previous_rosters"][0]["owner_id"] = "someone-else"
    if damage == "acquired":
        row["transactions"].append(
            {
                "transaction_id": "add",
                "status": "complete",
                "status_updated": 19000,
                "adds": {"keeper": 1},
            }
        )
    if damage == "drafted":
        row["picks"][1]["player_id"] = "keeper"
        args["picks"] = deepcopy(row["picks"])
    if damage == "round":
        row["previous_picks"][0]["round"] = 3
    if damage == "late":
        row["transactions"][0]["status_updated"] = 99999999
    if damage == "missing_mapping":
        row["mappings"] = []
    if damage == "wrong_season":
        row["league"]["season"] = "2024"
    if damage == "wrong_picks":
        row["picks"][0]["player_id"] = "different"
    if damage == "reused":
        row["mappings"] *= 2
    if damage == "prior_roster":
        row["previous_final"][0]["players"] = []
    if damage == "added_in_exchange":
        row["transactions"][0]["adds"] = {"replacement": 1}
    with pytest.raises(ValueError, match="[Rr]econstruction"):
        estimate(**args)


def test_prior_reconstruction_carries_cost_without_rewriting_previous_draft():
    from app.services.historical_full_player_picks import estimate, validate

    args = proof()
    first = args["reconstruction"]["seasons"][0]
    first["previous_picks"][0]["round"] = 3
    # First season keeper occupies round 2; next season cost becomes round 1.
    first["picks"][0]["round"] = 2
    first["league"].update(league_id="P", season="2024", previous_league_id="PP")
    first["previous_league"].update(league_id="PP", season="2023")
    first["previous_draft"].update(league_id="PP", season="2023")
    first["draft"].update(league_id="P", season="2024")
    second = deepcopy(first)
    second["league"].update(league_id="L", season="2025", previous_league_id="P")
    second["previous_league"].update(league_id="P", season="2024")
    second["draft"] = deepcopy(args["draft"])
    second["picks"] = deepcopy(args["picks"])
    second["previous_picks"] = deepcopy(first["picks"])
    second["previous_draft"] = deepcopy(first["draft"])
    args["reconstruction"]["seasons"].append(second)
    result = estimate(**args)
    validate(result)
    assert result["estimate"]["keeper_count"] == 1
    second["previous_picks"][1]["round"] = 99
    with pytest.raises(ValueError, match="Adjacent reconstruction"):
        estimate(**args)
    second["previous_picks"] = deepcopy(first["picks"])
    args["reconstruction"]["seasons"].pop(0)
    with pytest.raises(ValueError, match="prior draft evidence"):
        estimate(**args)


def test_altered_evidence_cannot_replay_even_when_estimated_prices_unchanged():
    from app.services.historical_full_player_picks import estimate, validate

    result = estimate(**proof())
    result["reconstruction"]["seasons"][0]["previous_final"][0]["players"] = []
    with pytest.raises(ValueError, match="replay failed"):
        validate(result)


def test_previous_pick_cost_must_belong_to_the_previous_league_draft():
    from app.services.historical_full_player_picks import estimate

    args = proof()
    args["reconstruction"]["seasons"][0]["previous_picks"][0]["draft_id"] = "unrelated"
    with pytest.raises(ValueError, match="Previous draft"):
        estimate(**args)


@pytest.mark.parametrize(
    "damage", ["wrong_week", "trade_drop", "pick_trade", "budget_trade"]
)
def test_reconstruction_rejects_nonfinal_rosters_and_trade_drops(damage):
    from app.services.historical_full_player_picks import estimate

    args = proof()
    row = args["reconstruction"]["seasons"][0]
    tx = row["transactions"][0]
    if damage == "wrong_week":
        row["previous_final_week"] = 1
    elif damage == "trade_drop":
        tx["type"] = "trade"
    elif damage == "pick_trade":
        tx["draft_picks"] = [{"round": 1}]
    else:
        tx["waiver_budget"] = [{"amount": 1}]
    with pytest.raises(ValueError, match="Reconstruction"):
        estimate(**args)
