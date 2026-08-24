import asyncio

from app.services.franchise_blurb_gen import (
    FRANCHISE_PROMPT_VERSION, generate_franchise_blurbs,
)
from sleeper_dynasty.models.franchise_outlook import (
    FranchiseFacts, franchise_facts_hash,
)


def _facts(uid, **over):
    base = dict(
        user_id=uid, owner_name=uid, team_name=None, league_format="dynasty",
        window="Contending", young_core_share=0.5, roster_rank=1, roster_of=2,
        young_core=["Malik Nabers"], aging_risks=[],
        draft_capital_status="neutral", draft_capital_net=0.0,
        top_need=None, signature_trade=None)
    base.update(over)
    return FranchiseFacts(**base)


class _FakeWriter:
    """Returns `blurbs` in order, cycling on the last one."""

    model = "fake"

    def __init__(self, blurbs=None):
        self.calls = 0
        self._blurbs = blurbs

    def write(self, facts):
        self.calls += 1
        if self._blurbs is None:
            return {"blurb": f"blurb for {facts.user_id}"}
        i = min(self.calls - 1, len(self._blurbs) - 1)
        return {"blurb": self._blurbs[i]}


def test_generates_and_skips_unchanged_by_hash():
    facts_by_owner = {"uA": _facts("uA"), "uB": _facts("uB")}
    writer = _FakeWriter()
    out = asyncio.run(generate_franchise_blurbs(
        facts_by_owner=facts_by_owner, prior_blurbs={}, writer=writer))
    assert out["uA"]["blurb"] == "blurb for uA"
    assert writer.calls == 2

    # Second run with matching prior hashes -> no new writer calls.
    writer2 = _FakeWriter()
    out2 = asyncio.run(generate_franchise_blurbs(
        facts_by_owner=facts_by_owner, prior_blurbs=out, writer=writer2))
    assert writer2.calls == 0
    assert out2["uA"]["blurb"] == "blurb for uA"


def test_prompt_version_is_folded_into_the_stored_hash():
    """A persona-only edit never moves the facts hash, so without this a
    prompt change would be skipped forever (STORY_PROMPT_VERSION precedent)."""
    facts = _facts("uA")
    out = asyncio.run(generate_franchise_blurbs(
        facts_by_owner={"uA": facts}, prior_blurbs={}, writer=_FakeWriter()))
    assert out["uA"]["facts_hash"] == \
        f"{franchise_facts_hash(facts)}:{FRANCHISE_PROMPT_VERSION}"


def test_a_bumped_prompt_version_invalidates_a_cached_blurb():
    facts = _facts("uA")
    stale = {"uA": {"blurb": "old", "facts_hash":
                    f"{franchise_facts_hash(facts)}:0", "generated_at": "t"}}
    writer = _FakeWriter()
    out = asyncio.run(generate_franchise_blurbs(
        facts_by_owner={"uA": facts}, prior_blurbs=stale, writer=writer))
    assert writer.calls == 1 and out["uA"]["blurb"] == "blurb for uA"


# --- the validator drives regeneration (story_gen's shape) ------------------

def test_a_violating_blurb_is_regenerated():
    writer = _FakeWriter([
        "Those veterans are dead weight eating cap space.",  # banned term
        "Malik Nabers anchors an ascending roster.",         # clean
    ])
    out = asyncio.run(generate_franchise_blurbs(
        facts_by_owner={"uA": _facts("uA")}, prior_blurbs={}, writer=writer,
        retry_delay=0))
    assert writer.calls == 2
    assert out["uA"]["blurb"] == "Malik Nabers anchors an ascending roster."


def test_a_persistently_violating_blurb_still_ships():
    """A flawed blurb beats a missing one — same call story_gen makes."""
    writer = _FakeWriter(["Every contract here is underwater."])
    out = asyncio.run(generate_franchise_blurbs(
        facts_by_owner={"uA": _facts("uA")}, prior_blurbs={}, writer=writer,
        max_attempts=2, retry_delay=0))
    assert writer.calls == 2
    assert out["uA"]["blurb"] == "Every contract here is underwater."


