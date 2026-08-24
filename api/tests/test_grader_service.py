from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.grader import GraderService
from sleeper_dynasty.api.sleeper import SleeperClient as _SC


@pytest.mark.asyncio
async def test_grader_service_emits_progress_and_returns_entry():
    fake_chain = [
        MagicMock(league_id="L1", name="Bros", season=2026,
                  playoff_week_start=15, total_rosters=2),
    ]
    fake_client = MagicMock()
    fake_client.walk_league_history = AsyncMock(return_value=fake_chain)
    fake_client.get_players = AsyncMock(return_value={
        "p1": {"full_name": "Player One", "position": "RB"},
    })

    progress_events = []

    async def progress_cb(stage: str, message: str, **extra):
        progress_events.append({"stage": stage, "message": message, **extra})

    svc = GraderService()

    async def fake_build_trade_history(client, current_league_id, player_names, **kwargs):
        return [], {}

    async def fake_pull_supporting_data(client, chain, **kwargs):
        return {
            "matchups": {},
            "ktc_by_player_id": {},
            "pick_value_table": {},
            "playoff_weeks_by_league": {"L1": 15},
            "roster_to_user_by_league": {"L1": {1: "u_a"}},
            "league_name_by_id": {"L1": "Bros"},
            "league_season_by_id": {"L1": 2026},
            "owners": {"u_a": {"owner_name": "Alice", "team_name": None, "avatar_url": None}},
            "warnings": [],
        }

    entry = await svc.run(
        client=fake_client,
        current_league_id="L1",
        progress_cb=progress_cb,
        _build_trade_history=fake_build_trade_history,
        _pull_supporting_data=fake_pull_supporting_data,
    )

    assert entry.league_id == "L1"
    assert entry.owners == {"u_a": {"owner_name": "Alice", "team_name": None, "avatar_url": None}}
    stages = {e["stage"] for e in progress_events}
    assert {"chain", "players", "trades", "supporting", "grading", "done"} <= stages


@pytest.mark.asyncio
async def test_grader_service_handles_empty_chain_gracefully():
    fake_client = MagicMock()
    fake_client.walk_league_history = AsyncMock(return_value=[])
    fake_client.get_players = AsyncMock(return_value={})

    progress_events = []

    async def progress_cb(stage, message, **extra):
        progress_events.append({"stage": stage, "message": message})

    async def fake_build(*args, **kwargs):
        return [], {}

    async def fake_pull(*args, **kwargs):
        return {
            "matchups": {}, "ktc_by_player_id": {}, "pick_value_table": {},
            "playoff_weeks_by_league": {}, "roster_to_user_by_league": {},
            "league_name_by_id": {}, "league_season_by_id": {},
            "owners": {}, "warnings": ["empty chain"],
        }

    svc = GraderService()
    entry = await svc.run(
        client=fake_client,
        current_league_id="L1",
        progress_cb=progress_cb,
        _build_trade_history=fake_build,
        _pull_supporting_data=fake_pull,
    )
    assert entry.warnings == ["empty chain"]


@pytest.mark.asyncio
async def test_cold_and_warm_runs_produce_identical_output(tmp_path):
    from types import SimpleNamespace
    from app.services.grader import GraderService

    # Two-season sealed chain. Season 2023 trades a player; season 2024 exists.
    leagues = [
        SimpleNamespace(league_id="L2024", season=2024, name="Bros",
                        playoff_week_start=15, total_rosters=2, status="complete",
                        playoff_round_type=0, format="dynasty"),
        SimpleNamespace(league_id="L2023", season=2023, name="Bros",
                        playoff_week_start=15, total_rosters=2, status="complete",
                        playoff_round_type=0, format="dynasty"),
    ]

    trade_tx = {
        "transaction_id": "tx1", "type": "trade", "status": "complete",
        "leg": 2, "created": 1690000000000,
        "roster_ids": [1, 2], "adds": {"p1": 2}, "drops": {"p1": 1},
        "draft_picks": [], "waiver_budget": [],
    }

    class CountingClient:
        def __init__(self): self.calls = 0
        async def walk_league_history(self, lid): return leagues
        async def get_players(self):
            self.calls += 1
            return {"p1": {"full_name": "Player One", "position": "RB"}}
        async def get_users(self, lid):
            self.calls += 1; return {"u_a": {"display_name": "Alice"},
                                     "u_b": {"display_name": "Bob"}}
        async def get_rosters(self, lid):
            self.calls += 1
            return [SimpleNamespace(roster_id=1, owner_id="u_a"),
                    SimpleNamespace(roster_id=2, owner_id="u_b")]
        async def get_transactions(self, lid, w):
            self.calls += 1
            return [trade_tx] if (lid == "L2023" and w == 2) else []
        async def get_drafts(self, lid): self.calls += 1; return []
        async def get_draft_picks(self, did): self.calls += 1; return []
        async def get_winners_bracket(self, league_id): return []
        async def get_losers_bracket(self, league_id): return []
        async def get_raw_matchups(self, lid, week):
            self.calls += 1
            return []
        _all_week_transactions = _SC._all_week_transactions
        get_trade_transactions = _SC.get_trade_transactions
        get_drop_transactions = _SC.get_drop_transactions
        get_roster_transactions = _SC.get_roster_transactions

    async def progress_cb(stage, message, **extra): pass

    # Stub global value fetchers to no-ops so only Sleeper calls are counted.
    import app.services.grader_io as gio
    async def _no_ktc(): return {}
    async def _no_fc(*, dynasty=True): return {}
    orig_ktc, orig_fc = gio.fetch_ktc_values, gio.fetch_fantasycalc_values
    gio.fetch_ktc_values, gio.fetch_fantasycalc_values = _no_ktc, _no_fc
    try:
        cold_client = CountingClient()
        cold = await GraderService().run(
            client=cold_client, current_league_id="L2024",
            progress_cb=progress_cb, cache_dir=tmp_path,
        )
        cold_calls = cold_client.calls

        warm_client = CountingClient()
        warm = await GraderService().run(
            client=warm_client, current_league_id="L2024",
            progress_cb=progress_cb, cache_dir=tmp_path,
        )
        warm_calls = warm_client.calls
    finally:
        gio.fetch_ktc_values, gio.fetch_fantasycalc_values = orig_ktc, orig_fc

    # Identical graded output.
    assert warm.grades == cold.grades
    assert warm.resolved_trades == cold.resolved_trades
    assert warm.roster_to_user_by_league == cold.roster_to_user_by_league
    # Warm hit the network strictly less (sealed seasons served from cache).
    assert warm_calls < cold_calls


@pytest.mark.asyncio
async def test_cold_and_warm_identical_with_populated_matchups(tmp_path):
    """Sibling to test_cold_and_warm_runs_produce_identical_output.

    Uses POPULATED matchup data so the (league_id, week, roster_id) tuple-key
    round-trip through LeagueRawCache is exercised and production/impact grading
    produces non-zero swings — proven identical between cold and warm runs.
    """
    from types import SimpleNamespace
    from app.services.grader import GraderService

    # Two-season sealed chain. Season 2023 trades p1 (roster 1 → roster 2) in week 2.
    leagues = [
        SimpleNamespace(league_id="L2024", season=2024, name="Bros",
                        playoff_week_start=15, total_rosters=2, status="complete",
                        playoff_round_type=0, format="dynasty"),
        SimpleNamespace(league_id="L2023", season=2023, name="Bros",
                        playoff_week_start=15, total_rosters=2, status="complete",
                        playoff_round_type=0, format="dynasty"),
    ]

    trade_tx = {
        "transaction_id": "tx1", "type": "trade", "status": "complete",
        "leg": 2, "created": 1690000000000,
        "roster_ids": [1, 2], "adds": {"p1": 2}, "drops": {"p1": 1},
        "draft_picks": [], "waiver_budget": [],
    }

    # Populated matchup payload: roster 2 (u_b) has p1 scoring 20 pts;
    # roster 1 (u_a) is the opponent with a different player scoring 10 pts.
    # This single entry is returned for every matchup URL so production
    # accrues identically across all post-trade weeks.
    _POPULATED_MATCHUPS = [
        {
            "matchup_id": 1, "roster_id": 2, "points": 100.0,
            "starters": ["p1"], "players": ["p1"], "players_points": {"p1": 20.0},
        },
        {
            "matchup_id": 1, "roster_id": 1, "points": 90.0,
            "starters": ["p2"], "players": ["p2"], "players_points": {"p2": 10.0},
        },
    ]

    class CountingClient:
        def __init__(self): self.calls = 0

        async def walk_league_history(self, lid):
            return leagues

        async def get_players(self):
            self.calls += 1
            return {
                "p1": {"full_name": "Player One", "position": "RB"},
                "p2": {"full_name": "Player Two", "position": "WR"},
            }

        async def get_users(self, lid):
            self.calls += 1
            return {
                "u_a": {"display_name": "Alice"},
                "u_b": {"display_name": "Bob"},
            }

        async def get_rosters(self, lid):
            self.calls += 1
            return [
                SimpleNamespace(roster_id=1, owner_id="u_a"),
                SimpleNamespace(roster_id=2, owner_id="u_b"),
            ]

        async def get_transactions(self, lid, w):
            self.calls += 1
            return [trade_tx] if (lid == "L2023" and w == 2) else []

        async def get_drafts(self, lid):
            self.calls += 1
            return []

        async def get_draft_picks(self, did):
            self.calls += 1
            return []

        async def get_winners_bracket(self, league_id):
            return []

        async def get_losers_bracket(self, league_id):
            return []

        async def get_raw_matchups(self, league_id, week):
            self.calls += 1
            # Populated matchups only for post-trade weeks: L2023 weeks > 2
            # (strictly after the trade) and all of L2024.
            use_populated = (
                (league_id == "L2023" and week > 2) or league_id == "L2024"
            )
            return _POPULATED_MATCHUPS if use_populated else []
        _all_week_transactions = _SC._all_week_transactions
        get_trade_transactions = _SC.get_trade_transactions
        get_drop_transactions = _SC.get_drop_transactions
        get_roster_transactions = _SC.get_roster_transactions

    async def progress_cb(stage, message, **extra): pass

    import app.services.grader_io as gio
    async def _no_ktc(): return {}
    async def _no_fc(*, dynasty=True): return {}
    orig_ktc, orig_fc = gio.fetch_ktc_values, gio.fetch_fantasycalc_values
    gio.fetch_ktc_values, gio.fetch_fantasycalc_values = _no_ktc, _no_fc
    try:
        cold_client = CountingClient()
        cold = await GraderService().run(
            client=cold_client, current_league_id="L2024",
            progress_cb=progress_cb, cache_dir=tmp_path,
        )
        cold_calls = cold_client.calls

        warm_client = CountingClient()
        warm = await GraderService().run(
            client=warm_client, current_league_id="L2024",
            progress_cb=progress_cb, cache_dir=tmp_path,
        )
        warm_calls = warm_client.calls
    finally:
        gio.fetch_ktc_values, gio.fetch_fantasycalc_values = orig_ktc, orig_fc

    # Identical graded output cold vs warm.
    assert warm.grades == cold.grades
    assert warm.resolved_trades == cold.resolved_trades

    # Warm run served sealed seasons from cache — fewer HTTP calls.
    assert warm_calls < cold_calls

    # Non-trivial production: tx1's production_total must show
    # p1 scoring non-zero points for at least one side post-trade.
    # cold.grades["tx1"] is a _to_dict(TradeGrade), with key
    # "production_total" → {user_id: float}.
    assert "tx1" in cold.grades, "Expected trade tx1 in grades"
    swing = cold.grades["tx1"]["production_total"]
    # u_b received p1 and p1 scored 20 pts/week in post-trade matchups.
    assert any(v != 0.0 for v in swing.values()), (
        f"Expected non-zero hindsight production swing; got {swing}"
    )


