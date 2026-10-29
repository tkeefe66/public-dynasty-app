import json
from importlib import import_module
from pathlib import Path

import anthropic
import pytest

from sleeper_dynasty.llm.cost_store import LlmCostStore
from sleeper_dynasty.llm.recap_writer import (
    RecapWriter,
    load_default_persona,
    load_lore_template,
)
from sleeper_dynasty.models.recap import OutlookFacts, RecapFacts


@pytest.fixture(autouse=True)
def no_external_usage_reporting(monkeypatch):
    monkeypatch.delenv("COACH_USAGE_URL", raising=False)
    monkeypatch.delenv("COACH_USAGE_TOKEN", raising=False)


def _facts():
    return RecapFacts(
        week=9,
        league_name="Bros",
        standings=[],
        matchups=[],
        high_scorer={"owner": "Team A", "points": 158.0},
        low_scorer=None,
        bench_regret=[],
        lucky=[],
        unlucky=[],
        heroes=[],
        goats=[],
        busts=[],
    )


@pytest.mark.parametrize('label,rec,valid', [
    ('half-PPR', '1.0', False), ('half PPR', '0.5', True),
    ('half-point PPR', '1', False), ('0.5-PPR', 1, False),
    ('full-PPR', '0.5', False), ('PPR', '0', False),
    ('non-PPR', '1.0', False), ('non-PPR', '0.0', True),
    ('full PPR', '1.0', True), ('PPR', 1, True),
    ('half–PPR', '1.0', False), ('standard scoring', '1', False),
])
def test_saved_reception_scoring_overrules_paid_review(writer_factory, label, rec, valid):
    # Mutation: trust an approving reviewer without comparing named scoring to saved rec.
    from sleeper_dynasty.llm.recap_packet import ArchivedPacket
    packet = _facts().to_dict()
    packet['source_snapshot'] = {'scoring_settings': {'rec': rec}}
    text = f'In a league with {label} scoring, every catch matters.'
    writer, requests = writer_factory([
        _message([_text(text)]), _message([_verdict()], stop_reason='tool_use')])
    if valid:
        assert writer.write(ArchivedPacket(packet)) == text
    else:
        with pytest.raises(ValueError, match='scoring.*refusing publication'):
            writer.write(ArchivedPacket(packet))
    assert len(requests) == 2


@pytest.mark.parametrize('claim,valid', [
    ('Their lowest score of the season.', False),
    ('His highest total of his career.', False),
    ('A season-low score.', False),
    ('The lowest score this week.', True),
    ('Their highest hopes for the season.', True),
])
def test_canonical_week_packet_cannot_prove_historical_scoring_records(writer_factory, claim, valid):
    # Mutation: let a paid reviewer approve a historical scoring record from one-week evidence.
    from sleeper_dynasty.llm.recap_packet import ArchivedPacket
    packet = _facts().to_dict()
    packet['source_snapshot'] = {'scoring_settings': {'rec': '1'}}
    writer, requests = writer_factory([
        _message([_text(claim)]), _message([_verdict()], stop_reason='tool_use')])
    if valid:
        assert writer.write(ArchivedPacket(packet)) == claim
    else:
        with pytest.raises(ValueError, match='historical scoring.*refusing publication'):
            writer.write(ArchivedPacket(packet))
    assert len(requests) == 2


def _message(content, *, stop_reason="end_turn", output_tokens=300):
    # Composed from the documented Messages API envelope, not a production capture.
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-haiku-4-5-20251001",
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": 800,
            "output_tokens": output_tokens,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        },
    }


def _text(text):
    return {"type": "text", "text": text}


def _verdict(value=None, *, name="submit_recap_review"):
    return {
        "type": "tool_use",
        "id": "toolu_test",
        "name": name,
        "input": {"approved": True, "checks": []} if value is None else value,
    }


def _edits(before, after):
    return {"type": "tool_use", "id": "toolu_edit", "name": "submit_recap_edits",
            "input": {"edits": [{"before": before, "after": after}]}}


def _passage_edits(edits):
    return {"type": "tool_use", "id": "toolu_edit", "name": "submit_recap_passage_edits",
            "input": {"edits": edits}}


@pytest.mark.parametrize("final_approved", [True, False])
def test_second_wording_repair_is_automatic_but_never_publishes_rejected_text(writer_factory, final_approved):
    # Mutation: stop after one repair, or publish the second repair without approval.
    def rejected(quote):
        return _message([_verdict({"approved": False, "checks": [{
            "status": "needs_correction", "quote": quote,
            "evidence": "Timing is not supported by the saved weekly totals"}]})], stop_reason="tool_use")
    writer, requests = writer_factory([
        _message([_text("Team A won on Monday.")]), rejected("on Monday"),
        _message([_passage_edits([{"passage_id": "p1", "after": "Team A won late."}])], stop_reason="tool_use"),
        rejected("late"),
        _message([_passage_edits([{"passage_id": "p1", "after": "Team A scored 158 points."}])], stop_reason="tool_use"),
        _message([_verdict()], stop_reason="tool_use") if final_approved else rejected("158 points"),
    ], max_calls=6)
    if final_approved:
        assert writer.write(_facts()) == "Team A scored 158 points."
    else:
        with pytest.raises(ValueError, match="2 corrections.*refusing publication"):
            writer.write(_facts())
    assert len(requests) == 6
    assert requests[4]["messages"][0] == requests[0]["messages"][0]
    assert "Team A scored 158 points." in json.dumps(requests[5])


@pytest.mark.parametrize("approved", [True, False])
def test_grounded_swap_evidence_keeps_each_owner_and_player_pair_together(writer_factory, approved):
    # Mutation: index swaps by slot alone and apply another owner's margin, or bypass a final rejection.
    # Reduced production capture: only owner names have been replaced; these two
    # distinct QB swaps were conflated by the final factual reviewer.
    from sleeper_dynasty.llm.recap_packet import ArchivedPacket

    packet = _facts().to_dict()
    packet["bench_regret"] = [
        {"owner": "Owner A", "points_left_on_bench": 44.7, "legal_swaps": [{
            "benched_player": {"owner": "Owner A", "player": "Aaron Rodgers (QB, PIT)", "points": 21.02, "position": "QB"},
            "started_player": {"owner": "Owner A", "player": "Jacoby Brissett (QB, ARI)", "points": 7.92, "position": "QB"},
            "slot": "QB", "points_gained": 13.1,
            "matchup_effect": {"margin": 11.42, "opponent_points": 129.9, "result": "win", "team_points": 141.32},
        }]},
        {"owner": "Owner B", "points_left_on_bench": 31.2, "legal_swaps": [{
            "benched_player": {"owner": "Owner B", "player": "C.J. Stroud (QB, HOU)", "points": 29.98, "position": "QB"},
            "started_player": {"owner": "Owner B", "player": "Patrick Mahomes (QB, KC)", "points": 11.48, "position": "QB"},
            "slot": "QB", "points_gained": 18.5,
            "matchup_effect": {"margin": 28.96, "opponent_points": 108.22, "result": "win", "team_points": 137.18},
        }]},
    ]
    original = "Owner B starting Stroud instead of Mahomes would have made it an 18-point win."
    corrected = original.replace("an 18-point", "a 29-point")
    verdict = {"approved": approved, "checks": [] if approved else [{
        "status": "needs_correction", "quote": "29-point win", "evidence": "Incorrect reviewer selected Owner A's 11.42 margin"}]}
    writer, requests = writer_factory([
        _message([_text(original)]),
        _message([_verdict({"approved": False, "checks": [{
            "status": "needs_correction", "quote": "18-point win", "evidence": "Owner B's Stroud/Mahomes swap margin is 28.96"}]})], stop_reason="tool_use"),
        _message([_passage_edits([{"passage_id": "p1", "after": corrected}])], stop_reason="tool_use"),
        _message([_verdict(verdict)], stop_reason="tool_use"),
    ])
    if approved:
        assert writer.write(ArchivedPacket(packet)) == corrected
    else:
        with pytest.raises(ValueError, match="after one correction"):
            writer.write(ArchivedPacket(packet))
    review_index = json.loads(requests[1]["messages"][0]["content"])["claim_evidence"]
    assert [(row["source_id"], row["owner"], row["benched_player"]["player"],
             row["started_player"]["player"], row["matchup_effect"]["margin"])
            for row in review_index["single_swaps"]] == [
        ("/facts/bench_regret/0/legal_swaps/0", "Owner A", "Aaron Rodgers (QB, PIT)", "Jacoby Brissett (QB, ARI)", 11.42),
        ("/facts/bench_regret/1/legal_swaps/0", "Owner B", "C.J. Stroud (QB, HOU)", "Patrick Mahomes (QB, KC)", 28.96),
    ]
    draft_index = json.loads(requests[0]["messages"][0]["content"][0]["text"].split("CLAIM EVIDENCE INDEX:\n```json\n")[1].split("\n```")[0])
    assert draft_index == review_index == json.loads(requests[3]["messages"][0]["content"])["claim_evidence"]
    assert requests[2]["messages"][0] == requests[0]["messages"][0]
    assert len(requests) == 4


