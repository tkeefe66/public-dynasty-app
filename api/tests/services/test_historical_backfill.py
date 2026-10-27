from copy import deepcopy
from datetime import date

import httpx
import pytest


def inputs():
    players = {
        f"p{i}": {
            "birth_date": "2000-01-01",
            "position": "RB",
            "fantasy_positions": ["RB"],
        }
        for i in range(50)
    }
    holders = {pid: "a" if i < 25 else "b" for i, pid in enumerate(players)}
    board = {
        "format": "non_sf_dynasty",
        "tep": "std",
        "asOf": "2025-12-30",
        "offset": 0,
        "total": 49,
        "rankings": [
            {"id": f"p{i}", "position": "RB", "value": 100 + i} for i in range(49)
        ],
    }
    return players, holders, board


def test_explicit_unranked_floor_and_kicker_defense_exclusion():
    # Mutation: turn every missing asset into a zero-valued human player.
    from app.services.historical_backfill import value_roster

    players, holders, board = inputs()
    players.update(k={"position": "K"}, defense={"position": "DEF"})
    holders.update(k="a", defense="b")
    rows, policy = value_roster(
        players, holders, board, date(2025, 12, 31), "non_sf_dynasty"
    )
    assert len(rows) == 50
    assert (
        next(p for p in rows if p["player_id"] == "p49")["pricing"] == "unranked_floor"
    )
    assert next(p for p in rows if p["player_id"] == "p49")["value"] == 0
    assert {p["player_id"] for p in policy["excluded"]} == {"k", "defense"}
    assert policy["unranked_upper_bounds"] == {"p49": 100}


@pytest.mark.parametrize(
    "mutation",
    [
        "truncated",
        "future",
        "stale",
        "wrong_format",
        "duplicates",
        "negative",
        "nan",
        "coverage",
    ],
)
def test_invalid_board_blocks_instead_of_becoming_replacement_values(mutation):
    # Mutation: accept bad/partial provider replies as complete price evidence.
    from app.services.historical_backfill import value_roster

    players, holders, board = inputs()
    if mutation == "truncated":
        board["total"] += 1
    if mutation == "future":
        board["asOf"] = "2025-12-31"
    if mutation == "stale":
        board["asOf"] = "2025-12-01"
    if mutation == "wrong_format":
        board["format"] = "sf_dynasty"
    if mutation == "duplicates":
        board["rankings"][-1] = deepcopy(board["rankings"][0])
    if mutation == "negative":
        board["rankings"][0]["value"] = -1
    if mutation == "nan":
        board["rankings"][0]["value"] = float("nan")
    if mutation == "coverage":
        board["rankings"].pop()
        board["total"] -= 1
    with pytest.raises(ValueError):
        value_roster(players, holders, board, date(2025, 12, 31), "non_sf_dynasty")


def test_dual_position_player_uses_offensive_eligibility_and_birthdate():
    # Mutation: use today's primary DB position or current age for a WR/DB player.
    from app.services.historical_backfill import value_roster

    players, holders, board = inputs()
    players["p0"].update(position="DB", fantasy_positions=["WR", "DB"], age=99)
    board["rankings"][0]["position"] = "WR"
    rows, _ = value_roster(
        players, holders, board, date(2025, 12, 31), "non_sf_dynasty"
    )
    assert rows[0]["position"] == "WR"
    assert rows[0]["birth_date"] == "2000-01-01"


def test_idp_exclusion_requires_versioned_opt_in_and_preserves_offensive_eligibility():
    from app.services.historical_backfill import value_roster

    players, holders, board = inputs()
    players.update(defender={"position": "LB"})
    holders["defender"] = "a"
    with pytest.raises(ValueError, match="unsupported position"):
        value_roster(players, holders, board, date(2025, 12, 31), "non_sf_dynasty")
    rows, policy = value_roster(
        players, holders, board, date(2025, 12, 31), "non_sf_dynasty", exclude_idp=True
    )
    assert policy["version"] == "stats-guy-offense-v2"
    assert policy["excluded"] == [
        {"player_id": "defender", "owner_id": "a", "position": "LB"}
    ]
    assert len(rows) == 50 and policy["eligible"] == 50
    players["defender"]["position"] = "UNKNOWN"
    with pytest.raises(ValueError, match="unsupported position"):
        value_roster(
            players,
            holders,
            board,
            date(2025, 12, 31),
            "non_sf_dynasty",
            exclude_idp=True,
        )