@pytest.mark.asyncio
async def test_run_merges_at_trade_fields_into_grades(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from datetime import date
    import app.services.grader_io as gio
    import app.services.at_trade as at_trade_mod
    from app.services.grader import GraderService

    leagues = [SimpleNamespace(league_id="L1", season=2026, name="Bros",
                               playoff_week_start=15, total_rosters=2, status="complete",
                               playoff_round_type=0, format="dynasty")]
    trade_tx = {"transaction_id": "tx1", "type": "trade", "status": "complete",
                "leg": 1, "created": 1746230400000,  # 2026-05-03
                "roster_ids": [1, 2], "adds": {"p_allen": 2}, "drops": {"p_allen": 1},
                "draft_picks": [], "waiver_budget": []}

    class C:
        async def walk_league_history(self, lid): return leagues
        async def get_players(self): return {"p_allen": {"full_name": "Josh Allen", "position": "QB"}}
        async def get_users(self, lid): return {"u_a": {"display_name": "A"}, "u_b": {"display_name": "B"}}
        async def get_rosters(self, lid):
            return [SimpleNamespace(roster_id=1, owner_id="u_a"),
                    SimpleNamespace(roster_id=2, owner_id="u_b")]
        async def get_transactions(self, lid, w): return [trade_tx] if w == 1 else []
        async def get_drafts(self, lid): return []
        async def get_draft_picks(self, did): return []
        async def get_winners_bracket(self, league_id): return []
        async def get_losers_bracket(self, league_id): return []
        async def get_raw_matchups(self, lid, week): return []
        _all_week_transactions = _SC._all_week_transactions
        get_trade_transactions = _SC.get_trade_transactions
        get_drop_transactions = _SC.get_drop_transactions
        get_roster_transactions = _SC.get_roster_transactions

    async def _ktc():
        from sleeper_dynasty.models.player import KTCValue
        return {"josh allen": KTCValue(name="Josh Allen", normalized_name="josh allen",
                                       position="QB", superflex_value=8000, one_qb_value=7900)}
    async def _fc(*, dynasty=True): return {}
    monkeypatch.setattr(gio, "fetch_ktc_values", _ktc)
    monkeypatch.setattr(gio, "fetch_fantasycalc_values", _fc)
    monkeypatch.setattr(at_trade_mod, "BACKFILL_CUTOFF", date(2020, 1, 1))

    async def cb(*a, **k): pass
    entry = await GraderService().run(client=C(), current_league_id="L1",
                                      progress_cb=cb, cache_dir=tmp_path)
    g = entry.grades["tx1"]
    assert "at_trade_value_swing" in g
    assert g["at_trade_value_swing"]["u_b"] == 8000.0
    assert g["aged_value_swing"]["u_b"] == 0.0
    assert g["at_trade_approx"] is True


@pytest.mark.asyncio
async def test_grader_service_stamps_league_phase():
    fake_chain = [
        MagicMock(league_id="L1", name="Bros", season=2026,
                  playoff_week_start=15, total_rosters=2),
    ]
    fake_client = MagicMock()
    fake_client.walk_league_history = AsyncMock(return_value=fake_chain)
    fake_client.get_players = AsyncMock(return_value={})
    fake_client.get_nfl_state = AsyncMock(return_value={
        "season_type": "regular", "season": "2026", "week": 5,
    })

    async def fake_build(client, current_league_id, player_names, **kwargs):
        return [], {}

    async def fake_pull(client, chain, **kwargs):
        return {
            "matchups": {}, "ktc_by_player_id": {}, "pick_value_table": {},
            "playoff_weeks_by_league": {"L1": 15},
            "roster_to_user_by_league": {"L1": {1: "u_a"}},
            "league_name_by_id": {"L1": "Bros"},
            "league_season_by_id": {"L1": 2026},
            "owners": {"u_a": {"owner_name": "Alice", "team_name": None, "avatar_url": None}},
            "warnings": [],
        }

    entry = await GraderService().run(
        client=fake_client,
        current_league_id="L1",
        progress_cb=AsyncMock(),
        _build_trade_history=fake_build,
        _pull_supporting_data=fake_pull,
    )
    assert entry.league_phase == {"phase": "regular", "season": 2026, "week": 5}


@pytest.mark.asyncio
async def test_grader_service_stamps_week_recap():
    """The recap is computed in the as-of-today value layer next to league_phase,
    straight from `matchups` — so the published figures reconcile with the
    standings built from the same entries."""
    fake_chain = [
        MagicMock(league_id="L1", name="Bros", season=2026,
                  playoff_week_start=15, total_rosters=2),
    ]
    fake_client = MagicMock()
    fake_client.walk_league_history = AsyncMock(return_value=fake_chain)
    fake_client.get_players = AsyncMock(return_value={})
    fake_client.get_nfl_state = AsyncMock(return_value={
        "season_type": "regular", "season": "2026", "week": 5,
    })

    async def fake_build(client, current_league_id, player_names, **kwargs):
        return [], {}

    def _mu(team, opp, opp_rid):
        return {
            "starters": [], "players": [], "players_points": {},
            "team_points": team, "opponent_points": opp,
            "opponent_roster_id": opp_rid,
        }

    async def fake_pull(client, chain, **kwargs):
        return {
            # Week 4 completed (current week is 5): Alice 130.0 beats Bob 90.0.
            "matchups": {
                ("L1", 4, 1): _mu(130.0, 90.0, 2),
                ("L1", 4, 2): _mu(90.0, 130.0, 1),
            },
            "ktc_by_player_id": {}, "pick_value_table": {},
            "playoff_weeks_by_league": {"L1": 15},
            "roster_to_user_by_league": {"L1": {1: "u_a", 2: "u_b"}},
            "league_name_by_id": {"L1": "Bros"},
            "league_season_by_id": {"L1": 2026},
            "owners": {
                "u_a": {"owner_name": "Alice", "team_name": None, "avatar_url": None},
                "u_b": {"owner_name": "Bob", "team_name": None, "avatar_url": None},
            },
            "warnings": [],
        }

    entry = await GraderService().run(
        client=fake_client,
        current_league_id="L1",
        progress_cb=AsyncMock(),
        _build_trade_history=fake_build,
        _pull_supporting_data=fake_pull,
    )
    assert entry.week_recap["season"] == "2026"
    assert entry.week_recap["week"] == 4
    assert entry.week_recap["high_score"] == {"user_id": "u_a", "points": 130.0}
    assert entry.week_recap["blowout"] == {
        "winner_user_id": "u_a", "loser_user_id": "u_b", "margin": 40.0,
    }
    # No trades in this fixture, so nobody started a trade-acquired player.
    assert entry.week_recap["traded_points"] is None


# ---------------------------------------------------------------------------
# Phase 5 Task 6 — draft_needs stamping (chain-cache-field quartet, 3/4: the
# grader actually computes and stamps the field; round-trip/pre-feature live
# in test_chain_cache.py, view fallback + format gates in
# test_draft_board_view.py).
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_grader_service_stamps_draft_needs(tmp_path, monkeypatch):
    """A fully-capable two-season dynasty chain with a completed rookie draft
    must come out of `GraderService.run` with `draft_needs["2024"]` -- one
    entry per owner, mapped from the engine's `OwnerNeeds` dataclass onto
    the wire-shaped dict `ChainCacheEntry.draft_needs` stores.

    FIX (round 1 review): the first version of this test gave every owner a
    hole-free roster (`holes == []` for both), which made `drafted_into`/
    `started` vacuously `[]`/`0` regardless of what `_picks_by_owner`/
    `_started_by_pick` actually contained -- deleting the whole loop that
    builds them in grader.py left the test green. Fixed by making u_b's
    seed roster genuinely empty at draft time.

    C1 fix (2026-08-17, pre-merge round): an empty slot is NO LONGER an
    unconditional hole -- `draft_needs.py` used to give it infinite
    severity (`margin=float("-inf")`), which is exactly the non-finite
    value that reached the HTTP response and 500'd the whole draft board.
    An empty slot now renders as empty (`margin=None`, `is_hole=False`);
    whether it should count as a hole is deliberately left undecided by
    arithmetic. So this fixture no longer leaves u_b's seed roster empty --
    it gives u_b a real, genuinely-below-replacement QB (`p_qb_b`, the
    league's worst ECR) instead, so u_b's hole comes from real board
    arithmetic. `p_qb_filler` is bench-only pool depth on u_a's roster (see
    `engine/draft_needs.py`'s tests for why depth is needed: with only two
    owners and no depth, the replacement line would land self-referentially
    on u_b's own value and never be strictly below it). u_a keeps its
    single, clearly-best QB (`p_qb_a`) as the hole-free contrast case.
    """
    fake_chain = [
        MagicMock(league_id="L2024", name="Bros", season=2024,
                  playoff_week_start=15, total_rosters=2, format="dynasty"),
        MagicMock(league_id="L2023", name="Bros", season=2023,
                  playoff_week_start=15, total_rosters=2, format="dynasty"),
    ]
    fake_client = MagicMock()
    fake_client.walk_league_history = AsyncMock(return_value=fake_chain)
    fake_client.get_players = AsyncMock(return_value={
        "p_qb_a": {"full_name": "QB A", "position": "QB"},
        "p_qb_filler": {"full_name": "QB Filler", "position": "QB"},
        "p_qb_b": {"full_name": "QB B", "position": "QB"},
        "p_new1": {"full_name": "Rookie One", "position": "RB"},
        "p_new2": {"full_name": "Rookie Two", "position": "QB"},
    })
    fake_client.get_traded_picks = AsyncMock(return_value=[])
    fake_client.get_roster_transactions = AsyncMock(return_value=[])

    _ROOKIE_DRAFT = {
        "draft_id": "d1", "status": "complete", "season": "2024",
        "type": "snake",
        "settings": {"player_type": 1, "rounds": 1, "teams": 2},
        "last_picked": 1715731200000,  # 2024-05-14, arbitrary
        "start_time": 1715731200000,
    }
    _PICKS = [
        {"player_id": "p_new1", "picked_by": "u_a", "round": 1,
         "draft_slot": 1, "pick_no": 1, "is_keeper": False},
        # u_b drafts a QB into its genuinely-below-replacement QB slot.
        {"player_id": "p_new2", "picked_by": "u_b", "round": 1,
         "draft_slot": 2, "pick_no": 2, "is_keeper": False},
    ]

    async def _get_drafts(lid):
        return [_ROOKIE_DRAFT] if lid == "L2024" else []

    async def _get_draft_picks(did):
        return _PICKS if did == "d1" else []

    fake_client.get_drafts = AsyncMock(side_effect=_get_drafts)
    fake_client.get_draft_picks = AsyncMock(side_effect=_get_draft_picks)

    async def fake_build(client, current_league_id, player_names, **kwargs):
        return [], {}

    def _mu(players, team, opp, opp_rid, starters=None, points=None):
        return {
            "starters": starters or [], "players": players,
            "players_points": points or {}, "team_points": team,
            "opponent_points": opp, "opponent_roster_id": opp_rid,
        }

    async def fake_pull(client, chain, **kwargs):
        return {
            # 2023's final played week -- the seed draft_needs reconstructs
            # from (NOT get_rosters, which would be 2024's live state).
            # u_a (roster 1) ends 2023 with its clear-best QB (p_qb_a)
            # PLUS bench-only pool depth (p_qb_filler) -- the depth keeps
            # the replacement line from landing self-referentially on
            # either owner's own starter (see engine/draft_needs.py's own
            # tests for why). u_b (roster 2) ends 2023 with a single,
            # genuinely-worst-ECR QB (p_qb_b) -- a real hole by board
            # arithmetic, not (post-C1) an empty-slot sentinel.
            "matchups": {
                ("L2023", 15, 1): _mu(
                    ["p_qb_a", "p_qb_filler"], 50.0, 40.0, 2),
                ("L2023", 15, 2): _mu(["p_qb_b"], 40.0, 50.0, 1),
                # p_new2 starts once for u_b in 2024, post-draft -- this is
                # what `games_started`/`started_by_pick`/`started` read, AND
                # (Biggest Needs redesign, 2026-08-19) what `production_total`
                # -- and therefore `production` -- reads too, from the same
                # matchup entry.
                ("L2024", 1, 2): _mu(["p_new2"], 10.0, 5.0, 1,
                                      starters=["p_new2"], points={"p_new2": 12.5}),
            },
            "ktc_by_player_id": {}, "pick_value_table": {},
            "playoff_weeks_by_league": {"L2024": 15, "L2023": 15},
            "playoff_week_start_by_league": {"L2024": 15, "L2023": 15},
            "phase_by_lwr": {},
            "roster_to_user_by_league": {
                "L2024": {1: "u_a", 2: "u_b"},
                "L2023": {1: "u_a", 2: "u_b"},
            },
            "roster_positions_by_league": {"L2024": ["QB", "BN"]},
            "positions": {
                "p_qb_a": "QB", "p_qb_filler": "QB", "p_qb_b": "QB",
                "p_new1": "RB", "p_new2": "QB",
            },
            "league_name_by_id": {"L2024": "Bros", "L2023": "Bros"},
            "league_season_by_id": {"L2024": 2024, "L2023": 2023},
            "owners": {
                "u_a": {"owner_name": "Alice", "team_name": None, "avatar_url": None},
                "u_b": {"owner_name": "Bob", "team_name": None, "avatar_url": None},
            },
            "owners_display": {"u_a": "Alice", "u_b": "Bob"},
            "warnings": [],
        }

    # The real committed dynasty-overall ECR history has no reason to cover
    # an invented draft_id/date, and even if it did, this test must not
    # depend on real players' (possibly tied) real-world ECR values -- see
    # the coordinator's mid-flight warning on draft_needs.py's tie-break
    # non-determinism. p_qb_a (5.0) beats p_qb_filler (10.0, worse rank but
    # still real pool depth) beats p_qb_b (999.0, the league's worst) --
    # demand["QB"]=2 (u_a's and u_b's own starters), pool sorted desc =
    # [-5.0, -10.0, -999.0], line = the 2nd-best = -10.0 (p_qb_filler's own
    # value, not self-referential to either starter). u_a's -5.0 clears it;
    # u_b's -999.0 does not, and the ECR veto (identical pool, no `points`
    # supplied here) doesn't rescue it either.
    import app.services.rookie_board_store as rbs_mod

    class _FakeBoardStore:
        def resolve_for_draft(self, draft_id, drafted_on):
            return {"p_qb_a": 5.0, "p_qb_filler": 10.0, "p_qb_b": 999.0}

    monkeypatch.setattr(
        rbs_mod.EcrBoardStore, "dynasty_overall",
        classmethod(lambda cls, cache_dir: _FakeBoardStore()))
    monkeypatch.setattr(
        rbs_mod.EcrBoardStore, "dynasty_superflex",
        classmethod(lambda cls, cache_dir: _FakeBoardStore()))

    entry = await GraderService().run(
        client=fake_client,
        current_league_id="L2024",
        progress_cb=AsyncMock(),
        cache_dir=tmp_path,
        _build_trade_history=fake_build,
        _pull_supporting_data=fake_pull,
    )

    assert entry.capabilities["roster_continuity"] is True
    assert entry.capabilities["multiyear_history"] is True
    assert "2024" in entry.draft_needs
    rows = entry.draft_needs["2024"]
    assert {r["user_id"] for r in rows} == {"u_a", "u_b"}
    by_uid = {r["user_id"]: r for r in rows}
    for r in rows:
        assert set(r) == {
            "user_id", "holes", "drafted_into", "started", "drafted_into_count",
            "slots", "production"}

    # u_a rostered its league-best QB into the league's only QB starter
    # slot -- clearly above the replacement line (drawn on the worse
    # bench-depth player, p_qb_filler), so u_a is hole-free. Deterministic:
    # no board tie-break, no unranked sentinel, involved.
    assert by_uid["u_a"]["holes"] == []
    assert by_uid["u_a"]["drafted_into"] == []
    assert by_uid["u_a"]["started"] == 0
    assert by_uid["u_a"]["drafted_into_count"] == 0
    assert by_uid["u_a"]["production"] == 0.0, "u_a has no holes, so nothing was ever credited"

    # u_b went into the draft with a genuinely below-replacement QB (real
    # board arithmetic, post-C1 -- an empty slot no longer auto-holes),
    # drafted a QB into it, and that QB recorded a start. Mutation this
    # proves against: gutting the `_picks_by_owner`/`_started_by_pick` loop
    # in grader.py (~1472-1483) leaves `picks_by_owner`/`started_by_pick`
    # empty, which would flip `drafted_into`/`started` back to `[]`/`0`
    # here.
    assert by_uid["u_b"]["holes"] == ["QB"]
    assert by_uid["u_b"]["drafted_into"] == ["QB"]
    assert by_uid["u_b"]["started"] == 1
    assert by_uid["u_b"]["drafted_into_count"] == 1
    assert by_uid["u_b"]["production"] == 12.5


# ---------------------------------------------------------------------------
# Task 2 (2026-08-17 league-native-holes revision) — the replacement line is
# now drawn on prior-season points, supplied by the grader as
# `build_draft_needs(..., points=...)`. Two things can go silently wrong
# building that map: reading the WRONG SEASON's points (the draft's own,
# unplayed season, instead of the prior one -- hindsight), and reading only
# ONE WEEK instead of summing every week present for that league id. Each
# gets its own dedicated test below; deliberately genuine population depth
# (3 rostered QBs, demand 2) so the replacement line is never degenerate --
# see the mutation-first-tests population-vs-cut-index trap.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_grader_service_draft_needs_points_come_from_prior_season_only(
        tmp_path, monkeypatch):
    """The points map feeding the replacement line must be built from the
    PRIOR season's league id (L2023, same `_prior_league_id` the seed already
    uses) -- never the draft's own season (L2024). For a draft that season
    has not been played; reading it would silently become hindsight the
    moment real games start landing under that league id.

    Fixture: u_a rosters two QBs -- p_qb_a1 (starter, prior-season points 300)
    and p_qb_a2 (bench, 80). u_b rosters one QB -- p_qb_b1 (starter, prior-
    season points 50) -- and ALSO has a SPURIOUS L2024 (the draft's own
    season) matchup entry crediting p_qb_b1 with 1000 points, which must be
    ignored entirely.

    With demand["QB"] = 2 (both owners' known starters) and a genuine
    3-player population (a1=300, a2=80, b1=50), the line is the 2nd-best =
    80 -- b1's OWN starter (50) sits genuinely below it (not a self-tie),
    making u_b's QB slot a real hole with margin -30.

    Mutation this catches: building the points map from `_needs_class.
    league_id` (or unfiltered, from every league in the chain) instead of
    `_prior_league_id` reads p_qb_b1's value as (at least) 1000 -- well above
    any replacement line -- and u_b's QB hole vanishes. Falsified live:
    swapping `_prior_league_id` for `_needs_class.league_id` at the points-map
    build site turns `by_uid["u_b"]["holes"]` from `["QB"]` to `[]` and its
    QB slot's `margin` from `-30.0` to a non-negative value.
    """
    fake_chain = [
        MagicMock(league_id="L2024", name="Bros", season=2024,
                  playoff_week_start=15, total_rosters=2, format="dynasty"),
        MagicMock(league_id="L2023", name="Bros", season=2023,
                  playoff_week_start=15, total_rosters=2, format="dynasty"),
    ]
    fake_client = MagicMock()
    fake_client.walk_league_history = AsyncMock(return_value=fake_chain)
    fake_client.get_players = AsyncMock(return_value={
        "p_qb_a1": {"full_name": "QB A1", "position": "QB"},
        "p_qb_a2": {"full_name": "QB A2", "position": "QB"},
        "p_qb_b1": {"full_name": "QB B1", "position": "QB"},
        "p_new1": {"full_name": "Rookie One", "position": "RB"},
        "p_new2": {"full_name": "Rookie Two", "position": "WR"},
    })
    fake_client.get_traded_picks = AsyncMock(return_value=[])
    fake_client.get_roster_transactions = AsyncMock(return_value=[])

    _ROOKIE_DRAFT = {
        "draft_id": "d1", "status": "complete", "season": "2024",
        "type": "snake",
        "settings": {"player_type": 1, "rounds": 1, "teams": 2},
        "last_picked": 1715731200000,  # 2024-05-14, arbitrary
        "start_time": 1715731200000,
    }
    _PICKS = [
        {"player_id": "p_new1", "picked_by": "u_a", "round": 1,
         "draft_slot": 1, "pick_no": 1, "is_keeper": False},
        {"player_id": "p_new2", "picked_by": "u_b", "round": 1,
         "draft_slot": 2, "pick_no": 2, "is_keeper": False},
    ]

    async def _get_drafts(lid):
        return [_ROOKIE_DRAFT] if lid == "L2024" else []

    async def _get_draft_picks(did):
        return _PICKS if did == "d1" else []

    fake_client.get_drafts = AsyncMock(side_effect=_get_drafts)
    fake_client.get_draft_picks = AsyncMock(side_effect=_get_draft_picks)

    async def fake_build(client, current_league_id, player_names, **kwargs):
        return [], {}

    def _mu(players, points, team, opp, opp_rid, starters=None):
        return {
            "starters": starters or [], "players": players,
            "players_points": points, "team_points": team,
            "opponent_points": opp, "opponent_roster_id": opp_rid,
        }

    async def fake_pull(client, chain, **kwargs):
        return {
            "matchups": {
                # u_a (roster 1): p_qb_a1 scores in TWO weeks (150 + 150 =
                # 300 total); p_qb_a2 only shows up in the final week (80).
                ("L2023", 10, 1): _mu(["p_qb_a1"], {"p_qb_a1": 150.0},
                                       50.0, 40.0, 2),
                ("L2023", 15, 1): _mu(
                    ["p_qb_a1", "p_qb_a2"],
                    {"p_qb_a1": 150.0, "p_qb_a2": 80.0}, 50.0, 40.0, 2),
                # u_b (roster 2): p_qb_b1's real, prior-season total is 50.
                ("L2023", 15, 2): _mu(["p_qb_b1"], {"p_qb_b1": 50.0},
                                       40.0, 50.0, 1),
                # SPURIOUS: the draft's own (unplayed-at-draft-time) season
                # crediting the SAME player with a huge, misleading total.
                # Must never reach the points map.
                ("L2024", 1, 2): _mu(["p_qb_b1"], {"p_qb_b1": 1000.0},
                                      10.0, 5.0, 1),
            },
            "ktc_by_player_id": {}, "pick_value_table": {},
            "playoff_weeks_by_league": {"L2024": 15, "L2023": 15},
            "playoff_week_start_by_league": {"L2024": 15, "L2023": 15},
            "phase_by_lwr": {},
            "roster_to_user_by_league": {
                "L2024": {1: "u_a", 2: "u_b"},
                "L2023": {1: "u_a", 2: "u_b"},
            },
            "roster_positions_by_league": {"L2024": ["QB", "BN", "BN"]},
            "positions": {
                "p_qb_a1": "QB", "p_qb_a2": "QB", "p_qb_b1": "QB",
                "p_new1": "RB", "p_new2": "WR",
            },
            "league_name_by_id": {"L2024": "Bros", "L2023": "Bros"},
            "league_season_by_id": {"L2024": 2024, "L2023": 2023},
            "owners": {
                "u_a": {"owner_name": "Alice", "team_name": None, "avatar_url": None},
                "u_b": {"owner_name": "Bob", "team_name": None, "avatar_url": None},
            },
            "owners_display": {"u_a": "Alice", "u_b": "Bob"},
            "warnings": [],
        }

    # Empty-of-our-players board (one unrelated placeholder keeps it
    # truthy -- `if _board:` on a literal `{}` would skip the whole stage).
    # None of our fixture players resolve to a real ECR rank, so the ECR
    # veto ties for all of them and never rescues -- points alone decide.
    import app.services.rookie_board_store as rbs_mod

    class _FakeBoardStore:
        def resolve_for_draft(self, draft_id, drafted_on):
            return {"_unused_placeholder": 999.0}

    monkeypatch.setattr(
        rbs_mod.EcrBoardStore, "dynasty_overall",
        classmethod(lambda cls, cache_dir: _FakeBoardStore()))
    monkeypatch.setattr(
        rbs_mod.EcrBoardStore, "dynasty_superflex",
        classmethod(lambda cls, cache_dir: _FakeBoardStore()))

    entry = await GraderService().run(
        client=fake_client,
        current_league_id="L2024",
        progress_cb=AsyncMock(),
        cache_dir=tmp_path,
        _build_trade_history=fake_build,
        _pull_supporting_data=fake_pull,
    )

    by_uid = {r["user_id"]: r for r in entry.draft_needs["2024"]}
    _qb_slot = lambda uid: next(
        s for s in by_uid[uid]["slots"] if s["slot"] == "QB")
    assert by_uid["u_a"]["holes"] == []
    assert _qb_slot("u_a")["is_hole"] is False
    assert by_uid["u_b"]["holes"] == ["QB"]
    assert _qb_slot("u_b")["margin"] == -30.0
    assert _qb_slot("u_b")["is_hole"] is True


