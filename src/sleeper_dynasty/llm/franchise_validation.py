"""Deterministic backstops for franchise-blurb prose.

The structural gap this closes: ``story_gen`` validates every trade story and
regenerates on a violation, while the franchise blurb — written by the same weak
model against a smaller packet — shipped whatever came back. It shipped a
paragraph asserting that eight veterans were "dead weight eating cap and roster
spots" in a league with no salary cap.

Same shape as ``story_validation``: pure, no Anthropic dependency, and detecting
only problems a *fresh sample* can plausibly fix, since the generator's answer to
a violation is to regenerate (bounded, then ship best-effort).

Five checks, weakest to strongest:

1. **Word cap** — counted on the STRIPPED text, over lead and body together.
2. **Banned terms** — league mechanics this platform's leagues do not have.
   Prompt text alone did not hold; a match is mechanical.
3. **Well-formed marks** — an unknown, unbalanced or nested tag.
4. **Unmarked names** — a multi-token capitalised run the packet cannot
   account for. Precision over recall; see ``_unknown_name_runs``.
5. **Marked names** — every ``[who]`` span must name someone in the packet.
   This is the one that matters, and it got stronger rather than weaker when
   the model started emitting marks: a ``[who]`` span is a DECLARATION that
   these words are a person, so it is checked at any length, where the
   unmarked run-check has to skip single tokens as ambiguous.
"""

from __future__ import annotations

import re

from sleeper_dynasty.llm.franchise_marks import (
    mark_violations, spans_of, strip_marks,
)
from sleeper_dynasty.models.franchise_outlook import FranchiseFacts

# Raised from 60. At 60, live generation was landing at 69-88 words on EVERY
# owner: all three retry rounds burned, best-effort prose shipped every time,
# and three Haiku calls per owner paid for nothing. A cap that nothing ever
# clears is not a backstop, it is a tax. The persona now states 12 words of lead
# and 40-60 of body — a concrete budget rather than "concise" — which fits
# inside 75 with room for a long sentence.
MAX_WORDS = 75

# Mechanics no league on this platform has. "cap" is the one that actually
# leaked; the rest are the same failure mode (importing rules from a format the
# model has read about) and cost nothing to forbid. "KTC" is banned as a term
# everywhere in the product — the UI never renders it.
#
# NOT routed through trade_story_writer.sanitize_prose on purpose: silently
# rewriting the word would leave the invented CLAIM standing with a different
# noun in it. A violation regenerates the sentence instead.
_BANNED = re.compile(
    r"\b(?:caps?|capped|cap\s+space|salar(?:y|ies)|contracts?|auctions?|KTC)\b",
    re.I)

# A capitalised name token — "Evans", "Bijan", "D'Andre", "Smith-Njigba", "A.J.".
#
# The interior class must accept UPPERCASE, and that is the whole point: an
# earlier version was `[A-Z][a-z'’.-]+`, which stops dead at the capital inside
# `D'Andre` and yields two tokens, `D'` and `Andre`. `_packet_tokens` meanwhile
# uses `_WORD`, which keeps `d'andre` whole — so the two sides tokenised the
# same name differently and `d'` was never in the packet's set. Every
# apostrophe or hyphen name in the league (D'Andre, De'Von, Ja'Marr,
# Smith-Njigba, St. Brown) then failed the check, exhausted its retries, and
# shipped flagged. The two regexes must agree on what one token is; this one is
# `_WORD` plus the requirement that it opens on a capital.
_TITLE_TOKEN = re.compile(r"\b[A-Z][A-Za-z'’.\-]*")
_SENTENCE_BREAK = re.compile(r"[.!?][\s\"'’)]*$")

# Capitalised phrases that are product vocabulary rather than people. Kept small
# on purpose: the token allowlist below is built from the packet itself, so this
# only has to cover words that are never in a packet.
_VOCABULARY = frozenset(w.lower() for w in (
    # The five metrics, in the fixed order they are always written.
    "Trade", "Value", "Total", "Points", "Regular", "Season", "Playoff",
    "Playoffs", "Toilet", "Bowl",
    # Rating and outlook vocabulary.
    "Franchise", "Rating", "Draft", "Capital", "Roster", "League", "Owner",
    "Core", "Young", "Aging", "Window", "Grade",
    # Window stages (engine/gm_rating.py::rating_to_stage). "Dynasty" is
    # already listed under League formats below and is not repeated.
    #
    # Severity here is LOW, and only because the facts packet keeps `window`:
    # _packet_tokens allows the subject's own stage straight off
    # FranchiseFacts.window, so this list only has to cover a DIFFERENT owner's
    # stage. Dropping `window` from the packet would invert that and make the
    # model fail validation for naming its own stage.
    "Competing", "Contending", "Retooling", "Rebuilding",
    # League formats.
    "Dynasty", "Keeper", "Redraft",
))

