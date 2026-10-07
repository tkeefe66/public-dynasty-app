import asyncio

from app.services.generation.models import (
    GenerationCandidate,
    GenerationControl,
    GenerationOperation,
)

from tests.test_generation_admin import admin_db as bulk_db  # noqa: F401


def seed(maker):
    async def add():
        async with maker.begin() as db:
            for ident, state, reason in [("held-one", "held", "worker_shutdown"),
                    ("held-two", "held", "worker_shutdown"), ("failed", "needs_attention", "execution_failed")]:
                db.add(GenerationOperation(id=ident, kind="generation", league_id="synthetic",
                    series_id="series", feature="gm_rating_blurb", subject=ident,
                    state=state, reason=reason, max_calls=2, generation=1))
    asyncio.run(add())


def test_bulk_resume_skips_failed_jobs_and_requires_exact_preview(client, bulk_db):  # noqa: F811
    seed(bulk_db)
    response = client.post("/api/admin/generation/jobs/batch/preview", json={
        "job_ids": ["held-one", "held-two", "failed"], "action": "resume", "reason": "Resume batch"})
    assert response.status_code == 200
    manifest = response.json()
    assert {i["id"] for i in manifest["items"]} == {"held-one", "held-two"}
    assert manifest["skipped"][0]["id"] == "failed"
    assert manifest["remaining_calls"] == 4
    body = {"preview_id": manifest["id"], "digest": manifest["digest"], "reason": "Confirm resume"}
    first = client.post("/api/admin/generation/jobs/batch/apply", json=body)
    second = client.post("/api/admin/generation/jobs/batch/apply", json=body)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert len(first.json()["jobs"]) == 2


def test_bulk_cancel_checks_observed_job_version(client, bulk_db):  # noqa: F811
    seed(bulk_db)
    manifest = client.post("/api/admin/generation/jobs/batch/preview", json={
        "job_ids": ["held-one", "held-two"], "action": "cancel", "reason": "Cancel batch"}).json()
    client.post("/api/admin/generation/jobs/held-one", json={"action": "cancel",
        "expected_generation": 1, "expected_state": "held", "reason": "Changed elsewhere"})
    response = client.post("/api/admin/generation/jobs/batch/apply", json={
        "preview_id": manifest["id"], "digest": manifest["digest"], "reason": "Confirm cancellation"})
    assert response.status_code == 409
    assert client.get("/api/admin/generation/jobs/held-two").json()["job"]["state"] == "held"


def test_bulk_resume_keeps_open_breaker_blocked(client, bulk_db):  # noqa: F811
    seed(bulk_db)
    async def block():
        async with bulk_db.begin() as db:
            control = await db.get(GenerationControl, "global")
            control.breakers_json = '{"gm_rating_blurb":{"open":true}}'
    asyncio.run(block())
    response = client.post("/api/admin/generation/jobs/batch/preview", json={
        "job_ids": ["held-one"], "action": "resume", "reason": "Resume batch"})
    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["skipped"][0]["reason"] == "feature_breaker_open"


def test_candidates_report_existing_job_availability(client, bulk_db):  # noqa: F811
    seed(bulk_db)
    async def add():
        async with bulk_db.begin() as db:
            db.add(GenerationCandidate(key="candidate", series_id="series", league_id="synthetic",
                feature="gm_rating_blurb", subject="held-one", event="created", payload_json="{}", digest="facts"))
    asyncio.run(add())
    response = client.get("/api/admin/generation/records/candidates")
    assert response.status_code == 200
    assert response.json()["records"][0]["availability"] == "held"