@pytest.mark.asyncio
async def test_grader_service_sums_prior_season_points_across_every_week(
        tmp_path, monkeypatch):
    """The points map must SUM `players_points` across every week present
    for the prior league id, not read a single (e.g. the latest) week.
    `players_points` only covers players rostered in this league that
    season -- summing every week is how a player traded mid-season still
    accrues what he scored across both rosters that held him.

    Fixture: u_a's starter p_qb_a1 scores in TWO prior-season weeks (40 +
    40 = 80 correct total). u_a's bench p_qb_a2 (10) and u_b's starter
    p_qb_b1 (60, single week) give a genuine 3-player population against
    demand 2, so the line (2nd-best = 60) is never a self-tie of either
    starter's own value under the CORRECT sum.

    Mutation this catches: reading only the LATEST week's `players_points`
    (reusing the seed's `_latest_week_by_roster` restriction, which
    correctly governs WHO is on a roster but must not also govern points)
    drops p_qb_a1 to 40. That reshuffles the whole line: population becomes
    [60, 40, 10], line becomes 40 (a1's own now-halved value, a self-tie),
    and BOTH owners' figures move -- u_a's QB slot margin from `20.0` to
    `0.0`, u_b's from `0.0` to `20.0`. Falsified live: restricting the
    points-summing loop to `_wk == _latest_week_by_roster.get(_rid)` flips
    both assertions below.
    """
    fake_chain = [
        MagicMock(league_id="L2024", name="Bros", season=2024,
                  playoff_week_start=15, total_rosters=2, format="dynasty"),
        MagicMock(league_id="L2023", name="Bros", season=2023,
                  playoff_week_start=15, total_rosters=2, format="dynasty"),
    ]
    fake_client = MagicMock()
    fake_client.walk_league_history = AsyncMock(return_value=fake_chain)
    fake_client.get_players = AsyncMock(return_value={
        "p_qb_a1": {"full_name": "QB A1", "position": "QB"},
        "p_qb_a2": {"full_name": "QB A2", "position": "QB"},
        "p_qb_b1": {"full_name": "QB B1", "position": "QB"},
        "p_new1": {"full_name": "Rookie One", "position": "RB"},
        "p_new2": {"full_name": "Rookie Two", "position": "WR"},
    })
    fake_client.get_traded_picks = AsyncMock(return_value=[])
    fake_client.get_roster_transactions = AsyncMock(return_value=[])

    _ROOKIE_DRAFT = {
        "draft_id": "d1", "status": "complete", "season": "2024",
        "type": "snake",
        "settings": {"player_type": 1, "rounds": 1, "teams": 2},
        "last_picked": 1715731200000,
        "start_time": 1715731200000,
    }
    _PICKS = [
        {"player_id": "p_new1", "picked_by": "u_a", "round": 1,
         "draft_slot": 1, "pick_no": 1, "is_keeper": False},
        {"player_id": "p_new2", "picked_by": "u_b", "round": 1,
         "draft_slot": 2, "pick_no": 2, "is_keeper": False},
    ]

    async def _get_drafts(lid):
        return [_ROOKIE_DRAFT] if lid == "L2024" else []

    async def _get_draft_picks(did):
        return _PICKS if did == "d1" else []

    fake_client.get_drafts = AsyncMock(side_effect=_get_drafts)
    fake_client.get_draft_picks = AsyncMock(side_effect=_get_draft_picks)

    async def fake_build(client, current_league_id, player_names, **kwargs):
        return [], {}

    def _mu(players, points, team, opp, opp_rid, starters=None):
        return {
            "starters": starters or [], "players": players,
            "players_points": points, "team_points": team,
            "opponent_points": opp, "opponent_roster_id": opp_rid,
        }

    async def fake_pull(client, chain, **kwargs):
        return {
            "matchups": {
                # p_qb_a1: an EARLIER week (5, not the latest/seed week)
                # plus the final week -- 40 + 40 = 80 only if both are summed.
                ("L2023", 5, 1): _mu(["p_qb_a1"], {"p_qb_a1": 40.0},
                                      20.0, 15.0, 2),
                ("L2023", 15, 1): _mu(
                    ["p_qb_a1", "p_qb_a2"],
                    {"p_qb_a1": 40.0, "p_qb_a2": 10.0}, 50.0, 40.0, 2),
                ("L2023", 15, 2): _mu(["p_qb_b1"], {"p_qb_b1": 60.0},
                                       40.0, 50.0, 1),
            },
            "ktc_by_player_id": {}, "pick_value_table": {},
            "playoff_weeks_by_league": {"L2024": 15, "L2023": 15},
            "playoff_week_start_by_league": {"L2024": 15, "L2023": 15},
            "phase_by_lwr": {},
            "roster_to_user_by_league": {
                "L2024": {1: "u_a", 2: "u_b"},
                "L2023": {1: "u_a", 2: "u_b"},
            },
            "roster_positions_by_league": {"L2024": ["QB", "BN", "BN"]},
            "positions": {
                "p_qb_a1": "QB", "p_qb_a2": "QB", "p_qb_b1": "QB",
                "p_new1": "RB", "p_new2": "WR",
            },
            "league_name_by_id": {"L2024": "Bros", "L2023": "Bros"},
            "league_season_by_id": {"L2024": 2024, "L2023": 2023},
            "owners": {
                "u_a": {"owner_name": "Alice", "team_name": None, "avatar_url": None},
                "u_b": {"owner_name": "Bob", "team_name": None, "avatar_url": None},
            },
            "owners_display": {"u_a": "Alice", "u_b": "Bob"},
            "warnings": [],
        }

    import app.services.rookie_board_store as rbs_mod

    class _FakeBoardStore:
        def resolve_for_draft(self, draft_id, drafted_on):
            return {"_unused_placeholder": 999.0}

    monkeypatch.setattr(
        rbs_mod.EcrBoardStore, "dynasty_overall",
        classmethod(lambda cls, cache_dir: _FakeBoardStore()))
    monkeypatch.setattr(
        rbs_mod.EcrBoardStore, "dynasty_superflex",
        classmethod(lambda cls, cache_dir: _FakeBoardStore()))

    entry = await GraderService().run(
        client=fake_client,
        current_league_id="L2024",
        progress_cb=AsyncMock(),
        cache_dir=tmp_path,
        _build_trade_history=fake_build,
        _pull_supporting_data=fake_pull,
    )

    by_uid = {r["user_id"]: r for r in entry.draft_needs["2024"]}
    _qb_slot = lambda uid: next(
        s for s in by_uid[uid]["slots"] if s["slot"] == "QB")
    assert by_uid["u_a"]["holes"] == []
    assert by_uid["u_b"]["holes"] == []
    assert _qb_slot("u_a")["margin"] == 20.0
    assert _qb_slot("u_b")["margin"] == 0.0


