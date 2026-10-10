"""Synthetic full source fixture: no external identifiers or paid calls."""
from copy import deepcopy

import pytest


def snapshot():
    participants = [{"roster_id": i, "owner_id": f"owner-{i}", "owner_name": f"Owner {i}",
                     "status": "regular"} for i in range(1, 13)]
    rows = [{"roster_id": i, "matchup_id": (i + 1) // 2,
             "points": "40.004" if i % 2 else "40.003", "custom_points": None,
             "starters": ["a", "b", "c", "d"], "players": ["a", "b", "c", "d", "e", "f"],
             "players_points": {"a": "10.001", "b": "10.001", "c": "10.001", "d": "10.001", "e": "30", "f": "20"}}
            for i in range(1, 13)]
    return {"season": 2026, "week": 4, "period_id": "4", "nfl_weeks": [4],
            "participants": participants, "scores": {"4": rows},
            "pairings": [{"source_id": f"matchup:{i}", "rosters": [2*i-1, 2*i],
                          "winner": 2*i-1, "result": "win", "scope": "week"} for i in range(1, 7)],
            "roster_positions": ["QB", "RB", "WR", "FLEX", "BN"], "scoring_settings": {"rec": 1},
            "lineup_eligibility": {"4": {str(i): {"source_id": f"archived-week:4:{i}",
                "eligible_player_ids": ["a", "b", "c", "d", "e", "f"], "reserve": [], "taxi": []} for i in range(1, 13)}},
            "player_metadata": {"available": True, "source": "sleeper:players.json", "digest": "synthetic-cache",
                "players": {k: {"name": k, "positions": [p]} for k, p in
                            [("a", "QB"), ("b", "RB"), ("c", "WR"), ("d", "TE"), ("e", "RB"), ("f", "WR")]}}}


def script_for(claims):
    return {"article_digest": "published-revision-2", "opening": "Cal Mercer is back and already furious.",
        "closing": "Same damned league. See you next week.", "premises": [],
        "segments": [{"id": c["id"], "owner_ids": c["owner_ids"], "matchup_ids": c["matchup_ids"],
                      "claim_ids": [c["id"]], "text": "Football has consequences.", "spoken_numbers": []}
                     for c in claims["claims"] if c["kind"] in ("result", "owner_status")]}


def test_coverage_inventory():
    # Mutation: replace set difference with a success boolean or count comparison.
    from sleeper_dynasty.engine.recap_video_claims import coverage_errors
    assert coverage_errors(["a", "b"], ["a", "a"]) == ["b"]
    assert coverage_errors(["a", "b"], ["b", "a"]) == []


def test_exact_margin_full_starter_sum_and_distinct_legal_counterfactuals():
    # Mutation: trim to top three starters, round before subtraction, or label optimal as single swap.
    from sleeper_dynasty.engine.recap_video_claims import compile_claims
    facts = compile_claims(snapshot())["claims"]
    result = next(c for c in facts if c["id"] == "result:matchup:1")
    assert result["values"]["margin"] == "0.001"
    total = next(c for c in facts if c["id"] == "starters:4:1")
    assert total["values"]["total"] == "40.004" and len(total["operands"]) == 4
    single = next(c for c in facts if c["id"] == "substitution:4:1")
    optimal = next(c for c in facts if c["id"] == "optimal:4:1")
    assert single["values"]["gain"] == "19.999"
    assert optimal["values"]["gain"] == "29.998"
    assert single["scope"] == "single_substitution" and optimal["scope"] == "optimal_lineup"


def test_optional_evidence_missing_omits_player_claims_without_losing_owners():
    # Mutation: infer player positions from names or drop owners without optional evidence.
    from sleeper_dynasty.engine.recap_video_claims import compile_claims, validate_script
    source = snapshot()
    source["player_metadata"] = {"available": False}
    source["participants"][-1]["status"] = "season_finished"
    source["participants"][-2]["status"] = "bye"
    source["pairings"] = source["pairings"][:-1]
    claims = compile_claims(source)
    assert len(claims["owner_ids"]) == 12
    assert not any(c["kind"] in ("substitution", "optimal") for c in claims["claims"])
    total = next(c for c in claims["claims"] if c["id"] == "starters:4:1")
    assert total["values"]["total"] == "40.004"
    assert all("name" not in component for component in total["operands"])
    assert validate_script(script_for(claims), claims, {"digest": "published-revision-2"}) == []


