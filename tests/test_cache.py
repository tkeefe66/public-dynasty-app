import json
import time
from pathlib import Path

from sleeper_dynasty.cache import FileCache


def test_cache_write_and_read(tmp_path):
    cache = FileCache(cache_dir=tmp_path)
    data = {"players": [{"id": "1", "name": "Test Player"}]}
    cache.write("players.json", data)
    result = cache.read("players.json", max_age_seconds=60)
    assert result == data


def test_cache_returns_none_when_expired(tmp_path):
    cache = FileCache(cache_dir=tmp_path)
    data = {"key": "value"}
    cache.write("old.json", data)
    result = cache.read("old.json", max_age_seconds=0)
    assert result is None


def test_cache_returns_none_when_missing(tmp_path):
    cache = FileCache(cache_dir=tmp_path)
    result = cache.read("nonexistent.json", max_age_seconds=60)
    assert result is None


def test_cache_invalidate(tmp_path):
    cache = FileCache(cache_dir=tmp_path)
    cache.write("remove_me.json", {"data": True})
    cache.invalidate("remove_me.json")
    result = cache.read("remove_me.json", max_age_seconds=60)
    assert result is None


def test_cache_returns_none_for_corrupt_json(tmp_path):
    cache = FileCache(cache_dir=tmp_path)
    # Write garbage (not valid JSON) directly to a cache file.
    corrupt_path = tmp_path / "corrupt.json"
    corrupt_path.write_text("{not valid json")
    result = cache.read("corrupt.json", max_age_seconds=60)
    assert result is None
