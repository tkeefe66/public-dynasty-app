"""Start rate — the share of a haul's points that were actually STARTED.

One definition, two call sites. `trade_view` computes it per trade side from
breakdown rows; `owner_view` computes it per trade and per career from the
grade's own totals. Both funnel through :func:`start_rate` so the number cannot
mean two things depending on which screen you are looking at.

WHAT IT ANSWERS: did this owner leave points on the bench? ``production_started``
is starters-only across every week, ``production_total`` is the same weeks with
the bench included, so their ratio is exactly "of everything this haul scored,
how much did you actually deploy". A player who produced but sat is the whole
gap between the two.

WHY THIS IS A LEGITIMATE DERIVATION when summing the phase metrics was not: this
is a ratio of two exact quantities over the SAME weeks. The phase sum was wrong
because the three phases do not cover every week (a placement game or an
eliminated week is in none of them), so it silently under-counted. Nothing is
missing here.

NONE, NEVER ZERO, when there is nothing to divide. A haul that has not played
has no start rate, and 0% would read as "you benched everything" — the most
damning possible reading of the least information.
"""

from __future__ import annotations


def start_rate(started: float, total: float) -> float | None:
    """Fraction of ``total`` points that were started, or ``None``.

    ``None`` when ``total`` is zero or negative. Zero is the "unplayed haul"
    case; negative should not occur for a received-only tally, but a swing-style
    caller could pass one and a negative denominator makes the ratio meaningless
    rather than merely unknown.
    """
    return (started / total) if total > 0 else None