@pytest.mark.parametrize("kickoff,published,relation", [
    ("2026-10-09T00:15:00+00:00", "2026-10-09T13:35:58.591000+00:00", "after"),
    ("2026-10-09T00:15:00+00:00", "2026-10-08T23:15:00+00:00", "before"),
    ("2026-10-09T00:15:00+00:00", "2026-10-08T18:15:00-06:00", "at"),
    (None, "2026-10-09T13:35:58.591000+00:00", "unknown"),
    ("2026-10-09T00:15:00", "2026-10-09T13:35:58+00:00", "unknown"),
    ("2026-10-09T00:15:00", "2026-10-09T13:35:58", "unknown"),
    ("2026-10-09T00:15:00+00:00", "unknown", "unknown"),
])
def test_grounded_news_timing_uses_player_kickoff_without_inventing_missing_times(writer_factory, kickoff, published, relation):
    # Mutation: compare reporting with the Sunday fantasy matchup, or treat unknown/naive times as known.
    # Reduced production capture: an in-game Thursday injury was reported Friday;
    # the reviewer incorrectly used the later Sunday fantasy matchup kickoff.
    from sleeper_dynasty.llm.recap_packet import ArchivedPacket

    packet = _facts().to_dict()
    packet["source_snapshot"] = {"kickoff_at": "2026-10-11T17:00:00+00:00"}
    packet["lineups"] = [{"owner": "Owner A", "starters": [{"player": "CeeDee Lamb (WR, DAL)", "points": 10}]}]
    packet["player_context"] = {"players": [{
        "player": "CeeDee Lamb", "position": "WR", "started": True, "kickoff_at": kickoff,
        "usage": {"limited_opportunity": False, "offense_share": 0.57, "offense_snaps": 34},
        "news": [{"published_at": published, "observed_at": "2026-10-09T14:15:22.040400+00:00",
                  "publisher": "FantasyPros", "text": "CeeDee Lamb injured his quad during Thursday night loss...",
                  "title": "CeeDee Lamb sustains quad injury Thursday night"}],
    }]}
    writer, requests = writer_factory([
        _message([_text("Lamb contributed 10 fantasy points.")]),
        _message([_verdict()], stop_reason="tool_use"),
    ])
    writer.write(ArchivedPacket(packet))
    timing = json.loads(requests[1]["messages"][0]["content"])["claim_evidence"]["player_news_timing"]
    assert timing == [{"source_id": "/facts/player_context/players/0/news/0", "player": "CeeDee Lamb",
                       "player_kickoff_at": kickoff, "published_at": published,
                       "publication_relative_to_player_kickoff": relation}]
    # Unknown kickoff must not expose report prose for the writer to turn into
    # actionable pregame advice. The reviewer still receives original evidence.
    draft_input = requests[0]["messages"][0]["content"][0]["text"]
    if relation == "unknown":
        assert "CeeDee Lamb injured his quad" not in draft_input
        assert "news_omitted" in draft_input
    else:
        assert "CeeDee Lamb injured his quad" in draft_input


@pytest.mark.parametrize("approved", [True, False])
@pytest.mark.parametrize("unknown_usage", [None, {}, {"offense_snaps": None}])
def test_usage_evidence_preserves_units_in_draft_repair_and_both_reviews(writer_factory, approved, unknown_usage):
    # Mutation: relabel snaps as routes, omit zero, dereference null usage, or supply units only to the final reviewer.
    from sleeper_dynasty.llm.recap_packet import ArchivedPacket

    packet = _facts().to_dict()
    packet["lineups"] = [{"owner": "Team A", "starters": [
        {"player": "Juwan Johnson (TE, NO)", "points": 0},
        {"player": "Synthetic Receiver (WR, TEST)", "points": 0},
        {"player": "Unknown Usage (WR, TEST)", "points": 0},
    ]}]
    # Reduced production evidence: Johnson's 42 is offense_snaps, not routes.
    # Synthetic rows distinguish actual zero from null and absent usage.
    packet["player_context"] = {"players": [
        {"player": "Juwan Johnson", "usage": {"offense_snaps": 42}, "news": []},
        {"player": "Synthetic Receiver", "usage": {"offense_snaps": 0, "offense_share": 0.25}, "news": []},
        {"player": "Unknown Usage", "usage": unknown_usage, "news": []},
    ]}
    original = "Johnson ran 42 routes."
    corrected = "Johnson played 42 offensive snaps."
    rejection = {"approved": False, "checks": [{
        "quote": original, "evidence": "usage.offense_snaps is 42 offensive snaps; route count is unknown.",
        "status": "needs_correction",
    }]}
    writer, requests = writer_factory([
        _message([_text(original)]),
        _message([_verdict(rejection)], stop_reason="tool_use"),
        _message([_passage_edits([{"passage_id": "p1", "after": corrected if approved else original}])], stop_reason="tool_use"),
        _message([_verdict() if approved else _verdict(rejection)], stop_reason="tool_use"),
    ])
    if approved:
        assert writer.write(ArchivedPacket(packet)) == corrected
    else:
        with pytest.raises(ValueError, match="after one correction"):
            writer.write(ArchivedPacket(packet))
    assert len(requests) == 4
    draft_index = json.loads(requests[0]["messages"][0]["content"][0]["text"].split("CLAIM EVIDENCE INDEX:\n```json\n")[1].split("\n```")[0])
    assert draft_index["version"] == "recap-owner-evidence-v5"
    assert draft_index["player_usage"] == [
        {"source_id": "/facts/player_context/players/0/usage/offense_snaps", "player": "Juwan Johnson",
         "field": "offense_snaps", "value": 42, "unit": "offensive_snaps"},
        {"source_id": "/facts/player_context/players/1/usage/offense_snaps", "player": "Synthetic Receiver",
         "field": "offense_snaps", "value": 0, "unit": "offensive_snaps"},
        {"source_id": "/facts/player_context/players/1/usage/offense_share", "player": "Synthetic Receiver",
         "field": "offense_share", "value": 0.25, "unit": "fraction_of_team_offensive_snaps"},
    ]
    assert draft_index == json.loads(requests[1]["messages"][0]["content"])["claim_evidence"]
    assert draft_index == json.loads(requests[3]["messages"][0]["content"])["claim_evidence"]
    assert requests[2]["messages"][0] == requests[0]["messages"][0]
    for request in requests:
        prompt = request["system"][1]["text"]
        assert prompt.startswith("recap-owner-evidence-v5\n")
        assert "never routes run, touches, targets, carries, or receptions" in prompt
        assert "Audit ALL usage claims in the first review" in prompt


