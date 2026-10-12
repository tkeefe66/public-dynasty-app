"""Guided recovery uses saved evidence and never buys a replacement implicitly."""
import asyncio

from app.services.generation.models import (
    ArtifactHead,
    ContentArtifact,
    GenerationCandidate,
    GenerationOperation,
    GenerationOutbox,
    GenerationPolicy,
    ProviderAttempt,
    stamp,
)
from app.services.generation.store import digest, dump
from sqlalchemy import func, select

from tests import test_generation_admin as admin_fixtures

admin_db = admin_fixtures.admin_db


def test_scheduler_manual_mode_requires_settings_change_before_continuing(client, admin_db):
    # Mutation: suggest Continue even though the scheduler would immediately hold again.
    async def configure(mode):
        async with admin_db.begin() as db:
            job = await db.get(GenerationOperation, "job")
            job.state, job.reason, job.actor_kind = "held", "manual_only", "scheduler"
            policy = await db.get(GenerationPolicy, "app")
            policy.value_json = dump({"paused": False, "features": {"trade_story": {"mode": mode}}})
    asyncio.run(configure("manual"))
    assert client.get("/api/admin/generation/jobs/job").json()["resolution"]["action"] == "settings"
    asyncio.run(configure("automatic"))
    assert client.get("/api/admin/generation/jobs/job").json()["resolution"]["action"] == "resume"


def stopped(maker, reason="execution_failed"):
    async def seed():
        async with maker.begin() as db:
            job = await db.get(GenerationOperation, "job")
            job.state, job.reason = "needs_attention", reason
            job.candidate_key = "candidate"
            payload = {"facts": {"trade_id": "synthetic-trade"}}
            job.payload_json, job.request_digest = dump(payload), digest(payload)
            db.add(GenerationCandidate(key="candidate", subject="story", series_id="series",
                league_id="synthetic", feature="trade_story", event="created",
                payload_json=dump(payload), digest=digest(payload), hold="historical_approval_required"))
    asyncio.run(seed())


def test_unknown_failure_gives_support_report_without_exposing_prompts(client, admin_db):
    # Mutation: recommend blind retry or include raw prompt/receipt content in the copy report.
    stopped(admin_db)
    result = client.get("/api/admin/generation/jobs/job").json()["resolution"]
    assert result["action"] == "support"
    assert result["title"] == "Requires an app fix"
    assert "job" in result["report"] and "execution_failed" in result["report"]
    assert "synthetic-trade" not in result["report"]


def test_related_unknown_request_blocks_replacement_even_on_cancelled_attempt(client, admin_db):
    # Mutation: check only the current operation's receipts, ignoring earlier uncertain spending.
    stopped(admin_db, "attempt_allowance_exhausted")
    async def seed():
        async with admin_db.begin() as db:
            db.add(GenerationOperation(id="older", kind="generation", league_id="synthetic",
                series_id="series", subject="story", feature="trade_story", state="cancelled"))
            db.add(ProviderAttempt(operation_id="older", stage=1, generation=1, model="synthetic",
                request_digest="digest", request_json="{}", state="unknown"))
    asyncio.run(seed())
    result = client.get("/api/admin/generation/jobs/job").json()["resolution"]
    assert result["action"] == "support"
    assert "confirm" in result["explanation"].lower()
    response = client.post("/api/admin/generation/jobs/job/replacement", json={
        "expected_generation": 1, "expected_state": "needs_attention", "reason": "Review replacement"})
    assert response.status_code == 409


def test_saved_current_story_routes_to_free_publication_not_replacement(client, admin_db):
    # Mutation: ignore the current artifact or offer a new paid request before checking delivery.
    stopped(admin_db)
    async def seed():
        async with admin_db.begin() as db:
            db.add(ContentArtifact(id="saved", operation_id="job", series_id="series", league_id="synthetic",
                feature="trade_story", subject="story", digest="saved", payload_json="{}", provenance="managed"))
            db.add(ArtifactHead(subject="story", artifact_id="saved", revision=1))
            db.add(GenerationOutbox(id="delivery", key="artifact:saved", kind="artifact",
                payload_json=dump({"artifact_id": "saved"}), error="projection_failed"))
    asyncio.run(seed())
    result = client.get("/api/admin/generation/jobs/job").json()["resolution"]
    assert result["action"] == "retry_publication"
    assert result["outbox_id"] == "delivery"
    assert result["cost"] == "No new AI request."


def test_prepare_replacement_cancels_old_work_but_requires_separate_paid_approval(client, admin_db):
    # Mutation: preparing the replacement authorizes it, or a stale snapshot cancels current work.
    stopped(admin_db, "attempt_allowance_exhausted")
    result = client.get("/api/admin/generation/jobs/job").json()["resolution"]
    assert result["action"] == "replacement"
    body = {"expected_generation": 1, "expected_state": "needs_attention", "reason": "Review replacement"}
    response = client.post("/api/admin/generation/jobs/job/replacement", json=body)
    assert response.status_code == 200, response.text
    preview = response.json()
    assert [item["key"] for item in preview["items"]] == ["candidate"]
    async def verify():
        async with admin_db() as db:
            assert (await db.get(GenerationOperation, "job")).state == "cancelled"
            assert await db.scalar(select(func.count()).select_from(GenerationOperation)) == 1
            assert await db.scalar(select(func.count()).select_from(ProviderAttempt)) == 0
    asyncio.run(verify())
    assert client.post("/api/admin/generation/jobs/job/replacement", json=body).status_code == 409
    approved = client.post("/api/admin/generation/campaigns/apply", json={
        "preview_id": preview["id"], "digest": preview["digest"], "reason": "Approve reviewed replacement"})
    assert approved.status_code == 200, approved.text
    assert len(approved.json()["jobs"]) == 1


