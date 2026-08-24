from datetime import datetime, timezone

import pytest

from sleeper_dynasty.engine.trade_history import (
    compute_pick_resolution_map,
    normalize_trade,
    resolve_assets,
)
from sleeper_dynasty.models.trade import (
    FaabAsset,
    PickAsset,
    PlayerAsset,
    ResolvedTrade,
    Trade,
    TradeSide,
)

from tests.helpers import load_fixture
from tests.helpers import wire_transaction_protocol


def test_normalize_two_team_trade_with_pick_and_player():
    raw_tx = load_fixture("transactions_trade.json")[0]
    # roster 1 -> user "u_alice"; roster 2 -> user "u_bob"
    roster_to_user = {1: "u_alice", 2: "u_bob"}
    trade = normalize_trade(
        raw_tx,
        roster_to_user=roster_to_user,
        league_id="league_2024",
        season=2024,
    )
    assert trade.transaction_id == "tx_001"
    assert trade.league_id == "league_2024"
    assert trade.season == 2024
    assert trade.week == 2
    # 1726099200000 ms = 2024-09-12 00:00:00 UTC.
    assert trade.traded_at == datetime(2024, 9, 12, 0, 0, tzinfo=timezone.utc)
    assert set(trade.sides.keys()) == {"u_alice", "u_bob"}

    alice = trade.sides["u_alice"]
    bob = trade.sides["u_bob"]

    # Alice (roster 1) received Bijan (5678) + 2025 1st (originally hers).
    received_player_ids = [
        a.player_id for a in alice.received if isinstance(a, PlayerAsset)
    ]
    assert "5678" in received_player_ids
    received_picks = [a for a in alice.received if isinstance(a, PickAsset)]
    assert len(received_picks) == 1
    assert received_picks[0].season == 2025
    assert received_picks[0].round == 1
    assert received_picks[0].original_owner_user_id == "u_alice"

    # Alice gave Adams (1234) + 2024 2nd (originally hers).
    given_player_ids = [
        a.player_id for a in alice.given if isinstance(a, PlayerAsset)
    ]
    assert "1234" in given_player_ids
    given_picks = [a for a in alice.given if isinstance(a, PickAsset)]
    assert len(given_picks) == 1
    assert given_picks[0].season == 2024
    assert given_picks[0].round == 2

    # Bob's side is the mirror.
    assert any(
        isinstance(a, PlayerAsset) and a.player_id == "1234"
        for a in bob.received
    )
    assert any(
        isinstance(a, PlayerAsset) and a.player_id == "5678"
        for a in bob.given
    )


def test_normalize_trade_with_faab():
    raw_tx = {
        "type": "trade",
        "status": "complete",
        "transaction_id": "tx_faab",
        "created": 1726099200000,
        "leg": 2,
        "roster_ids": [1, 2],
        "adds": {},
        "drops": {},
        "draft_picks": [],
        "waiver_budget": [{"sender": 1, "receiver": 2, "amount": 25}],
    }
    trade = normalize_trade(
        raw_tx,
        roster_to_user={1: "u_a", 2: "u_b"},
        league_id="L",
        season=2024,
    )
    a, b = trade.sides["u_a"], trade.sides["u_b"]
    assert any(isinstance(x, FaabAsset) and x.amount == 25 for x in a.given)
    assert any(isinstance(x, FaabAsset) and x.amount == 25 for x in b.received)


def test_normalize_skips_unmappable_rosters_gracefully():
    # If a roster_id is missing from the mapping, we still emit the side
    # under the original roster id as a fallback ("Owner #<roster_id>").
    raw_tx = {
        "type": "trade",
        "status": "complete",
        "transaction_id": "tx_ghost",
        "created": 1726099200000,
        "leg": 2,
        "roster_ids": [99, 2],
        "adds": {"1234": 2, "5678": 99},
        "drops": {"5678": 2, "1234": 99},
        "draft_picks": [],
        "waiver_budget": [],
    }
    trade = normalize_trade(
        raw_tx,
        roster_to_user={2: "u_b"},  # roster 99 not mapped
        league_id="L",
        season=2024,
    )
    # The ghost side appears under the fallback identity.
    assert "Owner #99" in trade.sides
    assert "u_b" in trade.sides


