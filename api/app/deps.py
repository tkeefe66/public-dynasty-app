from __future__ import annotations

from pathlib import Path

from app.config import get_settings


def get_cache_dir() -> Path:
    return get_settings().cache_dir
