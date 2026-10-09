"""Review means missing, approvable content; durable observations are not a queue."""
import asyncio
import json

import pytest
from sqlalchemy import func, select

from app.services.generation.models import (
    ArtifactHead,
    ContentArtifact,
    GenerationCandidate,
    GenerationControl,
    GenerationOperation,
    GenerationPolicy,
    LeagueSeason,
    LeagueSeries,
    ProviderAttempt,
    stamp,
)
from app.services.generation.store import digest, dump

from tests.test_generation_admin import admin_db as review_db  # noqa: F401


def add_candidate(db, key, *, feature="gm_rating_blurb", hold="", week=4, observed_at=1, **extra):
    payload = {"facts": {"owner_name": key}, "season": 2026, "week": week, "event_at": stamp(), **extra}
    row = GenerationCandidate(key=key, series_id="series", league_id="synthetic", feature=feature,
        subject=key, event=f"2026:week:{week:02d}", payload_json=dump(payload), digest=digest(payload),
        hold=hold, eligible_at=stamp(), observed_at=observed_at)
    db.add(row)
    return row


def add_artifact(db, row, payload):
    artifact = ContentArtifact(id="saved-" + row.key, series_id=row.series_id, league_id=row.league_id,
        subject=row.subject, feature=row.feature, payload_json=dump(payload), digest=digest(payload),
        provenance="legacy_unreviewed", facts_json=dump({"facts": {"week": 4}}))
    db.add(artifact)
    db.add(ArtifactHead(subject=row.subject, artifact_id=artifact.id, revision=1))


def configure_automatic(db, *, gm_mode="automatic"):
    async def run():
        (await db.get(GenerationPolicy, "app")).value_json = dump({"paused": False, "features": {
            feature: {"mode": gm_mode if feature == "gm_rating_blurb" else "automatic"}
            for feature in ("trade_story", "gm_rating_blurb", "franchise_blurb", "analyst")}})
        (await db.get(LeagueSeason, "synthetic")).latest_week = 4
        series = await db.get(LeagueSeries, "series")
        series.activated_at, series.activation_week = stamp() - 1000, 1
    return run()


def test_review_filters_before_pagination_and_does_not_queue_work(client, review_db):  # noqa: F811
    async def seed():
        async with review_db.begin() as db:
            await configure_automatic(db, gm_mode="manual")
            for index in range(105):
                row = add_candidate(db, f"done-{index}", feature="trade_story", observed_at=1000 + index)
                add_artifact(db, row, {"verdict": "Already written", "body": "Saved prose"})
            for state in ("queued", "running", "held", "needs_attention"):
                row = add_candidate(db, state, observed_at=900)
                db.add(GenerationOperation(id="operation-" + state, kind="generation",
                    subject=row.subject, league_id=row.league_id, state=state))
            add_candidate(db, "blocked", hold="subject_needs_attention", observed_at=800)
            add_candidate(db, "automatic", feature="trade_story", observed_at=700)
            add_candidate(db, "manual", observed_at=10)
            add_candidate(db, "historical", feature="franchise_blurb", hold="historical_approval_required", observed_at=9)
            add_candidate(db, "missed", feature="franchise_blurb", week=3, observed_at=8)
    asyncio.run(seed())
    first = client.get("/api/admin/generation/records/candidates?view=review&limit=2").json()
    second = client.get("/api/admin/generation/records/candidates?view=review&limit=2&offset=2").json()
    assert [row["key"] for row in first["records"]] == ["manual", "historical"]
    assert first["next_offset"] == 2
    assert [row["key"] for row in second["records"]] == ["missed"]
    assert second["next_offset"] is None
    combined = first["records"] + second["records"]
    assert all(row["availability"] == "available" and row["reviewable"] for row in combined)
    assert [row["review_reason"] for row in combined] == [
        "manual_approval_required", "historical_approval_required", "missed_event_approval_required"]
    raw = client.get("/api/admin/generation/records/candidates?limit=100").json()
    assert len(raw["records"]) == 100 and raw["records"][0]["availability"] == "completed"
    async def counts():
        async with review_db() as db:
            assert await db.scalar(select(func.count()).select_from(GenerationOperation)) == 5
            assert await db.scalar(select(func.count()).select_from(ProviderAttempt)) == 0
            assert (await db.get(GenerationCandidate, "automatic")).eligible_at > 0
    asyncio.run(counts())


