"""The bracket-mark parser: model markup in, renderable segments out."""

from sleeper_dynasty.llm.franchise_marks import (
    MARKS, mark_violations, normalize_markup, parse_segments, strip_marks,
)


def _texts(segments):
    return [(s["text"], s["mark"]) for s in segments]


def test_the_four_marks_are_the_vocabulary():
    assert MARKS == ("num", "who", "good", "risk")


def test_plain_prose_is_one_unmarked_segment():
    assert _texts(parse_segments("Nothing marked here.")) == [
        ("Nothing marked here.", None)]


def test_each_mark_becomes_its_own_segment():
    body = ("[num]73%[/num] of value sits with [who]Jahmyr Gibbs[/who] — "
            "[good]contention now[/good], but [risk]QB depth[/risk] is thin.")
    assert _texts(parse_segments(body)) == [
        ("73%", "num"),
        (" of value sits with ", None),
        ("Jahmyr Gibbs", "who"),
        (" — ", None),
        ("contention now", "good"),
        (", but ", None),
        ("QB depth", "risk"),
        (" is thin.", None),
    ]


def test_strip_marks_is_what_the_word_cap_counts():
    body = "[num]73%[/num] of value sits with [who]Jahmyr Gibbs[/who]."
    assert strip_marks(body) == "73% of value sits with Jahmyr Gibbs."
    assert len(strip_marks(body).split()) == 7

    # Tags glued to their words happen to split the same either way, which is
    # what makes counting the marked-up string look safe. It is not: the moment
    # the model spaces a tag off, every tag becomes a word.
    spaced = "[num] 73% [/num] of value sits with [who] Jahmyr Gibbs [/who]."
    assert len(spaced.split()) == 11
    assert len(strip_marks(normalize_markup(spaced)).split()) == 7


def test_normalize_pulls_stray_whitespace_outside_the_tags():
    spaced = "[num] 73% [/num] of value with [who] Jahmyr Gibbs [/who]."
    tidy = normalize_markup(spaced)
    assert tidy == "[num]73%[/num] of value with [who]Jahmyr Gibbs[/who]."
    # Segments and plain text both derive from the SAME normalized string, so
    # no span opens on a blank and the two can never disagree.
    assert "".join(s["text"] for s in parse_segments(tidy)) == strip_marks(tidy)
    assert ("73%", "num") in _texts(parse_segments(tidy))


def test_empty_segments_are_dropped_not_rendered():
    assert _texts(parse_segments("[num][/num]ok")) == [("ok", None)]
    assert parse_segments("") == []
    assert parse_segments(None) == []


class TestDegradation:
    """A bad tag costs its own emphasis, never the whole blurb."""

    def test_unknown_mark_degrades_that_span_to_plain_text(self):
        segs = parse_segments("a [shout]loud[/shout] b")
        assert _texts(segs) == [("a loud b", None)]

    def test_unclosed_tag_degrades_the_remainder_to_plain_text(self):
        # Not "mark everything after it": an unclosed [who] would set the whole
        # rest of the paragraph as a person's name.
        assert _texts(parse_segments("a [who]Gibbs and more")) == [
            ("a Gibbs and more", None)]

    def test_an_earlier_closed_mark_survives_a_later_unclosed_one(self):
        segs = parse_segments("[num]73%[/num] then [who]Gibbs and more")
        assert _texts(segs) == [("73%", "num"), (" then Gibbs and more", None)]

    def test_stray_closing_tag_is_dropped(self):
        assert _texts(parse_segments("a[/who] b")) == [("a b", None)]

    def test_nested_tags_flatten_to_the_outer_mark(self):
        # The inner open is consumed; nothing renders with two treatments.
        segs = parse_segments("[who]Josh [num]12[/num][/who]")
        assert all(s["mark"] in (None, "who") for s in segs)
        assert "".join(s["text"] for s in segs) == "Josh 12"

    def test_a_bracketed_phrase_is_left_alone(self):
        # Only a bracketed BARE LOWERCASE WORD is treated as an attempted mark.
        assert _texts(parse_segments("value [Week 3] holds")) == [
            ("value [Week 3] holds", None)]

    def test_a_bracketed_bare_word_is_read_as_an_attempted_mark(self):
        # The cost of being able to swallow an unknown tag rather than show it
        # to the reader. The persona has no other use for a bracket.
        assert _texts(parse_segments("value [sic] holds")) == [
            ("value  holds", None)]


class TestViolations:
    """What the validator regenerates on. Degradation still reports."""

    def test_clean_markup_has_no_violations(self):
        assert mark_violations(
            "[num]73%[/num] and [who]Gibbs[/who] and [good]depth[/good]") == []

    def test_unknown_mark_is_a_violation(self):
        v = mark_violations("a [shout]loud[/shout] b")
        assert v and all("shout" in x for x in v)

    def test_unbalanced_open_is_a_violation(self):
        v = mark_violations("a [who]Gibbs")
        assert len(v) == 1 and "who" in v[0] and "unclosed" in v[0]

    def test_unbalanced_close_is_a_violation(self):
        v = mark_violations("a[/num] b")
        assert len(v) == 1 and "num" in v[0] and "unbalanced" in v[0]

    def test_mismatched_close_is_a_violation(self):
        assert mark_violations("[who]Gibbs[/num]") != []

    def test_nesting_is_a_violation(self):
        v = mark_violations("[who]Josh [num]12[/num][/who]")
        assert any("nest" in x.lower() for x in v)


def test_who_spans_are_extracted_for_the_name_check():
    from sleeper_dynasty.llm.franchise_marks import spans_of

    body = "[who]Jahmyr Gibbs[/who] and [who]Puka Nacua[/who], not [num]25[/num]"
    assert spans_of(body, "who") == ["Jahmyr Gibbs", "Puka Nacua"]
    assert spans_of(body, "num") == ["25"]
    assert spans_of("plain", "who") == []
