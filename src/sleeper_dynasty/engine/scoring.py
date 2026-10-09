"""Pure league scoring for one NFL week, using normalized component stats.

Thresholds need weekly evidence. This function must never be called with
season-total statistics or aggregate projections to infer threshold awards.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from sleeper_dynasty.models.scoring import ThresholdBonus


def _number(value) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError("Scoring data must contain finite numeric values.")
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("Scoring data must contain finite numeric values.")
    return result


def score_week_stats(
    stats: Mapping[str, float],
    scoring: Mapping[str, float],
    *,
    bonuses: Sequence[ThresholdBonus] = (),
    position: str | None = None,
) -> Decimal:
    """Score one player's actual week, rounded once with decimal arithmetic.

    Raw feeds are sparse: an absent supported component contributes zero.
    Adapters must reject scoring categories the source cannot express rather
    than passing an unknown category here. A zero-target rule additionally
    needs an observed component: participation alone does not prove that a
    rule for another position applies to this player.
    """
    values = dict(stats)
    # A position premium may be omitted by the source. Preserve an explicit
    # source counter so the same receptions are never credited twice.
    if position in {"RB", "WR", "TE"}:
        values.setdefault(f"bonus_rec_{position.lower()}", stats.get("rec", 0))

    total = Decimal(0)
    for key, weight in scoring.items():
        multiplier = _number(weight)
        if multiplier:
            total += _number(values.get(key, 0)) * multiplier

    played = _number(stats["gp"]) > 0 if stats.get("gp") is not None else None
    for bonus in bonuses:
        if not bonus.points or not stats or played is False:
            continue
        # A zero target cannot infer applicability from gp alone: that would
        # credit, for example, a kicker's rule to every active receiver.
        # Partial rows without gp also need an actual component rather than
        # source rank placeholders or unrelated metadata.
        if ((bonus.target == 0 or played is None)
                and not any(key in stats for key in bonus.stat_keys)):
            continue
        combined = sum((_number(values.get(key, 0)) for key in bonus.stat_keys), Decimal(0))
        if combined >= _number(bonus.target):
            total += _number(bonus.points)

    if not total.is_finite():
        raise ValueError("Scoring data must contain finite numeric values.")
    try:
        return total.quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise ValueError("Scoring data is outside the supported numeric range.") from exc