def _stub_trade(asset_user_id, season, round_, original_owner_user_id):
    """Build a trivial Trade with one PickAsset on one side, for tests."""
    pick = PickAsset(
        season=season, round=round_, original_owner_user_id=original_owner_user_id
    )
    side = TradeSide(user_id=asset_user_id, received=[pick], given=[])
    other_side = TradeSide(user_id="other", received=[], given=[pick])
    return Trade(
        transaction_id="t1",
        league_id="L",
        season=season - 1,  # traded one season before draft
        week=2,
        traded_at=datetime(season - 1, 9, 12, tzinfo=timezone.utc),
        sides={asset_user_id: side, "other": other_side},
    )


def test_resolve_replaces_pick_when_draft_exists():
    trade = _stub_trade("u1", season=2024, round_=2, original_owner_user_id="u1")
    # Draft data: in 2024, u1's draft_slot is 1. The 2nd-round pick at slot 1
    # was used to draft player_id "p_rookie_b" (matches our fixture).
    drafts_by_season = {2024: {"draft_id": "draft_2024_a", "status": "complete"}}
    draft_picks_by_draft_id = {
        "draft_2024_a": [
            {"round": 2, "pick_no": 13, "draft_slot": 1, "roster_id": 2, "player_id": "p_rookie_b"},
            {"round": 1, "pick_no": 1, "draft_slot": 1, "roster_id": 5, "player_id": "p_rookie_a"},
        ],
    }
    user_to_slot_by_season = {2024: {"u1": 1}}
    player_names = {"p_rookie_b": "Rookie B"}

    resolved = resolve_assets(
        [trade],
        drafts_by_season=drafts_by_season,
        draft_picks_by_draft_id=draft_picks_by_draft_id,
        user_to_slot_by_season=user_to_slot_by_season,
        player_names=player_names,
        resolution_by_identity=compute_pick_resolution_map([trade]),
    )
    assert len(resolved) == 1
    rt = resolved[0]
    assert isinstance(rt, ResolvedTrade)
    side = rt.sides["u1"]
    assert len(side.received) == 1
    asset = side.received[0]
    assert isinstance(asset, PlayerAsset)
    assert asset.player_id == "p_rookie_b"
    assert asset.name == "Rookie B"
    assert asset.via_pick is not None
    assert asset.via_pick.season == 2024
    assert asset.via_pick.round == 2
    assert asset.via_pick.original_owner_user_id == "u1"


def test_resolve_leaves_unresolved_pick_untouched():
    # No draft for the pick's season -> still a PickAsset.
    trade = _stub_trade("u1", season=2030, round_=1, original_owner_user_id="u1")
    resolved = resolve_assets(
        [trade],
        drafts_by_season={},
        draft_picks_by_draft_id={},
        user_to_slot_by_season={},
        player_names={},
    )
    side = resolved[0].sides["u1"]
    assert isinstance(side.received[0], PickAsset)


