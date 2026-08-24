from __future__ import annotations

from app.services.chain_cache import ChainCacheEntry
from app.services.leaderboard import build_leaderboard

from ._grader_fixtures import dynasty_entry, redraft_entry  # noqa: F401 (fixtures)


def _rows(entry: ChainCacheEntry):
    return build_leaderboard(entry, year="all", prev_ratings={}).rows


def test_leaderboard_row_carries_the_roster_rank(dynasty_entry):
    rows = _rows(dynasty_entry)
    row = rows[0]
    assert row.roster_rank is not None
    assert row.roster_of == len(dynasty_entry.owners)


def test_redraft_leaves_leaderboard_roster_rank_absent(redraft_entry):
    # Absence, not a blank column - the same rule build_standings follows
    # (test_aggregations_roster_rank.py), and roster_ranks is populated on
    # this fixture too, so this proves the format gate hides it rather than
    # proving the data was never there.
    rows = _rows(redraft_entry)
    assert all(r.roster_rank is None for r in rows)
