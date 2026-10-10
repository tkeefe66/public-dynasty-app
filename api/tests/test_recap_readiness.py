"""Mutation targets: coverage deletion, 3600 boundary, original precision, rollover."""
import copy
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.services.generation.store import dump


@pytest.fixture(autouse=True)
def enabled_workflow(monkeypatch):
    from tests.recap_fixtures import install_recap_policy
    return install_recap_policy(monkeypatch)


def snapshot():
    return {
        "league_id": "synthetic", "season": 2026, "week": 4, "period_id": "4",
        "nfl_weeks": [4], "round": None, "phase": "regular",
        "roster_positions": ["QB", "RB", "BN"],
        "expected_games": ["synthetic-game"],
        "observed_games": [{"event_id": "synthetic-game", "completed": True,
                            "status": "STATUS_FINAL", "home": "BUF", "away": "NE"}],
        "inventory_verified": True, "schedule_revision": "qualified-v1",
        "participants": [{"roster_id": i, "owner_id": f"owner-{i}", "status": "regular"} for i in (1, 2)],
        "pairings": [{"rosters": [1, 2], "scope": "week", "status": "regular"}],
        "scores": {"4": [{"roster_id": i, "matchup_id": 1, "points": "100.0100",
            "custom_points": None, "starters": ["p1", "p2"], "players": ["p1", "p2", "p3"],
            "players_points": {"p1": "99.00", "p2": "1.0100", "p3": "20.00"}} for i in (1, 2)]},
        "starters": {"4": {str(i): ["p1", "p2"] for i in (1, 2)}},
        "bracket": {"ok": True, "winners": [], "losers": []},
        "dispositions": {}, "source_errors": [], "eligible_at": 1000, "observed_at": 1000,
    }


def evaluate(s, p=None, now=4600):
    from app.services.recap_video.readiness import evaluate_readiness
    return evaluate_readiness(s, p, now)


def test_empty_scoreboard_never_means_finished():
    assert evaluate({"expected_games": ["synthetic-game"], "observed_games": [],
        "inventory_verified": True, "eligible_at": 1}, now=2).code == "schedule_incomplete"


@pytest.mark.parametrize("seconds,ready", [(3599, False), (3600, True)])
def test_stable_sixty_minute_boundary(seconds, ready):
    # Changing >=3600 to >3600 breaks exact boundary; removing stability breaks 3599.
    s = snapshot()
    assert evaluate(s, s, 1000 + seconds).ready is ready


@pytest.mark.parametrize("sunday,utc_hour", [("2026-10-11", 14), ("2026-11-08", 15)])
def test_tuesday_eight_denver_across_dst(sunday, utc_hour):
    from app.services.recap_video.periods import eligible_release
    eligible = eligible_release(sunday)
    dt = datetime.fromtimestamp(eligible, ZoneInfo("UTC"))
    assert dt.hour == utc_hour and dt.weekday() == 1
    s = snapshot()
    s["eligible_at"] = eligible
    s["observed_at"] = eligible - 3660
    assert evaluate(s, s, eligible - 60).code == "release_not_due"
    assert evaluate(s, s, eligible).ready


@pytest.mark.parametrize("change,code", [
    ({"inventory_verified": False}, "schedule_inventory_unqualified"),
    ({"observed_games": []}, "schedule_incomplete"),
    ({"source_errors": ["matchups timeout"]}, "source_error"),
    ({"pairings": []}, "participant_incomplete"),
    ({"bracket": {"ok": False, "error": "timeout"}}, "bracket_unavailable"),
])
def test_incomplete_evidence_holds(change, code):
    s = snapshot()
    s.update(change)
    result = evaluate(s, snapshot())
    assert not result.ready and result.code == code


@pytest.mark.parametrize("status", ["STATUS_SCHEDULED", "STATUS_POSTPONED", "STATUS_CANCELED", "UNKNOWN"])
def test_unresolved_event_status_holds(status):
    s = snapshot()
    s["observed_games"][0].update(status=status, completed=False)
    assert evaluate(s, s).code == "games_unresolved"
    s["dispositions"] = {"synthetic-game": {"authority": "league", "source": "synthetic-rule", "decision": "void"}}
    assert evaluate(s, s).ready


