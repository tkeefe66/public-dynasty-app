"""Free collection/admission/publication sentinels. No paid transport on holds."""
import copy
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.services.generation.models import GenerationOperation, LeagueSeason, ProviderAttempt
from app.services.generation.store import Held, dump
from tests.test_generation_gateway import FakeTransport, REQUEST, seed_job
from tests.test_recap_readiness import snapshot


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv("TRADE_GRADER_ADMIN_EMAILS", "owner@test.local")
    async def yes(*args):
        return True
    monkeypatch.setattr("app.services.recap_video.readiness.workflow_enabled", yes)


class Sources:
    fail_bracket = False
    fail_matchups = False

    async def get_recap_source(self, path):
        if path.endswith("/state/nfl"):
            data = {"season": "2026", "week": 5, "season_type": "regular"}
        elif path.endswith("/users"):
            data = [{"user_id": f"owner-{i}", "display_name": f"Owner {i}"} for i in (1, 2)]
        elif path.endswith("/rosters"):
            data = [{"roster_id": i, "owner_id": f"owner-{i}"} for i in (1, 2)]
        elif "bracket" in path:
            if self.fail_bracket:
                return {"ok": False, "error": "http_503", "source": path}
            data = []
        elif "matchups" in path:
            if self.fail_matchups:
                return {"ok": False, "error": "timeout", "source": path}
            data = copy.deepcopy(snapshot()["scores"]["4"])
        else:
            data = {"season": "2026", "name": "Synthetic League", "roster_positions": ["QB", "RB", "BN"], "settings": {
                "playoff_week_start": 15, "playoff_round_type": 0, "playoff_teams": 6}}
        return {"ok": True, "data": data, "raw": dump(data), "source": path, "provider_timestamp": "synthetic"}


@pytest.fixture
def free_sources(monkeypatch):
    async def inventory(season):
        return {"season": season, "version": "synthetic-v1", "revision": "qualified-v1", "games": [{
            "event_id": "synthetic-game", "source_id": "synthetic-source", "home": "BUF", "away": "NE",
            "week": 4, "gameday": "2026-10-11", "kickoff": "2026-10-11T17:00:00Z"}],
            "source_bytes": {}, "provenance": {"qualification": "synthetic-test"}}
    async def scoreboard(season, week):
        games = copy.deepcopy(snapshot()["observed_games"])
        games[0]["kickoff"] = "2026-10-11T17:00:00Z"
        return {"games": games, "raw": "synthetic-scoreboard",
                "source": "synthetic-source", "provider_timestamp": "synthetic"}
    monkeypatch.setattr("app.services.recap_video.collector.fetch_inventory", inventory)
    monkeypatch.setattr("app.services.recap_video.collector.fetch_week_evidence", scoreboard)
    return Sources()


@pytest.mark.asyncio
async def test_collection_persists_due_time_then_complete_private_packet(maker, tmp_path, enabled, free_sources):
    from app.services.recap_video.collector import collect_recap
    from app.services.analyst_store import AnalystStore
    from app.services.generation.recap_models import RecapEpisode, RecapObservation, RecapScheduleInventory
    from app.services.generation.planner import collect_analyst
    from app.services.generation.models import GenerationCandidate
    from app.services.generation.recap_budget import episode_identity
    await seed_job(maker)
    async with maker.begin() as db:
        (await db.get(LeagueSeason, "synthetic")).latest_week = 4
    @asynccontextmanager
    async def fence():
        async with maker.begin() as db:
            yield db
    start = int(datetime(2026, 10, 13, 14, tzinfo=timezone.utc).timestamp())
    assert await collect_recap(free_sources, "synthetic", tmp_path, fence, start)
    assert not AnalystStore(tmp_path).editions("synthetic")
    assert await collect_recap(free_sources, "synthetic", tmp_path, fence, start + 30)
    async with maker() as db:
        assert len(list((await db.scalars(select(RecapObservation))).all())) == 1
        row = await db.get(RecapEpisode, episode_identity("series", 2026, "4"))
        assert row.next_observation_at == start + 900
        assert len(list((await db.scalars(select(RecapScheduleInventory))).all())) == 1
    await collect_recap(free_sources, "synthetic", tmp_path, fence, start + 3600)
    assert len(AnalystStore(tmp_path).editions("synthetic")) == 1
    assert AnalystStore(tmp_path).published_editions("synthetic") == []
    async with maker.begin() as db:
        await collect_analyst(db, "synthetic", "series", tmp_path)
        candidate = await db.scalar(select(GenerationCandidate).where(GenerationCandidate.feature == "analyst"))
        payload = json.loads(candidate.payload_json)
        assert payload["source_snapshot"]["scores"]["4"][0]["points"] == "100.0100"
        assert payload["source_snapshot"]["starters"]["4"]["1"] == ["p1", "p2"]
        assert payload["source_snapshot"]["roster_positions"] == ["QB", "RB", "BN"]
        assert payload["source_snapshot"]["player_metadata"]["available"] is False
        assert payload["recap_facts_digest"]
    free_sources.fail_matchups = True
    with pytest.raises(RuntimeError, match="recap_collection_failed"):
        await collect_recap(free_sources, "synthetic", tmp_path, fence, start + 4500)
    async with maker() as db:
        row = await db.get(RecapEpisode, episode_identity("series", 2026, "4"))
        assert row.lifecycle == "held"
        assert len(list((await db.scalars(select(RecapObservation))).all())) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("change,code", [({"observed_games": []}, "schedule_incomplete"),
    ({"inventory_verified": False}, "schedule_inventory_unqualified"),
    ({"pairings": []}, "participant_incomplete"), ({"bracket": {"ok": False}}, "bracket_unavailable"),
    ({"source_errors": ["timeout"]}, "source_error")])
