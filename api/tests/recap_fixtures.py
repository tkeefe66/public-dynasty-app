"""Emulate Task 5's registered feature without bypassing readiness policy checks."""
from copy import deepcopy
from importlib import import_module

from app.services.generation.policy import FeaturePolicy
from app.services.generation.store import resolve_policy


def install_recap_policy(monkeypatch):
    features = {name: {"mode": "automatic", "paused": False} for name in ("analyst", "recap_video")}

    async def resolved(db, series_id, **kwargs):
        result = deepcopy(await resolve_policy(db, series_id, **kwargs))
        for name, values in features.items():
            result["policy"]["features"].setdefault(name, FeaturePolicy().model_dump()).update(values)
        return result

    for name in ("recap_video.readiness", "generation.commands", "generation.planner",
                 "generation.candidate_status", "generation.gateway", "generation.artifacts", "generation.publication",
                 "generation.administration"):
        module = import_module("app.services." + name)
        if hasattr(module, "resolve_policy"):
            monkeypatch.setattr(module, "resolve_policy", resolved)
    return features
