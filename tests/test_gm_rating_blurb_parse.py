from sleeper_dynasty.llm.gm_rating_blurb_writer import parse_blurb


def test_parses_paragraph_and_pillar_highlights():
    text = (
        '{"blurb": "Tom is elite.", "highlights": '
        '{"Results": "Two rings lead the league.", '
        '"Assets": "Young and pick-rich."}}'
    )
    r = parse_blurb(text)
    assert r["blurb"] == "Tom is elite."
    assert r["pillars"] == {
        "results": "Two rings lead the league.",
        "assets": "Young and pick-rich.",
    }


def test_strips_markdown_fence():
    text = '```json\n{"blurb": "Hi.", "highlights": {"Results": "A title run."}}\n```'
    r = parse_blurb(text)
    assert r["blurb"] == "Hi."
    assert r["pillars"] == {"results": "A title run."}


def test_collapses_whitespace_in_highlights():
    text = '{"blurb": "Hi.", "highlights": {"Assets": "Young\\n  and   deep."}}'
    r = parse_blurb(text)
    assert r["pillars"]["assets"] == "Young and deep."


def test_falls_back_to_plain_paragraph_when_not_json():
    text = "Just a plain paragraph, no JSON here."
    r = parse_blurb(text)
    assert r["blurb"] == "Just a plain paragraph, no JSON here."
    assert "pillars" not in r


def test_omits_pillars_key_when_no_highlights():
    text = '{"blurb": "Only a paragraph."}'
    r = parse_blurb(text)
    assert r["blurb"] == "Only a paragraph."
    assert "pillars" not in r
