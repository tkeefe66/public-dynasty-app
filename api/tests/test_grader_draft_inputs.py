import datetime as _dt
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.adp_snapshot_store import AdpSnapshotStore
from app.services.grader import GraderService
from sleeper_dynasty.engine.draft_class import build_draft_classes, build_draft_picks
from sleeper_dynasty.engine.draft_results import build_drafted_pick_results


def _drafts(player_type, season=2026):
    return {"lg": [{
        "draft_id": "d1", "league_id": "lg", "season": str(season),
        "status": "complete", "type": "snake",
        "settings": {"rounds": 2, "teams": 2, "player_type": player_type},
    }]}


def _picks():
    return {"d1": [
        {"round": 1, "draft_slot": 1, "pick_no": 1, "player_id": "p1",
         "picked_by": "u1", "is_keeper": None},
        {"round": 1, "draft_slot": 2, "pick_no": 2, "player_id": "p2",
         "picked_by": "u2", "is_keeper": True},
    ]}


def _rows(classes, adp=None, projected=None):
    """``adp`` is a flat player_id -> ADP map for these single-draft ("d1")
    fixtures; wrapped into the draft-keyed shape build_drafted_pick_results
    now expects."""
    picks = build_draft_picks(
        classes=classes, picks_by_draft_id=_picks(),
        roster_to_user_by_league={})
    return build_drafted_pick_results(
        picks,
        ktc_floats={}, normalized_name_by_pid={},
        names={"p1": "Player One", "p2": "Player Two"},
        positions={"p1": "RB", "p2": "WR"}, extremes_by_name={},
        acquired_set=set(), points_fn=lambda *_: 0.0, games_fn=lambda *_: 0,
        current_holders={}, traded_away_set=set(),
        adp_by_draft={"d1": adp} if adp is not None else None,
        projected_by_player=projected,
    )


def test_redraft_rows_carry_adp_delta_and_projection():
    classes = build_draft_classes(
        drafts_by_league=_drafts(0), league_format="redraft",
        origin_season=2026)
    rows = _rows(classes, adp={"p1": 12.0}, projected={"p1": 210.5})
    row = next(r for r in rows if r["player_id"] == "p1")
    assert row["adp"] == pytest.approx(12.0)
    assert row["adp_delta"] == pytest.approx(-11.0)  # taken 1st, market said 12
    assert row["projected_points"] == pytest.approx(210.5)
    assert row["draft_kind"] == "full"


def test_unmatched_player_has_null_adp_not_zero():
    classes = build_draft_classes(
        drafts_by_league=_drafts(0), league_format="redraft",
        origin_season=2026)
    rows = _rows(classes, adp={})
    assert all(r["adp"] is None and r["adp_delta"] is None for r in rows)


def test_keeper_flag_survives_into_the_rows():
    classes = build_draft_classes(
        drafts_by_league=_drafts(0), league_format="redraft",
        origin_season=2026)
    rows = _rows(classes)
    assert {r["player_id"]: r["is_keeper"] for r in rows} == {
        "p1": False, "p2": True}


def test_auction_rows_get_null_adp_even_when_matched():
    """Auction pick_no is chronological, not positional — comparing it to ADP
    would be noise, so a non-gradeable pick's adp/adp_delta must stay null
    even when the player has a real ADP entry available."""
    classes = build_draft_classes(
        drafts_by_league={"lg": [{
            "draft_id": "d1", "league_id": "lg", "season": "2026",
            "status": "complete", "type": "auction",
            "settings": {"rounds": 2, "teams": 2, "player_type": 0},
        }]},
        league_format="redraft", origin_season=2026)
    assert classes[0].gradeable is False
    rows = _rows(classes, adp={"p1": 12.0}, projected={"p1": 210.5})
    row = next(r for r in rows if r["player_id"] == "p1")
    assert row["adp"] is None
    assert row["adp_delta"] is None
    assert row["projected_points"] == pytest.approx(210.5)  # unaffected


