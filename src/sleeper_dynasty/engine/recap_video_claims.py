"""Compact, exact evidence for narration and graphics; no provider or execution I/O."""
from __future__ import annotations

from decimal import Decimal
import re

from sleeper_dynasty.engine.lineup import SLOT_ELIGIBILITY


def coverage_errors(expected: list[str], covered: list[str]) -> list[str]:
    return sorted(set(expected) - set(covered))


def number(value):
    if not isinstance(value, str) and type(value) is not int:
        raise ValueError("Exact score text required; floating-point source is unsupported")
    result = Decimal(value)
    if not result.is_finite():
        raise ValueError("Finite score required")
    return result


_SMALL = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
_TENS = "zero ten twenty thirty forty fifty sixty seventy eighty ninety".split()


def spoken_decimal(value: str) -> str:
    """Lossless approved rendering; deliberately never round a close outcome."""
    def integer(n):
        if n < 20:
            return _SMALL[n]
        if n < 100:
            return _TENS[n // 10] + (" " + integer(n % 10) if n % 10 else "")
        if n < 1000:
            return integer(n // 100) + " hundred" + (" " + integer(n % 100) if n % 100 else "")
        if n < 1000000:
            return integer(n // 1000) + " thousand" + (" " + integer(n % 1000) if n % 1000 else "")
        return " ".join(_SMALL[int(c)] for c in str(n))
    plain = format(number(value), "f")
    sign = "minus " if plain.startswith("-") else ""
    whole, _, fraction = plain.lstrip("-").partition(".")
    fraction = fraction.rstrip("0")
    return sign + integer(int(whole)) + (" point " + " ".join(_SMALL[int(c)] for c in fraction) if fraction else "")


def _lineup_claims(snapshot, row, week, owner, matchup_ids):
    meta = snapshot.get("player_metadata", {})
    players = meta.get("players", {})
    slots = [s for s in snapshot.get("roster_positions", []) if s not in ("BN", "IR", "TAXI")]
    starters = row.get("starters", [])
    roster = row.get("players", [])
    points = row.get("players_points", {})
    if not slots or len(slots) != len(starters) or len(roster) != len(set(roster)):
        raise ValueError("Full starter slot inventory required")
    active = [p for p in roster if p != "0"]
    try:
        scores = {p: number(points[p]) for p in starters if p != "0"}
    except (KeyError, ValueError, ArithmeticError):
        raise ValueError("Full starter score evidence required") from None
    scores["0"] = Decimal(0)
    def legal(p, slot):
        return p == "0" or bool(set(players[p]["positions"]) & SLOT_ELIGIBILITY[slot])
    if (len([p for p in starters if p != "0"]) != len(set(starters) - {"0"})
            or any(p not in active for p in starters if p != "0")):
        raise ValueError("Full starter identity evidence required")
    rid = row["roster_id"]
    source = f"scores:{week}:{rid}"
    total = sum((scores[p] for p in starters), Decimal(0))
    enriched = bool(meta.get("available") and meta.get("source") and meta.get("digest"))
    components = [{"player_id": p, **({"name": players[p]["name"]} if enriched and players.get(p, {}).get("name") else {}), "value": str(scores[p]),
                   "source_id": source + ":players_points:" + p} for p in starters if p != "0"]
    def claim(kind, scope, values, operands):
        return {"id": f"{kind}:{week}:{rid}", "kind": kind, "scope": scope,
                "owner_ids": [owner], "matchup_ids": matchup_ids, "values": values,
                "operands": operands, "source_ids": [source] + ([meta["source"] + ":" + meta["digest"]] if enriched else [])}
    result = [claim("starters", f"week:{week}", {"total": str(total)}, components)]
    pool = snapshot.get("lineup_eligibility", {}).get(str(week), {}).get(str(rid), {})
    # Present-day roster reserve/taxi state cannot establish historical eligibility.
    if (not enriched or len(slots) > 12 or any(s not in SLOT_ELIGIBILITY for s in slots) or not pool.get("source_id")
            or any(not isinstance(pool.get(k), list) or any(not isinstance(p, str) for p in pool[k])
                   for k in ("eligible_player_ids", "reserve", "taxi"))):
        return result
    eligible, excluded = set(pool["eligible_player_ids"]), set(pool["reserve"] + pool["taxi"])
    if (eligible & excluded or eligible | excluded != set(active) or not (set(starters) - {"0"}) <= eligible
            or any(p not in players or not players[p].get("name") or not players[p].get("positions") or p not in points for p in eligible)):
        return result
    active = sorted(eligible)
    try:
        scores.update({p: number(points[p]) for p in active})
    except (ValueError, ArithmeticError):
        return result
    if any(not legal(p, s) for p, s in zip(starters, slots)):
        return result
    # Overrides and unexplained differences prohibit win/loss counterfactuals.
    if row.get("custom_points") is not None or number(row["points"]) != total:
        return result
    swaps = [(scores[p] - scores[old], old, p, slot) for old, slot in zip(starters, slots)
             for p in active if p not in starters and legal(p, slot)]
    if swaps:
        gain, old, new, slot = max(swaps)
        if gain > 0:
            result.append(claim("substitution", "single_substitution",
                {"gain": str(gain), "total": str(total + gain)},
                [{"out": old, "in": new, "slot": slot, "out_points": str(scores[old]), "in_points": str(scores[new])}]))
    # Exact maximum-weight matching, including overlapping flex eligibility.
    # DP over occupied slots avoids greedy multi-position assignment errors.
    dp = {0: (Decimal(0), [])}
    for p in active:
        for mask, (score, assignment) in list(dp.items()):
            for i, slot in enumerate(slots):
                target = mask | (1 << i)
                if mask == target or not legal(p, slot):
                    continue
                candidate = score + scores[p]
                if target not in dp or candidate > dp[target][0]:
                    dp[target] = (candidate, assignment + [{"player_id": p, "slot_index": i,
                                                           "slot": slot, "value": str(scores[p])}])
    optimum, assignment = max(dp.values(), key=lambda v: v[0])
    result.append(claim("optimal", "optimal_lineup", {"total": str(optimum), "gain": str(optimum-total)}, assignment))
    for counterfactual in result[1:]:
        counterfactual["source_ids"].append(pool["source_id"])
        counterfactual["eligibility"] = {"eligible_player_ids": active, "reserve": pool["reserve"], "taxi": pool["taxi"]}
    return result


def compile_claims(snapshot: dict) -> dict:
    participants = snapshot["participants"]
    owners = {p["roster_id"]: p["owner_id"] for p in participants}
    if not owners or len(owners) != len(participants) or any(not v for v in owners.values()):
        raise ValueError("Participant inventory incomplete")
    claims, matchups, paired = [], [], set()
    for index, pair in enumerate(snapshot["pairings"]):
        mid = str(pair.get("source_id") or f"matchup:{index + 1}")
        rosters = pair["rosters"]
        if len(rosters) != 2 or any(r not in owners or r in paired for r in rosters):
            raise ValueError("Matchup inventory incomplete")
        paired.update(rosters)
        totals, operands = [], []
        for rid in rosters:
            pieces = []
            for week in snapshot["nfl_weeks"]:
                rows = [r for r in snapshot["scores"][str(week)] if r["roster_id"] == rid]
                if len(rows) != 1:
                    raise ValueError("Score inventory incomplete")
                row = rows[0]
                field = "custom_points" if row.get("custom_points") is not None else "points"
                pieces.append(number(row[field]))
                operands.append({"owner_id": owners[rid], "value": str(row[field]),
                                 "source_id": f"scores:{week}:{rid}:{field}"})
                claims.extend(_lineup_claims(snapshot, row, week, owners[rid], [mid]))
            totals.append(sum(pieces, Decimal(0)))
        winner = None if totals[0] == totals[1] else rosters[0 if totals[0] > totals[1] else 1]
        if pair.get("result") == "tiebreak_win" and totals[0] == totals[1]:
            winner = pair["winner"]
        elif pair.get("winner", winner) != winner:
            raise ValueError("Result disagrees with exact scores")
        values = {"score_a": str(totals[0]), "score_b": str(totals[1]), "margin": str(abs(totals[0]-totals[1]))}
        claims.append({"id": "result:" + mid, "kind": "result", "scope": snapshot["period_id"],
            "owner_ids": [owners[r] for r in rosters], "matchup_ids": [mid], "values": values,
            "winner_id": owners[winner] if winner is not None else None,
            "result": "tiebreak_win" if pair.get("result") == "tiebreak_win" else "tie" if winner is None else "win",
            "operands": operands, "source_ids": [o["source_id"] for o in operands] + [mid]})
        matchups.append(mid)
    for p in participants:
        if p["roster_id"] in paired:
            continue
        if p.get("status") not in ("bye", "season_finished"):
            raise ValueError("Unpaired owner lacks supported status")
        claims.append({"id": "status:" + p["owner_id"], "kind": "owner_status", "scope": snapshot["period_id"],
            "owner_ids": [p["owner_id"]], "matchup_ids": [], "status": p["status"], "values": {},
            "operands": [], "source_ids": [f"participants:{p['roster_id']}", "bracket"]})
    for claim in claims:
        claim["spoken_values"] = {k: spoken_decimal(v) for k, v in claim["values"].items()}
    return {"version": "recap-claims-v1", "period_id": snapshot["period_id"],
        "owner_ids": sorted(set(owners.values())), "matchup_ids": matchups,
        "owners": [{"id": p["owner_id"], "name": p.get("owner_name") or p["owner_id"], "status": p["status"]} for p in participants],
        "claims": claims}


def validate_script(script: dict, claims: dict, published_article: dict) -> list[str]:
    """Deterministic integrity checks; semantic prose review is additionally mandatory."""
    if not isinstance(script, dict):
        return ["script_schema"]
    errors = []
    if script.get("article_digest") != published_article.get("digest") or not published_article.get("digest"):
        errors.append("article_revision")
    if any(not isinstance(script.get(k), str) or not script[k].strip() for k in ("opening", "closing")):
        errors.append("opening_closing_required")
    if not isinstance(script.get("premises"), list):
        errors.append("premises_schema")
    index = {c["id"]: c for c in claims["claims"]}
    owners, matchups, ids = [], [], set()
    segments = script.get("segments")
    if not isinstance(segments, list) or not segments:
        return errors + ["segments_required"]
    prose = [script.get("opening", ""), script.get("closing", "")]
    for segment in segments:
        if (not isinstance(segment, dict) or not isinstance(segment.get("id"), str)
                or not isinstance(segment.get("text"), str) or not segment["text"].strip()
                or any(not isinstance(segment.get(k), list) or any(not isinstance(v, str) for v in segment[k])
                       for k in ("owner_ids", "matchup_ids", "claim_ids"))):
            errors.append("segment_schema")
            continue
        sid = segment["id"]
        if sid in ids or sid in ("opening", "closing"):
            errors.append("duplicate_segment")
        ids.add(sid)
        prose.append(segment["text"])
        selected = [index[c] for c in segment["claim_ids"] if c in index]
        if not selected or len(selected) != len(segment["claim_ids"]):
            errors.append("unknown_claim:" + sid)
        covered_owners = {o for c in selected if c["kind"] in ("result", "owner_status") for o in c["owner_ids"]}
        covered_matchups = {m for c in selected if c["kind"] == "result" for m in c["matchup_ids"]}
        if set(segment["owner_ids"]) - {o for c in selected for o in c["owner_ids"]}:
            errors.append("owner_claim_mismatch:" + sid)
        owners.extend(set(segment["owner_ids"]) & covered_owners)
        matchups.extend(set(segment["matchup_ids"]) & covered_matchups)
        numbers = segment.get("spoken_numbers")
        if not isinstance(numbers, list):
            errors.append("spoken_number_schema")
            continue
        for value in numbers:
            if not isinstance(value, dict):
                errors.append("spoken_number_schema")
                continue
            claim = index.get(value.get("claim_id"), {})
            field = value.get("field")
            if (value.get("claim_id") not in segment["claim_ids"] or not value.get("exact")
                    or value["exact"] != claim.get("values", {}).get(field)
                    or value.get("spoken") != claim.get("spoken_values", {}).get(field)
                    or value.get("spoken", "") not in segment["text"]):
                errors.append("spoken_number:" + sid)
    errors.extend("owner_coverage:" + o for o in coverage_errors(claims["owner_ids"], owners))
    errors.extend("matchup_coverage:" + m for m in coverage_errors(claims["matchup_ids"], matchups))
    text = " ".join(p for p in prose if isinstance(p, str))
    # Conservative unsupported claim tripwires, not a replacement for semantic review.
    if re.search(r"\b(ACL|concussion|diagnosed|surgery|tore his|injured because)\b", text, re.I):
        errors.append("unsupported_medical")
    if re.search(r"\b(his wife|her husband|divorced|got arrested|last night at)\b", text, re.I):
        errors.append("unsupported_personal")
    return errors
