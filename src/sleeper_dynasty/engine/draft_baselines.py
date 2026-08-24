"""External expectation baselines for a draft: ADP and projected points.

Grading a pick is always *result minus expectation*. This module owns the two
expectations that come from outside the league — where the market drafted a
player, and how many points he was projected for — leaving the league-native
peer baseline to ``draft_signals.draft_skill``.

Both come from Sleeper's season projections payload
(``SleeperClient.get_projections``), which is keyed by native Sleeper
``player_id``, so nothing here needs an id crosswalk.

Pure. No I/O — callers thread in the fetched payload.
"""

from __future__ import annotations

from collections import defaultdict

# Sleeper's "never drafted" marker. It is NOT a 999th-overall ADP: left
# unfiltered it becomes a catch-all bucket that grades every undrafted player
# as though the market agreed on him. Same failure mode as DynastyProcess's
# literal "NA" key.
ADP_UNDRAFTED = 999.0

# Reception scoring at or above these thresholds selects the format. Sleeper
# leagues use 1.0 (PPR), 0.5 (half), or 0.0 (standard); the thresholds sit
# between them so unusual values (0.75, 0.25) land on the nearer format.
_PPR_FLOOR = 0.75
_HALF_PPR_FLOOR = 0.25

# Every scoring variant Sleeper publishes an ADP for — i.e. the complete range
# of ``adp_field_for``. The daily snapshot stores all four, so one league's
# refresh preserves the day's market for every OTHER league's scoring too.
ADP_FIELDS = ("adp_ppr", "adp_half_ppr", "adp_std", "adp_2qb")


def adp_field_for(*, rec_points: float, superflex: bool) -> str:
    """Which ``adp_*`` field matches this league's scoring.

    Superflex wins outright: a second startable QB moves quarterbacks so far up
    the board that reception scoring is a rounding error by comparison.
    """
    if superflex:
        return "adp_2qb"
    if rec_points >= _PPR_FLOOR:
        return "adp_ppr"
    if rec_points >= _HALF_PPR_FLOOR:
        return "adp_half_ppr"
    return "adp_std"


def points_field_for(*, rec_points: float) -> str:
    """Which ``pts_*`` field matches this league's scoring.

    Sleeper publishes no superflex projection variant — projected points do not
    depend on roster construction the way draft position does.
    """
    if rec_points >= _PPR_FLOOR:
        return "pts_ppr"
    if rec_points >= _HALF_PPR_FLOOR:
        return "pts_half_ppr"
    return "pts_std"


def _numeric(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def parse_adp(raw: dict, *, field: str) -> dict[str, float]:
    """player_id -> ADP, sentinel and non-numeric entries dropped."""
    out: dict[str, float] = {}
    for pid, stats in (raw or {}).items():
        if not isinstance(stats, dict):
            continue
        val = _numeric(stats.get(field))
        if val is None or val >= ADP_UNDRAFTED:
            continue
        out[str(pid)] = val
    return out


def parse_all_adp(raw: dict) -> dict[str, dict[str, float]]:
    """Every scoring variant's ADP map, ``adp_*`` field -> {player_id -> ADP}.

    Variants with no usable entries are dropped rather than stored empty: an
    empty map is indistinguishable from a failed fetch downstream, and the
    snapshot store refuses empties for exactly that reason.
    """
    out: dict[str, dict[str, float]] = {}
    for field in ADP_FIELDS:
        parsed = parse_adp(raw, field=field)
        if parsed:
            out[field] = parsed
    return out


def parse_projected_points(raw: dict, *, field: str) -> dict[str, float]:
    """player_id -> projected season points. Zero is kept (a real projection);
    missing is dropped (no projection published)."""
    out: dict[str, float] = {}
    for pid, stats in (raw or {}).items():
        if not isinstance(stats, dict):
            continue
        val = _numeric(stats.get(field))
        if val is None:
            continue
        out[str(pid)] = val
    return out


def adp_delta(*, pick_no: int, adp: float | None) -> float | None:
    """How far past his market price a player was taken.

    Positive = taken later than the market had him (value). Negative = a reach.
    None when the player has no ADP — the pick is ungraded on this baseline,
    which is not the same as scoring zero.
    """
    if adp is None:
        return None
    return float(pick_no) - float(adp)


def owner_adp_grades(rows: list[dict]) -> dict[str, dict]:
    """Roll per-pick ADP deltas up per owner, carrying coverage.

    ``total_delta`` is None for an owner with no matched picks. Reporting 0.0
    there would read as a league-average draft rather than an ungraded one.
    Keeper rows are excluded, matching ``draft_skill``.
    """
    totals: dict[str, float] = defaultdict(float)
    graded: dict[str, int] = defaultdict(int)
    seen: dict[str, int] = defaultdict(int)

    for r in rows:
        if r.get("is_keeper"):
            continue
        uid = str(r.get("drafter_id") or "")
        if not uid:
            continue
        seen[uid] += 1
        delta = r.get("adp_delta")
        if delta is None:
            continue
        totals[uid] += float(delta)
        graded[uid] += 1

    return {
        uid: {
            "total_delta": totals[uid] if graded[uid] else None,
            "graded_picks": graded[uid],
            "total_picks": seen[uid],
        }
        for uid in seen
    }
