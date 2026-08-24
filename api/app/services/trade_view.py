from __future__ import annotations

import re

from app.models.trade import (
    AssetFlip, AssetLine, BecameMetrics, LensMargins, LensWinners, LineageNode,
    PlayerInjuryView, PlayerProductionView, ProductionPoint, ProductionVerdictView,
    StandingAtTrade, TradeDetailResp, TradeSideView, TradeStory, TwistView,
)
from app.services.chain_cache import ChainCacheEntry
from app.services.identity import owner_ref
from app.services.start_rate import start_rate
from app.services.standings_snapshot_store import StandingsSnapshotStore
from sleeper_dynasty.engine.lineage import build_trade_lineage
from sleeper_dynasty.engine.trade_story import BLOWOUT_KTC


def _select_twist(sides) -> dict:
    """Pick one engine-derived 'twist' fact for the hero callout.

    Priority: a dropped asset (the haul evaporated) > a clearly low deployment
    side (<50% started while the other side is healthy) > nothing.
    """
    def rows(s):
        return s.get("breakdown") or []
    # 1. dropped asset, highest total points among dropped
    dropped = []
    for s in sides:
        for r in rows(s):
            if (r.get("terminal_state") == "dropped"):
                dropped.append((s.get("owner_name", ""), r))
    if dropped:
        owner, r = max(dropped, key=lambda t: float(t[1].get("production_total") or 0.0))
        return {"kind": "dropped", "owner": owner, "label": "Dropped",
                "detail": f"{owner} dropped {r.get('label')}"}
    # 2. low deployment (a side started <50% while another cleared 70%)
    pcts = [(s.get("owner_name", ""), s.get("start_pct")) for s in sides if s.get("start_pct") is not None]
    if pcts:
        low_owner, low = min(pcts, key=lambda t: t[1])
        high = max((p for _, p in pcts), default=0.0)
        if low < 0.5 and high >= 0.7:
            return {"kind": "low_deploy", "owner": low_owner, "label": "Barely played",
                    "detail": f"{low_owner} started just {round(low * 100)}% of the haul"}
    return {"kind": "none", "owner": "", "label": "", "detail": ""}


def _side_start_pct(rows) -> float | None:
    """Deployment %: started ÷ total over a side's *realized* rows.

    For flipped assets (top-level row has a non-empty flip.became list) the
    became players' production is what the side realized — not the 0/0 pick
    row — so we sum over flip.became instead. For kept assets, we use the row's
    own production fields. Returns None when realized total is 0.
    """
    def g(r, k):
        return getattr(r, k, None) if not isinstance(r, dict) else r.get(k)

    started = 0.0
    total = 0.0
    for r in rows:
        flip = g(r, "flip")
        if flip is not None:
            became = g(flip, "became") or []
            if became:
                for b in became:
                    started += float(g(b, "production_started") or 0.0)
                    total += float(g(b, "production_total") or 0.0)
                continue
        started += float(g(r, "production_started") or 0.0)
        total += float(g(r, "production_total") or 0.0)
    # One definition, shared with owner_view — see services/start_rate.py.
    return start_rate(started, total)


# The five-metric taxonomy as breakdown-row fields, keyed by lens name.
_LENS_FIELDS = {
    "value": "ktc",
    "total": "production_total",
    "regular": "production_regular",
    "playoff": "production_playoff",
    "toilet": "production_toilet",
}


def _realized_lens_totals(rows) -> dict[str, float]:
    """Per-lens realized totals over one side's breakdown rows.

    Same realized reading as the stat table's TOTAL row (and _side_start_pct):
    a kept asset counts its own line; a flipped asset (flip.became non-empty)
    counts what it became instead. Summing the rows this way is exactly what a
    client does, so lens margins reconcile with the visible rows.
    """
    def g(r, k):
        return getattr(r, k, None) if not isinstance(r, dict) else r.get(k)

    totals = {lens: 0.0 for lens in _LENS_FIELDS}
    for r in rows:
        flip = g(r, "flip")
        became = (g(flip, "became") or []) if flip is not None else []
        for src in became if became else [r]:
            for lens, field in _LENS_FIELDS.items():
                totals[lens] += float(g(src, field) or 0.0)
    return totals