def test_prepare_replacement_rolls_back_cancellation_when_facts_are_blocked(client, admin_db):
    # Mutation: cancellation survives a failed replacement preview, silently discarding unresolved work.
    stopped(admin_db, "attempt_allowance_exhausted")
    async def change():
        async with admin_db.begin() as db:
            (await db.get(GenerationCandidate, "candidate")).hold = "facts_unavailable"
    asyncio.run(change())
    response = client.post("/api/admin/generation/jobs/job/replacement", json={
        "expected_generation": 1, "expected_state": "needs_attention", "reason": "Review replacement"})
    assert response.status_code == 409
    assert client.get("/api/admin/generation/jobs/job").json()["job"]["state"] == "needs_attention"


def test_failed_deliveries_are_reviewable_in_their_own_league_and_content_scope(client, admin_db):
    # Mutation: failed delivery stays hidden behind a succeeded job, or filtering leaks another league.
    async def seed():
        async with admin_db.begin() as db:
            for ident, series, delivered in [("one", "series", False), ("two", "other", False), ("three", "series", True)]:
                db.add(ContentArtifact(id=ident, series_id=series, league_id="synthetic", feature="trade_story",
                    subject=ident, digest=ident, payload_json="{}", provenance="managed"))
                db.add(ArtifactHead(subject=ident, artifact_id=ident, revision=1))
                db.add(GenerationOutbox(id=ident, key="artifact:" + ident, kind="artifact",
                    payload_json=dump({"artifact_id": ident}), delivered=delivered, error="projection_failed"))
    asyncio.run(seed())
    response = client.get("/api/admin/generation/records/outbox?view=review&series_id=series&feature=trade_story")
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["records"]] == ["one"]
    assert response.json()["records"][0]["feature"] == "trade_story"


def test_replacement_never_substitutes_a_newer_week_for_the_failed_week(client, admin_db):
    # Mutation: match a replacement only by candidate key while its weekly facts have advanced.
    stopped(admin_db, "attempt_allowance_exhausted")
    async def change():
        async with admin_db.begin() as db:
            job = await db.get(GenerationOperation, "job")
            candidate = await db.get(GenerationCandidate, "candidate")
            job.feature = candidate.feature = "gm_rating_blurb"
            job.payload_json = dump({"season": 2026, "week": 3, "facts": {"owner_name": "Synthetic owner"}})
            candidate.payload_json = dump({"season": 2026, "week": 4, "facts": {"owner_name": "Synthetic owner"}})
    asyncio.run(change())
    result = client.get("/api/admin/generation/jobs/job").json()["resolution"]
    assert result["action"] == "support"
    assert client.post("/api/admin/generation/jobs/job/replacement", json={
        "expected_generation": 1, "expected_state": "needs_attention", "reason": "Review replacement"}).status_code == 409


def test_collection_cannot_remove_replacement_review_or_start_it_automatically(client, admin_db, monkeypatch):
    # Mutation: collection's subject_needs_attention blocks recovery, or observe clears the paid review gate.
    from app.services.generation.planner import observe
    from app.services.generation.worker import admit_automatic
    monkeypatch.setenv("TRADE_GRADER_ADMIN_EMAILS", "owner@test.local")
    stopped(admin_db, "attempt_allowance_exhausted")
    payload = {"facts": {"trade_id": "synthetic-trade"}, "season": 2026, "event_at": stamp()}
    async def collect():
        async with admin_db.begin() as db:
            return await observe(db, series_id="series", league_id="synthetic", feature="trade_story",
                subject="story", event="created", payload=payload)
    async def enable():
        async with admin_db.begin() as db:
            policy = await db.get(GenerationPolicy, "app")
            policy.value_json = dump({"paused": False, "features": {"trade_story": {"mode": "automatic"}}})
            job = await db.get(GenerationOperation, "job")
            row = await observe(db, series_id="series", league_id="synthetic", feature="trade_story",
                subject="story", event="created", payload=payload)
            job.candidate_key = row.key
            assert row.hold == "subject_needs_attention"
    asyncio.run(enable())
    response = client.post("/api/admin/generation/jobs/job/replacement", json={
        "expected_generation": 1, "expected_state": "needs_attention", "reason": "Review replacement"})
    assert response.status_code == 200, response.text
    asyncio.run(collect())
    asyncio.run(admit_automatic(admin_db))
    async def verify():
        async with admin_db() as db:
            assert await db.scalar(select(func.count()).select_from(GenerationOperation)) == 1
            assert await db.scalar(select(func.count()).select_from(ProviderAttempt)) == 0
            row = await db.get(GenerationCandidate, (await db.get(GenerationOperation, "job")).candidate_key)
            assert row.hold == "manual_approval_required"
    asyncio.run(verify())
    proposal = response.json()
    assert client.post("/api/admin/generation/campaigns/apply", json={
        "preview_id": proposal["id"], "digest": proposal["digest"], "reason": "Approve replacement"}).status_code == 200