@pytest.mark.parametrize("key", ["schedule_revision", "scores", "starters"])
def test_competitive_change_resets_stability(key):
    s, old = snapshot(), snapshot()
    if key == "schedule_revision":
        s[key] = "new-revision"
    elif key == "scores":
        s[key]["4"][0]["custom_points"] = "100.0200"
    else:
        s[key]["4"]["1"].reverse()
        s["scores"]["4"][0]["starters"].reverse()
    assert evaluate(s, old).code == "facts_unstable"


def test_observation_time_and_news_do_not_change_competitive_hash():
    s, old = snapshot(), snapshot()
    s.update(observed_at=4600, player_news="unrelated")
    assert evaluate(s, old).ready
    assert evaluate(s, old).facts_digest == evaluate(old, old).facts_digest


def test_precision_and_complete_starter_snapshot():
    from app.services.recap_video.periods import build_participants
    rows = snapshot()["scores"]
    result = build_participants([{"roster_id": i, "owner_id": f"owner-{i}"} for i in (1, 2)],
        rows, {"ok": True, "winners": [], "losers": []}, {"phase": "regular", "nfl_weeks": [4], "roster_positions": ["QB", "RB", "BN"]})
    assert result["participant_error"] == ""
    assert result["scores"]["4"][0]["points"] == "100.0100"
    assert result["starters"]["4"]["1"] == ["p1", "p2"]
    assert result["pairings"][0]["result"] == "tie"
    rows["4"][0]["matchup_id"] = rows["4"][1]["matchup_id"] = None
    result = build_participants([{"roster_id": i, "owner_id": f"owner-{i}"} for i in (1, 2)],
        rows, {"ok": True, "winners": [], "losers": []}, {"phase": "regular", "nfl_weeks": [4], "roster_positions": ["QB", "RB", "BN"]})
    assert result["participant_error"] == "participant_incomplete"
    assert result["pairings"] == []


def playoff_fixture():
    rosters = [{"roster_id": i, "owner_id": f"owner-{i}"} for i in range(1, 7)]
    bracket = {"ok": True, "winners": [
        {"m": 1, "r": 1, "t1": 1, "t2": 2, "w": 1, "l": 2},
        {"m": 2, "r": 2, "t1": {"w": 1}, "t2": 3, "p": 1},
        {"m": 3, "r": 2, "t1": {"l": 1}, "t2": 4, "p": 3},
    ], "losers": [{"m": 1, "r": 1, "t1": 5, "t2": 6, "w": 5, "l": 6, "p": 1}]}
    rows = [{**snapshot()["scores"]["4"][0], "roster_id": i,
             "matchup_id": 1 if i in (1, 2) else 2 if i in (5, 6) else None} for i in range(1, 7)]
    return rosters, bracket, rows


def test_playoff_byes_placement_and_finished_owners_have_evidence():
    from app.services.recap_video.periods import build_participants
    rosters, bracket, rows = playoff_fixture()
    period = {"phase": "post", "round": 1, "nfl_weeks": [15], "round_type": 0, "roster_positions": ["QB", "RB", "BN"]}
    result = build_participants(rosters, {"15": rows}, bracket, period)
    assert result["participant_error"] == ""
    assert {p["roster_id"]: p["status"] for p in result["participants"]} == {
        1: "title", 2: "title", 3: "bye", 4: "bye", 5: "consolation", 6: "consolation"}
    bracket["winners"][1].update(t1=1, t2=3, w=1, l=3)
    bracket["winners"][2].update(t1=2, t2=4, w=2, l=4)
    for row in rows:
        row["matchup_id"] = 1 if row["roster_id"] in (1, 3) else 2 if row["roster_id"] in (2, 4) else None
    result = build_participants(rosters, {"16": rows}, bracket,
        {"phase": "post", "round": 2, "nfl_weeks": [16], "round_type": 0, "roster_positions": ["QB", "RB", "BN"]})
    assert result["participant_error"] == ""
    assert {p["roster_id"]: p["status"] for p in result["participants"]} == {
        1: "title", 3: "title", 2: "placement", 4: "placement", 5: "season_finished", 6: "season_finished"}


