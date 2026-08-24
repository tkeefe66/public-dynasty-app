from sleeper_dynasty.engine.capabilities import (
    LeagueCapabilities,
    capabilities_from_dict,
    capabilities_to_dict,
    derive_capabilities,
)
from sleeper_dynasty.models.league import League


def _league(fmt):
    return League(
        league_id="L1", name="Test", season=2025, total_rosters=12,
        roster_positions=["QB"], scoring_settings={}, playoff_week_start=15,
        num_playoff_teams=6, status="in_season", format=fmt,
    )


def test_dynasty_format_carries_roster_continuity():
    caps = derive_capabilities(
        _league("dynasty"), chain_length=3, observed_pick_assets=True)
    assert caps.format == "dynasty"
    assert caps.roster_continuity is True


def test_keeper_format_carries_roster_continuity():
    caps = derive_capabilities(
        _league("keeper"), chain_length=2, observed_pick_assets=True)
    assert caps.format == "keeper"
    assert caps.roster_continuity is True


def test_redraft_format_has_no_roster_continuity():
    caps = derive_capabilities(
        _league("redraft"), chain_length=1, observed_pick_assets=False)
    assert caps.format == "redraft"
    assert caps.roster_continuity is False


def test_missing_format_defaults_to_dynasty():
    """An adapter that omits format must not silently demote a league."""
    for bad in (None, ""):
        caps = derive_capabilities(
            _league(bad), chain_length=3, observed_pick_assets=True)
        assert caps.format == "dynasty"


def test_future_picks_is_evidence_based_not_format_based():
    """A dynasty league with pick trading off has no future_picks."""
    caps = derive_capabilities(
        _league("dynasty"), chain_length=3, observed_pick_assets=False)
    assert caps.format == "dynasty"
    assert caps.future_picks is False


def test_redraft_league_with_pick_trades_reports_future_picks():
    """Evidence beats the declared format in the other direction too."""
    caps = derive_capabilities(
        _league("redraft"), chain_length=1, observed_pick_assets=True)
    assert caps.format == "redraft"
    assert caps.future_picks is True


def test_multiyear_history_needs_chain_longer_than_one():
    new_dynasty = derive_capabilities(
        _league("dynasty"), chain_length=1, observed_pick_assets=True)
    assert new_dynasty.multiyear_history is False
    old_dynasty = derive_capabilities(
        _league("dynasty"), chain_length=2, observed_pick_assets=True)
    assert old_dynasty.multiyear_history is True


def test_dict_roundtrip():
    caps = derive_capabilities(
        _league("redraft"), chain_length=1, observed_pick_assets=False)
    assert capabilities_from_dict(capabilities_to_dict(caps)) == caps


def test_empty_dict_reads_as_full_dynasty():
    """Pre-feature cache entries must be unaffected."""
    caps = capabilities_from_dict({})
    assert caps == LeagueCapabilities(
        format="dynasty", future_picks=True,
        roster_continuity=True, multiyear_history=True,
    )
