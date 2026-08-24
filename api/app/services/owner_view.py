from __future__ import annotations

from app.models.leaderboard import GMRow
from app.models.owner import (
    AgeProfileView, DraftCapitalView, DraftNeedView,
    DraftPickResult, DraftSkillView, FranchiseRatingView, H2HView,
    OutlookView, OwnerDetailResp, OwnerTradeRow, PlayerLite, ProseSegment,
    RankView, SeasonArc,
)
from app.models.trade import ProductionPoint, ProductionVerdictView, TradeProductionView
from app.services.aggregations import _format_assets_short
from app.services.chain_cache import ChainCacheEntry
from app.services.identity import owner_ref
from app.services.start_rate import start_rate
from app.services.track_record_view import build_track_record
from sleeper_dynasty.engine.gm_rating import rating_to_stage


# The emphasis marks the renderer knows. Kept in sync with
# `sleeper_dynasty.llm.franchise_marks.MARKS` and
# `web/components/furniture/Emphasis.tsx::EMPHASIS_KINDS`.
_MARKS = frozenset({"num", "who", "good", "risk"})


def _prose_segments(raw) -> list[ProseSegment] | None:
    """Cached blurb segments -> the response shape, or None.

    The cache is a JSON blob on disk written by an older build of this code, so
    nothing about its shape is guaranteed. A list that is not a list of
    ``{text, mark}`` degrades to None and the caller falls back to plain prose —
    an owner page must not 500 on a stale blurb.

    An unrecognised mark name is downgraded to plain rather than dropped: the
    words are still the blurb, only the emphasis is unavailable. Filtering it
    here rather than in the component keeps the "unknown mark is prose" rule in
    one place on the server, where the parser's rule already lives.
    """
    if not isinstance(raw, list) or not raw:
        return None
    out: list[ProseSegment] = []
    for seg in raw:
        if not isinstance(seg, dict) or not isinstance(seg.get("text"), str):
            return None
        mark = seg.get("mark")
        out.append(ProseSegment(
            text=seg["text"], mark=mark if mark in _MARKS else None))
    return out


