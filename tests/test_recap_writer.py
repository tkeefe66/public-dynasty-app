from unittest.mock import MagicMock, patch
import pytest

from sleeper_dynasty.llm.recap_writer import load_default_persona, load_lore_template, RecapWriter
from sleeper_dynasty.models.recap import RecapFacts, OutlookFacts


def test_default_persona_loads_and_has_hard_rules():
    persona = load_default_persona()
    assert "ONLY the facts" in persona
    assert "The Analyst" in persona


def test_lore_template_loads():
    tmpl = load_lore_template()
    assert "League Lore" in tmpl


def _facts():
    return RecapFacts(
        week=9, league_name="Bros", standings=[], matchups=[],
        high_scorer={"owner": "Team A", "points": 158.0},
        low_scorer=None, bench_regret=[], lucky=[], unlucky=[],
        heroes=[], goats=[], busts=[],
    )


def test_build_messages_includes_facts_and_lore():
    writer = RecapWriter(api_key="test", model="claude-opus-4-8")
    system, messages = writer.build_request(
        _facts(), lore="Team A is run by my idiot brother.",
    )
    assert any("idiot brother" in str(b) for b in messages[0]["content"]) \
        or "idiot brother" in str(messages)
    # Facts JSON present.
    assert "158.0" in str(messages)
    # Persona is the cached system block.
    assert "The Analyst" in str(system)


def test_write_calls_client_and_returns_text():
    fake_resp = MagicMock()
    fake_resp.content = [MagicMock(text="THE ANALYST SPEAKS")]
    fake_client = MagicMock()
    review = MagicMock()
    review.content = [MagicMock(text='{"approved": true, "violations": []}')]
    fake_client.messages.create.side_effect = [fake_resp, review]

    writer = RecapWriter(api_key="test", model="claude-opus-4-8")
    with patch.object(writer, "_client", fake_client):
        out = writer.write(_facts(), lore=None)
    assert out == "THE ANALYST SPEAKS"
    # Model + system prompt were passed.
    _, kwargs = fake_client.messages.create.call_args
    assert kwargs["model"] == "claude-opus-4-8"
    assert "fact" in str(kwargs["system"]).lower()


def test_build_request_includes_outlook_when_present():
    writer = RecapWriter(api_key="test")
    outlook = OutlookFacts(
        week=10, matchups=[], byes=[], weather=[], playoff_stakes=[],
    )
    _, messages = writer.build_request(_facts(), lore=None, outlook=outlook)
    assert "OUTLOOK" in str(messages)
    assert '"week": 10' in str(messages)


def test_write_records_cost_when_cost_store_provided():
    fake_resp = MagicMock()
    fake_resp.content = [MagicMock(text="# Week 1\nSome recap text.")]
    fake_resp.usage.input_tokens = 800
    fake_resp.usage.output_tokens = 300
    fake_client = MagicMock()
    review = MagicMock()
    review.content = [MagicMock(text='{"approved": true, "violations": []}')]
    fake_client.messages.create.side_effect = [fake_resp, review]

    mock_cost_store = MagicMock()

    writer = RecapWriter(api_key="test", model="claude-opus-4-8", cost_store=mock_cost_store)
    with patch.object(writer, "_client", fake_client):
        writer.write(_facts(), lore=None)

    assert [c.kwargs["writer"] for c in mock_cost_store.record.call_args_list] == ["recap", "recap_review"]
    call_kwargs = mock_cost_store.record.call_args_list[0].kwargs
    assert call_kwargs["writer"] == "recap"
    assert call_kwargs["input_tokens"] == 800
    assert call_kwargs["output_tokens"] == 300


@pytest.mark.parametrize("review_text", [
    '{"approved": false, "violations": ["Wrong player ownership"]}',
    '{"approved": true, "violations": ["Illegal QB for TE swap"]}',
    '{"approved": "true", "violations": []}',
    '{}', 'not json',
])
def test_review_failure_blocks_draft(review_text):
    # Mutation: return the draft without requiring a strict, clean review.
    draft, review = MagicMock(), MagicMock()
    draft.content = [MagicMock(text="An unsupported claim.")]
    review.content = [MagicMock(text=review_text)]
    writer = RecapWriter(api_key="test")
    writer._client = MagicMock()
    writer._client.messages.create.side_effect = [draft, review]
    with pytest.raises(ValueError, match="review"):
        writer.write(_facts())
