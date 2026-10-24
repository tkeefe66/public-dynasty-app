"""Expired authorization may renew; revocation and paid checkpoint fences may not."""

import json

import pytest
from app.db.models import LeagueMembership, User, YahooConnection, YahooLeagueGrant
from app.services.generation.gateway import Gateway
from app.services.generation.models import (
    ContentArtifact,
    GenerationCandidate,
    GenerationOperation,
    GenerationPolicy,
    LeagueSeason,
    ProviderAttempt,
    stamp,
)
from app.services.generation.store import Held, digest, dump
from app.services.generation.worker import Worker, admit_automatic
from sqlalchemy import delete, func, select

from sleeper_dynasty.api.yahoo import YahooRateLimitError
from tests.test_generation_gateway import BODY, REQUEST, FakeTransport, seed_job
from tests.test_generation_worker import prepare

LEAGUE = "999.l.100000001"


async def seed_yahoo(maker, *, queued=False, expired=False):
    if queued:
        await prepare(maker)
    else:
        await seed_job(maker)
    async with maker.begin() as db:
        member = await db.scalar(select(LeagueMembership))
        member.league_id = LEAGUE
        season = await db.get(LeagueSeason, "synthetic")
        season.league_id, season.provider, season.provider_key = LEAGUE, "yahoo", LEAGUE
        job = await db.get(GenerationOperation, "job")
        job.league_id, job.connection_generation = LEAGUE, "original"
        db.add(YahooConnection(user_id="owner", generation="original", status="connected",
                               sealed_tokens="synthetic-not-read", expires_at=stamp() + 3600))
        db.add(YahooLeagueGrant(user_id="owner", league_id=LEAGUE, generation="original",
                               expires_at=stamp() - 1 if expired else stamp() + 300))


async def expire_grant(maker):
    async with maker.begin() as db:
        grant = await db.get(YahooLeagueGrant, ("owner", LEAGUE))
        grant.expires_at = stamp() - 1


async def seed_candidate(maker, *, mode="automatic"):
    await seed_yahoo(maker, expired=True)
    async with maker.begin() as db:
        await db.execute(delete(GenerationOperation))
        policy = await db.get(GenerationPolicy, "app")
        policy.value_json = dump({"paused": False, "features": {"gm_rating_blurb": {"mode": mode}}})
        season = await db.get(LeagueSeason, LEAGUE)
        season.latest_week = 2
        payload = {"facts": {}, "season": 2026, "week": 2, "event_at": stamp()}
        db.add(GenerationCandidate(key="candidate", series_id="series", league_id=LEAGUE,
            feature="gm_rating_blurb", subject="candidate-subject", event="2026:week:02",
            payload_json=dump(payload), digest=digest(payload), eligible_at=stamp()))


def verified_provider(monkeypatch, *, revoke=False, throttle=False):
    verified = []

    async def verify(db, user_id, league_id):
        # Model provider membership evidence only; ensure_grant and its DB writes stay real.
        assert (user_id, league_id) == ("owner", LEAGUE)
        assert not db.info.get("generation_global_lock")
        verified.append((user_id, league_id))
        if throttle:
            raise YahooRateLimitError("Synthetic authorization throttle", retry_after=900)
        grant = await db.get(YahooLeagueGrant, (user_id, league_id))
        grant.expires_at = stamp() + 300
        if revoke:
            connection = await db.get(YahooConnection, user_id)
            connection.generation = "reconnected"
        return {"league_id": league_id}

    monkeypatch.setattr("app.services.yahoo_discovery.verify_league", verify)
    from app.services.generation import commands, gateway, worker, yahoo_authorization

    original_lock = gateway.lock_control

    async def track_lock(db):
        db.info["generation_global_lock"] = True
        return await original_lock(db)

    monkeypatch.setattr(gateway, "lock_control", track_lock)
    monkeypatch.setattr(worker, "lock_control", track_lock)
    monkeypatch.setattr(commands, "lock_control", track_lock)
    monkeypatch.setattr(yahoo_authorization, "lock_control", track_lock)
    return verified


class ExpiringTransport(FakeTransport):
    def __init__(self, maker):
        body = {**BODY, "content": [{"type": "text", "text": json.dumps({
            "blurb": "Strong record.", "highlights": {},
        })}]}
        super().__init__(body=json.dumps(body))
        self.maker = maker

    async def send(self, request):
        result = await super().send(request)
        await expire_grant(self.maker)
        return result