@pytest.mark.asyncio
async def test_grader_service_gates_draft_needs_to_dynasty_only(tmp_path, monkeypatch):
    """Pre-merge fix I1 (BLOCKER): a keeper league must never run the draft-
    needs reconstruction, and must come out of `GraderService.run` with
    `draft_needs == {}`.

    Identical fixture to `test_grader_service_stamps_draft_needs` above
    (same two-season chain, same completed rookie draft, same u_b-empty-QB
    seed that would otherwise produce a real hole/drafted_into/started
    result) with the ONLY change being `format="keeper"` on both chain
    leagues. `roster_continuity` and `multiyear_history` are both still True
    for this fixture -- `_CONTINUOUS_FORMATS = {"dynasty", "keeper"}` in
    engine/capabilities.py -- so this proves the gate needs its own
    `format == "dynasty"` check and not merely those two booleans: without
    it, keeper leagues sail straight through the same path dynasty does and
    read back a whole-prior-roster reconstruction as "no holes anywhere",
    confidently wrong rather than absent.

    Mutation this catches: dropping the `capabilities.get("format") ==
    "dynasty"` clause from the gate at grader.py (leaving only
    roster_continuity/multiyear_history/_gradeable_draft_classes) makes this
    fixture behave exactly like the dynasty test above and populate
    `draft_needs["2024"]`, failing the `== {}` assertion. Also asserts
    `get_roster_transactions` is never called -- proving the COMPUTE-time
    gate skipped the block entirely, not merely that a downstream filter
    discarded its output.
    """
    fake_chain = [
        MagicMock(league_id="L2024", name="Bros", season=2024,
                  playoff_week_start=15, total_rosters=2, format="keeper"),
        MagicMock(league_id="L2023", name="Bros", season=2023,
                  playoff_week_start=15, total_rosters=2, format="keeper"),
    ]
    fake_client = MagicMock()
    fake_client.walk_league_history = AsyncMock(return_value=fake_chain)
    fake_client.get_players = AsyncMock(return_value={
        "p_qb_a": {"full_name": "QB A", "position": "QB"},
        "p_new1": {"full_name": "Rookie One", "position": "RB"},
        "p_new2": {"full_name": "Rookie Two", "position": "QB"},
    })
    fake_client.get_traded_picks = AsyncMock(return_value=[])
    fake_client.get_roster_transactions = AsyncMock(return_value=[])

    _ROOKIE_DRAFT = {
        "draft_id": "d1", "status": "complete", "season": "2024",
        "type": "snake",
        "settings": {"player_type": 1, "rounds": 1, "teams": 2},
        "last_picked": 1715731200000,  # 2024-05-14, arbitrary
        "start_time": 1715731200000,
    }
    _PICKS = [
        {"player_id": "p_new1", "picked_by": "u_a", "round": 1,
         "draft_slot": 1, "pick_no": 1, "is_keeper": False},
        {"player_id": "p_new2", "picked_by": "u_b", "round": 1,
         "draft_slot": 2, "pick_no": 2, "is_keeper": False},
    ]

    async def _get_drafts(lid):
        return [_ROOKIE_DRAFT] if lid == "L2024" else []

    async def _get_draft_picks(did):
        return _PICKS if did == "d1" else []

    fake_client.get_drafts = AsyncMock(side_effect=_get_drafts)
    fake_client.get_draft_picks = AsyncMock(side_effect=_get_draft_picks)

    async def fake_build(client, current_league_id, player_names, **kwargs):
        return [], {}

    def _mu(players, team, opp, opp_rid, starters=None):
        return {
            "starters": starters or [], "players": players,
            "players_points": {}, "team_points": team,
            "opponent_points": opp, "opponent_roster_id": opp_rid,
        }

    async def fake_pull(client, chain, **kwargs):
        return {
            "matchups": {
                ("L2023", 15, 1): _mu(["p_qb_a"], 50.0, 40.0, 2),
                ("L2023", 15, 2): _mu([], 40.0, 50.0, 1),
                ("L2024", 1, 2): _mu(["p_new2"], 10.0, 5.0, 1,
                                      starters=["p_new2"]),
            },
            "ktc_by_player_id": {}, "pick_value_table": {},
            "playoff_weeks_by_league": {"L2024": 15, "L2023": 15},
            "playoff_week_start_by_league": {"L2024": 15, "L2023": 15},
            "phase_by_lwr": {},
            "roster_to_user_by_league": {
                "L2024": {1: "u_a", 2: "u_b"},
                "L2023": {1: "u_a", 2: "u_b"},
            },
            "roster_positions_by_league": {"L2024": ["QB", "BN"]},
            "positions": {
                "p_qb_a": "QB", "p_new1": "RB", "p_new2": "QB",
            },
            "league_name_by_id": {"L2024": "Bros", "L2023": "Bros"},
            "league_season_by_id": {"L2024": 2024, "L2023": 2023},
            "owners": {
                "u_a": {"owner_name": "Alice", "team_name": None, "avatar_url": None},
                "u_b": {"owner_name": "Bob", "team_name": None, "avatar_url": None},
            },
            "owners_display": {"u_a": "Alice", "u_b": "Bob"},
            "warnings": [],
        }

    import app.services.rookie_board_store as rbs_mod

    class _FakeBoardStore:
        def resolve_for_draft(self, draft_id, drafted_on):
            return {"p_qb_a": 5.0}

    monkeypatch.setattr(
        rbs_mod.EcrBoardStore, "dynasty_overall",
        classmethod(lambda cls, cache_dir: _FakeBoardStore()))
    monkeypatch.setattr(
        rbs_mod.EcrBoardStore, "dynasty_superflex",
        classmethod(lambda cls, cache_dir: _FakeBoardStore()))

    entry = await GraderService().run(
        client=fake_client,
        current_league_id="L2024",
        progress_cb=AsyncMock(),
        cache_dir=tmp_path,
        _build_trade_history=fake_build,
        _pull_supporting_data=fake_pull,
    )

    assert entry.capabilities["format"] == "keeper"
    assert entry.capabilities["roster_continuity"] is True
    assert entry.capabilities["multiyear_history"] is True
    assert entry.draft_needs == {}
    fake_client.get_roster_transactions.assert_not_called()