def build_owner_detail(
    entry: ChainCacheEntry, user_id: str,
    *, gm_row: GMRow | None = None, total_owners: int | None = None,
) -> OwnerDetailResp | None:
    if user_id not in entry.owners:
        # No owner with that id ever appeared.
        return None

    net_ktc = 0.0
    net_prod = 0.0
    production_regular = 0.0
    production_playoff = 0.0
    production_toilet = 0.0
    production_started = 0.0
    net_ktc_at_trade = 0.0
    net_ktc_today_subset = 0.0
    by_season: dict[int, dict[str, float]] = {}
    trade_rows: list[OwnerTradeRow] = []
    best_id: str | None = None
    worst_id: str | None = None
    best_swing = float("-inf")
    worst_swing = float("inf")

    for rt in entry.resolved_trades:
        season = rt["trade"]["season"]
        grade = entry.grades.get(rt["trade"]["transaction_id"]) or {}
        # Realized value drives the headline; swing stays for the diagnostic only.
        realized = float((grade.get("received_ktc") or {}).get(user_id, 0) or 0)
        swing = float((grade.get("snapshot_value_swing") or {}).get(user_id, 0) or 0)
        if user_id not in (grade.get("received_ktc") or {}):
            continue
        prod = float((grade.get("production_total") or {}).get(user_id, 0) or 0)
        regular = float((grade.get("production_regular") or {}).get(user_id, 0) or 0)
        playoff = float(
            (grade.get("production_playoff") or {}).get(user_id, 0) or 0
        )
        toilet = float((grade.get("production_toilet") or {}).get(user_id, 0) or 0)
        started = float((grade.get("production_started") or {}).get(user_id, 0) or 0)
        net_ktc += realized
        net_prod += prod
        production_regular += regular
        production_playoff += playoff
        production_toilet += toilet
        production_started += started
        at_map = grade.get("at_trade_value_swing") or {}
        if user_id in at_map:
            net_ktc_at_trade += float(at_map[user_id] or 0)
            net_ktc_today_subset += swing
        row = by_season.setdefault(season, {
            "net_ktc": 0.0, "production_total": 0.0,
            "production_regular": 0.0,
            "production_playoff": 0.0,
            "production_toilet": 0.0,
            "production_started": 0.0,
            "trades": 0,
        })
        row["net_ktc"] += realized
        row["production_total"] += prod
        row["production_regular"] += regular
        row["production_playoff"] += playoff
        row["production_toilet"] += toilet
        row["production_started"] += started
        row["trades"] += 1

        # One receipt row from this owner's perspective.
        sides = rt.get("sides") or {}
        my_side = sides.get(user_id) or {}
        counterparties = [
            owner_ref(entry, u) for u in sides.keys() if u != user_id
        ]
        traded_at = rt["trade"].get("traded_at") or ""
        trade_rows.append(OwnerTradeRow(
            trade_id=rt["trade"]["transaction_id"],
            date=traded_at[:10],
            season=season,
            week=rt["trade"].get("week"),
            counterparties=counterparties,
            assets_short=_format_assets_short(my_side),
            swing_ktc=realized,
            swing_prod=prod,
            swing_regular=regular,
            swing_playoff=playoff,
            swing_toilet=toilet,
            swing_started=started,
            start_pct=start_rate(started, prod),
        ))

        if realized > best_swing:
            best_swing = realized
            best_id = rt["trade"]["transaction_id"]
        if realized < worst_swing:
            worst_swing = realized
            worst_id = rt["trade"]["transaction_id"]

    arc = [
        SeasonArc(season=s, net_ktc=v["net_ktc"],
                  production_total=v["production_total"],
                  production_regular=v["production_regular"],
                  production_playoff=v["production_playoff"],
                  production_toilet=v["production_toilet"],
                  production_started=v["production_started"],
                  trades=int(v["trades"]))
        for s, v in sorted(by_season.items())
    ]
    # Receipts table reads newest-first; empty dates sort last.
    trade_rows.sort(key=lambda r: r.date, reverse=True)

    prod_raw = (getattr(entry, "owner_production_series", None) or {}).get(user_id) or {}
    production_series = {
        side: {
            metric: [ProductionPoint(season=s, week=w, value=v) for s, w, v in pts]
            for metric, pts in by_metric.items()
        }
        for side, by_metric in prod_raw.items()
    }
    prod_verdict_raw = (getattr(entry, "owner_production_verdict", None) or {}).get(user_id) or {}
    production_verdict = {
        m: ProductionVerdictView(label=vd["label"], sentence=vd["sentence"], tone=vd["tone"])
        for m, vd in prod_verdict_raw.items()
    }
    production_week_axis = list(getattr(entry, "production_week_axis", None) or [])
    production_week_phases = list(getattr(entry, "production_week_phases", None) or [])

    # Per-trade production drill: list of TradeProductionView for this owner.
    trades_raw = (getattr(entry, "owner_production_trades", None) or {}).get(user_id) or []
    production_trades = [
        TradeProductionView(
            trade_id=t["trade_id"],
            series={
                m: [ProductionPoint(season=s, week=w, value=v) for s, w, v in pts]
                for m, pts in t["byMetric"].items()
            },
        )
        for t in trades_raw
    ]

    # Redraft has no future picks and no roster carryover, so the Outlook tab
    # has nothing to say. Omitted entirely rather than empty-stated:
    # OwnerDeepDive.tsx:58 renders the tab only when detail.outlook is present,
    # and line 71 already falls back to overview on a stale ?tab=outlook link.
    #
    # Resolved HERE rather than beside the outlook assembly because
    # `is_redraft` also gates `roster_rank_view` and the franchise blurb just
    # below, while the assembly itself now sits under the Franchise Rating
    # block (it reads `gm_row`). Two lines hoisted, one block moved.
    from sleeper_dynasty.engine.capabilities import capabilities_from_dict
    league_format = capabilities_from_dict(entry.capabilities).format
    is_redraft = league_format == "redraft"

    # Same redraft gate aggregations.py and leaderboard.py apply to the
    # standings row and the /gm row: a redraft league carries no roster
    # between seasons, so there is no roster to rank. Ungated here, the hero
    # showed "ROSTER #4 OF 12" while the standings table two clicks away
    # deliberately hid the same figure.
    roster_rank_view: RankView | None = None
    raw_rank = None if is_redraft else (entry.roster_ranks or {}).get(user_id)
    if raw_rank:
        roster_rank_view = RankView(rank=raw_rank["rank"], of=raw_rank["of"])

    # --- Draft-skill rank across all owners with a score. ---
    draft_skill_view: DraftSkillView | None = None
    skills = {
        u: float(sig.get("draft_skill", 0.0) or 0.0)
        for u, sig in (entry.outlook_signals or {}).items()
        if "draft_skill" in sig
    }
    if user_id in skills:
        ordered = sorted(skills, key=lambda u: skills[u], reverse=True)
        draft_skill_view = DraftSkillView(
            score=skills[user_id],
            rank=ordered.index(user_id) + 1, of=len(ordered))

    # The franchise blurb IS the outlook prose ("Writing franchise outlooks",
    # grader.py) — same pillar the tab above was just dropped for. Suppressed
    # for redraft rather than shown next to a page that no longer has an
    # Outlook tab. Absence, not an empty state: the field is None and the
    # component renders nothing.
    _fr_blurb = {} if is_redraft else (
        (entry.franchise_blurbs or {}).get(user_id) or {})
    franchise_blurb = _fr_blurb.get("blurb") or None
    franchise_lead = _fr_blurb.get("lead") or None
    franchise_segments = _prose_segments(_fr_blurb.get("segments"))

    # --- Track record (win/title history) + head-to-head vs each league-mate. ---
    track_record = build_track_record(entry.season_records or {}, user_id)
    h2h_raw = (entry.head_to_head or {}).get(user_id, {})
    head_to_head = sorted(
        (
            H2HView(
                opponent=owner_ref(entry, opp),
                wins=int(rec.get("wins", 0)), losses=int(rec.get("losses", 0)),
                ties=int(rec.get("ties", 0)),
                points_for=float(rec.get("points_for", 0.0)),
                points_against=float(rec.get("points_against", 0.0)),
            )
            for opp, rec in h2h_raw.items()
        ),
        # Most-played rivalries first, then by wins.
        key=lambda v: (v.wins + v.losses + v.ties, v.wins),
        reverse=True,
    )

    # --- Franchise Rating (platform verdict): from the prebuilt leaderboard row. ---
    franchise_rating: FranchiseRatingView | None = None
    if gm_row is not None:
        # All-time per-pillar highlights from the cached GM blurb (LLM), if present.
        rating_blurb = (entry.owner_rating_blurbs or {}).get("all", {}).get(user_id) or {}
        franchise_rating = FranchiseRatingView(
            letter=gm_row.letter, rating=gm_row.rating,
            rank=gm_row.rank, of=total_owners or gm_row.rank, trend=gm_row.trend,
            pillars=gm_row.pillars,
            pillar_highlights=rating_blurb.get("pillars") or {},
        )

    # Why the letter is missing, when it is. Derived from the entry rather than
    # from `gm_row is None` so a swallowed leaderboard failure in the route
    # can't be reported to the reader as "new franchise".
    from app.services.franchise_redesign import (
        league_stage_sd, live_ratings, rated_owners,
    )
    _rated = rated_owners(entry)
    unrated_reason: str | None = None
    if user_id not in _rated:
        unrated_reason = "first_season" if not _rated else "new_franchise"

    # --- Optional outlook block (null on pre-feature caches and for redraft).
    #
    # Assembled AFTER the Franchise Rating block above, because every field it
    # now derives -- `window`, the two z's, `tilt`, `assets_signal_ranks` --
    # comes off `gm_row`, and there is no second window model to fall back on.
    # It sits beside the block that reads the same object so the two cannot
    # drift apart. (`gm_row` is a PARAMETER, so this is grouping, not a
    # dependency: the one real ordering constraint is `is_redraft`, hoisted
    # ~80 lines above, which this block reads to gate redraft out.)
    #
    # `raw_ol["window"]` and `raw_ol["trajectory"]` are NOT read. A pre-feature
    # blob still carries both (no SCHEMA_VERSION bump) and a newly written one
    # carries neither, so a bracket read would KeyError rather than degrade.
    outlook_view: OutlookView | None = None
    raw_ol = None if is_redraft else (entry.dynasty_outlooks or {}).get(user_id)
    if raw_ol:
        ol_sig = (entry.outlook_signals or {}).get(user_id, {})
        ap = raw_ol["age_profile"]
        dc = raw_ol["draft_capital"]
        _results = gm_row.pillars.get("results") if gm_row else None
        _assets = gm_row.pillars.get("assets") if gm_row else None
        # The band unit is this LEAGUE's own rating spread, from the one
        # helper the standings row and the LLM packet also call, so the two
        # screens still read one string. `gm_row` carries a single owner's
        # rating and cannot supply a spread, hence the league-wide read here;
        # it is the same pure arithmetic over persisted signals that produced
        # `gm_row` upstream, and a failure degrades to the fixed reference
        # bands rather than 500ing the page.
        try:
            _stage_sd = league_stage_sd(live_ratings(entry))
        except Exception:
            _stage_sd = None
        outlook_view = OutlookView(
            window=(
                rating_to_stage(gm_row.rating, sd=_stage_sd)
                if gm_row else None
            ),
            results_z=_results.z if _results else None,
            assets_z=_assets.z if _assets else None,
            tilt=(
                round(_assets.z - _results.z, 4)
                if _assets and _results else None
            ),
            assets_signal_ranks=(_assets.signal_ranks if _assets else {}),
            age_profile=AgeProfileView(
                avg_age_by_position=ap["avg_age_by_position"],
                league_avg_age_by_position=ap.get(
                    "league_avg_age_by_position") or {},
                overall_avg_age=ap["overall_avg_age"],
                aging_risks=[PlayerLite(**p) for p in ap["aging_risks"]],
                core_young=[PlayerLite(**p) for p in ap["core_young"]]),
            draft_capital=DraftCapitalView(
                picks_by_season=dc["picks_by_season"],
                picks_by_season_round=dc["picks_by_season_round"],
                net_vs_average=dc["net_vs_average"], status=dc["status"],
                total_value=float(ol_sig.get("draft_capital", 0.0) or 0.0)),
            draft_needs=[DraftNeedView(**n) for n in raw_ol["draft_needs"]])

    # --- Drafted picks grouped per season (Future & Draft tab). ---
    draft_picks_by_season: dict[str, list[DraftPickResult]] = {}
    for p in (entry.drafted_picks or []):
        if p.get("drafter_id") != user_id:
            continue
        season = str(p.get("draft_season"))
        draft_picks_by_season.setdefault(season, []).append(DraftPickResult(
            player_id=p["player_id"], full_name=p["full_name"],
            position=p.get("position", ""), round=p["round"], slot=p["slot"],
            picks_in_round=p["picks_in_round"], draft_season=p["draft_season"],
            acquired_via_trade=bool(p.get("acquired_via_trade")),
            current_value=float(p.get("current_value", 0.0)),
            lowest_value=float(p.get("lowest_value", 0.0)),
            highest_value=float(p.get("highest_value", 0.0)),
            avg_slot_value=float(p.get("avg_slot_value", 0.0)),
            production_total=float(p.get("production_total", 0.0)),
            production_started=float(p.get("production_started") or 0.0),
            production_regular=float(p.get("production_regular", 0.0)),
            production_playoff=float(p.get("production_playoff", 0.0)),
            production_toilet=float(p.get("production_toilet", 0.0)),
            games_started=int(p.get("games_started", 0) or 0),
            roster_status=str(p.get("roster_status", "rostered") or "rostered"),
            is_keeper=bool(p.get("is_keeper")),
            pick_no=int(p.get("pick_no", 0) or 0),
            adp=p.get("adp"),
            adp_delta=p.get("adp_delta"),
            projected_points=p.get("projected_points"),
            verdict=str(p.get("verdict") or ""),
        ))
    # Sort each season's rows by Avg Pick Value delta (best first).
    for rows_ in draft_picks_by_season.values():
        rows_.sort(key=lambda r: r.current_value - r.avg_slot_value, reverse=True)

    return OwnerDetailResp(
        league_id=entry.league_id, user_id=user_id,
        owner=owner_ref(entry, user_id),
        format=league_format,
        totals_by_lens={"ktc": net_ktc, "production": net_prod,
                        "regular": production_regular, "playoff": production_playoff,
                        "toilet": production_toilet,
                        "started": production_started,
                        # Career start rate. Omitted (not 0.0) when nothing has
                        # played — see services/start_rate.py.
                        **({"start_pct": _career_start}
                           if (_career_start := start_rate(production_started, net_prod)) is not None
                           else {}),
                        "ktc_at_trade": net_ktc_at_trade,
                        "ktc_aged": net_ktc_today_subset - net_ktc_at_trade},
        career_arc=arc,
        trades=trade_rows,
        best_trade_id=best_id, worst_trade_id=worst_id,
        outlook=outlook_view,
        roster_rank=roster_rank_view,
        draft_skill=draft_skill_view,
        franchise_blurb=franchise_blurb,
        franchise_lead=franchise_lead,
        franchise_segments=franchise_segments,
        draft_picks_by_season=draft_picks_by_season,
        production_series=production_series,
        production_verdict=production_verdict,
        production_week_axis=production_week_axis,
        production_week_phases=production_week_phases,
        production_trades=production_trades,
        franchise_rating=franchise_rating,
        unrated_reason=unrated_reason,
        track_record=track_record,
        head_to_head=head_to_head,
    )
