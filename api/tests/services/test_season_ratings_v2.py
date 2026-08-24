"""Task 6b: v2 has no year-scoped rating, so compute_season_ratings must stop
fabricating one, and its live consumer must degrade to its existing
"no signal"/"no stat" convention rather than reading a false zero.

(It had two consumers; `_backfill_yoy` died with the Strength x Trajectory
window model, so only `_rise_hero_stat` is left to pin.)
"""
from __future__ import annotations

import dataclasses

from app.services.aggregations import _rise_hero_stat
from app.services.leaderboard import compute_season_ratings

from ._grader_fixtures import dynasty_entry, redraft_entry  # noqa: F401


def test_season_ratings_is_empty_under_v2(dynasty_entry):
    # v2's signals are all-time and decay-weighted. A per-year loop over an
    # all-time tree returns the same number N times, which every downstream
    # consumer then reads as "this owner did not move" — a confident zero
    # where the truth is "no measurement exists". Give the chain two seasons
    # (dynasty_entry's own chain is empty, which would trivially loop zero
    # times either way) so this actually exercises the old per-season loop.
    entry = dataclasses.replace(
        dynasty_entry,
        chain=[
            {"league_id": "L", "season": 2024, "name": "Bros",
             "total_rosters": 2, "playoff_week_start": 15},
            {"league_id": "L", "season": 2025, "name": "Bros",
             "total_rosters": 2, "playoff_week_start": 15},
        ],
    )
    assert compute_season_ratings(entry) == {}


def test_riser_card_is_omitted_when_season_ratings_is_empty(dynasty_entry):
    # A "Biggest Riser" card showing every owner at 0 positions gained is
    # worse than no card. HeroStat(value="—", ...) is the existing "no
    # stat" convention this function already uses for its other empty
    # cases (see test_aggregations.py's card.value == "—" assertions), so
    # the all-time/off-season/year-riser modes — the three that read
    # season_ratings — must land there rather than emitting "▲0".
    assert dynasty_entry.season_ratings == {}
    card = _rise_hero_stat(
        dynasty_entry,
        current_ratings={"u1": 1600, "u2": 1400},
        year="all",
        is_in_season=False,
        prev_ratings={},
    )
    assert card.value == "—"
