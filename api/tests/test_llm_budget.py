from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.services.refresh_service import _llm_over_budget, month_to_date_spend
from sleeper_dynasty.llm.cost_store import LlmCostStore


def _seed(tmp_path, this_month_usd: float, last_month_usd: float) -> None:
    store = LlmCostStore(tmp_path)
    now = datetime.now(tz=timezone.utc)
    # Records carry their own ts; write directly to control the month.
    import json

    path = tmp_path / "llm_costs.jsonl"
    rows = [
        {"ts": now.isoformat(), "model": "m", "writer": "w",
         "league_id": "L", "input_tokens": 0, "output_tokens": 0,
         "cost_usd": this_month_usd},
        {"ts": f"{now.year - 1:04d}-{now.month:02d}-01T00:00:00+00:00",
         "model": "m", "writer": "w", "league_id": "L",
         "input_tokens": 0, "output_tokens": 0, "cost_usd": last_month_usd},
    ]
    with path.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    assert store.read_all()  # sanity


def test_month_to_date_only_counts_current_month(tmp_path):
    _seed(tmp_path, this_month_usd=2.50, last_month_usd=99.0)
    assert month_to_date_spend(tmp_path) == 2.50


def test_over_budget_logic(tmp_path, monkeypatch):
    _seed(tmp_path, this_month_usd=5.0, last_month_usd=0.0)

    # No budget configured → never over budget.
    monkeypatch.delenv("TRADE_GRADER_LLM_MONTHLY_BUDGET_USD", raising=False)
    assert asyncio.run(_llm_over_budget(tmp_path)) is False

    # Spend below budget.
    monkeypatch.setenv("TRADE_GRADER_LLM_MONTHLY_BUDGET_USD", "10")
    assert asyncio.run(_llm_over_budget(tmp_path)) is False

    # Spend at/over budget.
    monkeypatch.setenv("TRADE_GRADER_LLM_MONTHLY_BUDGET_USD", "5")
    assert asyncio.run(_llm_over_budget(tmp_path)) is True
