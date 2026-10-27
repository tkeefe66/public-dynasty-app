"""Receipt-backed, offline-replayable preparation of historical dynasty assets.

Preparation never publishes. Missing evidence fails explicitly; absent offensive
prices are a disclosed policy floor, never a purported provider observation.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from collections import Counter
from datetime import date
from pathlib import Path

import httpx

from sleeper_dynasty.util.atomic import write_json_atomic

log = logging.getLogger(__name__)
POLICY_VERSION = "stats-guy-v1"
SOURCE_URL = "https://statsguyfantasy.com"
OFFENSE = {"QB", "RB", "WR", "TE"}
IDP = {"DL", "DE", "DT", "NT", "LB", "ILB", "OLB", "DB", "CB", "S", "SS", "FS"}


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, allow_nan=False, separators=(",", ":")
        ).encode()
    ).hexdigest()


class EvidenceClient:
    def __init__(self, directory: Path, *, http=None, offline=False):
        self.directory = Path(directory)
        self.http = http
        self.offline = offline
        self.used = {}

    def get(self, url):
        return self.request("GET", url)

    def request(self, method, url, body=None):
        request = {"method": method, "url": url, "body": body}
        path = self.directory / f"{digest(request)}.json"
        if path.exists():
            receipt = json.loads(path.read_text())
            if (
                receipt["request"] != request
                or digest(receipt["response"]) != receipt["response_hash"]
            ):
                raise ValueError(
                    f"Evidence hash mismatch: {path}. Restore original receipt."
                )
            self.used[path.name] = digest(receipt)
            return receipt["response"]
        if self.offline:
            raise ValueError(f"Offline evidence missing: {method} {url}")
        log.info("historical evidence request method=%s url=%s", method, url)
        try:
            if self.http is None:
                with httpx.Client(timeout=45) as client:
                    response = client.request(method, url, json=body)
            else:
                response = self.http.request(method, url, json=body)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise ValueError(
                f"Evidence request failed HTTP {exc.response.status_code}: {url}; "
                f"Retry-After={exc.response.headers.get('Retry-After', 'not supplied')}. "
                "Check access or resume after the cooldown; saved receipts are reusable."
            ) from exc
        except (httpx.RequestError, ValueError) as exc:
            raise ValueError(
                f"Evidence request failed: {url}: {exc}. Resume to reuse saved receipts."
            ) from exc
        self.directory.mkdir(parents=True, exist_ok=True)
        receipt = {
            "request": request,
            "response": payload,
            "response_hash": digest(payload),
        }
        write_json_atomic(path, receipt)
        self.used[path.name] = digest(receipt)
        return payload


def value_roster(
    players, holders, board, cutoff: date, format: str, *, exclude_idp=False
):
    if (
        board.get("format") != format
        or board.get("tep") != "std"
        or not 1 <= (cutoff - date.fromisoformat(board["asOf"])).days <= 7
        or board.get("offset", 0) != 0
        or len(board["rankings"]) != board["total"]
    ):
        raise ValueError("Incomplete, stale, future, or wrong-format historical board.")
    lookup = {str(p["id"]): p for p in board["rankings"]}
    if len(lookup) != len(board["rankings"]):
        raise ValueError("Duplicate player IDs in historical board.")
    if any(
        not math.isfinite(float(p["value"])) or float(p["value"]) < 0
        for p in lookup.values()
    ):
        raise ValueError("Invalid historical price.")
    rows, excluded, upper = [], [], {}
    counts, missing = Counter(), Counter()
    for pid, owner in sorted(holders.items()):
        player = players.get(pid, {})
        eligible = (
            set(player.get("fantasy_positions") or [player.get("position")]) & OFFENSE
        )
        if not eligible:
            position = player.get("position")
            if position not in ({"K", "DEF"} | (IDP if exclude_idp else set())):
                raise ValueError(
                    f"Unknown/unsupported position for {pid}; review eligibility."
                )
            excluded.append({"player_id": pid, "owner_id": owner, "position": position})
            continue
        priced = lookup.get(pid)
        position = priced["position"] if priced else min(eligible)
        if position not in eligible:
            raise ValueError(f"Position mismatch for {pid}.")
        birthday = date.fromisoformat(player["birth_date"])
        if not 15 <= (cutoff - birthday).days / 365.25 <= 60:
            raise ValueError(f"Invalid historical birth date for {pid}.")
        counts[owner] += 1
        if priced is None:
            missing[owner] += 1
            floor_candidates = [
                float(p["value"])
                for p in lookup.values()
                if p["position"] == position and float(p["value"]) > 0
            ]
            if not floor_candidates:
                raise ValueError(f"No {position} price floor available.")
            upper[pid] = min(floor_candidates)
        rows.append(
            {
                "player_id": pid,
                "owner_id": owner,
                "birth_date": birthday.isoformat(),
                "position": position,
                "value": float(priced["value"]) if priced else 0,
                "pricing": "provider" if priced else "unranked_floor",
            }
        )
    if (
        set(counts) != set(holders.values())
        or not rows
        or sum(missing.values()) / len(rows) > 0.02
        or any(missing[o] > 2 or missing[o] / n > 0.10 for o, n in counts.items())
        or len(upper) > 8
    ):
        raise ValueError(
            "Historical offensive coverage below policy threshold; resolve missing prices."
        )
    return rows, {
        "version": "stats-guy-offense-v2" if exclude_idp else POLICY_VERSION,
        "excluded": excluded,
        "unranked_upper_bounds": upper,
        "priced": len(rows) - len(upper),
        "eligible": len(rows),
        "source_url": SOURCE_URL,
    }


def completed_transactions(transactions):
    unique = {}
    for row in transactions:
        if row.get("status") != "complete":
            continue
        key = row["transaction_id"]
        if not isinstance(row.get("status_updated"), int):
            raise TypeError(f"Transaction {key} has no completion timestamp.")
        if key in unique and unique[key] != row:
            raise ValueError(f"Conflicting transaction evidence: {key}")
        unique[key] = row
    return sorted(
        unique.values(), key=lambda t: (t["status_updated"], t["transaction_id"])
    )


def roster_sets(rows):
    result = {r["roster_id"]: set(r.get("players") or []) for r in rows}
    if len(result) != len(rows) or sum(map(len, result.values())) != len(
        set().union(*result.values())
    ):
        raise ValueError("Duplicate historical roster/player ownership.")
    return result


def reconcile_rosters(current_rosters, final_matchups, transactions, cutoff_ms):
    current, final = roster_sets(current_rosters), roster_sets(final_matchups)
    for tx in reversed(completed_transactions(transactions)):
        if tx["status_updated"] < cutoff_ms:
            continue
        for pid, rid in (tx.get("adds") or {}).items():
            if rid not in current or pid not in current[rid]:
                raise ValueError("Cannot reconcile post-cutoff roster addition.")
            current[rid].remove(pid)
        for pid, rid in (tx.get("drops") or {}).items():
            if rid not in current or any(pid in ids for ids in current.values()):
                raise ValueError("Cannot reconcile post-cutoff roster drop.")
            current[rid].add(pid)
    if current != final:
        raise ValueError(
            "Cutoff rosters do not reconcile with final-week player lists."
        )
    return {pid: rid for rid, ids in final.items() for pid in sorted(ids)}


def reconstruct_picks(roster_ids, season, rounds, transactions, cutoff_ms):
    picks = {
        (y, r, rid): rid
        for y in range(season + 1, season + 4)
        for r in range(1, rounds + 1)
        for rid in roster_ids
    }
    for tx in completed_transactions(transactions):
        if tx["status_updated"] >= cutoff_ms:
            continue
        for pick in tx.get("draft_picks") or []:
            key = (int(pick["season"]), pick["round"], pick["roster_id"])
            if season < key[0] <= season + 3 and key not in picks:
                raise ValueError("Unknown future pick in transaction ledger.")
            if key not in picks:
                continue
            if picks[key] != pick["previous_owner_id"]:
                raise ValueError(
                    f"Pick previous owner mismatch: {key}; fetch full league history."
                )
            if pick["owner_id"] not in roster_ids:
                raise ValueError("Unknown pick owner.")
            picks[key] = pick["owner_id"]
    return picks
