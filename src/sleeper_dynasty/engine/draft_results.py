"""Per-pick draft outcome results for the Future & Draft owner tab.

Pure functions: resolve each rookie-draft pick into a row carrying its career-arc
value (current/lowest/highest), value-vs-slot delta, how it was acquired, and the
started points it produced for the drafting owner. No I/O — callers thread in the
matchup/value/snapshot data already pulled during refresh.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Callable

from sleeper_dynasty.engine.draft_baselines import adp_delta
from sleeper_dynasty.engine.draft_signals import DraftedPick
from sleeper_dynasty.engine.rookie_board import board_delta


def started_points_while_on_roster(
    pid: str,
    uid: str,
    *,
    phase: str,
    matchups: dict[tuple[str, int, int], dict],
    roster_to_user_by_league: dict[str, dict[int, str]],
    phase_by_lwr: dict[tuple[str, int, int], str] | None = None,
    playoff_week_start_by_league: dict[str, int] | None = None,
) -> float:
    """Points ``pid`` scored for ``uid`` in weeks matching ``phase``.

    ``phase`` is one of:
      - "total"   -- all weeks, **bench included** (received-only Total Points).
      - "started" -- started points in EVERY week, phase-blind. Regular +
        playoff + toilet is LESS than this: a bye or placement week belongs to
        no phase. Use this as the denominator's partner for Start %, never the
        sum of the three.
      - "regular" -- started points in weeks before playoff start.
      - "playoff" -- started points in live title-bracket games (per ``phase_by_lwr``).
      - "toilet"  -- started points in losers-bracket games.

    All but "total" count only weeks ``pid`` was in the starting lineup. Owner-gated
    by weekly roster membership, so points after the owner trades the player away
    don't count.
    """
    phase_by_lwr = phase_by_lwr or {}
    playoff_week_start_by_league = playoff_week_start_by_league or {}
    started_only = phase != "total"
    roster_field = "starters" if started_only else "players"
    total = 0.0
    for (lg, wk, rid), entry in matchups.items():
        if roster_to_user_by_league.get(lg, {}).get(rid) != uid:
            continue
        # "started" is started-only but phase-BLIND: a bye week and a placement
        # game belong to no phase, so filtering by phase would silently drop
        # them. That undercount is worse for better teams, because better teams
        # get byes — see the docstring.
        if phase not in ("total", "started"):
            ps = playoff_week_start_by_league.get(lg, 15)
            wk_phase = "regular" if wk < ps else phase_by_lwr.get((lg, wk, rid), "dropped")
            if wk_phase != phase:
                continue
        if pid not in (entry.get(roster_field) or []):
            continue
        total += float((entry.get("players_points") or {}).get(pid, 0.0) or 0.0)
    return total


def started_games_while_on_roster(
    pid: str,
    uid: str,
    *,
    matchups: dict[tuple[str, int, int], dict],
    roster_to_user_by_league: dict[str, dict[int, str]],
) -> int:
    """Count of weeks ``pid`` was in ``uid``'s starting lineup while on roster.

    One combined number across all phases (regular + playoff + toilet). Owner-gated
    by weekly roster membership, so weeks after the owner traded the player away
    don't count. Bench-only weeks (not in ``starters``) don't count.
    """
    count = 0
    for (lg, _wk, rid), entry in matchups.items():
        if roster_to_user_by_league.get(lg, {}).get(rid) != uid:
            continue
        if pid in (entry.get("starters") or []):
            count += 1
    return count


def seasons_held_while_on_roster(
    pid: str,
    uid: str,
    *,
    matchups: dict[tuple[str, int, int], dict],
    roster_to_user_by_league: dict[str, dict[int, str]],
    league_season_by_id: dict[str, int],
    completed_seasons: set[int] | None = None,
) -> int:
    """How many distinct NFL seasons ``uid`` held ``pid`` for at least one week.

    This is the cohort key, and it is deliberately **seasons held**, not seasons
    elapsed. Production is owner-gated — it stops the day the player is traded
    away — so measuring it against a cohort that kept accruing would brand every
    good pick you ever sold a bust. One week counts as the whole season: the
    alternative is a fractional cohort that does not exist.

    ``completed_seasons``, when given, restricts the count to seasons in that
    set — the cohort's own ``n`` only ever counts COMPLETE seasons (the
    committed history has no notion of a partial year), so an in-progress NFL
    season must not inflate this count either: one played week and a handful
    of points would otherwise bump a pick from cell ``n`` to ``n+1`` — a much
    higher bar — and flip Hit to Bust for as long as that season stays live.
    ``None`` (the default) counts every season held, unrestricted, so existing
    callers are unaffected.
    """
    seasons: set[int] = set()
    for (lg, _wk, rid), entry in matchups.items():
        if roster_to_user_by_league.get(lg, {}).get(rid) != uid:
            continue
        if pid not in (entry.get("players") or []):
            continue
        season = league_season_by_id.get(lg)
        if season:
            seasons.add(int(season))
    if completed_seasons is not None:
        seasons &= completed_seasons
    return len(seasons)


def derive_roster_status(
    pid: str,
    uid: str,
    *,
    current_holders: dict[str, str],
    traded_away_set: set[tuple[str, str]],
) -> str:
    """Current standing of ``pid`` relative to the drafting owner ``uid``.

    - "rostered": still on ``uid``'s roster right now.
    - "traded":   no longer on ``uid``'s roster, and ``uid`` traded him away.
    - "dropped":  no longer on ``uid``'s roster via any other path (waiver/drop).
    """
    if current_holders.get(pid) == uid:
        return "rostered"
    if (uid, pid) in traded_away_set:
        return "traded"
    return "dropped"


def build_drafted_pick_results(
    picks: list[DraftedPick],
    *,
    ktc_floats: dict[str, float],
    normalized_name_by_pid: dict[str, str],
    names: dict[str, str],
    positions: dict[str, str],
    extremes_by_name: dict[str, tuple[float, float]],
    acquired_set: set[tuple[str, str]],
    points_fn: Callable[[str, str, str], float],
    games_fn: Callable[[str, str], int],
    current_holders: dict[str, str],
    traded_away_set: set[tuple[str, str]],
    adp_by_draft: dict[str, dict[str, float]] | None = None,
    projected_by_player: dict[str, float] | None = None,
    rookie_ecr_by_draft: dict[str, dict[str, float]] | None = None,
    seasons_fn: Callable[[str, str], int] | None = None,
) -> list[dict]:
    """One result dict per rookie-draft pick.

    Args:
        ktc_floats: player_id -> current superflex value.
        normalized_name_by_pid: player_id -> KTC normalized_name (snapshot key).
        names / positions: player_id -> display name / position.
        extremes_by_name: normalized_name -> (lowest, highest) from snapshots.
        acquired_set: {(drafter_uid, player_id)} the drafter got via a trade.
        points_fn: (player_id, uid, phase) -> points; phase in
            {"total", "started", "regular", "playoff", "toilet"}.
        adp_by_draft: draft_id -> {player_id -> ADP}. Keyed per draft rather
            than flattened across the whole chain, so a player drafted in more
            than one season grades against each season's own market baseline
            instead of whichever class happened to be read last.
    """
    # Round averages of current value, per (season, round).
    groups: dict[tuple[int, int], list[float]] = defaultdict(list)
    for p in picks:
        groups[(p.draft_season, p.round)].append(ktc_floats.get(p.player_id, 0.0))
    avg_by_group = {
        k: (sum(vals) / len(vals)) if vals else 0.0 for k, vals in groups.items()
    }

    out: list[dict] = []
    for p in picks:
        cur = ktc_floats.get(p.player_id, 0.0)
        nn = normalized_name_by_pid.get(p.player_id)
        lo, hi = extremes_by_name.get(nn, (cur, cur)) if nn else (cur, cur)
        lo, hi = min(lo, cur), max(hi, cur)  # current always inside the arc
        adp = (
            (adp_by_draft or {}).get(p.draft_id, {}).get(p.player_id)
            if p.gradeable else None
        )
        # The BASELINE is whichever external expectation this class actually
        # has. A dynasty rookie class has a rookie consensus board; a
        # redraft/keeper class has Sleeper ADP. Rookie ECR wins when both are
        # present — grading a rookie class against overall-NFL ADP would price
        # a 1.01 against ~30th overall and print a 29-pick reach.
        #
        # `adp`/`adp_delta` below keep their existing Sleeper-ADP meaning.
        # Repointing them would be a shape change on a persisted field.
        ecr = (
            (rookie_ecr_by_draft or {}).get(p.draft_id, {}).get(p.player_id)
            if p.gradeable else None
        )
        # NOTE: `rookie_cohorts.COMPARABLE_BASELINE` gates which of these values
        # may be graded into a Hit/Average/Bust verdict. Adding a source here
        # means deciding there.
        if ecr is not None:
            baseline, baseline_source = ecr, "rookie_ecr"
        elif adp is not None:
            baseline, baseline_source = adp, "sleeper_adp"
        else:
            baseline, baseline_source = None, ""
        projected = (projected_by_player or {}).get(p.player_id)
        out.append({
            "player_id": p.player_id,
            "full_name": names.get(p.player_id, p.player_id),
            "position": positions.get(p.player_id, ""),
            "drafter_id": p.drafter_id,
            "round": p.round,
            "slot": p.slot,
            "picks_in_round": p.picks_in_round,
            "draft_season": p.draft_season,
            "acquired_via_trade": (p.drafter_id, p.player_id) in acquired_set,
            "current_value": cur,
            "lowest_value": lo,
            "highest_value": hi,
            "avg_slot_value": avg_by_group.get((p.draft_season, p.round), 0.0),
            "production_total": points_fn(p.player_id, p.drafter_id, "total"),
            # Started points across EVERY week — the honest denominator partner
            # for Start %. Not the sum of the three phase tallies: a bye or a
            # placement week belongs to no phase and would vanish from that sum.
            "production_started": points_fn(p.player_id, p.drafter_id, "started"),
            "production_regular": points_fn(p.player_id, p.drafter_id, "regular"),
            "production_playoff": points_fn(p.player_id, p.drafter_id, "playoff"),
            "production_toilet": points_fn(p.player_id, p.drafter_id, "toilet"),
            "games_started": games_fn(p.player_id, p.drafter_id),
            "roster_status": derive_roster_status(
                p.player_id, p.drafter_id,
                current_holders=current_holders,
                traded_away_set=traded_away_set),
            "pick_no": p.pick_no,
            "is_keeper": p.is_keeper,
            # False for auction: the row is a real result and renders, but
            # nothing may *grade* it — an auction's pick_no is chronological,
            # not positional, so any slot comparison is noise. Consumers that
            # rank or score picks must filter on this.
            "gradeable": p.gradeable,
            "draft_kind": p.draft_kind,
            "adp": adp,
            "adp_delta": adp_delta(pick_no=p.pick_no, adp=adp),
            "baseline": baseline,
            "baseline_delta": board_delta(pick_no=p.pick_no, ecr=baseline),
            "baseline_source": baseline_source,
            "projected_points": projected,
            "seasons_held": seasons_fn(p.player_id, p.drafter_id) if seasons_fn else 0,
        })
    return out


def _draft_position(p: dict) -> int:
    """Overall pick number. Round 2 slot 1 is the 13th pick, not the 1st."""
    explicit = int(p.get("pick_no") or 0)
    if explicit:
        return explicit
    per_round = int(p.get("picks_in_round") or 0)
    return (int(p.get("round") or 1) - 1) * per_round + int(p.get("slot") or 0)


def _market_row(p: dict) -> dict:
    return {
        "player_id": p.get("player_id"),
        "full_name": p.get("full_name") or p.get("player_id"),
        "position": p.get("position") or "",
        "drafter_id": p.get("drafter_id"),
        "round": int(p.get("round") or 0),
        "slot": int(p.get("slot") or 0),
        "draft_position": _draft_position(p),
        "baseline_delta": float(p["baseline_delta"]),
        "baseline_source": p.get("baseline_source") or "",
    }


def _market_preview(field: list[dict]) -> tuple[dict | None, dict | None, int]:
    """Best value / biggest reach vs consensus (rookie ECR, or Sleeper ADP),
    independent of production — real the moment the draft ends, unlike the
    production-ranked best/worst below.

    ``baseline_delta`` is pick_no minus the player's consensus rank: positive
    means he fell past where the market had him (a steal), negative means he
    went ahead of it (a reach) — the same figure the draft board's per-pick
    slot +/- already prices. A pick with no baseline match (no rookie ECR, no
    ADP) is excluded rather than counted as neutral; ``matched`` reports how
    many scored picks had one at all, so a class with thin coverage doesn't
    silently print a hollow "best value".

    Needs at least two matched picks to call anything a steal or a reach —
    same "nothing to compare against" rule as the production grade. Ties
    broken by projected points (a bigger name falling, or getting reached
    for, reads as more consequential), then draft order for determinism.
    """
    candidates = [p for p in field if p.get("baseline_delta") is not None]
    if len(candidates) < 2:
        return None, None, len(candidates)

    def key(p: dict) -> tuple[float, float, int]:
        return (
            float(p["baseline_delta"]),
            float(p.get("projected_points") or 0.0),
            -_draft_position(p),
        )

    best_value = _market_row(max(candidates, key=key))
    reach = _market_row(min(candidates, key=key))
    return best_value, reach, len(candidates)


def build_draft_review(picks: list[dict]) -> dict | None:
    """How the most recent draft panned out. Pure; None when unreviewable.

    Grades each pick by **rank against its own draft** rather than an external
    baseline: sort the class by production, and compare where a player finished
    to where he was taken. A back taken 13th who produced 1st beat his slot by
    12. That needs no ADP table, no positional model, and no assumption about
    what a given slot "should" return — the draft is its own yardstick, which
    is the only honest one when league size and scoring both vary.

    **Results and grades have different availability dates.** A class that has
    not played yet returns ``graded: False`` with null best/worst rather than
    None: right after a draft every pick sits at 0.0 and naming a "best pick"
    out of ties would invent one, but the results — who took whom, where — are
    real the moment the draft completes and must still render. It is not,
    however, silent about the picks: ``best_value``/``reach``/``matched``
    (see ``_market_preview``) grade the class against draft-day consensus
    instead, which needs no played game — the ungraded window's "so what".

    **Only scored picks are in the field.** Keepers are shown elsewhere but
    never scored — a keep is not a draft decision, and leaving one in would
    let it win "best pick", pad "N of M picks beat their slot", and shift the
    production ranking every real pick is measured against. Auction picks
    (``gradeable: False``) are out for the same reason ``draft_skill``
    excludes them: an auction's ``pick_no`` is the order money changed hands,
    so a slot delta against it is noise. The market preview shares this same
    field, for the same reasons.

    **A class with nothing scorable still reports its results.** An all-auction
    or all-keeper class can never be graded, but the draft happened, and "the
    class is in the books, N picks" is both true and worth saying. Returning
    None there would send the lead to trade-of-the-week and take the only link
    to the draft board with it — worse than saying less.

    None is reserved for a class that cannot be reviewed at all: no picks, or
    fewer than two in the season.
    """
    if not picks:
        return None
    season = max(int(p.get("draft_season") or 0) for p in picks)
    made = [p for p in picks if int(p.get("draft_season") or 0) == season]
    if len(made) < 2:
        return None
    field = [
        p for p in made
        if not p.get("is_keeper")
        # Absent on pre-feature rows, which predate auction support and were
        # all snake/linear — default True rather than silently emptying them.
        and p.get("gradeable", True)
    ]
    # Nothing scorable: report the results, grade nothing. `total` is every
    # pick MADE, because that is what "N picks" means to a reader. Only the
    # graded denominator below narrows to scored picks, since only those can
    # beat a slot.
    if len(field) < 2:
        best_value, reach, matched = _market_preview(field)
        return {
            "season": season, "graded": False,
            "best": None, "worst": None,
            "beat_slot": 0, "total": len(made),
            "best_value": best_value, "reach": reach, "matched": matched,
        }

    if not any(float(p.get("production_total") or 0.0) > 0 for p in field):
        # Same reading as the nothing-scorable case above: ungraded `total` is
        # every pick made, not just the scorable ones.
        best_value, reach, matched = _market_preview(field)
        return {
            "season": season, "graded": False,
            "best": None, "worst": None,
            "beat_slot": 0, "total": len(made),
            "best_value": best_value, "reach": reach, "matched": matched,
        }

    # Rank by production, best first. The secondary key on draft position keeps
    # tied production deterministic instead of dependent on input order.
    ranked = sorted(
        field,
        key=lambda p: (-float(p.get("production_total") or 0.0), _draft_position(p)),
    )

    rows = []
    for rank, p in enumerate(ranked, start=1):
        pos = _draft_position(p)
        rows.append({
            "player_id": p.get("player_id"),
            "full_name": p.get("full_name") or p.get("player_id"),
            "position": p.get("position") or "",
            "drafter_id": p.get("drafter_id"),
            "round": int(p.get("round") or 0),
            "slot": int(p.get("slot") or 0),
            "draft_position": pos,
            "production_total": round(float(p.get("production_total") or 0.0), 1),
            # Positive = finished ahead of where he was taken.
            "slot_delta": pos - rank,
        })

    # Ties broken by production so the "best" of several equal deltas is the
    # one who actually scored more; the reverse for "worst".
    best = max(rows, key=lambda r: (r["slot_delta"], r["production_total"]))
    worst = min(rows, key=lambda r: (r["slot_delta"], r["production_total"]))
    best_value, reach, matched = _market_preview(field)
    return {
        "season": season,
        "graded": True,
        "best": best,
        "worst": worst,
        "beat_slot": sum(1 for r in rows if r["slot_delta"] > 0),
        "total": len(rows),
        "best_value": best_value, "reach": reach, "matched": matched,
    }