_WORD = re.compile(r"[A-Za-z][A-Za-z'’.-]*")


def _packet_tokens(facts: FranchiseFacts) -> set[str]:
    """Every word the packet itself contains, lowercased.

    Membership is checked per TOKEN, not per full name, so the model may say
    "Nabers" or "Malik Nabers" or "Bijan Robinson" (out of the signature trade)
    and all three resolve. A name is invented only when it contributes a word
    the packet never used.
    """
    strings: list[str] = []
    for value in facts.to_dict().values():
        if isinstance(value, str):
            strings.append(value)
        elif isinstance(value, list):
            strings.extend(v for v in value if isinstance(v, str))
    return {_norm(m.group(0)) for s in strings for m in _WORD.finditer(s)}


def _norm(token: str) -> str:
    """One normalisation, used on BOTH sides of every membership test.

    Edge punctuation is noise: a possessive ("Mahomes'") and a sentence-final
    name ("… Nacua.") must match the packet's bare `nacua`. Interior
    punctuation is not — it is part of the name (Ja'Marr, Smith-Njigba), which
    is why this strips only the edges. The rule that matters is that the packet
    side and the prose side call this same function; when they normalised
    differently, every apostrophe name in the league failed.
    """
    return token.lower().strip("'’.-")


def _unknown_name_runs(prose: str, allowed: set[str]) -> list[str]:
    """Runs of 2+ title-case tokens that the packet does not account for.

    A sentence-initial token stays IN its run but is never itself checked: it
    carries a capital for free, so "Despite Mike Evans aging" must not report
    the invented name "Despite". Dropping such a token from the run instead
    would let a blurb that OPENS on an invented player ("Stefon Diggs eats
    ...") slip through as a lone surname, which is the most likely place for
    one to appear.

    Single tokens are never flagged — a lone capitalised word is
    indistinguishable from ordinary sentence-case prose, and story_validation
    makes the same precision-over-recall trade for the same reason: a false
    positive loops until the attempts run out.
    """
    runs: list[list[tuple[str, bool]]] = []       # (token, is_sentence_initial)
    current: list[tuple[str, bool]] = []
    end_of_prev = 0

    for m in _TITLE_TOKEN.finditer(prose):
        contiguous = bool(current) and prose[end_of_prev:m.start()].strip() == ""
        initial = (
            m.start() == 0 or bool(_SENTENCE_BREAK.search(prose[:m.start()])))
        if not contiguous:
            if len(current) >= 2:
                runs.append(current)
            current = [(m.group(0), initial)]
        else:
            current.append((m.group(0), initial))
        end_of_prev = m.end()

    if len(current) >= 2:
        runs.append(current)

    return [
        " ".join(tok for tok, _ in run)
        for run in runs
        if any(_norm(tok) not in allowed for tok, is_initial in run
               if not is_initial)
    ]


def find_violations(
    prose: str, facts: FranchiseFacts, lead: str = "",
) -> list[str]:
    """Return human-readable violations of the blurb contract (empty = clean).

    ``prose`` is the body, marked or not — plain prose passes through every
    check unchanged, which is what keeps a pre-marks cached blurb validatable.
    ``lead`` is the short opening claim; it counts against the same word budget
    because the reader sees the two as one paragraph.
    """
    violations: list[str] = []
    body = (prose or "").strip()
    # Every check below runs on the STRIPPED text, except the mark checks
    # themselves. A tag must not inflate the word count, and must not smuggle a
    # banned term past a regex by splitting the word it sits next to.
    text = strip_marks(body).strip()
    lead_text = strip_marks(lead or "").strip()
    both = f"{lead_text} {text}".strip()

    words = len(both.split())
    if words > MAX_WORDS:
        violations.append(f"too long ({words} words; max {MAX_WORDS})")

    for m in _BANNED.finditer(both):
        violations.append(
            f"banned term ('{m.group(0)}'): this league has no salary cap, "
            f"contracts or auction budget")

    violations.extend(mark_violations(body))

    allowed = _packet_tokens(facts) | _VOCABULARY
    for run in _unknown_name_runs(both, allowed):
        violations.append(f"'{run}' is not in the facts packet")

    # A [who] span is the model asserting "these words name a person", so every
    # word in it has to be one the packet used — no sentence-initial exemption
    # and no single-token exemption, both of which exist above only because an
    # UNMARKED capital is ambiguous. Here it is not.
    for span in spans_of(body, "who"):
        # `_WORD` keeps a trailing apostrophe, so a possessive ("Mike Evans'")
        # tokenises to `evans'` and would never match the packet's `evans`.
        # Trim the edges; an interior apostrophe (Ja'Marr) is part of the name.
        unknown = [w for w in _WORD.findall(span)
                   if _norm(w) not in allowed]
        if unknown:
            violations.append(f"'{span}' is not in the facts packet")

    return violations
