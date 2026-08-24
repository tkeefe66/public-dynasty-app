from __future__ import annotations

from app.services.head_to_head_signals import compute_head_to_head


def _entry(opp_rid: int, tp: float, op: float) -> dict:
    return {"opponent_roster_id": opp_rid, "team_points": tp, "opponent_points": op}


def _supporting() -> dict:
    # Two chained leagues (seasons), same two owners by stable user_id.
    return {
        "matchups": {
            # 2024 (L1): a beats b 110-100
            ("L1", 1, 1): _entry(2, 110, 100),
            ("L1", 1, 2): _entry(1, 100, 110),
            # 2025 (L2): b beats a 95-90
            ("L2", 1, 1): _entry(2, 90, 95),
            ("L2", 1, 2): _entry(1, 95, 90),
        },
        "roster_to_user_by_league": {
            "L1": {1: "a", 2: "b"},
            "L2": {1: "a", 2: "b"},
        },
        "league_season_by_id": {"L1": 2024, "L2": 2025},
        "playoff_week_start_by_league": {"L1": 15, "L2": 15},
    }


def test_chain_wide_records_aggregate_by_owner():
    h2h = compute_head_to_head(_supporting())
    assert h2h["a"]["b"] == {
        "opponent_id": "b", "wins": 1, "losses": 1, "ties": 0,
        "points_for": 200.0, "points_against": 195.0,
    }
    assert h2h["b"]["a"] == {
        "opponent_id": "a", "wins": 1, "losses": 1, "ties": 0,
        "points_for": 195.0, "points_against": 200.0,
    }


def test_output_is_json_serializable_dicts():
    h2h = compute_head_to_head(_supporting())
    # Plain dicts (no dataclasses) so the ChainCache JSON write round-trips.
    assert isinstance(h2h["a"]["b"], dict)


def test_empty_supporting_yields_empty():
    assert compute_head_to_head({}) == {}
