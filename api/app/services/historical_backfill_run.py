"""Prepare a private historical ranking preview; never writes a live cache.

python -m app.services.historical_backfill_run --help
"""

from __future__ import annotations

import argparse
import itertools
import json
import logging
import math
from copy import deepcopy
from dataclasses import fields, replace
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from statistics import median

from app.services.chain_cache import ChainCacheEntry
from app.services.franchise_redesign import live_ratings
from app.services.grader_io import _assemble_played_matchups
from app.services.historical_backfill import (
    EvidenceClient,
    digest,
    reconcile_rosters,
    reconstruct_picks,
    value_roster,
)
from app.services.historical_rating_assets import HistoricalRatingAssets
from app.services.season_ratings import (
    build_season_rating_inputs,
    historical_results_digest,
)
from sleeper_dynasty.api.nfl_schedule import parse_scoreboard
from sleeper_dynasty.engine.gm_rating import rating_to_letter
from sleeper_dynasty.engine.playoff_phase import weeks_for_round
from sleeper_dynasty.engine.standings import standings_as_of
from sleeper_dynasty.util.atomic import write_json_atomic

SLEEPER = "https://api.sleeper.app/v1"
STATS_GUY = "https://api.statsguyfantasy.com/api/v1"


def validate_brackets(
    winners,
    losers,
    roster_ids,
    playoff_teams,
    *,
    matchups,
    league_id,
    playoff_start,
    final_week,
    toilet_bowl=False,
    playoff_round_type=0,
    inactive_rosters=(),
):
    """Require complete title-path and placement evidence, not just scored rows."""
    if not 2 <= playoff_teams <= len(roster_ids):
        raise ValueError("Unsupported playoff team count.")
    if playoff_round_type not in (0, 1, 2):
        raise ValueError("Unknown playoff round timing.")
    inactive = set(inactive_rosters)
    if not inactive <= set(roster_ids):
        raise ValueError("Unknown inactive postseason roster.")
    populations, round_ends = [], []
    for games, size, low_wins in (
        (winners, playoff_teams, False),
        (losers, len(roster_ids) - playoff_teams - len(inactive), toilet_bowl),
    ):
        if size == 0 and not games:
            populations.append(set())
            continue
        participants = {g.get(k) for g in games for k in ("w", "l")}
        title_games = [g for g in games if g.get("p") in (None, 1)]
        placements = [g for g in games if g.get("p") is not None]
        placed = [g[k] for g in placements for k in ("w", "l")]
        if (
            not games
            or len({g.get("m") for g in games}) != len(games)
            or any(g.get("w") == g.get("l") for g in games)
            or None in participants
            or not participants <= set(roster_ids)
            or len(participants) != size
            or len(title_games) != size - 1
            or sum(g.get("p") == 1 for g in games) != 1
            or len(placed) != size
            or set(placed) != participants
            or {g["p"] for g in placements} != set(range(1, size, 2))
        ):
            raise ValueError(
                "Completed postseason bracket evidence is missing, truncated, or inconsistent."
            )
        populations.append(participants)
        total_rounds = max(int(g["r"]) for g in games)
        for game in games:
            weeks = weeks_for_round(
                int(game["r"]), playoff_start, playoff_round_type, total_rounds
            )
            if min(weeks) < playoff_start or max(weeks) > 18:
                raise ValueError("Invalid postseason round timing.")
            round_ends.append(max(weeks))
            totals = [0.0, 0.0]
            for week in weeks:
                win = matchups.get((league_id, week, game["w"]))
                loss = matchups.get((league_id, week, game["l"]))
                if (
                    not win
                    or not loss
                    or win["opponent_roster_id"] != game["l"]
                    or loss["opponent_roster_id"] != game["w"]
                    or any(
                        not isinstance(row.get("team_points"), (int, float))
                        or not math.isfinite(row["team_points"])
                        for row in (win, loss)
                    )
                ):
                    raise ValueError(
                        f"Postseason bracket disagrees with played matchups: league={league_id} "
                        f"week={week} game={game}; missing score or opponent evidence."
                    )
                totals[0] += win["team_points"]
                totals[1] += loss["team_points"]
            if totals[0] > totals[1] if low_wins else totals[0] < totals[1]:
                raise ValueError(
                    f"Postseason bracket disagrees with played matchups: league={league_id} "
                    f"weeks={weeks} game={game}, winner={totals[0]}, loser={totals[1]}."
                )
    if max(round_ends) != final_week:
        raise ValueError("Postseason bracket does not reach the final played week.")
    if (
        populations[0] & populations[1]
        or set.union(*populations) & inactive
        or set.union(*populations, inactive) != set(roster_ids)
    ):
        raise ValueError("Postseason brackets do not cover every roster exactly once.")