def test_redraft_year_one_is_ingested():
    """The draft happening in the chain's origin season is the graded event in
    a redraft league, not a startup to discard."""
    classes = build_draft_classes(
        drafts_by_league=_drafts(0, season=2026), league_format="redraft",
        origin_season=2026)
    assert len(classes) == 1
    assert len(_rows(classes)) == 2


# --- Grader-level wiring: the ADP/capture block inside GraderService.run,
# exercised through the actual refresh path rather than by calling the pure
# engine functions directly. Everything above this line tests draft_results
# in isolation; nothing above proves the grader wires it correctly. ---

def _league(league_id: str, season: int, *, fmt: str = "redraft",
            superflex: bool = False):
    return SimpleNamespace(
        league_id=league_id, season=season, name="Test League",
        total_rosters=2, playoff_week_start=15, status="complete",
        playoff_round_type=0, format=fmt,
        scoring_settings={"rec": 1.0},  # PPR -> adp_ppr / pts_ppr
        roster_positions=(
            ["QB", "RB", "WR", "TE", "SUPER_FLEX", "BN"] if superflex
            else ["QB", "RB", "WR", "TE", "FLEX", "BN"]
        ),
    )


def _epoch_ms(d: _dt.date) -> int:
    """Epoch milliseconds for midnight UTC on ``d``, matching how Sleeper's
    ``last_picked`` and the grader's UTC-date conversion both work."""
    return int(_dt.datetime.combine(
        d, _dt.time.min, tzinfo=_dt.timezone.utc).timestamp() * 1000)


_TODAY = _dt.datetime.now(_dt.timezone.utc).date()


def _draft_dict(draft_id: str, league_id: str, season: int,
                 *, last_picked: _dt.date | None = _TODAY):
    """``last_picked`` defaults to "today" (real UTC date) so a completed
    draft in these fixtures resolves against the daily snapshot this same
    refresh just captured — mirroring a draft that just finished. Pass an
    explicit earlier date to model a draft that happened before our
    snapshot history begins."""
    d = {
        "draft_id": draft_id, "league_id": league_id, "season": str(season),
        "status": "complete", "type": "snake",
        "settings": {"rounds": 1, "teams": 2, "player_type": 0},
    }
    if last_picked is not None:
        d["last_picked"] = _epoch_ms(last_picked)
    return d


def _pick_dict(player_id: str, *, pick_no: int = 1, uid: str = "u1"):
    return {"round": 1, "draft_slot": pick_no, "pick_no": pick_no,
            "player_id": player_id, "picked_by": uid, "is_keeper": False}


def _supporting_for(league_seasons: dict[str, int], *, matchups: dict | None = None) -> dict:
    return {
        "matchups": matchups or {}, "ktc_by_player_id": {}, "pick_value_table": {},
        "playoff_weeks_by_league": {lid: 15 for lid in league_seasons},
        "roster_to_user_by_league": {lid: {1: "u1", 2: "u2"} for lid in league_seasons},
        "league_name_by_id": {lid: "Test League" for lid in league_seasons},
        "league_season_by_id": dict(league_seasons),
        "owners": {
            "u1": {"owner_name": "Alice", "team_name": None, "avatar_url": None},
            "u2": {"owner_name": "Bob", "team_name": None, "avatar_url": None},
        },
        "warnings": [],
        "phase_by_lwr": {},
        "playoff_week_start_by_league": {lid: 15 for lid in league_seasons},
        "positions": {"p1": "RB", "p_old": "WR"},
    }


