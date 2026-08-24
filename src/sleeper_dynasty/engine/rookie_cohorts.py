"""Hit / Average / Bust, measured against what comparable picks actually scored.

A threshold like "beat your round average by 40 points" is a number somebody
made up. This module has none: a pick is a **Hit** if it beat three-quarters of
the players ranked where it was ranked, a **Bust** if it fell below a quarter of
them, and **Average** in between. Every bar is a percentile of real outcomes.

Two things make the comparison fair:

- **Cohorts are keyed by (ECR band, seasons held)**, and the totals are
  cumulative. A pick held one season is judged against what its peers had
  accumulated after one season, never against their careers.
- **Scoring is the league's own.** The committed history carries raw components,
  not points, because 6-point passing touchdowns move a QB-heavy cohort's bar by
  roughly thirty points against 4-point ones.

Pure. No I/O — callers thread in the history and the league's scoring settings.
"""

from __future__ import annotations

import statistics as st
from collections import defaultdict

# Upper bounds, inclusive. CONTINUOUS — ECR is fractional (8.7, 12.5, 18.2), and
# integer ranges with gaps once dumped 32 of 389 players into the bottom cohort,
# manufacturing false hits for anyone whose rank fell between two bands.
ECR_EDGES: tuple[float, ...] = (4.0, 8.0, 12.0, 18.0, 24.0, 36.0, 60.0)

# nflverse component -> this app's scoring-settings key.
_PRICED: tuple[tuple[str, str], ...] = (
    ("passing_yards", "pass_yd"), ("passing_tds", "pass_td"),
    ("interceptions", "pass_int"), ("passing_2pt_conversions", "pass_2pt"),
    ("rushing_yards", "rush_yd"), ("rushing_tds", "rush_td"),
    ("rushing_2pt_conversions", "rush_2pt"),
    ("receptions", "rec"), ("receiving_yards", "rec_yd"),
    ("receiving_tds", "rec_td"), ("receiving_2pt_conversions", "rec_2pt"),
    ("sack_fumbles_lost", "fum_lost"), ("rushing_fumbles_lost", "fum_lost"),
    ("receiving_fumbles_lost", "fum_lost"),
)

# The scoring-settings keys `_PRICED` can express.
_PRICED_KEYS: frozenset[str] = frozenset(key for _, key in _PRICED)

# Keys a league may price that this extract cannot express, but which cannot
# meaningfully move a bar built from THIS population — offensive rookies off a
# FantasyPros rookie board, measured in nflverse passing/rushing/receiving
# components.
#
# WHY THIS SET EXISTS AT ALL. The original rule refused on any nonzero key
# outside `_PRICED`. Every Sleeper league prices a kicker and a team defense,
# so it refused for **every real league** and the verdict was empty everywhere
# — measured on the reference league, 29 of its 44 nonzero keys were outside
# `_PRICED` and 26 of those could only ever accrue to a kicker or a defense.
# The rule was asking "does the league price anything I can't express?" when
# the question that matters is "can what I can't express change the total of a
# player I am comparing?".
_KICKER_AND_TEAM_DEFENSE: frozenset[str] = frozenset({
    # Kicker. No player on a rookie skill board attempts a field goal.
    "fga", "fgm", "fgm_0_19", "fgm_20_29", "fgm_30_39", "fgm_40_49",
    "fgm_50p", "fgm_yds", "fgm_yds_over_30", "fgmiss", "fgmiss_0_19",
    "fgmiss_20_29", "fgmiss_30_39", "fgmiss_40_49", "fgmiss_50p",
    "xpa", "xpm", "xpmiss",
    # Team defense / special-teams UNIT. Scored against a DST roster slot,
    # never against an individual offensive player.
    "pts_allow", "pts_allow_0", "pts_allow_1_6", "pts_allow_7_13",
    "pts_allow_14_20", "pts_allow_21_27", "pts_allow_28_34", "pts_allow_35p",
    "yds_allow", "yds_allow_0_100", "yds_allow_100_199", "yds_allow_200_299",
    "yds_allow_300_349", "yds_allow_350_399", "yds_allow_400_449",
    "yds_allow_450_499", "yds_allow_500_549", "yds_allow_550p",
    "def_td", "def_2pt", "def_st_td", "def_st_ff", "def_st_fum_rec",
    "def_pr_td", "def_kr_td", "def_forced_punts", "def_3_and_out",
    "sack", "sack_yd", "safe", "int",
})

