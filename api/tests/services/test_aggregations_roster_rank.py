from __future__ import annotations

from app.services.aggregations import build_dashboard
from app.services.chain_cache import ChainCacheEntry

from ._grader_fixtures import dynasty_entry, redraft_entry  # noqa: F401 (fixtures)


def build_standings(entry: ChainCacheEntry):
    """Thin wrapper: roster rank rides the standings rows build_dashboard
    already assembles — there is no separate standings builder."""
    return build_dashboard(entry, year="all", lens="ktc").standings


def test_standing_rows_carry_the_roster_rank(dynasty_entry):
    rows = build_standings(dynasty_entry)
    row = rows[0]
    assert row.roster_rank is not None
    assert row.roster_of == len(dynasty_entry.owners)


def test_redraft_leaves_roster_rank_absent(redraft_entry):
    # Absence, not a blank column - the same rule the Outlook columns follow.
    rows = build_standings(redraft_entry)
    assert all(r.roster_rank is None for r in rows)