class _FakeDraftClient:
    """Minimal async Sleeper-shaped client covering exactly what the
    draft-inputs + ADP blocks in GraderService.run call."""

    def __init__(self, chain, drafts_by_league, picks_by_draft_id, projections,
                 *, raise_on_projections=False, raise_on_traded_picks=False):
        self._chain = chain
        self._drafts_by_league = drafts_by_league
        self._picks_by_draft_id = picks_by_draft_id
        self._projections = projections
        self._raise_on_projections = raise_on_projections
        self._raise_on_traded_picks = raise_on_traded_picks

    async def walk_league_history(self, league_id):
        return self._chain

    async def get_players(self):
        return {
            "p1": {"full_name": "Player One", "position": "RB"},
            "p_old": {"full_name": "Old Player", "position": "WR"},
        }

    async def get_traded_picks(self, league_id):
        if self._raise_on_traded_picks:
            raise RuntimeError("traded picks fetch failed")
        return []

    async def get_drafts(self, league_id):
        return self._drafts_by_league.get(league_id, [])

    async def get_draft_picks(self, draft_id):
        return self._picks_by_draft_id.get(draft_id, [])

    async def get_projections(self, season, week=None):
        if self._raise_on_projections:
            raise RuntimeError("projections fetch failed")
        return self._projections


async def _fake_build_trade_history(client, current_league_id, player_names, **kwargs):
    return [], {}


@pytest.mark.asyncio
async def test_grading_uses_the_snapshot_never_live_adp(tmp_path):
    """A snapshot captured for a draft must win over whatever the live
    projections fetch returns this refresh — conflating the two turns 'beat
    the market' into 'beat hindsight'."""
    chain = [_league("L1", 2026)]
    drafts_by_league = {"L1": [_draft_dict("d1", "L1", 2026)]}
    picks_by_draft_id = {"d1": [_pick_dict("p1")]}
    # Pre-seed a draft-day baseline that DIFFERS from the live fetch below.
    AdpSnapshotStore(tmp_path).capture("d1", {"p1": 5.0})
    projections = {"p1": {"adp_ppr": 99.0, "pts_ppr": 150.0}}
    client = _FakeDraftClient(chain, drafts_by_league, picks_by_draft_id, projections)

    async def fake_pull(client, chain, **kwargs):
        return _supporting_for({"L1": 2026})

    entry = await GraderService().run(
        client=client, current_league_id="L1", progress_cb=AsyncMock(),
        _build_trade_history=_fake_build_trade_history,
        _pull_supporting_data=fake_pull, cache_dir=tmp_path,
    )
    row = next(r for r in entry.drafted_picks if r["player_id"] == "p1")
    assert row["adp"] == pytest.approx(5.0)          # snapshot, not live 99.0
    assert row["adp_delta"] == pytest.approx(-4.0)    # pick_no 1 - adp 5.0
    assert row["projected_points"] == pytest.approx(150.0)  # projections stay live


@pytest.mark.asyncio
async def test_only_the_current_seasons_class_is_captured(tmp_path):
    """A class whose draft happened before our snapshot history begins must
    never get a baseline written for it, or a later refresh could grade it
    against a market that postdates the actual draft. d2025 is modeled as
    having been drafted well before "today" (the only day this refresh's
    daily capture can see); d2026 drafted "today" resolves normally."""
    chain = [_league("L2025", 2025), _league("L2026", 2026)]
    drafts_by_league = {
        "L2025": [_draft_dict(
            "d2025", "L2025", 2025,
            last_picked=_TODAY - _dt.timedelta(days=365))],
        "L2026": [_draft_dict("d2026", "L2026", 2026)],
    }
    picks_by_draft_id = {
        "d2025": [_pick_dict("p_old")],
        "d2026": [_pick_dict("p1")],
    }
    projections = {"p1": {"adp_ppr": 3.0, "pts_ppr": 250.0}}
    client = _FakeDraftClient(chain, drafts_by_league, picks_by_draft_id, projections)

    async def fake_pull(client, chain, **kwargs):
        return _supporting_for({"L2025": 2025, "L2026": 2026})

    await GraderService().run(
        client=client, current_league_id="L2026", progress_cb=AsyncMock(),
        _build_trade_history=_fake_build_trade_history,
        _pull_supporting_data=fake_pull, cache_dir=tmp_path,
    )
    store = AdpSnapshotStore(tmp_path)
    assert store.read("d2026") is not None    # current season: captured
    assert store.read("d2025") is None        # past season: never captured