@pytest.mark.parametrize("completion", ["legacy_story", "legacy_analyst", "current_profile", "successful_period"])
def test_semantically_completed_content_is_unselectable_and_preview_rejects(client, review_db, completion):  # noqa: F811
    async def seed():
        async with review_db.begin() as db:
            feature = {"legacy_story": "trade_story", "legacy_analyst": "analyst"}.get(completion, "gm_rating_blurb")
            row = add_candidate(db, "complete", feature=feature, hold="historical_approval_required")
            if completion == "successful_period":
                db.add(GenerationOperation(id="finished", kind="generation", league_id=row.league_id,
                    subject=row.subject, feature=row.feature, state="succeeded", request_digest="older-facts",
                    payload_json=dump({"season": 2026, "week": 4, "facts": {"old": True}})))
                # A more recent cancelled attempt must not conceal prior completion.
                db.add(GenerationOperation(id="later", kind="generation", league_id=row.league_id,
                    subject=row.subject, feature=row.feature, state="cancelled", created_at=stamp() + 1))
            else:
                content = {"edition_type": "roast"} if completion == "legacy_analyst" else (
                    {"generation_period": {"season": 2026, "week": 4}} if completion == "current_profile" else {"body": "Saved"})
                add_artifact(db, row, content)
    asyncio.run(seed())
    listing = client.get("/api/admin/generation/records/candidates").json()
    assert listing["records"][0]["availability"] == "completed"
    assert not client.get("/api/admin/generation/records/candidates?view=review").json()["records"]
    response = client.post("/api/admin/generation/campaigns/preview", json={
        "candidates": ["complete"], "reason": "Preview selected work"})
    assert response.status_code == 409 and "already completed" in response.json()["detail"]


def test_legacy_profile_without_period_does_not_invent_completion(client, review_db):  # noqa: F811
    async def seed():
        async with review_db.begin() as db:
            row = add_candidate(db, "uncertain-profile", hold="historical_approval_required")
            add_artifact(db, row, {"blurb": "Legacy profile with no verified generation period"})
    asyncio.run(seed())
    row = client.get("/api/admin/generation/records/candidates?view=review").json()["records"][0]
    assert row["availability"] == "available" and row["review_reason"] == "historical_approval_required"


def test_manually_written_preseason_summary_does_not_become_missing_after_facts_change(client, review_db):  # noqa: F811
    async def seed():
        async with review_db.begin() as db:
            row = add_candidate(db, "preseason", week=0, hold="historical_approval_required")
            add_artifact(db, row, {"blurb": "Saved before the season", "generation_period": {"season": 2026, "week": 0}})
    asyncio.run(seed())
    row = client.get("/api/admin/generation/records/candidates").json()["records"][0]
    assert row["availability"] == "completed" and not row["reviewable"]


def test_completion_after_preview_cannot_buy_the_same_event_again(client, review_db):  # noqa: F811
    async def seed():
        async with review_db.begin() as db:
            add_candidate(db, "racing", hold="historical_approval_required")
    asyncio.run(seed())
    manifest = client.post("/api/admin/generation/campaigns/preview", json={
        "candidates": ["racing"], "reason": "Preview missing profile"}).json()
    async def finish_elsewhere():
        async with review_db.begin() as db:
            row = await db.get(GenerationCandidate, "racing")
            db.add(GenerationOperation(id="completed-elsewhere", kind="generation", league_id=row.league_id,
                subject=row.subject, feature=row.feature, state="succeeded", payload_json=row.payload_json,
                request_digest=row.digest))
    asyncio.run(finish_elsewhere())
    response = client.post("/api/admin/generation/campaigns/apply", json={
        "preview_id": manifest["id"], "digest": manifest["digest"], "reason": "Approve reviewed set"})
    assert response.status_code == 409 and "already completed" in response.json()["detail"]
    assert len(client.get("/api/admin/generation/records/jobs").json()["records"]) == 2


