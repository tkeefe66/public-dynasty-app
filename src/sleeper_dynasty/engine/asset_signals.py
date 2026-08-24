"""The Assets pillar: what a franchise holds right now.

Both signals are *shares* rather than raw totals, so they are scale-free and
comparable without depending on how a particular valuation source is scaled.

``young_core_share`` replaces the old negated mean age. A straight mean over a
roster measures roster filler: it ranked one owner 10th of 12 on youth while
his most valuable assets were a 24-year-old QB and two young receivers, because
eight veterans dragged the average the young core should have dominated.

Pure: no I/O, no clock.
"""

from __future__ import annotations

YOUNG_MAX_AGE = 25


def asset_signals(
    *,
    current_holders: dict[str, str],
    value_by_player: dict[str, float],
    age_by_player: dict[str, int],
    owners: list[str],
    young_max_age: int = YOUNG_MAX_AGE,
) -> dict[str, dict[str, float]]:
    """uid -> {roster_value_share, young_core_share}.

    - ``roster_value_share``: this owner's roster value over the league's total.
    - ``young_core_share``: the share of *this owner's* value held by players
      aged ``young_max_age`` or younger.

    Players with an unknown age are excluded from **both** sides of the
    young-core ratio. Leaving them in the denominator only would bias the
    signal down for whoever rosters the most unlisted deep-bench rookies. They
    still count toward roster value, which does not depend on age.
    """
    value: dict[str, float] = {u: 0.0 for u in owners}
    aged_value: dict[str, float] = {u: 0.0 for u in owners}
    young_value: dict[str, float] = {u: 0.0 for u in owners}

    for pid, uid in current_holders.items():
        v = float(value_by_player.get(pid, 0.0) or 0.0)
        value.setdefault(uid, 0.0)
        aged_value.setdefault(uid, 0.0)
        young_value.setdefault(uid, 0.0)
        value[uid] += v
        age = age_by_player.get(pid)
        if age is None:
            continue
        aged_value[uid] += v
        if int(age) <= young_max_age:
            young_value[uid] += v

    league_total = sum(value.values())
    out: dict[str, dict[str, float]] = {}
    for uid in value:
        denom = aged_value[uid]
        out[uid] = {
            "roster_value_share": (value[uid] / league_total) if league_total else 0.0,
            "young_core_share": (young_value[uid] / denom) if denom else 0.0,
        }
    return out