# Keys an offensive player CAN accrue, kept out of the refusal on a measured
# materiality bound rather than an impossibility argument — the distinction is
# deliberate, which is why they are a separate set.
#
# `fum` is total fumbles. `_PRICED` already carries `fum_lost`, so the only
# unmodelled part is the non-lost ones — one or two a season at a dollar or two
# apiece. The rest are individual special-teams and loose-ball credits: a
# receiver recovering a fumble, a gunner forcing one, a returner taking a kick
# back. Real, and a handful of occurrences across a career.
#
# MEASURED, on the reference league's 69 judged picks: perturbing every total
# by +/-5 points moved 3 verdicts, and each sat within a few points of a
# percentile edge, where "average" and "hit" are already a coin toss. Bars in
# that league spread 26-472 points. Anything that can move a total further than
# this — return YARDAGE, first downs, `pass_sack`, positional bonuses like
# `bonus_rec_te` (30-60 points a season to a TE) — is deliberately absent and
# still refuses.
_BOUNDED_RESIDUAL: frozenset[str] = frozenset({
    "fum",
    "ff", "fum_rec", "fum_rec_td", "blk_kick",
    "st_td", "st_ff", "st_fum_rec",
})

# The allowlist is the whole safety property. A key nobody has classified might
# be worth sixty points a season, so the fallback stays deny — `build_cohorts`
# refuses on anything that is neither priced nor listed here. Adding a Sleeper
# setting to this set is a claim that it cannot move a rookie skill player's
# total by more than a rounding error; adding one to `_PRICED` is the way to
# handle a key that can.
_IGNORABLE: frozenset[str] = _KICKER_AND_TEAM_DEFENSE | _BOUNDED_RESIDUAL


def band(ecr: float) -> int:
    """Which cohort an ECR falls in. Every real number lands in exactly one."""
    for i, hi in enumerate(ECR_EDGES):
        if ecr <= hi:
            return i
    return len(ECR_EDGES)


def score_season(stats: dict, scoring: dict) -> float:
    """Price one season's components with a league's settings.

    A component the league does not price contributes 0 rather than raising —
    a league with no 2-point setting is not an error, it just scores none.
    """
    total = 0.0
    for component, key in _PRICED:
        value = stats.get(component)
        if not value:
            continue
        total += float(value) * float(scoring.get(key) or 0.0)
    return total


