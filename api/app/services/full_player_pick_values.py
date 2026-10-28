"""Public-data estimates for full-player keeper drafts, never rookie quotes.

Estimate the value of an unused round entitlement from the league's observed
non-keeper selections. Pool adjacent rounds when sample noise makes a later
round more valuable. The weighted decreasing fit preserves total sample value.
Future keeper elections and draft order are unknown: use generic round values,
flat across the existing three-year asset horizon, and mark ratings provisional.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from math import isfinite

from app.services.historical_backfill import IDP, digest
from sleeper_dynasty.models.player import KTCValue

VERSION = "full-player-observed-rounds-v1"
EXCLUDED_POSITIONS = {"K", "DEF"}
log = logging.getLogger(__name__)


def with_full_player_pick_values(league, drafts, picks_by_draft, supporting, *, prices_as_of=None, exclude_idp=False):
    """Return an isolated rating bundle; trade grading retains its own tables."""
    if getattr(league, "format", None) != "keeper" or (getattr(league, "format_evidence", None) or {}).get("future_picks_retained") is False:
        return supporting
    result = {**supporting, "pick_value_table": {}, "pick_value_table_tiered": {}}
    receipt = {"version": VERSION, "status": "unavailable", "league_id": league.league_id,
               "season": league.season, "prices_as_of": prices_as_of or date.today().isoformat()}
    result["full_player_pick_valuation"] = receipt
    excluded_positions = EXCLUDED_POSITIONS | (IDP if exclude_idp else set())
    if exclude_idp:
        receipt['excluded_positions'] = sorted(excluded_positions)
    try:
        candidates = [d for d in drafts if d.get("league_id") == league.league_id
                      and str(d.get("season")) == str(league.season)]
        if len(candidates) != 1:
            raise ValueError("A single current-season full-player draft is required.")
        draft = candidates[0]
        settings = draft.get("settings") or {}
        teams, rounds = settings.get("teams"), settings.get("rounds")
        if (draft.get("status") != "complete" or draft.get("type") not in {"snake", "linear"}
                or settings.get("player_type") != 0 or type(rounds) is not int or rounds < 1
                or type(teams) is not int or teams != league.total_rosters):
            raise ValueError("Completed full-player draft settings are unverified or unsupported.")
        picks = picks_by_draft.get(draft["draft_id"]) or []
        if (len(picks) != teams * rounds
                or {p.get("pick_no") for p in picks} != set(range(1, teams * rounds + 1))
                or len({p.get("player_id") for p in picks}) != len(picks)):
            raise ValueError("Full-player draft selections are incomplete or duplicated.")
        samples = {r: [] for r in range(1, rounds + 1)}
        evidence = []
        for pick in sorted(picks, key=lambda p: p["pick_no"]):
            r, pid = pick.get("round"), pick.get("player_id")
            if (type(r) is not int or r != (pick["pick_no"] - 1) // teams + 1
                    or not pid or "is_keeper" not in pick
                    or (pick["is_keeper"] is not None and type(pick["is_keeper"]) is not bool)):
                raise ValueError("Draft round or keeper flags are unverified.")
            row = {"pick_no": pick["pick_no"], "round": r, "player_id": pid,
                   "is_keeper": pick["is_keeper"]}
            if not pick["is_keeper"]:
                position = (supporting.get("positions") or {}).get(pid)
                value = getattr((supporting.get("ktc_by_player_id") or {}).get(pid), "superflex_value", None)
                if position in excluded_positions:
                    value = 0.0  # Explicit asset policy, not missing-price imputation.
                elif (position not in {"QB", "RB", "WR", "TE"}
                      or not isinstance(value, (float, int)) or not isfinite(value) or value < 0):
                    raise ValueError(f"Drafted offensive player {pid} has no verified current price or position.")
                row.update(position=position, value=value,
                           source=(supporting.get("player_value_sources") or {}).get(pid, "current-player-values")
                           if position not in excluded_positions else "excluded-position")
                samples[r].append(float(value))
            evidence.append(row)
        if any(not values or sum(values) <= 0 for values in samples.values()):
            raise ValueError("Every round needs priced non-keeper selections with positive offensive value.")
        # Weighted pool-adjacent-violators: no fabricated early/mid/late tiers.
        blocks = []
        for r, values in samples.items():
            blocks.append(([r], sum(values), len(values)))
            while len(blocks) > 1 and blocks[-2][1] / blocks[-2][2] < blocks[-1][1] / blocks[-1][2]:
                b, a = blocks.pop(), blocks.pop()
                blocks.append((a[0] + b[0], a[1] + b[1], a[2] + b[2]))
        fitted = {r: total / count for rs, total, count in blocks for r in rs}
        round_rows = [{"round": r, "sample_count": len(values), "observed_mean": sum(values) / len(values),
                       "value": fitted[r]} for r, values in samples.items()]
        receipt.update(status="ready", draft_id=draft["draft_id"], teams=teams,
                       draft_rounds=rounds, keeper_count=sum(bool(p["is_keeper"]) for p in picks),
                       rounds=round_rows, selections=evidence,
                       draft_sha256=digest({"draft": draft, "picks": picks}))
        result["pick_value_table"] = {
            (year, r): KTCValue(name=f"Full-player round {r}", normalized_name=f"full-player-round-{r}",
                               position="RDP", superflex_value=fitted[r])
            for year in range(league.season + 1, league.season + 4) for r in samples}
        log.info("Full-player keeper pick estimate ready: league=%s season=%s rounds=%s selections=%s",
                 league.league_id, league.season, rounds, len(evidence))
    except (KeyError, TypeError, ValueError) as exc:
        receipt["reason"] = f"Full-player pick prices unavailable: {exc} Refresh verified draft and player data."
        log.warning("Full-player keeper pick estimate unavailable: league=%s reason=%s", league.league_id, exc)
    return result


def _binding(entry):
    payload = {"league_id": entry.league_id, "seasons": entry.league_season_by_id,
                   "identity": entry.owner_identity_version, "format": entry.capabilities.get("format"),
                   "membership": {str(k): v for k, v in entry.roster_to_user_by_league.get(entry.league_id, {}).items()},
                   "assets": entry.outlook_signals, "valuation": entry.current_rating_verification.get("pick_valuation")}
    # Vacant rosters retain assets in shared denominators under a None owner.
    # Hash the persisted JSON representation (None key -> "null") so both
    # pre-write and post-read verification use identical key types and ordering.
    return digest(json.loads(json.dumps(payload)))


def bind_pick_valuation(entry):
    if entry.current_rating_verification.get("pick_valuation"):
        entry.current_rating_verification["pick_valuation_binding"] = _binding(entry)


def current_pick_valuation(entry):
    audit = entry.current_rating_verification
    receipt = audit.get("pick_valuation") or {}
    if (receipt.get("version") == VERSION and receipt.get("status") == "ready"
            and receipt.get("league_id") == entry.league_id
            and receipt.get("season") == entry.league_season_by_id.get(entry.league_id)
            and audit.get("pick_valuation_binding") == _binding(entry)):
        return receipt
    return None


def valuation_note(receipt):
    return (f"Estimated full-player keeper picks: {receipt['season']} completed draft, "
            f"{receipt['draft_rounds']} rounds, KeepTradeCut/FantasyCalc player prices as of {receipt['prices_as_of']}. "
            "Keeper selections are excluded; kickers and defenses carry no asset value. "
            "Round averages are smoothed and projected unchanged across the next three drafts. "
            "These are estimates of unused pick entitlements, not market quotes or predictions of future keepers.")