@pytest.mark.parametrize("contract", ["legacy", "passage", "grounded_v1"])
def test_saved_writer_receipts_remain_byte_exact_after_repair_entrypoint_added(writer_factory, contract):
    # Mutation: change any existing write() request while adding the saved-draft entrypoint.
    from sleeper_dynasty.llm.recap_packet import ArchivedPacket

    fixture = json.loads((Path(__file__).parents[1] / f"api/tests/fixtures/synthetic_analyst_{contract}_receipts.json").read_text())
    writer, requests = writer_factory(fixture["responses"], grounding_version="recap-owner-evidence-v1",
        legacy_repair=contract == "legacy", grounded_review=contract == "grounded_v1")
    facts = ArchivedPacket(fixture["payload"]["edition"]["facts"])
    if fixture.get("expected_error"):
        with pytest.raises(ValueError, match=fixture["expected_error"]):
            writer.write(facts)
    else:
        assert writer.write(facts) == fixture["expected"]
    assert [{key: value for key, value in request.items() if key != "_timeout"} for request in requests] == fixture["requests"]


@pytest.mark.parametrize("version", ["recap-owner-evidence-v1", "recap-owner-evidence-v2"])
@pytest.mark.parametrize("legacy_repair", [True, False])
def test_saved_repair_sends_only_passage_correction_then_independent_review(writer_factory, version, legacy_repair):
    # Mutation: redraft the article, use the review model for stage one, or change untouched passages.
    original = "# Week 9\n\nTeam A scored **185 points**.\n\nThe supported closing joke survives."
    corrected = original.replace("185", "158")
    findings = [{"quote": "185 points", "evidence": "high_scorer.points is 158"}]
    writer, requests = writer_factory([
        _message([_passage_edits([{"passage_id": "p2", "after": "Team A scored **158 points**."}])], stop_reason="tool_use"),
        _message([_verdict()], stop_reason="tool_use"),
    ], model="claude-haiku-4-5-20251001", review_model="claude-sonnet-4-6",
       grounding_version=version, legacy_repair=legacy_repair)
    outlook = OutlookFacts(10, [], [], [], [])
    assert writer.repair_saved(_facts(), original, findings, lore="Team A is my brother.", outlook=outlook) == corrected
    assert len(requests) == 2
    assert [r["model"] for r in requests] == ["claude-haiku-4-5-20251001", "claude-sonnet-4-6"]
    assert [r["tool_choice"]["name"] for r in requests] == ["submit_recap_passage_edits", "submit_recap_review"]
    assert all(r["system"][1]["text"].startswith(version + "\n") for r in requests)
    repair = requests[0]
    schema = repair["tools"][0]["input_schema"]["properties"]["edits"]["items"]["properties"]
    assert schema["passage_id"]["enum"] == ["p1", "p2", "p3"]
    repair_text = repair["messages"][-1]["content"]
    assert json.loads(repair_text.split("DRAFT PASSAGES:\n")[1].split("\nEDITOR FINDINGS:")[0]) == [
        {"passage_id": "p1", "text": "# Week 9"}, {"passage_id": "p2", "text": "Team A scored **185 points**."},
        {"passage_id": "p3", "text": "The supported closing joke survives."},
    ]
    assert json.loads(repair_text.split("EDITOR FINDINGS:\n")[1]) == findings
    review = json.loads(requests[1]["messages"][0]["content"])
    assert review["draft"] == corrected
    assert review["facts"] == _facts().to_dict()
    assert review["outlook"] == outlook.to_dict()
    assert review["lore"] == "Team A is my brother."
    assert "EDITOR FINDINGS" not in requests[1]["messages"][0]["content"]


@pytest.mark.parametrize("review", [
    _message([_verdict({"approved": False, "checks": [{"quote": "158", "evidence": "Still unsupported", "status": "needs_correction"}]})], stop_reason="tool_use"),
    _message([_verdict({"approved": True, "checks": [{"quote": "158", "evidence": "Contradiction", "status": "needs_correction"}]})], stop_reason="tool_use"),
    _message([_text("Approved")]),
])
def test_saved_repair_rejected_or_malformed_review_never_gets_third_call(writer_factory, review):
    # Mutation: ignore the final verdict or fall back to write() for another correction.
    writer, requests = writer_factory([
        _message([_passage_edits([{"passage_id": "p1", "after": "Team A scored 158."}])], stop_reason="tool_use"), review,
    ])
    with pytest.raises(ValueError, match="refusing publication"):
        writer.repair_saved(_facts(), "Team A scored 185.", [{"quote": "185", "evidence": "Saved total is 158"}])
    assert len(requests) == 2


@pytest.mark.parametrize("draft,findings", [
    ("", [{"quote": "a", "evidence": "b"}]), (None, [{"quote": "a", "evidence": "b"}]),
    ("Saved draft", []), ("Saved draft", None), ("Saved draft", [{}]),
    ("Saved draft", [{"quote": " ", "evidence": "b"}]),
    ("Saved draft", [{"quote": "a", "evidence": None}]),
    ("Saved draft", [{"quote": "a", "evidence": "b", "status": "needs_correction"}]),
    ("Saved draft", [{"quote": "a", "evidence": "b"}] * 13),
])
def test_saved_repair_invalid_source_material_stops_before_provider(writer_factory, draft, findings):
    # Mutation: send an empty draft or unchecked editor input to a paid repair.
    writer, requests = writer_factory([])
    with pytest.raises(ValueError, match="Saved recap repair requires"):
        writer.repair_saved(_facts(), draft, findings)
    assert requests == []


@pytest.mark.parametrize("repair", [
    _passage_edits([{"passage_id": "p9", "after": "Wrong target"}]),
    _passage_edits([{"passage_id": "p1", "after": "a"}, {"passage_id": "p1", "after": "b"}]),
    _passage_edits([{"passage_id": "p1", "after": ""}]),
    _edits("Saved draft", "New draft"),
])
def test_saved_repair_invalid_edits_never_request_review(writer_factory, repair):
    # Mutation: accept unknown/duplicate IDs, a removed whole article, or the old literal-edit contract.
    writer, requests = writer_factory([_message([repair], stop_reason="tool_use")])
    with pytest.raises(ValueError, match="refusing publication|review the saved response"):
        writer.repair_saved(_facts(), "Saved draft", [{"quote": "Saved", "evidence": "Use supported facts"}])
    assert len(requests) == 1


def test_saved_repair_missing_matchup_stops_before_review(writer_factory):
    # Mutation: publish a repaired article that still omits a required matchup.
    from sleeper_dynasty.models.recap import MatchupRecap
    facts = _facts()
    facts.matchups = [MatchupRecap("Alice", "Bob", 25, 15, 10, False, False)]
    writer, requests = writer_factory([_message([_passage_edits([])], stop_reason="tool_use")])
    with pytest.raises(ValueError, match="missing recap matchup"):
        writer.repair_saved(facts, "Saved draft", [{"quote": "Saved", "evidence": "Add missing matchup"}])
    assert len(requests) == 1


