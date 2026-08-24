from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

# Cost per million tokens (input, output).
# Verify current rates at https://www.anthropic.com/pricing
_PRICING: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    "claude-haiku-4-5":          (1.00, 5.00),
    "claude-sonnet-4-6":         (3.00, 15.00),
    "claude-opus-4-8":           (5.00, 25.00),
    "claude-opus-4-7":           (5.00, 25.00),
    "claude-fable-5":            (10.00, 50.00),
}
_FALLBACK_PRICING = (3.00, 15.00)  # unknown model: assume mid-tier

# Cache reads bill at ~0.1x base input; 5-minute cache writes at ~1.25x.
_CACHE_READ_MULT = 0.1
_CACHE_WRITE_MULT = 1.25


def _cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_input_tokens: int = 0,
    cache_creation_input_tokens: int = 0,
) -> float:
    in_price, out_price = _PRICING.get(model, _FALLBACK_PRICING)
    return (
        input_tokens * in_price
        + output_tokens * out_price
        + cache_read_input_tokens * in_price * _CACHE_READ_MULT
        + cache_creation_input_tokens * in_price * _CACHE_WRITE_MULT
    ) / 1_000_000


class LlmCostStore:
    def __init__(self, cache_dir: Path) -> None:
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        self._path = cache_dir / "llm_costs.jsonl"

    def record(
        self,
        *,
        model: str,
        writer: str,
        league_id: str,
        input_tokens: int,
        output_tokens: int,
        cache_read_input_tokens: int = 0,
        cache_creation_input_tokens: int = 0,
    ) -> None:
        cost = _cost_usd(
            model, input_tokens, output_tokens,
            cache_read_input_tokens, cache_creation_input_tokens,
        )
        entry = {
            "ts": datetime.now(tz=timezone.utc).isoformat(),
            "model": model,
            "writer": writer,
            "league_id": league_id,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_input_tokens": cache_read_input_tokens,
            "cache_creation_input_tokens": cache_creation_input_tokens,
            "cost_usd": round(cost, 6),
        }
        try:
            with self._path.open("a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            log.warning("failed to write LLM cost record", exc_info=True)

    def read_all(self) -> list[dict]:
        if not self._path.exists():
            return []
        records: list[dict] = []
        with self._path.open() as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        log.warning("skipping corrupt LLM cost record: %s", line[:80])
        return records
