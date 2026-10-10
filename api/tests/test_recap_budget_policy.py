"""Mutations: relax strict caps, remove revision gate, write on GET, fake zero balances."""
import asyncio
import json

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.services.generation.recap_budget import RecapCaps, get_budget_view
from app.services.generation.recap_models import RecapBudgetPolicy
from app.services.generation.models import GenerationAudit
from tests.test_generation_admin import admin_db  # noqa: F401
from tests.test_generation_postgres import pgmaker  # noqa: F401

PATH = "/api/admin/generation/recap-budgets/series"


def test_caps_defaults():
    assert RecapCaps().model_dump() == dict(video_episode_microusd=3_000_000,
        video_month_microusd=15_000_000, combined_episode_microusd=5_000_000,
        combined_month_microusd=25_000_000)


@pytest.mark.parametrize("invalid", [0, -1, True, 1.2, "3", 9_007_199_254_740_992])
def test_caps_reject_invalid_units(invalid):
    with pytest.raises(ValidationError):
        RecapCaps(video_episode_microusd=invalid)


def test_caps_reject_unknown_fields():
    with pytest.raises(ValidationError):
        RecapCaps(unknown=1)


def test_defaults_read_only_and_enforced(client, admin_db):
    response = client.get(PATH, params={"episode_id": "episode"})
    assert response.status_code == 200
    value = response.json()
    assert value["revision"] == 0
    assert value["caps"] == RecapCaps().model_dump()
    assert value["episode_id"] == "episode"
    assert value["enforcement_state"] == {"active": True, "reason": ""}
    assert value["media_automation_enabled"] is False
    assert all(balance["known_microusd"] == balance["reserved_microusd"] == 0 for balance in value["balances"].values())
    async def check():
        async with admin_db() as db:
            assert await db.scalar(select(func.count()).select_from(RecapBudgetPolicy)) == 0
            view = await get_budget_view(db, "series", None, 1790814600)
            assert view["month_key"] == "2026-09"  # Oct 1 UTC is still September in Denver.
    asyncio.run(check())


def test_save_persists_and_audits_revision(client, admin_db):
    caps = RecapCaps(video_episode_microusd=2_500_000).model_dump()
    body = dict(caps=caps, expected_revision=0, reason="Reviewed ceiling", acknowledge_overcommitted=False)
    response = client.put(PATH, json=body)
    assert response.status_code == 200
    assert response.json()["revision"] == 1
    assert client.put(PATH, json=body).status_code == 409
    assert client.get(PATH).json()["caps"] == caps
    async def check():
        async with admin_db() as db:
            row = await db.get(RecapBudgetPolicy, "series")
            assert row.revision == 1 and json.loads(row.caps_json) == caps
            audit = await db.scalar(select(GenerationAudit).where(GenerationAudit.action == "recap_caps_saved"))
            assert audit.actor_id == "owner" and audit.reason == body["reason"]
            assert json.loads(audit.before_json)["caps"] == RecapCaps().model_dump()
            assert json.loads(audit.after_json)["caps"] == caps
    asyncio.run(check())


def test_unknown_series(client, admin_db):
    assert client.get(PATH.replace("series", "missing")).status_code == 404
    assert client.put(PATH.replace("series", "missing"), json=dict(caps={}, expected_revision=0,
        reason="Update", acknowledge_overcommitted=False)).status_code == 404


@pytest.mark.parametrize("invalid", [0, -1, True, 1.2, 9_007_199_254_740_992])
def test_api_rejects_invalid_caps(client, admin_db, invalid):
    assert client.put(PATH, json=dict(caps={"video_episode_microusd": invalid}, expected_revision=0,
        reason="Update", acknowledge_overcommitted=False)).status_code == 422


def test_nonadmin_forbidden(client, app, admin_db):
    from app.auth.deps import get_current_user, require_admin
    from types import SimpleNamespace
    app.dependency_overrides.pop(require_admin)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="member", is_admin=False)
    assert client.get(PATH).status_code == 403
    assert client.put(PATH, json={}).status_code == 403


def test_app_limit_visible_without_rewriting_setting(client, admin_db):
    from app.repositories.app_settings import set_monthly_budget
    async def seed():
        async with admin_db.begin() as db:
            await set_monthly_budget(db, 7.5)
    asyncio.run(seed())
    value = client.get(PATH).json()["app_limit"]
    assert value["month_microusd"] == value["balance"]["remaining_microusd"] == 7_500_000


def test_overcommit_response_is_structured_and_requires_acknowledgment(client, admin_db):
    # Mutation: collapse overcommit and revision conflicts into indistinguishable strings.
    from app.services.generation.recap_budget import reserve_plan
    from tests.test_recap_budget_ledger import NOW, allocation
    async def seed():
        async with admin_db.begin() as db:
            await reserve_plan(db, "episode", "series", "plan", [allocation()], NOW)
    asyncio.run(seed())
    body = dict(caps={"video_episode_microusd": 1_000_000}, expected_revision=0,
                reason="Lower", acknowledge_overcommitted=False)
    response = client.put(PATH, json=body)
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "recap_budget_overcommitted"
    assert detail["acknowledgment_required"] is True
    assert detail["affected"][0]["reserved_microusd"] == 2_000_000
    assert client.get(PATH).json()["revision"] == 0
    assert client.put(PATH, json={**body, "acknowledge_overcommitted": True}).status_code == 200