def test_saved_repair_scoring_guard_still_overrules_approving_review(writer_factory):
    # Mutation: return a reviewed saved-draft repair without checking the canonical scoring contract.
    from sleeper_dynasty.llm.recap_packet import ArchivedPacket
    packet = _facts().to_dict()
    packet["source_snapshot"] = {"scoring_settings": {"rec": "1"}}
    writer, requests = writer_factory([
        _message([_passage_edits([])], stop_reason="tool_use"),
        _message([_verdict()], stop_reason="tool_use"),
    ])
    with pytest.raises(ValueError, match="scoring.*refusing publication"):
        writer.repair_saved(ArchivedPacket(packet), "This half-PPR league.", [{"quote": "half-PPR", "evidence": "Saved scoring is full PPR"}])
    assert len(requests) == 2


def test_passage_correction_preserves_other_prose_and_reviews_complete_result(writer_factory):
    # Mutation: require the model to reproduce source text, or skip review after an indexed repair.
    draft = "# Week 9\n\nHe ran **39 snaps**, and this is what he does with them.\n\nAn unchanged joke."
    corrected = "# Week 9\n\nHe ran **63 snaps**, and this is what he does with them.\n\nAn unchanged joke."
    writer, requests = writer_factory([
        _message([_text(draft)]),
        _message([_verdict({"approved": False, "checks": [
            {"status": "needs_correction", "quote": "He ran 39 snaps", "evidence": "usage.offense_snaps is 63"}
        ]})], stop_reason="tool_use"),
        _message([_passage_edits([{"passage_id": "p2", "after": "He ran **63 snaps**, and this is what he does with them."}])], stop_reason="tool_use"),
        _message([_verdict()], stop_reason="tool_use"),
    ])
    assert writer.write(_facts()) == corrected
    repair = requests[2]
    assert repair["tool_choice"]["name"] == "submit_recap_passage_edits"
    schema = repair["tools"][0]["input_schema"]["properties"]["edits"]["items"]["properties"]
    assert schema["passage_id"]["enum"] == ["p1", "p2", "p3"]
    passages = json.loads(repair["messages"][-1]["content"].split("DRAFT PASSAGES:\n")[1].split("\nEDITOR FINDINGS:")[0])
    assert passages == [{"passage_id": "p1", "text": "# Week 9"},
                        {"passage_id": "p2", "text": "He ran **39 snaps**, and this is what he does with them."},
                        {"passage_id": "p3", "text": "An unchanged joke."}]
    assert json.loads(requests[3]["messages"][0]["content"])["draft"] == corrected
    assert len(requests) == 4


@pytest.mark.parametrize("edits", [
    [{"passage_id": "p0", "after": "Wrong target"}],
    [{"passage_id": "p3", "after": "Wrong target"}],
    [{"passage_id": 1, "after": "Wrong type"}],
    [{"passage_id": "p1", "after": "First"}, {"passage_id": "p1", "after": "Second"}],
    [{"passage_id": "p1", "after": 12}],
    [{"passage_id": "p1", "after": "Text", "before": "Ignored"}],
])
def test_invalid_passage_targets_stop_before_review(writer_factory, edits):
    # Mutation: guess unknown targets, coerce malformed edits, or allow multiple replacements for one passage.
    writer, requests = writer_factory([
        _message([_text("Wrong score.\n\nKeep this.")]),
        _message([_verdict({"approved": False, "checks": [
            {"status": "needs_correction", "quote": "Wrong score", "evidence": "Wrong"}
        ]})], stop_reason="tool_use"),
        _message([_passage_edits(edits)], stop_reason="tool_use"),
    ])
    with pytest.raises(ValueError, match="Analyst repair"):
        writer.write(_facts())
    assert len(requests) == 3


def test_passage_edits_handle_identical_paragraphs_and_keep_original_spacing():
    # Mutation: replace all matching text or reconstruct the article with normalized separators.
    from sleeper_dynasty.llm.recap_writer import apply_recap_edits
    response = anthropic.types.Message.model_validate(_message([_passage_edits([
        {"passage_id": "p3", "after": "Corrected."},
        {"passage_id": "p1", "after": "# Revised"},
    ])], stop_reason="tool_use"))
    assert apply_recap_edits("# Original\n\nSame.\n\n\nSame.\n", response) == "# Revised\n\nSame.\n\n\nCorrected.\n"


def test_explicit_approval_can_include_supported_audit_checks(writer_factory):
    # Mutation: reject an approved audit merely because it documents supported claims.
    writer, _ = writer_factory([
        _message([_text("Team A scored 158 points.")]),
        _message([_verdict({"approved": True, "checks": [
            {"status": "supported", "quote": "158 points", "evidence": "high_scorer.points is 158"}
        ]})], stop_reason="tool_use"),
    ])
    assert writer.write(_facts()) == "Team A scored 158 points."


def test_only_explicit_errors_reach_repair_while_supported_checks_are_preserved(writer_factory):
    # Mutation: treat all audit notes as errors or silently discard a needs_correction check.
    writer, requests = writer_factory([
        _message([_text("Team A scored 185 points. Team A leads.")]),
        _message([_verdict({"approved": False, "checks": [
            {"status": "supported", "quote": "Team A leads", "evidence": "high_scorer.owner is Team A"},
            {"status": "needs_correction", "quote": "185 points", "evidence": "high_scorer.points is 158"}
        ]})], stop_reason="tool_use"),
        _message([_edits("185 points", "158 points")], stop_reason="tool_use"),
        _message([_verdict()], stop_reason="tool_use"),
    ])
    assert writer.write(_facts()) == "Team A scored 158 points. Team A leads."
    feedback = json.loads(requests[2]["messages"][-1]["content"].split("EDITOR FINDINGS:\n")[1])
    assert feedback == [{"quote": "185 points", "evidence": "high_scorer.points is 158"}]


@pytest.mark.parametrize("approved,status", [(True, "needs_correction"), (False, "supported"), (True, "unknown")])
def test_approval_must_agree_with_explicit_claim_status(writer_factory, approved, status):
    # Mutation: guess approval from evidence prose or ignore an unsupported claim's status.
    writer, _ = writer_factory([
        _message([_text("Team A scored 158 points.")]),
        _message([_verdict({"approved": approved, "checks": [
            {"status": status, "quote": "158 points", "evidence": "Supported; no error; removing this."}
        ]})], stop_reason="tool_use"),
    ])
    with pytest.raises(ValueError, match="review.*not approve"):
        writer.write(_facts())


def test_corrections_patch_only_the_quoted_error(writer_factory):
    # Mutation: ask for another full draft and lose already-correct prose during correction.
    writer, requests = writer_factory([
        _message([_text("# Week 9\n\nTeam A scored 185 points.\n\nAn excellent closing joke.")]),
        _message([_verdict({"approved": False, "checks": [
            {"status": "needs_correction", "quote": "185 points", "evidence": "high_scorer.points is 158"}
        ]})], stop_reason="tool_use"),
        _message([_edits("185 points", "158 points")], stop_reason="tool_use"),
        _message([_verdict()], stop_reason="tool_use"),
    ])
    assert writer.write(_facts()) == "# Week 9\n\nTeam A scored 158 points.\n\nAn excellent closing joke."
    assert requests[2]["tool_choice"]["name"] == "submit_recap_passage_edits"


