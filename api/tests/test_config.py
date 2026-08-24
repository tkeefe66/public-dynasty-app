from __future__ import annotations

from app.config import Settings


def test_postgres_url_normalized_to_asyncpg():
    s = Settings(database_url="postgresql://u:p@host:5432/db")
    assert s.database_url == "postgresql+asyncpg://u:p@host:5432/db"


def test_legacy_postgres_scheme_normalized():
    s = Settings(database_url="postgres://u:p@host:5432/db")
    assert s.database_url == "postgresql+asyncpg://u:p@host:5432/db"


def test_async_url_left_untouched():
    url = "postgresql+asyncpg://u:p@host/db"
    assert Settings(database_url=url).database_url == url


def test_empty_url_defaults_to_sqlite():
    assert Settings(database_url="").database_url.startswith("sqlite+aiosqlite:///")
