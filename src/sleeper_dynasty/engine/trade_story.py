"""FactsBuilder for trade stories.

Every number a story can cite is computed here so the LLM writer never has to
(and can never invent one). Pure functions, unit-testable against fixture data.
"""

from __future__ import annotations

from datetime import datetime

from sleeper_dynasty.models.trade import (
    PickAsset, PlayerAsset, ResolvedTrade,
)
from sleeper_dynasty.models.trade_story import OwnerStrategyFacts, PlayerArc, PickOutcome, TradeStoryFacts
from sleeper_dynasty.engine.trade_grader import _is_post_trade

# Dynasty in-season trading window (deadline ~Week 11). Everything else is
# offseason. Centralized so it can be refined against real data later.
IN_SEASON_MONTHS = {9, 10, 11}

RECENT_DEALS = 4  # window for the "sold a 1st in N of last 4 deals" tendency


def is_offseason(traded_at: datetime) -> bool:
    return traded_at.month not in IN_SEASON_MONTHS


def _counts(side_received, side_given):
    players_recv = sum(isinstance(a, PlayerAsset) for a in side_received)
    picks_recv = sum(isinstance(a, PickAsset) for a in side_received)
    players_given = sum(isinstance(a, PlayerAsset) for a in side_given)
    picks_given = sum(isinstance(a, PickAsset) for a in side_given)
    return players_recv, picks_recv, players_given, picks_given


def _trade_tilt(received, given) -> str:
    """Classify a SINGLE trade's direction for one side.

    Mirrors the career-tilt signals in build_owner_strategy, but for this one
    deal: received player(s) + sent pick(s) is win-now; received pick(s) + sent
    player(s) is rebuild; anything else (player-for-player, pick-for-pick, or a
    move that is both) is balanced. This is the deterministic per-trade fact the
    story writer must use instead of inferring direction from the owner's
    *career* tilt phrasing (which describes the pattern, not this deal).
    """
    p_recv, k_recv, p_given, k_given = _counts(received, given)
    win_now = p_recv >= 1 and k_given >= 1
    rebuild = k_recv >= 1 and p_given >= 1
    if win_now and not rebuild:
        return "win-now"
    if rebuild and not win_now:
        return "rebuild"
    return "balanced"


def _fits_career_tilt(trade_tilt: str, career_tilt: str | None) -> str:
    """Whether THIS trade fits or breaks the owner's established pattern.

    "fits" / "breaks" when both this trade and the career pattern have a clear
    directional lean and they agree / disagree; "n/a" when there is nothing to
    compare (no established career pattern, a balanced career, or a balanced
    trade). Precomputing this removes the single inference the story writer
    keeps getting backwards when a trade opposes the owner's tilt.
    """
    if not career_tilt or career_tilt == "balanced" or trade_tilt == "balanced":
        return "n/a"
    return "fits" if trade_tilt == career_tilt else "breaks"