def verified_idle_rosters(weekly, rows, winners, losers, settings, start, final):
    """Prove the middle two idle teams in Sleeper's 10-team, four-team toilet format."""
    population = {r.roster_id for r in rows}
    win_ids = {g.get(k) for g in winners for k in ("w", "l")}
    lose_ids = {g.get(k) for g in losers for k in ("w", "l")}
    absent = population - win_ids - lose_ids
    if not absent:
        return set()
    ranked = sorted(rows, key=lambda r: (-(r.wins + r.ties / 2), -r.points_for))
    if (
        len(population) != 10
        or settings.get("playoff_teams") != 4
        or settings.get("playoff_type") != 0
        or settings.get("playoff_round_type") != 2
        or win_ids != {r.roster_id for r in ranked[:4]}
        or lose_ids != {r.roster_id for r in ranked[-4:]}
        or absent != {r.roster_id for r in ranked[4:6]}
    ):
        raise ValueError(
            "Missing postseason participants lack verified inactive seed evidence."
        )
    for week in range(start, final + 1):
        source = weekly.get(week, [])
        indexed = {r["roster_id"]: r for r in source}
        if (
            set(indexed) != population
            or len(source) != len(population)
            or any(
                "matchup_id" not in indexed[r] or indexed[r]["matchup_id"] is not None
                for r in absent
            )
        ):
            raise ValueError(
                "Missing postseason participants lack explicit inactive weekly evidence."
            )
    return absent


def historical_standings(
    matchups, *, league_id, playoff_start, roster_to_user, median_game=False
):
    """Reconstruct H2H plus an optional median result; PF/PA count H2H only."""
    rows = standings_as_of(
        matchups,
        league_id=league_id,
        through_week=playoff_start - 1,
        playoff_week_start=playoff_start,
        roster_to_user=roster_to_user,
    )
    for week in range(1, playoff_start):
        weekly = {
            rid: row
            for (lid, wk, rid), row in matchups.items()
            if lid == league_id and wk == week
        }
        if set(weekly) != set(roster_to_user) or any(
            not isinstance(row.get(key), (int, float)) or not math.isfinite(row[key])
            for row in weekly.values()
            for key in ("team_points", "opponent_points")
        ):
            raise ValueError(
                "Regular-season matchup evidence is incomplete or invalid."
            )
        scores = {rid: row["team_points"] for rid, row in weekly.items()}
        if median_game:
            midpoint = median(scores.values())
            for row in rows:
                value = scores[row.roster_id]
                row.wins += int(value > midpoint)
                row.losses += int(value < midpoint)
                row.ties += int(value == midpoint)
    return rows


def read_entry(path):
    raw = json.loads(path.read_text())
    raw["roster_to_user_by_league"] = {
        lid: {int(r): uid for r, uid in mapping.items()}
        for lid, mapping in raw["roster_to_user_by_league"].items()
    }
    return ChainCacheEntry(
        **{
            k: v
            for k, v in raw.items()
            if k in {f.name for f in fields(ChainCacheEntry)}
        }
    )


