"""Build a focused editorial brief while preserving the complete saved evidence."""
from copy import deepcopy
from dataclasses import dataclass

from sleeper_dynasty.models.recap import RecapFacts


def period_local_facts(facts: dict) -> bool:
    return (facts.get('text_contract') == 'period-text-v1'
            and all(not facts.get(key) for key in ('bench_regret', 'lineups', 'heroes', 'goats', 'busts',
                'standings', 'lucky', 'unlucky', 'player_context', 'high_scorer', 'low_scorer'))
            and facts.get('standings_race') == {'available': False}
            and facts.get('bets') == {'available': False})


def period_text_source(source: dict) -> dict:
    """Version-one period text inputs: results and starters, no bench claims.

    Used identically by writing, review, and correction comparison. Raw source
    remains in the immutable archive, never silently substituted for this view.
    """
    result = deepcopy(source)
    for rows in (result.get('scores') or {}).values():
        for row in rows:
            starters = row['starters']
            row['players_points'] = {pid: row['players_points'][pid] for pid in starters if pid != '0'}
            row['players'] = list(starters)
    return result


@dataclass(frozen=True)
class ArchivedPacket:
    """Use saved evidence without reconstructing it from a later league state."""

    data: dict

    @property
    def week(self) -> int:
        return self.data["week"]

    def to_dict(self) -> dict:
        return deepcopy(self.data)


def editorial_facts(facts: RecapFacts | ArchivedPacket, *, starter_safe=False) -> dict:
    """Keep each team's leading starters, low scorer, awards and legal swaps.

    Sending hundreds of unrelated bench players makes ownership and chronology
    harder to follow. Writer, repair and reviewer all receive this same subset;
    the archive retains the original facts and complete source metadata.
    """
    packet = deepcopy(facts.to_dict())
    if period_local_facts(packet) or (starter_safe and packet.get('source_snapshot')):
        packet['source_snapshot'] = period_text_source(packet['source_snapshot'])
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