def _lens_verdict(totals_by_uid: dict[str, dict[str, float]]) -> dict:
    """Winners/margins per lens + overall call from per-side realized totals.

    A lens where every side is 0 is unscored → excluded from the call and the
    tally (winner/margin null). A scored lens with equal leaders is tied →
    winner/margin null, counts toward nobody. The toilet lens is a plain fact:
    larger figure wins; whether that's desirable is left to copy.

    ``call``: "unanimous" when every decided lens went to one user, "split"
    when decided lenses went to more than one, "none" when nothing was decided
    (all tied or nothing scored).
    """
    winners: dict[str, str | None] = {lens: None for lens in _LENS_FIELDS}
    margins: dict[str, float | None] = {lens: None for lens in _LENS_FIELDS}
    wins_by_uid = {uid: 0 for uid in totals_by_uid}
    for lens in _LENS_FIELDS:
        vals = {uid: float((t or {}).get(lens) or 0.0)
                for uid, t in totals_by_uid.items()}
        if len(vals) < 2 or all(v == 0.0 for v in vals.values()):
            continue  # unscored (or not a multi-side trade)
        top = max(vals.values())
        leaders = [uid for uid, v in vals.items() if v == top]
        if len(leaders) > 1:
            continue  # tied
        uid = leaders[0]
        winners[lens] = uid
        margins[lens] = top - max(v for u, v in vals.items() if u != uid)
        wins_by_uid[uid] += 1
    lens_winners = {u for u, n in wins_by_uid.items() if n > 0}
    call = ("none" if not lens_winners
            else "unanimous" if len(lens_winners) == 1 else "split")
    tally = "-".join(
        str(n) for n in sorted(wins_by_uid.values(), reverse=True)) or "0"
    return {"winners": winners, "margins": margins, "call": call, "tally": tally}


def _collect_terminal_ids(node) -> list[str]:
    """player_ids of the terminal leaves beneath a lineage node."""
    out: list[str] = []
    if not node.children and node.terminal_player_id:
        out.append(node.terminal_player_id)
    for c in node.children:
        out.extend(_collect_terminal_ids(c))
    return out


def _collect_terminal_player_states(node) -> dict[str, str | None]:
    """terminal_state (on_roster / dropped / …) by player_id for terminal player
    leaves — so a flipped asset's became players carry the same roster status a
    kept asset shows."""
    out: dict[str, str | None] = {}
    if not node.children and node.terminal_player_id:
        out[node.terminal_player_id] = node.terminal_state
    for c in node.children:
        out.update(_collect_terminal_player_states(c))
    return out


def _collect_terminal_picks(node) -> list[dict]:
    """(label, terminal_state) for terminal pick leaves (undrafted futures)."""
    out: list[dict] = []
    if not node.children and node.terminal_pick:
        out.append({"label": node.label, "terminal_state": node.terminal_state})
    for c in node.children:
        out.extend(_collect_terminal_picks(c))
    return out