@pytest.mark.asyncio
async def test_expired_grant_renews_between_new_paid_stages(maker, monkeypatch):
    # Mutation: never renew TTL-only expiry, or renew while holding the global admission lock.
    await seed_yahoo(maker)
    verified = verified_provider(monkeypatch)
    transport = FakeTransport()
    gateway = Gateway(maker, transport, epoch="test-epoch")
    assert await gateway.invoke("job", 1, 1, REQUEST) == BODY
    assert verified == []
    await expire_grant(maker)
    assert await gateway.invoke("job", 1, 2, REQUEST) == BODY
    assert verified == [("owner", LEAGUE)]
    async with maker() as db:
        job = await db.get(GenerationOperation, "job")
        assert (job.calls, job.max_calls, job.connection_generation) == (2, 2, "original")
        assert await db.scalar(select(func.count()).select_from(ProviderAttempt)) == 2
    assert transport.sends == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("revocation", ["generation", "grant_generation", "disconnected", "membership", "grant"])
async def test_revocation_prevents_yahoo_verification_and_paid_send(maker, monkeypatch, revocation):
    # Mutation: treating a revoked identity as mere expiry refreshes unauthorized provider access.
    await seed_yahoo(maker, expired=True)
    verified = verified_provider(monkeypatch)
    async with maker.begin() as db:
        if revocation == "membership":
            await db.execute(delete(LeagueMembership))
            db.add(User(id="other", google_sub="other", email="other@test.local"))
            db.add(LeagueMembership(user_id="other", league_id=LEAGUE))
        elif revocation == "grant":
            await db.execute(delete(YahooLeagueGrant))
        elif revocation == "grant_generation":
            grant = await db.get(YahooLeagueGrant, ("owner", LEAGUE))
            grant.generation = "previous"
        else:
            connection = await db.get(YahooConnection, "owner")
            if revocation == "generation":
                connection.generation = "reconnected"
            else:
                connection.status = "disconnected"
    transport = FakeTransport()
    with pytest.raises(Held, match="membership_removed|provider_grant_changed"):
        await Gateway(maker, transport, epoch="test-epoch").invoke("job", 1, 1, REQUEST)
    assert verified == []
    assert transport.sends == 0
    async with maker() as db:
        assert await db.scalar(select(func.count()).select_from(ProviderAttempt)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("revoked", [False, True])
async def test_saved_receipt_replay_never_revalidates_yahoo_or_resends(maker, monkeypatch, revoked):
    # Mutation: renewing before checking the receipt makes offline paid recovery require Yahoo.
    await seed_yahoo(maker)
    transport = FakeTransport()
    gateway = Gateway(maker, transport, epoch="test-epoch")
    assert await gateway.invoke("job", 1, 1, REQUEST) == BODY
    await expire_grant(maker)
    if revoked:
        async with maker.begin() as db:
            await db.execute(delete(LeagueMembership))
    verified = verified_provider(monkeypatch, throttle=True)
    assert await gateway.invoke("job", 1, 1, REQUEST) == BODY
    assert verified == []
    assert transport.sends == 1


@pytest.mark.asyncio
async def test_connection_changed_during_renewal_cannot_send(maker, monkeypatch):
    # Mutation: trusting pre-renewal authorization skips the locked dispatch identity recheck.
    await seed_yahoo(maker, expired=True)
    verified = verified_provider(monkeypatch, revoke=True)
    transport = FakeTransport()
    with pytest.raises(Held, match="provider_grant_changed"):
        await Gateway(maker, transport, epoch="test-epoch").invoke("job", 1, 1, REQUEST)
    assert verified == [("owner", LEAGUE)]
    assert transport.sends == 0
    async with maker() as db:
        assert await db.scalar(select(func.count()).select_from(ProviderAttempt)) == 0


@pytest.mark.asyncio
async def test_expired_grant_renews_before_artifact_save_without_new_paid_calls(maker, tmp_path, monkeypatch):
    # Mutation: omit publication renewal and strand valid saved output after a long provider call.
    await seed_yahoo(maker, queued=True)
    verified = verified_provider(monkeypatch)
    transport = ExpiringTransport(maker)
    worker = Worker(maker, tmp_path, transport=transport, epoch="test-epoch")
    assert await worker.tick()
    assert verified == [("owner", LEAGUE)]
    assert transport.sends == 1
    async with maker() as db:
        job = await db.get(GenerationOperation, "job")
        assert job.state == "succeeded", job.reason
        assert await db.scalar(select(func.count()).select_from(ContentArtifact)) == 1
        assert await db.scalar(select(func.count()).select_from(ProviderAttempt)) == 1
    assert not await worker.tick()
    assert transport.sends == 1


@pytest.mark.asyncio
async def test_connection_changed_during_publication_renewal_preserves_receipt_only(maker, tmp_path, monkeypatch):
    # Mutation: trusting renewal instead of save_artifact's identity fence publishes after reconnect.
    await seed_yahoo(maker, queued=True)
    verified = verified_provider(monkeypatch, revoke=True)
    transport = ExpiringTransport(maker)
    worker = Worker(maker, tmp_path, transport=transport, epoch="test-epoch")
    assert await worker.tick()
    assert verified == [("owner", LEAGUE)]
    async with maker() as db:
        job = await db.get(GenerationOperation, "job")
        assert (job.state, job.reason) == ("held", "provider_grant_changed")
        assert await db.scalar(select(func.count()).select_from(ContentArtifact)) == 0
        attempt = await db.scalar(select(ProviderAttempt))
        assert attempt.state == "received" and attempt.usage_state == "known"
    assert not await worker.tick()
    assert transport.sends == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("after_send", [False, True])
async def test_authorization_throttle_never_auto_retries_paid_operation(maker, tmp_path, monkeypatch, after_send):
    # Mutation: applying free-job backoff to paid authorization repeatedly wakes or resends paid work.
    await seed_yahoo(maker, queued=True, expired=not after_send)
    verified = verified_provider(monkeypatch, throttle=True)
    transport = ExpiringTransport(maker)
    worker = Worker(maker, tmp_path, transport=transport, epoch="test-epoch")
    assert await worker.tick()
    async with maker() as db:
        job = await db.get(GenerationOperation, "job")
        assert (job.state, job.reason) == ("needs_attention", "yahoo_rate_limited")
        assert job.retry_count == 0 and job.next_attempt_at == 0
        assert await db.scalar(select(func.count()).select_from(ContentArtifact)) == 0
        assert await db.scalar(select(func.count()).select_from(ProviderAttempt)) == int(after_send)
    assert not await worker.tick()
    assert verified == [("owner", LEAGUE)]
    assert transport.sends == int(after_send)


@pytest.mark.asyncio
async def test_automatic_admission_renews_expired_selected_admin_grant(maker, monkeypatch):
    # Mutation: renew only existing operations, leaving expired candidates permanently unadmitted.
    await seed_candidate(maker)
    verified = verified_provider(monkeypatch)
    await admit_automatic(maker)
    await admit_automatic(maker)
    async with maker() as db:
        jobs = (await db.scalars(select(GenerationOperation))).all()
        assert len(jobs) == 1
        assert (jobs[0].actor_id, jobs[0].connection_generation) == ("owner", "original")
        assert jobs[0].state == "queued" and jobs[0].calls == 0
        assert await db.scalar(select(func.count()).select_from(ProviderAttempt)) == 0
    assert verified == [("owner", LEAGUE)]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["manual", "disabled"])
