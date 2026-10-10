"""Exact token dimensions and immutable standard first-party pricing snapshots.

Verified 2026-09-30: https://platform.claude.com/docs/en/about-claude/pricing
No model fallback. Amounts round upward to one micro-USD per physical attempt.
"""
from decimal import ROUND_CEILING, Decimal

from app.services.generation.store import Held, dump

# Envelope v1 admits <=64 messages, <=256 text blocks and <=16 client tools.
# Reserve one token per ASCII-serialized byte PLUS 65,536 wrapper tokens.
# This deliberately avoids average chars/token estimates and includes escaped
# Unicode, schemas, role/system wrappers and forced-tool formatting. Anthropic
# documents system-added counting tokens as unbilled (token-counting docs).
# Wrapper allowance is our conservative pricing qualification, not a provider
# guarantee: any receipt exceeding it stops dispatch with reservation_exceeded.
WRAPPER_TOKEN_ALLOWANCE = 65_536
BOUND_VERSION = "ascii-byte-envelope-v1"

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


def validate_request_shape(request: dict):
    def reject():
        raise Held("request_option_unregistered")

    if not isinstance(request, dict) or set(request) - {"model", "max_tokens", "system", "messages", "tools", "tool_choice"}:
        reject()
    if type(request.get("max_tokens")) is not int or not 1 <= request["max_tokens"] <= 8192:
        reject()
    messages = request.get("messages")
    if not isinstance(messages, list) or not 1 <= len(messages) <= 64:
        reject()
    blocks = 0
    def text_content(value):
        nonlocal blocks
        if isinstance(value, str):
            blocks += 1
            return
        if not isinstance(value, list) or not value:
            reject()
        for block in value:
            if (not isinstance(block, dict) or set(block) != {"type", "text"}
                    or block["type"] != "text" or not isinstance(block["text"], str)):
                reject()
            blocks += 1
    if "system" in request:
        text_content(request["system"])
    for message in messages:
        if (not isinstance(message, dict) or set(message) != {"role", "content"}
                or message["role"] not in ("user", "assistant")):
            reject()
        text_content(message["content"])
    if blocks > 256:
        reject()
    tools = request.get("tools", [])
    if not isinstance(tools, list) or len(tools) > 16:
        reject()
    names = set()
    for tool in tools:
        if (not isinstance(tool, dict) or set(tool) - {"name", "description", "input_schema"}
                or not isinstance(tool.get("name"), str) or not isinstance(tool.get("input_schema"), dict)
                or ("description" in tool and not isinstance(tool["description"], str))):
            reject()
        names.add(tool["name"])
    choice = request.get("tool_choice")
    if choice is not None and (not isinstance(choice, dict) or set(choice) != {"type", "name"}
                              or choice["type"] != "tool" or choice["name"] not in names):
        reject()


def _ceiling(snapshot, prompt_bytes, output_tokens):
    if snapshot.get("unit") != "micro_usd_per_token" or snapshot.get("model") not in RATES:
        raise Held("pricing_unknown")
    try:
        incoming, outgoing = Decimal(snapshot["input"]), Decimal(snapshot["output"])
        if not incoming.is_finite() or not outgoing.is_finite() or min(incoming, outgoing) <= 0:
            raise ValueError()
        return int(((prompt_bytes + WRAPPER_TOKEN_ALLOWANCE) * incoming + output_tokens * outgoing)
                   .to_integral_value(rounding=ROUND_CEILING))
    except (KeyError, ValueError, ArithmeticError):
        raise Held("pricing_unknown") from None


def request_ceiling(request, snapshot):
    validate_request_shape(request)
    if request["model"] != snapshot.get("model"):
        raise Held("pricing_unknown")
    return _ceiling(snapshot, len(dump(request).encode("ascii")), request["max_tokens"])


def bounded_plan(operation_id, feature_name, saved, current, max_calls):
    """Reserve every permitted draft/review/repair/review using future request limits."""
    prompt = min(saved["max_prompt_chars"], current["max_prompt_chars"])
    output = min(saved["max_tokens"], current["max_tokens"])
    result = []
    for stage in range(1, min(max_calls, saved["max_calls"], current["max_calls"]) + 1):
        model = saved["review_model"] if feature_name == "analyst" and stage > 1 else saved["model"]
        snapshot = pricing(model)
        snapshot.update(bound_version=BOUND_VERSION, max_serialized_bytes=prompt,
                        max_output_tokens=output, wrapper_tokens=WRAPPER_TOKEN_ALLOWANCE)
        result.append(dict(key=str(stage), category="written", operation_id=operation_id,
            max_microusd=_ceiling(snapshot, prompt, output), rate_snapshot=snapshot))
    return result


def narration_allocations(operation_id, chunks, rate_snapshot, *, replacements=0):
    """Qualified all-in character rate; each replacement must be explicitly authorized."""
    required = {"provider", "product", "version", "currency", "unit", "microusd_per_character", "evidence"}
    if (not isinstance(rate_snapshot, dict) or set(rate_snapshot) != required
            or any(not isinstance(v, str) or not v for v in rate_snapshot.values())
            or rate_snapshot["currency"] != "USD" or rate_snapshot["unit"] != "character"):
        raise Held("pricing_unknown")
    try:
        rate = Decimal(rate_snapshot["microusd_per_character"])
        if not rate.is_finite() or rate <= 0:
            raise ValueError()
    except (ValueError, ArithmeticError):
        raise Held("pricing_unknown") from None
    if (type(replacements) is not int or not 0 <= replacements <= 1 or not isinstance(chunks, list)
            or not 1 <= len(chunks) <= 64 or any(not isinstance(s, str) or not s for s in chunks)):
        raise Held("narration_plan_unbounded")
    return [dict(key=f"narration:{take}:{index}", category="video", operation_id=operation_id,
        max_microusd=int((len(text) * rate).to_integral_value(rounding=ROUND_CEILING)),
        rate_snapshot={**rate_snapshot, "submitted_characters": len(text)})
        for take in range(replacements + 1) for index, text in enumerate(chunks)]


def price_usage(body: dict, snapshot: dict) -> tuple[str, dict, int | None]:
    usage = body.get("usage")
    if not isinstance(usage, dict):
        return "unknown", {}, None
    if set(usage) - {"input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens",
                     "cache_creation", "server_tool_use", "service_tier"}:
        return "pricing_unknown", usage, None
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
