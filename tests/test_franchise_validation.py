"""The franchise-blurb backstops (mirrors test_story_validation)."""

from sleeper_dynasty.llm.franchise_validation import (
    MAX_WORDS, _VOCABULARY, find_violations,
)
from sleeper_dynasty.models.franchise_outlook import FranchiseFacts


def _facts(**over) -> FranchiseFacts:
    base = dict(
        user_id="uA", owner_name="Alice", team_name="Team A",
        league_format="dynasty", window="Contending", young_core_share=0.62,
        roster_rank=3, roster_of=12,
        young_core=["Malik Nabers", "Brock Bowers"],
        aging_risks=["Mike Evans"],
        draft_capital_status="pick-rich", draft_capital_net=3.0,
        top_need="RB (immediate)",
        signature_trade="received Bijan Robinson (+1400)",
    )
    base.update(over)
    return FranchiseFacts(**base)


def test_clean_prose_has_no_violations():
    prose = ("Contending and dangerous: Malik Nabers and Brock Bowers anchor a "
             "young core, with Mike Evans the one asset on the clock.")
    assert find_violations(prose, _facts()) == []


# --- word cap --------------------------------------------------------------

def test_over_long_prose_is_a_violation():
    prose = " ".join(["word"] * (MAX_WORDS + 1))
    v = find_violations(prose, _facts())
    assert any("too long" in x for x in v)


def test_prose_at_the_cap_is_clean():
    assert find_violations(" ".join(["word"] * MAX_WORDS), _facts()) == []


# --- banned terms: league mechanics this league does not have --------------

def test_salary_cap_language_is_a_violation():
    """The prose that prompted this called eight aging veterans "dead weight
    eating cap and roster spots". This league has no salary cap."""
    v = find_violations("Those aging risks are dead weight eating cap space.",
                        _facts())
    assert any("banned term" in x and "cap" in x for x in v)


def test_each_banned_term_is_caught():
    for term, sentence in [
        ("salary", "A bloated salary bill weighs him down."),
        ("contract", "Every contract on the roster is upside down."),
        ("auction", "He overspent at auction on the wrong tier."),
        ("KTC", "His KTC total leads the league."),
    ]:
        v = find_violations(sentence, _facts())
        assert any("banned term" in x for x in v), (term, v)


def test_draft_capital_is_not_mistaken_for_a_salary_cap():
    """`cap` is matched on a word boundary — "capital" must survive, since the
    packet's own draft-capital signal is the thing being described."""
    assert find_violations(
        "Pick-rich draft capital keeps the window open.", _facts()) == []


# --- invented players: the strongest check ---------------------------------

def test_a_player_not_in_the_packet_is_a_violation():
    v = find_violations(
        "Malik Nabers leads a core that Stefon Diggs cannot drag down.",
        _facts())
    assert any("not in the facts" in x and "Stefon Diggs" in x for x in v)


def test_every_packet_name_source_is_accepted():
    prose = ("Alice runs Team A around Malik Nabers, Brock Bowers and Bijan "
             "Robinson, with Mike Evans aging out.")
    assert find_violations(prose, _facts()) == []


def test_a_sentence_initial_capital_does_not_read_as_a_name():
    """"Despite Mike Evans" must not report the invented name "Despite" — the
    opening token carries a capital for free and is never itself checked."""
    assert find_violations(
        "Contending window here. Despite Mike Evans aging, the core holds.",
        _facts()) == []


def test_an_invented_name_that_OPENS_the_blurb_is_still_caught():
    """The likeliest place for one, so the sentence-initial exemption covers
    the token only, not the whole run."""
    v = find_violations("Stefon Diggs anchors a fading core.", _facts())
    assert any("Stefon Diggs" in x for x in v)


def test_the_fixed_metric_vocabulary_is_not_read_as_a_name():
    assert find_violations(
        "He wins on Trade Value and Regular Season Points alike.", _facts()) == []


def test_an_nfl_team_name_is_an_invention_too():
    v = find_violations("His Kansas City stack carries the roster.", _facts())
    assert any("not in the facts" in x for x in v)


def test_a_single_capitalised_word_is_not_flagged():
    """Surname-only references are ambiguous against sentence-case prose, so
    the check stays on multi-token runs — precise over exhaustive, the same
    trade-off story_validation makes. A false positive would loop."""
    assert find_violations("Evans is the one on the clock.", _facts()) == []


def test_violations_accumulate():
    v = find_violations(
        "Stefon Diggs eats cap space here.", _facts())
    assert len(v) >= 2


# --- marks: names are structural now ---------------------------------------

def test_the_cap_is_75_and_counts_stripped_words():
    """The cap was 60 and live generation landed at 69-88 on every owner,
    exhausting all three retry rounds and shipping best-effort prose every
    time. That is the cap being wrong, not the model misbehaving."""
    assert MAX_WORDS == 75


def test_word_count_ignores_the_tags():
    """Counting the marked-up string charges every spaced-off tag as a word,
    which fails a blurb that is comfortably inside its budget."""
    body = " ".join(
        ["[num] 1 [/num]"] * 20 + ["word"] * 20)   # 40 words, 60 tokens marked
    assert len(body.split()) > MAX_WORDS
    assert not any("too long" in x for x in find_violations(body, _facts()))