async def test_automatic_admission_manual_modes_do_not_verify_or_queue(maker, monkeypatch, mode):
    # Mutation: refresh provider authorization before enforcing the saved manual/disabled policy.
    await seed_candidate(maker, mode=mode)
    verified = verified_provider(monkeypatch)
    await admit_automatic(maker)
    assert verified == []
    async with maker() as db:
        assert await db.scalar(select(func.count()).select_from(GenerationOperation)) == 0


@pytest.mark.asyncio
async def test_automatic_admission_throttle_holds_until_fresh_collection(maker, monkeypatch):
    # Mutation: silently swallow renewal failures and hammer Yahoo on every worker tick.
    from app.services.generation.planner import observe

    await seed_candidate(maker)
    verified = verified_provider(monkeypatch, throttle=True)
    await admit_automatic(maker)
    await admit_automatic(maker)
    async with maker() as db:
        candidate = await db.get(GenerationCandidate, "candidate")
        assert candidate.hold == "yahoo_rate_limited"
        assert await db.scalar(select(func.count()).select_from(GenerationOperation)) == 0
    assert verified == [("owner", LEAGUE)]
    # Real collection re-observes the same semantic candidate after free-job backoff.
    async with maker.begin() as db:
        candidate = await db.get(GenerationCandidate, "candidate")
        payload = json.loads(candidate.payload_json)
        await db.delete(candidate)
        row = await observe(db, series_id="series", league_id=LEAGUE,
            feature="gm_rating_blurb", subject="candidate-subject", event="2026:week:02", payload=payload)
        row.hold = "yahoo_rate_limited"
        key = row.key
    async with maker.begin() as db:
        await observe(db, series_id="series", league_id=LEAGUE,
            feature="gm_rating_blurb", subject="candidate-subject", event="2026:week:02", payload=payload)
        assert (await db.get(GenerationCandidate, key)).hold == ""


