"""Build a focused editorial brief while preserving the complete saved evidence."""
from copy import deepcopy
from dataclasses import dataclass

from sleeper_dynasty.models.recap import RecapFacts


@dataclass(frozen=True)
class ArchivedPacket:
    """Use saved evidence without reconstructing it from a later league state."""

    data: dict

    @property
    def week(self) -> int:
        return self.data["week"]

    def to_dict(self) -> dict:
        return deepcopy(self.data)


def editorial_facts(facts: RecapFacts | ArchivedPacket) -> dict:
    """Keep each team's leading starters, low scorer, awards and legal swaps.

    Sending hundreds of unrelated bench players makes ownership and chronology
    harder to follow. Writer, repair and reviewer all receive this same subset;
    the archive retains the original facts and complete source metadata.
    """
    packet = deepcopy(facts.to_dict())
    selected = set()

    def select(line):
        if line.get("player"):
            selected.add(line["player"])

    for key in ("heroes", "goats", "busts"):
        for line in packet[key]:
            select(line)
    for regret in packet["bench_regret"]:
        for swap in regret.get("legal_swaps", []):
            select(swap["benched_player"])
            select(swap["started_player"])
    for lineup in packet["lineups"]:
        ordered = sorted(lineup["starters"], key=lambda p: p["points"], reverse=True)
        for line in [*ordered[:3], *ordered[-1:]]:
            select(line)
    for lineup in packet["lineups"]:
        lineup["starters"] = [p for p in lineup["starters"] if p["player"] in selected]
    names = {name.rsplit(" (", 1)[0] for name in selected}
    context = packet["player_context"]
    if "players" in context:
        context["players"] = [p for p in context["players"] if p.get("player") in names]
    # Full citation list belongs to the archive footer. Each retained news item
    # still carries its own publisher, text, URL, and chronology.
    context.pop("sources", None)
    context.pop("news_count", None)
    return packet