@pytest.mark.parametrize("edits", [
    [{"before": "Absent claim", "after": "Correction"}],
    [{"before": "points", "after": "scores"}],
    [{"before": "11", "after": "12"}],
    [{"before": "185 points", "after": "158 points"}, {"before": "185", "after": "158"}],
    [{"before": "185 points", "after": 158}],
])
def test_ambiguous_or_overlapping_edits_never_publish(writer_factory, edits):
    # Mutation: replace all matches, silently ignore missing edits, or corrupt overlapping passages.
    tool = _edits("", "")
    tool["input"]["edits"] = edits
    writer, requests = writer_factory([
        _message([_text("185 points, not 158 points. Opponent: 111.")]),
        _message([_verdict({"approved": False, "checks": [
            {"status": "needs_correction", "quote": "185 points", "evidence": "high_scorer.points is 158"}
        ]})], stop_reason="tool_use"),
        _message([tool], stop_reason="tool_use"),
    ])
    with pytest.raises(ValueError, match="Analyst repair"):
        writer.write(_facts())
    assert len(requests) == 3


@pytest.fixture
def writer_factory(monkeypatch):
    # Anthropic 1.x uses httpx2; older supported SDKs use httpx. Build the
    # transport with the installed SDK's public default client's HTTP package.
    http = import_module(
        next(
            base.__module__.split(".")[0]
            for base in anthropic.DefaultHttpxClient.__mro__
            if base.__name__ == "Client"
        )
    )
    clients = []

    real_client = anthropic.Anthropic

    def make(responses, *, cost_store=None, **writer_options):
        requests = []

        def handle(request):
            payload = json.loads(request.content)
            payload["_timeout"] = request.extensions.get("timeout")
            requests.append(payload)
            index = len(requests) - 1
            assert index < len(responses), "Unexpected paid retry"
            response = responses[index]
            if response == "timeout":
                raise http.ReadTimeout("Synthetic provider timeout", request=request)
            if isinstance(response, int):
                return http.Response(
                    response,
                    json={
                        "type": "error",
                        "error": {
                            "type": "rate_limit_error",
                            "message": "Synthetic provider failure",
                        },
                    },
                )
            if callable(response):
                response = response(payload)
            return http.Response(200, json=response)

        monkeypatch.setattr(
            anthropic,
            "Anthropic",
            lambda **kwargs: real_client(
                **kwargs,
                http_client=anthropic.DefaultHttpxClient(
                    transport=http.MockTransport(handle)
                ),
            ),
        )
        writer = RecapWriter(
            client=anthropic.Anthropic(api_key="test", max_retries=0, timeout=300),
            cost_store=cost_store, league_id="test-league", **writer_options
        )
        clients.append(writer._client)
        return writer, requests

    yield make
    for client in clients:
        client.close()


def test_default_persona_loads_and_has_hard_rules():
    # Mutation: load a persona that omits the facts-only contract.
    persona = load_default_persona()
    assert "ONLY the facts" in persona
    assert "The Analyst" in persona


def test_lore_template_loads():
    # Mutation: load the persona in place of the editable lore template.
    assert "League Lore" in load_lore_template()


def test_build_messages_includes_facts_and_lore(writer_factory):
    # Mutation: drop lore or the facts packet from the request.
    writer, _ = writer_factory([])
    system, messages = writer.build_request(_facts(), lore="Team A is my brother.")
    assert "my brother" in str(messages)
    assert "158.0" in str(messages)
    assert "The Analyst" in str(system)


def test_build_request_includes_outlook_when_present(writer_factory):
    # Mutation: ignore the supplied upcoming-week outlook.
    writer, _ = writer_factory([])
    outlook = OutlookFacts(week=10, matchups=[], byes=[], weather=[], playoff_stakes=[])
    _, messages = writer.build_request(_facts(), lore=None, outlook=outlook)
    assert "OUTLOOK" in str(messages)
    outlook_json = messages[0]["content"][0]["text"].split("```json\n")[2].split("\n```")[0]
    assert json.loads(outlook_json)["week"] == 10


def test_news_filter_keeps_original_source_ids_and_saved_v2_requests():
    from copy import deepcopy
    from sleeper_dynasty.llm.recap_writer import _writing_packet, _claim_evidence
    packet = {"bench_regret": [], "player_context": {"players": [{
        "player": "Synthetic Player", "kickoff_at": "2026-10-25T17:00:00+00:00",
        "news": [{"text": "Unqualified claim", "published_at": None},
                 {"text": "Qualified report", "published_at": "2026-10-25T16:00:00+00:00"}]}]}}
    original = deepcopy(packet)
    filtered = _writing_packet(packet, "recap-owner-evidence-v3")
    assert "Unqualified claim" not in str(filtered)
    assert filtered["player_context"]["players"][0]["news"][1]["text"] == "Qualified report"
    assert _claim_evidence(filtered, "recap-owner-evidence-v3") == _claim_evidence(packet, "recap-owner-evidence-v3")
    assert _writing_packet(packet, "recap-owner-evidence-v2") == original == packet


def test_unknown_news_is_omitted_from_writer_but_preserved_for_review(writer_factory):
    # Mutation: leak unknown chronology to writing or discard immutable review evidence.
    facts = _facts()
    facts.lineups = [{"owner": "Team A", "starters": [{"player": "Test QB (QB, FA)", "points": 3}]}]
    facts.player_context = {"players": [{"player": "Test QB", "usage": {"offense_snaps": 3},
                                         "news": [{"text": "Left with knee injury"}]}]}
    writer, requests = writer_factory([
        _message([_text("The quarterback's injury shortened his outing.")]),
        _message([_verdict()], stop_reason="tool_use"),
    ])
    writer.write(facts)
    draft_text = requests[0]["messages"][0]["content"][0]["text"]
    draft = json.loads(draft_text.split("```json\n")[1].split("\n```")[0])
    review = json.loads(requests[1]["messages"][0]["content"])
    assert "text" not in draft["player_context"]["players"][0]["news"][0]
    assert "news_omitted" in draft["player_context"]["players"][0]["news"][0]
    assert draft["player_context"]["players"][0]["usage"] == {"offense_snaps": 3}
    assert facts.player_context == review["facts"]["player_context"]


def test_editorial_packet_keeps_relevant_context_without_all_rostered_players(writer_factory):
    # Mutation: send every rostered player's news, or discard context for a featured bench substitution.
    from copy import deepcopy

    from sleeper_dynasty.models.recap import BenchRegret, PlayerLine
    facts = _facts()
    facts.lineups = [{"owner": "Team A", "starters": [
        {"player": f"Player {i} (RB, FA)", "owner": "Team A", "points": i} for i in range(10)
    ]}]
    facts.bench_regret = [BenchRegret("Team A", 10, PlayerLine("Bench", "Team A", 10),
        PlayerLine("Player 4", "Team A", 4), [{"benched_player": {"player": "Bench (RB, FA)"},
                                               "started_player": {"player": "Player 4 (RB, FA)"}}])]
    facts.player_context = {"players": [
        {"player": f"Player {i}", "usage": {"offense_snaps": i}, "news": []} for i in range(50)
    ] + [{"player": "Bench", "news": [{"text": "Dated report", "published_at": "2026-09-28"}]}],
        "sources": [{"title": "Separate archive footer"}], "note": "Missing usage is unknown"}
    before = deepcopy(facts.to_dict())
    writer, requests = writer_factory([
        _message([_text("Team A got 9 points from Player 9.")]),
        _message([_verdict()], stop_reason="tool_use"),
    ])
    writer.write(facts, lore="Team A is my brother.")
    draft = json.loads(requests[0]["messages"][0]["content"][0]["text"].split("```json\n")[1].split("\n```")[0])
    review = json.loads(requests[1]["messages"][0]["content"])
    assert {p["player"] for p in draft["player_context"]["players"]} == {
        "Player 0", "Player 7", "Player 8", "Player 9", "Player 4", "Bench"}
    from sleeper_dynasty.llm.recap_writer import _writing_packet
    assert draft == _writing_packet(review["facts"], "recap-owner-evidence-v3")
    assert review["lore"] == "Team A is my brother."
    assert "sources" not in draft["player_context"]
    assert facts.to_dict() == before
    assert requests[0]["model"] == "claude-sonnet-4-6"


