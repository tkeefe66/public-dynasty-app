from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.services.chain_cache import ChainCache
from app.services.grader import GraderService
from app.services.owner_identity_store import OwnerIdentityStore

from sleeper_dynasty.api.owner_identity import OwnerIdentity, OwnerIdentityClient
from sleeper_dynasty.models.league import League, Roster

CURRENT = "461.l.100000001"
PREVIOUS = "449.l.100000002"
A = CURRENT + ".t.1"
B = CURRENT + ".t.2"
OLD_A = PREVIOUS + ".t.2"
OLD_B = PREVIOUS + ".t.1"


def identity():
    return OwnerIdentity(
        aliases={A: A, OLD_A: A, B: B, OLD_B: B},
        names={A: "Alex", B: "Blair"},
    )


def test_identity_store_roundtrip_is_scoped_and_rejects_broken_mappings(tmp_path):
    # Mutation: reading another league's mapping would combine unrelated owners.
    store = OwnerIdentityStore(tmp_path)
    store.write(CURRENT, identity())
    assert store.read(CURRENT).aliases[OLD_A] == A
    assert store.read(PREVIOUS).aliases == {}
    with pytest.raises(ValueError, match="target"):
        OwnerIdentity(aliases={OLD_A: A, A: B}, names={B: "Blair"})
    store._path(CURRENT).write_text("{")
    with pytest.raises(ValueError, match="owner identity"):
        store.read(CURRENT)


@pytest.mark.asyncio
async def test_identity_does_not_infer_links_from_matching_names():
    # Mutation: nickname grouping would merge two unconfirmed people named Alex.
    source = SimpleNamespace(get_users=AsyncMock(return_value={
        OLD_A: {"display_name": "Alex", "team_name": "Old team"},
        "unconfirmed": {"display_name": "Alex", "team_name": "Other team"},
    }))
    users = await OwnerIdentityClient(source, identity()).get_users(PREVIOUS)
    assert set(users) == {A, "unconfirmed"}
    assert users[A]["team_name"] == "Old team"
    assert users[A]["franchise_name"] == "Alex"


@pytest.mark.asyncio
async def test_identity_rejects_two_teams_mapped_to_one_owner_in_a_season():
    # Mutation: dict rekey without collision validation silently drops a team.
    source = SimpleNamespace(get_users=AsyncMock(return_value={
        OLD_A: {"display_name": "Alex"}, A: {"display_name": "Another Alex"},
    }))
    with pytest.raises(ValueError, match="same season"):
        await OwnerIdentityClient(source, identity()).get_users(PREVIOUS)


class SeasonClient:
    """Normalized Yahoo shapes, with roster slots changing between seasons."""

    def __init__(self):
        self.leagues = [
            League(CURRENT, "Example", 2025, 2, ["RB"], {"rush_yd": 0.1}, 15, 2, "complete", format="keeper"),
            League(PREVIOUS, "Example", 2024, 2, ["RB"], {"rush_yd": 0.1}, 15, 2, "complete", format="keeper"),
        ]

    async def walk_league_history(self, lid):
        return self.leagues

    async def get_players(self):
        return {"p1": {"full_name": "Runner One", "position": "RB", "age": 24}}

    async def get_users(self, lid):
        return {
            (A if lid == CURRENT else OLD_A): {"display_name": "Alex", "team_name": "New A" if lid == CURRENT else "Old A"},
            (B if lid == CURRENT else OLD_B): {"display_name": "Blair", "team_name": "New B" if lid == CURRENT else "Old B"},
        }

    async def get_rosters(self, lid):
        return [
            Roster(1 if lid == CURRENT else 2, A if lid == CURRENT else OLD_A, "Alex", ["p1"], 10, 4, 0, 100, 50),
            Roster(2 if lid == CURRENT else 1, B if lid == CURRENT else OLD_B, "Blair", [], 4, 10, 0, 50, 100),
        ]

    async def get_trade_transactions(self, lid):
        return [] if lid == CURRENT else [{
            "transaction_id": "trade-1", "type": "trade", "status": "complete",
            "leg": 1, "created": 1725000000000, "roster_ids": [1, 2],
            "adds": {"p1": 2}, "drops": {"p1": 1}, "draft_picks": [], "waiver_budget": [],
        }]

    async def get_drop_transactions(self, lid):
        return []

    async def get_roster_transactions(self, lid):
        return await self.get_trade_transactions(lid)

    async def get_drafts(self, lid):
        return [{"draft_id": lid, "league_id": lid, "season": "2025" if lid == CURRENT else "2024", "status": "complete", "settings": {"rounds": 1, "teams": 2}}]

    async def get_draft_picks(self, lid):
        return [{"player_id": "p1", "roster_id": 1 if lid == CURRENT else 2, "round": 1, "pick_no": 1, "draft_slot": 1, "metadata": {"position": "RB"}}]

    async def get_traded_picks(self, lid):
        return []

    async def get_projections(self, season):
        return {}

    async def get_raw_matchups(self, lid, week):
        if week > 14:
            return []
        a_slot = 1 if lid == CURRENT else 2
        return [
            {"roster_id": a_slot, "matchup_id": 1, "points": 20, "starters": ["p1"], "players": ["p1"], "players_points": {"p1": 20}},
            {"roster_id": 3 - a_slot, "matchup_id": 1, "points": 10, "starters": [], "players": [], "players_points": {}},
        ]

    async def get_phase_map(self, league):
        return {}

    async def get_postseason_results(self, league):
        return {}


