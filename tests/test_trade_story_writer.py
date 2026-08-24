from unittest.mock import MagicMock, patch

from sleeper_dynasty.llm.trade_story_writer import (
    TradeStoryWriter, load_persona, parse_story, sanitize_prose,
)
from sleeper_dynasty.models.trade_story import TradeStoryFacts


def _facts():
    return TradeStoryFacts(
        trade_id="t1", season=2024, is_offseason=True, winner_user_id="u_mike",
        lopsidedness=0.82, margins={"ktc": 1840.0, "production": 41.2, "impact": 6.0},
        sides=[{"user_id": "u_mike", "owner_name": "Mike",
                "player_arcs": [], "pick_outcomes": []}],
        owners={"u_mike": {"owner_name": "Mike", "tilt": "win-now"}},
    )


def test_persona_loads_with_hard_rules():
    p = load_persona()
    assert "ONLY" in p and "Beat Writer" in p


def test_parse_story_splits_verdict_and_body():
    raw = "Mike robbed Tom.\n\nThree months later, it is not close.\n\nReceipts."
    story = parse_story(raw)
    assert story["verdict"] == "Mike robbed Tom."
    assert "Three months later" in story["body"]
    assert "Receipts." in story["body"]


def test_build_request_has_persona_and_facts_only():
    w = TradeStoryWriter(api_key="test")
    system, messages = w.build_request(_facts())
    # No cache_control — inert below Haiku's 4096-token cache minimum.
    assert "cache_control" not in system[0]
    assert "Beat Writer" in str(system)
    assert "1840.0" in str(messages) and "use only" in str(messages).lower()


def test_write_calls_client_and_parses():
    fake = MagicMock()
    fake.content = [MagicMock(text="Mike robbed Tom.\n\nNot close.")]
    client = MagicMock()
    client.messages.create.return_value = fake
    w = TradeStoryWriter(api_key="test")
    with patch.object(w, "_client", client):
        out = w.write(_facts())
    # tidy_headline strips the trailing period the persona bans on headlines.
    assert out["verdict"] == "Mike robbed Tom"
    assert "_usage" in out
    _, kwargs = client.messages.create.call_args
    assert kwargs["model"] == "claude-haiku-4-5-20251001"


def test_build_request_serializes_realized_fate_facts():
    facts = TradeStoryFacts(
        trade_id="t1", season=2025, is_offseason=False, winner_user_id="u_a",
        lopsidedness=0.4, margins={"ktc": 500.0},
        sides=[{
            "user_id": "u_a", "owner_name": "A", "player_arcs": [],
            "pick_outcomes": [{
                "season": 2026, "round": 1, "became_player": "Cut Guy",
                "flipped_for": None, "points_per_game": None,
                "terminal_state": "dropped", "dropped_before_week": 0,
            }],
            "realized_players": [],
        }],
        owners={"u_a": {"owner_name": "A", "tilt": "win-now"}},
    )
    w = TradeStoryWriter(api_key="test")
    _, messages = w.build_request(facts)
    blob = str(messages)
    assert "dropped" in blob and "dropped_before_week" in blob


def test_persona_explains_realized_fate():
    p = load_persona()
    assert "terminal_state" in p
    assert "realized_players" in p


def test_persona_includes_given_summary_instruction():
    p = load_persona()
    assert "given_summary" in p


def test_sanitize_prose_strips_ktc_jargon():
    # "KTC" is never shown to users; it is "Trade Value".
    assert "KTC" not in sanitize_prose("won by 5,030 points on KTC alone")
    assert "K.T.C." not in sanitize_prose("a K.T.C. edge")
    # case-insensitive, word-boundary only (don't mangle unrelated words)
    assert sanitize_prose("the ktc value") == "the trade value"
    assert sanitize_prose("the KTC market value") == "the market value"
    assert sanitize_prose("blackticket") == "blackticket"


def test_write_sanitizes_leaked_ktc():
    fake = MagicMock()
    fake.content = [MagicMock(
        text="Mike won on KTC.\n\nHe led by 1,840 on KTC over the season.")]
    client = MagicMock()
    client.messages.create.return_value = fake
    w = TradeStoryWriter(api_key="test")
    with patch.object(w, "_client", client):
        out = w.write(_facts())
    assert "KTC" not in out["verdict"]
    assert "KTC" not in out["body"]


def test_persona_bans_ktc_term():
    p = load_persona()
    assert "KTC" in p  # the ban itself names the term


def test_persona_instructs_structured_output():
    p = load_persona()
    assert "lede" in p.lower()
    assert "beat" in p.lower()
    # the output contract still bans em dashes and KTC
    assert "em dash" in p.lower() or "—" in p


def test_persona_structured_block_has_no_em_dash_and_names_owner():
    p = load_persona()
    # The structured output-format block (under "Hard rules", before "## Voice")
    # must be em-dash-free so a weak model can't copy an em dash from the template
    # into its output, and must still guard names via owner_name (not user_id).
    block = p.split("## Voice")[0]
    assert "—" not in block
    assert "owner_name" in block


def test_parse_story_structured_headline_lede_beats():
    raw = (
        "Mikey robbed Tom\n\n"
        "Tom flipped a future RB1 for a pick that evaporated.\n\n"
        "- Bijan became a workhorse: 705 points for Mikey.\n"
        "- Chubb got dropped before he paid off.\n"
        "- The market gives Mikey a 9,000-point edge today.\n"
    )
    out = parse_story(raw)
    assert out["verdict"] == "Mikey robbed Tom"
    assert out["lede"] == "Tom flipped a future RB1 for a pick that evaporated."
    assert out["beats"] == [
        "Bijan became a workhorse: 705 points for Mikey.",
        "Chubb got dropped before he paid off.",
        "The market gives Mikey a 9,000-point edge today.",
    ]
    # body is a readable fallback: lede + beats, paragraph-separated
    assert "Bijan became a workhorse" in out["body"]
    assert out["body"].startswith("Tom flipped a future RB1")
    assert "\n\n" in out["body"]


def test_parse_story_backcompat_no_bullets():
    # Old shape (headline + paragraph, no bullets): degrade gracefully.
    raw = "Mikey robbed Tom\n\nThree months later it is not close. Receipts."
    out = parse_story(raw)
    assert out["verdict"] == "Mikey robbed Tom"
    assert out["beats"] == []
    assert out["lede"] == "Three months later it is not close. Receipts."
    assert out["body"] == "Three months later it is not close. Receipts."
