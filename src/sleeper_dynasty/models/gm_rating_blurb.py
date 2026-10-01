"""Facts packet for the per-owner GM-rating blurb.

Contract between engine/gm_rating_blurb.py (builder) and
llm/gm_rating_blurb_writer.py (writer). The writer references ONLY these facts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sleeper_dynasty.models._signature import signature_hash


@dataclass
class OwnerRatingFacts:
    user_id: str
    owner_name: str
    team_name: str | None
    scope_label: str          # "career" | "the 2025 season"
    rank: int
    rating: int
    # The builder emits a list of labeled summaries; mapping-shaped callers are
    # also supported. Preserve either shape when serializing saved facts.
    # Results + Assets normally; Results only for redraft.
    pillars: list[dict[str, Any]] | dict[str, dict[str, Any]] = field(default_factory=dict)
    championships: int = 0
    made_playoffs_rate: float = 0.0
    draft_capital_counted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "owner_name": self.owner_name,
            "team_name": self.team_name,
            "scope_label": self.scope_label,
            "rank": self.rank,
            "rating": self.rating,
            "pillars": self.pillars,
            "championships": self.championships,
            "made_playoffs_rate": round(self.made_playoffs_rate, 2),
            "draft_capital_counted": self.draft_capital_counted,
        }


def rating_facts_hash(facts: OwnerRatingFacts) -> str:
    """Stable 16-char hash of the facts packet (used for incremental skip).

    Coarsened so the blurb regenerates on material change (rank shift, rating
    band, pillar shake-up) but not on per-refresh KTC drift. See _signature.py.
    """
    return signature_hash(facts.to_dict())