def _enrich_breakdown(rows, nodes, became_rows, name_of) -> list[AssetLine]:
    """Attach journey info (terminal_state / linked flip + what it became) to
    each received-asset row. Rows and lineage root nodes are index-aligned
    (both derive from the same received-asset order). ``became_rows`` are the
    side's terminal stat lines, matched to a flip's leaves by player_id."""
    by_pid = {r.get("player_id"): r for r in became_rows if r.get("player_id")}
    by_pick_label = {r.get("label"): r for r in became_rows
                     if not r.get("player_id") and r.get("label")}
    out: list[AssetLine] = []
    for i, r in enumerate(rows):
        line = dict(r)
        owner_uid = line.get("from_pick_owner_uid")
        if owner_uid:
            # Resolve the pick's original-owner uid to a display name so the row
            # tag matches the exchange line's "(orig: X)". When the uid can't be
            # resolved (name_of echoes the raw id — e.g. an owner who left the
            # league), drop it rather than print an 18-digit Sleeper id.
            nm = name_of(owner_uid)
            if nm and nm != owner_uid:
                line["from_pick_owner"] = nm
        node = nodes[i] if i < len(nodes) else None
        if node is not None and node.flipped_as_pick and line.get("label"):
            # The owner flipped this pick before the draft, so the slot's
            # eventual draftee — baked into the label as "(<name>)" — is not
            # what they realized. Drop it; the flip journey shows the real
            # outcome. (Held picks keep the annotation: they did draft him.)
            line["label"] = re.sub(r"\s*\([^)]*\)\s*$", "", line["label"])
        if node is not None and node.flipped_at:
            leaf_ids = _collect_terminal_ids(node)
            leaf_states = _collect_terminal_player_states(node)
            terminal_picks = _collect_terminal_picks(node)
            player_became = [
                AssetLine(**{**by_pid[pid], "terminal_state": leaf_states.get(pid)})
                for pid in leaf_ids if pid in by_pid
            ]
            pick_became = [
                AssetLine(**(by_pick_label[p["label"]]
                              if p["label"] in by_pick_label
                              else {"label": p["label"], "kind": "pick",
                                    "terminal_state": p["terminal_state"]}))
                for p in terminal_picks
            ]
            line["flip"] = AssetFlip(
                to_owner=name_of(node.flip_counterparty_uid),
                trade_id=node.flip_trade_id,
                league_id=node.flip_league_id,
                date=node.flipped_at,
                became=player_became + pick_became,
            )
        elif node is not None:
            line["terminal_state"] = node.terminal_state
        out.append(AssetLine(**line))
    return out


def _to_lineage(node) -> LineageNode:
    return LineageNode(
        label=node.label, kind=node.kind, flipped_at=node.flipped_at,
        terminal_state=node.terminal_state, became_player=node.became_player,
        children=[_to_lineage(c) for c in node.children],
    )