def test_current_artifact_correction_remains_explicitly_approvable(client, review_db):  # noqa: F811
    async def seed():
        async with review_db.begin() as db:
            row = add_candidate(db, "editable", feature="analyst")
            add_artifact(db, row, {"season": 2026, "week": 4, "edition_type": "roast",
                "facts": {"week": 4}, "markdown": "Saved original"})
    asyncio.run(seed())
    proposal = client.post("/api/admin/generation/artifacts/saved-editable/correction", json={
        "expected_artifact": "saved-editable", "reason": "Correct the stated result"}).json()
    rows = client.get("/api/admin/generation/records/candidates?view=review").json()["records"]
    assert len(rows) == 1 and rows[0]["key"] == proposal["key"]
    assert rows[0]["review_reason"] == "correction_approval_required"
    manifest = client.post("/api/admin/generation/campaigns/preview", json={
        "candidates": [proposal["key"]], "reason": "Review exact correction"}).json()
    response = client.post("/api/admin/generation/campaigns/apply", json={
        "preview_id": manifest["id"], "digest": manifest["digest"], "reason": "Approve exact correction"})
    assert response.status_code == 200 and len(response.json()["jobs"]) == 1


@pytest.mark.parametrize("block", ["policy", "feature", "series", "capability", "provider", "breaker", "hold"])
def test_review_and_direct_preview_preserve_paid_holds(client, review_db, block):  # noqa: F811
    async def seed():
        async with review_db.begin() as db:
            add_candidate(db, "restricted", hold="historical_approval_required")
            if block == "policy":
                (await db.get(GenerationPolicy, "app")).value_json = dump({"paused": True})
            elif block == "feature":
                (await db.get(GenerationPolicy, "app")).value_json = dump({"paused": False,
                    "features": {"gm_rating_blurb": {"mode": "disabled"}}})
            elif block == "series":
                (await db.get(LeagueSeries, "series")).hold = "owner_paused"
            elif block == "capability":
                (await db.get(LeagueSeason, "synthetic")).verified_at = 0
            elif block == "provider":
                (await db.get(GenerationControl, "global")).provider_hold = "accounting_attention"
            elif block == "breaker":
                (await db.get(GenerationControl, "global")).breakers_json = dump({"gm_rating_blurb": {"open": True}})
            else:
                (await db.get(GenerationCandidate, "restricted")).hold = "subject_needs_attention"
    asyncio.run(seed())
    row = client.get("/api/admin/generation/records/candidates").json()["records"][0]
    assert row["availability"] == "blocked" and row["blocked_by"]
    assert not client.get("/api/admin/generation/records/candidates?view=review").json()["records"]
    response = client.post("/api/admin/generation/campaigns/preview", json={
        "candidates": ["restricted"], "reason": "Review selected content"})
    assert response.status_code == 409


def test_series_manual_override_survives_automatic_shared_defaults(client, review_db):  # noqa: F811
    async def seed():
        async with review_db.begin() as db:
            await configure_automatic(db)
            add_candidate(db, "manual-override")
            db.add(GenerationPolicy(scope="series:series", value_json=dump({
                "features": {"gm_rating_blurb": {"mode": "manual"}}})))
    asyncio.run(seed())
    row = client.get("/api/admin/generation/records/candidates?view=review").json()["records"][0]
    assert row["key"] == "manual-override" and row["review_reason"] == "manual_approval_required"


