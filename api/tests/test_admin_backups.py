from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.deps import get_current_user
from app.db.base import Base
from app.db.session import get_db
from app.main import app as fastapi_app
from app.repositories import app_settings
from app.services.backup_service import (
    STATUS_ERROR_KEY,
    STATUS_OK_KEY,
    STATUS_RUN_KEY,
)


def _admin():
    return SimpleNamespace(id="u1", email="admin@test.local", is_admin=True)


def _non_admin():
    return SimpleNamespace(id="u2", email="user@test.local", is_admin=False)


@pytest.fixture()
def maker(tmp_path):
    """Async sqlite session-maker wired as the app's DB, mirroring the
    override pattern in test_admin_route.py."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'backups.db'}")

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return async_sessionmaker(engine, expire_on_commit=False)

    m = asyncio.run(_setup())

    async def _override_get_db():
        async with m() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    fastapi_app.dependency_overrides[get_db] = _override_get_db
    fastapi_app.dependency_overrides[get_current_user] = _admin
    try:
        yield m
    finally:
        fastapi_app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


@pytest.fixture()
def client(maker):
    return TestClient(fastapi_app)


@pytest.fixture()
def seed_settings(maker):
    """Write app_settings rows directly through the same session-maker the
    overridden get_db serves, so the route reads back what the test seeded."""

    def _seed(values: dict[str, str]) -> None:
        async def _write():
            async with maker() as db:
                for key, value in values.items():
                    await app_settings.set_setting(db, key, value)
                await db.commit()

        asyncio.run(_write())

    return _seed


def test_reports_never_run_before_the_first_backup(client):
    body = client.get("/api/admin/backups").json()
    assert body["last_ok_at"] is None
    assert body["last_run_id"] is None
    assert body["enabled"] is False


def test_reports_the_last_successful_run(client, seed_settings):
    seed_settings({
        STATUS_OK_KEY: "2026-08-12T09:00:00+00:00",
        STATUS_RUN_KEY: "2026-08-12T09-00-00Z",
        STATUS_ERROR_KEY: "",
    })
    body = client.get("/api/admin/backups").json()
    assert body["last_ok_at"] == "2026-08-12T09:00:00+00:00"
    assert body["last_run_id"] == "2026-08-12T09-00-00Z"
    assert body["last_error"] is None  # empty string normalizes to null


def test_surfaces_the_last_error(client, seed_settings):
    seed_settings({STATUS_ERROR_KEY: "RuntimeError: r2 unreachable"})
    assert client.get("/api/admin/backups").json()["last_error"] == (
        "RuntimeError: r2 unreachable"
    )


def test_requires_admin(maker):
    """Backup status names the app's infrastructure state; it is an app-owner
    view like every other /api/admin route (see test_admin_route.py)."""
    fastapi_app.dependency_overrides[get_current_user] = _non_admin
    assert TestClient(fastapi_app).get("/api/admin/backups").status_code == 403