async def run_grader(client, tmp_path, monkeypatch):
    from app.services import grader_io

    from sleeper_dynasty.engine import injury_data
    monkeypatch.setattr(injury_data, "_fetch_csv_rows", lambda url: [])
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(grader_io, "fetch_ktc_values", AsyncMock(return_value={}))
    monkeypatch.setattr(grader_io, "fetch_fantasycalc_values", AsyncMock(return_value={}))
    monkeypatch.setattr(grader_io, "fetch_nfl_points", AsyncMock(return_value={}))

    async def progress(*args, **kwargs):
        pass

    return await GraderService().run(
        client=client, current_league_id=CURRENT, cache_dir=tmp_path,
        progress_cb=progress, skip_llm=True,
        _nfl_state={"season": 2026, "week": 1, "season_type": "off"},
    )


@pytest.mark.asyncio
async def test_linked_history_rebuilds_from_unchanged_raw_cache(tmp_path, monkeypatch):
    # Mutation: only mapping live fetches leaves sealed seasons and cached grades split.
    from app.services.aggregations import build_dashboard
    from app.services.owner_view import build_owner_detail

    from sleeper_dynasty.engine.lineage import build_trade_lineage

    old = await run_grader(SeasonClient(), tmp_path, monkeypatch)
    cache = ChainCache(tmp_path)
    cache.write(CURRENT, old)
    raw_before = {p.name: p.read_bytes() for p in tmp_path.glob("raw_*.json")}
    assert len(old.owners) == 4

    linked = await run_grader(OwnerIdentityClient(SeasonClient(), identity()), tmp_path, monkeypatch)
    assert set(linked.owners) == {A, B}
    assert linked.owners[A]["team_name"] == "New A"
    assert linked.owner_identity_version == identity().version
    assert linked.owner_aliases[OLD_A] == A
    assert linked.roster_to_user_by_league[PREVIOUS] == {1: B, 2: A}
    assert set(linked.season_records["2024"]) == {A, B}
    assert set(linked.season_records["2025"]) == {A, B}
    assert linked.grades["trade-1"]["production_total"][A] == 560
    assert linked.head_to_head[A][B]["wins"] == 28
    assert len(linked.drafted_picks) == 2
    assert {p["drafter_id"] for p in linked.drafted_picks} == {A}
    tree = build_trade_lineage(linked.resolved_trades, "trade-1", linked.current_holders)
    assert tree[A][0].terminal_state == "on_roster"
    assert {p.name: p.read_bytes() for p in tmp_path.glob("raw_*.json")} == raw_before

    cache.write(CURRENT, linked)
    reloaded = cache.read(CURRENT)
    assert reloaded.owner_aliases == identity().aliases
    assert cache.read(CURRENT, owner_identity_version="obsolete") is None
    assert len(build_dashboard(reloaded, "all", "ktc").standings) == 2
    assert {r.owner.franchise_name for r in build_dashboard(reloaded, "all", "ktc").standings} == {"Alex", "Blair"}
    detail = build_owner_detail(reloaded, OLD_A)
    assert detail is not None and detail.user_id == A


def test_pre_identity_cache_keeps_existing_behavior(tmp_path):
    # Mutation: forcing every league to have a mapping makes existing Sleeper caches cold.
    from tests.helpers import minimal_chain_cache_entry
    cache = ChainCache(tmp_path)
    entry = minimal_chain_cache_entry()
    assert entry.owner_aliases == {}
    assert entry.owner_identity_version == ""
    cache.write(entry.league_id, entry)
    assert cache.read(entry.league_id, owner_identity_version="") is not None


@pytest.mark.asyncio
async def test_refresh_rejects_result_if_owner_links_changed_mid_run(tmp_path, monkeypatch):
    # Mutation: publishing a stale run would undo an operator's owner repair.
    from app.services import refresh_service

    from tests.helpers import minimal_chain_cache_entry
    entry = minimal_chain_cache_entry()
    entry.league_id = CURRENT
    ChainCache(tmp_path).write(CURRENT, entry)
    before = ChainCache(tmp_path).read(CURRENT).cached_at
    OwnerIdentityStore(tmp_path).write(CURRENT, identity())
    monkeypatch.setattr(refresh_service.GraderService, "run", AsyncMock(return_value=entry))
    monkeypatch.setattr(refresh_service, "_llm_over_budget", AsyncMock(return_value=True))
    with pytest.raises(ValueError, match="Owner links changed"):
        await refresh_service.refresh_league(SimpleNamespace(), CURRENT, cache_dir=tmp_path)
    assert ChainCache(tmp_path).read(CURRENT).cached_at == before


def test_rating_trend_does_not_compare_different_owner_groupings(tmp_path):
    # Mutation: old team-season ratings must not become an owner's career trend.
    from app.services.leaderboard import load_prev_ratings
    from app.services.rating_snapshot_store import RatingSnapshotStore
    store = RatingSnapshotStore(tmp_path)
    store.write(CURRENT, "2025-01", {A: 1700}, model="v2_keeper")
    store.write(CURRENT, "2025-02", {A: 1800}, model="v2_keeper")
    assert load_prev_ratings(tmp_path, CURRENT, model="v2_keeper", owner_identity_version=identity().version) == {}
    assert load_prev_ratings(tmp_path, CURRENT, model="v2_keeper") == {A: 1700}


def test_yahoo_factory_loads_confirmed_links(tmp_path, monkeypatch):
    # Mutation: configuring a mapping must affect normal scheduled clients too.
    from app import config
    from app.services.platform_client import client_for_league

    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(cache_dir=tmp_path))
    OwnerIdentityStore(tmp_path).write(CURRENT, identity())
    client = client_for_league(CURRENT, access_token="test-only-token")
    assert isinstance(client, OwnerIdentityClient)
    assert client.identity.resolve(OLD_A) == A