@pytest.mark.asyncio
async def test_grader_service_reads_sealed_roster_txs_from_cache(tmp_path, monkeypatch):
    """Pre-merge fix I2: a SEALED prior season's roster transactions must be
    read back off the `LeagueRawCache` trade bundle rather than re-fetched
    via the client. The bundle already carries this exact feed
    (`raw_roster_txs`, see test_fetch_league_season_data_produces_raw_
    roster_txs in tests/test_trade_history.py) -- calling the client
    unconditionally would re-walk 18 weeks of transactions per sealed
    league-season on every refresh, forever, which is precisely the doubling
    caching the bundle exists to prevent.

    Same two-season chain as `test_grader_service_stamps_draft_needs`, but a
    real `LeagueRawCache` file for the sealed prior season (L2023) is
    pre-populated exactly as `_fetch_league_season_data` would have written
    it during the trade-history build phase (bypassed here via the
    `_build_trade_history` stub, so nothing else touches the raw cache).
    `get_roster_transactions` must be called for the current season (L2024,
    absent from the pre-populated cache) and must NOT be called for the
    sealed prior season (L2023, served from cache).

    Mutation this catches: reverting the consumer at grader.py to call
    `client.get_roster_transactions(_lid)` unconditionally (bypassing
    `league_cache.read_trade_bundle`) makes L2023 get fetched too, and the
    `called_lids == ["L2024"]` assertion below fails (`["L2023", "L2024"]`
    instead, `sorted()` iteration order is deterministic either way).
    """
    from app.services.league_raw_cache import LeagueRawCache

    fake_chain = [
        MagicMock(league_id="L2024", name="Bros", season=2024,
                  playoff_week_start=15, total_rosters=2, format="dynasty"),
        MagicMock(league_id="L2023", name="Bros", season=2023,
                  playoff_week_start=15, total_rosters=2, format="dynasty"),
    ]
    fake_client = MagicMock()
    fake_client.walk_league_history = AsyncMock(return_value=fake_chain)
    fake_client.get_players = AsyncMock(return_value={
        "p_qb_a": {"full_name": "QB A", "position": "QB"},
        "p_new1": {"full_name": "Rookie One", "position": "RB"},
        "p_new2": {"full_name": "Rookie Two", "position": "QB"},
    })
    fake_client.get_traded_picks = AsyncMock(return_value=[])
    fake_client.get_roster_transactions = AsyncMock(return_value=[])

    # Exactly what _fetch_league_season_data would have written for the
    # sealed 2023 season during the (here-bypassed) trade-history build.
    _cached_bundle = {
        "users": {"u_a": {}, "u_b": {}},
        "roster_to_user": {1: "u_a", 2: "u_b"},
        "raw_trades": [], "raw_drops": [],
        "raw_roster_txs": [{
            "transaction_id": "cached1", "type": "waiver", "status": "complete",
            "adds": {}, "drops": {}, "status_updated": 1700000000000,
        }],
        "drafts": [], "draft_picks_by_draft_id": {},
    }
    LeagueRawCache(cache_dir=tmp_path).write_trade_bundle("L2023", _cached_bundle)

    _ROOKIE_DRAFT = {
        "draft_id": "d1", "status": "complete", "season": "2024",
        "type": "snake",
        "settings": {"player_type": 1, "rounds": 1, "teams": 2},
        "last_picked": 1715731200000,
        "start_time": 1715731200000,
    }
    _PICKS = [
        {"player_id": "p_new1", "picked_by": "u_a", "round": 1,
         "draft_slot": 1, "pick_no": 1, "is_keeper": False},
        {"player_id": "p_new2", "picked_by": "u_b", "round": 1,
         "draft_slot": 2, "pick_no": 2, "is_keeper": False},
    ]

    async def _get_drafts(lid):
        return [_ROOKIE_DRAFT] if lid == "L2024" else []

    async def _get_draft_picks(did):
        return _PICKS if did == "d1" else []

    fake_client.get_drafts = AsyncMock(side_effect=_get_drafts)
    fake_client.get_draft_picks = AsyncMock(side_effect=_get_draft_picks)

    async def fake_build(client, current_league_id, player_names, **kwargs):
        return [], {}

    def _mu(players, team, opp, opp_rid, starters=None):
        return {
            "starters": starters or [], "players": players,
            "players_points": {}, "team_points": team,
            "opponent_points": opp, "opponent_roster_id": opp_rid,
        }

    async def fake_pull(client, chain, **kwargs):
        return {
            "matchups": {
                ("L2023", 15, 1): _mu(["p_qb_a"], 50.0, 40.0, 2),
                ("L2023", 15, 2): _mu([], 40.0, 50.0, 1),
                ("L2024", 1, 2): _mu(["p_new2"], 10.0, 5.0, 1,
                                      starters=["p_new2"]),
            },
            "ktc_by_player_id": {}, "pick_value_table": {},
            "playoff_weeks_by_league": {"L2024": 15, "L2023": 15},
            "playoff_week_start_by_league": {"L2024": 15, "L2023": 15},
            "phase_by_lwr": {},
            "roster_to_user_by_league": {
                "L2024": {1: "u_a", 2: "u_b"},
                "L2023": {1: "u_a", 2: "u_b"},
            },
            "roster_positions_by_league": {"L2024": ["QB", "BN"]},
            "positions": {
                "p_qb_a": "QB", "p_new1": "RB", "p_new2": "QB",
            },
            "league_name_by_id": {"L2024": "Bros", "L2023": "Bros"},
            "league_season_by_id": {"L2024": 2024, "L2023": 2023},
            "owners": {
                "u_a": {"owner_name": "Alice", "team_name": None, "avatar_url": None},
                "u_b": {"owner_name": "Bob", "team_name": None, "avatar_url": None},
            },
            "owners_display": {"u_a": "Alice", "u_b": "Bob"},
            "warnings": [],
        }

    import app.services.rookie_board_store as rbs_mod

    class _FakeBoardStore:
        def resolve_for_draft(self, draft_id, drafted_on):
            return {"p_qb_a": 5.0}

    monkeypatch.setattr(
        rbs_mod.EcrBoardStore, "dynasty_overall",
        classmethod(lambda cls, cache_dir: _FakeBoardStore()))
    monkeypatch.setattr(
        rbs_mod.EcrBoardStore, "dynasty_superflex",
        classmethod(lambda cls, cache_dir: _FakeBoardStore()))

    entry = await GraderService().run(
        client=fake_client,
        current_league_id="L2024",
        progress_cb=AsyncMock(),
        cache_dir=tmp_path,
        _build_trade_history=fake_build,
        _pull_supporting_data=fake_pull,
    )

    called_lids = [c.args[0] for c in fake_client.get_roster_transactions.call_args_list]
    assert called_lids == ["L2024"]
    # Still produces a real result -- the cache read didn't silently starve
    # the reconstruction of data.
    assert "2024" in entry.draft_needs
    assert {r["user_id"] for r in entry.draft_needs["2024"]} == {"u_a", "u_b"}


