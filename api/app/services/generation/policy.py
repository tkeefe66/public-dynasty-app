"""Strict configuration and one deterministic effective-settings resolver."""
from __future__ import annotations

from copy import deepcopy
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

FEATURES = ("trade_story", "gm_rating_blurb", "franchise_blurb", "analyst")
HAIKU = "claude-haiku-4-5-20251001"
SONNET = "claude-sonnet-4-6"
MODELS = (HAIKU, "claude-haiku-4-5", SONNET)


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class FeaturePolicy(StrictModel):
    mode: Literal["disabled", "manual", "automatic"] = "manual"
    paused: bool = False
    model: Literal["claude-haiku-4-5-20251001", "claude-haiku-4-5", "claude-sonnet-4-6"] = HAIKU
    review_model: Literal["claude-haiku-4-5-20251001", "claude-haiku-4-5", "claude-sonnet-4-6"] = SONNET
    max_calls: int = Field(default=2, ge=1, le=4)
    max_tokens: int = Field(default=1024, ge=64, le=8192)
    max_prompt_chars: int = Field(default=128_000, ge=1024, le=256_000)


def feature_defaults() -> dict[str, FeaturePolicy]:
    values = {key: FeaturePolicy() for key in FEATURES}
    values["analyst"] = FeaturePolicy(model=SONNET, max_calls=4, max_tokens=8192)
    return values


class Policy(StrictModel):
    paused: bool = True
    max_concurrency: int = Field(default=1, ge=1, le=4)
    series_concurrency: int = Field(default=1, ge=1, le=1)
    breaker_failures: int = Field(default=3, ge=1, le=3)
    refresh_interval_seconds: int = Field(default=10800, ge=900, le=604800)
    features: dict[str, FeaturePolicy] = Field(default_factory=feature_defaults)

    @model_validator(mode="after")
    def registered_features(self):
        if set(self.features) - set(FEATURES):
            raise ValueError("Unknown feature; register its execution contract first")
        defaults = feature_defaults()
        for key, value in self.features.items():
            if key != "analyst" and value.max_calls > 2:
                raise ValueError("Story and blurb workflows permit at most two calls")
            defaults[key] = value
        self.features = defaults
        return self


class Capabilities(StrictModel):
    format: Literal["dynasty", "keeper", "redraft"]
    future_picks: bool
    roster_continuity: bool
    multiyear_history: bool


def paid_capabilities(raw: dict | None) -> dict | None:
    try:
        return Capabilities.model_validate(raw).model_dump()
    except (ValueError, TypeError):
        return None


def merge(left: dict, right: dict) -> dict:
    result = deepcopy(left)
    for key, value in right.items():
        result[key] = merge(result.get(key, {}), value) if isinstance(value, dict) else value
    return result


def effective(layers: list[tuple[str, dict]]) -> dict:
    """Layer ordinary values; intersect all explicit pauses after merging."""
    result = Policy().model_dump()
    sources: dict[str, str] = {}
    blocked: list[str] = []
    feature_pauses: set[str] = set()

    def origins(data, source, prefix=""):
        for key, value in data.items():
            name = f"{prefix}{key}"
            if isinstance(value, dict):
                origins(value, source, name + ".")
            else:
                sources[name] = source

    origins(result, "defaults")
    for source, value in layers:
        result = merge(result, value)
        # Validate merged values before checking truthiness of any flag.
        Policy.model_validate(result)
        origins(value, source)
        if value.get("paused") is True:
            blocked.append(f"{source}_paused")
        for key, feature in value.get("features", {}).items():
            if feature.get("paused") is True or feature.get("mode") == "disabled":
                feature_pauses.add(key)
    policy = Policy.model_validate(result)
    if blocked:
        policy.paused = True
    if policy.paused and not blocked:
        blocked.append("activation_required")
    for key in feature_pauses:
        policy.features[key].paused = True
    return {"policy": policy.model_dump(), "sources": sources, "blocked_by": blocked}
