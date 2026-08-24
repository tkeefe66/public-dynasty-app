from pathlib import Path
import json
from sleeper_dynasty.llm.cost_store import LlmCostStore, _cost_usd


def test_read_empty(tmp_path):
    store = LlmCostStore(tmp_path)
    assert store.read_all() == []


def test_record_creates_file(tmp_path):
    store = LlmCostStore(tmp_path)
    store.record(model="claude-haiku-4-5-20251001", writer="trade_story",
                 league_id="L1", input_tokens=500, output_tokens=200)
    assert (tmp_path / "llm_costs.jsonl").exists()


def test_record_and_read(tmp_path):
    store = LlmCostStore(tmp_path)
    store.record(model="claude-haiku-4-5-20251001", writer="trade_story",
                 league_id="L1", input_tokens=500, output_tokens=200)
    records = store.read_all()
    assert len(records) == 1
    r = records[0]
    assert r["writer"] == "trade_story"
    assert r["model"] == "claude-haiku-4-5-20251001"
    assert r["league_id"] == "L1"
    assert r["input_tokens"] == 500
    assert r["output_tokens"] == 200
    assert r["cost_usd"] > 0
    assert "ts" in r


def test_cost_calculation_haiku_input():
    # 1M input tokens × $1.00/MTok = $1.00
    cost = _cost_usd("claude-haiku-4-5-20251001", 1_000_000, 0)
    assert abs(cost - 1.00) < 0.001


def test_cost_calculation_haiku_output():
    # 1M output tokens × $5.00/MTok = $5.00
    cost = _cost_usd("claude-haiku-4-5-20251001", 0, 1_000_000)
    assert abs(cost - 5.00) < 0.001


def test_cost_calculation_cached_tokens():
    # Cache reads bill at 0.1x input; writes at 1.25x. Haiku input = $1.00/MTok.
    read = _cost_usd("claude-haiku-4-5-20251001", 0, 0, cache_read_input_tokens=1_000_000)
    assert abs(read - 0.10) < 0.001
    write = _cost_usd("claude-haiku-4-5-20251001", 0, 0, cache_creation_input_tokens=1_000_000)
    assert abs(write - 1.25) < 0.001


def test_multiple_records_append(tmp_path):
    store = LlmCostStore(tmp_path)
    for i in range(3):
        store.record(model="claude-haiku-4-5-20251001", writer="trade_story",
                     league_id="L1", input_tokens=100, output_tokens=50)
    assert len(store.read_all()) == 3


def test_unknown_model_uses_fallback(tmp_path):
    store = LlmCostStore(tmp_path)
    # Should not raise — falls back to mid-tier pricing
    store.record(model="claude-unknown-future", writer="recap",
                 league_id="", input_tokens=1000, output_tokens=500)
    records = store.read_all()
    assert records[0]["cost_usd"] > 0


def test_record_failure_is_silent(tmp_path):
    # Create a valid store, then replace the JSONL file with a directory
    # so the open("a") call inside record() fails.
    store = LlmCostStore(tmp_path)
    jsonl_path = tmp_path / "llm_costs.jsonl"
    jsonl_path.mkdir()  # make it a directory so open() fails
    # Should not raise
    store.record(model="claude-haiku-4-5-20251001", writer="trade_story",
                 league_id="L1", input_tokens=100, output_tokens=50)
