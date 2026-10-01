import asyncio
from types import SimpleNamespace

import pytest
from app.auth.deps import get_current_user, require_admin
from app.db.session import get_db
from app.services.generation.models import GenerationCandidate
from app.services.generation.store import digest, dump

from tests.test_generation_gateway import seed_job


@pytest.fixture
def admin_db(app, maker):
    asyncio.run(seed_job(maker))
    async def isolated():
        async with maker.begin() as db:
            yield db
    app.dependency_overrides[get_db] = isolated
    app.dependency_overrides[require_admin] = lambda: SimpleNamespace(id="owner", is_admin=True)
    yield maker
    app.dependency_overrides.pop(get_db, None)


def test_non_owner_cannot_read_or_mutate_control(client, app, admin_db):
    app.dependency_overrides.pop(require_admin)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="member", is_admin=False)
    assert client.get("/api/admin/generation").status_code == 403
    assert client.put("/api/admin/generation/policy/app", json={
        "expected_revision": 1, "value": {"paused": False}, "reason": "try"}).status_code == 403


def test_policy_form_cannot_overwrite_a_newer_revision(client, admin_db):
    body = {"expected_revision": 1, "value": {"paused": True}, "reason": "Pause while checking"}
    first = client.put("/api/admin/generation/policy/app", json=body)
    assert first.status_code == 200
    assert first.json()["effective"]["policy"]["paused"] is True
    assert client.put("/api/admin/generation/policy/app", json={**body, "value": {"paused": False}}).status_code == 409
    current = client.get("/api/admin/generation/policy/app").json()
    assert current["revision"] == 2
    assert current["effective"]["policy"]["paused"] is True


def candidate(maker):
    async def seed():
        async with maker.begin() as db:
            payload = {"facts": {"test": True}, "week": 2}
            db.add(GenerationCandidate(key="candidate", series_id="series", league_id="synthetic",
                feature="gm_rating_blurb", subject="different-subject", event="2026:week:02",
                payload_json=dump(payload), digest=digest(payload), hold="historical_approval_required"))
    asyncio.run(seed())


def test_campaign_preview_binds_exact_candidate_and_policy_versions(client, admin_db):
    candidate(admin_db)
    preview = client.post("/api/admin/generation/campaigns/preview",
        json={"candidates": ["candidate"], "reason": "Review initial profile"}).json()
    assert preview["max_calls"] == 2
    client.put("/api/admin/generation/policy/app", json={
        "expected_revision": 1, "value": {"paused": False, "refresh_interval_seconds": 900},
        "reason": "Another owner changes policy"})
    response = client.post("/api/admin/generation/campaigns/apply",
        json={"preview_id": preview["id"], "digest": preview["digest"], "reason": "Approve"})
    assert response.status_code == 409


def test_campaign_apply_is_idempotent_and_requires_its_preview(client, admin_db):
    candidate(admin_db)
    preview = client.post("/api/admin/generation/campaigns/preview",
        json={"candidates": ["candidate"], "reason": "Review initial profile"}).json()
    body = {"preview_id": preview["id"], "digest": preview["digest"], "reason": "Approve exact set"}
    first = client.post("/api/admin/generation/campaigns/apply", json=body)
    second = client.post("/api/admin/generation/campaigns/apply", json=body)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert len(first.json()["jobs"]) == 1


def test_failed_projection_retry_reuses_artifact_and_rejects_stale_state(client, admin_db):
    from app.services.generation.models import GenerationOutbox
    async def seed():
        async with admin_db.begin() as db:
            db.add(GenerationOutbox(id="projection", key="saved-artifact", kind="artifact",
                payload_json=dump({"artifact_id": "saved"}), error="projection_failed"))
    asyncio.run(seed())
    body = {"expected_error": "projection_failed", "reason": "Storage repaired"}
    response = client.post("/api/admin/generation/outbox/projection/retry", json=body)
    assert response.status_code == 200
    assert response.json()["error"] == ""
    assert response.json()["payload_json"] == dump({"artifact_id": "saved"})
    assert client.post("/api/admin/generation/outbox/projection/retry", json=body).status_code == 409


def test_correction_proposal_requires_current_artifact_and_does_not_create_job(client, admin_db):
    from app.services.generation.artifacts import import_artifact
    async def seed():
        async with admin_db.begin() as db:
            return (await import_artifact(db, series_id="series", league_id="synthetic", feature="analyst",
                subject="edition", payload={"season": 2026, "week": 2, "facts": {"week": 2},
                    "markdown": "Original edition"}, target={}, facts={"week": 2})).id
    artifact = asyncio.run(seed())
    body = {"expected_artifact": artifact, "reason": "Correct the stated result"}
    response = client.post(f"/api/admin/generation/artifacts/{artifact}/correction", json=body)
    assert response.status_code == 200
    assert response.json()["hold"] == "historical_approval_required"
    assert len(client.get("/api/admin/generation/records/jobs").json()["records"]) == 1
    assert client.post(f"/api/admin/generation/artifacts/{artifact}/correction",
        json={**body, "expected_artifact": "stale"}).status_code == 409


def test_registry_keeps_leagues_with_no_current_members(client, admin_db):
    from sqlalchemy import delete
    from app.db.models import LeagueMembership
    async def remove():
        async with admin_db.begin() as db:
            await db.execute(delete(LeagueMembership))
    asyncio.run(remove())
    response = client.get("/api/admin/generation/leagues").json()
    assert response["records"][0]["id"] == "series"
    assert response["records"][0]["members"] == 0
