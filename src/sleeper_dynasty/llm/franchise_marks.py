"""Inline emphasis marks in franchise-blurb prose: parse, strip, validate.

WHY A MARKUP AT ALL, AND WHY THE MODEL EMITS IT
-------------------------------------------------------------------------
The owner hero's paragraph differentiates four things inside the prose — a
figure, a person, a strength, a risk. The alternative was a regex over finished
prose: match anything percent-shaped, match anything that looks like a player
name. That is fragile in exactly the way that matters, because it guesses at
meaning after the fact ("25 and under" is a figure; "Week 25" is not; a
capitalised pair is a name until it is "Trade Value"). The model already knows
which is which while it is writing, so it says so.

WHY BRACKETS AND NOT HTML/MARKDOWN
Two reasons. A weak model emits ``[num]73%[/num]`` far more reliably than
nested JSON or balanced HTML, and — decisively — nothing downstream may ever
treat model output as markup. This parses to a list of ``{text, mark}`` and the
renderer maps each segment to a React element, so React escapes every character
and there is no ``dangerouslySetInnerHTML`` anywhere on the path. Angle brackets
would invite exactly the shortcut this shape exists to foreclose.

DEGRADATION IS NOT THE SAME AS ACCEPTANCE
A malformed or unknown tag loses its emphasis and the words survive as plain
prose — a broken blurb still reads. It is *also* reported by ``mark_violations``
so the generator regenerates it. Rendering and validating disagree on purpose:
the reader gets the best available text, the pipeline gets told it was wrong.
"""

from __future__ import annotations

import re

# The four treatments, and there is no fifth — see
# `web/components/furniture/Emphasis.tsx` for why colour is confined to the two
# valence marks. Order matches that component's `EMPHASIS_KINDS`.
MARKS: tuple[str, ...] = ("num", "who", "good", "risk")

# Tag-SHAPED tokens, not just known ones: an unknown tag has to be RECOGNISED
# before it can be swallowed, or `[shout]loud[/shout]` degrades by showing the
# reader its own tags. So any bracketed bare lowercase word is treated as an
# attempted mark — in this prose a bracket is always markup, because the persona
# has no other use for one. A bracketed phrase that is not tag-shaped
# (`[Week 3]`, `[per the packet]`) is left in the prose untouched.
_TAG = re.compile(r"\[(/?)([a-z]+)\]")


def normalize_markup(body: str | None) -> str:
    """Tidy the model's raw markup ONCE, before anything derives from it.

    One failure, two spellings: the model sometimes spaces a tag off its word
    (``[num] 73% [/num]``). Whitespace immediately INSIDE a tag pair is deleted
    — the separating space outside the pair is already there — and runs are then
    collapsed. Without this, stripping the tags leaves a double space and an
    orphaned ``.`` that the word count charges as a word, and the span renders
    with a leading blank inside its hairline border.

    Done here rather than inside ``strip_marks`` on purpose: every consumer —
    segments, plain text, word count, validator — reads the SAME normalized
    string, so the rendered prose and the counted prose can never drift apart.
    """
    if not body:
        return ""
    s = re.sub(r"(\[[a-z]+\])\s+", r"\1", body)     # nothing right after an open
    s = re.sub(r"\s+(\[/[a-z]+\])", r"\1", s)       # nothing right before a close
    return re.sub(r"\s+", " ", s).strip()


def _tokens(text: str):
    """Yield ``("text", s)`` / ``("open"|"close", name)`` over the markup."""
    pos = 0
    for m in _TAG.finditer(text):
        if m.start() > pos:
            yield "text", text[pos:m.start()]
        yield ("close" if m.group(1) else "open"), m.group(2)
        pos = m.end()
    if pos < len(text):
        yield "text", text[pos:]


def parse_segments(body: str | None) -> list[dict]:
    """Marked prose -> ``[{"text": str, "mark": str | None}, ...]``.

    Adjacent unmarked runs are merged so the renderer emits one text node per
    stretch of plain prose rather than one per swallowed tag. Empty segments are
    dropped — an empty ``<span>`` with a bottom border would draw a stray rule.
    """
    if not body:
        return []

    out: list[dict] = []
    open_mark: str | None = None
    # Index in `out` where the currently-open mark began. An UNCLOSED mark must
    # not survive: `[who]` with no close would otherwise set every remaining
    # word of the paragraph as a person's name, which reads far worse than the
    # plain prose it degrades to. So the span stays provisional until it closes.
    open_at = 0

    def push(text: str, mark: str | None) -> None:
        if not text:
            return
        out.append({"text": text, "mark": mark})

    for kind, value in _tokens(body):
        if kind == "text":
            push(value, open_mark)
        elif kind == "open":
            # An unknown mark, or a second open inside an open one, is swallowed
            # and its text inherits whatever is already in force. Never two
            # treatments on one span.
            if value in MARKS and open_mark is None:
                open_mark, open_at = value, len(out)
        elif value == open_mark:
            open_mark = None
        # A stray or mismatched close is swallowed: dropping the delimiter and
        # keeping the words is the degradation this module promises.

    if open_mark is not None:
        for seg in out[open_at:]:
            seg["mark"] = None

    # Merge adjacent plain runs last, once every mark is final — doing it during
    # the walk would have to un-merge when a provisional span is revoked.
    merged: list[dict] = []
    for seg in out:
        if merged and merged[-1]["mark"] is None and seg["mark"] is None:
            merged[-1]["text"] += seg["text"]
        else:
            merged.append(seg)
    return merged


def strip_marks(body: str | None) -> str:
    """The prose a reader would see, with every tag removed.

    This is what the word cap counts and what the plain-text fallback renders.
    Counting the marked-up string instead would let the tags inflate the count
    and fail an in-budget blurb.
    """
    return "".join(t for kind, t in _tokens(body or "") if kind == "text")


def spans_of(body: str | None, mark: str) -> list[str]:
    """Every well-formed span carrying ``mark``, in order.

    Used by the validator: every ``[who]`` span has to be a name the facts
    packet actually contains, which is the check that stops the model inventing
    a player now that names are structural rather than incidental.
    """
    return [s["text"] for s in parse_segments(body) if s["mark"] == mark]


def mark_violations(body: str | None) -> list[str]:
    """Human-readable markup faults (empty = well-formed).

    Deliberately a second pass rather than a by-product of ``parse_segments``:
    the parser's job is to always produce something renderable, and giving it a
    failure channel is how "one bad tag" turns into "no paragraph".
    """
    violations: list[str] = []
    stack: list[str] = []

    for kind, value in _tokens(body or ""):
        if kind == "text":
            continue
        if kind == "open":
            if value not in MARKS:
                violations.append(
                    f"unknown mark '[{value}]' (allowed: "
                    f"{', '.join(MARKS)})")
                continue
            if stack:
                violations.append(
                    f"nested mark '[{value}]' inside '[{stack[-1]}]' — marks "
                    f"never overlap")
            stack.append(value)
        else:
            if value not in MARKS:
                violations.append(f"unknown mark '[/{value}]'")
            elif not stack:
                violations.append(f"unbalanced '[/{value}]' with no opening tag")
            elif stack[-1] != value:
                violations.append(
                    f"'[/{value}]' closes '[{stack[-1]}]' — mismatched tags")
                stack.pop()
            else:
                stack.pop()

    violations.extend(f"unclosed '[{m}]'" for m in stack)
    return violations
