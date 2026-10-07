import asyncio
from types import SimpleNamespace

import pytest
from app.services.generation.administration import candidate_label
from app.services.generation.models import (
    ArtifactHead,
    ContentArtifact,
    GenerationCandidate,
    GenerationOperation,
    GenerationPolicy,
    LeagueSeason,
    stamp,
)
from app.services.generation.store import digest, dump

from tests.test_generation_admin import admin_db as catchup_db  # noqa: F401


def seed(maker):
    async def run():
        async with maker.begin() as db:
            season = await db.get(LeagueSeason, "synthetic")
            season.latest_week = 4
            for key, feature, week, event_at in [
                ("recap", "analyst", 4, stamp()),
                ("profile", "gm_rating_blurb", 4, stamp()),
                ("outlook", "franchise_blurb", 4, stamp()),
                ("trade", "trade_story", 5, stamp()),
                ("old-trade", "trade_story", 1, stamp() - 8 * 86400),
                ("old-profile", "gm_rating_blurb", 3, stamp()),
                ("finished", "analyst", 3, stamp()),
                ("pending", "analyst", 2, stamp()),
                ("future", "analyst", 6, stamp()),
            ]:
                payload = {"season": 2026, "week": week, "event_at": event_at,
                           "facts": {"owner_name": key}}
                db.add(GenerationCandidate(key=key, series_id="series", league_id="synthetic",
                    feature=feature, subject=key, event=f"2026:week:{week:02d}",
                    payload_json=dump(payload), digest=digest(payload), hold="historical_approval_required"))
            db.add(ContentArtifact(id="saved", series_id="series", league_id="synthetic",
                feature="analyst", subject="finished", payload_json=dump({"edition_type": "roast"}),
                digest="synthetic-digest", provenance="managed"))
            db.add(ArtifactHead(subject="finished", artifact_id="saved", revision=1))
            db.add(GenerationOperation(id="pending-job", kind="generation", subject="pending", league_id="synthetic",
                feature="analyst", state="needs_attention"))
    asyncio.run(run())


def test_catchup_previews_current_missing_content_without_buying(client, catchup_db):  # noqa: F811
    seed(catchup_db)
    response = client.post("/api/admin/generation/campaigns/catch-up/preview",
                           json={"reason": "Catch up all leagues"})
    assert response.status_code == 200
    assert {item["key"] for item in response.json()["items"]} == {"recap", "profile", "outlook", "trade"}
    assert response.json()["max_calls"] == 10
    assert len(client.get("/api/admin/generation/records/jobs").json()["records"]) == 2


def test_catchup_does_not_silently_truncate_at_record_page_boundary(client, catchup_db):  # noqa: F811
    seed(catchup_db)
    async def add():
        async with catchup_db.begin() as db:
            for n in range(105):
                payload = {"season": 2026, "week": 4, "event_at": stamp(), "facts": {"owner_name": str(n)}}
                db.add(GenerationCandidate(key=f"extra-{n}", series_id="series", league_id="synthetic",
                    feature="gm_rating_blurb", subject=f"extra-{n}", event="2026:week:05",
                    payload_json=dump(payload), digest=digest(payload)))
    asyncio.run(add())
    response = client.post("/api/admin/generation/campaigns/catch-up/preview", json={"reason": "Catch up"})
    assert response.status_code == 200
    assert len(response.json()["items"]) == 109


def test_catchup_unknown_league_filter_is_explicit(client, catchup_db):  # noqa: F811
    response = client.post("/api/admin/generation/campaigns/catch-up/preview",
                           json={"reason": "Catch up", "series_id": "missing"})
    assert response.status_code == 422


def test_trade_label_names_participants_instead_of_provider_id():
    row = SimpleNamespace(subject="internal-subject", payload_json=dump({"facts": {
        "trade_id": "internal-trade", "sides": [{"owner_name": "Alice"}, {"owner_name": "Bob"}]},
        "event_at": 1790812800}))
    assert candidate_label(row).startswith("Alice ↔ Bob")
    assert "internal-trade" not in candidate_label(row)


@pytest.mark.parametrize("blocked", ["policy", "old_scope", "saved_current"])
def test_catchup_skips_disabled_historical_and_already_current_profiles(client, catchup_db, blocked):  # noqa: F811
    seed(catchup_db)
    async def change():
        async with catchup_db.begin() as db:
            if blocked == "policy":
                policy = await db.get(GenerationPolicy, "app")
                policy.value_json = dump({"paused": False, "features": {"gm_rating_blurb": {"mode": "disabled"}}})
            elif blocked == "old_scope":
                row = await db.get(GenerationCandidate, "profile")
                payload = {"season": 2026, "week": 4, "facts": {"owner_name": "Profile"}, "target": {"scope": "2025"}}
                row.payload_json, row.digest = dump(payload), digest(payload)
            else:
                db.add(ContentArtifact(id="current-profile", series_id="series", league_id="synthetic",
                    feature="gm_rating_blurb", subject="profile", digest="synthetic-current", provenance="legacy_unreviewed",
                    payload_json=dump({"generation_period": {"season": 2026, "week": 4}})))
                db.add(ArtifactHead(subject="profile", artifact_id="current-profile", revision=1))
    asyncio.run(change())
    response = client.post("/api/admin/generation/campaigns/catch-up/preview", json={"reason": "Catch up"})
    assert response.status_code == 200
    assert "profile" not in {item["key"] for item in response.json()["items"]}


def test_catchup_batch_can_apply_once_without_per_item_approvals(client, catchup_db):  # noqa: F811
    seed(catchup_db)
    reviewed = client.post("/api/admin/generation/campaigns/catch-up/preview", json={"reason": "Catch up"}).json()
    body = {"preview_id": reviewed["id"], "digest": reviewed["digest"], "reason": "Approve catch-up batch"}
    first = client.post("/api/admin/generation/campaigns/apply", json=body)
    second = client.post("/api/admin/generation/campaigns/apply", json=body)
    assert first.status_code == second.status_code == 200
    assert len(first.json()["jobs"]) == 4
    assert first.json() == second.json()
