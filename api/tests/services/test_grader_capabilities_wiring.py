"""The grader wiring seam for league capabilities.

Everything else in this feature is covered in isolation — derive_capabilities,
observed_pick_assets, the cache default, model selection off a hand-built
entry, pull_supporting_data's value precedence. Nothing ran GraderService.run
itself, which is where the pieces are joined:

  * grader.run stamps `entry.capabilities` inside a bare `except Exception`.
    A regression there is swallowed into a log line, and the league is then
    silently graded under the dynasty weight tree with the Outlook tab back.
  * grader.run picks the snapshot namespace from the chain's format. Nothing
    asserted that a redraft chain stays out of the dynasty table.

These two tests are the only place a real `run` is checked against a
`redraft` chain, plus the dynasty mirror so the gate can't be widened
into "everything is redraft".
"""
from __future__ import annotations

import pytest

from app.services.grader import GraderService
from ._grader_fixtures import _run_with_one_trade

_OFFSEASON = {"season_type": "off", "week": 0}


@pytest.mark.asyncio
async def test_run_stamps_redraft_capabilities_and_skips_the_ktc_snapshot(tmp_path):
    captured: dict = {}
    entry = await _run_with_one_trade(
        GraderService(), cache_dir=tmp_path, nfl_state=_OFFSEASON,
        league_format="redraft", captured=captured,
    )

    assert entry.capabilities["format"] == "redraft"
    # Redraft has no roster carryover; the one-season chain has no history.
    assert entry.capabilities["roster_continuity"] is False
    assert entry.capabilities["multiyear_history"] is False

    # Superseded contract: this used to assert the store was None, because a
    # redraft chain was denied one outright. It now gets a redraft-namespaced
    # store so its price history accrues forward. What must still hold — and is
    # what the None-assertion was really protecting — is that it is NOT the
    # dynasty namespace.
    store = captured["snapshot_store"]
    assert store is not None, "a redraft chain must accrue its own price history"
    assert store.source == "redraft"
    assert "snapshots-redraft" in str(store.dir)
    assert store.dir.name != "snapshots", "must never be the dynasty namespace"


@pytest.mark.asyncio
async def test_run_stamps_dynasty_capabilities_and_keeps_the_ktc_snapshot(tmp_path):
    """The mirror. A dynasty league must be completely unaffected by the
    redraft gate — this is the assertion that catches a gate widened the wrong
    way (e.g. an inverted check, or a fallback that reads as redraft)."""
    captured: dict = {}
    entry = await _run_with_one_trade(
        GraderService(), cache_dir=tmp_path, nfl_state=_OFFSEASON,
        league_format="dynasty", captured=captured,
    )

    assert entry.capabilities["format"] == "dynasty"
    assert entry.capabilities["roster_continuity"] is True
    assert captured["snapshot_store"] is not None


@pytest.mark.asyncio
async def test_run_stamps_keeper_capabilities_and_keeps_the_ktc_snapshot(tmp_path):
    """Keeper is not redraft: it keeps roster continuity, the dynasty weight
    tree (a keeper_led tree is deferred), and KTC pricing."""
    captured: dict = {}
    entry = await _run_with_one_trade(
        GraderService(), cache_dir=tmp_path, nfl_state=_OFFSEASON,
        league_format="keeper", captured=captured,
    )

    assert entry.capabilities["format"] == "keeper"
    assert entry.capabilities["roster_continuity"] is True
    assert captured["snapshot_store"] is not None
