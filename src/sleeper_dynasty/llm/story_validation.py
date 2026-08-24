"""Deterministic backstops for trade-story prose.

The story writer is a weak model (Haiku) and the persona bans more than it can
reliably obey. Rather than trust prose discipline, enforce it:

- ``repair_prose`` / ``tidy_headline`` apply cheap, always-safe fixes (em dashes,
  trailing headline punctuation, leading markdown). These never warrant a costly
  regeneration -- just clean the text.
- ``find_violations`` detects *semantic* problems that a repair cannot fix and a
  fresh sample probably can: reversed trade direction (the recurring bug), bare
  positional epithets (the vector that produced it), and over-long headlines.
  The generator regenerates while violations remain (bounded), then ships the
  best-effort text.

Pure and unit-tested; no Anthropic dependency.
"""

from __future__ import annotations

import re

from sleeper_dynasty.models.trade_story import TradeStoryFacts

# --- repair: always-safe text fixes -----------------------------------------

_EM_DASH = re.compile(r"\s*(?:—|--|–)\s*")


def repair_prose(text: str) -> str:
    """Replace em/en dashes and ``--`` with a comma; collapse the seams.

    The persona bans dashes outright. Stripping is invisible and damage-free, so
    we repair rather than regenerate. Idempotent.
    """
    text = _EM_DASH.sub(", ", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.;:])", r"\1", text)
    return text.strip()


def tidy_headline(headline: str) -> str:
    """Strip leading markdown and a trailing period from the headline."""
    headline = headline.strip().lstrip("#").strip()
    headline = headline.strip("*").strip()
    headline = re.sub(r"\.+$", "", headline).strip()
    return headline


# --- violations: semantic problems that warrant regeneration ----------------

# A received player can legitimately be "flipped"/"traded away"/"sent" onward
# (the persona allows it), so those verbs are EXCLUDED. These verbs, applied to a
# player a side RECEIVED, can only mean the direction was reversed.
_SOLD_VERBS = (
    r"sold(?:\s+low)?(?:\s+on)?|shipped(?:\s+out)?|shipped\s+off|unloaded|"
    r"offloaded|gave\s+up|gave\s+away|parted\s+with|dumped|jettisoned|"
    r"surrendered|coughed\s+up|let\s+go\s+of|shipped\s+away"
)
# Applied to a player a side GAVE, these can only mean reversed direction (you
# cannot acquire-in-this-trade what you gave away; there is no "later" reading).
_BOUGHT_VERBS = (
    r"bought(?:\s+high)?(?:\s+on)?|acquired|landed|grabbed|nabbed|snagged|"
    r"picked\s+up|hauled\s+in|reeled\s+in|brought\s+in|added"
)

# Bare positional / role epithets the persona forbids (use the player's name).
# Matched only after an article/adjective so we don't trip on, say, "wide
# receiver corps" discussion -- in practice these stories should never use them.
_EPITHET = re.compile(
    r"\b(?:the|a|an|that|this|young|veteran|vet|ageing|aging|star|stud|elite|"
    r"former|fading|washed|prized|cornerstone|workhorse|bell[\s-]?cow)\s+"
    r"(?:\w+\s+){0,2}?"
    r"(?:running\s+backs?|wide\s+receivers?|tight\s+ends?|wideouts?|"
    r"quarterbacks?|halfbacks?|fullbacks?|pass[\s-]?catchers?|"
    r"signal[\s-]?callers?|receivers?|rushers?)\b",
    re.I,
)

_PICK_RE = re.compile(r"\bpick\b", re.I)


def _player_names(summary: str) -> list[str]:
    """Pull player names out of a received/given summary.

    Summaries look like "Mike Evans (WR)" or "2026 3rd pick · 2027 2nd pick" or
    "Bijan Robinson". Pick entries carry "pick" and are skipped.
    """
    names: list[str] = []
    for part in (summary or "").split("·"):
        part = part.strip()
        if not part or _PICK_RE.search(part):
            continue
        # Drop a trailing "(POS)".
        name = re.sub(r"\s*\([^)]*\)\s*$", "", part).strip()
        if name:
            names.append(name)
    return names


def _name_variants(name: str) -> list[str]:
    """Full name plus a surname-only fallback (the model often shortens)."""
    variants = [name]
    parts = name.split()
    if len(parts) > 1 and len(parts[-1]) >= 4:
        variants.append(parts[-1])
    return variants


def _subject_did(text: str, owner: str, verbs: str, name: str) -> bool:
    """True if `owner` is the subject tying a verb in `verbs` to `name`.

    Anchoring on the owner name as the subject is what keeps this precise: the
    same verb+player is *correct* for the other side ("Amir shipped Mike Evans"
    when Amir gave him), and only a reversal when the receiving owner is the one
    doing the selling ("Tom sold Mike Evans" when Tom got him). The possessive
    ("Tom's pattern...") is excluded so it is never read as the subject. Misses
    pronoun-subject reversals on purpose; the epithet rule and the upstream
    deterministic fields cover those, and a false positive would loop forever.
    """
    for variant in _name_variants(name):
        pat = re.compile(
            rf"\b{re.escape(owner)}\b(?!['’]s)(?:\s+\w+){{0,3}}?\s+"
            rf"(?:{verbs})\b(?:\s+\w+){{0,4}}?\s+{re.escape(variant)}\b", re.I)
        if pat.search(text):
            return True
    return False


def find_violations(verdict: str, body: str, facts: TradeStoryFacts) -> list[str]:
    """Return human-readable semantic violations (empty list = clean)."""
    violations: list[str] = []
    text = f"{verdict}\n{body}"

    # 1. Reversed trade direction -- the recurring bug.
    for side in facts.sides:
        owner = side.get("owner_name", side.get("user_id", "?"))
        for name in _player_names(side.get("received_summary", "")):
            if _subject_did(text, owner, _SOLD_VERBS, name):
                violations.append(
                    f"reversed direction: {owner} RECEIVED {name} but the story "
                    f"says they sold/gave him")
        for name in _player_names(side.get("given_summary", "")):
            if _subject_did(text, owner, _BOUGHT_VERBS, name):
                violations.append(
                    f"reversed direction: {owner} GAVE {name} but the story says "
                    f"they acquired him")

    # 2. Bare positional epithet (the vector that produces reversals).
    m = _EPITHET.search(text)
    if m:
        violations.append(
            f"bare positional epithet ('{m.group(0).strip()}'): name the player")

    # 3. Over-long headline (persona: 5-8 words).
    words = len(tidy_headline(verdict).split())
    if words > 8:
        violations.append(f"headline too long ({words} words; max 8)")

    return violations