@pytest.mark.asyncio
async def test_automatic_admission_can_use_another_valid_admin_before_actor_is_saved(maker, monkeypatch):
    # Mutation: hold the entire candidate after one eligible administrator fails renewal.
    await seed_candidate(maker)
    verified = verified_provider(monkeypatch, throttle=True)
    monkeypatch.setenv("TRADE_GRADER_ADMIN_EMAILS", "owner@test.local,other@test.local")
    async with maker.begin() as db:
        db.add(User(id="other", google_sub="other", email="other@test.local", is_admin=True))
        db.add(LeagueMembership(user_id="other", league_id=LEAGUE))
        db.add(YahooConnection(user_id="other", generation="other-connection", status="connected",
                               sealed_tokens="synthetic", expires_at=stamp() + 3600))
        db.add(YahooLeagueGrant(user_id="other", league_id=LEAGUE, generation="other-connection",
                               expires_at=stamp() + 300))
    await admit_automatic(maker)
    async with maker() as db:
        jobs = (await db.scalars(select(GenerationOperation))).all()
        assert len(jobs) == 1 and jobs[0].actor_id == "other"
        assert jobs[0].connection_generation == "other-connection"
        assert (await db.get(GenerationCandidate, "candidate")).hold == ""
    assert verified == [("owner", LEAGUE)]


@pytest.mark.asyncio
@pytest.mark.parametrize("another_league", [False, True])
async def test_automatic_admission_deduplicates_failed_verification_across_candidates(
        maker, monkeypatch, another_league):
    # Mutation: retry account-wide discovery per candidate or per league after Yahoo throttles.
    await seed_candidate(maker)
    async with maker.begin() as db:
        original = await db.get(GenerationCandidate, "candidate")
        other_league = "999.l.100000002" if another_league else LEAGUE
        if another_league:
            db.add(LeagueMembership(user_id="owner", league_id=other_league))
            db.add(LeagueSeason(league_id=other_league, series_id="series", provider="yahoo",
                provider_key=other_league, season=2026, latest_week=2))
            db.add(YahooLeagueGrant(user_id="owner", league_id=other_league, generation="original",
                expires_at=stamp() - 1))
        db.add(GenerationCandidate(key="candidate-two", series_id="series", league_id=other_league,
            feature=original.feature, subject="another-subject", event=original.event,
            payload_json=original.payload_json, digest=original.digest, eligible_at=stamp()))
    verified = verified_provider(monkeypatch, throttle=True)
    await admit_automatic(maker)
    assert verified == [("owner", LEAGUE)]
    async with maker() as db:
        candidates = (await db.scalars(select(GenerationCandidate))).all()
        assert [row.hold for row in candidates] == ["yahoo_rate_limited"] * 2
        assert await db.scalar(select(func.count()).select_from(GenerationOperation)) == 0


@pytest.mark.asyncio
async def test_automatic_admission_refuses_reconnect_during_verification(maker, monkeypatch):
    # Mutation: admit with the connection current after verification instead of the selected one.
    await seed_candidate(maker)
    verified = verified_provider(monkeypatch, revoke=True)
    await admit_automatic(maker)
    assert verified == [("owner", LEAGUE)]
    async with maker() as db:
        assert await db.scalar(select(func.count()).select_from(GenerationOperation)) == 0
        assert (await db.get(GenerationCandidate, "candidate")).hold == "provider_grant_changed"


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["connection", "membership"])
async def test_automatic_admission_rechecks_principal_under_global_lock(maker, monkeypatch, change):
    # Mutation: adopt a replacement connection or removed membership between preflight and admission.
    from app.services.generation import worker

    await seed_candidate(maker)
    verified = verified_provider(monkeypatch)
    original_lock = worker.lock_control

    async def change_before_admission(db):
        result = await original_lock(db)
        if change == "membership":
            await db.execute(delete(LeagueMembership))
        else:
            connection = await db.get(YahooConnection, "owner")
            grant = await db.get(YahooLeagueGrant, ("owner", LEAGUE))
            connection.generation = grant.generation = "replacement"
        return result

    monkeypatch.setattr(worker, "lock_control", change_before_admission)
    await admit_automatic(maker)
    assert verified == [("owner", LEAGUE)]
    async with maker() as db:
        assert await db.scalar(select(func.count()).select_from(GenerationOperation)) == 0
