"""Assemble the league-wide draft board for one season.

The board is the only screen that shows a whole draft class at once. It has to
work on draft night — when every pick sits at 0.0 production — so results and
grades are separated: picks always render, grade columns appear only once the
class has played.
"""

from __future__ import annotations

import collections
import logging

from app.models.league import (
    DraftBoardOwner, DraftBoardPick, DraftBoardResp, OwnerNeedsResp,
)
from app.services.aggregations import owner_ref
from sleeper_dynasty.engine.draft_baselines import owner_adp_grades
from sleeper_dynasty.engine.draft_par import points_above_round

log = logging.getLogger(__name__)


def available_seasons(entry) -> list[int]:
    """Every draft season on this chain, newest first."""
    return sorted(
        {int(p.get("draft_season") or 0)
         for p in (getattr(entry, "drafted_picks", None) or [])
         if p.get("draft_season")},
        reverse=True,
    )


def _needs_for_season(entry, season: int) -> list[OwnerNeedsResp] | None:
    """This season's "Going in" needs, or None when the league is ineligible
    or there is nothing stamped for it.

    Re-checks capabilities here rather than trusting an absent-vs-present
    ``draft_needs`` key alone: the grader already gates the expensive
    reconstruction on ``format == "dynasty"``/``roster_continuity``/
    ``multiyear_history`` (see ``GraderService.run``), but a league's format
    can change and a stale cache entry could otherwise leak a leftover
    season's needs onto a board that is no longer eligible for them. None
    (absent), never [], so the frontend omits the panel rather than
    rendering an empty one.

    ``format == "dynasty"`` (not merely ``roster_continuity``) is required
    because keeper leagues cannot be reconstructed at all: keepers enter the
    new season through the draft rather than a transaction, so the
    as-of-draft-day roster reconstruction has no way to model the annual
    release of everyone else and reads the whole prior roster back as
    "still there" -- every slot full, no holes, ever. See the matching gate
    and its full reasoning in ``GraderService.run``.
    """
    caps = getattr(entry, "capabilities", None) or {}
    if (caps.get("format") != "dynasty"
            or not caps.get("roster_continuity")
            or not caps.get("multiyear_history")):
        return None
    raw = (getattr(entry, "draft_needs", None) or {}).get(str(season))
    if not raw:
        return None
    return [OwnerNeedsResp(**row) for row in raw]