async def test_incomplete_snapshot_cannot_reach_paid_gateway(maker, enabled, change, code):
    from app.services.recap_video.readiness import observe_period
    from app.services.recap_video.contracts import EpisodeKey
    from app.services.generation.gateway import Gateway
    await seed_job(maker)
    async with maker.begin() as db:
        (await db.get(LeagueSeason, "synthetic")).latest_week = 4
        s = snapshot()
        s.update(change)
        await observe_period(db, EpisodeKey("series", 2026, "4"), s, 1000)
        job = await db.get(GenerationOperation, "job")
        job.feature = "analyst"
        job.payload_json = dump({"season": 2026, "week": 4, "recap_facts_digest": "stale"})
    transport = FakeTransport()
    with pytest.raises(Held, match=code):
        from app.services.generation.policy import Policy
        request = {**REQUEST, "model": Policy().features["analyst"].model}
        await Gateway(maker, transport, epoch="test-epoch").invoke("job", 1, 1, request)
    assert transport.sends == 0
    async with maker() as db:
        assert not list((await db.scalars(select(ProviderAttempt))).all())


def test_playoff_budget_identity_uses_round_not_archive_week():
    from app.services.generation.recap_budget import operation_episode, episode_identity
    payload = {"season": 2026, "week": 17, "period_id": "playoff:3", "edition": {
        "season": 2026, "week": 17, "facts": {"period_id": "playoff:3"}}}
    job = SimpleNamespace(series_id="series", payload_json=dump(payload))
    assert operation_episode(job) == episode_identity("series", 2026, "playoff:3")
    payload["edition"]["facts"]["period_id"] = "playoff:2"
    job.payload_json = dump(payload)
    with pytest.raises(Held, match="identity_conflict"):
        operation_episode(job)


@pytest.mark.asyncio
async def test_new_publication_rechecks_current_evidence_and_retains_old_editions(maker, tmp_path, enabled):
    from app.services.analyst_store import AnalystEdition, AnalystStore
    from app.services.recap_video.readiness import observe_period, competitive_digest
    from app.services.recap_video.contracts import EpisodeKey
    from app.services.generation.models import ContentArtifact, GenerationOutbox
    from app.services.generation.publication import drain
    from app.services.generation.recap_models import RecapEpisode
    from app.services.generation.store import digest
    await seed_job(maker)
    key, s = EpisodeKey("series", 2026, "4"), snapshot()
    async with maker.begin() as db:
        (await db.get(LeagueSeason, "synthetic")).latest_week = 4
        ident = await observe_period(db, key, s, 1000)
    content = AnalystEdition.model_validate({"season": 2026, "week": 4, "league_name": "Synthetic",
        "generated_at": "2026-10-13T14:00:00Z", "model": "synthetic", "markdown": "Reviewed roast.", "facts": {}}).model_dump()
    store = AnalystStore(tmp_path)
    store.save("synthetic", {**content, "week": 1})
    original = store.edition_path("synthetic", 2026, 1).read_bytes()
    async with maker.begin() as db:
        await observe_period(db, key, s, 4600)
        db.add(ContentArtifact(id="new", series_id="series", league_id="synthetic", feature="analyst",
            subject="synthetic-edition", revision=1, payload_json=dump(content), digest=digest(content),
            facts_json=dump({"season": 2026, "week": 4, "recap_facts_digest": competitive_digest(s)}), provenance="managed"))
        db.add(GenerationOutbox(key="new", kind="artifact", payload_json=dump({"artifact_id": "new"})))
        await observe_period(db, key, {**s, "observed_games": []}, 5500)
    await drain(maker, tmp_path)
    assert not store.edition_path("synthetic", 2026, 4).exists()
    assert store.edition_path("synthetic", 2026, 1).read_bytes() == original
    async with maker.begin() as db:
        await observe_period(db, key, s, 6400)
    async with maker.begin() as db:
        await observe_period(db, key, s, 10000)
    await drain(maker, tmp_path)
    assert store.edition_path("synthetic", 2026, 4).exists()
    async with maker() as db:
        assert (await db.get(RecapEpisode, ident)).article_digest == digest(content)