def collect(
    client, entry, season, *, results_only=False, approved_points_resolutions=()
):
    approvals = {}
    for item in approved_points_resolutions:
        key = (item["season"], item["roster_id"], item["field"])
        if (
            key in approvals
            or item["field"] not in {"points_for", "points_against"}
            or item["season"] != season
            or any(
                not isinstance(item.get(k), (int, float)) or not math.isfinite(item[k])
                for k in ("provider", "recomputed")
            )
        ):
            raise ValueError(
                "Points resolutions must be unique exact selected-season PF/PA evidence."
            )
        approvals[key] = item
    used_approvals = set()
    lids = {lid: y for lid, y in entry.league_season_by_id.items() if y <= season}
    targets = [lid for lid, y in lids.items() if y == season]
    if len(targets) != 1:
        raise ValueError("Expected exactly one league for selected season.")
    target = targets[0]
    supporting = {
        k: {}
        for k in (
            "matchups",
            "playoff_week_start_by_league",
            "winners_bracket_by_league",
            "losers_bracket_by_league",
            "num_playoff_teams_by_league",
            "roster_records_by_league",
        )
    }
    supporting.update(
        league_season_by_id=lids,
        owners=entry.owners,
        roster_to_user_by_league=entry.roster_to_user_by_league,
        evidence_discrepancies=[],
    )
    bundles, transactions = {}, []
    for lid, year in sorted(lids.items(), key=lambda x: x[1]):
        base = f"{SLEEPER}/league/{lid}"
        league = client.get(base)
        settings = league["settings"]
        if (
            int(league["season"]) != year
            or league["status"] != "complete"
            or settings.get("type") not in (0, 1, 2)
            or settings.get("league_average_match", 0) not in (0, 1)
            or settings.get("playoff_round_type", 0) not in (0, 1, 2)
            or settings.get("playoff_type", 1) not in (0, 1)
        ):
            raise ValueError(
                "Unsupported or incomplete Sleeper season settings; verify format, median games, and playoff timing."
            )
        previous = league.get("previous_league_id")
        if previous and previous != "0" and previous not in lids:
            raise ValueError(
                "League chain is truncated; inherited pick ownership cannot be proven."
            )
        rosters = client.get(base + "/rosters")
        expected = entry.roster_to_user_by_league[lid]
        observed = {
            r["roster_id"]: entry.owner_aliases.get(r["owner_id"], r["owner_id"])
            for r in rosters
        }
        if observed != expected:
            raise ValueError(
                "Historical owner membership changed or is unmapped; review canonical identities."
            )
        weekly = {week: client.get(base + f"/matchups/{week}") for week in range(1, 19)}
        matchups = _assemble_played_matchups(weekly, lid)
        pws = int(settings["playoff_week_start"])
        final_week = max((key[1] for key in matchups), default=0)
        if final_week != settings.get("last_scored_leg") or not pws <= final_week <= 18:
            raise ValueError("Final played week conflicts with league settings.")
        for week in range(1, pws):
            if {r for lg, w, r in matchups if w == week} != set(expected):
                raise ValueError("Regular-season matchup evidence is incomplete.")
        rows = historical_standings(
            matchups,
            league_id=lid,
            playoff_start=pws,
            roster_to_user=expected,
            median_game=bool(settings.get("league_average_match", 0)),
        )
        records = {}
        for row in rows:
            source = next(
                r["settings"] for r in rosters if r["roster_id"] == row.roster_id
            )
            record = {k: source[k] for k in ("wins", "losses", "ties")}
            record.update(
                points_for=source.get("fpts", 0) + source.get("fpts_decimal", 0) / 100,
                points_against=source.get("fpts_against", 0)
                + source.get("fpts_against_decimal", 0) / 100,
            )
            if any(abs(getattr(row, k) - v) > 0.011 for k, v in record.items()):
                differences = {
                    k: {"recomputed": getattr(row, k), "provider": v}
                    for k, v in record.items()
                    if abs(getattr(row, k) - v) > 0.011
                }
                unresolved = dict(differences)
                for field, values in differences.items():
                    key = (year, row.roster_id, field)
                    approval = approvals.get(key)
                    if approval is None:
                        continue
                    if any(
                        abs(approval[k] - values[k]) > 1e-7
                        for k in ("provider", "recomputed")
                    ):
                        raise ValueError(
                            "Approved points resolution does not match observed evidence."
                        )
                    used_approvals.add(key)
                    record[field] = values["recomputed"]
                    unresolved.pop(field)
                    supporting["evidence_discrepancies"].append(
                        {
                            "season": year,
                            "roster_id": row.roster_id,
                            "differences": {field: values},
                            "resolution": "approved_weekly_scores",
                        }
                    )
                if unresolved and (
                    year == season
                    or any(k in unresolved for k in ("wins", "losses", "ties"))
                ):
                    raise ValueError(
                        f"Recomputed results disagree with provider records: {year}, roster {row.roster_id}: {differences}."
                    )
                # Prior seasons' aggregate points do not enter the rating. The
                # weekly scores establish all-play; provider W/L establishes
                # the record. Preserve their disagreement instead of repairing
                # a game with an unknowable correction.
                if unresolved:
                    supporting["evidence_discrepancies"].append(
                        {
                            "season": year,
                            "roster_id": row.roster_id,
                            "differences": unresolved,
                        }
                    )
            records[row.roster_id] = record
        wb = client.get(base + "/winners_bracket")
        lb = client.get(base + "/losers_bracket")
        inactive = verified_idle_rosters(
            weekly, rows, wb, lb, settings, pws, final_week
        )
        supporting.setdefault("inactive_postseason_rosters", {})[lid] = sorted(inactive)
        validate_brackets(
            wb,
            lb,
            list(expected),
            settings["playoff_teams"],
            matchups=matchups,
            league_id=lid,
            playoff_start=pws,
            final_week=final_week,
            toilet_bowl=settings.get("playoff_type") == 0,
            playoff_round_type=settings.get("playoff_round_type", 0),
            inactive_rosters=inactive,
        )
        season_tx = [
            t for week in range(19) for t in client.get(base + f"/transactions/{week}")
        ]
        transactions.extend(season_tx)
        supporting["matchups"].update(matchups)
        for key, value in (
            ("playoff_week_start", pws),
            ("winners_bracket", wb),
            ("losers_bracket", lb),
            ("num_playoff_teams", settings["playoff_teams"]),
            ("roster_records", records),
        ):
            supporting[key + "_by_league"][lid] = value
        bundles[lid] = (league, rosters, weekly, season_tx, final_week)
    if used_approvals != set(approvals):
        raise ValueError(
            "Approved points resolutions contain unused or no-longer-matching evidence."
        )
    if results_only:
        return None, None, supporting
    league, rosters, weekly, season_tx, final_week = bundles[target]
    if league["settings"]["type"] != 2:
        raise ValueError(
            "Keeper/redraft assets require separately verified retention, pick inventory, and compatible prices; dynasty rookie-pick prices cannot be substituted."
        )
    schedule = client.get(
        f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates={season}&seasontype=2&week={final_week}&limit=1000"
    )
    if (
        int(schedule["season"]["year"]) != season
        or int(schedule["week"]["number"]) != final_week
    ):
        raise ValueError("Schedule season/week mismatch.")
    games = parse_scoreboard(schedule, strict=True)
    if not games or any(
        not g["kickoff"]
        or not (
            g["completed"]
            or (g["status"] == "STATUS_CANCELED" and g["state"] == "post")
        )
        for g in games
    ):
        raise ValueError("Final NFL week is incomplete.")
    cutoff = max(
        datetime.fromisoformat(g["kickoff"]) for g in games
    ).date() + timedelta(days=1)
    cutoff_ms = int(datetime.combine(cutoff, time(), UTC).timestamp() * 1000)
    holders = reconcile_rosters(rosters, weekly[final_week], season_tx, cutoff_ms)
    mapping = entry.roster_to_user_by_league[target]
    holders = {pid: mapping[rid] for pid, rid in holders.items()}
    rounds = int(league["settings"]["draft_rounds"])
    if not 1 <= rounds <= 10 or league.get("scoring_settings", {}).get(
        "bonus_rec_te", 0
    ):
        raise ValueError(
            "Unsupported draft rounds or TE premium; do not substitute standard values."
        )
    picks = reconstruct_picks(list(mapping), season, rounds, transactions, cutoff_ms)
    current_picks = reconstruct_picks(
        list(mapping), season, rounds, transactions, 2**63
    )
    endpoint = client.get(f"{SLEEPER}/league/{target}/traded_picks")
    endpoint_picks = {key: key[2] for key in picks}
    for p in endpoint:
        key = (int(p["season"]), p["round"], p["roster_id"])
        if key in endpoint_picks:
            endpoint_picks[key] = p["owner_id"]
    if endpoint_picks != current_picks:
        raise ValueError("Full pick ledger does not reconcile with provider holdings.")
    positions = league["roster_positions"]
    format = (
        "sf_dynasty"
        if "SUPER_FLEX" in positions or positions.count("QB") > 1
        else "non_sf_dynasty"
    )
    price_date = (cutoff - timedelta(days=1)).isoformat()
    board = client.get(
        f"{STATS_GUY}/rankings?format={format}&tep=std&date={price_date}&limit=1000"
    )
    players = client.get(f"{SLEEPER}/players/nfl")
    priced, policy = value_roster(players, holders, board, cutoff, format)
    pick_ids = [
        f"pick:{y}:{r}"
        for y in range(season + 1, season + 4)
        for r in range(1, rounds + 1)
    ]
    pick_reply = client.request(
        "POST",
        STATS_GUY + "/trades/evaluate",
        {
            "format": format,
            "tep": "std",
            "date": board["asOf"],
            "sideA": pick_ids,
            "sideB": [str(board["rankings"][0]["id"])],
        },
    )
    values = pick_reply["sideA"]["assets"]
    if (
        len(values) != len(pick_ids)
        or {p["id"] for p in values} != set(pick_ids)
        or any(
            p.get("found") is not True or p.get("asOf") != board["asOf"] for p in values
        )
    ):
        raise ValueError("Incomplete or wrong-date historical pick prices.")
    pick_prices = {p["id"]: p["value"] for p in values}
    supporting["season_end_dates"] = {target: cutoff.isoformat()}
    raw = {
        "version": 1,
        "season": season,
        "season_league_id": target,
        "format": "dynasty",
        "as_of": cutoff.isoformat(),
        "through_week": final_week,
        "prices_as_of": board["asOf"],
        "identity_version": entry.owner_identity_version,
        "verified_by": "historical-backfill-v1",
        "verified_at": date.today().isoformat(),
        "roster_source": "Sleeper final-week roster + transaction reversal",
        "picks_source": "Sleeper full-chain pick ledger + endpoint reconciliation",
        "prices_source": "Stats Guy Fantasy dated API estimates (generic year/round picks)",
        "owners": sorted(mapping.values()),
        "draft_rounds": rounds,
        "pick_horizon": 3,
        "players": priced,
        "picks": [
            {
                "season": y,
                "round": r,
                "original_owner_id": mapping[original],
                "owner_id": mapping[owner],
                "value": pick_prices[f"pick:{y}:{r}"],
            }
            for (y, r, original), owner in sorted(picks.items())
        ],
    }
    # Record only receipts used by this run, including both requests and responses.
    policy["evidence_sha256"] = digest(client.used)
    return raw, policy, supporting


