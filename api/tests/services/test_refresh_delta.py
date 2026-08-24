from app.services.chain_cache import ChainCacheEntry
from app.services.refresh_delta import new_transaction_ids, prior_transaction_ids


def _entry(tx_ids):
    return ChainCacheEntry(
        league_id="L", chain=[],
        resolved_trades=[{"trade": {"transaction_id": t}} for t in tx_ids],
        grades={}, owners={}, playoff_weeks_by_league={},
        roster_to_user_by_league={}, league_name_by_id={},
        league_season_by_id={}, cached_at="",
    )


def test_prior_ids_extracts_transaction_ids():
    assert prior_transaction_ids(_entry(["a", "b"])) == {"a", "b"}
    assert prior_transaction_ids(None) == set()


def test_new_ids_are_those_absent_in_prior():
    resolved = [{"trade": {"transaction_id": t}} for t in ["a", "b", "c"]]
    assert new_transaction_ids(resolved, _entry(["a", "b"])) == {"c"}


def test_no_new_when_all_present():
    resolved = [{"trade": {"transaction_id": t}} for t in ["a", "b"]]
    assert new_transaction_ids(resolved, _entry(["a", "b"])) == set()
