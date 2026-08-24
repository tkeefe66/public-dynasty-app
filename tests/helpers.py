"""Shared local test helpers for the root tests/ suite."""
import json
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    """Load and JSON-decode a fixture file from tests/fixtures by name."""
    with open(FIXTURES / name) as f:
        return json.load(f)


def trade_player_asset(pid, name, via_pick=None):
    """Build a dict-form trade PlayerAsset for lineage/regrade tests."""
    return {"player_id": pid, "name": name, "via_pick": via_pick}


def trade_pick_asset(season, rnd, orig, drafted_id=None, drafted_name=None):
    """Build a dict-form trade PickAsset for lineage/regrade tests."""
    return {"season": season, "round": rnd, "original_owner_user_id": orig,
            "drafted_player_id": drafted_id, "drafted_player_name": drafted_name}


# The protocol methods SleeperClient derives purely from its own
# get_transactions — no HTTP client, no other state.
_DERIVED_FROM_GET_TRANSACTIONS = (
    "_all_week_transactions",
    "get_trade_transactions",
    "get_drop_transactions",
    "get_roster_transactions",
)


def wire_transaction_protocol(client):
    """Give a test double the trade/drop/add protocol methods.

    ``trade_history`` asks its client for trades and drops rather than raw
    per-week transactions. Test doubles still define the per-week
    ``get_transactions``, so rather than reimplement the filtering in every
    stub — where it would drift from the real thing — bind SleeperClient's own
    derivation onto the double. The stub supplies the fake data; the real
    Sleeper logic runs over it, which is exactly the pre-protocol behavior.

    Returns ``client`` for chaining.
    """
    from types import MethodType

    from sleeper_dynasty.api.sleeper import SleeperClient

    for name in _DERIVED_FROM_GET_TRANSACTIONS:
        setattr(client, name, MethodType(getattr(SleeperClient, name), client))
    return client