@pytest.mark.asyncio
async def test_grader_service_excludes_keeper_picks_from_picks_by_owner(tmp_path, monkeypatch):
    """Pre-merge fix I3: a keeper pick must never count as "drafted into" a
    hole. A keeper is a player the owner already had going into the draft --
    if that player sits below the replacement line he is what CREATES the
    hole, and crediting him with having "drafted into" it (via the keeper
    pick that merely re-declares him) has the causality backwards. Auction
    picks are deliberately NOT filtered by this same guard (`gradeable` is
    an orthogonal axis -- see the comment at the filter site) so this test
    is specifically about `is_keeper`, not "any non-scored pick".

    Identical fixture to `test_grader_service_stamps_draft_needs` above
    (including its C1 fix, 2026-08-17: u_b's hole comes from a genuinely
    below-replacement QB and real board arithmetic, not the old
    empty-slot-is-an-unconditional-hole sentinel), with the ONLY change
    being u_b's pick (`p_new2`) flagged `is_keeper: True`.

    Mutation this catches: removing the `if _row.get("is_keeper"): continue`
    guard from grader.py's `_picks_by_owner` loop makes u_b's keeper pick
    count again, flipping `by_uid["u_b"]["drafted_into"]` from `[]` back to
    `["QB"]` (and `started`/`drafted_into_count` from `0`/`0` back to
    `1`/`1`) -- the exact values the dynasty-fixture test above asserts FOR
    a non-keeper pick, which is what proves this guard is the difference.
    `holes == ["QB"]` is unchanged by this fix on purpose: filtering
    picks_by_owner doesn't touch roster_asof's reconstruction, only which
    picks may claim credit against it.
    """
    fake_chain = [
        MagicMock(league_id="L2024", name="Bros", season=2024,
                  playoff_week_start=15, total_rosters=2, format="dynasty"),
        MagicMock(league_id="L2023", name="Bros", season=2023,
                  playoff_week_start=15, total_rosters=2, format="dynasty"),
    ]
    fake_client = MagicMock()
    fake_client.walk_league_history = AsyncMock(return_value=fake_chain)
    fake_client.get_players = AsyncMock(return_value={
        "p_qb_a": {"full_name": "QB A", "position": "QB"},
        "p_qb_filler": {"full_name": "QB Filler", "position": "QB"},
        "p_qb_b": {"full_name": "QB B", "position": "QB"},
        "p_new1": {"full_name": "Rookie One", "position": "RB"},
        "p_new2": {"full_name": "Rookie Two", "position": "QB"},
    })
    fake_client.get_traded_picks = AsyncMock(return_value=[])
    fake_client.get_roster_transactions = AsyncMock(return_value=[])

    _ROOKIE_DRAFT = {
        "draft_id": "d1", "status": "complete", "season": "2024",
        "type": "snake",
        "settings": {"player_type": 1, "rounds": 1, "teams": 2},
        "last_picked": 1715731200000,
        "start_time": 1715731200000,
    }
    _PICKS = [
        {"player_id": "p_new1", "picked_by": "u_a", "round": 1,
         "draft_slot": 1, "pick_no": 1, "is_keeper": False},
        # The only change from test_grader_service_stamps_draft_needs:
        # u_b's pick is now a keeper.
        {"player_id": "p_new2", "picked_by": "u_b", "round": 1,
         "draft_slot": 2, "pick_no": 2, "is_keeper": True},
    ]

    async def _get_drafts(lid):
        return [_ROOKIE_DRAFT] if lid == "L2024" else []

    async def _get_draft_picks(did):
        return _PICKS if did == "d1" else []

    fake_client.get_drafts = AsyncMock(side_effect=_get_drafts)
    fake_client.get_draft_picks = AsyncMock(side_effect=_get_draft_picks)

    async def fake_build(client, current_league_id, player_names, **kwargs):
        return [], {}

    def _mu(players, team, opp, opp_rid, starters=None):
        return {
            "starters": starters or [], "players": players,
            "players_points": {}, "team_points": team,
            "opponent_points": opp, "opponent_roster_id": opp_rid,
        }

    async def fake_pull(client, chain, **kwargs):
        return {
            # Same C1-fixed shape as test_grader_service_stamps_draft_needs:
            # u_a's clear-best QB plus bench-only pool depth
            # (p_qb_filler); u_b's genuinely-worst-ECR QB (p_qb_b) is a
            # real hole by board arithmetic.
            "matchups": {
                ("L2023", 15, 1): _mu(
                    ["p_qb_a", "p_qb_filler"], 50.0, 40.0, 2),
                ("L2023", 15, 2): _mu(["p_qb_b"], 40.0, 50.0, 1),
                ("L2024", 1, 2): _mu(["p_new2"], 10.0, 5.0, 1,
                                      starters=["p_new2"]),
            },
            "ktc_by_player_id": {}, "pick_value_table": {},
            "playoff_weeks_by_league": {"L2024": 15, "L2023": 15},
            "playoff_week_start_by_league": {"L2024": 15, "L2023": 15},
            "phase_by_lwr": {},
            "roster_to_user_by_league": {
                "L2024": {1: "u_a", 2: "u_b"},
                "L2023": {1: "u_a", 2: "u_b"},
            },
            "roster_positions_by_league": {"L2024": ["QB", "BN"]},
            "positions": {
                "p_qb_a": "QB", "p_qb_filler": "QB", "p_qb_b": "QB",
                "p_new1": "RB", "p_new2": "QB",
            },
            "league_name_by_id": {"L2024": "Bros", "L2023": "Bros"},
            "league_season_by_id": {"L2024": 2024, "L2023": 2023},
            "owners": {
                "u_a": {"owner_name": "Alice", "team_name": None, "avatar_url": None},
                "u_b": {"owner_name": "Bob", "team_name": None, "avatar_url": None},
            },
            "owners_display": {"u_a": "Alice", "u_b": "Bob"},
            "warnings": [],
        }

    import app.services.rookie_board_store as rbs_mod

    class _FakeBoardStore:
        def resolve_for_draft(self, draft_id, drafted_on):
            return {"p_qb_a": 5.0, "p_qb_filler": 10.0, "p_qb_b": 999.0}

    monkeypatch.setattr(
        rbs_mod.EcrBoardStore, "dynasty_overall",
        classmethod(lambda cls, cache_dir: _FakeBoardStore()))
    monkeypatch.setattr(
        rbs_mod.EcrBoardStore, "dynasty_superflex",
        classmethod(lambda cls, cache_dir: _FakeBoardStore()))

    entry = await GraderService().run(
        client=fake_client,
        current_league_id="L2024",
        progress_cb=AsyncMock(),
        cache_dir=tmp_path,
        _build_trade_history=fake_build,
        _pull_supporting_data=fake_pull,
    )

    by_uid = {r["user_id"]: r for r in entry.draft_needs["2024"]}
    assert by_uid["u_b"]["holes"] == ["QB"]
    assert by_uid["u_b"]["drafted_into"] == []
    assert by_uid["u_b"]["started"] == 0
    assert by_uid["u_b"]["drafted_into_count"] == 0