def build_owner_strategy(
    resolved: list[ResolvedTrade],
    grades: dict[str, dict],
    owners_display: dict[str, str],
    as_of: datetime | None = None,
) -> dict[str, OwnerStrategyFacts]:
    """Aggregate each owner's trading tendencies across the chain.

    When ``as_of`` is given, only trades made strictly BEFORE that moment are
    counted, so a per-trade story describes the pattern an owner had
    established *up to* that deal (not a career label that bakes in trades made
    later). With no cutoff (the default) it aggregates the whole chain, which
    is what the owner *career* dossiers want.
    """
    acc: dict[str, dict] = {}
    # Newest-first per owner, for the "last N deals" tendency.
    by_owner_deals: dict[str, list[tuple[datetime, int]]] = {}

    for rt in resolved:
        if as_of is not None and rt.trade.traded_at >= as_of:
            continue
        for uid, side in rt.sides.items():
            p_recv, k_recv, p_given, k_given = _counts(side.received, side.given)
            a = acc.setdefault(uid, {
                "trades_count": 0, "net_picks": 0,
                "players_for_picks_count": 0, "picks_for_players_count": 0,
                "first_round_picks_sent": 0, "net_ktc": 0.0,
            })
            a["trades_count"] += 1
            a["net_picks"] += k_recv - k_given
            if p_recv >= 1 and k_given >= 1:
                a["players_for_picks_count"] += 1
            if k_recv >= 1 and p_given >= 1:
                a["picks_for_players_count"] += 1
            firsts_sent = sum(
                isinstance(x, PickAsset) and x.round == 1 for x in side.given
            )
            a["first_round_picks_sent"] += firsts_sent
            g = grades.get(rt.trade.transaction_id) or {}
            a["net_ktc"] += float(
                (g.get("snapshot_value_swing") or {}).get(uid, 0.0) or 0.0
            )
            by_owner_deals.setdefault(uid, []).append(
                (rt.trade.traded_at, firsts_sent)
            )

    out: dict[str, OwnerStrategyFacts] = {}
    for uid, a in acc.items():
        if a["players_for_picks_count"] > a["picks_for_players_count"]:
            tilt = "win-now"
        elif a["picks_for_players_count"] > a["players_for_picks_count"]:
            tilt = "rebuild"
        else:
            tilt = "balanced"

        tendencies: list[str] = []
        if tilt == "win-now":
            tendencies.append("buys win-now help with picks")
        elif tilt == "rebuild":
            tendencies.append("trades present help for future picks")
        recent = sorted(by_owner_deals.get(uid, []), reverse=True)[:RECENT_DEALS]
        firsts_recent = sum(1 for _, f in recent if f > 0)
        if firsts_recent >= 3:
            tendencies.append(
                f"sold a 1st in {firsts_recent} of last {len(recent)} deals"
            )

        out[uid] = OwnerStrategyFacts(
            user_id=uid, owner_name=owners_display.get(uid, uid),
            trades_count=a["trades_count"], net_picks=a["net_picks"],
            players_for_picks_count=a["players_for_picks_count"],
            picks_for_players_count=a["picks_for_players_count"],
            first_round_picks_sent=a["first_round_picks_sent"],
            tilt=tilt, net_ktc=a["net_ktc"], tendencies=tendencies,
        )
    return out


def build_player_arc(
    pid: str,
    player_name: str,
    position: str | None,
    owner_uid: str,
    rt: ResolvedTrade,
    matchups: dict[tuple[str, int, int], dict],
    roster_to_user_by_league: dict[str, dict[int, str]],
    playoff_weeks_by_league: dict[str, int],
    league_season_by_id: dict[str, int] | None = None,
    current_holders: dict[str, str] | None = None,
) -> PlayerArc:
    league_season_by_id = league_season_by_id or {}
    last_rostered_week: int | None = None
    starter_weeks = benched_weeks = decisive_starts = 0
    points_total = 0.0
    season_high_points: float | None = None
    season_high_week: int | None = None
    season_high_is_playoff = False
    reg_pts: list[float] = []
    pf_pts: list[float] = []

    phantom_points = 0.0
    for (lg, wk, rid), entry in matchups.items():
        if not _is_post_trade(lg, wk, rt, league_season_by_id):
            continue
        if pid not in (entry.get("players") or []):
            continue
        is_starter = pid in (entry.get("starters") or [])
        pts = float((entry.get("players_points") or {}).get(pid, 0.0) or 0.0)
        if is_starter:
            phantom_points += pts  # started points on ANY roster post-trade
        if roster_to_user_by_league.get(lg, {}).get(rid) != owner_uid:
            continue
        last_rostered_week = (
            wk if last_rostered_week is None else max(last_rostered_week, wk)
        )
        if not is_starter:
            benched_weeks += 1
            continue
        starter_weeks += 1
        points_total += pts
        is_playoff = wk >= playoff_weeks_by_league.get(lg, 15)
        (pf_pts if is_playoff else reg_pts).append(pts)
        team_pts = float(entry.get("team_points") or 0.0)
        opp_pts = float(entry.get("opponent_points") or 0.0)
        if team_pts > opp_pts and pts > (team_pts - opp_pts):
            decisive_starts += 1
        if season_high_points is None or pts > season_high_points:
            season_high_points, season_high_week = pts, wk
            season_high_is_playoff = is_playoff

    pct: float | None = None
    if reg_pts and pf_pts:
        reg_avg = sum(reg_pts) / len(reg_pts)
        if reg_avg > 0:
            pct = (sum(pf_pts) / len(pf_pts) / reg_avg - 1.0) * 100.0

    # Received this player but never rostered him while he played elsewhere:
    # the owner flipped him before he suited up. His 0s are not a knock on him.
    flipped = starter_weeks == 0 and benched_weeks == 0 and phantom_points > 1e-6
    held = (current_holders or {}).get(pid) == owner_uid
    dropped = (not flipped) and (not held)
    return PlayerArc(
        player=player_name, position=position, received_by=owner_uid,
        starter_weeks=starter_weeks, points_total=points_total,
        season_high_points=season_high_points, season_high_week=season_high_week,
        season_high_is_playoff=season_high_is_playoff,
        playoff_vs_regular_pct=pct, decisive_starts=decisive_starts,
        benched_weeks=benched_weeks, phantom_points=phantom_points, flipped=flipped,
        dropped=dropped, last_rostered_week=last_rostered_week,
    )


