"""League-scored NFL production, independent of fantasy roster ownership."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from decimal import Decimal, ROUND_HALF_UP

from sleeper_dynasty.engine.scoring import score_week_stats
from sleeper_dynasty.models.scoring import ThresholdBonus


def completed_week(season: int, state: dict | None) -> int:
    """Conservative cutoff: never label the current NFL week completed."""
    try:
        live_season = int(state["season"])
        phase = state["season_type"]
        if live_season <= 0 or phase not in {"pre", "regular", "post", "off"}:
            raise ValueError
        last = 18 if season >= 2021 else 17
        if season < live_season:
            return last
        if season > live_season or phase == "pre":
            return 0
        if phase in {"post", "off"}:
            return last
        week = int(state["week"])
        if not 0 <= week <= last + 1:
            raise ValueError
        return max(0, min(last, week - 1))
    except (KeyError, TypeError, ValueError):
        raise ValueError("NFL season state is unavailable. Try again shortly.") from None


def score_player_week(
    stats: dict, scoring: dict, position: str,
    *, bonuses: Sequence[ThresholdBonus] = (),
) -> Decimal:
    return score_week_stats(stats, scoring, bonuses=bonuses, position=position)


def build_scoring_rows(
    stats_by_week: dict[int, dict], players: dict, scoring: dict, through_week: int,
    *, bonuses: Sequence[ThresholdBonus] = (),
) -> list[dict]:
    totals: dict[str, Decimal] = defaultdict(Decimal)
    games: dict[str, int] = defaultdict(int)
    for week, raw in stats_by_week.items():
        if not 1 <= week <= through_week:
            continue
        for pid, stats in raw.items():
            player = players.get(pid) or {}
            if not player.get("position"):
                continue
            # Zero and negative scoring games still count. Presence alone does
            # not: the feed includes inactive players and rank placeholders.
            # gms_active=1 also appears on rank-only inactive placeholders.
            played = stats.get("gp", 0)
            if not played:
                continue
            totals[pid] += score_player_week(stats, scoring, player["position"], bonuses=bonuses)
            games[pid] += 1

    by_position: dict[str, list[dict]] = defaultdict(list)
    for pid, total in totals.items():
        player = players[pid]
        name = player.get("full_name") or " ".join(
            str(player.get(k) or "") for k in ("first_name", "last_name")
        ).strip() or pid
        by_position[player["position"]].append({
            "player_id": pid, "name": name, "position": player["position"],
            "team": player.get("team"), "points": float(total), "games": games[pid],
            "points_per_game": float((total / games[pid]).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)),
        })

    rows = []
    for position in sorted(by_position):
        group = sorted(by_position[position], key=lambda r: (-r["points"], r["name"], r["player_id"]))
        previous = None
        rank = 0
        for index, row in enumerate(group, 1):
            if row["points"] != previous:
                rank = index
            row["rank"] = rank
            previous = row["points"]
            rows.append(row)
    return rows
