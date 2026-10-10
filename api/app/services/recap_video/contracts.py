"""Shared episode identities and pure readiness decisions."""
from dataclasses import dataclass


@dataclass(frozen=True)
class EpisodeKey:
    series_id: str
    season: int
    period_id: str


@dataclass(frozen=True)
class ReadinessDecision:
    ready: bool
    code: str
    eligible_at: int
    facts_digest: str