@pytest.mark.parametrize("change,error", [
    (lambda s: s["segments"].pop(0), "owner_coverage"),
    (lambda s: s.update(article_digest="superseded-revision"), "article_revision"),
    (lambda s: s["segments"][0].update(text="He tore his ACL."), "unsupported_medical"),
    (lambda s: s["segments"][0].update(text="His wife left him last night."), "unsupported_personal"),
    (lambda s: s["segments"][0].update(claim_ids=["invented"]), "unknown_claim"),
])
def test_unpublishable_scripts_have_explicit_errors(change, error):
    # Mutation: accept unchecked IDs, omitted owner, stale article or unsupported factual jokes.
    from sleeper_dynasty.engine.recap_video_claims import compile_claims, validate_script
    claims = compile_claims(snapshot())
    script = script_for(claims)
    # One result segment per matchup: removing it removes both owners.
    script["segments"] = [s for s in script["segments"] if s["matchup_ids"]]
    change(script)
    assert any(error in e for e in validate_script(script, claims, {"digest": "published-revision-2"}))


def test_spoken_number_cannot_round_away_winning_margin():
    # Mutation: trust provider spoken value independently of exact fact.
    from sleeper_dynasty.engine.recap_video_claims import compile_claims, validate_script
    claims = compile_claims(snapshot())
    script = script_for(claims)
    segment = next(s for s in script["segments"] if s["id"] == "result:matchup:1")
    segment["spoken_numbers"] = [{"claim_id": segment["id"], "field": "margin", "exact": "0.001", "spoken": "zero"}]
    assert "spoken_number" in " ".join(validate_script(script, claims, {"digest": "published-revision-2"}))


def test_full_playoff_round_custom_override_and_inactive_coverage():
    # Mutation: calculate only final week, discard custom_points, or omit inactive owner.
    from sleeper_dynasty.engine.recap_video_claims import compile_claims, validate_script
    source = snapshot()
    source.update(period_id="playoff:2", nfl_weeks=[4, 5])
    source["scores"]["5"] = deepcopy(source["scores"]["4"])
    source["scores"]["5"][0]["custom_points"] = "70.00009"
    source["participants"][-2]["status"] = "bye"
    source["participants"][-1]["status"] = "season_finished"
    source["pairings"].pop()
    claims = compile_claims(source)
    result = next(c for c in claims["claims"] if c["id"] == "result:matchup:1")
    assert result["values"]["score_a"] == "110.00409"
    assert result["values"]["margin"] == "29.99809"
    assert len(result["operands"]) == 4
    script = script_for(claims)
    assert validate_script(script, claims, {"digest": "published-revision-2"}) == []
    script["segments"] = [s for s in script["segments"] if s["id"] != "status:owner-12"]
    assert "owner_coverage:owner-12" in validate_script(script, claims, {"digest": "published-revision-2"})


def test_illegal_bench_position_never_becomes_legal_substitution():
    # Mutation: choose highest bench score without checking slot eligibility.
    from sleeper_dynasty.engine.recap_video_claims import compile_claims
    source = snapshot()
    source["player_metadata"]["players"]["e"]["positions"] = ["K"]
    claim = next(c for c in compile_claims(source)["claims"] if c["id"] == "substitution:4:1")
    assert claim["operands"][0]["in"] == "f"
    assert claim["values"]["gain"] == "9.999"


def test_missing_weekly_eligibility_omits_counterfactuals_keeps_starter_sum():
    # Mutation: current roster or every scored bench player implies historical lineup eligibility.
    from sleeper_dynasty.engine.recap_video_claims import compile_claims
    source = snapshot()
    source.pop("lineup_eligibility")
    facts = compile_claims(source)["claims"]
    assert not any(c["kind"] in ("substitution", "optimal") for c in facts)
    assert next(c for c in facts if c["id"] == "starters:4:1")["values"]["total"] == "40.004"


def test_scored_reserve_and_taxi_players_excluded_from_optimal_pool():
    # Mutation: highest scored reserve/taxi included despite explicit weekly exclusion evidence.
    from sleeper_dynasty.engine.recap_video_claims import compile_claims
    source = snapshot()
    pool = source["lineup_eligibility"]["4"]["1"]
    pool.update(eligible_player_ids=["a", "b", "c", "d"], reserve=["e"], taxi=["f"])
    facts = compile_claims(source)["claims"]
    assert not any(c["id"] == "substitution:4:1" for c in facts)
    optimal = next(c for c in facts if c["id"] == "optimal:4:1")
    assert optimal["values"]["gain"] == "0.000"
    assert pool["source_id"] in optimal["source_ids"]


def test_large_starter_inventory_is_never_silently_trimmed():
    # Mutation: optional optimal-lineup complexity bound drops mandatory full starter sums too.
    from sleeper_dynasty.engine.recap_video_claims import compile_claims
    source = snapshot()
    source["roster_positions"] = ["QB", *["RB"] * 12]
    source["player_metadata"] = {"available": False}
    for row in source["scores"]["4"]:
        row["starters"] = row["players"] = [f"player-{i}" for i in range(13)]
        row["players_points"] = {p: "10" for p in row["players"]}
    total = next(c for c in compile_claims(source)["claims"] if c["id"] == "starters:4:1")
    assert total["values"]["total"] == "130" and len(total["operands"]) == 13