@pytest.mark.asyncio
async def test_current_seasons_class_gets_baselined_on_first_refresh(tmp_path):
    """Capture-before-read: the very first refresh that sees a completed
    current-season class must both capture its baseline AND read it straight
    back into that same pass's grading — not wait for a second refresh."""
    chain = [_league("L1", 2026)]
    drafts_by_league = {"L1": [_draft_dict("d1", "L1", 2026)]}
    picks_by_draft_id = {"d1": [_pick_dict("p1")]}
    projections = {"p1": {"adp_ppr": 7.0, "pts_ppr": 180.0}}
    client = _FakeDraftClient(chain, drafts_by_league, picks_by_draft_id, projections)

    async def fake_pull(client, chain, **kwargs):
        return _supporting_for({"L1": 2026})

    entry = await GraderService().run(
        client=client, current_league_id="L1", progress_cb=AsyncMock(),
        _build_trade_history=_fake_build_trade_history,
        _pull_supporting_data=fake_pull, cache_dir=tmp_path,
    )
    assert AdpSnapshotStore(tmp_path).read("d1") == {"p1": pytest.approx(7.0)}
    row = next(r for r in entry.drafted_picks if r["player_id"] == "p1")
    assert row["adp"] == pytest.approx(7.0)


@pytest.mark.asyncio
async def test_projections_fetch_failure_degrades_without_failing_refresh(tmp_path):
    """Refresh stages degrade, never fail: a raising projections fetch must
    drop the ADP/projection columns but leave the rest of the refresh —
    including the drafted-pick rows themselves — intact."""
    chain = [_league("L1", 2026)]
    drafts_by_league = {"L1": [_draft_dict("d1", "L1", 2026)]}
    picks_by_draft_id = {"d1": [_pick_dict("p1")]}
    client = _FakeDraftClient(
        chain, drafts_by_league, picks_by_draft_id, projections={},
        raise_on_projections=True,
    )

    async def fake_pull(client, chain, **kwargs):
        return _supporting_for({"L1": 2026})

    entry = await GraderService().run(
        client=client, current_league_id="L1", progress_cb=AsyncMock(),
        _build_trade_history=_fake_build_trade_history,
        _pull_supporting_data=fake_pull, cache_dir=tmp_path,
    )
    assert entry.drafted_picks, "rookie_picks/drafted_picks must survive"
    row = next(r for r in entry.drafted_picks if r["player_id"] == "p1")
    assert row["adp"] is None
    assert row["adp_delta"] is None
    assert row["projected_points"] is None
    assert AdpSnapshotStore(tmp_path).read("d1") is None  # never captured


