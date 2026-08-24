from datetime import datetime

from app.services.grader import observed_pick_assets
from sleeper_dynasty.engine.capabilities import capabilities_from_dict
from sleeper_dynasty.models.trade import (
    PickAsset, PlayerAsset, ResolvedTrade, Trade, TradeSide,
)


def _resolved(received):
    side = TradeSide(user_id="u1", received=received, given=[])
    trade = Trade(
        transaction_id="t1", league_id="L1", season=2025, week=3,
        traded_at=datetime(2025, 10, 1), sides={"u1": side},
    )
    return ResolvedTrade(trade=trade, sides={"u1": side})


def test_observed_pick_assets_true_when_a_pick_was_traded():
    rt = _resolved([PickAsset(season=2027, round=1, original_owner_user_id="u2")])
    assert observed_pick_assets([rt]) is True


def test_observed_pick_assets_false_for_player_only_trades():
    rt = _resolved([PlayerAsset(player_id="4034", name="Alvin Kamara")])
    assert observed_pick_assets([rt]) is False


def test_observed_pick_assets_false_for_no_trades():
    assert observed_pick_assets([]) is False


def test_observed_pick_assets_checks_given_side_too():
    """A pick only ever appears on the giving side in a 3-team leg."""
    side = TradeSide(
        user_id="u1", received=[],
        given=[PickAsset(season=2027, round=2, original_owner_user_id="u1")],
    )
    trade = Trade(
        transaction_id="t2", league_id="L1", season=2025, week=3,
        traded_at=datetime(2025, 10, 1), sides={"u1": side},
    )
    assert observed_pick_assets([ResolvedTrade(trade=trade, sides={"u1": side})]) is True


def test_entry_defaults_to_empty_capabilities():
    from tests.helpers import minimal_chain_cache_entry

    entry = minimal_chain_cache_entry(league_id="L1")
    assert entry.capabilities == {}


def test_empty_capabilities_reads_as_full_dynasty():
    from tests.helpers import minimal_chain_cache_entry

    entry = minimal_chain_cache_entry(league_id="L1")
    caps = capabilities_from_dict(entry.capabilities)
    assert caps.format == "dynasty"
    assert caps.future_picks is True