@pytest.mark.parametrize("missing", ["recap", "preview"])
def test_approved_but_incomplete_article_is_not_a_full_roast(writer_factory, missing):
    # Mutation: accept a factually approved article that leaves out an entire matchup.
    from sleeper_dynasty.models.recap import MatchupPreview, MatchupRecap
    facts = _facts()
    facts.matchups = [MatchupRecap("Alice", "Bob", 25, 15, 10, False, False)]
    outlook = OutlookFacts(10, [MatchupPreview("Cam", "Dee", 30, 20, "Cam", 10)], [], [], [])
    text = "# Week 9\n\nClosing joke."
    if missing != "recap":
        text += "\n\n### Alice 25 — Bob 15\n\nA crushing loss."
    if missing != "preview":
        text += "\n\n### Cam vs. Dee\n\nCam is projected ahead."
    writer, _ = writer_factory([_message([_text(text)]), _message([_edits(text, text)], stop_reason="tool_use")])
    with pytest.raises(ValueError, match="missing.*matchup"):
        writer.write(facts, outlook=outlook)


def test_matchup_coverage_uses_rendered_names_and_distinct_preview_headings(writer_factory):
    # Mutation: compare raw KTC owner names to sanitized text, or reuse a recap as its own preview.
    from sleeper_dynasty.models.recap import MatchupPreview, MatchupRecap
    facts = _facts()
    facts.matchups = [MatchupRecap("Team KTC", "Bob", 25, 15, 10, False, False)]
    outlook = OutlookFacts(10, [MatchupPreview("Team KTC", "Bob", 30, 20, "Team KTC", 10)], [], [], [])
    recap = "### Team KTC 25 vs. Bob 15\n\nA crushing loss."
    preview = "\n\n### Team KTC vs. Bob\n\nNext week's projections: 30 vs. 20."
    writer, _ = writer_factory([_message([_text(recap + preview)]), _message([_verdict()], stop_reason="tool_use")])
    assert "Team trade value" in writer.write(facts, outlook=outlook)
    unchanged = recap.replace("KTC", "trade value")
    incomplete, _ = writer_factory([_message([_text(recap)]), _message([_edits(unchanged, unchanged)], stop_reason="tool_use")])
    with pytest.raises(ValueError, match="missing preview matchup"):
        incomplete.write(facts, outlook=outlook)


def test_coverage_accepts_typography_and_decorative_emoji_changes():
    from sleeper_dynasty.llm.recap_writer import require_matchup_coverage
    from sleeper_dynasty.models.recap import MatchupRecap
    facts = _facts()
    facts.matchups = [MatchupRecap("Yorkin’ It", "Hawgs 🐖🧴", 25, 15, 10, False, False)]
    require_matchup_coverage("### Yorkin' It def. Hawgs 🐖🧤", facts, None)
    with pytest.raises(ValueError, match="missing recap matchup"):
        require_matchup_coverage("### Yorkin' It def. Hogs", facts, None)

    # Teams distinguished only by emoji must retain their separate identities.
    facts.matchups = [MatchupRecap("Hawgs 🐖", "Hawgs 🧴", 25, 15, 10, False, False)]
    with pytest.raises(ValueError, match="missing recap matchup"):
        require_matchup_coverage("### Hawgs 🐖 def. Hawgs 🐖", facts, None)


@pytest.mark.parametrize("approved", [True, False])
def test_missing_sections_share_single_repair_and_require_factual_review(writer_factory, approved):
    from sleeper_dynasty.models.recap import MatchupPreview, MatchupRecap
    facts = _facts()
    facts.matchups = [MatchupRecap("Alice", "Bob", 25, 15, 10, False, False)]
    outlook = OutlookFacts(10, [MatchupPreview("Cam", "Dee", 30, 20, "Cam", 10)], [], [], [])
    original = "# Week 9\n\nClosing joke."
    fixed = original + "\n### Alice 25 vs. Bob 15\nAlice won.\n### Cam vs. Dee\nCam is projected ahead."
    def repair(request):
        feedback = request["messages"][-1]["content"]
        assert "missing recap matchup: Alice / Bob" in feedback
        assert "missing preview matchup: Cam / Dee" in feedback
        assert "WHOLE draft" in feedback and "every related margin" in feedback
        return _message([_edits(original, fixed)], stop_reason="tool_use")
    verdict = {"approved": approved, "checks": [] if approved else [
        {"quote": "Alice won", "evidence": "Synthetic rejection", "status": "needs_correction"}]}
    writer, requests = writer_factory([_message([_text(original)]), repair,
        _message([_verdict(verdict)], stop_reason="tool_use")])
    if approved:
        assert writer.write(facts, outlook=outlook) == fixed
    else:
        with pytest.raises(ValueError, match="after one correction"):
            writer.write(facts, outlook=outlook)
    assert len(requests) == 3


def test_write_requires_structured_review_and_returns_sanitized_draft(writer_factory):
    # Mutation: request unstructured JSON text, or parse review text instead of tool input.
    def review_response(request):
        assert request["tool_choice"] == {"type": "tool", "name": "submit_recap_review"}
        tool = request["tools"][0]
        assert tool["name"] == "submit_recap_review"
        assert set(tool["input_schema"]["required"]) == {"approved", "checks"}
        evidence = json.loads(request["messages"][0]["content"])
        assert evidence["facts"]["week"] == 9
        assert "KTC" not in evidence["draft"]
        return _message([_text("Review complete."), _verdict()], stop_reason="tool_use")

    writer, requests = writer_factory(
        [
            _message([_text("# Week 9\nTeam A leads KTC value.")]),
            review_response,
        ]
    )
    result = writer.write(_facts())
    assert result.startswith("# Week 9\nTeam A leads")
    assert "KTC" not in result
    assert "tools" not in requests[0]
    assert len(requests) == 2


@pytest.mark.parametrize('max_calls', [2, 4, 6])
def test_editorial_guard_repairs_approved_error_within_existing_allowance(writer_factory, max_calls):
    # Mutation: trust approval over deterministic evidence, or buy extra repair calls.
    from sleeper_dynasty.llm.recap_packet import ArchivedPacket
    packet = _facts().to_dict()
    packet['season'] = 2026
    writer, requests = writer_factory([
        _message([_text('In 2025. On purpose.')]),
        _message([_verdict()], stop_reason='tool_use'),
        _message([_passage_edits([{'passage_id': 'p1', 'after': 'In 2026. On purpose.'}])], stop_reason='tool_use'),
        _message([_verdict()], stop_reason='tool_use'),
    ], max_calls=max_calls)
    if max_calls == 2:
        with pytest.raises(ValueError, match='refusing publication'):
            writer.write(ArchivedPacket(packet))
        assert len(requests) == 2
    else:
        assert writer.write(ArchivedPacket(packet)) == 'In 2026. On purpose.'
        assert len(requests) == 4
        assert 'Current recap season is 2026' in json.dumps(requests[2])
        assert json.loads(requests[3]['messages'][0]['content'])['draft'] == 'In 2026. On purpose.'