@pytest.mark.asyncio
async def test_draft_inputs_failure_before_drafts_by_league_is_bound_degrades_cleanly(
    tmp_path, caplog,
):
    """drafts_by_league is first assigned deep inside the draft-inputs try
    block. If that block raises BEFORE reaching that assignment (here:
    get_traded_picks, the very first call in the block), drafts_by_league
    must still be a bound empty dict when the ADP block's own try reads it a
    few lines later — an UnboundLocalError caught by that try's except is a
    crash-and-swallow, not the clean no-op degrade-never-fail promises."""
    import logging

    chain = [_league("L1", 2026)]
    drafts_by_league = {"L1": [_draft_dict("d1", "L1", 2026)]}
    picks_by_draft_id = {"d1": [_pick_dict("p1")]}
    projections = {"p1": {"adp_ppr": 3.0, "pts_ppr": 250.0}}
    client = _FakeDraftClient(
        chain, drafts_by_league, picks_by_draft_id, projections,
        raise_on_traded_picks=True,
    )

    async def fake_pull(client, chain, **kwargs):
        return _supporting_for({"L1": 2026})

    caplog.set_level(logging.ERROR, logger="app.services.grader")
    entry = await GraderService().run(
        client=client, current_league_id="L1", progress_cb=AsyncMock(),
        _build_trade_history=_fake_build_trade_history,
        _pull_supporting_data=fake_pull, cache_dir=tmp_path,
    )

    # The draft-inputs stage itself failed, so there are no picks to grade —
    # that part is expected. What matters is that the ADP block downstream
    # never crashed on an unbound drafts_by_league: no ADP-stage failure was
    # logged (a clean no-op logs nothing; a caught UnboundLocalError would
    # log "ADP/projection fetch skipped" via log.exception).
    assert entry.drafted_picks == []
    assert not any(
        "ADP/projection fetch skipped" in r.message for r in caplog.records
    ), "ADP block should degrade as a clean no-op, not a caught exception"
    assert AdpSnapshotStore(tmp_path).read("d1") is None


@pytest.mark.asyncio
async def test_daily_capture_stores_every_variant_not_just_this_leagues(tmp_path):
    """Multi-tenant install: one dated file is shared by every league. A
    superflex league's refresh must leave a PPR league's board readable, or
    (both files being write-once) the wrong market freezes in permanently."""
    from app.services.adp_snapshot_store import AdpSnapshotStore

    chain = [_league("L1", 2026, superflex=True)]
    drafts_by_league = {"L1": [_draft_dict("d1", "L1", 2026)]}
    picks_by_draft_id = {"d1": [_pick_dict("qb1")]}
    # QBs ~25 picks apart between the two variants.
    projections = {"qb1": {"adp_ppr": 45.0, "adp_2qb": 20.0, "pts_ppr": 300.0}}
    client = _FakeDraftClient(chain, drafts_by_league, picks_by_draft_id, projections)

    async def fake_pull(client, chain, **kwargs):
        return _supporting_for({"L1": 2026})

    entry = await GraderService().run(
        client=client, current_league_id="L1", progress_cb=AsyncMock(),
        _build_trade_history=_fake_build_trade_history,
        _pull_supporting_data=fake_pull, cache_dir=tmp_path,
    )
    # This superflex league graded against 2QB ADP...
    row = next(r for r in entry.drafted_picks if r["player_id"] == "qb1")
    assert row["adp"] == pytest.approx(20.0)
    # ...and the day's PPR board survived for whoever reads it next.
    store = AdpSnapshotStore(tmp_path)
    assert store.resolve_for_draft(
        "some-ppr-draft", _TODAY, field="adp_ppr") == {"qb1": pytest.approx(45.0)}


@pytest.mark.asyncio
async def test_dynasty_rookie_class_gets_no_adp_or_projection(tmp_path):
    """Sleeper publishes no rookie ADP; the overall-NFL ADP it DOES publish
    would grade a 1.01 rookie against ~30th overall and print a 29-pick
    reach. Design matrix: dynasty -> no ADP baseline, no projection
    baseline."""
    chain = [_league("L0", 2025, fmt="dynasty"), _league("L1", 2026, fmt="dynasty")]
    # player_type 1 = rookie-only, so this is a graded dynasty rookie class
    # (2025 is the origin/startup season and is skipped by build_draft_classes).
    rookie = _draft_dict("d1", "L1", 2026)
    rookie["settings"]["player_type"] = 1
    drafts_by_league = {"L0": [], "L1": [rookie]}
    picks_by_draft_id = {"d1": [_pick_dict("p1")]}
    projections = {"p1": {"adp_ppr": 30.0, "pts_ppr": 180.0}}
    client = _FakeDraftClient(chain, drafts_by_league, picks_by_draft_id, projections)

    async def fake_pull(client, chain, **kwargs):
        return _supporting_for({"L0": 2025, "L1": 2026})

    entry = await GraderService().run(
        client=client, current_league_id="L1", progress_cb=AsyncMock(),
        _build_trade_history=_fake_build_trade_history,
        _pull_supporting_data=fake_pull, cache_dir=tmp_path,
    )
    row = next(r for r in entry.drafted_picks if r["player_id"] == "p1")
    assert row["adp"] is None
    assert row["adp_delta"] is None
    assert row["projected_points"] is None


