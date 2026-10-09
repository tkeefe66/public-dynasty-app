"""Failed first imports must remain identifiable before registry creation."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.auth.deps import require_admin
from app.db.models import LeagueMembership, User
from app.db.session import get_db
from app.services.generation.models import (
    GenerationCandidate, GenerationOperation, LeagueSeason, LeagueSeries,
)


LEAGUE = "470.l.123456"


@pytest.fixture
def named_import_db(app, maker):
    async def seed():
        async with maker.begin() as db:
            db.add(User(id="member", google_sub="member", email="member@test.local"))
            db.add(LeagueMembership(
                id="membership", user_id="member", league_id=LEAGUE,
                league_name="Example Yahoo League",
                added_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ))
            db.add(GenerationOperation(
                id="failed-import", kind="refresh", league_id=LEAGUE,
                actor_id="member", state="needs_attention", reason="execution_failed",
            ))
            db.add(GenerationCandidate(
                key="example-candidate", series_id="", league_id=LEAGUE,
                feature="gm_rating_blurb", subject="example-owner", event="2026:week:01",
                payload_json='{"facts":{"owner_name":"Example Owner"}}', digest="example",
            ))

    asyncio.run(seed())

    async def isolated():
        async with maker.begin() as db:
            yield db

    app.dependency_overrides[get_db] = isolated
    app.dependency_overrides[require_admin] = lambda: SimpleNamespace(id="owner", is_admin=True)
    yield maker
    app.dependency_overrides.pop(get_db, None)


def test_failed_import_uses_captured_name_without_creating_registry(client, named_import_db):
    jobs = client.get("/api/admin/generation/records/jobs?state=needs_attention").json()["records"]
    assert jobs[0]["league_name"] == "Example Yahoo League"
    assert jobs[0]["league_id"] == LEAGUE
    assert jobs[0]["series_id"] == ""
    detail = client.get("/api/admin/generation/jobs/failed-import").json()
    assert detail["job"]["league_name"] == "Example Yahoo League"
    candidates = client.get("/api/admin/generation/records/candidates").json()["records"]
    assert candidates[0]["league_name"] == "Example Yahoo League"

    async def remains_unregistered():
        async with named_import_db() as db:
            assert await db.scalar(select(func.count()).select_from(LeagueSeries)) == 0
            assert await db.scalar(select(func.count()).select_from(LeagueSeason)) == 0
            assert (await db.get(GenerationOperation, "failed-import")).state == "needs_attention"

    asyncio.run(remains_unregistered())


def test_registered_name_takes_precedence_over_old_membership_name(client, named_import_db):
    async def register():
        async with named_import_db.begin() as db:
            db.add(LeagueSeries(id="series", name="Current Registry Name"))
            db.add(LeagueSeason(
                league_id=LEAGUE, provider="yahoo", provider_key=LEAGUE,
                series_id="series", season=2026,
            ))

    asyncio.run(register())
    detail = client.get("/api/admin/generation/jobs/failed-import").json()
    assert detail["job"]["league_name"] == "Current Registry Name"


def test_missing_name_keeps_original_league_id_for_ui_fallback(client, named_import_db):
    async def clear_name():
        async with named_import_db.begin() as db:
            (await db.get(LeagueMembership, "membership")).league_name = "   "

    asyncio.run(clear_name())
    detail = client.get("/api/admin/generation/jobs/failed-import").json()["job"]
    assert detail["league_name"] is None
    assert detail["league_id"] == LEAGUE