def test_legacy_v4_does_not_buy_new_editorial_repair_calls(writer_factory):
    # Mutation: change replayed v4 requests or add a repair absent from saved receipts.
    writer, requests = writer_factory([
        _message([_text('In 2025. On purpose.')]),
        _message([_verdict()], stop_reason='tool_use'),
    ], grounding_version='recap-owner-evidence-v4')
    with pytest.raises(ValueError, match='editorial claim'):
        writer.write(_facts())
    assert len(requests) == 2
    assert 'editorial_scope' not in json.dumps(requests)
    assert requests[0]['system'][1]['text'].startswith('recap-owner-evidence-v4\n')


def test_saved_repair_cannot_publish_new_editorial_error(writer_factory):
    # Mutation: omit editorial validation from the saved-draft recovery entrypoint.
    writer, requests = writer_factory([
        _message([_passage_edits([{'passage_id': 'p1', 'after': 'In 2025. On purpose.'}])], stop_reason='tool_use'),
        _message([_verdict()], stop_reason='tool_use'),
    ])
    with pytest.raises(ValueError, match='refusing publication'):
        writer.repair_saved(_facts(), 'Wrong season.', [{'quote': 'Wrong season.', 'evidence': 'Remove the season.'}])
    assert len(requests) == 2


def test_full_length_recap_finishes_without_a_paid_retry(writer_factory):
    # Mutation: restore the 4096-token ceiling that truncates a 5000-token draft.
    def draft_response(request):
        if request["max_tokens"] < 5000:
            return _message(
                [_text("Partial recap")], stop_reason="max_tokens", output_tokens=4096
            )
        return _message([_text("Complete recap with sign-off.")], output_tokens=5000)

    writer, requests = writer_factory(
        [
            draft_response,
            _message([_verdict()], stop_reason="tool_use"),
        ]
    )
    assert writer.write(_facts()) == "Complete recap with sign-off."
    assert len(requests) == 2
    assert requests[1]["max_tokens"] >= 8192


def test_review_contract_bounds_findings_without_treating_feedback_as_approval(writer_factory):
    # Mutation: treat an ungrounded complaint as approval instead of requiring a fresh verdict.
    writer, requests = writer_factory([
        _message([_text("Team A scored 158 points.")]),
        _message([_verdict({"approved": False, "checks": [
            {"status": "needs_correction", "quote": "Team B scored 900 points", "evidence": "Not in the facts"}
        ]})], stop_reason="tool_use"),
        _message([{"type": "tool_use", "id": "toolu_edit", "name": "submit_recap_edits",
                   "input": {"edits": []}}], stop_reason="tool_use"),
        _message([_verdict({"approved": False, "checks": []})], stop_reason="tool_use"),
    ])
    with pytest.raises(ValueError, match="review.*not approve"):
        writer.write(_facts())
    schema = requests[1]["tools"][0]["input_schema"]["properties"]["checks"]
    assert schema["maxItems"] == 12
    assert schema["items"]["properties"]["quote"]["maxLength"] == 240
    assert schema["items"]["properties"]["evidence"]["maxLength"] == 400
    assert len(requests) == 4


def test_paraphrased_review_feedback_reaches_repair_but_exact_edits_and_approval_are_required(writer_factory):
    # Mutation: fail before repair because the reviewer drops Markdown or paraphrases a claim.
    # Production capture: a full review mixed withdrawn findings and a paraphrased
    # standings error; rejecting the whole list prevented correcting the real error.
    writer, requests = writer_factory([
        _message([_text("Team A scored **185 points**. The closing joke survives.")]),
        _message([_verdict({"approved": False, "checks": [
            {"status": "needs_correction", "quote": "Team A scored 185 points", "evidence": "high_scorer.points is 158"},
            {"status": "needs_correction", "quote": "Closing joke", "evidence": "Figurative; supported; withdrawing this finding."},
        ]})], stop_reason="tool_use"),
        _message([_edits("**185 points**", "**158 points**")], stop_reason="tool_use"),
        _message([_verdict()], stop_reason="tool_use"),
    ])
    assert writer.write(_facts()) == "Team A scored **158 points**. The closing joke survives."
    assert len(requests) == 4


def test_followup_review_error_stops_instead_of_buying_second_repair(writer_factory):
    # Mutation: ignore the four-call default and purchase a second correction pair.
    writer, requests = writer_factory([
        _message([_text("Team A scored 185 points. Team B won.")]),
        _message([_verdict({"approved": False, "checks": [
            {"status": "needs_correction", "quote": "185 points", "evidence": "high_scorer.points is 158"}
        ]})], stop_reason="tool_use"),
        _message([_edits("185 points", "158 points")], stop_reason="tool_use"),
        _message([_verdict({"approved": False, "checks": [
            {"status": "needs_correction", "quote": "Team B won", "evidence": "No Team B matchup is supplied"}
        ]})], stop_reason="tool_use"),
        _message([_edits(" Team B won.", "")], stop_reason="tool_use"),
        _message([_verdict()], stop_reason="tool_use"),
    ])
    with pytest.raises(ValueError, match="after one correction"):
        writer.write(_facts())
    assert len(requests) == 4


def test_long_review_finishes_and_correction_uses_stronger_model(writer_factory):
    # Mutation: keep the 4096 review ceiling or send repair back to the failing draft model.
    def review(request):
        if request["max_tokens"] < 5000:
            return _message([_verdict()], stop_reason="max_tokens", output_tokens=4096)
        return _message([_verdict({"approved": False, "checks": [
            {"status": "needs_correction", "quote": "185 points", "evidence": "high_scorer.points is 158"}
        ]})], stop_reason="tool_use", output_tokens=5000)
    writer, requests = writer_factory([
        _message([_text("Team A scored 185 points.")]), review,
        _message([_edits("185 points", "158 points")], stop_reason="tool_use"),
        _message([_verdict()], stop_reason="tool_use"),
    ])
    assert writer.write(_facts()) == "Team A scored 158 points."
    assert requests[2]["model"] == "claude-sonnet-4-6"


def test_verbose_but_actionable_review_can_be_repaired(writer_factory):
    # Mutation: treat requested brevity as an accuracy gate and discard real errors.
    # Captured production shape: a 254-char exact quote and an 860-char explanation.
    quote = "Team A scored 185 points. " * 11
    finding = {"status": "needs_correction", "quote": quote.strip(), "evidence": "high_scorer.points is 158. " * 35}
    writer, requests = writer_factory([
        _message([_text(quote)]),
        _message([_verdict({"approved": False, "checks": [finding]})], stop_reason="tool_use"),
        _message([_edits(quote, "Team A scored 158 points.")], stop_reason="tool_use"),
        _message([_verdict()], stop_reason="tool_use"),
    ])
    assert writer.write(_facts()) == "Team A scored 158 points."
    assert len(requests) == 4


