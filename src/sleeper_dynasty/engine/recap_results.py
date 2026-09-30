"""Deterministic results edition. No model, news, lore, or inferred explanations."""
import math


def _label(value) -> str:
    # Keep league-controlled names/terms inside their paragraph and out of markup.
    return " ".join(str(value).split()).replace("*", "∗")


def _points(value) -> str:
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Results edition requires finite scores")
    return f"{value:.2f}"


def render_results_recap(facts: dict, outlook: dict | None = None) -> str:
    """Render only explicit scores and computed context from a completed week."""
    blocks = [f"## Week {facts['week']} results",
              "Results edition · Compiled directly from league scores and recorded data. "
              "The AI-written roast was unavailable for this edition.", "## Every matchup"]
    if not facts.get("matchups"):
        raise ValueError("Results edition requires completed matchups")
    for game in facts["matchups"]:
        score = (f"**{_label(game['winner'])} {_points(game['winner_points'])}, "
                 f"{_label(game['loser'])} {_points(game['loser_points'])}**.")
        result = ("Tied matchup." if game["margin"] == 0 else
                  f"{_label(game['winner'])} won by {_points(game['margin'])} points.")
        blocks.append(f"{score} {result}")

    blocks.append("## Leading starters")
    leaders = []
    for lineup in facts.get("lineups", []):
        if lineup.get("starters"):
            top = max(lineup["starters"], key=lambda p: p["points"])
            leaders.append(f"- {_label(lineup['owner'])}: {_label(top['player'])}, {_points(top['points'])} fantasy points.")
    blocks.append("\n".join(leaders) or "Starter scoring details were unavailable.")

    blocks.extend(["## Bench decisions",
                   "These are independent hindsight scenarios, not points that can be added together. "
                   "They do not establish what was knowable before kickoff."])
    swaps = []
    for regret in facts.get("bench_regret", []):
        for swap in regret.get("legal_swaps", []):
            bench, starter = swap["benched_player"], swap["started_player"]
            line = (f"- {_label(regret['owner'])}, {_label(swap['slot'])}: "
                    f"{_label(bench['player'])} ({_points(bench['points'])}) for "
                    f"{_label(starter['player'])} ({_points(starter['points'])}) "
                    f"would add +{_points(swap['points_gained'])} points.")
            effect = swap.get("matchup_effect")
            if effect and effect.get("result") in ("win", "loss", "tie"):
                line += (f" That single swap would make the score {_points(effect['team_points'])} "
                         f"to {_points(effect['opponent_points'])} ({effect['result']}).")
            swaps.append(line)
    blocks.append("\n".join(swaps) or "No higher-scoring legal bench swaps were identified in the available recap data.")

    blocks.append("## Standings after this week")
    race = facts.get("standings_race", {})
    if race.get("available"):
        blocks.append("Ranked by wins plus half of ties, then points for. Exact ties share rank; these are not playoff seeds.")
        rows = []
        for team in race["teams"]:
            wins, losses, ties = team["record_after"]
            rank = f"{'Tied ' if team.get('rank_tied') else ''}{team['rank_after']}"
            rows.append(f"- {rank}. {_label(team['owner'])}: {wins}-{losses}-{ties} (W-L-T), "
                        f"{_points(team['points_for'])} points for.")
        blocks.append("\n".join(rows))
    else:
        blocks.append("Standings could not be verified against the league's scoring rules and records. No rank or playoff claims are included.")

    blocks.append("## Bets on the books")
    bets = facts.get("bets", {})
    if not bets.get("available"):
        blocks.append("Bet ledger unavailable for this edition. That does not mean there are no bets.")
    else:
        blocks.append(f"Ledger snapshot: {_label(bets.get('as_of', 'at publication'))}. "
                      "This reflects recorded status at publication, not necessarily at the final whistle. "
                      "Each stake is the amount owed by the loser, not a doubled pot.")
        rows = []
        for bet in [*bets.get("active", []), *bets.get("resolved", [])]:
            if bet.get("status") == "settled":
                status = f"Recorded winner: {_label(bet.get('winner') or 'unavailable')}"
            elif bet.get("status") == "push":
                status = "Recorded as a push"
            else:
                status = "Open; no result recorded"
            rows.append(f"- {_label(bet.get('side_a', 'Unknown owner'))} vs "
                        f"{_label(bet.get('side_b', 'Unknown owner'))} · {_label(bet['stake'])}. "
                        f"Recorded terms: “{_label(bet['terms'])}”. {status}.")
        blocks.append("\n".join(rows) or "No open or resolved bets were recorded in this snapshot.")

    blocks.append(f"## Week {facts['week'] + 1} preview")
    if outlook and outlook.get("matchups"):
        blocks.append("Projected totals use optimized eligible lineups at publication, not confirmed starters or guaranteed results.")
        rows = []
        for game in outlook["matchups"]:
            edge = ("no projected edge" if game["spread"] == 0 else
                    f"projected edge: {_label(game['favorite'])} by {_points(game['spread'])}")
            rows.append(f"- {_label(game['home'])} {_points(game['home_projected'])}, "
                        f"{_label(game['away'])} {_points(game['away_projected'])} · {edge}.")
        blocks.append("\n".join(rows))
    else:
        blocks.append("Projections were unavailable for this edition. No forecast is assumed.")
        pairings = race.get("upcoming_matchups", [])
        if pairings:
            blocks.append("\n".join(f"- {_label(g['side_a'])} vs {_label(g['side_b'])}." for g in pairings))
    return "\n\n".join(blocks)