BLOWOUT_KTC = 2500.0


def _terminal_player_names(node) -> list[str]:
    """The terminal PLAYER names beneath a lineage node (the players the flip
    chain ultimately landed). Undrafted terminal picks contribute no name."""
    if node is None:
        return []
    if not node.children:
        if node.terminal_player_id:
            return [node.became_player or node.label]
        return []
    out: list[str] = []
    for c in node.children:
        out.extend(_terminal_player_names(c))
    return out


def _pick_outcome(asset, *, flipped_as_pick: bool = False,
                  flipped_for: str | None = None) -> PickOutcome | None:
    if isinstance(asset, PlayerAsset) and asset.via_pick is not None:
        return PickOutcome(season=asset.via_pick.season,
                           round=asset.via_pick.round,
                           became_player=asset.name, points_per_game=None)
    if isinstance(asset, PickAsset):
        # A pick flipped *as a pick* before the draft never became its slot's
        # draftee for this owner (they realized the flip package instead), so
        # don't feed the writer a misleading "became <draftee>" fact — report
        # what the flip ultimately landed instead.
        return PickOutcome(
            season=asset.season, round=asset.round,
            became_player=(None if flipped_as_pick else asset.drafted_player_name),
            points_per_game=None,
            flipped_for=(flipped_for if flipped_as_pick else None))
    return None


def _asset_summary(assets: list, positions: dict[str, str]) -> str:
    """Human-readable list of assets on one side of a trade.

    Players: "Name (POS)" or "Name". Picks (including via_pick players): "YYYY Nth pick".
    FaabAssets are skipped. Multiple items joined with " · ". Used for both the
    given and received summaries so the writer has a symmetric, unambiguous anchor
    for each direction.
    """
    def _ordinal(n: int) -> str:
        return {1: "1st", 2: "2nd", 3: "3rd"}.get(n, f"{n}th")

    parts: list[str] = []
    for a in assets:
        if isinstance(a, PlayerAsset):
            if a.via_pick is not None:
                parts.append(
                    f"{a.via_pick.season} {_ordinal(a.via_pick.round)} pick")
            else:
                pos = positions.get(a.player_id)
                parts.append(f"{a.name} ({pos})" if pos else a.name)
        elif isinstance(a, PickAsset):
            parts.append(f"{a.season} {_ordinal(a.round)} pick")
        # FaabAsset: skip
    return " · ".join(parts)


