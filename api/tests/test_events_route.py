from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.deps import get_current_user
from app.db.base import Base
from app.db.models import PageEvent, User
from app.db.session import get_db
from app.main import app as fastapi_app
from sqlalchemy import select


@pytest.fixture()
def client(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'evr.db'}")

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        m = async_sessionmaker(engine, expire_on_commit=False)
        async with m() as db:
            db.add(User(id="u1", google_sub="g1", email="a@t.local"))
            await db.commit()
        return m

    maker = asyncio.run(_setup())

    async def _override_get_db():
        async with maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    fastapi_app.dependency_overrides[get_db] = _override_get_db
    fastapi_app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="u1")
    try:
        yield TestClient(fastapi_app), maker
    finally:
        fastapi_app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


def test_post_event_stores_normalized(client):
    c, maker = client
    r = c.post("/api/events", json={"path": "/league/77/gm?x=1"})
    assert r.status_code == 204

    async def _read():
        async with maker() as db:
            return (await db.execute(select(PageEvent))).scalars().all()
    rows = asyncio.run(_read())
    assert len(rows) == 1
    assert rows[0].route == "/league/[id]/gm"
    assert rows[0].league_id == "77"
    assert rows[0].path == "/league/77/gm"  # query stripped


def test_post_event_requires_auth():
    fastapi_app.dependency_overrides.clear()
    c = TestClient(fastapi_app)
    assert c.post("/api/events", json={"path": "/"}).status_code == 401