def test_roster_reversal_includes_post_cutoff_drop_but_not_before():
    # Mutation: trust current old-league rosters or reverse all transactions.
    from app.services.historical_backfill import reconcile_rosters

    current = [{"roster_id": 1, "players": ["a"]}, {"roster_id": 2, "players": ["c"]}]
    final = [
        {"roster_id": 1, "players": ["a", "b"]},
        {"roster_id": 2, "players": ["c"]},
    ]
    tx = [
        {
            "status": "complete",
            "transaction_id": "before",
            "status_updated": 100,
            "drops": {"z": 1},
        },
        {
            "status": "complete",
            "transaction_id": "after",
            "status_updated": 300,
            "drops": {"b": 1},
        },
    ]
    assert reconcile_rosters(current, final, tx, 200) == {"a": 1, "b": 1, "c": 2}
    with pytest.raises(ValueError, match="reconcile"):
        reconcile_rosters(current, final, tx[:1], 200)


def test_pick_replay_requires_previous_owner_and_cutoff():
    # Mutation: drop the previous-owner check or include later trades.
    from app.services.historical_backfill import reconstruct_picks

    move = {
        "season": "2026",
        "round": 1,
        "roster_id": 1,
        "previous_owner_id": 1,
        "owner_id": 2,
    }
    tx = [
        {
            "status": "complete",
            "transaction_id": "t",
            "status_updated": 100,
            "draft_picks": [move],
        }
    ]
    result = reconstruct_picks([1, 2], 2025, 1, tx, 200)
    assert result[(2026, 1, 1)] == 2 and len(result) == 6
    assert reconstruct_picks([1, 2], 2025, 1, tx, 50)[(2026, 1, 1)] == 1
    tx[0]["draft_picks"][0]["previous_owner_id"] = 2
    with pytest.raises(ValueError, match="previous owner"):
        reconstruct_picks([1, 2], 2025, 1, tx, 200)


def test_exact_cutoff_drop_resolution_requires_latest_completed_movement():
    from app.services.historical_backfill import reconcile_rosters

    current = [{"roster_id": 1, "players": ["a"]}, {"roster_id": 2, "players": ["b"]}]
    final = [
        {"roster_id": 1, "players": ["a", "DEF"]},
        {"roster_id": 2, "players": ["b"]},
    ]
    tx = [
        {
            "transaction_id": "drop",
            "status": "complete",
            "status_updated": 100,
            "drops": {"DEF": 1},
            "adds": None,
        }
    ]
    resolution = {"player_id": "DEF", "roster_id": 1, "transaction_id": "drop"}
    with pytest.raises(ValueError, match="do not reconcile"):
        reconcile_rosters(current, final, tx, 200)
    assert reconcile_rosters(
        current, final, tx, 200, verified_pre_cutoff_drops=[resolution]
    ) == {"a": 1, "b": 2}
    for bad in (
        {**resolution, "roster_id": 2},
        {**resolution, "transaction_id": "other"},
    ):
        with pytest.raises(ValueError, match="drop evidence"):
            reconcile_rosters(current, final, tx, 200, verified_pre_cutoff_drops=[bad])
    later = {
        "transaction_id": "later",
        "status": "complete",
        "status_updated": 150,
        "adds": {"DEF": 2},
    }
    with pytest.raises(ValueError, match="drop evidence"):
        reconcile_rosters(
            current, final, tx + [later], 200, verified_pre_cutoff_drops=[resolution]
        )
    with pytest.raises(ValueError, match="drop evidence"):
        reconcile_rosters(
            current,
            final,
            tx + [{**later, "status_updated": 100}],
            200,
            verified_pre_cutoff_drops=[resolution],
        )
    with pytest.raises(ValueError, match="drop evidence"):
        reconcile_rosters(
            current, final, tx, 50, verified_pre_cutoff_drops=[resolution]
        )


def test_receipts_replay_offline_and_detect_corruption(tmp_path):
    # Mutation: refetch cached requests or trust altered evidence bytes.
    from app.services.historical_backfill import EvidenceClient

    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"answer": 3})
    )
    with httpx.Client(transport=transport) as http:
        client = EvidenceClient(tmp_path, http=http)
        assert client.get("https://api.sleeper.app/v1/example") == {"answer": 3}
    offline = EvidenceClient(tmp_path, offline=True)
    assert offline.get("https://api.sleeper.app/v1/example") == {"answer": 3}
    receipt = next(tmp_path.glob("*.json"))
    receipt.write_text(receipt.read_text().replace('"answer": 3', '"answer": 4'))
    with pytest.raises(ValueError, match="hash"):
        offline.get("https://api.sleeper.app/v1/example")


def test_rate_limit_is_explicit_and_never_cached_as_data(tmp_path):
    # Mutation: store a 429 response as a successful empty historical board.
    from app.services.historical_backfill import EvidenceClient

    with (
        httpx.Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(429, headers={"Retry-After": "60"})
            )
        ) as http,
        pytest.raises(ValueError, match="60"),
    ):
        EvidenceClient(tmp_path, http=http).get("https://api.sleeper.app/v1/example")
    assert not list(tmp_path.glob("*.json"))
