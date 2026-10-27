"""Resolve Sleeper advancement from final ancestry, including consolation trees."""

from __future__ import annotations


def title_path(games: list[dict]) -> tuple[set[int], dict | None]:
    """Return game indices feeding the title and its final.

    Explicit slot references take precedence. Older rounds omit these edges;
    their resolved participants must have won their latest earlier game (or
    have a bye). Unplayed slots may reference games without a resolved roster.
    Minimal result-only fixtures remain supported when no ancestry is supplied.
    """
    if not games:
        return set(), None
    by_match = {g["m"]: i for i, g in enumerate(games) if g.get("m") is not None}
    if len(by_match) != sum(g.get("m") is not None for g in games):
        raise ValueError("Ambiguous bracket: duplicate match identifiers.")

    def reference(index, slot):
        game = games[index]
        value = game.get(slot)
        edge = game.get(f"{slot}_from")
        if isinstance(value, dict):
            if edge is not None and edge != value:
                raise ValueError("Inconsistent bracket slot references.")
            edge = value
        if edge is None:
            return None
        if not isinstance(edge, dict) or len(edge) != 1 or not set(edge) <= {"w", "l"}:
            raise ValueError("Invalid bracket advancement reference.")
        outcome, match = next(iter(edge.items()))
        previous = by_match.get(match)
        if previous is None or (games[previous].get("r") or 0) >= (game.get("r") or 0):
            raise ValueError(
                "Invalid bracket reference: source must be an earlier match."
            )
        resolved = games[previous].get(outcome)
        if isinstance(value, int) and resolved is not None and value != resolved:
            raise ValueError("Inconsistent bracket reference and participant.")
        return previous, outcome

    # Validate placement references too; a contradictory edge is never evidence.
    edges = {
        (i, slot): reference(i, slot)
        for i in range(len(games))
        for slot in ("t1", "t2")
    }
    for index, game in enumerate(games):
        entrants = []
        for slot in ("t1", "t2"):
            edge = edges[index, slot]
            rid = games[edge[0]].get(edge[1]) if edge is not None else game.get(slot)
            if isinstance(rid, int):
                entrants.append(rid)
        result = [game.get(k) for k in ("w", "l")]
        if all(isinstance(rid, int) for rid in result) and (
            result[0] == result[1]
            or (len(entrants) == 2 and set(result) != set(entrants))
        ):
            raise ValueError("Inconsistent bracket result and resolved participants.")
    finals = [i for i, g in enumerate(games) if g.get("p") == 1]
    if not finals:
        # Retain the legacy unlabelled-final format only when unambiguous.
        unlabelled = [i for i, g in enumerate(games) if g.get("p") is None]
        if not unlabelled:
            return set(), None
        last_round = max(games[i].get("r") or 0 for i in unlabelled)
        finals = [i for i in unlabelled if (games[i].get("r") or 0) == last_round]
    if len(finals) != 1:
        raise ValueError("Ambiguous bracket: no unique championship final.")
    path: set[int] = set()

    def visit(index):
        if index in path:
            return
        game = games[index]
        if game.get("p") not in (None, 1):
            raise ValueError("Inconsistent bracket: placement game feeds title.")
        path.add(index)
        for slot, result_key in (("t1", "w"), ("t2", "l")):
            edge = edges[index, slot]
            if edge is not None:
                previous, outcome = edge
                if outcome != "w":
                    raise ValueError(
                        "Inconsistent bracket: a loser advances toward title."
                    )
                visit(previous)
                continue
            rid = game.get(slot)
            if rid is None:
                rid = game.get(result_key)
            if not isinstance(rid, int):
                continue
            prior = [
                i
                for i, row in enumerate(games)
                if (row.get("r") or 0) < (game.get("r") or 0)
                and rid in (row.get("w"), row.get("l"))
            ]
            if not prior:
                continue  # First appearance / bye, not a fabricated win.
            latest = max(games[i].get("r") or 0 for i in prior)
            sources = [i for i in prior if (games[i].get("r") or 0) == latest]
            if len(sources) != 1 or games[sources[0]].get("w") != rid:
                raise ValueError(
                    "Ambiguous bracket title ancestry: participant did not uniquely advance."
                )
            visit(sources[0])

    visit(finals[0])
    return path, games[finals[0]]


def implicit_seventh(games: list[dict], path: set[int]) -> dict[int, int]:
    """Prove seventh from the completed seven-team consolation elimination.

    This is deliberately limited to the observed 3/3/3 structure: three title
    quarterfinal losers enter the 5-7 tree, one gets a bye to p5, and the other
    two play a semifinal whose loser has no later game. No source game is added.
    """
    if len(games) != 9 or len(path) != 6:
        return {}
    if any(not isinstance(g.get(k), int) for g in games for k in ("w", "l")):
        return {}
    rounds = [[g for g in games if g.get("r") == r] for r in (1, 2, 3)]
    if [len(rows) for rows in rounds] != [3, 3, 3]:
        return {}
    placements = {g.get("p"): g for g in rounds[2]}
    if set(placements) != {1, 3, 5}:
        return {}
    population = {g[k] for g in games for k in ("w", "l")}
    placed = [g[k] for g in rounds[2] for k in ("w", "l")]
    if len(population) != 7 or len(set(placed)) != 6:
        return {}
    consolation = [g for i, g in enumerate(games) if i not in path and g.get("r") == 2]
    if len(consolation) != 1 or consolation[0].get("p") is not None:
        return {}
    semi = consolation[0]
    early_losers = {g["l"] for g in rounds[0]}
    if len(early_losers) != 3 or not {semi["w"], semi["l"]} <= early_losers:
        return {}
    fifth = placements[5]
    bye = early_losers - {semi["w"], semi["l"]}
    if {fifth["w"], fifth["l"]} != bye | {semi["w"]}:
        return {}
    if population - set(placed) != {semi["l"]}:
        return {}
    return {semi["l"]: 7}