@pytest.mark.asyncio
async def test_dynasty_refresh_still_captures_the_daily_market(tmp_path):
    """The dynasty gate is on GRADING, not on capture. Daily capture has to
    stay unconditional — a dynasty league refreshing on the redraft league's
    draft day is one of the writers keeping that day's board recoverable."""
    from app.services.adp_snapshot_store import AdpSnapshotStore

    chain = [_league("L0", 2025, fmt="dynasty"), _league("L1", 2026, fmt="dynasty")]
    rookie = _draft_dict("d1", "L1", 2026)
    rookie["settings"]["player_type"] = 1
    client = _FakeDraftClient(
        chain, {"L0": [], "L1": [rookie]}, {"d1": [_pick_dict("p1")]},
        {"p1": {"adp_ppr": 30.0, "pts_ppr": 180.0}})

    async def fake_pull(client, chain, **kwargs):
        return _supporting_for({"L0": 2025, "L1": 2026})

    await GraderService().run(
        client=client, current_league_id="L1", progress_cb=AsyncMock(),
        _build_trade_history=_fake_build_trade_history,
        _pull_supporting_data=fake_pull, cache_dir=tmp_path,
    )
    assert AdpSnapshotStore(tmp_path).list_dates() == [_TODAY]


@pytest.mark.asyncio
async def test_seasons_held_and_verdict_survive_the_grader_seam(tmp_path):
    """CRITICAL D: test_grader_verdict.py ("the seam, not the whole refresh")
    never imports grader.py — it re-calls the rookie_cohorts engine functions
    directly — so deleting `seasons_fn=_seasons` from the
    build_drafted_pick_results call, or deleting the verdict-stamping loop
    right after it, would make the Verdict column silently vanish in
    production with every other suite green. This drives the real
    GraderService end to end and asserts on the persisted `drafted_picks`
    row, so it actually notices."""
    chain = [_league("L1", 2026, fmt="dynasty")]
    rookie = _draft_dict("d1", "L1", 2026)
    rookie["settings"]["player_type"] = 1
    client = _FakeDraftClient(
        chain, {"L1": [rookie]}, {"d1": [_pick_dict("p1")]}, projections={})
    # p1 held by u1 for one week of L1/2026.
    matchups = {("L1", 1, 1): {"players": ["p1"], "starters": [], "players_points": {}}}

    async def fake_pull(client, chain, **kwargs):
        return _supporting_for({"L1": 2026}, matchups=matchups)

    entry = await GraderService().run(
        client=client, current_league_id="L1", progress_cb=AsyncMock(),
        _build_trade_history=_fake_build_trade_history,
        _pull_supporting_data=fake_pull, cache_dir=tmp_path,
        # A COMPLETE 2026 season (scoring not in progress), so the one week
        # of matchup data above counts as a whole season held rather than
        # zero (CRITICAL A's completed-seasons gate would otherwise exclude
        # the chain's only/newest season while it looks still in progress).
        _nfl_state={"season_type": "off", "season": 2026, "week": 0},
    )
    row = next(r for r in entry.drafted_picks if r["player_id"] == "p1")
    assert row["seasons_held"] == 1
    # No rookie-ECR/ADP baseline in this fixture (no network in tests, and
    # ADP is skipped for a dynasty rookie class), so the honest verdict is
    # "", not a KeyError from a missing stamp.
    assert row["verdict"] == ""
