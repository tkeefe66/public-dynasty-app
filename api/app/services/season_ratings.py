"""Dated rating inputs and a shared, fail-closed scope resolver.

All keeps the existing career model. A year never falls back to current facts.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime
from math import isfinite

from app.services.chain_cache import ChainCacheEntry

INPUT_VERSION = 1


def historical_results_digest(snapshot):
    from app.services.historical_backfill import digest
    payload = {"outcome_signals": snapshot["outcome_signals"],
               "season_records": snapshot["season_records"]}
    if snapshot.get("results_coverage"):
        payload["results_coverage"] = {k: v for k, v in snapshot["results_coverage"].items()
                                       if k not in {"verified_at", "verified_by"}}
    return digest(payload)


def _complete_signals(owners, outcomes, assets, fmt):
    def valid(signals, keys):
        return all(isinstance(signals.get(key), (int, float)) and
                   isfinite(signals[key]) for key in keys)
    for uid in owners:
        if not valid(outcomes.get(uid, {}), ("expected_wins", "playoff_success", "luck")):
            return False
        if fmt != "redraft":
            keys = ("roster_value_share", "draft_capital")
            if fmt == "dynasty":
                keys += ("young_core_share",)
            if not valid(assets.get(uid, {}), keys):
                return False
    return True


def scoped_rating_entry(entry: ChainCacheEntry, year) -> ChainCacheEntry | None:
    from app.services.current_rating_verification import current_rating_error
    if year == "all":
        from app.services.current_results_coverage import current_scoped_entry
        return None if current_rating_error(entry) else current_scoped_entry(entry)
    snapshot = (entry.season_rating_inputs or {}).get(str(year), {})
    if snapshot.get("basis") == "current" and current_rating_error(entry):
        return None
    if snapshot.get("version") != INPUT_VERSION or snapshot.get("status") not in {"ready", "provisional"}:
        return None
    owner_only = snapshot.get("basis") == "current" and bool(entry.current_rating_verification.get("owner_coverage"))
    from app.services.full_player_pick_values import current_pick_valuation
    model_only = snapshot.get("basis") == "current" and bool(current_pick_valuation(entry))
    if snapshot.get("basis") != "current" and (snapshot.get("asset_source") or {}).get("pick_valuation"):
        from app.services.historical_full_player_picks import snapshot_valuation
        model_only = bool(snapshot_valuation(snapshot))
        source = snapshot['asset_source']
        if (not model_only or source.get('season') != int(year)
                or entry.league_season_by_id.get(source.get('season_league_id')) != int(year)
                or source.get('identity_version') != entry.owner_identity_version):
            return None
    if ((snapshot.get("status") == "provisional" and not (owner_only or model_only)) or snapshot.get("results_coverage")
            or snapshot.get("requires_results_coverage")):
        from app.services.historical_results_coverage import ResultsCoverage
        try:
            coverage = ResultsCoverage.model_validate(snapshot.get("results_coverage"))
        except ValueError:
            return None
        if (snapshot.get("status") != "provisional" or coverage.season != int(year)
                or coverage.identity_version != entry.owner_identity_version
                or coverage.league_seasons != {lid: y for lid, y in entry.league_season_by_id.items() if y <= int(year)}
                or {int(y) for y in snapshot.get("season_records", {})} != set(coverage.included_seasons)
                or (snapshot.get("basis") != "current" and snapshot.get("format") != "redraft" and not snapshot.get("asset_source"))):
            return None
    owners = snapshot.get("owners") or []
    if owner_only:
        from app.services.current_rating_verification import current_owner_coverage
        coverage = current_owner_coverage(entry)
        if coverage is None or set(owners) != set(coverage["roster_to_owner"].values()):
            return None
    if any(uid not in entry.owners for uid in owners):
        return None
    from app.services.owner_membership import season_membership
    membership = season_membership(entry, int(year))
    owners = [uid for uid in owners if membership.get(uid) == "active"]
    outcomes = snapshot.get("outcome_signals") or {}
    assets = snapshot.get("outlook_signals") or {}
    fmt = snapshot.get("format")
    if fmt not in {"dynasty", "keeper", "redraft"} or not owners:
        return None
    if not _complete_signals(owners, outcomes, assets, fmt):
        return None
    roster_ranks = snapshot.get("roster_ranks") or {}
    if any(uid not in owners for uid in roster_ranks):
        ranked = sorted((uid for uid in roster_ranks if uid in owners),
                        key=lambda uid: roster_ranks[uid]["rank"])
        roster_ranks = {uid: {"rank": i + 1, "of": len(ranked)} for i, uid in enumerate(ranked)}
    return replace(
        entry,
        owners={uid: entry.owners[uid] for uid in owners},
        capabilities={**entry.capabilities, "format": fmt},
        outcome_signals=outcomes, outlook_signals=assets,
        season_records={s: rows for s, rows in (snapshot.get("season_records") or {}).items()
                        if int(s) <= int(year)},
        roster_ranks=roster_ranks,
        # Historical stage applies to the historical roster, including owners
        # who have since left. Never consult today's outlook availability.
        dynasty_outlooks={uid: {"historical": True} for uid in assets},
    )


def rating_scope(entry: ChainCacheEntry, year) -> dict:
    snapshot = (entry.season_rating_inputs or {}).get(str(year), {})
    scoped = scoped_rating_entry(entry, year)
    ready = scoped is not None
    from app.services.current_results_coverage import current_results
    current_snapshot = current_results(entry) if year == "all" else None
    coverage = (current_snapshot or {}).get("coverage", {}) if year == "all" else snapshot.get("results_coverage") or {}
    from app.services.current_rating_verification import current_owner_coverage
    owner_coverage = current_owner_coverage(entry) if year == "all" or snapshot.get("basis") == "current" else None
    from app.services.full_player_pick_values import (
        current_pick_valuation,
        valuation_note,
    )
    pick_valuation = current_pick_valuation(entry) if year == "all" or snapshot.get("basis") == "current" else None
    provisional = ready and bool(coverage or owner_coverage or pick_valuation)
    from app.services.historical_full_player_picks import snapshot_valuation
    historical_valuation = snapshot_valuation(snapshot) if ready and snapshot.get("basis") != "current" else None
    provisional = provisional or bool(historical_valuation)
    reason = None
    if scoped is None:
        from app.services.current_rating_verification import current_rating_error
        reason = (current_rating_error(entry) if year == "all" or snapshot.get("basis") == "current" else None) or snapshot.get("reason") or (
            "Verified season inputs are missing. Refresh league data; historical assets require a verified backfill.")
    basis = "current" if year == "all" else snapshot.get("basis", "season_end")
    source = snapshot.get("asset_source") or {}
    policy = source.get("valuation_policy") or {}
    stats_guy = ready and year != "all" and policy.get("version") in {"stats-guy-v1", "stats-guy-offense-v2"}
    dynasty_process = ready and year != "all" and policy.get("version") in {"dynasty-process-v1", "dynasty-process-offense-v2"}
    dated_prices = stats_guy or dynasty_process
    return {
        "status": "provisional" if provisional else "ready" if ready else "unavailable", "basis": basis,
        "as_of": entry.cached_at if year == "all" else snapshot.get("as_of"),
        "label": ("Provisional current career rating" if provisional and basis == "current" else
                  f"Provisional franchise rating at end of {year}" if provisional else
                  "Current career rating" if year == "all" else
                  f"Franchise rating through {year}" if basis == "current" else
                  f"Franchise rating at end of {year}") if ready else
                 "Historical data unavailable" if year != "all" else "Rating unavailable",
        "reason": reason,
        "current_valuation_note": valuation_note(pick_valuation) if ready and pick_valuation else None,
        "included_seasons": coverage.get("included_seasons", []),
        "excluded_seasons": coverage.get("excluded_seasons", []),
        "verified_owner_count": len(owner_coverage["roster_to_owner"]) if owner_coverage else None,
        "excluded_rosters": owner_coverage["excluded_rosters"] if owner_coverage else [],
        "valuation_source": "stats_guy" if stats_guy else "dynasty_process" if dynasty_process else None,
        "prices_as_of": source.get("prices_as_of") if dated_prices else None,
        "valuation_note": (f"{policy['priced']}/{policy['eligible']} offensive players priced. "
                           "Unranked players use a zero replacement floor; "
                           + ("kickers, team defenses, and individual defensive players are excluded from assets. "
                              if policy.get("version", "").endswith("offense-v2") else
                              "kickers and defenses are excluded from assets. ")
                           + ("No future-pick assets were included in this verified snapshot. "
                              if source.get("draft_rounds") == 0 else
                              ("Estimated full-player keeper picks use this season's completed draft and the same dated player board across the next three drafts. Keeper selections are excluded; round averages are smoothed. "
                               if historical_valuation else "Generic round values price future picks. "))
                           + ("Keeper placeholder exclusions were reconstructed from reviewed draft, roster, and transaction evidence. "
                              if historical_valuation and source.get("pick_valuation", {}).get("reconstruction") else "")
                           + "Historical estimates use "
                           "a different valuation source from current ratings.") if dated_prices else None,
    }


def build_season_rating_inputs(entry: ChainCacheEntry, supporting: dict, *, asset_store=None,
                              results_store=None, results_coverage=None, prior_snapshots=None,
                              format_store=None) -> dict:
    """Build fresh inputs, including on incremental refresh and identity changes.

    Results are re-derived from bounded raw seasons. Historical Assets require
    a verified manifest; the current holdings/price table is never a substitute.
    """
    from app.services.rating_signals import compute_rating_signals
    from sleeper_dynasty.engine.results_signals import (
        latest_played_season,
        results_signals,
    )
    from sleeper_dynasty.engine.standings import all_play_win_pct

    now = datetime.fromisoformat(entry.cached_at)
    calendar_season = now.year - (1 if now.month <= 2 else 0)
    years = sorted(set(entry.league_season_by_id.values()))
    out = {}
    prior_snapshots = entry.season_rating_inputs if prior_snapshots is None else prior_snapshots
    for year in years:
        lids = [lid for lid, season in entry.league_season_by_id.items() if season == year]
        from app.services.aggregations import _championship_decided
        completed = any(lg.get("status") == "complete" for lg in entry.chain if lg.get("season") == year)
        completed = completed or _championship_decided((entry.season_records or {}).get(str(year), {}))
        owners = sorted({uid for lid in lids for uid in entry.roster_to_user_by_league.get(lid, {}).values()})
        fmt = next((lg.get("format") for lg in entry.chain
                    if lg.get("season") == year and lg.get("format") in {"dynasty", "keeper", "redraft"}), None)
        # Never infer an old season's format from today's settings.
        current = year == max(years) and year >= calendar_season and not completed
        if current and fmt is None:
            fmt = entry.capabilities.get("format", "dynasty")
        snapshot = {"version": INPUT_VERSION, "status": "unavailable",
                    "basis": "current" if current else "season_end", "format": fmt,
                    "as_of": entry.cached_at if current else None, "owners": owners}
        out[str(year)] = snapshot
        prior = (prior_snapshots or {}).get(str(year), {})
        if not current and ((prior.get("status") == "provisional" and not (prior.get("asset_source") or {}).get("pick_valuation")) or prior.get("results_coverage")
                            or prior.get("requires_results_coverage")):
            snapshot["requires_results_coverage"] = True
        if not current and (prior.get("format_evidence") or prior.get("requires_format_evidence")):
            snapshot["requires_format_evidence"] = True
        if not current and format_store is not None and len(lids) == 1:
            try:
                format_evidence = format_store.load(lids[0], year)
                if format_evidence:
                    fmt = format_evidence['format']
                    snapshot.update(format=fmt, format_evidence=format_evidence, requires_format_evidence=True)
            except (ValueError, OSError) as exc:
                snapshot['reason'] = str(exc)
                continue
        if snapshot.get("requires_format_evidence") and not snapshot.get("format_evidence"):
            snapshot["reason"] = "Reviewed season format evidence is missing. Restore its verified record."
            continue
        if not owners or fmt is None:
            snapshot["reason"] = "Season membership or league format is unverified. Refresh league data."
            continue
        if current:
            from app.services.current_rating_verification import current_rating_error
            from app.services.current_results_coverage import (
                current_results,
                current_scoped_entry,
            )
            error = current_rating_error(entry)
            if error:
                snapshot["reason"] = error
                continue
            scoped_current = current_scoped_entry(entry)
            owners = [uid for uid in owners if uid in scoped_current.owners]
            snapshot["owners"] = owners
            receipt = current_results(entry)
            if receipt:
                snapshot.update(results_coverage=receipt['coverage'], requires_results_coverage=True)
            snapshot.update(outcome_signals=deepcopy(scoped_current.outcome_signals),
                            outlook_signals=deepcopy(entry.outlook_signals),
                            roster_ranks=deepcopy(entry.roster_ranks),
                            season_records=deepcopy(scoped_current.season_records))
        else:
            bounded_lids = {lid: season for lid, season in entry.league_season_by_id.items() if season <= year}
            effective = supporting
            try:
                raw_coverage = (results_coverage or {}).get(str(year))
                if raw_coverage is None and results_store is not None and len(lids) == 1:
                    raw_coverage = results_store.load(lids[0], year)
                if raw_coverage is not None:
                    snapshot["requires_results_coverage"] = True
                    from app.services.historical_results_coverage import apply_coverage
                    effective, coverage = apply_coverage(entry, supporting, year, raw_coverage)
                    snapshot["results_coverage"] = coverage.model_dump(mode="json")
                    bounded_lids = effective["league_season_by_id"]
                elif snapshot.get("requires_results_coverage") or supporting.get("excluded_result_seasons"):
                    snapshot["requires_results_coverage"] = True
                    snapshot["reason"] = "Selected year requires verified Results coverage before excluded history can be used."
                    continue
            except ValueError as exc:
                snapshot["reason"] = str(exc)
                continue
            # A missing week changes every owner's all-play population. Do not
            # grade a partial archive as though it represented the full season.
            matchups = effective.get("matchups") or {}
            complete = all(entry.roster_to_user_by_league.get(lid) for lid in bounded_lids) and all(
                (lid, week, rid) in matchups
                and matchups[(lid, week, rid)].get("team_points") is not None
                for lid in bounded_lids
                for week in range(1, (supporting.get("playoff_week_start_by_league") or {}).get(lid, 15))
                for rid in entry.roster_to_user_by_league.get(lid, {}))
            if not complete:
                snapshot["reason"] = "Historical game results are incomplete. Refresh league data."
                continue
            bounded = {**effective, "league_season_by_id": bounded_lids,
                       "owners": {uid: entry.owners[uid] for uid in owners},
                       "matchups": {key: val for key, val in (effective.get("matchups") or {}).items()
                                    if key[0] in bounded_lids}}
            _, _, _, records = compute_rating_signals(bounded, {})
            all_play = {season: all_play_win_pct(
                bounded["matchups"], league_id=lid,
                playoff_week_start=(supporting.get("playoff_week_start_by_league") or {}).get(lid, 15),
                roster_to_user=entry.roster_to_user_by_league.get(lid, {}))
                for lid, season in bounded_lids.items()}
            int_records = {int(s): rows for s, rows in records.items()}
            anchor = latest_played_season(int_records)
            if anchor is None or any(all_play.get(year, {}).get(uid) is None for uid in owners):
                snapshot["reason"] = "Historical game results are incomplete. Refresh league data."
                continue
            snapshot.update(season_records=records, results_source={"all_play_by_season": all_play},
                            outcome_signals=results_signals(all_play_by_season=all_play,
                                season_records=int_records, owners=owners, latest_played_season=anchor),
                            outlook_signals={}, roster_ranks={})
            if fmt != "redraft":
                if asset_store is None or len(lids) != 1:
                    snapshot["reason"] = "Verified historical roster, pick ownership, and asset prices are missing."
                    continue
                through_week = max((key[1] for key in bounded["matchups"] if key[0] in lids), default=0)
                assets, reason = asset_store.load(
                    season=year, season_league_id=lids[0], owners=owners, format=fmt,
                    identity_version=entry.owner_identity_version, through_week=through_week,
                    cutoff_date=(supporting.get("season_end_dates") or {}).get(lids[0]))
                if assets is None:
                    snapshot["reason"] = reason
                    continue
                if (assets.validation is not None and assets.validation.result_inputs_sha256
                        != historical_results_digest(snapshot)):
                    snapshot["reason"] = "Historical results changed since validation. Rerun the historical backfill preview."
                    continue
                signals, ranks = assets.signals()
                snapshot.update(outlook_signals=signals, roster_ranks=ranks,
                                as_of=assets.as_of.isoformat(), asset_source=assets.model_dump(mode="json"))
        outcomes = snapshot.get("outcome_signals") or {}
        assets = snapshot.get("outlook_signals") or {}
        if not _complete_signals(owners, outcomes, assets, fmt):
            snapshot["reason"] = "Rating inputs are incomplete. Refresh league data."
            continue
        snapshot["status"] = "provisional" if (snapshot.get("results_coverage") or
            (snapshot.get("asset_source") or {}).get("pick_valuation") or
            (current and (entry.current_rating_verification.get("owner_coverage") or
                          entry.current_rating_verification.get("pick_valuation")))) else "ready"
    return out