@pytest.mark.asyncio
async def test_authorization_requires_ready_episode_and_bound_digest(maker, enabled):
    from app.services.generation.commands import authorize_candidate
    from app.services.generation.models import GenerationCandidate
    from app.services.recap_video.readiness import observe_period, competitive_digest
    from app.services.recap_video.contracts import EpisodeKey
    await seed_job(maker)
    s, key = snapshot(), EpisodeKey("series", 2026, "4")
    async with maker.begin() as db:
        (await db.get(LeagueSeason, "synthetic")).latest_week = 4
        await observe_period(db, key, s, 1000)
        db.add(GenerationCandidate(key="recap", series_id="series", league_id="synthetic", feature="analyst",
            subject="recap", event="2026:week:04", digest="request", payload_json=dump({
                "season": 2026, "week": 4, "recap_facts_digest": competitive_digest(s)})))
    async with maker.begin() as db:
        with pytest.raises(Held, match="facts_unstable"):
            await authorize_candidate(db, "recap", actor_id="owner", actor_kind="admin", reason="Test", authorization_key="first")
        await observe_period(db, key, s, 4600)
        row = await authorize_candidate(db, "recap", actor_id="owner", actor_kind="admin", reason="Test", authorization_key="first")
        assert row.feature == "analyst"
        from app.services.generation.models import stamp
        row.state, row.generation, row.lease_until = "running", 1, stamp() + 600
    async with maker.begin() as db:
        await observe_period(db, key, {**s, "schedule_revision": "changed"}, 5500)
    transport = FakeTransport()
    from app.services.generation.gateway import Gateway
    with pytest.raises(Held, match="facts_unstable"):
        await Gateway(maker, transport, epoch="test-epoch").invoke(row.id, 1, 1, REQUEST)
    assert transport.sends == 0


@pytest.mark.asyncio
async def test_enabled_collector_failure_surfaces_to_free_job(tmp_path, monkeypatch):
    from app.services.analyst import generate_analyst
    async def failed(*args):
        raise RuntimeError("recap_collection_failed: source unavailable; retry")
    monkeypatch.setattr("app.services.recap_video.collector.collect_recap", failed)
    with pytest.raises(RuntimeError, match="recap_collection_failed"):
        await generate_analyst(None, SimpleNamespace(league_id="synthetic"), tmp_path)


@pytest.mark.asyncio
async def test_unexpected_source_failure_invalidates_previously_ready_period(maker, tmp_path, enabled, free_sources, monkeypatch):
    from app.services.recap_video.collector import collect_recap
    from app.services.generation.recap_models import RecapEpisode
    await seed_job(maker)
    @asynccontextmanager
    async def fence():
        async with maker.begin() as db:
            yield db
    start = int(datetime(2026, 10, 13, 14, tzinfo=timezone.utc).timestamp())
    async with maker.begin() as db:
        (await db.get(LeagueSeason, "synthetic")).latest_week = 4
    await collect_recap(free_sources, "synthetic", tmp_path, fence, start)
    await collect_recap(free_sources, "synthetic", tmp_path, fence, start + 3600)
    async def malformed(*args):
        return {"ok": True, "data": {"week": "not-a-week", "season": "2026", "settings": {}}, "raw": "bad"}
    monkeypatch.setattr(free_sources, "get_recap_source", malformed)
    with pytest.raises(RuntimeError, match="recap_collection_failed"):
        await collect_recap(free_sources, "synthetic", tmp_path, fence, start + 4500)
    async with maker() as db:
        row = await db.scalar(select(RecapEpisode))
        assert row.lifecycle == "held" and row.hold == "source_error"
