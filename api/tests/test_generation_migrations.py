import asyncio
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.db.base import Base
from app.db.models import User
from app.services.generation.models import GenerationControl
from sqlalchemy import select, text

from tests.test_generation_postgres import pgmaker  # noqa: F401


@pytest.mark.asyncio
async def test_additive_migrations_preserve_identity_and_seed_paused(pgmaker, monkeypatch):  # noqa: F811
    async with pgmaker.kw["bind"].begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    monkeypatch.setenv("TRADE_GRADER_DATABASE_URL", pgmaker.kw["bind"].url.render_as_string(hide_password=False))
    api = Path(__file__).resolve().parents[1]
    config = Config(str(api / "alembic.ini"))
    config.set_main_option("script_location", str(api / "migrations"))
    await asyncio.to_thread(command.upgrade, config, "0008_yahoo_connections")
    async with pgmaker.begin() as db:
        db.add(User(id="preserved", google_sub="preserved", email="preserved@test.local"))
    async with pgmaker() as db:
        before = (await db.execute(select(User.__table__))).mappings().all()
    await asyncio.to_thread(command.upgrade, config, "head")
    async with pgmaker() as db:
        assert (await db.execute(select(User.__table__))).mappings().all() == before
        assert (await db.get(GenerationControl, "global")).hold == "activation_required"
