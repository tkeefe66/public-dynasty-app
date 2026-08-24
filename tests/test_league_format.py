from sleeper_dynasty.api.sleeper import format_for_type
from sleeper_dynasty.engine.capabilities import derive_capabilities
from sleeper_dynasty.models.league import League


def _league(fmt="dynasty"):
    return League(
        league_id="L1", name="Test", season=2025, total_rosters=12,
        roster_positions=["QB"], scoring_settings={}, playoff_week_start=15,
        num_playoff_teams=6, status="in_season", format=fmt,
    )


def test_league_defaults_to_dynasty_format():
    """An adapter that forgets to set format must not demote a league."""
    lg = League(
        league_id="L1", name="Test", season=2025, total_rosters=12,
        roster_positions=["QB"], scoring_settings={}, playoff_week_start=15,
        num_playoff_teams=6, status="in_season",
    )
    assert lg.format == "dynasty"


def test_league_has_no_platform_specific_type_field():
    """The Sleeper settings.type int must not live on the neutral model."""
    assert not hasattr(_league(), "league_type")


def test_capabilities_read_format_off_the_league():
    for fmt in ("dynasty", "keeper", "redraft"):
        assert derive_capabilities(
            _league(fmt), chain_length=1, observed_pick_assets=False
        ).format == fmt


def test_capabilities_need_no_platform_knowledge():
    """Any object with a .format string must work — that is the portability
    contract. A Yahoo league is described by the same call."""

    class NotASleeperLeague:
        format = "keeper"

    caps = derive_capabilities(
        NotASleeperLeague(), chain_length=2, observed_pick_assets=False)
    assert caps.format == "keeper"
    assert caps.roster_continuity is True
    assert caps.multiyear_history is True


def test_sleeper_owns_the_type_mapping():
    assert format_for_type(0) == "redraft"
    assert format_for_type(1) == "keeper"
    assert format_for_type(2) == "dynasty"


def test_unknown_sleeper_type_defaults_to_dynasty():
    for bad in (None, 7, -1):
        assert format_for_type(bad) == "dynasty"


def test_capabilities_module_no_longer_exports_format_for_type():
    """The mapping is a Sleeper detail; leaving a copy in the engine invites
    drift the moment a second platform exists."""
    import sleeper_dynasty.engine.capabilities as caps
    assert not hasattr(caps, "format_for_type")
