"""Pure, serializable generation inputs built alongside free grading."""
from dataclasses import asdict

from sleeper_dynasty.engine.trade_story import (
    build_owner_strategy,
    build_trade_story_facts,
)


def build_inputs(entry, resolved, grades, supporting, resolved_dicts, current_holders, franchises):
    from app.services.blurb_gen import owner_rating_facts_by_scope
    from app.services.generation.models import stamp
    out = []
    names = {uid: owner.get("owner_name") or uid for uid, owner in entry.owners.items()}
    provider = "yahoo" if ".l." in entry.league_id else "sleeper"
    for rt in resolved:
        tx = rt.trade.transaction_id
        facts = build_trade_story_facts(
            rt=rt, grade=grades.get(tx) or {},
            owner_strategy=build_owner_strategy(resolved, grades, names, as_of=rt.trade.traded_at),
            owners_display=names, matchups=supporting["matchups"],
            roster_to_user_by_league=supporting["roster_to_user_by_league"],
            playoff_weeks_by_league=supporting["playoff_weeks_by_league"],
            league_season_by_id=supporting["league_season_by_id"],
            positions=supporting.get("positions") or {}, resolved_trades=resolved_dicts,
            current_holders=current_holders or {})
        out.append({"feature": "trade_story", "identity": [provider, rt.trade.league_id, tx],
            "event": "created", "payload": {"facts": asdict(facts),
                "event_at": int(rt.trade.traded_at.timestamp()), "season": facts.season,
                "target": {"slot": "trade_stories", "key": tx}}})
    season = entry.league_season_by_id.get(entry.league_id, 0)
    period = getattr(entry, "generation_period", {}) or {}
    week = int(period.get("week") or 0) if period.get("season") == season else 0
    common = {"season": season, "week": week, "event_at": stamp()}
    event = f"{season}:week:{week:02d}"
    for scope, owners in owner_rating_facts_by_scope(entry).items():
        for uid, facts in owners.items():
            out.append({"feature": "gm_rating_blurb", "identity": [season, scope, uid],
                "event": event, "payload": {**common, "facts": asdict(facts),
                    "target": {"slot": "owner_rating_blurbs", "scope": scope, "key": uid}}})
    for uid, facts in franchises.items():
        out.append({"feature": "franchise_blurb", "identity": [season, uid], "event": event,
            "payload": {**common, "facts": asdict(facts),
                "target": {"slot": "franchise_blurbs", "key": uid}}})
    return out