def build_cohorts(
    history: dict, scoring: dict, *, min_n: int = 8,
) -> dict[str, tuple[float, float, float]]:
    """``{"band|n": (p25, median, p75)}`` over cumulative totals.

    A cell with fewer than ``min_n`` players is **omitted**, not computed. A
    percentile drawn from four players is noise wearing a percentile's
    authority, and a verdict is not worth issuing from it.

    Two more refusals, both for the same reason (wrong is worse than absent):

    - A league that prices anything neither in ``_PRICED`` nor in
      ``_IGNORABLE`` gets **no cohorts at all** — a bonus-inclusive real total
      compared against a bar that never saw the bonus is a confident, wrong
      answer. ``_IGNORABLE`` is the narrow exception: scoring that cannot
      reach this population (kicker, team defense) or cannot move it more than
      a rounding error. Unclassified keys refuse.
    - A cell whose ``p25 == p75`` is **omitted**. That happens when every
      component this league prices scored 0 (e.g. ``scoring == {}`` — a
      truncated payload, or a platform that carries no Sleeper scoring keys
      at all): every cumulative total in the bucket is 0.0, the bar is a
      single degenerate point, and ANY positive total would read as a "hit"
      against it. A distribution that cannot discriminate must not be used
      to judge.
    """
    if any(v and k not in _PRICED_KEYS and k not in _IGNORABLE
           for k, v in (scoring or {}).items()):
        return {}

    buckets: dict[str, list[float]] = defaultdict(list)
    for rec in (history or {}).values():
        ecr = rec.get("ecr")
        if ecr is None:
            continue
        b = band(float(ecr))
        cumulative = 0.0
        for season in rec.get("seasons") or []:
            cumulative += score_season(season, scoring)
            buckets[f"{b}|{int(season['n'])}"].append(cumulative)

    out: dict[str, tuple[float, float, float]] = {}
    for key, values in buckets.items():
        if len(values) < min_n:
            continue
        values.sort()
        p25 = values[min(len(values) - 1, int(0.25 * len(values)))]
        p75 = values[min(len(values) - 1, int(0.75 * len(values)))]
        if p25 == p75:
            continue
        out[key] = (p25, st.median(values), p75)
    return out


# The only baseline comparable to these cohorts. `band()` expects a rookie
# consensus rank (~1-144); a redraft league's Sleeper ADP (~1-300) would band
# into a cohort it has no relationship to and return a confident, meaningless
# verdict. Wrong is worse than absent — a blank column reads as "no data", a
# bogus Hit reads as truth. Any NEW baseline source must be judged against this
# list before it can be graded.
COMPARABLE_BASELINE = "rookie_ecr"


def verdict_for_row(row: dict, cohorts: dict[str, tuple[float, float, float]]) -> str:
    """A pick row -> its verdict, or "" when the row is not comparable.

    Owns the eligibility rule as well as the comparison, so the two cannot
    drift apart in separate files.

    An **auction** pick falls out for free — `build_drafted_pick_results` gates
    the baseline on `gradeable`, so it carries no rookie-ECR rank to judge. A
    **keeper** does NOT: a keep inside an otherwise gradeable rookie draft gets
    a baseline like any other row, so the exclusion has to be written down.
    (An earlier version of this docstring claimed both fell out for free. Only
    one did.) A keep is not a draft decision, which is the same reason
    `draft_skill`, `build_draft_review` and the board's owner rollup all score
    the identical `scored` subset — and the owner row's Hit/Bust counts have to
    equal the verdicts on the pick rows beneath it, which they cannot do if a
    keeper carries one on the ledger and is excluded from the rollup.
    """
    if row.get("is_keeper"):
        return ""
    if row.get("baseline_source") != COMPARABLE_BASELINE:
        return ""
    return verdict(
        row.get("production_total"),
        row.get("baseline"),
        int(row.get("seasons_held") or 0),
        cohorts,
    )


def verdict(
    total: float | None,
    ecr: float | None,
    seasons_held: int,
    cohorts: dict[str, tuple[float, float, float]],
) -> str:
    """``"hit" | "average" | "bust"``, or ``""`` when it cannot be judged.

    Falls back ONE step to ``seasons_held - 1`` when the exact cell is missing
    or too thin — a pick held three seasons against cells for one and two is
    judged at two. Never upward (that would measure a three-season total
    against a one-season bar and call nearly everything a hit) and never more
    than one step down either: a pick held nine seasons with coverage only at
    n=1 must read as unjudgeable, not get silently compared to a rookie-year
    bar just because SOME earlier cell happens to exist.
    """
    if total is None or ecr is None or seasons_held < 1:
        return ""
    b = band(float(ecr))
    for n in (int(seasons_held), int(seasons_held) - 1):
        if n < 1:
            break
        cell = cohorts.get(f"{b}|{n}")
        if cell:
            p25, _median, p75 = cell
            return "hit" if total > p75 else "bust" if total < p25 else "average"
    return ""
