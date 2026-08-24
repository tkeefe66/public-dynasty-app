"""Player name normalization for cross-source matching.

Fantasy data sources spell names differently — "A.J. Brown" on one site,
"AJ Brown" or "A.J Brown" on another. Sleeper itself uses ``full_name``
values that don't line up with FantasyPros or KeepTradeCut spellings.

``normalize_player_name`` produces a canonical key that makes those
spellings collide. Use it as the dict key when building cross-source
lookups (e.g. fantasypros projections, KTC values).

Rules:
    - Lowercase
    - Strip punctuation: ``.`` ``'`` ``,``
    - Strip common roman-numeral / generational suffixes
      (``jr``, ``sr``, ``ii``, ``iii``, ``iv``, ``v``)
    - Collapse runs of internal whitespace into a single space
    - Preserve hyphens in compound names ("Amon-Ra St. Brown")
    - Strip leading / trailing whitespace
"""

from __future__ import annotations

import re

# Characters we strip out entirely (replaced with empty string, so
# "A.J." becomes "AJ" and "D'Andre" becomes "DAndre").
_PUNCTUATION_RE = re.compile(r"[.,']")

# Suffix tokens to drop when they appear as the final whitespace-separated
# token after punctuation stripping. We match case-insensitively against
# the lowercased form.
_SUFFIX_TOKENS = frozenset({"jr", "sr", "ii", "iii", "iv", "v"})

# Pattern for collapsing internal whitespace.
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_player_name(name: str) -> str:
    """Return a canonical lowercase form of a player name for matching.

    See module docstring for rules.

    Args:
        name: Raw player name from any data source.

    Returns:
        Canonical form, e.g. "A.J. Brown" -> "aj brown",
        "Marvin Harrison Jr." -> "marvin harrison",
        "Amon-Ra St. Brown" -> "amon-ra st brown".
        Returns "" for empty / None-like input.
    """
    if not name:
        return ""

    # 1. Strip punctuation (periods, apostrophes, commas).
    cleaned = _PUNCTUATION_RE.sub("", name)

    # 2. Lowercase + trim outer whitespace.
    cleaned = cleaned.lower().strip()

    # 3. Collapse runs of internal whitespace to a single space.
    cleaned = _WHITESPACE_RE.sub(" ", cleaned)

    # 4. Drop trailing suffix token if present. Only one — we don't expect
    #    nested suffixes like "Jr. III".
    parts = cleaned.split(" ")
    if len(parts) > 1 and parts[-1] in _SUFFIX_TOKENS:
        parts = parts[:-1]

    return " ".join(parts)
