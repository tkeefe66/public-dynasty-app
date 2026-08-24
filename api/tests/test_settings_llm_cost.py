from __future__ import annotations
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.auth.deps import require_admin
from app.main import app as _app

_FAKE_ADMIN = SimpleNamespace(id="test-user", email="admin@test.local", is_admin=True)


@pytest.fixture(autouse=True)
def _authorized_admin():
    # The llm-cost/config endpoints are admin-guarded; these tests predate auth.
    _app.dependency_overrides[require_admin] = lambda: _FAKE_ADMIN
    try:
        yield
    finally:
        _app.dependency_overrides.clear()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADE_GRADER_CACHE_DIR", str(tmp_path))
    from app.main import app
    return TestClient(app)


def test_llm_cost_empty(client):
    resp = client.get("/api/settings/llm-cost?period=7d")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_cost_usd"] == 0.0
    assert data["total_calls"] == 0
    assert data["daily"] == []
    assert data["by_writer"] == {}
    assert "active_model" in data


def test_llm_cost_with_record(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADE_GRADER_CACHE_DIR", str(tmp_path))
    from sleeper_dynasty.llm.cost_store import LlmCostStore
    store = LlmCostStore(tmp_path)
    store.record(model="claude-haiku-4-5-20251001", writer="trade_story",
                 league_id="L1", input_tokens=1_000_000, output_tokens=0)
    from app.main import app
    client = TestClient(app)
    resp = client.get("/api/settings/llm-cost?period=7d")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_calls"] == 1
    assert abs(data["total_cost_usd"] - 1.00) < 0.01  # 1M haiku input @ $1.00/MTok
    assert "trade_story" in data["by_writer"]
    assert data["by_writer"]["trade_story"]["calls"] == 1
    # Zero-filled: a 7d period spans 8 calendar days (cutoff..now inclusive),
    # not just the single day with an actual record.
    assert len(data["daily"]) == 8
    assert sum(d["calls"] for d in data["daily"]) == 1
    assert any(d["calls"] == 0 for d in data["daily"])


def test_llm_cost_by_writer_breakdown(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADE_GRADER_CACHE_DIR", str(tmp_path))
    from sleeper_dynasty.llm.cost_store import LlmCostStore
    store = LlmCostStore(tmp_path)
    store.record(model="claude-haiku-4-5-20251001", writer="trade_story",
                 league_id="L1", input_tokens=500, output_tokens=200)
    store.record(model="claude-haiku-4-5-20251001", writer="gm_rating_blurb",
                 league_id="L1", input_tokens=300, output_tokens=100)
    from app.main import app
    client = TestClient(app)
    resp = client.get("/api/settings/llm-cost?period=7d")
    data = resp.json()
    assert set(data["by_writer"].keys()) == {"trade_story", "gm_rating_blurb"}


def test_config_endpoint(client):
    resp = client.get("/api/settings/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "llm_model" in data
    assert "haiku" in data["llm_model"]


def test_period_today_filters_old_records(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADE_GRADER_CACHE_DIR", str(tmp_path))
    path = tmp_path / "llm_costs.jsonl"
    path.write_text(json.dumps({
        "ts": "2020-01-01T00:00:00+00:00",
        "model": "claude-haiku-4-5-20251001",
        "writer": "trade_story",
        "league_id": "L1",
        "input_tokens": 1000,
        "output_tokens": 500,
        "cost_usd": 0.003,
    }) + "\n")
    from app.main import app
    client = TestClient(app)
    resp = client.get("/api/settings/llm-cost?period=today")
    data = resp.json()
    assert data["total_calls"] == 0
