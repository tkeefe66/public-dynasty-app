"""The owner hero's roster rank obeys the same redraft gate as the other three.

aggregations.py (standings) and leaderboard.py both drop `entry.roster_ranks`
for a redraft league; owner_view did not, so a redraft hero read
"ROSTER #4 OF 12" while the standings table two clicks away deliberately hid
the same figure.
"""
from __future__ import annotations

from app.services.owner_view import build_owner_detail

from ._grader_fixtures import dynasty_entry, redraft_entry  # noqa: F401 (fixtures)


def test_owner_hero_carries_the_roster_rank_in_a_dynasty_league(dynasty_entry):
    detail = build_owner_detail(dynasty_entry, "u1")
    assert detail.roster_rank is not None
    assert detail.roster_rank.rank == 1


def test_redraft_leaves_the_owner_hero_roster_rank_absent(redraft_entry):
    # roster_ranks is populated on this fixture, so this proves the format
    # gate hides it rather than proving the data was never there.
    assert redraft_entry.roster_ranks["u1"]["rank"] == 1
    detail = build_owner_detail(redraft_entry, "u1")
    assert detail.roster_rank is None