def build_trade_story_facts(
    rt: ResolvedTrade,
    grade: dict,
    owner_strategy: dict[str, OwnerStrategyFacts],
    owners_display: dict[str, str],
    matchups: dict[tuple[str, int, int], dict],
    roster_to_user_by_league: dict[str, dict[int, str]],
    playoff_weeks_by_league: dict[str, int],
    league_season_by_id: dict[str, int] | None = None,
    positions: dict[str, str] | None = None,
    resolved_trades: list[dict] | None = None,
    current_holders: dict[str, str] | None = None,
) -> TradeStoryFacts:
    positions = positions or {}
    current_holders = current_holders or {}
    # Winner + Trade Value margin come from REALIZED received value (held -> today,
    # flipped -> flip date, dropped -> 0) — the same number the receipts, owner
    # views, and leaderboards use (grade["received_ktc"]). snapshot_value_swing is
    # only a mark-to-market diagnostic: it credits a drafted-then-dropped pick at
    # the player's full market value, so it must NOT drive the verdict (it would
    # contradict the receipts, which already zero a dropped haul). Fall back to the
    # swing only when realized value is unavailable (e.g. the CLI path, no store).
    received = grade.get("received_ktc") or {}
    if received:
        winner = max(received, key=lambda u: received.get(u, 0.0))
        runner_up = max(
            (v for u, v in received.items() if u != winner), default=0.0)
        win_margin = float(received.get(winner, 0.0)) - float(runner_up)
    else:
        swings = grade.get("snapshot_value_swing") or {}
        winner = max(swings, key=lambda u: swings.get(u, 0.0)) if swings else None
        win_margin = abs(swings.get(winner, 0.0)) if winner else 0.0
    if winner is None or win_margin < 1e-6:
        winner = None
        win_margin = 0.0
    lopsidedness = min(1.0, win_margin / BLOWOUT_KTC)

    margins = {
        "ktc": win_margin if winner else 0.0,
        "production": float(
            (grade.get("production_total") or {}).get(winner, 0.0)
            if winner else 0.0
        ),
        # "Points Started" per the four-metric vocabulary (was "impact").
        "points_started": float(
            (grade.get("production_regular") or {}).get(winner, 0.0)
            if winner else 0.0
        ),
        # "Playoff Points" (four-metric model, added on feat/owner-section).
        "playoff_points": float(
            (grade.get("production_playoff") or {}).get(winner, 0.0)
            if winner else 0.0
        ),
    }

    # Lineage tells us (a) which received picks the owner flipped *as a pick*
    # before the draft, and (b) each terminal leaf's realized state (kept /
    # dropped / undrafted). Built WITH current_holders so dropped vs kept is
    # accurate. terminal_assets reuses the same bounded walk for the realized
    # production arcs, so story and became-grade tell one story.
    flipped_tree: dict[str, list] = {}
    terminals_by_uid: dict[str, list[dict]] = {}
    if resolved_trades:
        from sleeper_dynasty.engine.lineage import (
            build_trade_lineage, terminal_assets,
        )
        tx_id = rt.trade.transaction_id
        flipped_tree = build_trade_lineage(
            resolved_trades, tx_id, current_holders=current_holders)
        terminals_by_uid = terminal_assets(resolved_trades, tx_id)

    sides: list[dict] = []
    for uid, side in rt.sides.items():
        arcs = [
            build_player_arc(
                pid=a.player_id, player_name=a.name,
                position=positions.get(a.player_id), owner_uid=uid, rt=rt,
                matchups=matchups,
                roster_to_user_by_league=roster_to_user_by_league,
                playoff_weeks_by_league=playoff_weeks_by_league,
                league_season_by_id=league_season_by_id,
                current_holders=current_holders,
            ).to_dict()
            for a in side.received if isinstance(a, PlayerAsset)
        ]
        # Production arcs for the terminal players this side's assets became.
        terminal_arcs: dict[str, PlayerArc] = {}
        for t in terminals_by_uid.get(uid, []):
            if t.get("kind") != "player":
                continue
            tpid = t["player_id"]
            terminal_arcs[tpid] = build_player_arc(
                pid=tpid, player_name=t.get("name") or t.get("label") or tpid,
                position=positions.get(tpid), owner_uid=uid, rt=rt,
                matchups=matchups,
                roster_to_user_by_league=roster_to_user_by_league,
                playoff_weeks_by_league=playoff_weeks_by_league,
                league_season_by_id=league_season_by_id,
                current_holders=current_holders,
            )
        direct_pids = {
            a.player_id for a in side.received if isinstance(a, PlayerAsset)
        }
        realized_players = [
            arc.to_dict() for pid, arc in terminal_arcs.items()
            if pid not in direct_pids
        ]
        # The lineage root nodes are index-aligned with the received assets that
        # carry an identity (players + picks; FAAB is dropped on both sides).
        nodes = flipped_tree.get(uid) or []
        ided = [a for a in side.received if isinstance(a, (PlayerAsset, PickAsset))]
        node_of = {id(a): n for a, n in zip(ided, nodes)}

        def _outcome(a):
            n = node_of.get(id(a))
            flipped = bool(getattr(n, "flipped_as_pick", False))
            realized = ", ".join(_terminal_player_names(n)) if flipped else ""
            po = _pick_outcome(a, flipped_as_pick=flipped,
                               flipped_for=realized or None)
            if po is None or n is None:
                return po
            if flipped:
                po.terminal_state = "flipped"
                return po
            # A kept/dropped/undrafted pick: read the realized state off the
            # terminal leaf, and pull production from the draftee's arc.
            leaf_state = getattr(n, "terminal_state", None)
            tpid = getattr(n, "terminal_player_id", None)
            if leaf_state == "on_roster":
                po.terminal_state = "kept"
            elif leaf_state == "dropped":
                po.terminal_state = "dropped"
            elif leaf_state == "undrafted":
                po.terminal_state = "undrafted"
            arc = terminal_arcs.get(tpid) if tpid else None
            if arc is not None:
                if arc.starter_weeks > 0:
                    po.points_per_game = arc.points_total / arc.starter_weeks
                if po.terminal_state == "dropped":
                    po.dropped_before_week = arc.last_rostered_week or 0
            return po

        outs = [o.to_dict() for o in map(_outcome, side.received) if o is not None]
        # Per-trade direction facts: what this side did in THIS deal and how it
        # relates to their career pattern. Precomputed so the writer never has
        # to derive direction from the owner's career-tilt phrasing (the
        # inference that produced "sold the receiver he actually bought").
        trade_tilt = _trade_tilt(side.received, side.given)
        career_tilt = owner_strategy[uid].tilt if uid in owner_strategy else None
        sides.append({
            "user_id": uid, "owner_name": owners_display.get(uid, uid),
            "given_summary": _asset_summary(list(side.given), positions),
            "received_summary": _asset_summary(list(side.received), positions),
            "this_trade_tilt": trade_tilt,
            "fits_career_tilt": _fits_career_tilt(trade_tilt, career_tilt),
            "player_arcs": arcs, "pick_outcomes": outs,
            "realized_players": realized_players,
        })

    # How it panned out by PRODUCTION (the same head-to-head the chart shows):
    # each side's cumulative total points following the lineage chain (a traded
    # player's points while held, then what he became; a drop stops there).
    lsbi = league_season_by_id or {}
    # Post-trade games played by any side. Drives both the production verdict and
    # season_underway. Computed from matchups alone (independent of
    # resolved_trades) so the "has the season started" signal is always present.
    from sleeper_dynasty.engine.trade_grader import _is_post_trade
    n_games = len({(lg, wk) for (lg, wk, _rid) in matchups
                   if _is_post_trade(lg, wk, rt, lsbi)})
    season_underway = n_games > 0

    production_winner = production_outcome = None
    if resolved_trades and matchups:
        from sleeper_dynasty.engine.trade_grader import player_week_points
        from sleeper_dynasty.engine.production_series import head_to_head_verdict
        totals: dict[str, float] = {}
        for uid, side in rt.sides.items():
            recv = [a.player_id for a in side.received if getattr(a, "player_id", None)]
            term = [t["player_id"] for t in terminals_by_uid.get(uid, [])
                    if t.get("kind") == "player" and t.get("player_id")]
            chain = list(dict.fromkeys([*recv, *term]))
            totals[uid] = sum(
                sum(player_week_points(
                    pid, uid, matchups=matchups,
                    roster_to_user_by_league=roster_to_user_by_league, rt=rt,
                    league_season_by_id=lsbi,
                ).values())
                for pid in chain
            )
        verdict = head_to_head_verdict(
            totals=totals, n_games=n_games, metric="total", names=owners_display)
        production_winner = verdict.get("winner_uid")
        production_outcome = verdict.get("label")

    return TradeStoryFacts(
        trade_id=rt.trade.transaction_id, season=rt.trade.season,
        is_offseason=is_offseason(rt.trade.traded_at),
        season_underway=season_underway,
        winner_user_id=winner, lopsidedness=lopsidedness, margins=margins,
        sides=sides,
        owners={uid: f.to_dict() for uid, f in owner_strategy.items()},
        production_winner_user_id=production_winner,
        production_outcome=production_outcome,
    )