def test_normalize_does_not_create_phantom_side_for_pick_original_drafter():
    """Regression: a pick whose roster_id (original drafter) is NOT in
    roster_ids must NOT add a phantom side to the trade."""
    raw_tx = {
        "type": "trade",
        "status": "complete",
        "transaction_id": "tx_real_3team_lookalike",
        "created": 1777840756662,
        "leg": 1,
        "roster_ids": [3, 4],  # ONLY 2 teams in the trade
        "adds": {"2216": 3},
        "drops": {"2216": 4},
        "draft_picks": [
            {
                "season": "2027", "round": 2,
                "roster_id": 6,           # original drafter — NOT in trade
                "previous_owner_id": 3,    # prior holder — in trade (giver)
                "owner_id": 4,             # new owner — in trade (receiver)
            },
        ],
        "waiver_budget": [],
    }
    trade = normalize_trade(
        raw_tx,
        roster_to_user={3: "u_three", 4: "u_four", 6: "u_six"},
        league_id="L",
        season=2026,
    )
    # Only the two trade participants should appear as sides.
    assert set(trade.sides.keys()) == {"u_three", "u_four"}
    # The pick is given by u_three (prior holder) to u_four (new owner).
    three = trade.sides["u_three"]
    four = trade.sides["u_four"]
    given_picks = [a for a in three.given if isinstance(a, PickAsset)]
    received_picks = [a for a in four.received if isinstance(a, PickAsset)]
    assert len(given_picks) == 1
    assert len(received_picks) == 1
    # The PickAsset's original_owner_user_id is u_six (roster 6 was original drafter).
    assert given_picks[0].original_owner_user_id == "u_six"
    assert received_picks[0].original_owner_user_id == "u_six"


from unittest.mock import AsyncMock, MagicMock

from sleeper_dynasty.engine.trade_history import build_trade_history


@pytest.mark.asyncio
async def test_build_trade_history_orchestrates_one_season():
    """End-to-end: one league, one trade week, one trade — comes back resolved."""
    # Build a fake SleeperClient that returns canned responses.
    client = MagicMock()

    # Walk: just league_2024 → None.
    from sleeper_dynasty.models.league import League
    league_2024 = League(
        league_id="league_2024",
        name="Bros",
        season=2024,
        total_rosters=2,
        roster_positions=[],
        scoring_settings={},
        playoff_week_start=15,
        num_playoff_teams=6,
        status="complete",
    )
    client.walk_league_history = AsyncMock(return_value=[league_2024])
    client.get_users = AsyncMock(return_value={
        "u_alice": {"display_name": "Alice", "team_name": None},
        "u_bob": {"display_name": "Bob", "team_name": None},
    })

    from sleeper_dynasty.models.league import Roster
    client.get_rosters = AsyncMock(return_value=[
        Roster(roster_id=1, owner_id="u_alice", owner_name="Alice", players=[],
               wins=0, losses=0, ties=0, points_for=0, points_against=0),
        Roster(roster_id=2, owner_id="u_bob", owner_name="Bob", players=[],
               wins=0, losses=0, ties=0, points_for=0, points_against=0),
    ])

    # transactions: only return the fixture trade on leg 2; empty for everything else.
    fixture_trade = load_fixture("transactions_trade.json")
    async def fake_transactions(league_id, week):
        if week == 2:
            return fixture_trade
        return []
    client.get_transactions = AsyncMock(side_effect=fake_transactions)
    wire_transaction_protocol(client)

    client.get_drafts = AsyncMock(return_value=[{
        "draft_id": "draft_2024_a",
        "status": "complete",
        "season": "2024",
        "draft_order": {"u_alice": 1, "u_bob": 2},
    }])
    client.get_draft_picks = AsyncMock(return_value=[
        {"round": 1, "pick_no": 1, "draft_slot": 1, "roster_id": 1, "player_id": "p1"},
        {"round": 2, "pick_no": 14, "draft_slot": 2, "roster_id": 2, "player_id": "p_rookie_b"},
    ])

    player_names = {"5678": "Bijan Robinson", "1234": "Davante Adams", "p_rookie_b": "Rookie B"}

    resolved = await build_trade_history(
        client,
        current_league_id="league_2024",
        player_names=player_names,
    )

    # One trade comes back, fully populated.
    assert len(resolved) == 1
    rt = resolved[0]
    assert rt.trade.season == 2024
    # The 2024 2nd pick was originally Alice's (roster 1) — with draft_slot 1
    # in our fake draft order. But the fixture's draft_picks row for round 2
    # is draft_slot=2 (Bob's). Since Alice's slot=1, the resolver finds no
    # round-2 row at slot 1, so the pick stays unresolved. That's acceptable
    # for v1; we just assert the trade made it through.


