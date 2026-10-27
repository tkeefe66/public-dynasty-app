"""Current ratings require real format, holdings, prices, and pick evidence."""
from math import isfinite


def verify_current_assets(league, rosters, supporting, *, picks_verified, draft_rounds=None):
    result = {"version": 1, "status": "unavailable", "format": getattr(league, "format", None)}
    if not getattr(league, "effective_format_verified", False):
        return {**result, "reason": getattr(league, "format_error", None) or
                "Current league format is unverified. Verify this season's keeper/redraft settings."}
    if (not rosters or len(rosters) != getattr(league, "total_rosters", None)
            or any(not r.owner_id for r in rosters)
            or len({r.owner_id for r in rosters}) != len(rosters)):
        return {**result, "reason": "Current roster ownership is incomplete. Refresh league data."}
    if result["format"] != "redraft":
        positions = supporting.get("positions") or {}
        prices = supporting.get("ktc_by_player_id") or {}
        missing = []
        for roster in rosters:
            if not roster.players:
                return {**result, "reason": "Current rosters are incomplete. Refresh league data."}
            for pid in roster.players:
                if positions.get(pid) in {"K", "DEF", "DL", "LB", "DB", "DE", "DT", "CB", "S", "SS", "FS", "NT", "ILB", "OLB"}:
                    continue
                value = getattr(prices.get(pid), "superflex_value", None)
                if not positions.get(pid) or not isinstance(value, (int, float)) or not isfinite(value) or value < 0:
                    missing.append(pid)
        if missing:
            return {**result, "missing_price_player_ids": sorted(set(missing)),
                    "reason": f"Current roster prices are unverified for {len(set(missing))} players. Missing prices are not scored as zero."}
        evidence = getattr(league, "format_evidence", None) or {}
        no_future_picks = evidence.get("future_picks_retained") is False
        # Yahoo's adapter returns [] without querying a pick-ownership ledger.
        if not no_future_picks and (".l." in league.league_id or not picks_verified):
            return {**result, "reason": "Current future-pick ownership is unverified. Verify player-only retention or supply a pick ledger."}
        if not no_future_picks:
            if type(draft_rounds) is not int or draft_rounds <= 0:
                return {**result, "reason": "Future draft rounds are unverified. Verify the season's draft settings."}
            table = supporting.get("pick_value_table") or {}
            for year in range(league.season + 1, league.season + 4):
                for round_number in range(1, draft_rounds + 1):
                    value = getattr(table.get((year, round_number)), "superflex_value", None)
                    if not isinstance(value, (int, float)) or not isfinite(value) or value <= 0:
                        return {**result, "reason": "Future-pick prices are incomplete. Missing pick prices are not scored as zero."}
    return {**result, "status": "ready"}


def current_rating_error(entry):
    from app.services.current_results_coverage import current_results
    scoped = current_results(entry)
    # Current/All Results are cumulative. Dated provisional snapshots filter
    # excluded seasons, but the career rollup does not yet apply that coverage.
    excluded = {}
    for year, snapshot in (entry.season_rating_inputs or {}).items():
        coverage = snapshot.get("results_coverage") or {}
        if snapshot.get("requires_results_coverage") and not coverage:
            excluded[int(year)] = "Required historical Results verification is missing."
        for item in coverage.get("excluded_seasons", []):
            excluded[item["season"]] = item["reason"]
    scoped_exclusions = {x['season'] for x in scoped['coverage']['excluded_seasons']} if scoped else set()
    if excluded and not set(excluded).issubset(scoped_exclusions):
        details = "; ".join(f"{year}: {reason}" for year, reason in sorted(excluded.items()))
        return f"Cumulative Results include unverified history ({details}). Current and All ratings remain unavailable until that history is verified or explicitly excluded from the career calculation."
    audit = entry.current_rating_verification
    if audit.get('requires_results_coverage') and scoped is None:
        return "Current provisional Results verification is missing or stale. Revalidate coverage before publishing ratings."
    if audit:
        if audit.get("status") != "ready":
            return audit.get("reason") or "Current rating inputs are unverified. Refresh league data."
        if audit.get("format") != entry.capabilities.get("format"):
            return "Current rating inputs use a different league format. Refresh league data."
        from app.services.season_ratings import _complete_signals
        owners = set(entry.roster_to_user_by_league.get(entry.league_id, {}).values()) or set(entry.owners)
        outcomes = scoped['outcome_signals'] if scoped else entry.outcome_signals
        if not _complete_signals(owners, outcomes, entry.outlook_signals, audit["format"]):
            return "Current rating signals are incomplete. Refresh league data; missing inputs are not scored as zero."
    else:
        return "Current league format and rating inputs require verification. Refresh league data."
    return None
