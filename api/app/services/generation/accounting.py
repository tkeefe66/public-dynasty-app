"""Exact token dimensions and immutable standard first-party pricing snapshots.

Verified 2026-09-30: https://platform.claude.com/docs/en/about-claude/pricing
No model fallback. Amounts round upward to one micro-USD per physical attempt.
"""
from decimal import ROUND_CEILING, Decimal

RATES = {
    "claude-haiku-4-5-20251001": ("1", "5"),
    "claude-haiku-4-5": ("1", "5"),
    "claude-sonnet-4-6": ("3", "15"),
}


def pricing(model: str) -> dict:
    if model not in RATES:
        raise ValueError("Model price is unknown; paid submission is blocked")
    incoming, outgoing = RATES[model]
    return {"model": model, "input": incoming, "output": outgoing,
            "cache_read": str(Decimal(incoming) / 10),
            "cache_write_5m": str(Decimal(incoming) * Decimal("1.25")),
            "cache_write_1h": str(Decimal(incoming) * 2),
            "unit": "micro_usd_per_token", "verified": "2026-09-30",
            "rounding": "ceiling_per_attempt"}


def price_usage(body: dict, snapshot: dict) -> tuple[str, dict, int | None]:
    usage = body.get("usage")
    if not isinstance(usage, dict):
        return "unknown", {}, None
    if body.get("model") not in RATES:
        return "pricing_unknown", usage, None
    # Snapshot rates, not mutable current rates, settle the admitted request.
    if RATES[body["model"]] != RATES[snapshot["model"]]:
        return "pricing_unknown", usage, None
    for key in ("input_tokens", "output_tokens"):
        if type(usage.get(key)) is not int or usage[key] < 0:
            return "unknown", usage, None
    counts = {key: usage.get(key) or 0 for key in (
        "input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")}
    if any(type(value) is not int or value < 0 for value in counts.values()):
        return "unknown", usage, None
    creation = usage.get("cache_creation") or {}
    five = creation.get("ephemeral_5m_input_tokens", counts["cache_creation_input_tokens"])
    hour = creation.get("ephemeral_1h_input_tokens", 0)
    if (type(five) is not int or type(hour) is not int or min(five, hour) < 0
            or five + hour != counts["cache_creation_input_tokens"]):
        return "unknown", usage, None
    server_tools = usage.get("server_tool_use") or {}
    if any(server_tools.values()) or usage.get("service_tier", "standard") not in (None, "standard"):
        return "pricing_unknown", usage, None
    amount = (counts["input_tokens"] * Decimal(snapshot["input"])
              + counts["output_tokens"] * Decimal(snapshot["output"])
              + counts["cache_read_input_tokens"] * Decimal(snapshot["cache_read"])
              + five * Decimal(snapshot["cache_write_5m"])
              + hour * Decimal(snapshot["cache_write_1h"]))
    return "known", usage, int(amount.quantize(Decimal(1), rounding=ROUND_CEILING))