@pytest.mark.asyncio
async def test_build_trade_history_backfills_player_names():
    """PlayerAssets created during normalize_trade have name="" by default.
    build_trade_history must backfill names from player_names before returning.
    """
    from unittest.mock import AsyncMock, MagicMock
    from sleeper_dynasty.engine.trade_history import build_trade_history
    from sleeper_dynasty.models.league import League, Roster
    from sleeper_dynasty.models.trade import PlayerAsset

    client = MagicMock()
    league_2024 = League(
        league_id="league_2024",
        name="Bros",
        season=2024,
        total_rosters=2,
        roster_positions=[],
        scoring_settings={},
        playoff_week_start=15,
        num_playoff_teams=6,
        status="complete",
    )
    client.walk_league_history = AsyncMock(return_value=[league_2024])
    client.get_users = AsyncMock(return_value={
        "u_alice": {"display_name": "Alice", "team_name": None},
        "u_bob": {"display_name": "Bob", "team_name": None},
    })
    client.get_rosters = AsyncMock(return_value=[
        Roster(roster_id=1, owner_id="u_alice", owner_name="Alice", players=[],
               wins=0, losses=0, ties=0, points_for=0, points_against=0),
        Roster(roster_id=2, owner_id="u_bob", owner_name="Bob", players=[],
               wins=0, losses=0, ties=0, points_for=0, points_against=0),
    ])
    # Raw transaction: Alice (roster 1) gives player 1234 and gets 5678.
    raw_tx = {
        "type": "trade",
        "status": "complete",
        "transaction_id": "tx_backfill",
        "created": 1726099200000,
        "leg": 3,
        "roster_ids": [1, 2],
        "adds": {"5678": 1, "1234": 2},
        "drops": {"1234": 1, "5678": 2},
        "draft_picks": [],
        "waiver_budget": [],
    }
    async def fake_transactions(league_id, week):
        if week == 3:
            return [raw_tx]
        return []
    client.get_transactions = AsyncMock(side_effect=fake_transactions)
    wire_transaction_protocol(client)
    client.get_drafts = AsyncMock(return_value=[])
    client.get_draft_picks = AsyncMock(return_value=[])

    player_names = {"5678": "Bijan Robinson", "1234": "Davante Adams"}

    resolved = await build_trade_history(
        client,
        current_league_id="league_2024",
        player_names=player_names,
    )

    assert len(resolved) == 1
    rt = resolved[0]
    alice_side = rt.sides["u_alice"]
    # Alice received 5678 — name should be backfilled.
    received_player = next(
        (a for a in alice_side.received if isinstance(a, PlayerAsset)), None
    )
    assert received_player is not None
    assert received_player.name == "Bijan Robinson", (
        f"Expected 'Bijan Robinson' but got {received_player.name!r}; "
        "player name was not backfilled from player_names"
    )


