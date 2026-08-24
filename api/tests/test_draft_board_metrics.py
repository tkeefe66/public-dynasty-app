from app.services.draft_board_view import build_draft_board
from tests.helpers import minimal_chain_cache_entry


def pick(**over):
    r = dict(player_id="p1", full_name="A Rookie", position="RB", drafter_id="u1",
             round=1, slot=1, picks_in_round=12, pick_no=1, draft_season=2025,
             production_total=100.0, production_started=60.0,
             production_regular=10.0, production_playoff=20.0,
             production_toilet=0.0, games_started=3)
    r.update(over)
    return r


def _board(*picks):
    return build_draft_board(
        minimal_chain_cache_entry(drafted_picks=list(picks)), season=2025)


def test_the_five_metric_run_reaches_each_pick():
    p = _board(pick(), pick(player_id="p2", pick_no=2)).picks[0]
    assert (p.production_total, p.production_started, p.production_regular,
            p.production_playoff, p.production_toilet, p.games_started) == (
        100.0, 60.0, 10.0, 20.0, 0.0, 3)


def test_phases_sum_to_less_than_started_and_that_is_not_an_error():
    # A bye or placement week belongs to no phase. This is the contract, so it
    # is asserted rather than left as a surprise for the next reader.
    p = _board(pick(), pick(player_id="p2", pick_no=2)).picks[0]
    assert p.production_regular + p.production_playoff + p.production_toilet < p.production_started


def test_owner_points_above_round_is_zero_sum_across_the_class():
    b = _board(pick(drafter_id="a", production_total=200.0),
               pick(player_id="p2", pick_no=2, drafter_id="b", production_total=0.0))
    assert round(sum(o.points_above_round or 0.0 for o in b.owners), 6) == 0.0


def test_owners_are_sorted_by_points_above_round_not_by_raw_production():
    # PAR order must DIVERGE from Total order here, or the test cannot tell the
    # two sort keys apart. With one pick per owner per round, PAR is just
    # total minus a shared constant and the orderings are always identical —
    # so the fixture deliberately gives owners uneven round distributions.
    #
    #   round 1: b=300, d=300  -> avg 300  -> PAR b=0,   d=0
    #   round 3: a=100, c=0    -> avg  50  -> PAR a=+50, c=-50
    #
    # Raw Total ranks b/d first (300) and a third (100).
    # PAR ranks a FIRST (+50) — he beat his round by 50 while b and d merely
    # matched theirs. That is the whole point of the metric: it rewards
    # drafting well, not drafting early.
    b = _board(
        pick(drafter_id="b", round=1, pick_no=1, production_total=300.0),
        pick(player_id="p2", drafter_id="d", round=1, pick_no=2, production_total=300.0),
        pick(player_id="p3", drafter_id="a", round=3, pick_no=3, production_total=100.0),
        pick(player_id="p4", drafter_id="c", round=3, pick_no=4, production_total=0.0),
    )
    assert b.graded is True
    assert b.owners[0].user_id == "a", "PAR must outrank raw production"
    assert b.owners[-1].user_id == "c"
    assert b.owners[0].points_above_round == 50.0
    # Zero-sum still holds on this uneven distribution.
    assert round(sum(o.points_above_round or 0.0 for o in b.owners), 6) == 0.0


def test_owner_production_phases_sum_across_the_owners_picks():
    # I3 / C: the accumulator in `draft_board_view.py` sums into a dict whose
    # keys double as the row-dict keys it reads (`for key in acc: acc[key] +=
    # r.get(key)`). Misspell or rename one key on either side and the loop
    # silently sums a key that doesn't exist -> 0.0 for every owner, forever,
    # with no exception and no failing test. Byte-for-byte the failure mode a
    # previous fix round closed on the owner-view side; nothing here asserted
    # on `production_started`/`_regular`/`_playoff`/`_toilet` before this.
    #
    # Two picks, one owner, distinct values per phase so a sum is
    # distinguishable from a single pick's own figures or from 0.0.
    b = _board(
        pick(drafter_id="u1",
             production_started=60.0, production_regular=10.0,
             production_playoff=20.0, production_toilet=5.0),
        pick(player_id="p2", pick_no=2, drafter_id="u1",
             production_started=40.0, production_regular=15.0,
             production_playoff=0.0, production_toilet=3.0),
    )
    assert len(b.owners) == 1
    o = b.owners[0]
    assert o.production_started == 100.0
    assert o.production_regular == 25.0
    assert o.production_playoff == 20.0
    assert o.production_toilet == 8.0


def test_pre_feature_rows_default_rather_than_raise():
    # Rows written before phase 2 carry no production_started key.
    p = _board({"player_id": "p1", "full_name": "X", "position": "RB",
                "drafter_id": "u1", "round": 1, "slot": 1, "picks_in_round": 12,
                "pick_no": 1, "draft_season": 2025, "production_total": 0.0},
               {"player_id": "p2", "full_name": "Y", "position": "WR",
                "drafter_id": "u2", "round": 1, "slot": 2, "picks_in_round": 12,
                "pick_no": 2, "draft_season": 2025, "production_total": 0.0}).picks[0]
    assert p.production_started == 0.0
    assert p.games_started == 0
