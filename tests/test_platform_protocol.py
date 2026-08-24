import pytest

from sleeper_dynasty.api.platform import (
    LeaguePlatform, PLATFORM_SLEEPER, PLATFORM_YAHOO, platform_for_league_id,
)


def test_all_digit_ids_are_sleeper():
    assert platform_for_league_id("1048178156025733120") == PLATFORM_SLEEPER
    assert platform_for_league_id("123") == PLATFORM_SLEEPER


def test_yahoo_league_keys_are_yahoo():
    assert platform_for_league_id("461.l.123456") == PLATFORM_YAHOO
    assert platform_for_league_id("nfl.l.98765") == PLATFORM_YAHOO


def test_routing_is_case_insensitive_and_whitespace_tolerant():
    assert platform_for_league_id("  461.L.123456 ") == PLATFORM_YAHOO


def test_empty_id_is_rejected_loudly():
    """A silent default here would send a Yahoo league to the Sleeper client
    and fail deep inside an HTTP call with an unrelated message."""
    with pytest.raises(ValueError, match="empty league id"):
        platform_for_league_id("")


def test_unrecognized_shape_is_rejected_loudly():
    with pytest.raises(ValueError, match="unrecognized league id"):
        platform_for_league_id("not-a-league")


def test_sleeper_client_satisfies_the_protocol():
    from sleeper_dynasty.api.sleeper import SleeperClient
    assert isinstance(SleeperClient(), LeaguePlatform)


def test_protocol_names_every_read_the_grader_makes():
    """Guard: the protocol is the contract. If the grader learns to call
    something new on its client, it must be added here first."""
    required = {
        "walk_league_history", "get_rosters", "get_users", "get_players",
        "get_raw_matchups", "get_phase_map", "get_trade_transactions",
        "get_drop_transactions", "get_roster_transactions", "get_draft_results",
        "get_traded_picks", "get_nfl_state", "get_stats", "close",
    }
    assert required <= set(dir(LeaguePlatform))