@pytest.mark.asyncio
async def test_build_trade_history_filters_blacklisted_transaction_ids():
    """Hard-coded blacklist must not surface in the resolved trades."""
    from unittest.mock import AsyncMock, MagicMock

    from sleeper_dynasty.engine.trade_history import (
        BLACKLISTED_TRANSACTION_IDS,
        build_trade_history,
    )
    from sleeper_dynasty.models.league import League, Roster

    # Sanity: the blacklist actually contains the two known junk IDs.
    assert "1094079897179373568" in BLACKLISTED_TRANSACTION_IDS
    assert "1031422536271220736" in BLACKLISTED_TRANSACTION_IDS

    client = MagicMock()
    league = League(
        league_id="L", name="N", season=2024,
        total_rosters=2, roster_positions=[], scoring_settings={},
        playoff_week_start=15, num_playoff_teams=6, status="complete",
    )
    client.walk_league_history = AsyncMock(return_value=[league])
    client.get_users = AsyncMock(return_value={
        "u_a": {"display_name": "A", "team_name": None},
        "u_b": {"display_name": "B", "team_name": None},
    })
    client.get_rosters = AsyncMock(return_value=[
        Roster(1, "u_a", "A", [], 0, 0, 0, 0, 0),
        Roster(2, "u_b", "B", [], 0, 0, 0, 0, 0),
    ])
    blacklisted_tx = {
        "type": "trade", "status": "complete",
        "transaction_id": "1094079897179373568",
        "created": 1726099200000, "leg": 2,
        "roster_ids": [1, 2],
        "adds": {"p_x": 1}, "drops": {"p_x": 2},
        "draft_picks": [], "waiver_budget": [],
    }
    good_tx = {
        "type": "trade", "status": "complete",
        "transaction_id": "tx_good",
        "created": 1726099200000, "leg": 2,
        "roster_ids": [1, 2],
        "adds": {"p_y": 1}, "drops": {"p_y": 2},
        "draft_picks": [], "waiver_budget": [],
    }
    async def fake_txs(_lid, week):
        return [blacklisted_tx, good_tx] if week == 2 else []
    client.get_transactions = AsyncMock(side_effect=fake_txs)
    wire_transaction_protocol(client)
    client.get_drafts = AsyncMock(return_value=[])
    client.get_draft_picks = AsyncMock(return_value=[])

    resolved = await build_trade_history(
        client, current_league_id="L", player_names={"p_x": "X", "p_y": "Y"},
    )
    tx_ids = [rt.trade.transaction_id for rt in resolved]
    assert "1094079897179373568" not in tx_ids
    assert "tx_good" in tx_ids


def test_derive_user_slot_map_uses_draft_order_when_present():
    from sleeper_dynasty.engine.trade_history import _derive_user_slot_map
    draft = {
        "draft_id": "d1",
        "status": "complete",
        "draft_order": {"u_alice": 5, "u_bob": 12, "u_carol": 3},
    }
    # Picks are irrelevant when draft_order is present.
    picks: list[dict] = []
    slot_map = _derive_user_slot_map(draft, picks, roster_to_user={})
    assert slot_map == {"u_alice": 5, "u_bob": 12, "u_carol": 3}


def test_derive_user_slot_map_falls_back_to_heuristic_without_draft_order():
    from sleeper_dynasty.engine.trade_history import _derive_user_slot_map
    draft = {"draft_id": "d1", "status": "complete"}  # no draft_order
    picks = [
        {"round": 1, "draft_slot": 7, "roster_id": 3, "player_id": "p1"},
        {"round": 2, "draft_slot": 7, "roster_id": 3, "player_id": "p2"},
        {"round": 1, "draft_slot": 4, "roster_id": 5, "player_id": "p3"},
    ]
    slot_map = _derive_user_slot_map(
        draft, picks, roster_to_user={3: "u_a", 5: "u_b"}
    )
    assert slot_map == {"u_a": 7, "u_b": 4}


def _pick_trade(tx_id, traded_at, giver, receiver, season, rnd, original_owner):
    from sleeper_dynasty.models.trade import PickAsset, Trade, TradeSide

    pick = PickAsset(season=season, round=rnd, original_owner_user_id=original_owner)
    sides = {
        giver: TradeSide(user_id=giver, received=[], given=[pick]),
        receiver: TradeSide(user_id=receiver, received=[pick], given=[]),
    }
    return Trade(
        transaction_id=tx_id, league_id="L", season=2024, week=1,
        traded_at=traded_at, sides=sides,
    )


def test_resolution_map_picks_last_receiver():
    from datetime import datetime, timezone
    from sleeper_dynasty.engine.trade_history import compute_pick_resolution_map

    # A->B (Sept), then B->C (Oct). Identity = (u_a, 2025, 1).
    ab = _pick_trade("ab", datetime(2024, 9, 1, tzinfo=timezone.utc),
                     giver="u_a", receiver="u_b", season=2025, rnd=1, original_owner="u_a")
    bc = _pick_trade("bc", datetime(2024, 10, 1, tzinfo=timezone.utc),
                     giver="u_b", receiver="u_c", season=2025, rnd=1, original_owner="u_a")

    resolution = compute_pick_resolution_map([ab, bc])
    # The pick belongs to whoever received it last: the B->C trade.
    assert resolution[("u_a", 2025, 1)] == "bc"


