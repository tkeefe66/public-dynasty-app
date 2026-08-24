"""Tests for deterministic trade-story validation + repair.

The story writer is a weak model (Haiku). The persona bans a lot it cannot be
trusted to obey: reversed trade direction, bare positional epithets, em dashes,
over-long headlines. These backstops enforce the rules the prose keeps breaking
-- repairing the cheap mechanical ones and flagging the semantic ones for
regeneration.
"""

from sleeper_dynasty.llm.story_validation import (
    repair_prose, tidy_headline, find_violations,
)
from sleeper_dynasty.models.trade_story import TradeStoryFacts


def _facts(tom_received="Mike Evans (WR)", tom_given="2026 3rd pick · 2027 2nd pick"):
    """A Mike-Evans-shaped trade: Tom received the WR and gave the picks."""
    return TradeStoryFacts(
        trade_id="t", season=2026, is_offseason=True,
        winner_user_id="u_amir", lopsidedness=0.5, margins={},
        sides=[
            {"user_id": "u_tom", "owner_name": "Tom",
             "received_summary": tom_received, "given_summary": tom_given},
            {"user_id": "u_amir", "owner_name": "Amir",
             "received_summary": tom_given, "given_summary": tom_received},
        ],
        owners={},
    )


# --- repair (always applied, no regeneration) ---

def test_repair_strips_em_dash_and_double_hyphen():
    assert "—" not in repair_prose("a heist — plain and simple")
    assert "--" not in repair_prose("a heist -- plain and simple")
    # replaced with a comma+space, prose still reads
    assert repair_prose("a heist — plain") == "a heist, plain"


def test_repair_is_idempotent_and_leaves_clean_text():
    clean = "Amir robbed the vault and never looked back."
    assert repair_prose(clean) == clean


def test_tidy_headline_strips_trailing_period_and_markdown():
    assert tidy_headline("Amir robs the vault.") == "Amir robs the vault"
    assert tidy_headline("## Amir robs the vault") == "Amir robs the vault"
    assert tidy_headline("**Amir robs the vault**") == "Amir robs the vault"


# --- violations (trigger regeneration) ---

def test_clean_story_has_no_violations():
    facts = _facts()
    v = find_violations(
        "Amir fleeces Tom on the Evans deal",
        "Amir shipped Mike Evans and walked off with two picks. Tom bought "
        "high on a fading receiver's market.",
        facts,
    )
    # "bought high on ... receiver's market" -> contains an epithet, see below;
    # keep the clean case epithet-free:
    v = find_violations(
        "Amir fleeces Tom on the Evans deal",
        "Amir shipped Mike Evans for two future picks. Tom is betting the "
        "picks beat the veteran.",
        facts,
    )
    assert v == []


def test_reversal_received_player_described_as_sold():
    # Tom RECEIVED Mike Evans; saying Tom "sold" him is the reversal bug.
    facts = _facts()
    v = find_violations(
        "Tom sells low again",
        "Tom sold Mike Evans for a bag of future picks.",
        facts,
    )
    assert any("revers" in s.lower() or "direction" in s.lower() for s in v)


def test_reversal_given_player_described_as_acquired():
    # Amir GAVE Mike Evans; saying Amir "acquired" him is reversed.
    facts = _facts()
    v = find_violations(
        "Amir loads up",
        "Amir acquired Mike Evans to chase a title.",
        facts,
    )
    assert any("revers" in s.lower() or "direction" in s.lower() for s in v)


def test_flipping_a_received_player_is_not_a_reversal():
    # The persona explicitly allows "flipped him" for a received player.
    facts = _facts()
    v = find_violations(
        "Tom keeps wheeling",
        "Tom flipped Mike Evans days later for even more picks.",
        facts,
    )
    assert v == []


def test_bare_positional_epithet_is_flagged():
    # The exact reported prose: Tom received the WR, but the story calls him
    # "the veteran receiver" and reverses the direction around the epithet.
    facts = _facts()
    v = find_violations(
        "Tom sells low on the vet",
        "Tom sold low on the veteran receiver and bought high on picks.",
        facts,
    )
    assert any("epithet" in s.lower() for s in v)


def test_over_long_headline_is_flagged():
    facts = _facts()
    v = find_violations(
        "Amir absolutely fleeces Tom in the most lopsided heist of the entire offseason",
        "Amir shipped Mike Evans for picks.",
        facts,
    )
    assert any("headline" in s.lower() for s in v)


def test_short_punchy_headline_is_allowed():
    facts = _facts()
    v = find_violations("Grand larceny", "Amir shipped Mike Evans for picks.", facts)
    assert all("headline" not in s.lower() for s in v)