def rank_preview(entry, supporting, raw, *, include_results=False):
    assets = HistoricalRatingAssets.model_validate(raw)

    class PreviewStore:
        def load(self, **kwargs):
            if kwargs["season"] != assets.season:
                return None, "Outside preview season"
            if (
                kwargs["season_league_id"] != assets.season_league_id
                or set(kwargs["owners"]) != set(assets.owners)
                or kwargs["identity_version"] != assets.identity_version
                or kwargs["through_week"] != assets.through_week
                or kwargs["cutoff_date"] != assets.as_of.isoformat()
            ):
                raise ValueError("Preview identity or cutoff mismatch.")
            return assets, None

    snapshots = build_season_rating_inputs(
        entry, supporting, asset_store=PreviewStore()
    )
    preview = replace(entry, season_rating_inputs=snapshots)
    ratings = live_ratings(preview, year=assets.season)
    if set(ratings) != set(assets.owners):
        raise ValueError(
            f"Historical rating pipeline rejected preview: {snapshots[str(assets.season)].get('reason')}"
        )
    rows = {
        uid: {
            "rating": row["rating"],
            "grade": rating_to_letter(row["rating"]),
            "rank": 1
            + sum(other["rating"] > row["rating"] for other in ratings.values()),
            "pillars": row["pillars"],
        }
        for uid, row in ratings.items()
    }
    if include_results:
        return rows, historical_results_digest(snapshots[str(assets.season)])
    return rows


