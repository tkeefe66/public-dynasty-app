"""Current ratings require real format, holdings, prices, and pick evidence."""
from math import isfinite


def verify_current_assets(league, rosters, supporting, *, picks_verified, draft_rounds=None):
    result = {"version": 1, "status": "unavailable", "format": getattr(league, "format", None)}
    if not getattr(league, "effective_format_verified", False):
        return {**result, "reason": getattr(league, "format_error", None) or
                "Current league format is unverified. Verify this season's keeper/redraft settings."}
    assigned = [r for r in rosters if r.owner_id]
    if (not rosters or len(rosters) != getattr(league, "total_rosters", None)
            or not assigned or len({r.owner_id for r in assigned}) != len(assigned)):
        return {**result, "reason": "Current roster ownership is incomplete. Refresh league data."}
    if len(assigned) != len(rosters):
        ids = [getattr(r, "roster_id", None) for r in rosters]
        if any(type(rid) is not int for rid in ids) or len(set(ids)) != len(ids):
            return {**result, "reason": "Current roster identifiers are incomplete. Refresh league data."}
        result["owner_coverage"] = {
            "roster_to_owner": {str(r.roster_id): r.owner_id for r in assigned},
            "excluded_rosters": [{"roster_id": r.roster_id, "reason": "Current owner is unassigned."}
                                 for r in rosters if not r.owner_id],
        }
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
            if result["format"] == "keeper":
                receipt = supporting.get("full_player_pick_valuation") or {}
                if (receipt.get("status") != "ready" or receipt.get("league_id") != league.league_id
                        or receipt.get("season") != league.season or receipt.get("draft_rounds") != draft_rounds):
                    return {**result, "reason": receipt.get("reason") or
                            "Full-player pick prices require a verified completed draft and public player prices."}
                result["pick_valuation"] = receipt
            for year in range(league.season + 1, league.season + 4):
                for round_number in range(1, draft_rounds + 1):
                    value = getattr(table.get((year, round_number)), "superflex_value", None)
                    if not isinstance(value, (int, float)) or not isfinite(value) or value <= 0:
                        return {**result, "reason": "Future-pick prices are incomplete. Missing pick prices are not scored as zero."}
    return {**result, "status": "ready"}


def current_owner_coverage(entry):
    """A partial-owner receipt is valid only for its exact current membership."""
    coverage = entry.current_rating_verification.get("owner_coverage")
    if not coverage:
        return None
    mapping = {str(rid): uid for rid, uid in
               entry.roster_to_user_by_league.get(entry.league_id, {}).items() if uid}
    excluded = coverage.get("excluded_rosters") or []
    if (not mapping or coverage.get("roster_to_owner") != mapping or not excluded
            or any(str(row.get("roster_id")) in mapping for row in excluded)):
        return None
    return coverage


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
    if audit.get("pick_valuation"):
        from app.services.full_player_pick_values import current_pick_valuation
        if current_pick_valuation(entry) is None:
            return "Current full-player pick valuation is stale. Refresh draft and player data before publishing ratings."
    if audit.get("owner_coverage") and current_owner_coverage(entry) is None:
        return "Current owner verification is stale. Refresh league data before publishing ratings."
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
