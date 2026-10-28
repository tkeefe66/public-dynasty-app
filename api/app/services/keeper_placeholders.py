"""Replay reviewed placeholder evidence; never infer keepers from missing prices."""

from copy import deepcopy


def _unique(rows, key):
    indexed = {r[key]: r for r in rows}
    if len(indexed) != len(rows):
        raise ValueError("Reconstruction contains duplicate evidence identities.")
    return indexed


def normalize(*, season, league_id, draft, picks, evidence):
    """Return an isolated valuation input while retaining raw provider selections.

    This reviewed policy requires multiple independent signals, not a retirement
    status or roster overlap alone. Publication must compare the saved source
    records to provider receipts before importing the containing asset manifest.
    """
    try:
        return _normalize(season, league_id, draft, picks, evidence)
    except (KeyError, TypeError, ValueError, StopIteration) as exc:
        raise ValueError(f"Reconstruction evidence failed: {exc}") from exc


def _normalize(season, league_id, draft, picks, evidence):
    if (
        evidence["version"] != 1
        or not evidence["reviewed_by"]
        or not evidence["basis"]
        or evidence["cost_rule"] != "prior-round-minus-one-floor-one"
    ):
        raise ValueError("Unsupported or unreviewed keeper-cost policy.")
    seasons = evidence["seasons"]
    if not seasons or len(seasons) > 30:
        raise ValueError("Missing or excessive reconstruction history.")
    resolved = {}
    normalized = None
    previous_year = None
    previous_row = None
    for row in seasons:
        league = row["league"]
        year = int(league["season"])
        lid = league["league_id"]
        prior = row["previous_league"]
        if (
            int(prior["season"]) != year - 1
            or league["previous_league_id"] != prior["league_id"]
            or year > season
            or (previous_year is not None and year != previous_year + 1)
        ):
            raise ValueError("Season lineage does not match.")
        previous_year = year
        d = row["draft"]
        if (
            d["league_id"] != lid
            or int(d["season"]) != year
            or d["status"] != "complete"
        ):
            raise ValueError("Draft does not match completed season.")
        start, end = d["start_time"], d["last_picked"]
        if not 0 < start <= end:
            raise ValueError("Draft timestamps are invalid.")
        raw = row["picks"]
        selections = _unique(raw, "player_id")
        if any(p["draft_id"] != d["draft_id"] for p in raw):
            raise ValueError("Selections belong to another draft.")
        current = _unique(row["rosters"], "roster_id")
        owners = _unique(row["previous_rosters"], "owner_id")
        opening = _unique(row["opening"], "roster_id")
        final = _unique(row["previous_final"], "roster_id")
        if row["previous_final_week"] != prior["settings"]["last_scored_leg"]:
            raise ValueError("Previous roster snapshot is not the final scored week.")
        if set(current) != set(opening) or len(current) != d["settings"]["teams"]:
            raise ValueError("Roster coverage is incomplete.")
        retained = set()
        for rid, roster in current.items():
            previous = owners.get(roster["owner_id"])
            if previous is None:
                continue
            prior_players = set(final[previous["roster_id"]]["players"] or [])
            for pid in (
                set(opening[rid]["players"] or []) - set(selections)
            ) & prior_players:
                retained.add((rid, pid))
        mappings = row["mappings"]
        mapped = {(m["roster_id"], m["keeper"]) for m in mappings}
        placeholders = {m["placeholder"] for m in mappings}
        if (
            not mappings
            or mapped != retained
            or len(mapped) != len(mappings)
            or len(placeholders) != len(mappings)
        ):
            raise ValueError(
                "Mappings must uniquely cover every undrafted retained player."
            )
        txs = list(_unique(row["transactions"], "transaction_id").values())
        txs = [t for t in txs if t["status"] == "complete"]
        prior_draft = row["previous_draft"]
        if (
            prior_draft["league_id"] != prior["league_id"]
            or int(prior_draft["season"]) != year - 1
            or prior_draft["status"] != "complete"
            or any(
                p["draft_id"] != prior_draft["draft_id"] for p in row["previous_picks"]
            )
        ):
            raise ValueError("Previous draft evidence belongs to another season.")
        if previous_row is not None and (
            previous_row["draft"] != prior_draft
            or previous_row["picks"] != row["previous_picks"]
        ):
            raise ValueError(
                "Adjacent reconstruction copies of the previous draft conflict."
            )
        prior_picks = _unique(row["previous_picks"], "player_id")
        derived = deepcopy(raw)
        for m in mappings:
            keeper, placeholder, rid = m["keeper"], m["placeholder"], m["roster_id"]
            pick = selections[placeholder]
            if pick["roster_id"] != rid or pick.get("is_keeper") is True:
                raise ValueError(
                    "Placeholder ownership or provider keeper flag conflicts."
                )
            if any(
                t["status_updated"] <= end
                and (
                    keeper in (t.get("adds") or {}) or keeper in (t.get("drops") or {})
                )
                for t in txs
            ):
                raise ValueError(
                    "Retained player has a pre-draft acquisition or removal."
                )
            cost = prior_picks.get(keeper, {}).get("round")
            if cost is None:
                cost = resolved.get((prior["league_id"], keeper))
            if type(cost) is not int or pick["round"] != max(1, cost - 1):
                raise ValueError("Keeper cost lacks matching prior draft evidence.")
            drops = [
                t
                for t in txs
                if end <= t["status_updated"] <= end + 7_200_000
                and t.get("type") in {"free_agent", "commissioner"}
                and not t.get("draft_picks")
                and not t.get("waiver_budget")
                and t.get("drops") == {placeholder: rid}
                and not t.get("adds")
            ]
            if len(drops) != 1:
                raise ValueError(
                    "Placeholder lacks a unique immediate standalone drop."
                )
            # A second dropped pick at the same cost would make assignment ambiguous.
            candidates = [
                p
                for p in raw
                if p["roster_id"] == rid
                and p["round"] == pick["round"]
                and any(
                    t.get("drops") == {p["player_id"]: rid}
                    and not t.get("adds")
                    and end <= t["status_updated"] <= end + 7_200_000
                    for t in txs
                )
            ]
            if len(candidates) != 1:
                raise ValueError("Multiple selections could represent the keeper cost.")
            next(p for p in derived if p["player_id"] == placeholder)["is_keeper"] = (
                True
            )
            resolved[(lid, keeper)] = pick["round"]
        if year == season:
            if lid != league_id or d != draft or raw != picks:
                raise ValueError(
                    "Reconstruction is not bound to the requested original draft."
                )
            normalized = derived
        previous_row = row
    if normalized is None:
        raise ValueError("Selected season reconstruction is missing.")
    return normalized