def test_two_week_final_needs_both_weeks_and_resolved_bracket():
    from app.services.recap_video.periods import build_participants
    rosters = [{"roster_id": i, "owner_id": f"owner-{i}"} for i in (1, 2)]
    bracket = {"ok": True, "winners": [{"m": 1, "r": 1, "t1": 1, "t2": 2}], "losers": []}
    period = {"phase": "post", "round": 1, "nfl_weeks": [16, 17], "round_type": 1, "roster_positions": ["QB", "RB", "BN"]}
    result = build_participants(rosters, {"16": snapshot()["scores"]["4"]}, bracket, period)
    assert result["participant_error"] == "round_incomplete"
    result = build_participants(rosters, {str(w): snapshot()["scores"]["4"] for w in (16, 17)}, bracket, period)
    assert result["participant_error"] == "round_unresolved"


@pytest.mark.parametrize("kind,weeks", [(0, [17]), (1, [17, 18]), (2, [17, 18])])
def test_actual_round_rules_define_episode_membership(kind, weeks):
    from app.services.recap_video.periods import scoring_period
    start = 13 if kind == 2 else 15
    bracket = {"ok": True, "winners": [{"r": r} for r in (1, 2, 3)], "losers": []}
    period = scoring_period(17, {"playoff_week_start": start, "playoff_round_type": kind,
        "playoff_teams": 6}, bracket)
    assert period["period_id"] == "playoff:3" and period["nfl_weeks"] == weeks


def test_unknown_or_ambiguous_round_rules_hold():
    from app.services.recap_video.periods import scoring_period
    for kind, bracket in [(99, {"ok": True}), (1, {"ok": True, "winners": [{"r": 3}], "losers": [{"r": 2}]})]:
        with pytest.raises(ValueError, match="playoff_.*"):
            scoring_period(17, {"playoff_week_start": 15, "playoff_round_type": kind, "playoff_teams": 6}, bracket)


def test_malformed_score_cannot_be_admitted_by_fabricated_pairing():
    s = snapshot()
    s["scores"]["4"][0]["points"] = 100.01
    assert evaluate(s, s).code == "score_precision_unavailable"


def test_shortened_starter_rows_hold_against_actual_lineup_slots():
    s = snapshot()
    s["scores"]["4"][0]["starters"] = ["p1"]
    s["starters"]["4"]["1"] = ["p1"]
    assert evaluate(s, s).code == "starter_evidence_incomplete"


@pytest.mark.parametrize("positions", [None, "QB", {}, [], ["BN"], [None], ["QB", "UNKNOWN"], [["QB"]]])
def test_invalid_slot_inventory_never_disables_starter_completeness(positions):
    s = snapshot()
    s["roster_positions"] = positions
    s["scores"]["4"][0]["starters"] = ["0"]
    s["starters"]["4"]["1"] = ["0"]
    assert evaluate(s, s).code == "roster_positions_unsupported"
    del s["roster_positions"]
    assert evaluate(s, s).code == "roster_positions_unsupported"


@pytest.mark.parametrize("current_pairing", [None, 2])
def test_missing_placement_match_cannot_imply_finished(current_pairing):
    from app.services.recap_video.periods import build_participants
    rosters = [{"roster_id": i, "owner_id": f"owner-{i}"} for i in range(1, 5)]
    bracket = {"ok": True, "winners": [
        {"m": 1, "r": 1, "t1": 1, "t2": 2, "w": 1, "l": 2},
        {"m": 2, "r": 1, "t1": 3, "t2": 4, "w": 3, "l": 4},
        {"m": 3, "r": 2, "t1": 1, "t2": 3, "w": 1, "l": 3, "p": 1},
        {"m": 4, "r": 2, "t1": 2, "t2": 4, "w": 2, "l": 4, "p": 3},
    ], "losers": []}
    scores = {"16": [{"roster_id": i, "matchup_id": 1 if i in (1, 3) else 2,
        "points": "100.00", "starters": ["p"], "players": ["p"], "players_points": {"p": "100.00"}}
        for i in range(1, 5)]}
    s = {**snapshot(), "week": 16, "period_id": "playoff:2", "phase": "post", "round": 2,
         "round_type": 0, "nfl_weeks": [16], "roster_positions": ["QB"]}
    s.update(build_participants(rosters, scores, bracket, s))
    assert evaluate(s, s).ready
    bracket["winners"].pop()  # Delete real placement coverage, retaining all owner rows.
    for row in scores["16"]:
        if row["roster_id"] in (2, 4):
            row["matchup_id"] = current_pairing
    s.update(build_participants(rosters, scores, bracket, s))
    assert evaluate(s, s).code == "participant_status_unknown"


