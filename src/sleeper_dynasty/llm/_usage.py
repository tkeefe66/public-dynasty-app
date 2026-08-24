"""Shared helper: extract billable token counts from an Anthropic usage object.

Captures cache read/creation tokens alongside input/output so LlmCostStore can
price them correctly (cache reads ~0.1x, writes ~1.25x). On models/requests
without caching these come back as None/0 and pass through as 0.
"""

from __future__ import annotations

from typing import Any


def usage_dict(usage: Any) -> dict[str, int]:
    return {
        "input_tokens": usage.input_tokens or 0,
        "output_tokens": usage.output_tokens or 0,
        "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
        "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
    }