@pytest.mark.parametrize("feature", ["gm_rating_blurb", "franchise_blurb", "analyst"])
def test_automatic_admission_does_not_rebuy_manual_completion_but_next_week_can_run(review_db, feature):  # noqa: F811
    from app.services.generation.planner import observe
    from app.services.generation.worker import admit_automatic

    async def run():
        async with review_db.begin() as db:
            await configure_automatic(db)
            payload = {"facts": {"owner_name": "Owner"}, "season": 2026, "week": 4, "event_at": stamp()}
            row = await observe(db, series_id="series", league_id="synthetic", feature=feature,
                subject="manually-completed", event="2026:week:04", payload=payload)
            add_artifact(db, row, {"edition_type": "roast"} if feature == "analyst" else {
                "generation_period": {"season": 2026, "week": 4}, "blurb": "Already generated"})
            key = row.key
        await admit_automatic(review_db)
        async with review_db() as db:
            assert await db.scalar(select(func.count()).select_from(GenerationOperation)) == 1
            assert (await db.get(GenerationCandidate, key)).eligible_at == 0
        if feature.endswith("blurb"):
            async with review_db.begin() as db:
                (await db.get(LeagueSeason, "synthetic")).latest_week = 5
                await observe(db, series_id="series", league_id="synthetic", feature=feature,
                    subject="manually-completed", event="2026:week:05", payload={**payload, "week": 5})
            await admit_automatic(review_db)
            async with review_db() as db:
                jobs = (await db.scalars(select(GenerationOperation).where(
                    GenerationOperation.subject == "manually-completed"))).all()
                assert len(jobs) == 1 and jobs[0].state == "queued" and jobs[0].actor_kind == "scheduler"
                assert json.loads(jobs[0].payload_json)["week"] == 5
        async with review_db() as db:
            assert await db.scalar(select(func.count()).select_from(ProviderAttempt)) == 0
    asyncio.run(run())


def test_catchup_skips_semantic_completion_and_blocked_work_without_failing_valid_items(client, review_db):  # noqa: F811
    async def seed():
        async with review_db.begin() as db:
            await configure_automatic(db)
            completed = add_candidate(db, "done", hold="historical_approval_required")
            db.add(GenerationOperation(id="written", kind="generation", league_id=completed.league_id,
                subject=completed.subject, feature=completed.feature, state="succeeded", request_digest="old-facts",
                payload_json=dump({"season": 2026, "week": 4, "facts": {"old": True}})))
            add_candidate(db, "missing", hold="historical_approval_required")
            add_candidate(db, "paused-feature", feature="franchise_blurb", hold="historical_approval_required")
            policy = await db.get(GenerationPolicy, "app")
            values = json.loads(policy.value_json)
            values["features"]["franchise_blurb"]["paused"] = True
            policy.value_json = dump(values)
    asyncio.run(seed())
    response = client.post("/api/admin/generation/campaigns/catch-up/preview", json={"reason": "Catch up missing current content"})
    assert response.status_code == 200
    assert {item["key"] for item in response.json()["items"]} == {"missing"}
    assert response.json()["skipped"] == {"already_completed": 1, "feature_paused": 1}
    assert len(client.get("/api/admin/generation/records/jobs").json()["records"]) == 2


def seed_legacy_without_archived_facts(maker, *, source="matching"):
    async def seed():
        async with maker.begin() as db:
            # This is the artifact identity, not a persisted candidate.
            origin = GenerationCandidate(key="legacy", series_id="series", league_id="synthetic",
                subject="legacy", feature="gm_rating_blurb")
            add_artifact(db, origin, {"blurb": "Saved legacy profile", "generation_period": {"season": 2026, "week": 4}})
            (await db.get(ContentArtifact, "saved-legacy")).facts_json = dump({"facts": {}})
            if source != "missing":
                row = add_candidate(db, "latest-source", hold="historical_approval_required")
                row.subject = "legacy"
                if source == "other_league":
                    row.league_id = "different-league"
                elif source == "other_feature":
                    row.feature = "franchise_blurb"
                elif source == "only_correction":
                    row.event = "correction:earlier"
                elif source == "invalid_digest":
                    row.digest = "corrupt"
    asyncio.run(seed())