@pytest.mark.asyncio
async def test_grader_service_sorts_picks_by_owner_by_pick_no(tmp_path, monkeypatch):
    """Final-review Finding 3: the capacity-capped `drafted_into`/`started`
    credit in `engine/draft_needs.py` walks each owner's picks in DRAFT
    ORDER and stops crediting once a position's open-hole capacity is
    exhausted -- so WHICH pick gets the credit depends on `_picks_by_owner`
    actually being in pick order. Nothing enforced that upstream of this
    fix; `drafted_picks` was walked in whatever order the list happened to
    arrive in.

    Identical two-season dynasty fixture to `test_grader_service_stamps_
    draft_needs`, except u_b has exactly ONE QB hole (capacity 1, same
    board arithmetic as that test) and makes TWO QB picks instead of one:
    `p_new2` (pick_no=2, never started) and `p_new3` (pick_no=1, started
    once). They are handed to `get_draft_picks` in REVERSED order --
    `p_new2` (the later, non-starting pick) first, `p_new3` (the earlier,
    starting pick) second -- so a naive list-order walk would credit
    `p_new2` and read `started=0`, while a pick_no-sorted walk credits
    `p_new3` (the true first pick into the hole) and reads `started=1`.

    Mutation this catches: dropping the `sorted(drafted_picks, key=...
    pick_no...)` in grader.py's `_picks_by_owner` loop back to a bare
    `for _row in drafted_picks:` flips `started` from `1` back to `0` here
    (the credited pick's `games_started` differs between the two, but
    `drafted_into`/`drafted_into_count` do not -- both picks are QB, so
    that reading is identical either way and cannot catch this on its
    own).
    """
    fake_chain = [
        MagicMock(league_id="L2024", name="Bros", season=2024,
                  playoff_week_start=15, total_rosters=2, format="dynasty"),
        MagicMock(league_id="L2023", name="Bros", season=2023,
                  playoff_week_start=15, total_rosters=2, format="dynasty"),
    ]
    fake_client = MagicMock()
    fake_client.walk_league_history = AsyncMock(return_value=fake_chain)
    fake_client.get_players = AsyncMock(return_value={
        "p_qb_a": {"full_name": "QB A", "position": "QB"},
        "p_qb_filler": {"full_name": "QB Filler", "position": "QB"},
        "p_qb_b": {"full_name": "QB B", "position": "QB"},
        "p_new1": {"full_name": "Rookie One", "position": "RB"},
        "p_new2": {"full_name": "Rookie Two", "position": "QB"},
        "p_new3": {"full_name": "Rookie Three", "position": "QB"},
    })
    fake_client.get_traded_picks = AsyncMock(return_value=[])
    fake_client.get_roster_transactions = AsyncMock(return_value=[])

    _ROOKIE_DRAFT = {
        "draft_id": "d1", "status": "complete", "season": "2024",
        "type": "snake",
        "settings": {"player_type": 1, "rounds": 2, "teams": 2},
        "last_picked": 1715731200000,
        "start_time": 1715731200000,
    }
    _PICKS = [
        {"player_id": "p_new1", "picked_by": "u_a", "round": 1,
         "draft_slot": 1, "pick_no": 1, "is_keeper": False},
        # Reversed relative to pick_no on purpose (see docstring): the
        # non-starting, LATER pick (pick_no=2) is listed first here, and
        # the starting, EARLIER pick (pick_no=1) is listed second.
        {"player_id": "p_new2", "picked_by": "u_b", "round": 2,
         "draft_slot": 2, "pick_no": 3, "is_keeper": False},
        {"player_id": "p_new3", "picked_by": "u_b", "round": 1,
         "draft_slot": 2, "pick_no": 2, "is_keeper": False},
    ]

    async def _get_drafts(lid):
        return [_ROOKIE_DRAFT] if lid == "L2024" else []

    async def _get_draft_picks(did):
        return _PICKS if did == "d1" else []

    fake_client.get_drafts = AsyncMock(side_effect=_get_drafts)
    fake_client.get_draft_picks = AsyncMock(side_effect=_get_draft_picks)

    async def fake_build(client, current_league_id, player_names, **kwargs):
        return [], {}

    def _mu(players, team, opp, opp_rid, starters=None):
        return {
            "starters": starters or [], "players": players,
            "players_points": {}, "team_points": team,
            "opponent_points": opp, "opponent_roster_id": opp_rid,
        }

    async def fake_pull(client, chain, **kwargs):
        return {
            "matchups": {
                ("L2023", 15, 1): _mu(
                    ["p_qb_a", "p_qb_filler"], 50.0, 40.0, 2),
                ("L2023", 15, 2): _mu(["p_qb_b"], 40.0, 50.0, 1),
                # Only p_new3 (the true FIRST pick, pick_no=2) ever starts.
                # p_new2 (pick_no=3) never appears in a starters list.
                ("L2024", 1, 2): _mu(["p_new3"], 10.0, 5.0, 1,
                                      starters=["p_new3"]),
            },
            "ktc_by_player_id": {}, "pick_value_table": {},
            "playoff_weeks_by_league": {"L2024": 15, "L2023": 15},
            "playoff_week_start_by_league": {"L2024": 15, "L2023": 15},
            "phase_by_lwr": {},
            "roster_to_user_by_league": {
                "L2024": {1: "u_a", 2: "u_b"},
                "L2023": {1: "u_a", 2: "u_b"},
            },
            "roster_positions_by_league": {"L2024": ["QB", "BN"]},
            "positions": {
                "p_qb_a": "QB", "p_qb_filler": "QB", "p_qb_b": "QB",
                "p_new1": "RB", "p_new2": "QB", "p_new3": "QB",
            },
            "league_name_by_id": {"L2024": "Bros", "L2023": "Bros"},
            "league_season_by_id": {"L2024": 2024, "L2023": 2023},
            "owners": {
                "u_a": {"owner_name": "Alice", "team_name": None, "avatar_url": None},
                "u_b": {"owner_name": "Bob", "team_name": None, "avatar_url": None},
            },
            "owners_display": {"u_a": "Alice", "u_b": "Bob"},
            "warnings": [],
        }

    import app.services.rookie_board_store as rbs_mod

    class _FakeBoardStore:
        def resolve_for_draft(self, draft_id, drafted_on):
            return {"p_qb_a": 5.0, "p_qb_filler": 10.0, "p_qb_b": 999.0}

    monkeypatch.setattr(
        rbs_mod.EcrBoardStore, "dynasty_overall",
        classmethod(lambda cls, cache_dir: _FakeBoardStore()))
    monkeypatch.setattr(
        rbs_mod.EcrBoardStore, "dynasty_superflex",
        classmethod(lambda cls, cache_dir: _FakeBoardStore()))

    entry = await GraderService().run(
        client=fake_client,
        current_league_id="L2024",
        progress_cb=AsyncMock(),
        cache_dir=tmp_path,
        _build_trade_history=fake_build,
        _pull_supporting_data=fake_pull,
    )

    by_uid = {r["user_id"]: r for r in entry.draft_needs["2024"]}
    # u_b's single QB hole has capacity for exactly one credited pick. Sorted
    # by pick_no, that's p_new3 (pick_no=2, the true first QB pick), which
    # started -- so `started` is 1, not 0. A list-order walk would instead
    # credit p_new2 (pick_no=3, listed first in `_PICKS`), which never
    # started.
    assert by_uid["u_b"]["holes"] == ["QB"]
    assert by_uid["u_b"]["drafted_into"] == ["QB"]
    assert by_uid["u_b"]["drafted_into_count"] == 1
    assert by_uid["u_b"]["started"] == 1


@pytest.mark.asyncio
async def test_grader_service_skips_ungradeable_newest_class_for_needs(tmp_path, monkeypatch):
    """Pre-merge fix M1: "newest GRADEABLE class" is what the design spec,
    the ChainCacheEntry.draft_needs docstring, and grader.py's own comment
    all promise -- only implemented as `max(draft_classes, key=season)` with
    no gradeable filter. Only bites a league whose newest draft is an
    auction (`gradeable=False`, `pick_no` is chronological rather than
    positional, so a slot-vs-hole comparison against it is noise).

    Three-season dynasty chain: L2024 (newest by season, an AUCTION rookie
    draft -- gradeable=False), L2023 (a real snake rookie draft --
    gradeable=True), L2022 (origin season, no draft, present only to seed
    L2023's draft-day roster from its final matchup week).

    Mutation this catches: reverting `_gradeable_draft_classes = [c for c in
    draft_classes if c.gradeable]` back to using `draft_classes` directly at
    the `max(..., key=lambda c: c.season)` call selects the 2024 auction as
    `_needs_class` instead, and `entry.draft_needs` comes back keyed
    `"2024"` instead of `"2023"` (or the pipeline errors trying to treat an
    auction's chronological `pick_no` as a positional slot delta).
    """
    fake_chain = [
        MagicMock(league_id="L2024", name="Bros", season=2024,
                  playoff_week_start=15, total_rosters=2, format="dynasty"),
        MagicMock(league_id="L2023", name="Bros", season=2023,
                  playoff_week_start=15, total_rosters=2, format="dynasty"),
        MagicMock(league_id="L2022", name="Bros", season=2022,
                  playoff_week_start=15, total_rosters=2, format="dynasty"),
    ]
    fake_client = MagicMock()
    fake_client.walk_league_history = AsyncMock(return_value=fake_chain)
    fake_client.get_players = AsyncMock(return_value={
        "p_l23_a": {"full_name": "L23 A", "position": "RB"},
        "p_l23_b": {"full_name": "L23 B", "position": "QB"},
    })
    fake_client.get_traded_picks = AsyncMock(return_value=[])
    fake_client.get_roster_transactions = AsyncMock(return_value=[])

    _AUCTION_DRAFT_24 = {
        "draft_id": "auction1", "status": "complete", "season": "2024",
        "type": "auction",
        "settings": {"player_type": 1, "rounds": 1, "teams": 2},
        "last_picked": 1715731200000, "start_time": 1715731200000,
    }
    _ROOKIE_DRAFT_23 = {
        "draft_id": "d2023", "status": "complete", "season": "2023",
        "type": "snake",
        "settings": {"player_type": 1, "rounds": 1, "teams": 2},
        "last_picked": 1684022400000,  # 2023-05-14, arbitrary
        "start_time": 1684022400000,
    }
    _PICKS_2023 = [
        {"player_id": "p_l23_a", "picked_by": "u_a", "round": 1,
         "draft_slot": 1, "pick_no": 1, "is_keeper": False},
        {"player_id": "p_l23_b", "picked_by": "u_b", "round": 1,
         "draft_slot": 2, "pick_no": 2, "is_keeper": False},
    ]

    async def _get_drafts(lid):
        if lid == "L2024":
            return [_AUCTION_DRAFT_24]
        if lid == "L2023":
            return [_ROOKIE_DRAFT_23]
        return []

    async def _get_draft_picks(did):
        if did == "d2023":
            return _PICKS_2023
        return []

    fake_client.get_drafts = AsyncMock(side_effect=_get_drafts)
    fake_client.get_draft_picks = AsyncMock(side_effect=_get_draft_picks)

    async def fake_build(client, current_league_id, player_names, **kwargs):
        return [], {}

    def _mu(players, team, opp, opp_rid, starters=None):
        return {
            "starters": starters or [], "players": players,
            "players_points": {}, "team_points": team,
            "opponent_points": opp, "opponent_roster_id": opp_rid,
        }

    async def fake_pull(client, chain, **kwargs):
        return {
            # L2022's final week seeds L2023's draft-day roster (empty for
            # both owners -- irrelevant to this test, which only asserts on
            # WHICH season got reconstructed, not the hole content).
            "matchups": {
                ("L2022", 15, 1): _mu([], 50.0, 40.0, 2),
                ("L2022", 15, 2): _mu([], 40.0, 50.0, 1),
            },
            "ktc_by_player_id": {}, "pick_value_table": {},
            "playoff_weeks_by_league": {"L2024": 15, "L2023": 15, "L2022": 15},
            "playoff_week_start_by_league": {"L2024": 15, "L2023": 15, "L2022": 15},
            "phase_by_lwr": {},
            "roster_to_user_by_league": {
                "L2024": {1: "u_a", 2: "u_b"},
                "L2023": {1: "u_a", 2: "u_b"},
                "L2022": {1: "u_a", 2: "u_b"},
            },
            "roster_positions_by_league": {"L2023": ["QB", "BN"]},
            "positions": {"p_l23_a": "RB", "p_l23_b": "QB"},
            "league_name_by_id": {"L2024": "Bros", "L2023": "Bros", "L2022": "Bros"},
            "league_season_by_id": {"L2024": 2024, "L2023": 2023, "L2022": 2022},
            "owners": {
                "u_a": {"owner_name": "Alice", "team_name": None, "avatar_url": None},
                "u_b": {"owner_name": "Bob", "team_name": None, "avatar_url": None},
            },
            "owners_display": {"u_a": "Alice", "u_b": "Bob"},
            "warnings": [],
        }

    import app.services.rookie_board_store as rbs_mod

    class _FakeBoardStore:
        def resolve_for_draft(self, draft_id, drafted_on):
            return {"p_qb_a": 5.0}

    monkeypatch.setattr(
        rbs_mod.EcrBoardStore, "dynasty_overall",
        classmethod(lambda cls, cache_dir: _FakeBoardStore()))
    monkeypatch.setattr(
        rbs_mod.EcrBoardStore, "dynasty_superflex",
        classmethod(lambda cls, cache_dir: _FakeBoardStore()))

    entry = await GraderService().run(
        client=fake_client,
        current_league_id="L2024",
        progress_cb=AsyncMock(),
        cache_dir=tmp_path,
        _build_trade_history=fake_build,
        _pull_supporting_data=fake_pull,
    )

    assert "2023" in entry.draft_needs
    assert "2024" not in entry.draft_needs


