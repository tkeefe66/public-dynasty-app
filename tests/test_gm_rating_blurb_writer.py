import json
from unittest.mock import MagicMock, patch

from sleeper_dynasty.llm.gm_rating_blurb_writer import (
    GmRatingBlurbWriter, load_blurb_persona, parse_blurb,
)
from sleeper_dynasty.models.gm_rating_blurb import OwnerRatingFacts


def _facts():
    return OwnerRatingFacts(
        user_id="u1", owner_name="Bob", team_name="Sticky Icky",
        scope_label="career", rank=2, rating=1741,
        pillars=[{"label": "Outcomes", "weight": 0.45, "contribution": 148,
                  "top_signals": [{"label": "Championships", "contribution": 55}],
                  "worst_signals": []}],
        championships=1, made_playoffs_rate=0.6, draft_capital_counted=False,
    )


def test_persona_loads_with_hard_rules():
    p = load_blurb_persona()
    assert "ONLY" in p and "GM Profiler" in p


def test_parse_blurb_collapses_to_one_paragraph():
    out = parse_blurb("  Bob is a win-now killer.\n\nHis roster is aging.  ")
    assert out["blurb"] == "Bob is a win-now killer. His roster is aging."


def test_build_request_has_persona_and_facts_only():
    w = GmRatingBlurbWriter(api_key="test")
    system, messages = w.build_request(_facts())
    assert "cache_control" not in system[0]
    assert "GM Profiler" in str(system)
    assert "1741" in str(messages) and "use only" in str(messages).lower()


def test_parse_blurb_extracts_pillar_highlights():
    sample = json.dumps({
        "blurb": "Bob is solid.",
        "highlights": {
            "Results": "Won a title in 2023.",
            "Assets": "Strong roster but pick-poor heading into 2026."
        }
    })
    out = parse_blurb(sample)
    assert out["blurb"] == "Bob is solid."
    assert out["pillars"]["results"] == "Won a title in 2023."
    assert out["pillars"]["assets"] == "Strong roster but pick-poor heading into 2026."


def test_parse_blurb_omits_missing_assets_pillar():
    # Redraft packets carry only the Results pillar; the writer's highlights
    # key set follows what the packet exposed, so a missing Assets key here
    # must not surface as a phantom empty highlight.
    sample = json.dumps({
        "blurb": "Bob is solid.",
        "highlights": {"Results": "Won a title in 2023."}
    })
    out = parse_blurb(sample)
    assert out["pillars"] == {"results": "Won a title in 2023."}


def test_write_calls_client_with_haiku_and_parses():
    fake = MagicMock()
    fake.content = [MagicMock(text="Bob ranks 2nd.\n\nHe is win-now.")]
    client = MagicMock()
    client.messages.create.return_value = fake
    w = GmRatingBlurbWriter(api_key="test")
    with patch.object(w, "_client", client):
        out = w.write(_facts())
    assert out["blurb"] == "Bob ranks 2nd. He is win-now."
    assert "_usage" in out
    _, kwargs = client.messages.create.call_args
    assert kwargs["model"] == "claude-haiku-4-5-20251001"