@pytest.mark.parametrize("status", ["bye", "season_finished"])
def test_nonplaying_bracket_status_conflicts_with_current_pairing(status):
    from app.services.recap_video.periods import build_participants
    rosters, bracket, rows = playoff_fixture()
    bracket["losers"][0]["p"] = 1
    round_no = 1 if status == "bye" else 2
    if round_no == 2:
        bracket["winners"][1].update(t1=1, t2=3, w=1, l=3)
        bracket["winners"][2].update(t1=2, t2=4, w=2, l=4)
    for row in rows:
        rid = row["roster_id"]
        row["matchup_id"] = (1 if rid in (1, 2) else 2 if rid in (5, 6) else 3) if round_no == 1 else (
            1 if rid in (1, 3) else 2 if rid in (2, 4) else 3)
    result = build_participants(rosters, {"16": rows}, bracket, {"phase": "post", "round": round_no,
        "nfl_weeks": [16], "round_type": 0, "roster_positions": ["QB", "RB", "BN"]})
    assert result["participant_error"] == "pairing_conflict"


@pytest.mark.asyncio
@pytest.mark.parametrize("feature,change,code", [
    ("recap_video", {"mode": "disabled"}, "recap_workflow_disabled"),
    ("recap_video", {"paused": True}, "recap_feature_paused"),
    ("analyst", {"paused": True}, "recap_feature_paused"),
    ("analyst", {"mode": "disabled"}, "recap_feature_paused"),
    ("analyst", {"mode": "manual"}, "manual_approval_required"),
    ("recap_video", {"mode": "manual"}, "manual_approval_required"),
])
async def test_feature_restriction_then_rollover_cannot_mint_admission(maker, enabled_workflow, feature, change, code):
    from app.services.recap_video.contracts import EpisodeKey
    from app.services.recap_video.readiness import observe_period, competitive_digest
    from app.services.generation.recap_models import RecapEpisode
    from app.services.generation.models import LeagueSeason
    from app.services.generation.planner import automatic_eligibility
    from app.services.generation.commands import authorize_candidate
    from app.services.generation.models import GenerationCandidate, ProviderAttempt
    from app.services.generation.store import Held
    from tests.test_generation_gateway import seed_job
    await seed_job(maker)
    enabled_workflow[feature].update(change)
    async with maker.begin() as db:
        season = await db.get(LeagueSeason, "synthetic")
        season.latest_week = 4
        key, s = EpisodeKey("series", 2026, "4"), snapshot()
        ident = await observe_period(db, key, s, 1000)
        await observe_period(db, key, s, 4600)
        row = await db.get(RecapEpisode, ident)
        assert row.admitted_at == 0 and row.hold == code
        season.latest_week = 5
        enabled_workflow[feature].update(mode="automatic", paused=False)
        await observe_period(db, key, {**s, "current_period_id": "5"}, 5500)
        assert row.admitted_at == 0 and row.hold == "historical_approval_required"
        assert await automatic_eligibility(db, season, "analyst", {
            "season": 2026, "week": 4, "recap_facts_digest": competitive_digest(s)}, 5500) == "historical_approval_required"
        db.add(GenerationCandidate(key="recap", series_id="series", league_id="synthetic", feature="analyst",
            subject="recap", event="2026:week:04", digest="request", payload_json=dump({
                "season": 2026, "week": 4, "recap_facts_digest": competitive_digest(s)})))
        with pytest.raises(Held, match="historical_approval_required"):
            await authorize_candidate(db, "recap", actor_id="owner", actor_kind="scheduler",
                reason="Rollover is not approval", authorization_key="rollover")
        assert not list((await db.scalars(select(ProviderAttempt))).all())


def test_delayed_wednesday_game_does_not_move_release_to_next_tuesday():
    from app.services.recap_video.periods import period_release
    expected = [{"week": 4, "gameday": "2026-10-11"}, {"week": 4, "gameday": "2026-10-14"}]
    assert datetime.fromtimestamp(period_release(expected, [4]), ZoneInfo("America/Denver")).isoformat() == "2026-10-13T08:00:00-06:00"