def test_the_lead_counts_against_the_same_budget():
    """A reader sees lead and body as one paragraph, so one cap covers both."""
    lead = " ".join(["word"] * 10)
    body = " ".join(["word"] * (MAX_WORDS - 10))
    assert find_violations(body, _facts(), lead=lead) == []
    v = find_violations(body + " overflow", _facts(), lead=lead)
    assert any("too long" in x for x in v)


def test_a_who_span_must_name_someone_in_the_packet():
    v = find_violations("[who]Stefon Diggs[/who] anchors it.", _facts())
    assert any("Stefon Diggs" in x and "not in the facts" in x for x in v)


def test_a_who_span_is_checked_even_when_it_is_one_word():
    """The unmarked run-check skips single tokens because a lone capital is
    ambiguous against sentence-case prose. A [who] span is not ambiguous —
    the model has declared it a person — so it is checked at any length."""
    v = find_violations("The core runs through [who]Chase[/who].", _facts())
    assert any("Chase" in x for x in v)
    assert find_violations("Around [who]Nabers[/who] it holds.", _facts()) == []


def test_a_packet_name_inside_a_who_span_is_clean():
    assert find_violations(
        "[who]Malik Nabers[/who] and [who]Brock Bowers[/who] anchor it.",
        _facts()) == []


def test_a_possessive_who_span_still_resolves():
    assert find_violations(
        "Past [who]Mike Evans'[/who] window it holds.", _facts()) == []


def test_an_unknown_mark_is_a_violation():
    v = find_violations("A [shout]loud[/shout] core.", _facts())
    assert any("unknown mark" in x for x in v)


def test_unbalanced_tags_are_a_violation():
    assert any("unclosed" in x
               for x in find_violations("A [who]Nabers core.", _facts()))
    assert any("unbalanced" in x
               for x in find_violations("A core[/who].", _facts()))


def test_nested_tags_are_a_violation():
    v = find_violations("[who]Nabers [num]25[/num][/who] leads.", _facts())
    assert any("nested" in x for x in v)


def test_a_banned_term_inside_a_mark_is_still_caught():
    """Checked on stripped text, so a tag cannot smuggle one past."""
    v = find_violations("Dead weight eating [risk]cap space[/risk].", _facts())
    assert any("banned term" in x for x in v)


def test_well_marked_prose_is_clean():
    body = ("[num]62%[/num] of value sits with [who]Malik Nabers[/who] and "
            "[who]Brock Bowers[/who] — [good]pick-rich and ascending[/good], "
            "with [risk]RB[/risk] the one need.")
    assert find_violations(body, _facts(), lead="Young, and getting younger.") == []


# --- punctuated names: the tokenizer-mismatch regression --------------------
# Every case below is a real name from the reference league that failed in
# production on 2026-08-17. The prose tokenizer stopped at the capital inside
# `D'Andre`, yielding `D'` + `Andre`, while the packet side kept `d'andre`
# whole — so the two sides disagreed about what one token was and three of
# twelve blurbs exhausted their retries and shipped flagged.

def test_an_apostrophe_name_from_the_packet_is_clean():
    facts = _facts(young_core=["D'Andre Swift", "De'Von Achane"])
    prose = "D'Andre Swift and De'Von Achane carry the backfield."
    assert find_violations(prose, facts) == []


def test_a_hyphenated_name_from_the_packet_is_clean():
    facts = _facts(young_core=["Jaxon Smith-Njigba"])
    assert find_violations("Jaxon Smith-Njigba is the target share.", facts) == []


def test_an_initialled_name_from_the_packet_is_clean():
    facts = _facts(young_core=["A.J. Brown"])
    assert find_violations("Yet A.J. Brown remains the alpha.", facts) == []


def test_a_marked_apostrophe_name_is_clean():
    facts = _facts(young_core=["D'Andre Swift"])
    prose = "[who]D'Andre Swift[/who] carries the backfield."
    assert find_violations(prose, facts) == []


def test_an_invented_apostrophe_name_is_still_caught():
    # The fix must not blunt the check it was fixing: a punctuated name the
    # packet never mentions is still an invention.
    facts = _facts(young_core=["Malik Nabers"])
    v = find_violations("[who]Ja'Marr Chase[/who] leads the room.", facts)
    assert any("Ja'Marr Chase" in x for x in v)


def test_a_possessive_punctuated_name_resolves():
    facts = _facts(young_core=["D'Andre Swift"])
    assert find_violations("D'Andre Swift' role grew.", facts) == []


# --- vocabulary: live stages in, retired ones out ---------------------------

def test_vocabulary_carries_the_live_stages_and_none_of_the_retired_ones():
    for live in ("retooling", "contending", "competing", "dynasty", "rebuilding"):
        assert live in _VOCABULARY
    for retired in ("now", "peaking", "ascending", "descending"):
        assert retired not in _VOCABULARY