@pytest.mark.parametrize("extra", [{"unexpected": 1}, {"reason": "   "},
    {"expected_revision": True}, {"caps": {"unknown": 1}}])
def test_invalid_save_envelope(client, admin_db, extra):
    body = dict(caps={}, expected_revision=0, reason="Update", acknowledge_overcommitted=False)
    assert client.put(PATH, json={**body, **extra}).status_code == 422


def test_sqlite_migration_roundtrip_preserves_old_records(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from pathlib import Path
    from sqlalchemy import create_engine, text
    api = Path(__file__).resolve().parents[1]
    path = tmp_path / "migration.db"
    monkeypatch.setenv("TRADE_GRADER_DATABASE_URL", f"sqlite+aiosqlite:///{path}")
    config = Config(str(api / "alembic.ini"))
    config.set_main_option("script_location", str(api / "migrations"))
    command.upgrade(config, "0010_generation_submissions")
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as db:
        db.execute(text("INSERT INTO users (id, google_sub, email, is_admin) VALUES ('preserved', 'preserved', 'test@local', 0)"))
        db.execute(text("INSERT INTO league_memberships (id, user_id, league_id) VALUES ('membership', 'preserved', 'synthetic')"))
        db.execute(text("INSERT INTO provider_attempts (id, operation_id, stage, generation, request_digest, request_json, model, state, usage_state, usage_json, pricing_json, provider_request_id, error_code, created_at, settled_at) VALUES ('receipt','old',1,1,'hash','{}','synthetic','unknown','unknown','{}','{}','','',1,0)"))
        before = {table: db.execute(text(f"SELECT * FROM {table}")).all()
                  for table in ("users", "league_memberships", "provider_attempts")}
    command.upgrade(config, "0011_recap_budget")
    command.downgrade(config, "0010_generation_submissions")
    command.upgrade(config, "0011_recap_budget")
    with engine.connect() as db:
        for table, rows in before.items():
            assert db.execute(text(f"SELECT * FROM {table}")).all() == rows
        assert db.execute(text("SELECT count(*) FROM recap_budget_policies")).scalar() == 0
    engine.dispose()


@pytest.mark.asyncio
async def test_postgres_caps_revision_race(pgmaker):
    from app.services.generation.recap_budget import save_caps
    from app.services.generation.models import LeagueSeries
    from app.services.generation.store import Conflict
    async with pgmaker.begin() as db:
        db.add(LeagueSeries(id="race-series"))
    async def save():
        try:
            async with pgmaker.begin() as db:
                await save_caps(db, "race-series", RecapCaps(), 0, "owner", "Reviewed", False)
            return "saved"
        except Conflict:
            return "conflict"
    assert sorted(await asyncio.gather(save(), save())) == ["conflict", "saved"]


@pytest.mark.asyncio
async def test_postgres_budget_migration_roundtrip(pgmaker, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from pathlib import Path
    from sqlalchemy import text
    async with pgmaker.kw["bind"].begin() as db:
        await db.execute(text("DROP TABLE recap_budget_policies"))
        await db.execute(text("DROP TABLE IF EXISTS alembic_version"))
        await db.execute(text("CREATE TABLE alembic_version (version_num varchar(32) PRIMARY KEY)"))
        await db.execute(text("INSERT INTO alembic_version VALUES ('0010_generation_submissions')"))
        await db.execute(text("INSERT INTO users (id,google_sub,email,is_admin,created_at,updated_at) VALUES ('preserved','preserved','test@local',false,now(),now())"))
        await db.execute(text("INSERT INTO league_memberships (id,user_id,league_id,added_at) VALUES ('membership','preserved','synthetic',now())"))
        await db.execute(text("INSERT INTO provider_attempts (id,operation_id,stage,generation,request_digest,request_json,model,state,usage_state,usage_json,pricing_json,provider_request_id,error_code,created_at,settled_at) VALUES ('receipt','old',1,1,'hash','{}','synthetic','unknown','unknown','{}','{}','','',1,0)"))
        before = {table: (await db.execute(text(f"SELECT * FROM {table}"))).all()
                  for table in ("users", "league_memberships", "provider_attempts")}
    monkeypatch.setenv("TRADE_GRADER_DATABASE_URL", pgmaker.kw["bind"].url.render_as_string(hide_password=False))
    api = Path(__file__).resolve().parents[1]
    config = Config(str(api / "alembic.ini"))
    config.set_main_option("script_location", str(api / "migrations"))
    await asyncio.to_thread(command.upgrade, config, "0011_recap_budget")
    await asyncio.to_thread(command.downgrade, config, "0010_generation_submissions")
    await asyncio.to_thread(command.upgrade, config, "0011_recap_budget")
    async with pgmaker() as db:
        for table, rows in before.items():
            assert (await db.execute(text(f"SELECT * FROM {table}"))).all() == rows
        assert await db.scalar(select(func.count()).select_from(RecapBudgetPolicy)) == 0