@pytest.mark.parametrize(
    "verdict",
    [
        {"approved": False, "checks": []},
        {"approved": True, "checks": ["Illegal QB for TE swap"]},
        {"approved": "true", "checks": []},
        {"approved": 1, "checks": []},
        {"approved": True},
        {"approved": False, "checks": [""]},
        {"approved": False, "checks": "Wrong score"},
        {"approved": False, "checks": [42]},
        {},
    ],
)
def test_review_failure_blocks_draft(writer_factory, verdict):
    # Mutation: accept any tool result without a strictly true approval and empty violations.
    writer, requests = writer_factory(
        [
            _message([_text("An unsupported claim.")]),
            _message([_verdict(verdict)], stop_reason="tool_use"),
        ]
    )
    with pytest.raises(ValueError, match="review.*not approve"):
        writer.write(_facts())
    assert len(requests) == 2


@pytest.mark.parametrize(
    "content,stop_reason",
    [
        ([_text('{"approved": true, "checks": []}')], "end_turn"),
        ([_text('```json\n{"approved": true, "checks": []}\n```')], "end_turn"),
        ([_verdict(name="wrong_tool")], "tool_use"),
        (
            [_verdict(), _verdict({"approved": False, "checks": ["Wrong score"]})],
            "tool_use",
        ),
        ([_verdict()], "end_turn"),
        ([], "tool_use"),
    ],
)
def test_missing_or_ambiguous_structured_review_blocks_publication(
    writer_factory, content, stop_reason
):
    # Mutation: trust text, an unrelated tool, or the first of conflicting verdicts.
    writer, requests = writer_factory(
        [
            _message([_text("Draft")]),
            _message(content, stop_reason=stop_reason),
        ]
    )
    with pytest.raises(ValueError, match="review.*structured verdict"):
        writer.write(_facts())
    assert len(requests) == 2


@pytest.mark.parametrize("stage", ["recap", "recap_review"])
def test_truncation_blocks_publication_and_still_records_cost(
    writer_factory, tmp_path, stage
):
    # Mutation: accept a truncated response, or check truncation before recording its cost.
    responses = [_message([_text("Draft")])]
    if stage == "recap_review":
        responses.append(_message([_verdict()], stop_reason="tool_use"))
    responses[-1]["stop_reason"] = "max_tokens"
    store = LlmCostStore(tmp_path)
    writer, requests = writer_factory(responses, cost_store=store)
    with pytest.raises(ValueError, match=f"{stage} was truncated"):
        writer.write(_facts())
    records = store.read_all()
    assert [r["writer"] for r in records] == (
        ["recap"] if stage == "recap" else ["recap", "recap_review"]
    )
    assert [r["cost_usd"] for r in records] == (
        [0.0069] if stage == "recap" else [0.0069, 0.0069]
    )
    assert len(requests) == len(responses)


def test_write_records_both_stages_in_real_cost_ledger(writer_factory, tmp_path):
    # Mutation: omit either stage's ledger record or lose its league attribution.
    store = LlmCostStore(tmp_path)
    writer, _ = writer_factory(
        [
            _message([_text("Draft")]),
            _message([_verdict()], stop_reason="tool_use"),
        ],
        cost_store=store,
    )
    writer.write(_facts())
    records = store.read_all()
    assert [r["writer"] for r in records] == ["recap", "recap_review"]
    assert all(r["league_id"] == "test-league" for r in records)
    assert [r["model"] for r in records] == [
        "claude-sonnet-4-6",
        "claude-sonnet-4-6",
    ]
    assert [r["cost_usd"] for r in records] == [0.0069, 0.0069]


def test_draft_and_independent_review_have_longer_deadlines(writer_factory):
    # Mutation: use the less capable draft model again, or retain the 90-second timeout.
    writer, requests = writer_factory(
        [
            _message([_text("Draft")]),
            _message([_verdict()], stop_reason="tool_use"),
        ]
    )
    writer.write(_facts())
    assert requests[0]["model"] == "claude-sonnet-4-6"
    assert requests[1]["model"] == "claude-sonnet-4-6"
    assert all(request["_timeout"]["read"] == 300 for request in requests)


def test_rejection_is_corrected_with_evidence_then_reviewed_again(
    writer_factory, tmp_path
):
    # Mutation: return the rejected draft, omit its feedback, or skip the corrected review.
    violations = [{"status": "needs_correction", "quote": "185 points", "evidence": "high_scorer.points is 158, not 185."}]
    store = LlmCostStore(tmp_path)
    writer, requests = writer_factory(
        [
            _message([_text("Team A scored 185 points.")]),
            _message(
                [_verdict({"approved": False, "checks": violations})],
                stop_reason="tool_use",
            ),
            _message([_edits("185 points", "158 points")], stop_reason="tool_use"),
            _message([_verdict()], stop_reason="tool_use"),
        ],
        cost_store=store,
    )
    outlook = OutlookFacts(week=10, matchups=[], byes=[], weather=[], playoff_stakes=[])
    result = writer.write(_facts(), lore="Team A is my brother.", outlook=outlook)
    assert result == "Team A scored 158 points."
    assert len(requests) == 4
    repair = json.dumps(requests[2]["messages"])
    assert "185 points" in repair and violations[0]["evidence"] in repair
    assert "158.0" in repair and "my brother" in repair and "OUTLOOK" in repair
    review = json.loads(requests[3]["messages"][0]["content"])
    assert review["draft"] == result
    assert review["facts"] == _facts().to_dict()
    assert review["outlook"] == outlook.to_dict()
    assert [r["writer"] for r in store.read_all()] == [
        "recap",
        "recap_review",
        "recap_repair",
        "recap_review",
    ]
    assert [r["model"] for r in store.read_all()] == [
        "claude-sonnet-4-6",
        "claude-sonnet-4-6",
        "claude-sonnet-4-6",
        "claude-sonnet-4-6",
    ]


def test_second_rejection_stops_after_one_correction(writer_factory):
    # Mutation: keep spending on revisions, or publish despite the final rejection.
    rejection = _message(
        [_verdict({"approved": False, "checks": [{"status": "needs_correction", "quote": "bad", "evidence": "Wrong score"}]})],
        stop_reason="tool_use",
    )
    writer, requests = writer_factory(
        [
            _message([_text("A bad draft")]),
            rejection,
            _message([_edits("A bad draft", "Still bad")], stop_reason="tool_use"),
            rejection,
            _message([_edits("Still bad", "Also bad")], stop_reason="tool_use"),
            rejection,
        ]
    )
    with pytest.raises(ValueError, match="after one correction"):
        writer.write(_facts())
    assert len(requests) == 4


@pytest.mark.parametrize("failure", ["timeout", 429, 500])
def test_provider_failure_is_not_automatically_retried(writer_factory, failure, caplog):
    # Mutation: restore SDK retries, multiplying calls after uncertain provider failures.
    writer, requests = writer_factory([failure])
    with pytest.raises(anthropic.APIError):
        writer.write(_facts())
    assert len(requests) == 1
    assert "usage unknown" in caplog.text


@pytest.mark.parametrize("stage", ["recap_repair", "second_review"])
def test_failed_correction_never_returns_the_first_draft(writer_factory, stage):
    # Mutation: fall back to rejected text when correction or its review fails.
    responses = [
        _message([_text("Wrong score")]),
        _message(
            [_verdict({"approved": False, "checks": [{"status": "needs_correction", "quote": "Wrong score", "evidence": "Wrong score"}]})],
            stop_reason="tool_use",
        ),
    ]
    if stage == "second_review":
        responses.append(_message([_edits("Wrong score", "Corrected score")], stop_reason="tool_use"))
    responses.append("timeout")
    writer, requests = writer_factory(responses)
    with pytest.raises(anthropic.APITimeoutError):
        writer.write(_facts())
    assert len(requests) == len(responses)