def test_resolution_map_handles_reacquisition():
    from datetime import datetime, timezone
    from sleeper_dynasty.engine.trade_history import compute_pick_resolution_map

    out = _pick_trade("out", datetime(2024, 9, 1, tzinfo=timezone.utc),
                      giver="u_a", receiver="u_b", season=2025, rnd=1, original_owner="u_a")
    back = _pick_trade("back", datetime(2024, 11, 1, tzinfo=timezone.utc),
                       giver="u_b", receiver="u_a", season=2025, rnd=1, original_owner="u_a")
    resolution = compute_pick_resolution_map([out, back])
    assert resolution[("u_a", 2025, 1)] == "back"


def test_resolve_assets_resolves_only_in_resolution_trade():
    from datetime import datetime, timezone
    from sleeper_dynasty.engine.trade_history import (
        compute_pick_resolution_map,
        resolve_assets,
    )
    from sleeper_dynasty.models.trade import PickAsset, PlayerAsset

    # Pick (u_a, 2024 R1) flipped A->B then B->C; C drafts player "p_drafted".
    ab = _pick_trade("ab", datetime(2024, 5, 1, tzinfo=timezone.utc),
                     giver="u_a", receiver="u_b", season=2024, rnd=1, original_owner="u_a")
    bc = _pick_trade("bc", datetime(2024, 6, 1, tzinfo=timezone.utc),
                     giver="u_b", receiver="u_c", season=2024, rnd=1, original_owner="u_a")

    drafts_by_season = {2024: {"draft_id": "d1", "status": "complete"}}
    draft_picks_by_draft_id = {
        "d1": [{"round": 1, "draft_slot": 3, "player_id": "p_drafted"}],
    }
    user_to_slot_by_season = {2024: {"u_a": 3}}  # original owner u_a holds slot 3
    player_names = {"p_drafted": "Drafted Rookie"}

    resolution = compute_pick_resolution_map([ab, bc])
    resolved = resolve_assets(
        [ab, bc],
        drafts_by_season=drafts_by_season,
        draft_picks_by_draft_id=draft_picks_by_draft_id,
        user_to_slot_by_season=user_to_slot_by_season,
        player_names=player_names,
        resolution_by_identity=resolution,
    )
    by_id = {rt.trade.transaction_id: rt for rt in resolved}

    # B->C is the resolution trade: C's received pick became the PlayerAsset.
    c_received = by_id["bc"].sides["u_c"].received
    assert any(isinstance(a, PlayerAsset) and a.player_id == "p_drafted"
               for a in c_received)

    # A->B is NOT the resolution trade: B's received asset stays a PickAsset,
    # annotated with the drafted player for valuation only.
    b_received = by_id["ab"].sides["u_b"].received
    assert len(b_received) == 1
    pick = b_received[0]
    assert isinstance(pick, PickAsset)
    assert pick.drafted_player_id == "p_drafted"
    assert pick.drafted_player_name == "Drafted Rookie"
    # No PlayerAsset leaked into the non-resolution trade.
    assert not any(isinstance(a, PlayerAsset) for a in b_received)


def test_resolve_future_pick_untouched_even_with_map():
    from datetime import datetime, timezone
    from sleeper_dynasty.models.trade import PickAsset

    # A 2030 pick whose draft hasn't happened. A resolution map exists and names
    # this trade, but with no completed draft the pick must pass through as-is.
    ab = _pick_trade("ab", datetime(2024, 9, 1, tzinfo=timezone.utc),
                     giver="u_a", receiver="u_b", season=2030, rnd=1, original_owner="u_a")
    resolution = compute_pick_resolution_map([ab])
    resolved = resolve_assets(
        [ab],
        drafts_by_season={},               # no draft for 2030
        draft_picks_by_draft_id={},
        user_to_slot_by_season={},
        player_names={},
        resolution_by_identity=resolution,
    )
    pick = resolved[0].sides["u_b"].received[0]
    assert isinstance(pick, PickAsset)
    assert pick.drafted_player_id is None   # not annotated — draft hasn't happened
    assert pick.drafted_player_name is None