def test_an_invented_player_is_regenerated():
    writer = _FakeWriter([
        "Stefon Diggs drags this roster down.",
        "Malik Nabers is the whole case here.",
    ])
    out = asyncio.run(generate_franchise_blurbs(
        facts_by_owner={"uA": _facts("uA")}, prior_blurbs={}, writer=writer,
        retry_delay=0))
    assert out["uA"]["blurb"] == "Malik Nabers is the whole case here."


def test_a_writer_error_leaves_no_blurb_rather_than_failing():
    class _Boom:
        model = "fake"

        def write(self, facts):
            raise RuntimeError("overloaded")

    out = asyncio.run(generate_franchise_blurbs(
        facts_by_owner={"uA": _facts("uA")}, prior_blurbs={}, writer=_Boom(),
        max_attempts=2, retry_delay=0))
    assert out == {}


# --- marks: the validator reads the MARKED body ----------------------------

class _MarkWriter:
    """Returns full parse_franchise-shaped records in order, cycling."""

    model = "fake"

    def __init__(self, records):
        self.calls = 0
        self._records = records

    def write(self, facts):
        self.calls += 1
        i = min(self.calls - 1, len(self._records) - 1)
        return dict(self._records[i])


def _record(lead, body):
    from sleeper_dynasty.llm.franchise_marks import parse_segments, strip_marks
    return {"lead": lead, "body": body, "blurb": strip_marks(body),
            "segments": parse_segments(body)}


def test_a_malformed_mark_is_regenerated():
    """The stripped `blurb` has no tags left, so validating THAT would pass
    every broken mark. The generator has to hand over the marked body."""
    bad = _record("Young.", "A [shout]loud[/shout] core around Malik Nabers.")
    good = _record("Young.", "A core around [who]Malik Nabers[/who].")
    writer = _MarkWriter([bad, good])
    out = asyncio.run(generate_franchise_blurbs(
        facts_by_owner={"uA": _facts("uA")}, prior_blurbs={}, writer=writer,
        retry_delay=0))
    assert writer.calls == 2
    assert out["uA"]["segments"] == good["segments"]


def test_an_invented_who_span_is_regenerated():
    bad = _record("Young.", "[who]Stefon Diggs[/who] anchors it.")
    good = _record("Young.", "[who]Malik Nabers[/who] anchors it.")
    writer = _MarkWriter([bad, good])
    out = asyncio.run(generate_franchise_blurbs(
        facts_by_owner={"uA": _facts("uA")}, prior_blurbs={}, writer=writer,
        retry_delay=0))
    assert writer.calls == 2
    assert out["uA"]["blurb"] == "Malik Nabers anchors it."


def test_clean_marked_prose_ships_on_the_first_attempt():
    rec = _record("Young, and getting younger.",
                  "[num]50%[/num] of value sits with [who]Malik Nabers[/who] "
                  "— [good]ascending[/good] with no [risk]pressing need[/risk].")
    writer = _MarkWriter([rec])
    out = asyncio.run(generate_franchise_blurbs(
        facts_by_owner={"uA": _facts("uA")}, prior_blurbs={}, writer=writer,
        retry_delay=0))
    assert writer.calls == 1
    assert out["uA"]["lead"] == "Young, and getting younger."
    assert {"text": "50%", "mark": "num"} in out["uA"]["segments"]


def test_a_pre_marks_record_still_validates_on_its_plain_blurb():
    """A cached v2 record has no `body` key. The generator falls back to
    `blurb` rather than validating an empty string, which would pass anything."""
    writer = _FakeWriter(["Stefon Diggs anchors it.", "Malik Nabers anchors it."])
    out = asyncio.run(generate_franchise_blurbs(
        facts_by_owner={"uA": _facts("uA")}, prior_blurbs={}, writer=writer,
        retry_delay=0))
    assert writer.calls == 2
    assert out["uA"]["blurb"] == "Malik Nabers anchors it."