def build_trade_detail(
    entry: ChainCacheEntry, trade_id: str,
    *, standings_store: StandingsSnapshotStore | None = None,
) -> TradeDetailResp | None:
    rt = next(
        (r for r in entry.resolved_trades
         if r["trade"]["transaction_id"] == trade_id),
        None,
    )
    if rt is None:
        return None
    grade = entry.grades.get(trade_id) or {}
    sides: list[TradeSideView] = []
    at_swing = (grade.get("at_trade_value_swing") or {})
    aged = (grade.get("aged_value_swing") or {})

    # Journey enrichment: marry each side's received breakdown with the lineage
    # tree (flip metadata) and the became leaves' stats.
    raw_lineage = build_trade_lineage(
        entry.resolved_trades, trade_id, entry.current_holders or {})
    became_grades = ((entry.became_grades or {}).get(trade_id) or {}).get("grades") or {}

    # Per-trade production series + verdict
    prod_series_raw = (getattr(entry, "trade_production_series", None) or {}).get(trade_id) or {}
    production_series_view: dict[str, dict[str, list[ProductionPoint]]] = {}
    for uid, by_metric in prod_series_raw.items():
        production_series_view[uid] = {
            metric: [ProductionPoint(season=s, week=w, value=v) for s, w, v in pts]
            for metric, pts in by_metric.items()
        }
    prod_verdict_raw = (getattr(entry, "trade_production_verdict", None) or {}).get(trade_id) or {}
    production_verdict_view = {
        metric: ProductionVerdictView(**vd) for metric, vd in prod_verdict_raw.items()
    }
    production_week_axis = list(getattr(entry, "production_week_axis", None) or [])
    production_week_phases = list(getattr(entry, "production_week_phases", None) or [])

    # Received players that left the roster (dropped/traded): uid -> [DepartureView]
    from app.models.trade import DepartureView
    departures_raw = (getattr(entry, "trade_departures", None) or {}).get(trade_id) or {}
    departures_view: dict[str, list[DepartureView]] = {
        uid: [DepartureView(**d) for d in dlist] for uid, dlist in departures_raw.items()
    }

    # Per-player production drill: uid -> [PlayerProductionView]
    players_raw = (getattr(entry, "trade_production_players", None) or {}).get(trade_id) or {}
    production_players_view: dict[str, list[PlayerProductionView]] = {
        uid: [
            PlayerProductionView(
                player_id=p["player_id"],
                series={
                    m: [ProductionPoint(season=s, week=w, value=v) for s, w, v in pts]
                    for m, pts in p["byMetric"].items()
                },
            )
            for p in plist
        ]
        for uid, plist in players_raw.items()
    }

    # Per-received-player injury context: uid -> player_id -> PlayerInjuryView
    injury_raw = (getattr(entry, "trade_injury", None) or {}).get(trade_id) or {}
    injury_view: dict[str, dict[str, PlayerInjuryView]] = {
        uid: {pid: PlayerInjuryView(**blk) for pid, blk in by_pid.items()}
        for uid, by_pid in injury_raw.items()
    }

    def _name_of(uid: str | None) -> str:
        if not uid:
            return "another team"
        return (entry.owners.get(uid, {}) or {}).get("owner_name") or uid

    enriched_breakdown: dict[str, list[AssetLine]] = {}
    for uid in (rt["sides"] or {}):
        enriched_breakdown[uid] = _enrich_breakdown(
            (grade.get("breakdown") or {}).get(uid, []),
            raw_lineage.get(uid, []),
            (became_grades.get(uid) or {}).get("breakdown") or [],
            _name_of,
        )
    standing_by_owner: dict[str, StandingAtTrade] = {}
    if standings_store is not None:
        rows = standings_store.as_of(
            entry.league_id,
            int(rt["trade"]["season"]),
            int(rt["trade"]["week"]),
        )
        total = len(rows)
        for row in rows:
            standing_by_owner[row["owner_id"]] = StandingAtTrade(
                rank=int(row["rank"]),
                wins=int(row["wins"]),
                losses=int(row["losses"]),
                ties=int(row["ties"]),
                points_for=float(row["points_for"]),
                total_teams=total,
            )
    for uid, side in (rt["sides"] or {}).items():
        ref = owner_ref(entry, uid)
        sides.append(TradeSideView(
            user_id=uid,
            owner_name=ref.owner_name,
            team_name=ref.team_name,
            avatar_url=ref.avatar_url,
            received=side.get("received") or [],
            given=side.get("given") or [],
            snapshot_ktc_swing=float(
                (grade.get("snapshot_value_swing") or {}).get(uid, 0) or 0
            ),
            received_ktc=float(
                (grade.get("received_ktc") or {}).get(uid, 0) or 0
            ),
            breakdown=enriched_breakdown.get(uid, []),
            production_total=float(
                (grade.get("production_total") or {}).get(uid, 0) or 0
            ),
            production_started=float(
                (grade.get("production_started") or {}).get(uid, 0) or 0
            ),
            start_pct=_side_start_pct(enriched_breakdown.get(uid, [])),
            production_regular=float(
                (grade.get("production_regular") or {}).get(uid, 0) or 0
            ),
            production_playoff=float(
                (grade.get("production_playoff") or {}).get(uid, 0) or 0
            ),
            production_toilet=float(
                (grade.get("production_toilet") or {}).get(uid, 0) or 0
            ),
            at_trade_ktc_swing=(float(at_swing[uid]) if uid in at_swing else None),
            aged_ktc_swing=(float(aged[uid]) if uid in aged else None),
            at_trade_approx=bool(grade.get("at_trade_approx", False)),
            at_trade_snapshot_date=grade.get("at_trade_snapshot_date"),
            at_trade_standing=standing_by_owner.get(uid),
        ))
    raw_story = (entry.trade_stories or {}).get(trade_id)
    story = (
        TradeStory(verdict=raw_story.get("verdict", ""),
                   lede=raw_story.get("lede", ""),
                   beats=raw_story.get("beats", []) or [],
                   body=raw_story.get("body", ""),
                   generated_at=raw_story.get("generated_at"))
        if raw_story else None
    )
    lineage = {uid: [_to_lineage(n) for n in nodes] for uid, nodes in raw_lineage.items()}
    became = {
        uid: BecameMetrics(
            ktc=float(m.get("ktc", 0.0) or 0.0),
            production=float(m.get("production", 0.0) or 0.0),
            regular=float(m.get("regular", 0.0) or 0.0),
            playoff=float(m.get("playoff", 0.0) or 0.0),
            toilet=float(m.get("toilet", 0.0) or 0.0),
            terminal_labels=list(m.get("terminal_labels") or []),
            breakdown=[AssetLine(**r) for r in (m.get("breakdown") or [])],
        )
        for uid, m in became_grades.items()
    }
    owner_names = {
        uid: (o or {}).get("owner_name") or uid
        for uid, o in (entry.owners or {}).items()
    }
    # Per-lens verdicts over each side's REALIZED breakdown rows (kept assets'
    # own line + flipped assets' became — the stat table's TOTAL reading).
    lens = _lens_verdict({
        uid: _realized_lens_totals(rows)
        for uid, rows in enriched_breakdown.items()
    })
    # Compute hero card inputs: Trade Value winner + lopsidedness.
    winner_user_id: str | None = None
    lopsidedness: float = 0.0
    if len(sides) >= 2:
        sorted_by_ktc = sorted(sides, key=lambda s: s.received_ktc, reverse=True)
        if sorted_by_ktc[0].received_ktc > sorted_by_ktc[1].received_ktc:
            winner_user_id = sorted_by_ktc[0].user_id
            win_margin = sorted_by_ktc[0].received_ktc - sorted_by_ktc[1].received_ktc
            lopsidedness = min(1.0, win_margin / BLOWOUT_KTC)

    # Build selector input from assembled TradeSideViews and attach twist callout.
    side_dicts = [
        {
            "owner_name": sv.owner_name,
            "start_pct": sv.start_pct,
            "breakdown": [
                {
                    "label": al.label,
                    "terminal_state": al.terminal_state,
                    "ktc": al.ktc,
                    "production_total": al.production_total,
                }
                for al in sv.breakdown
            ],
        }
        for sv in sides
    ]
    _twist_raw = _select_twist(side_dicts)
    twist = TwistView(**_twist_raw) if _twist_raw["kind"] != "none" else None
    return TradeDetailResp(
        league_id=entry.league_id,
        trade_id=trade_id,
        date=rt["trade"]["traded_at"][:10],
        week=rt["trade"]["week"],
        season=rt["trade"]["season"],
        league_name=entry.league_name_by_id.get(
            rt["trade"]["league_id"], rt["trade"]["league_id"]
        ),
        sides=sides,
        story=story,
        lineage=lineage,
        became=became,
        owner_names=owner_names,
        production_series=production_series_view,
        production_verdict=production_verdict_view,
        production_week_axis=production_week_axis,
        production_week_phases=production_week_phases,
        production_players=production_players_view,
        injury=injury_view,
        departures=departures_view,
        twist=twist,
        winner_user_id=winner_user_id,
        lopsidedness=lopsidedness,
        winners_by_lens=LensWinners(**lens["winners"]),
        margins_by_lens=LensMargins(**lens["margins"]),
        call=lens["call"],
        lens_tally=lens["tally"],
    )
