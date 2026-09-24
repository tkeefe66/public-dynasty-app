import json
from importlib import import_module

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
        "input": {"approved": True, "violations": []} if value is None else value,
    }


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

    def make(responses, *, cost_store=None):
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
            api_key="test", cost_store=cost_store, league_id="test-league"
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
    assert '"week": 10' in str(messages)


def test_player_context_is_identical_in_draft_and_review(writer_factory):
    # Mutation: leave news out of serialization or send it only to the writer.
    facts = _facts()
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
    assert draft["player_context"] == facts.player_context == review["facts"]["player_context"]


def test_write_requires_structured_review_and_returns_sanitized_draft(writer_factory):
    # Mutation: request unstructured JSON text, or parse review text instead of tool input.
    def review_response(request):
        assert request["tool_choice"] == {"type": "tool", "name": "submit_recap_review"}
        tool = request["tools"][0]
        assert tool["name"] == "submit_recap_review"
        assert set(tool["input_schema"]["required"]) == {"approved", "violations"}
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
    assert requests[1]["max_tokens"] <= 4096


@pytest.mark.parametrize(
    "verdict",
    [
        {"approved": False, "violations": []},
        {"approved": True, "violations": ["Illegal QB for TE swap"]},
        {"approved": "true", "violations": []},
        {"approved": 1, "violations": []},
        {"approved": True},
        {"approved": False, "violations": [""]},
        {"approved": False, "violations": "Wrong score"},
        {"approved": False, "violations": [42]},
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
        ([_text('{"approved": true, "violations": []}')], "end_turn"),
        ([_text('```json\n{"approved": true, "violations": []}\n```')], "end_turn"),
        ([_verdict(name="wrong_tool")], "tool_use"),
        (
            [_verdict(), _verdict({"approved": False, "violations": ["Wrong score"]})],
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
        [0.0023] if stage == "recap" else [0.0023, 0.0069]
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
        "claude-haiku-4-5-20251001",
        "claude-sonnet-4-6",
    ]
    assert [r["cost_usd"] for r in records] == [0.0023, 0.0069]


def test_review_uses_sonnet_and_longer_deadline(writer_factory):
    # Mutation: send factual review to the draft model, or retain the 90-second timeout.
    writer, requests = writer_factory(
        [
            _message([_text("Draft")]),
            _message([_verdict()], stop_reason="tool_use"),
        ]
    )
    writer.write(_facts())
    assert requests[0]["model"] == "claude-haiku-4-5-20251001"
    assert requests[1]["model"] == "claude-sonnet-4-6"
    assert all(request["_timeout"]["read"] == 300 for request in requests)


def test_rejection_is_corrected_with_evidence_then_reviewed_again(
    writer_factory, tmp_path
):
    # Mutation: return the rejected draft, omit its feedback, or skip the corrected review.
    violations = ["The packet says 158 points; the draft says 185."]
    store = LlmCostStore(tmp_path)
    writer, requests = writer_factory(
        [
            _message([_text("Team A scored 185 points.")]),
            _message(
                [_verdict({"approved": False, "violations": violations})],
                stop_reason="tool_use",
            ),
            _message([_text("Team A scored 158 points.")]),
            _message([_verdict()], stop_reason="tool_use"),
        ],
        cost_store=store,
    )
    outlook = OutlookFacts(week=10, matchups=[], byes=[], weather=[], playoff_stakes=[])
    result = writer.write(_facts(), lore="Team A is my brother.", outlook=outlook)
    assert result == "Team A scored 158 points."
    assert len(requests) == 4
    repair = json.dumps(requests[2]["messages"])
    assert "185 points" in repair and violations[0] in repair
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
        "claude-haiku-4-5-20251001",
        "claude-sonnet-4-6",
        "claude-haiku-4-5-20251001",
        "claude-sonnet-4-6",
    ]


def test_second_rejection_stops_after_one_correction(writer_factory):
    # Mutation: keep spending on revisions, or publish despite the second rejection.
    rejection = _message(
        [_verdict({"approved": False, "violations": ["Wrong score"]})],
        stop_reason="tool_use",
    )
    writer, requests = writer_factory(
        [
            _message([_text("Bad draft")]),
            rejection,
            _message([_text("Still bad")]),
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
            [_verdict({"approved": False, "violations": ["Wrong score"]})],
            stop_reason="tool_use",
        ),
    ]
    if stage == "second_review":
        responses.append(_message([_text("Corrected score")]))
    responses.append("timeout")
    writer, requests = writer_factory(responses)
    with pytest.raises(anthropic.APITimeoutError):
        writer.write(_facts())
    assert len(requests) == len(responses)