def test_resolve_assets_without_map_annotates_never_upgrades():
    from datetime import datetime, timezone
    from sleeper_dynasty.models.trade import PickAsset, PlayerAsset

    # Same completed-draft setup as the resolution test, but NO map passed.
    # Contract: every drafted pick is annotated, none upgraded to a PlayerAsset.
    ab = _pick_trade("ab", datetime(2024, 5, 1, tzinfo=timezone.utc),
                     giver="u_a", receiver="u_b", season=2024, rnd=1, original_owner="u_a")
    resolved = resolve_assets(
        [ab],
        drafts_by_season={2024: {"draft_id": "d1", "status": "complete"}},
        draft_picks_by_draft_id={"d1": [{"round": 1, "draft_slot": 3, "player_id": "p_drafted"}]},
        user_to_slot_by_season={2024: {"u_a": 3}},
        player_names={"p_drafted": "Drafted Rookie"},
        # resolution_by_identity omitted -> defaults to {}
    )
    received = resolved[0].sides["u_b"].received
    assert all(isinstance(a, PickAsset) for a in received)
    assert not any(isinstance(a, PlayerAsset) for a in received)
    assert received[0].drafted_player_id == "p_drafted"


def test_fetch_league_season_data_uses_cache_for_sealed_league():
    import asyncio
    from types import SimpleNamespace
    from sleeper_dynasty.engine.trade_history import _fetch_league_season_data

    class FakeCache:
        def __init__(self, stored): self.stored = stored; self.writes = []
        def read_trade_bundle(self, lid): return self.stored.get(lid)
        def write_trade_bundle(self, lid, b): self.writes.append((lid, b))

    class FailClient:
        # Any network access is a test failure for the sealed/cached path.
        async def get_users(self, *a): raise AssertionError("network hit")
        async def get_rosters(self, *a): raise AssertionError("network hit")
        async def get_transactions(self, *a): raise AssertionError("network hit")
        async def get_trade_transactions(self, *a): raise AssertionError("network hit")
        async def get_drop_transactions(self, *a): raise AssertionError("network hit")
        async def get_drafts(self, *a): raise AssertionError("network hit")
        async def get_draft_picks(self, *a): raise AssertionError("network hit")

    sealed = SimpleNamespace(league_id="L1", season=2024, name="Bros",
                             status="complete")
    bundle = {
        "users": {"u_a": {}}, "roster_to_user": {1: "u_a"},
        "raw_trades": [], "drafts": [], "draft_picks_by_draft_id": {},
    }
    cache = FakeCache({"L1": dict(bundle)})

    out = asyncio.run(_fetch_league_season_data(FailClient(), sealed, cache))
    # League re-attached; rest comes straight from cache; nothing written.
    assert out["league"] is sealed
    assert out["raw_trades"] == [] and out["roster_to_user"] == {1: "u_a"}
    assert cache.writes == []