def test_legacy_correction_copies_matching_current_facts_without_reopening_ordinary_approval(client, review_db):  # noqa: F811
    seed_legacy_without_archived_facts(review_db)
    response = client.post("/api/admin/generation/artifacts/saved-legacy/correction", json={
        "expected_artifact": "saved-legacy", "reason": "Correct the profile using refreshed league facts"})
    assert response.status_code == 200
    proposal = response.json()
    copied = json.loads(proposal["payload_json"])
    assert copied["facts"] == {"owner_name": "latest-source"}
    assert copied["correction_base"] == "saved-legacy"
    assert copied["previous_content"] == {"blurb": "Saved legacy profile", "generation_period": {"season": 2026, "week": 4}}
    async def change_source():
        async with review_db.begin() as db:
            source = await db.get(GenerationCandidate, "latest-source")
            assert "correction_base" not in json.loads(source.payload_json)
            payload = json.loads(source.payload_json)
            payload["facts"] = {"owner_name": "Later facts"}
            source.payload_json, source.digest = dump(payload), digest(payload)
    asyncio.run(change_source())
    assert client.post("/api/admin/generation/campaigns/preview", json={
        "candidates": ["latest-source"], "reason": "Ordinary completed content"}).status_code == 409
    manifest = client.post("/api/admin/generation/campaigns/preview", json={
        "candidates": [proposal["key"]], "reason": "Review the explicit correction"}).json()
    applied = client.post("/api/admin/generation/campaigns/apply", json={
        "preview_id": manifest["id"], "digest": manifest["digest"], "reason": "Approve exact correction"})
    assert applied.status_code == 200
    job = client.get(f'/api/admin/generation/jobs/{applied.json()["jobs"][0]}').json()["job"]
    assert json.loads(job["payload_json"])["facts"] == copied["facts"]


@pytest.mark.parametrize("source", ["missing", "other_league", "other_feature", "only_correction", "invalid_digest"])
def test_legacy_correction_refuses_missing_or_mismatched_current_facts(client, review_db, source):  # noqa: F811
    seed_legacy_without_archived_facts(review_db, source=source)
    response = client.post("/api/admin/generation/artifacts/saved-legacy/correction", json={
        "expected_artifact": "saved-legacy", "reason": "Correct this saved profile"})
    assert response.status_code == 409 and "Correction facts are unavailable" in response.json()["detail"]


def test_legacy_correction_still_rejects_changed_artifact_head_at_apply(client, review_db):  # noqa: F811
    seed_legacy_without_archived_facts(review_db)
    proposal = client.post("/api/admin/generation/artifacts/saved-legacy/correction", json={
        "expected_artifact": "saved-legacy", "reason": "Correct this saved profile"}).json()
    manifest = client.post("/api/admin/generation/campaigns/preview", json={
        "candidates": [proposal["key"]], "reason": "Review exact correction"}).json()
    async def advance():
        async with review_db.begin() as db:
            db.add(ContentArtifact(id="newer-legacy", series_id="series", league_id="synthetic",
                subject="legacy", feature="gm_rating_blurb", payload_json=dump({"blurb": "Revised elsewhere"}),
                digest="new-content", provenance="managed", revision=2))
            head = await db.get(ArtifactHead, "legacy")
            head.artifact_id, head.revision = "newer-legacy", 2
    asyncio.run(advance())
    response = client.post("/api/admin/generation/campaigns/apply", json={
        "preview_id": manifest["id"], "digest": manifest["digest"], "reason": "Approve correction"})
    assert response.status_code == 409 and "changed" in response.json()["detail"]
