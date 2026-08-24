import json

from sleeper_dynasty.llm.franchise_outlook_writer import (
    FranchiseOutlookWriter, parse_franchise,
)
from sleeper_dynasty.models.franchise_outlook import FranchiseFacts


def _facts():
    return FranchiseFacts(
        user_id="uA", owner_name="Alice", team_name="Team A",
        league_format="dynasty", window="Contending", young_core_share=0.62,
        roster_rank=3, roster_of=12, young_core=["Young Gun"],
        aging_risks=[], draft_capital_status="pick-rich", draft_capital_net=3.0,
        top_need="RB (immediate)", signature_trade="received Bijan (+1400)")


def test_build_request_embeds_facts_json_and_static_persona():
    w = FranchiseOutlookWriter(api_key="test-key")
    system, messages = w.build_request(_facts())
    assert "cache_control" not in system[0]
    user_text = messages[0]["content"][0]["text"]
    assert "Contending" in user_text
    # the facts packet is embedded as JSON
    assert json.dumps(_facts().to_dict(), indent=2) in user_text


def test_persona_states_the_mark_vocabulary_and_a_concrete_budget():
    """The persona is the only place the model learns the syntax.

    Asserted here rather than eyeballed: a rename in `franchise_marks.MARKS`
    that never reaches the prompt yields a model emitting tags the parser
    swallows, which shows up as *missing emphasis*, not as an error.
    """
    persona = FranchiseOutlookWriter(api_key="test-key").persona
    for mark in ("[num]", "[/num]", "[who]", "[good]", "[risk]"):
        assert mark in persona
    assert "LEAD" in persona and "BODY" in persona
    # A concrete budget, not "be concise" — the vaguer instruction is what put
    # live generation at 69-88 words against a 60-word cap.
    assert "60 words" in persona


class TestParse:
    def test_splits_lead_from_body_and_segments_the_marks(self):
        out = parse_franchise(json.dumps({
            "lead": "The league's top roster, and its youngest.",
            "body": "[num]73%[/num] of value sits with [who]Jahmyr Gibbs[/who].",
        }))
        assert out["lead"] == "The league's top roster, and its youngest."
        assert out["segments"] == [
            {"text": "73%", "mark": "num"},
            {"text": " of value sits with ", "mark": None},
            {"text": "Jahmyr Gibbs", "mark": "who"},
            {"text": ".", "mark": None},
        ]

    def test_blurb_is_the_stripped_body_the_plain_fallback_renders(self):
        out = parse_franchise(json.dumps({
            "lead": "Top roster.",
            "body": "[num]73%[/num] with [who]Gibbs[/who].",
        }))
        assert out["blurb"] == "73% with Gibbs."
        # `body` is the marked source the validator reads, kept distinct from
        # the plain text so neither has to be re-derived from the other.
        assert out["body"] == "[num]73%[/num] with [who]Gibbs[/who]."

    def test_strips_a_markdown_fence(self):
        out = parse_franchise(
            '```json\n{"lead": "L.", "body": "plain."}\n```')
        assert out["lead"] == "L." and out["blurb"] == "plain."

    def test_non_json_falls_back_to_plain_prose_with_no_lead(self):
        """A malformed response still ships a readable paragraph."""
        out = parse_franchise("Ascending and dangerous.\n")
        assert out["lead"] == ""
        assert out["blurb"] == "Ascending and dangerous."
        assert out["segments"] == [
            {"text": "Ascending and dangerous.", "mark": None}]

    def test_a_missing_body_does_not_raise(self):
        out = parse_franchise(json.dumps({"lead": "Only a lead."}))
        assert out["lead"] == "Only a lead."
        assert out["blurb"] == "" and out["segments"] == []

    def test_normalizes_whitespace_the_model_leaves_around_tags(self):
        out = parse_franchise(json.dumps({
            "lead": "  Top   roster. ", "body": "[num] 73% [/num] of value."}))
        assert out["lead"] == "Top roster."
        assert out["blurb"] == "73% of value."
        assert out["segments"][0] == {"text": "73%", "mark": "num"}

    def test_a_malformed_tag_costs_its_span_not_the_blurb(self):
        out = parse_franchise(json.dumps({
            "lead": "L.", "body": "a [shout]loud[/shout] b"}))
        assert out["blurb"] == "a loud b"
        assert out["segments"] == [{"text": "a loud b", "mark": None}]