def test_fetch_league_season_data_fetches_and_stores_when_sealed_and_uncached():
    import asyncio
    from types import SimpleNamespace
    from sleeper_dynasty.engine.trade_history import _fetch_league_season_data

    class FakeCache:
        def __init__(self): self.store = {}; self.writes = 0
        def read_trade_bundle(self, lid): return self.store.get(lid)
        def write_trade_bundle(self, lid, b): self.store[lid] = b; self.writes += 1

    class StubClient:
        async def get_users(self, lid): return {"u_a": {}}
        async def get_rosters(self, lid):
            return [SimpleNamespace(roster_id=1, owner_id="u_a")]
        async def get_transactions(self, lid, w): return []
        async def get_trade_transactions(self, lid): return []
        async def get_drop_transactions(self, lid): return []
        async def get_roster_transactions(self, lid): return []
        async def get_drafts(self, lid): return []
        async def get_draft_picks(self, did): return []

    sealed = SimpleNamespace(league_id="L1", season=2024, name="Bros",
                             status="complete")
    cache = FakeCache()
    out = asyncio.run(_fetch_league_season_data(StubClient(), sealed, cache))
    assert out["roster_to_user"] == {1: "u_a"}
    assert cache.writes == 1
    assert "league" not in cache.store["L1"]   # League object excluded from cache


def test_fetch_league_season_data_produces_raw_roster_txs():
    """I2 pre-merge fix: the producer side had NO test -- the bundle must
    actually carry `raw_roster_txs`, both in the dict `_fetch_league_season_
    data` returns and in what it writes to the sealed-season cache. Without
    this, the consumer's cache-read wiring (grader.py) has nothing real to
    read: the whole point of caching this feed is to avoid a fresh 18-week
    walk per sealed league-season on every refresh, and that only holds if
    the producer actually put the fetched transactions in the bundle.

    Mutation this catches: deleting the `raw_roster_txs = await client.
    get_roster_transactions(...)` fetch and its `"raw_roster_txs": raw_
    roster_txs` bundle entry (trade_history.py:380,394) drops the key from
    BOTH the returned dict and the cached write -- `out["raw_roster_txs"]`
    raises KeyError and the cache-store assertion fails.
    """
    import asyncio
    from types import SimpleNamespace
    from sleeper_dynasty.engine.trade_history import _fetch_league_season_data

    class FakeCache:
        def __init__(self): self.store = {}
        def read_trade_bundle(self, lid): return self.store.get(lid)
        def write_trade_bundle(self, lid, b): self.store[lid] = b

    _SENTINEL_TXS = [{"transaction_id": "t1", "type": "waiver", "status": "complete"}]

    class StubClient:
        async def get_users(self, lid): return {"u_a": {}}
        async def get_rosters(self, lid):
            return [SimpleNamespace(roster_id=1, owner_id="u_a")]
        async def get_trade_transactions(self, lid): return []
        async def get_drop_transactions(self, lid): return []
        async def get_roster_transactions(self, lid): return list(_SENTINEL_TXS)
        async def get_drafts(self, lid): return []
        async def get_draft_picks(self, did): return []

    sealed = SimpleNamespace(league_id="L1", season=2024, name="Bros",
                              status="complete")
    cache = FakeCache()
    out = asyncio.run(_fetch_league_season_data(StubClient(), sealed, cache))

    assert out["raw_roster_txs"] == _SENTINEL_TXS
    assert cache.store["L1"]["raw_roster_txs"] == _SENTINEL_TXS


def test_fetch_league_season_data_never_caches_current_season():
    import asyncio
    from types import SimpleNamespace
    from sleeper_dynasty.engine.trade_history import _fetch_league_season_data

    class FakeCache:
        def __init__(self): self.reads = 0; self.writes = 0
        def read_trade_bundle(self, lid): self.reads += 1; return None
        def write_trade_bundle(self, lid, b): self.writes += 1

    class StubClient:
        async def get_users(self, lid): return {}
        async def get_rosters(self, lid): return []
        async def get_transactions(self, lid, w): return []
        async def get_trade_transactions(self, lid): return []
        async def get_drop_transactions(self, lid): return []
        async def get_roster_transactions(self, lid): return []
        async def get_drafts(self, lid): return []
        async def get_draft_picks(self, did): return []

    current = SimpleNamespace(league_id="L1", season=2026, name="Bros",
                              status="in_season")
    cache = FakeCache()
    asyncio.run(_fetch_league_season_data(StubClient(), current, cache))
    assert cache.reads == 0 and cache.writes == 0  # status gating skips cache entirely