# ---------------------------------------------------------------------------
# M6 (2026-08-18) — the roster reconstruction rewinds to the draft's OPEN, not
# its close. A slow-clock rookie draft runs for days (83h on the reference
# league in both 2026 and 2025, 47h in 2024) and what managers do during those
# days is clear bench room for the picks they are about to make: 17 drops
# across 7 of 12 rosters inside the 2026 window, Najee Harris / Cooper Kupp /
# Brandon Aiyuk / Mike Evans / Jaylen Waddle among them. Rewinding to
# `last_picked` applied that cleanup BEFORE reading the holes, so the roster
# came out thinner than the owner ever had it.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_grader_service_draft_needs_rewind_to_the_drafts_open(
        tmp_path, monkeypatch):
    """Mutation this catches: `as_of=_draft_start_dt` reverting to
    `as_of=_last_picked_dt` in grader.py's `roster_asof` call.

    THREE owners, not two, and the difference is load-bearing. With one QB
    starter slot each, `demand["QB"]` equals the owner count, and the
    replacement line is the demand-th best QB in the league pool. At two
    owners the line is the 2nd-best, so the only way an owner can clear it is
    to HOLD the 2nd-best — the line lands on that owner's own starter and the
    "no hole" reading is true by construction under any implementation. A
    third owner pushes the line onto `p_qb_filler`, a BENCH player nobody
    starts, so u_b clears it by a real margin.

    The window: the draft opens at T0 and closes 83h later, and u_b drops
    `p_qb_mid` — his starter — 24h in. Two independent readings flip on which
    instant is used, in OPPOSITE directions, which is what makes this a fact
    about the cutoff rather than about one owner:

      at the OPEN   pool [-5, -10, -30, -40, -999], line = 3rd = -30 (bench
                    filler). u_b starts p_qb_mid (-10): clears, NO hole.
                    u_c starts p_qb_c (-40): below, HOLE.
      at the CLOSE  p_qb_mid is gone. pool [-5, -30, -40, -999], line = 3rd =
                    -40. u_b now starts p_qb_scrub (-999): HOLE. u_c's -40 is
                    exactly AT the line: no longer a hole.

    So reading the close doesn't merely add a hole — it moves one from u_c to
    u_b. A fixture where only u_b changed would still pass a mutation that
    holed everybody.
    """
    fake_chain = [
        MagicMock(league_id="L2024", name="Bros", season=2024,
                  playoff_week_start=15, total_rosters=3, format="dynasty"),
        MagicMock(league_id="L2023", name="Bros", season=2023,
                  playoff_week_start=15, total_rosters=3, format="dynasty"),
    ]
    fake_client = MagicMock()
    fake_client.walk_league_history = AsyncMock(return_value=fake_chain)
    fake_client.get_players = AsyncMock(return_value={
        "p_qb_a": {"full_name": "QB A", "position": "QB"},
        "p_qb_filler": {"full_name": "QB Filler", "position": "QB"},
        "p_qb_mid": {"full_name": "QB Mid", "position": "QB"},
        "p_qb_scrub": {"full_name": "QB Scrub", "position": "QB"},
        "p_qb_c": {"full_name": "QB C", "position": "QB"},
        "p_new1": {"full_name": "Rookie One", "position": "RB"},
    })
    fake_client.get_traded_picks = AsyncMock(return_value=[])

    T0 = 1715731200000            # draft opens
    CLOSE = T0 + 83 * 3600 * 1000  # 83 hours later, the real measured span
    MID = T0 + 24 * 3600 * 1000    # u_b clears bench room, 24h in

    # The one transaction the whole test turns on. Inside the window, so the
    # OPEN excludes it and the CLOSE applies it.
    fake_client.get_roster_transactions = AsyncMock(return_value=[{
        "type": "free_agent", "status": "complete",
        "status_updated": MID,
        "adds": None, "drops": {"p_qb_mid": 2},
    }])

    _ROOKIE_DRAFT = {
        "draft_id": "d1", "status": "complete", "season": "2024",
        "type": "snake",
        "settings": {"player_type": 1, "rounds": 1, "teams": 3},
        "start_time": T0,
        "last_picked": CLOSE,
    }
    _PICKS = [
        {"player_id": "p_new1", "picked_by": "u_a", "round": 1,
         "draft_slot": 1, "pick_no": 1, "is_keeper": False},
    ]

    async def _get_drafts(lid):
        return [_ROOKIE_DRAFT] if lid == "L2024" else []

    async def _get_draft_picks(did):
        return _PICKS if did == "d1" else []

    fake_client.get_drafts = AsyncMock(side_effect=_get_drafts)
    fake_client.get_draft_picks = AsyncMock(side_effect=_get_draft_picks)

    async def fake_build(client, current_league_id, player_names, **kwargs):
        return [], {}

    def _mu(players, team, opp, opp_rid, starters=None):
        return {
            "starters": starters or [], "players": players,
            "players_points": {}, "team_points": team,
            "opponent_points": opp, "opponent_roster_id": opp_rid,
        }

    async def fake_pull(client, chain, **kwargs):
        return {
            "matchups": {
                # 2023's final played week -- the seed. u_b holds p_qb_mid
                # here, which is the whole point: he went INTO the draft
                # with him.
                ("L2023", 15, 1): _mu(["p_qb_a", "p_qb_filler"], 50.0, 40.0, 2),
                ("L2023", 15, 2): _mu(["p_qb_mid", "p_qb_scrub"], 40.0, 50.0, 1),
                ("L2023", 15, 3): _mu(["p_qb_c"], 45.0, 45.0, 1),
            },
            "ktc_by_player_id": {}, "pick_value_table": {},
            "playoff_weeks_by_league": {"L2024": 15, "L2023": 15},
            "playoff_week_start_by_league": {"L2024": 15, "L2023": 15},
            "phase_by_lwr": {},
            "roster_to_user_by_league": {
                "L2024": {1: "u_a", 2: "u_b", 3: "u_c"},
                "L2023": {1: "u_a", 2: "u_b", 3: "u_c"},
            },
            "roster_positions_by_league": {"L2024": ["QB", "BN"]},
            "positions": {
                "p_qb_a": "QB", "p_qb_filler": "QB", "p_qb_mid": "QB",
                "p_qb_scrub": "QB", "p_qb_c": "QB", "p_new1": "RB",
            },
            "league_name_by_id": {"L2024": "Bros", "L2023": "Bros"},
            "league_season_by_id": {"L2024": 2024, "L2023": 2023},
            "owners": {
                "u_a": {"owner_name": "Alice", "team_name": None, "avatar_url": None},
                "u_b": {"owner_name": "Bob", "team_name": None, "avatar_url": None},
                "u_c": {"owner_name": "Carol", "team_name": None, "avatar_url": None},
            },
            "owners_display": {"u_a": "Alice", "u_b": "Bob", "u_c": "Carol"},
            "warnings": [],
        }

    import app.services.rookie_board_store as rbs_mod

    class _FakeBoardStore:
        def resolve_for_draft(self, draft_id, drafted_on):
            return {"p_qb_a": 5.0, "p_qb_mid": 10.0, "p_qb_filler": 30.0,
                    "p_qb_c": 40.0, "p_qb_scrub": 999.0}

    monkeypatch.setattr(
        rbs_mod.EcrBoardStore, "dynasty_overall",
        classmethod(lambda cls, cache_dir: _FakeBoardStore()))
    monkeypatch.setattr(
        rbs_mod.EcrBoardStore, "dynasty_superflex",
        classmethod(lambda cls, cache_dir: _FakeBoardStore()))

    entry = await GraderService().run(
        client=fake_client,
        current_league_id="L2024",
        progress_cb=AsyncMock(),
        cache_dir=tmp_path,
        _build_trade_history=fake_build,
        _pull_supporting_data=fake_pull,
    )

    by_uid = {r["user_id"]: r for r in entry.draft_needs["2024"]}

    # u_b went in holding p_qb_mid and cut him mid-draft. Reading the close
    # would credit that cut to his "going in" roster and manufacture a hole.
    assert by_uid["u_b"]["holes"] == [], (
        "u_b held a clearing QB when the draft OPENED; a hole here means the "
        "reconstruction applied his mid-draft cleanup drop")
    # And the hole that genuinely existed at the open must still be reported.
    assert by_uid["u_c"]["holes"] == ["QB"]
    assert by_uid["u_a"]["holes"] == []
