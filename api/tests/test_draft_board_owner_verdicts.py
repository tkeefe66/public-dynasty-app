"""The Owners table's Hit/Bust rollup and its Picks count.

Both exist to satisfy one house rule — a headline figure equals the rows
beneath it — so both tests are built around the ways that can silently break.
"""

from app.services.draft_board_view import build_draft_board
from tests.helpers import minimal_chain_cache_entry


def pick(**over):
    r = dict(player_id="p1", full_name="A Rookie", position="RB", drafter_id="u1",
             round=1, slot=1, picks_in_round=12, pick_no=1, draft_season=2025,
             production_total=200.0, verdict="hit")
    r.update(over)
    return r


def _owners(*picks):
    b = build_draft_board(
        minimal_chain_cache_entry(drafted_picks=list(picks)), season=2025)
    return {o.user_id: o for o in b.owners}


def test_each_owners_counts_equal_that_owners_own_pick_verdicts():
    """Mutation this catches: rolling the counts up over ALL picks rather than
    per `drafter_id` (or reading one shared Counter for everybody).

    Two owners with DIFFERENT verdict mixes, and neither mix is a prefix or a
    permutation of the other — u1 is 2 hit / 1 bust, u2 is 1 average / 1 bust.
    A league-wide tally would give both owners 2/1/2 and pass a fixture where
    the two owners happened to draft alike.
    """
    o = _owners(
        pick(drafter_id="u1", player_id="a", pick_no=1, verdict="hit"),
        pick(drafter_id="u1", player_id="b", pick_no=2, verdict="hit"),
        pick(drafter_id="u1", player_id="c", pick_no=3, verdict="bust"),
        pick(drafter_id="u2", player_id="d", pick_no=4, verdict="average"),
        pick(drafter_id="u2", player_id="e", pick_no=5, verdict="bust"),
    )
    assert (o["u1"].hit, o["u1"].average, o["u1"].bust) == (2, 0, 1)
    assert (o["u2"].hit, o["u2"].average, o["u2"].bust) == (0, 1, 1)


def test_an_unjudged_pick_counts_toward_nothing():
    """Mutation this catches: bucketing the empty verdict — counting `""` as a
    bust (the falsy-lands-in-the-last-branch slip), or letting it inflate any
    of the three.

    The class here is deliberately MOSTLY unjudged: 3 of 4 carry no verdict,
    which is the real shape (on the reference league 39 of 108 picks are
    unjudged, an entire unplayed class among them). A fixture with one
    unjudged pick out of five would still read plausibly under a rule that
    dropped it into `bust`.
    """
    o = _owners(
        pick(player_id="a", pick_no=1, verdict="hit"),
        pick(player_id="b", pick_no=2, verdict=""),
        pick(player_id="c", pick_no=3, verdict=""),
        pick(player_id="d", pick_no=4, verdict=""),
    )["u1"]
    assert (o.hit, o.average, o.bust) == (1, 0, 0)
    # And the class is still four picks — unjudged is not unmade.
    assert o.picks_made == 4


def test_a_keeper_is_counted_as_a_pick_but_never_as_a_verdict():
    """Mutation this catches: rolling the verdict counts up over `rows`
    instead of `scored` (which would let a keeper's verdict into the owner
    row), or conversely counting `picks_made` over `scored` (which would drop
    the keeper from a count of the class the ledger visibly shows).

    The keeper here carries `verdict="hit"` on purpose — an entry stamped
    before `verdict_for_row` learned to refuse keepers. The two assertions
    pull in opposite directions, so a single list used for both cannot
    satisfy them: one demands the keeper out, the other demands it in.
    """
    o = _owners(
        pick(player_id="a", pick_no=1, verdict="hit"),
        pick(player_id="k", pick_no=2, verdict="hit", is_keeper=True),
    )["u1"]
    assert o.hit == 1, "a keeper is shown, never scored"
    assert o.picks_made == 2, "a keeper is still a row on the ledger"


def test_picks_made_counts_the_class_not_the_scored_subset():
    """Mutation this catches: `picks_made` being aliased to `total_picks`.

    `total_picks` is the ADP-coverage denominator and counts SCORED picks
    only, so the two diverge exactly when a class holds an unscorable pick.
    This fixture makes them diverge (3 made, 2 scored); a fixture with no
    keeper leaves them equal and the alias passes.
    """
    o = _owners(
        pick(player_id="a", pick_no=1),
        pick(player_id="b", pick_no=2),
        pick(player_id="k", pick_no=3, is_keeper=True),
    )["u1"]
    assert o.picks_made == 3
    assert o.total_picks == 2