def build_draft_board(entry, *, season: int) -> DraftBoardResp | None:
    """One season's board, or None when there is nothing to show."""
    rows = [
        p for p in (getattr(entry, "drafted_picks", None) or [])
        if int(p.get("draft_season") or 0) == int(season)
    ]
    if not rows:
        return None

    rows = sorted(rows, key=lambda r: (
        int(r.get("pick_no") or 0) or
        (int(r.get("round") or 1) - 1) * int(r.get("picks_in_round") or 0)
        + int(r.get("slot") or 0)
    ))

    picks = [
        DraftBoardPick(
            player_id=str(r.get("player_id") or ""),
            full_name=str(r.get("full_name") or r.get("player_id") or ""),
            position=str(r.get("position") or ""),
            drafter_id=str(r.get("drafter_id") or ""),
            owner=owner_ref(entry, str(r.get("drafter_id") or "")) or None,
            round=int(r.get("round") or 0),
            slot=int(r.get("slot") or 0),
            picks_in_round=int(r.get("picks_in_round") or 0),
            pick_no=int(r.get("pick_no") or 0),
            is_keeper=bool(r.get("is_keeper")),
            production_total=float(r.get("production_total") or 0.0),
            production_started=float(r.get("production_started") or 0.0),
            production_regular=float(r.get("production_regular") or 0.0),
            production_playoff=float(r.get("production_playoff") or 0.0),
            production_toilet=float(r.get("production_toilet") or 0.0),
            games_started=int(r.get("games_started") or 0),
            adp=r.get("adp"),
            adp_delta=r.get("adp_delta"),
            projected_points=r.get("projected_points"),
            baseline=r.get("baseline"),
            baseline_delta=r.get("baseline_delta"),
            baseline_source=str(r.get("baseline_source") or ""),
            verdict=str(r.get("verdict") or ""),
            roster_status=str(r.get("roster_status") or "rostered"),
        )
        for r in rows
    ]
    has_verdicts = any(r.get("verdict") for r in rows)

    # Every pick above is a *result* and renders. Only these are *scored*:
    # keepers are shown, not scored (a keep is not a draft decision), and an
    # auction pick has no positional slot to grade against. One definition of
    # "this owner's draft" for the whole owners section — before this, the ADP
    # grade skipped keepers while the production ranking summed them, so the
    # same response carried two.
    scored = [
        r for r in rows
        if not r.get("is_keeper")
        # Absent on pre-feature rows, which were all snake/linear.
        and r.get("gradeable", True)
    ]

    # Graded means "a pick this draft is answerable for has played". Keeper and
    # auction points are real but are not this draft's doing, so they must not
    # flip it — otherwise an all-keeper class claims to be graded while the
    # owners section has nothing to rank.
    graded = any(float(r.get("production_total") or 0.0) > 0 for r in scored)

    grades = owner_adp_grades(scored)
    production_by_owner: dict[str, float] = {}
    for r in scored:
        uid = str(r.get("drafter_id") or "")
        production_by_owner[uid] = production_by_owner.get(uid, 0.0) + float(
            r.get("production_total") or 0.0)

    # Every figure here comes from the SAME `scored` list the ADP grade uses,
    # so the two can never carry different definitions of "this owner's draft".
    par_by_owner = points_above_round(scored)

    # Hit/Average/Bust, counted off the SAME verdict strings the pick rows
    # render — never judged again here, so the owner row and the rows beneath
    # it cannot disagree. Counted over `scored` for the same reason every other
    # owner figure is: a keep is not a draft decision. `verdict_for_row`
    # already refuses to judge a keeper, so this is belt-and-braces against a
    # cache entry stamped before that rule existed.
    verdicts_by_owner: dict[str, collections.Counter] = collections.defaultdict(
        collections.Counter)
    for r in scored:
        v = str(r.get("verdict") or "")
        if v:
            verdicts_by_owner[str(r.get("drafter_id") or "")][v] += 1

    # Over `rows`, not `scored`: this counts the class an owner actually made,
    # which is the number of rows the Picks ledger shows for them.
    picks_made_by_owner: collections.Counter = collections.Counter(
        str(r.get("drafter_id") or "") for r in rows)
    by_owner: dict[str, dict] = {}
    for r in scored:
        uid = str(r.get("drafter_id") or "")
        acc = by_owner.setdefault(uid, {
            "production_started": 0.0, "production_regular": 0.0,
            "production_playoff": 0.0, "production_toilet": 0.0})
        for key in acc:
            acc[key] += float(r.get(key) or 0.0)

    # Listed from everyone who MADE a pick, not just everyone with a scorable
    # one. An owner whose whole class was keepers or auction bids still drafted
    # here; dropping them silently shortens the ranking, which reads as "this
    # owner had no draft" rather than "this owner has no grade". Their figures
    # come back null/zero — absent, not average.
    drafters: list[str] = []
    for r in rows:
        uid = str(r.get("drafter_id") or "")
        if uid and uid not in drafters:
            drafters.append(uid)

    _UNGRADED = {"total_delta": None, "graded_picks": 0, "total_picks": 0}
    owners: list[DraftBoardOwner] = []
    for uid in drafters:
        g = grades.get(uid, _UNGRADED)
        owners.append(DraftBoardOwner(
            user_id=uid,
            owner=owner_ref(entry, uid) or None,
            adp_total_delta=g["total_delta"],
            graded_picks=g["graded_picks"],
            total_picks=g["total_picks"],
            production_total=production_by_owner.get(uid, 0.0),
            production_started=by_owner.get(uid, {}).get("production_started", 0.0),
            production_regular=by_owner.get(uid, {}).get("production_regular", 0.0),
            production_playoff=by_owner.get(uid, {}).get("production_playoff", 0.0),
            production_toilet=by_owner.get(uid, {}).get("production_toilet", 0.0),
            points_above_round=par_by_owner.get(uid),
            hit=verdicts_by_owner.get(uid, {}).get("hit", 0),
            average=verdicts_by_owner.get(uid, {}).get("average", 0),
            bust=verdicts_by_owner.get(uid, {}).get("bust", 0),
            picks_made=picks_made_by_owner.get(uid, 0),
        ))
    # Best draft first. PAR when graded — ranking by raw Total Points ranks
    # draft POSITION, since whoever picked first tends to win. ADP delta
    # otherwise. Either way the figure sorted by is one the board shows.
    owners.sort(
        key=lambda o: (
            (o.points_above_round or 0.0) if graded
            else (o.adp_total_delta if o.adp_total_delta is not None else 0.0)
        ),
        reverse=True,
    )

    fmt = str((getattr(entry, "capabilities", None) or {}).get("format")
              or "dynasty")

    # Named from the data rather than from the league format: one place decides
    # what the column is called, and it is the same place that filled it.
    _SOURCE_LABELS = {"rookie_ecr": "ECR", "sleeper_adp": "ADP"}
    baseline_label = ""
    for r in rows:
        label = _SOURCE_LABELS.get(str(r.get("baseline_source") or ""))
        if label and r.get("baseline") is not None:
            baseline_label = label
            break

    return DraftBoardResp(
        league_id=entry.league_id,
        season=int(season),
        seasons=available_seasons(entry),
        graded=graded,
        format=fmt,
        picks=picks,
        owners=owners,
        baseline_label=baseline_label,
        has_verdicts=has_verdicts,
        needs=_needs_for_season(entry, season),
    )
