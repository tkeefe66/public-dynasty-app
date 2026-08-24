"""The grader-stamps-it leg of the `bracket_watch` quartet.

The other three (round-trip, pre-feature default, surface fallback) are in
api/tests/test_bracket_watch_api.py. This one drives a real GraderService.run
so the wiring itself is covered — the stamp sits inside a bare
`except Exception`, where a regression would otherwise be swallowed into a log
line and the postseason lead would silently keep its placeholder all January.
"""
from __future__ import annotations

import pytest

from app.services.grader import GraderService

from ._grader_fixtures import _run_with_one_trade

# season_type "regular" with week >= the league's playoff start is what
# derive_league_phase calls "post" — the fantasy postseason runs inside the
# NFL regular season.
_POSTSEASON = {"season_type": "regular", "week": 16, "season": 2024}
_REGULAR = {"season_type": "regular", "week": 3, "season": 2024}
_OFFSEASON = {"season_type": "off", "week": 0}

# Roster 1 beat roster 2 in a title-path game; nothing else has been played.
_BRACKET = {
    "winners_bracket_by_league": {
        "L": [{"m": 1, "r": 1, "t1": 1, "t2": 2, "w": 1, "l": 2}],
    },
}


@pytest.mark.asyncio
async def test_run_stamps_bracket_watch_during_the_postseason(tmp_path):
    entry = await _run_with_one_trade(
        GraderService(), cache_dir=tmp_path, nfl_state=_POSTSEASON,
        supporting_extra=_BRACKET,
    )
    assert entry.bracket_watch, "postseason refresh must stamp the bracket watch"
    assert entry.bracket_watch["season"] == 2024
    assert entry.bracket_watch["entered"] == 2
    assert entry.bracket_watch["alive"] == ["u1"]
    assert entry.bracket_watch["eliminated"] == ["u2"]


@pytest.mark.asyncio
async def test_no_bracket_watch_outside_the_postseason(tmp_path):
    """The lead is the only consumer, so computing it year-round would put a
    bracket walk on every refresh for a block nothing renders."""
    for state in (_REGULAR, _OFFSEASON):
        entry = await _run_with_one_trade(
            GraderService(), cache_dir=tmp_path, nfl_state=state,
            supporting_extra=_BRACKET,
        )
        assert entry.bracket_watch == {}


@pytest.mark.asyncio
async def test_a_postseason_with_no_bracket_data_stamps_nothing(tmp_path):
    """A league whose bracket hasn't been published yet must not fail the
    refresh — the stage is best-effort and the lead falls back."""
    entry = await _run_with_one_trade(
        GraderService(), cache_dir=tmp_path, nfl_state=_POSTSEASON,
    )
    assert entry.bracket_watch == {}
