"""signal_ranks reaches the /gm response and the owner page.

PillarBreakdown is rebuilt through `PillarBreakdown(**pd)` in leaderboard.py,
and Pydantic DROPS an extra key — so a rank populated anywhere other than on
the model itself silently never arrives. That is the failure this file exists
to catch.
"""

from app.services.franchise_redesign import live_ratings
from tests.helpers import minimal_chain_cache_entry


def _entry_three_owners():
    return minimal_chain_cache_entry(
        owners={u: {"owner_name": u} for u in ("a", "b", "c")},
        season_records={"2024": {
            u: {"wins": 7, "losses": 6, "ties": 0, "rank": i + 1}
            for i, u in enumerate(("a", "b", "c"))}},
        outcome_signals={
            "a": {"expected_wins": 0.7, "playoff_success": 2.0, "luck": 0.1},
            "b": {"expected_wins": 0.5, "playoff_success": 1.0, "luck": 0.0},
            "c": {"expected_wins": 0.3, "playoff_success": 0.0, "luck": -0.1},
        },
        outlook_signals={
            "a": {"roster_value_share": 0.05, "young_core_share": 0.60,
                  "draft_capital": 100.0},
            "b": {"roster_value_share": 0.11, "young_core_share": 0.20,
                  "draft_capital": 300.0},
            "c": {"roster_value_share": 0.08, "young_core_share": 0.40,
                  "draft_capital": 200.0},
        },
    )


def test_signal_ranks_are_1_is_best_by_raw_descending():
    out = live_ratings(_entry_three_owners())
    assert out["b"]["pillars"]["assets"]["signal_ranks"]["roster_value_share"] == 1
    assert out["c"]["pillars"]["assets"]["signal_ranks"]["roster_value_share"] == 2
    assert out["a"]["pillars"]["assets"]["signal_ranks"]["roster_value_share"] == 3
    # And the ordering is per-signal, not one rank reused across the pillar.
    assert out["a"]["pillars"]["assets"]["signal_ranks"]["young_core_share"] == 1


def test_every_pillar_carries_ranks():
    out = live_ratings(_entry_three_owners())
    for row in out.values():
        for pillar in row["pillars"].values():
            assert set(pillar["signal_ranks"]) == set(pillar["signals"])


def test_ties_share_the_better_rank_and_skip_the_next():
    """A finishing order, not a dense one: two firsts are followed by a third."""
    entry = minimal_chain_cache_entry(
        owners={u: {"owner_name": u} for u in ("a", "b", "c")},
        season_records={"2024": {
            u: {"wins": 7, "losses": 6, "ties": 0, "rank": i + 1}
            for i, u in enumerate(("a", "b", "c"))}},
        outcome_signals={
            u: {"expected_wins": 0.5, "playoff_success": 1.0, "luck": 0.0}
            for u in ("a", "b", "c")},
        outlook_signals={
            "a": {"roster_value_share": 0.11, "young_core_share": 0.1,
                  "draft_capital": 1.0},
            "b": {"roster_value_share": 0.11, "young_core_share": 0.2,
                  "draft_capital": 2.0},
            "c": {"roster_value_share": 0.05, "young_core_share": 0.3,
                  "draft_capital": 3.0},
        },
    )
    out = live_ratings(entry)
    ranks = {
        u: out[u]["pillars"]["assets"]["signal_ranks"]["roster_value_share"]
        for u in ("a", "b", "c")
    }
    assert ranks == {"a": 1, "b": 1, "c": 3}


def test_signal_ranks_survive_the_pydantic_rebuild():
    """leaderboard.py does `PillarBreakdown(**pd)`; an extra key is dropped."""
    from app.services.leaderboard import build_leaderboard
    board = build_leaderboard(_entry_three_owners(), year="all", prev_ratings={})
    row = next(r for r in board.rows if r.user_id == "b")
    assert row.pillars["assets"].signal_ranks["roster_value_share"] == 1