def validate_sensitivity(entry, supporting, raw, policy):
    baseline = rank_preview(entry, supporting, raw)
    bounds = policy["unranked_upper_bounds"]
    if len(bounds) > 8:
        raise ValueError(
            "Too many unranked players for exhaustive sensitivity validation."
        )
    scenarios, changes = [], []
    for flags in itertools.product((False, True), repeat=len(bounds)):
        overrides = {
            pid: bounds[pid] if high else 0 for pid, high in zip(bounds, flags)
        }
        alternate = deepcopy(raw)
        for player in alternate["players"]:
            if player["player_id"] in overrides:
                player["value"] = overrides[player["player_id"]]
        ratings = rank_preview(entry, supporting, alternate)
        changed = [
            uid
            for uid in baseline
            if any(ratings[uid][key] != baseline[uid][key] for key in ("rank", "grade"))
        ]
        changes.extend(changed)
        scenarios.append(
            {
                "overrides": overrides,
                "changed_owners": changed,
                "max_rating_delta": max(
                    abs(ratings[u]["rating"] - baseline[u]["rating"]) for u in baseline
                ),
            }
        )
    return baseline, scenarios, not changes


def prepare(entry, client, season, output):
    raw, policy, supporting = collect(client, entry, season)
    raw = HistoricalRatingAssets.model_validate(raw).model_dump(mode="json")
    ratings, scenarios, stable = validate_sensitivity(entry, supporting, raw, policy)
    output.mkdir(parents=True, exist_ok=True)
    if not stable and (output / "manifest.json").exists():
        raise ValueError(
            "Blocked preview cannot replace a validated output. Use a new output directory."
        )
    report = {
        "season": season,
        "as_of": raw["as_of"],
        "prices_as_of": raw["prices_as_of"],
        "status": "validated" if stable else "blocked",
        "policy": policy,
        "scenarios": scenarios,
        "rankings": ratings,
        "owners": {uid: entry.owners[uid] for uid in ratings},
        "evidence": client.used,
        "chain_identity_version": entry.owner_identity_version,
        "prior_points_discrepancies": supporting["evidence_discrepancies"],
        "limitations": "Provider-dated estimates; not independently proven contemporaneous snapshots. "
        "Zero unranked floor; K/DEF excluded from assets. Results include all scoring.",
    }
    report["coverage_by_owner"] = {
        uid: {
            "eligible": sum(p["owner_id"] == uid for p in raw["players"]),
            "priced": sum(
                p["owner_id"] == uid and p["pricing"] == "provider"
                for p in raw["players"]
            ),
            "unranked": [
                p["player_id"]
                for p in raw["players"]
                if p["owner_id"] == uid and p["pricing"] == "unranked_floor"
            ],
            "excluded": [p for p in policy["excluded"] if p["owner_id"] == uid],
        }
        for uid in raw["owners"]
    }
    if stable:
        raw["valuation_policy"] = policy
        raw["validation"] = {
            "manifest_sha256": digest(
                {k: v for k, v in raw.items() if k != "validation"}
            ),
            "result_inputs_sha256": rank_preview(
                entry,
                supporting,
                {**raw, "valuation_policy": None},
                include_results=True,
            )[1],
            "stable": True,
            "scenarios": len(scenarios),
        }
        raw = HistoricalRatingAssets.model_validate(raw).model_dump(mode="json")
        report["manifest_sha256"] = raw["validation"]["manifest_sha256"]
        path = output / "manifest.json"
        if path.exists() and json.loads(path.read_text()) != raw:
            raise ValueError(
                "Output already contains a different manifest; use a new output directory."
            )
        write_json_atomic(path, raw)
    write_json_atomic(output / "preview.json", report)
    if not stable:
        raise ValueError(
            "Unranked-player sensitivity changes a rank or grade. Preview saved; publication blocked."
        )
    return report


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--chain",
        type=Path,
        required=True,
        help="Read-only exported canonical ChainCacheEntry",
    )
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Private output directory; never the production cache",
    )
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    try:
        report = prepare(
            read_entry(args.chain),
            EvidenceClient(args.evidence_dir, offline=args.offline),
            args.season,
            args.output,
        )
        print(
            f"Validated {args.season}: {len(report['rankings'])} owners, {len(report['scenarios'])} sensitivity scenarios. "
            f"Preview: {args.output / 'preview.json'}. Nothing published."
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(
            2,
            f"Historical backfill failed: {exc}\nReview evidence, then resume using the same receipts.\n",
        )


if __name__ == "__main__":
    main()