@pytest.mark.asyncio
async def test_disabled_workflow_observations_never_admit(maker, monkeypatch):
    from app.services.recap_video.readiness import observe_period
    from app.services.recap_video.contracts import EpisodeKey
    from app.services.generation.recap_models import RecapEpisode
    from app.services.generation.models import LeagueSeason
    from tests.test_generation_gateway import seed_job
    async def disabled(*args):
        return False
    monkeypatch.setattr("app.services.recap_video.readiness.workflow_enabled", disabled)
    await seed_job(maker)
    async with maker.begin() as db:
        (await db.get(LeagueSeason, "synthetic")).latest_week = 4
        key = EpisodeKey("series", 2026, "4")
        ident = await observe_period(db, key, snapshot(), 1000)
        await observe_period(db, key, snapshot(), 4600)
        row = await db.get(RecapEpisode, ident)
        assert row.admitted_at == 0 and row.hold == "recap_workflow_disabled"


@pytest.mark.asyncio
async def test_free_history_or_paused_workflow_cannot_mint_admission(maker):
    from app.services.recap_video.contracts import EpisodeKey
    from app.services.recap_video.readiness import observe_period
    from app.services.generation.recap_models import RecapEpisode
    from app.services.generation.models import GenerationControl, LeagueSeason
    from tests.test_generation_gateway import seed_job
    await seed_job(maker)
    async with maker.begin() as db:
        (await db.get(LeagueSeason, "synthetic")).latest_week = 4
        (await db.get(GenerationControl, "global")).hold = "owner_paused"
        ident = await observe_period(db, EpisodeKey("series", 2026, "4"), snapshot(), 1000)
    async with maker.begin() as db:
        await observe_period(db, EpisodeKey("series", 2026, "4"), snapshot(), 4600)
        row = await db.get(RecapEpisode, ident)
        assert row.admitted_at == 0 and row.hold == "owner_paused"
        (await db.get(GenerationControl, "global")).hold = ""
        s = {**snapshot(), "current_period_id": "5"}
        await observe_period(db, EpisodeKey("series", 2026, "4"), s, 5500)
        assert row.admitted_at == 0 and row.hold == "historical_approval_required"


@pytest.mark.asyncio
async def test_immutable_observations_stability_and_rollover(maker):
    from app.services.recap_video.contracts import EpisodeKey
    from app.services.recap_video.readiness import observe_period
    from app.services.generation.recap_models import RecapEpisode, RecapObservation
    from app.services.generation.models import LeagueSeason
    from tests.test_generation_gateway import seed_job
    await seed_job(maker)
    key = EpisodeKey("series", 2026, "4")
    s = snapshot()
    async with maker.begin() as db:
        (await db.get(LeagueSeason, "synthetic")).latest_week = 4
        ident = await observe_period(db, key, s, 1000)
    for now in (1900, 2800, 3700, 4600):
        async with maker.begin() as db:
            assert await observe_period(db, key, s, now) == ident
    async with maker.begin() as db:
        row = await db.get(RecapEpisode, ident)
        assert row.lifecycle == "ready" and row.admitted_at == 4600
        records = list((await db.scalars(select(RecapObservation).where(RecapObservation.episode_id == ident))).all())
        before = {r.id: r.snapshot_json for r in records}
        assert len(before) == 5
        db.add(LeagueSeason(league_id="next-season", series_id="series", provider="sleeper",
                           provider_key="next-season", season=2027, latest_week=1))
    async with maker.begin() as db:
        await observe_period(db, key, s, 5500)
        assert (await db.get(RecapEpisode, ident)).lifecycle == "ready"
        other = {**s, "week": 3, "period_id": "3"}
        other_id = await observe_period(db, EpisodeKey("series", 2026, "3"), other, 5500)
        assert (await db.get(RecapEpisode, other_id)).hold == "historical_approval_required"
        for oid, content in before.items():
            assert (await db.get(RecapObservation, oid)).snapshot_json == content
        s["observed_games"] = []
        await observe_period(db, key, s, 6400)
        assert (await db.get(RecapEpisode, ident)).hold == "schedule_incomplete"
