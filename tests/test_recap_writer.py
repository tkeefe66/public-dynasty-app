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
def writer_factory():
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

    def make(responses, *, cost_store=None):
        requests = []

        def handle(request):
            payload = json.loads(request.content)
            requests.append(payload)
            index = len(requests) - 1
            assert index < len(responses), "Unexpected paid retry"
            response = responses[index]
            if callable(response):
                response = response(payload)
            return http.Response(200, json=response)

        client = anthropic.Anthropic(
            api_key="test",
            max_retries=0,
            http_client=anthropic.DefaultHttpxClient(
                transport=http.MockTransport(handle)
            ),
        )
        writer = RecapWriter(
            api_key="test", cost_store=cost_store, league_id="test-league"
        )
        writer._client.close()
        writer._client = client
        clients.append(client)
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
        {"approved": False, "violations": ["Wrong player ownership"]},
        {"approved": True, "violations": ["Illegal QB for TE swap"]},
        {"approved": "true", "violations": []},
        {"approved": 1, "violations": []},
        {"approved": True},
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
    assert all(r["cost_usd"] == 0.0023 for r in records)
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
    assert all(
        r["league_id"] == "test-league" and r["cost_usd"] == 0.0023 for r in records
    )
