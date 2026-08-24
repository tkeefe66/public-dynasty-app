"""Pure aggregations: ChainCacheEntry → DashboardResp.

No IO. Server-side filtering for year/lens/sort/filter.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from app.models.league import (
    BracketWatch,
    DashboardResp,
    DraftReview,
    DraftReviewPick,
    HeroStat,
    HeroStats,
    LatestTrade,
    LeagueCapabilitiesResp,
    LeagueSummary,
    Records,
    StandingRow,
    WeekRecap,
    WeekRecapBlowout,
    WeekRecapFigure,
)
from app.services.chain_cache import ChainCacheEntry
from app.services.identity import owner_name, owner_ref
from sleeper_dynasty.engine.capabilities import (
    capabilities_from_dict,
    capabilities_to_dict,
)
from sleeper_dynasty.engine.gm_rating import rating_to_letter, rating_to_stage

log = logging.getLogger(__name__)

Lens = Literal["ktc", "production"]
Year = int | Literal["all"]


def _ordinal(n: int) -> str:
    """1 → '1st', 2 → '2nd', 3 → '3rd', 4+ → 'Nth'."""
    if 11 <= (n % 100) <= 13:
        return f"{n}th"
    return f"{n}{('th', 'st', 'nd', 'rd', 'th', 'th', 'th', 'th', 'th', 'th')[n % 10]}"


def _finish_label(rec: dict) -> str:
    """Per-season Finish string.

    Playoff (winners-bracket) teams show their championship place — ``1st 🏆``,
    ``2nd``, ``3rd`` … Toilet-bowl (losers-bracket) teams show the draft pick the
    bracket earned them — ``1.01 🚽`` (toilet champion) through ``1.06`` — since
    that bracket sets draft order. Falls back to coarse flags for older cached
    records that predate the placement fields, and ``—`` when neither applies.
    """
    pp = rec.get("playoff_place")
    if pp:
        return "1st 🏆" if pp == 1 else _ordinal(pp)
    tp = rec.get("toilet_place")
    if tp:
        pick = f"1.{tp:02d}"
        return f"{pick} 🚽" if tp == 1 else pick
    if rec.get("champion"):
        return "1st 🏆"
    if rec.get("runner_up"):
        return "2nd"
    if rec.get("made_playoffs"):
        return "Playoffs"
    return "—"


def _fmt_record(
    uid: str, year: Year, season_records: dict
) -> tuple[str | None, str | None, str | None]:
    """Return (season_record, best_finish, playoff_record) strings for one owner.

    Per-season: season_record = reg W-L, best_finish = playoff result, playoff_record = None.
    All-time:   season_record = career reg W-L, best_finish = best career achievement,
                playoff_record = career playoff W-L ("4-0", "1-1", etc.) or None.
    Returns (None, None, None) when no record data is available.
    """
    sr = season_records or {}

    if year == "all":
        if not sr:
            return None, None, None
        total_w = total_l = total_t = 0
        champs = toilet_titles = p_wins = p_losses = seasons = 0
        for yr_data in sr.values():
            rec = (yr_data or {}).get(uid) or {}
            if not rec:
                continue
            total_w += rec.get("wins", 0)
            total_l += rec.get("losses", 0)
            total_t += rec.get("ties", 0)
            seasons += 1
            if rec.get("champion"):
                champs += 1
            if rec.get("toilet_place") == 1:
                toilet_titles += 1
            if rec.get("made_playoffs"):
                p_wins += rec.get("rounds_won", 0)
                p_losses += 0 if rec.get("champion") else 1
        if seasons == 0:
            return None, None, None
        reg_str = f"{total_w}-{total_l}" if total_t == 0 else f"{total_w}-{total_l}-{total_t}"
        # Career badge: a 🏆 per championship, a 🚽 per Toilet Bowl title.
        parts: list[str] = []
        if champs:
            parts.append("🏆" * champs)
        if toilet_titles:
            parts.append("🚽" * toilet_titles)
        finish_str = " ".join(parts) if parts else "—"
        playoff_str = f"{p_wins}-{p_losses}" if p_wins + p_losses > 0 else None
        return reg_str, finish_str, playoff_str

    else:  # specific year
        yr_data = sr.get(str(year)) or {}
        rec = yr_data.get(uid) or {}
        if not rec:
            return None, None, None
        w, l, t = rec.get("wins", 0), rec.get("losses", 0), rec.get("ties", 0)
        if w == 0 and l == 0 and t == 0:
            return "—", "—", None
        record_str = f"{w}-{l}" if t == 0 else f"{w}-{l}-{t}"
        return record_str, _finish_label(rec), None


def _filter_trades_by_year(
    entry: ChainCacheEntry, year: Year
) -> list[dict[str, Any]]:
    if year == "all":
        return list(entry.resolved_trades)
    return [rt for rt in entry.resolved_trades if rt["trade"]["season"] == year]


def _grade_for(entry: ChainCacheEntry, trade_id: str) -> dict[str, Any]:
    return entry.grades.get(trade_id) or {}


def _letter_grade(net_ktc_by_uid: dict[str, float]) -> dict[str, str]:
    """League-relative letter grade from realized net_ktc, via z-score buckets.

    Realized Trade Value is all-positive and league-specific, so absolute
    thresholds don't transfer. z-score across the league instead. When all
    owners are equal (sd == 0), everyone receives "B".
    """
    vals = list(net_ktc_by_uid.values())
    n = len(vals)
    if n == 0:
        return {}
    mean = sum(vals) / n
    sd = (sum((v - mean) ** 2 for v in vals) / n) ** 0.5

    def bucket(z: float) -> str:
        if z >= 1.25:
            return "A"
        if z >= 0.75:
            return "A−"
        if z >= 0.25:
            return "B+"
        if z >= -0.25:
            return "B"
        if z >= -0.75:
            return "B−"
        if z >= -1.25:
            return "C"
        return "D"

    if sd == 0:
        return {uid: "B" for uid in net_ktc_by_uid}
    return {uid: bucket((v - mean) / sd) for uid, v in net_ktc_by_uid.items()}


def _aggregate_owner_rows(
    entry: ChainCacheEntry, trades: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    def _blank(uid: str) -> dict[str, Any]:
        return {
            "user_id": uid,
            "net_ktc": 0.0, "production_total": 0.0,
            "production_regular": 0.0,
            "production_playoff": 0.0,
            "production_toilet": 0.0,
            "production_started": 0.0,
            "trades": 0,
            "net_ktc_at_trade": 0.0, "net_ktc_today_subset": 0.0,
        }

    rows: dict[str, dict[str, Any]] = {uid: _blank(uid) for uid in entry.owners}
    for rt in trades:
        g = _grade_for(entry, rt["trade"]["transaction_id"])
        received = g.get("received_ktc") or {}
        swing = g.get("snapshot_value_swing") or {}
        # received_ktc carries every side (written in the grading stage), so
        # keying off it covers the same uids snapshot_value_swing did.
        for uid, val in received.items():
            row = rows.setdefault(uid, _blank(uid))
            row["net_ktc"] += float(val or 0)               # realized headline
            at_map = g.get("at_trade_value_swing") or {}
            if uid in at_map:
                row["net_ktc_at_trade"] += float(at_map[uid] or 0)
                row["net_ktc_today_subset"] += float(swing.get(uid, 0) or 0)
            row["production_total"] += float(
                (g.get("production_total") or {}).get(uid, 0) or 0
            )
            row["production_regular"] += float(
                (g.get("production_regular") or {}).get(uid, 0) or 0
            )
            row["production_playoff"] += float(
                (g.get("production_playoff") or {}).get(uid, 0) or 0
            )
            row["production_toilet"] += float(
                (g.get("production_toilet") or {}).get(uid, 0) or 0
            )
            row["production_started"] += float(
                (g.get("production_started") or {}).get(uid, 0) or 0
            )
            row["trades"] += 1
    return rows


def _compute_gm_trends(
    ratings: dict[str, int], prev_ratings: dict[str, int]
) -> dict[str, int]:
    """prev_rank − current_rank per uid (positive = climbed). Zero when no prior snapshot.

    ``prev_ratings`` must already be scoped to the entry's current rating
    model -- this function has no store access and can't tell a same-model
    predecessor from a different one. The caller gets that for free by
    fetching it through ``leaderboard.load_prev_ratings(..., model=...)``,
    which returns {} rather than a cross-model snapshot (see
    RatingSnapshotStore's module docstring for why that matters)."""
    if not prev_ratings:
        return {uid: 0 for uid in ratings}
    prev_rank = {
        uid: i + 1
        for i, (uid, _) in enumerate(
            sorted(prev_ratings.items(), key=lambda kv: kv[1], reverse=True)
        )
    }
    current_rank = {
        uid: i + 1
        for i, (uid, _) in enumerate(
            sorted(ratings.items(), key=lambda kv: kv[1], reverse=True)
        )
    }
    return {uid: (prev_rank.get(uid, current_rank[uid]) - current_rank[uid]) for uid in ratings}


def _rise_hero_stat(
    entry: ChainCacheEntry,
    current_ratings: dict[str, int],
    year: Year,
    is_in_season: bool,
    prev_ratings: dict[str, int],
) -> HeroStat:
    """Context-aware 'Biggest Riser' KPI card.

    Picks label and baseline from four modes:
      weekly      — in-season + current year → week-over-week snapshot
      off_season  — off-season + current year → end-of-last-season baseline
      year_riser  — past completed year → year-minus-1 baseline
      all_time    — all-years view → first-season baseline
    """
    season_ratings = entry.season_ratings or {}
    seasons_with_data = sorted(int(k) for k in season_ratings if k.isdigit())
    chain_seasons = sorted({lg["season"] for lg in entry.chain})
    current_season = max(chain_seasons) if chain_seasons else None

    # --- Determine mode, label, baselines ---
    if year == "all":
        label = "Biggest All-Time Riser"
        context = "GM Rating positions gained all-time"
        first = min(seasons_with_data) if seasons_with_data else None
        baseline = season_ratings.get(str(first), {}) if first else {}
        compare = current_ratings

    elif isinstance(year, int) and year == current_season and is_in_season:
        label = "Biggest Weekly Rise"
        context = "GM Rating positions gained"
        baseline = prev_ratings
        compare = current_ratings

    elif isinstance(year, int) and year == current_season and not is_in_season:
        label = "Biggest Off-Season Riser"
        context = "GM Rating positions gained since last season"
        prev_season = max((s for s in seasons_with_data if s < year), default=None)
        baseline = season_ratings.get(str(prev_season), {}) if prev_season else {}
        compare = current_ratings

    else:  # past completed year
        label = "Biggest Year Riser"
        context = f"GM Rating positions gained in {year}"
        prev_year = max((s for s in seasons_with_data if s < year), default=None)
        baseline = season_ratings.get(str(prev_year), {}) if prev_year else {}
        compare = season_ratings.get(str(year), {})

    # --- Compute trends and find biggest riser ---
    if not baseline or not compare:
        return HeroStat(value="—", context=context, label=label)

    baseline_rank = {
        uid: i + 1
        for i, (uid, _) in enumerate(
            sorted(baseline.items(), key=lambda kv: kv[1], reverse=True)
        )
    }
    current_rank = {
        uid: i + 1
        for i, (uid, _) in enumerate(
            sorted(compare.items(), key=lambda kv: kv[1], reverse=True)
        )
    }
    last_baseline_rank = len(baseline_rank)
    trends = {
        uid: (baseline_rank.get(uid, last_baseline_rank + 1) - current_rank[uid])
        for uid in compare
    }
    if not trends:
        return HeroStat(value="—", context=context, label=label)

    rise_uid = max(trends, key=lambda u: trends[u])
    rise = trends[rise_uid]
    if rise > 0:
        return HeroStat(
            value=f"▲{rise}",
            context=context,
            label=label,
            owner=owner_name(entry, rise_uid),
            owner_user_id=rise_uid,
        )
    return HeroStat(value="—", context=context, label=label)


def _all_time_ratings(entry: ChainCacheEntry) -> dict[str, int]:
    """All-time {uid: rating} — delegates to the single live builder."""
    from app.services.franchise_redesign import live_ratings
    return {uid: r["rating"] for uid, r in live_ratings(entry).items()}


def _asset_label(a: dict[str, Any]) -> str:
    """Human label for one traded asset (player, draft pick, or FAAB).

    Draft picks carry no ``name``/``player_id``; without this they rendered as a
    bare "?". Prefer the drafted player's name when a flipped pick has resolved,
    else the pick slot ("2026 3rd").
    """
    if a.get("name"):
        return a["name"]
    if a.get("season") is not None and a.get("round") is not None:
        rnd = a["round"]
        ordinal = {1: "1st", 2: "2nd", 3: "3rd"}.get(rnd, f"{rnd}th")
        return a.get("drafted_player_name") or f"{a['season']} {ordinal}"
    if a.get("amount") is not None:
        return f"${a['amount']} FAAB"
    return a.get("player_id") or "?"


def _format_assets_short(side: dict[str, Any]) -> str:
    bits = [_asset_label(a) for a in side.get("received", [])]
    return "; ".join(bits[:3]) or "—"


def _intel_hero_stats(
    entry: ChainCacheEntry,
    ratings: dict[str, int],
    year: Year = "all",
    is_in_season: bool = False,
    prev_ratings: dict[str, int] | None = None,
) -> HeroStats:
    """Four intelligence-focused KPI cards: Top GM, Biggest Riser, Best Roster, Draft Ace."""
    outlook = entry.outlook_signals or {}

    # Top GM — use year-scoped ratings when viewing a specific past season,
    # all-time ratings otherwise (all years / current season).
    _sr = entry.season_ratings or {}
    top_gm_ratings = (
        _sr.get(str(year)) if isinstance(year, int) and str(year) in _sr else ratings
    )
    top_gm_context = f"GM Rating · {year}" if isinstance(year, int) and str(year) in _sr else "GM Rating"
    if top_gm_ratings:
        top_uid = max(top_gm_ratings, key=lambda u: top_gm_ratings[u])
        top_gm = HeroStat(
            value=f"{top_gm_ratings[top_uid]:,}",
            context=top_gm_context,
            owner=owner_name(entry, top_uid),
            owner_user_id=top_uid,
        )
    else:
        top_gm = HeroStat(value="—", context=top_gm_context)

    # Biggest Riser (context-aware) -----------------------------------------
    biggest_weekly_rise = _rise_hero_stat(
        entry, ratings, year, is_in_season, prev_ratings or {}
    )

    # Best Roster ------------------------------------------------------------
    roster_vals = {uid: float(outlook.get(uid, {}).get("roster_value") or 0) for uid in entry.owners}
    if any(v > 0 for v in roster_vals.values()):
        roster_uid = max(roster_vals, key=lambda u: roster_vals[u])
        best_roster = HeroStat(
            value=f"{int(roster_vals[roster_uid]):,}",
            context="KTC roster value · today",
            owner=owner_name(entry, roster_uid),
            owner_user_id=roster_uid,
        )
    else:
        best_roster = HeroStat(value="—", context="KTC roster value · today")

    # Draft Ace — year-scoped when viewing a specific year, all-time otherwise -
    if year != "all" and isinstance(year, int):
        year_skill = (entry.draft_skill_by_season or {}).get(str(year), {})
        skill_vals = {uid: float(year_skill.get(uid) or 0) for uid in entry.owners if uid in year_skill}
        ace_context = f"draft skill score · {year} class"
    else:
        skill_vals = {uid: float(outlook.get(uid, {}).get("draft_skill") or 0) for uid in entry.owners}
        ace_context = "draft skill score · all-time"
    if any(v > 0 for v in skill_vals.values()):
        ace_uid = max(skill_vals, key=lambda u: skill_vals[u])
        draft_ace = HeroStat(
            value=f"+{skill_vals[ace_uid]:.2f}",
            context=ace_context,
            owner=owner_name(entry, ace_uid),
            owner_user_id=ace_uid,
        )
    else:
        draft_ace = HeroStat(value="—", context=ace_context)

    return HeroStats(
        top_gm=top_gm,
        biggest_weekly_rise=biggest_weekly_rise,
        best_roster=best_roster,
        draft_ace=draft_ace,
    )


def build_trades_list(
    entry: ChainCacheEntry, *, year: Year = "all", lens: Lens = "ktc"
) -> list[LatestTrade]:
    """All trades in the window, newest first (uncapped). Powers the Trades tab,
    where the dashboard's short ``latest_trades`` teaser isn't enough. ``lens`` is
    accepted for API parity; each row already carries both KTC and production
    swings, so it doesn't change the payload."""
    trades = _filter_trades_by_year(entry, year)
    return _latest_trades(entry, trades, n=len(trades))


def _strict_winner(by_uid: dict[str, Any]) -> str | None:
    """The uid holding the top value, but only when it holds it *alone*.

    Two guards, both about not claiming a result the numbers don't support:

    * Fewer than two graded sides — a lone graded uid (partial or corrupted
      grading) has no opponent to have "won" against.
    * A tie at the top — plain ``max`` would hand the win to whichever uid the
      dict happened to list first. On production that fires constantly: before
      week 1 of a season *every* trade has both sides at 0.0, and the lead
      would name a field winner three lines above a POINTS cell reading "—".
      On the zero-sum value swing a tie means 0.0-0.0, which is a wash.
    """
    if len(by_uid) < 2:
        return None
    top, runner_up = sorted(by_uid, key=lambda uid: by_uid[uid], reverse=True)[:2]
    return None if by_uid[top] == by_uid[runner_up] else top


def _latest_trades(
    entry: ChainCacheEntry, trades: list[dict[str, Any]], n: int = 5
) -> list[LatestTrade]:
    sorted_trades = sorted(
        trades, key=lambda rt: rt["trade"]["traded_at"], reverse=True
    )[:n]
    out: list[LatestTrade] = []
    for rt in sorted_trades:
        g = _grade_for(entry, rt["trade"]["transaction_id"])
        prod_swings = g.get("production_total") or {}
        parties = [
            owner_ref(entry, uid) for uid in (rt["sides"] or {}).keys()
        ][:3]
        bits: list[str] = []
        for side in (rt["sides"] or {}).values():
            received = (side or {}).get("received") or []
            if received:
                bits.append(_asset_label(received[0]))
        assets_short = " ↔ ".join(bits[:2]) if bits else "—"
        ktc_swings_by_uid = g.get("snapshot_value_swing") or {}
        ktc_swing_vals = list(ktc_swings_by_uid.values())
        prod_vals = list(prod_swings.values())

        # The lead's verdict. A strict argmax over the zero-sum value swing and
        # over the received-only production tally — the two can legitimately
        # disagree (36% of trades in a real league), which is the story worth
        # telling. Both require at least two graded sides and a strict lead;
        # see `_strict_winner`.
        value_winner_uid = _strict_winner(ktc_swings_by_uid)
        prod_winner_uid = _strict_winner(prod_swings)

        # Ordering anchor for the split — the value *leader*, strict or not. A
        # tied value swing has no winner, but the pair of production totals is
        # still a fact, so a wash leaves the ordering to the plain argmax
        # rather than suppressing the split.
        anchor_uid = (
            max(ktc_swings_by_uid, key=ktc_swings_by_uid.get)
            if len(ktc_swings_by_uid) >= 2 else None
        )
        production_split = None
        # Guard: the value swing and production dicts are normally keyed off
        # the same graded sides, but if they ever disagree (anchor_uid not
        # present in prod_swings), fall back to no split rather than let a
        # KeyError from prod_swings[anchor_uid] surface as an unhandled 500 in
        # a dashboard aggregation.
        if (
            anchor_uid is not None
            and len(prod_swings) == 2
            and anchor_uid in prod_swings
        ):
            other_uid = next(u for u in prod_swings if u != anchor_uid)
            production_split = (
                float(prod_swings[anchor_uid]),
                float(prod_swings[other_uid]),
            )

        out.append(LatestTrade(
            trade_id=rt["trade"]["transaction_id"],
            date=rt["trade"]["traded_at"][:10],
            week=rt["trade"]["week"], parties=parties,
            assets_short=assets_short,
            swing_ktc=float(max(ktc_swing_vals)) if ktc_swing_vals else 0.0,
            swing_prod=float(max(prod_vals) - min(prod_vals)) if len(prod_vals) >= 2 else 0.0,
            value_winner=owner_ref(entry, value_winner_uid) if value_winner_uid else None,
            production_winner=owner_ref(entry, prod_winner_uid) if prod_winner_uid else None,
            production_split=production_split,
        ))
    return out


def _headline_trades(
    entry: ChainCacheEntry, trades: list[dict[str, Any]], n: int = 3
) -> list[LatestTrade]:
    """The window's most consequential trades, ranked by Trade Value swing.

    Unlike ``_latest_trades`` (newest-first), this surfaces the biggest moves so
    the dashboard hero stays meaningful even in a quiet offseason. Reuses the
    LatestTrade builder, then sorts by swing magnitude."""
    built = _latest_trades(entry, trades, n=len(trades))
    return sorted(built, key=lambda t: abs(t.swing_ktc), reverse=True)[:n]


def _bracket_watch(
    entry: ChainCacheEntry, phase: str, rows: list[StandingRow]
) -> "BracketWatch | None":
    """Live title-path state for the postseason lead.

    The bracket half comes off the persisted blob; the playoff-points leader
    is read from the standings rows already built for this response, so the
    lead can never disagree with the table underneath it.
    """
    raw = getattr(entry, "bracket_watch", None) or {}
    if phase != "post" or not isinstance(raw, dict) or not raw:
        return None
    alive_ids = [str(u) for u in (raw.get("alive") or [])]
    if not alive_ids:
        return None

    leader = max(
        (r for r in rows if (r.production_playoff or 0) > 0),
        key=lambda r: r.production_playoff,
        default=None,
    )
    top_uid = raw.get("top_seed_user_id")
    try:
        return BracketWatch(
            season=int(raw.get("season") or 0),
            entered=int(raw.get("entered") or 0),
            alive_count=int(raw.get("alive_count") or len(alive_ids)),
            alive=[owner_ref(entry, uid) for uid in alive_ids],
            top_seed_owner=owner_ref(entry, str(top_uid)) if top_uid else None,
            top_seed=raw.get("top_seed"),
            playoff_points_leader=owner_ref(entry, leader.user_id) if leader else None,
            playoff_points=round(leader.production_playoff, 1) if leader else None,
        )
    except Exception:
        log.exception("bracket watch skipped for league %s", entry.league_id)
        return None


def _draft_review(entry: ChainCacheEntry, phase: str) -> "DraftReview | None":
    """Results (and, once played, grades) for the last draft, for the
    draft-window lead.

    Only built during the draft window — the lead is the sole consumer, and
    computing it year-round would put a rankings pass on every dashboard
    response for a block nothing renders. Returns None on a pre-feature cache
    or an unreviewable class (no picks, or fewer than two); the lead falls
    back rather than half-printing. An unplayed class still comes back with
    `graded=False` and null best/worst — the results are real the moment the
    draft completes, only the grade waits on played games.
    """
    if phase != "draft":
        return None
    from sleeper_dynasty.engine.draft_results import build_draft_review

    raw = build_draft_review(list(getattr(entry, "drafted_picks", None) or []))
    if not raw:
        return None

    def _pick(d: dict) -> DraftReviewPick:
        uid = str(d.get("drafter_id") or "")
        return DraftReviewPick(
            player_id=str(d.get("player_id") or ""),
            full_name=str(d.get("full_name") or ""),
            position=str(d.get("position") or ""),
            drafter_id=uid,
            owner=owner_ref(entry, uid) if uid else None,
            round=int(d.get("round") or 0),
            slot=int(d.get("slot") or 0),
            draft_position=int(d.get("draft_position") or 0),
            production_total=(
                float(d["production_total"]) if d.get("production_total") is not None else None
            ),
            slot_delta=int(d["slot_delta"]) if d.get("slot_delta") is not None else None,
            baseline_delta=(
                float(d["baseline_delta"]) if d.get("baseline_delta") is not None else None
            ),
            baseline_source=str(d.get("baseline_source") or ""),
        )

    try:
        graded = bool(raw.get("graded", True))
        return DraftReview(
            season=int(raw["season"]),
            graded=graded,
            best=_pick(raw["best"]) if graded and raw.get("best") else None,
            worst=_pick(raw["worst"]) if graded and raw.get("worst") else None,
            beat_slot=int(raw["beat_slot"]),
            total=int(raw["total"]),
            best_value=_pick(raw["best_value"]) if raw.get("best_value") else None,
            reach=_pick(raw["reach"]) if raw.get("reach") else None,
            matched=int(raw.get("matched") or 0),
        )
    except Exception:
        log.exception("draft review skipped for league %s", entry.league_id)
        return None


def _week_recap(entry: ChainCacheEntry, phase: str) -> WeekRecap | None:
    """Validate the persisted recap blob and attach owner refs.

    Returns None on a pre-feature cache, outside the regular season, or on any
    blob that doesn't carry a complete high score and blowout — the lead prints
    its placeholder rather than a partial recap.
    """
    raw = getattr(entry, "week_recap", None) or {}
    if phase != "regular" or not isinstance(raw, dict) or not raw:
        return None
    high, blow = raw.get("high_score") or {}, raw.get("blowout") or {}
    if not high.get("user_id") or not blow.get("winner_user_id"):
        return None

    def _figure(d: dict | None) -> WeekRecapFigure | None:
        if not isinstance(d, dict) or not d.get("user_id"):
            return None
        uid = str(d["user_id"])
        return WeekRecapFigure(
            user_id=uid, owner=owner_ref(entry, uid), points=float(d.get("points") or 0.0),
        )

    top = _figure(high)
    if top is None:
        return None
    try:
        return WeekRecap(
            season=str(raw.get("season") or ""),
            week=int(raw.get("week") or 0),
            high_score=top,
            blowout=WeekRecapBlowout(
                winner_user_id=str(blow["winner_user_id"]),
                winner=owner_ref(entry, str(blow["winner_user_id"])),
                loser_user_id=str(blow.get("loser_user_id") or ""),
                loser=(
                    owner_ref(entry, str(blow["loser_user_id"]))
                    if blow.get("loser_user_id") else None
                ),
                margin=float(blow.get("margin") or 0.0),
            ),
            traded_points=_figure(raw.get("traded_points")),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _records(
    entry: ChainCacheEntry, owner_rows: dict[str, dict[str, Any]]
) -> Records:
    if not owner_rows:
        return Records(
            biggest_value_swing=0, biggest_production=0,
            biggest_playoff=0, most_trades=0,
        )
    top_v = max(owner_rows.values(), key=lambda r: r["net_ktc"])
    top_p = max(owner_rows.values(), key=lambda r: r["production_total"])
    top_pl = max(owner_rows.values(), key=lambda r: r["production_playoff"])
    top_t = max(owner_rows.values(), key=lambda r: r["trades"])
    return Records(
        biggest_value_swing=top_v["net_ktc"],
        biggest_value_swing_owner=owner_name(entry, top_v["user_id"]),
        biggest_value_swing_owner_user_id=top_v["user_id"],
        biggest_production=top_p["production_total"],
        biggest_production_owner=owner_name(entry, top_p["user_id"]),
        biggest_production_owner_user_id=top_p["user_id"],
        biggest_playoff=top_pl["production_playoff"],
        biggest_playoff_owner=owner_name(entry, top_pl["user_id"]),
        biggest_playoff_owner_user_id=top_pl["user_id"],
        most_trades=top_t["trades"],
        most_trades_owner=owner_name(entry, top_t["user_id"]),
        most_trades_owner_user_id=top_t["user_id"],
    )


def build_dashboard(
    entry: ChainCacheEntry,
    year: Year,
    lens: Literal["ktc", "production"],
    prev_ratings: dict[str, int] | None = None,
    is_in_season: bool = False,
) -> DashboardResp:
    """Produce a DashboardResp from a cached chain entry + query params."""
    trades = _filter_trades_by_year(entry, year)
    rows = _aggregate_owner_rows(entry, trades)

    # All-time GM ratings (independent of year filter)
    ratings = _all_time_ratings(entry)  # {uid: int}
    # This league's own stage band unit, derived ONCE from the one helper the
    # owner page and the LLM packet also call — never re-derived here.
    from app.services.franchise_redesign import league_stage_sd
    stage_sd = league_stage_sd(ratings)
    gm_rank_by_uid: dict[str, int] = {
        uid: i + 1
        for i, (uid, _) in enumerate(
            sorted(ratings.items(), key=lambda kv: kv[1], reverse=True)
        )
    }
    gm_trend_by_uid = _compute_gm_trends(ratings, prev_ratings or {})

    # Standings: primary sort by GM rating, tiebreak by net_ktc. An unrated
    # owner (no completed season — franchise_redesign.rated_owners) is absent
    # from `ratings` and sorts to the bottom on the 0 default; ratings are
    # clamped to 800-2200, so the default can never interleave him with a
    # graded franchise. His row still renders, with `gm_letter`/`gm_rating`
    # None below.
    sorted_rows = sorted(
        rows.values(),
        key=lambda r: (ratings.get(r["user_id"], 0), r["net_ktc"]),
        reverse=True,
    )
    grade_by_uid = _letter_grade({r["user_id"]: r["net_ktc"] for r in sorted_rows})

    # Redraft drops the Assets pillar (franchise_redesign.model_for) and the
    # owner page's Outlook tab (owner_view). The standings' outlook-derived
    # columns — Window, Draft cap — are the same surface and go with them:
    # their tooltip sends the reader to an Outlook tab that no longer exists,
    # and a redraft rating is Results-only, so a stage derived from it would
    # describe a competitive window the league does not have. Left unpopulated
    # (None) rather than zeroed, so the frontend can omit the columns
    # entirely — absence, not a blank column.
    #
    # `entry.dynasty_outlooks` no longer supplies the window STRING — that is
    # derived from the rating below — but it is still read as the per-owner
    # GATE. See `_has_outlook` at the `window=` kwarg.
    _outlooks_apply = (
        capabilities_from_dict(entry.capabilities).format != "redraft")
    # Which owners actually hold a current roster. `ratings` covers every owner
    # with a completed season, including departed ones; refresh writes a
    # `dynasty_outlooks` blob only for owners still holding a roster, and
    # `owner_view` gates its whole Outlook block on exactly this truthiness.
    # Sharing the condition is what makes the two surfaces agree by
    # construction rather than by coincidence.
    _has_outlook = entry.dynasty_outlooks or {}
    outlook_signals = (entry.outlook_signals or {}) if _outlooks_apply else {}
    season_recs = entry.season_records or {}
    # roster_ranks is already computed and persisted at refresh (never
    # recomputed here) - same redraft gate as the outlook columns above,
    # since a redraft league carries no roster to rank between seasons.
    roster_ranks = (entry.roster_ranks or {}) if _outlooks_apply else {}

    standings = []
    for i, r in enumerate(sorted_rows):
        uid = r["user_id"]
        _record, _finish, _playoff = _fmt_record(uid, year, season_recs)
        # Numeric sort helpers: wins (descending = more wins first) and rank (ascending = better)
        if year == "all":
            _wins: int | None = sum(
                (season_recs.get(yr) or {}).get(uid, {}).get("wins", 0)
                for yr in season_recs
            ) or None
            _rank: int | None = None  # no single rank for all-time
        else:
            _yr = (season_recs.get(str(year)) or {}).get(uid) or {}
            _wins = _yr.get("wins") if _yr else None
            _rank = _yr.get("rank") if _yr else None
        standings.append(StandingRow(
            rank=i + 1,
            user_id=uid,
            owner=owner_ref(entry, uid),
            net_ktc=r["net_ktc"],
            production_total=r["production_total"],
            production_regular=r["production_regular"],
            production_started=r["production_started"],
            production_playoff=r["production_playoff"],
            production_toilet=r["production_toilet"],
            trades=r["trades"],
            grade=grade_by_uid.get(uid, "B"),
            net_ktc_at_trade=r["net_ktc_at_trade"],
            net_ktc_aged=r["net_ktc_today_subset"] - r["net_ktc_at_trade"],
            gm_rating=ratings.get(uid),
            gm_letter=rating_to_letter(ratings[uid]) if uid in ratings else None,
            gm_rank=gm_rank_by_uid.get(uid),
            gm_trend=gm_trend_by_uid.get(uid, 0),
            roster_rank=(roster_ranks.get(uid) or {}).get("rank"),
            roster_of=(roster_ranks.get(uid) or {}).get("of"),
            # Derived from the SAME live_ratings builder the owner page reads,
            # so the stage on /owner/{uid} and the Window here are one string,
            # not two arithmetics that can disagree.
            #
            # TWO gates, both required and neither sufficient.
            #
            # `_outlooks_apply` is the league-level redraft gate: `ratings` is
            # not redraft-gated (:725) though every Outlook-derived column is,
            # so without it every redraft row gets a non-null window, flips
            # StandingsTable's hasOutlookColumns true, and labels redraft
            # franchises "Dynasty".
            #
            # `_has_outlook.get(uid)` is the per-OWNER gate, and it is the same
            # object `owner_view` gates its Outlook block on. A departed owner
            # is still rated (his seasons are in the books) but holds no
            # current roster, so he has no outlook blob and /owner/{uid}
            # renders no stage; deriving one from his rating here would print
            # "Retooling" beside a page that shows nothing. A stage is a claim
            # about a roster's competitive window — no roster, no claim.
            window=(
                rating_to_stage(ratings[uid], sd=stage_sd)
                if _outlooks_apply and uid in ratings
                and _has_outlook.get(uid) else None
            ),
            draft_capital_value=(
                float((outlook_signals.get(uid) or {}).get("draft_capital") or 0)
                if _outlooks_apply else None
            ),
            season_record=_record,
            best_finish=_finish,
            playoff_record=_playoff,
            season_wins=_wins,
            season_rank=_rank,
        ))

    seasons = sorted({lg["season"] for lg in entry.chain})
    # League-calendar phase stamped at refresh; pre-feature caches fall back
    # to offseason (self-corrects on the next refresh).
    lp = getattr(entry, "league_phase", None) or {}
    phase = lp.get("phase")
    if phase not in ("regular", "post", "draft", "offseason"):
        phase = "offseason"
    phase_season = int(lp.get("season") or (max(seasons) if seasons else 0))
    phase_week = lp.get("week")
    if not isinstance(phase_week, int):
        phase_week = None
    # Week recap (A2): persisted verbatim at refresh; owner refs are attached
    # here so names honor the same overrides every other row does. A pre-feature
    # cache (or any non-regular phase) has {} and the lead keeps its skeleton.
    week_recap = _week_recap(entry, phase)
    draft_review = _draft_review(entry, phase)
    bracket_watch = _bracket_watch(entry, phase, standings)

    league = LeagueSummary(
        league_id=entry.league_id,
        name=next(
            (lg["name"] for lg in entry.chain if lg["league_id"] == entry.league_id),
            entry.league_id,
        ),
        season=max(seasons) if seasons else 0,
        total_rosters=next(
            (lg["total_rosters"] for lg in entry.chain
             if lg["league_id"] == entry.league_id), 0
        ),
        status="active",
        seasons=seasons,
        last_refreshed=entry.cached_at,
    )

    return DashboardResp(
        league=league,
        selected_year=year,
        selected_lens=lens,
        hero_stats=_intel_hero_stats(
            entry, ratings,
            year=year, is_in_season=is_in_season, prev_ratings=prev_ratings,
        ),
        standings=standings,
        latest_trades=_latest_trades(entry, trades),
        headline_trades=_headline_trades(entry, trades),
        records=_records(entry, rows),
        total_trades=len(trades),
        warnings=entry.warnings,
        phase=phase,
        phase_season=phase_season,
        phase_week=phase_week,
        week_recap=week_recap,
        draft_review=draft_review,
        bracket_watch=bracket_watch,
        capabilities=LeagueCapabilitiesResp(
            **capabilities_to_dict(capabilities_from_dict(entry.capabilities))),
    )
