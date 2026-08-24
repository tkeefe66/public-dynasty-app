"""Tests for draft_needs: draft-day holes against a league-relative,
per-position replacement line, plus the two draft verdicts."""

from __future__ import annotations

import json
import math
import subprocess
import sys

from sleeper_dynasty.engine.draft_needs import build_draft_needs


def _starter_for(needs, uid, slot):
    for n in needs:
        if n.user_id == uid:
            return n.starters_by_slot[slot]
    raise KeyError(uid)


def _by_owner(needs, uid):
    return next(n for n in needs if n.user_id == uid)


# --- The five mandated tests, verbatim from the brief (positions added) --


def test_ecr_rank_is_inverted_so_the_best_player_starts():
    """The single easiest thing to get backwards. Raw ECR in = worst starts."""
    board = {"qb_elite": 1.0, "qb_bad": 300.0}
    positions = {"qb_elite": "QB", "qb_bad": "QB"}
    rosters = {"u1": {"qb_elite", "qb_bad"}}
    needs = build_draft_needs(rosters, board, positions, ["QB", "BN"], {}, {})
    assert _starter_for(needs, "u1", "QB") == "qb_elite"


def test_def_slot_never_becomes_a_hole():
    """DEF stays excluded post-K-inclusion (position-room-model spec,
    2026-08-18): dynasty-overall ECR doesn't meaningfully rank it, it's
    streamed weekly, and no rookie draft addresses it -- unchanged from
    the original K+DEF exclusion, now DEF-only. Not stripping it gives
    every owner a permanent phantom hole (empty slot, no players in the
    value map, always below any line)."""
    rosters = {"u1": {"qb1"}}
    positions = {"qb1": "QB"}
    needs = build_draft_needs(
        rosters, {"qb1": 1.0}, positions, ["QB", "DEF"], {}, {}
    )
    assert "DEF" not in needs[0].holes
    assert len(needs[0].slots) == 1, "DEF is stripped entirely, not just excluded from holes"


def test_k_slot_can_become_a_hole_under_the_league_line():
    """Position-room-model spec, 2026-08-18: K is no longer wholesale
    excluded -- kicker points are real (Sleeper scores K normally), and a
    thin K room is real diagnostic signal even though a rookie draft
    essentially never addresses it (see the spec's 'Decision: include K,
    scoped correctly'). `depth_k` is bench-only pool depth for u3 so the
    line isn't self-referential to the two owners actually being checked
    -- same discipline as every other demand-sensitive fixture in this
    file. direct demand for K = 1 slot/owner x 3 owners = 3; pool sorted
    descending [100(strong_k), 50(mid_k), 40(depth_k), 10(weak_k)] -> the
    3rd-best (line) = 40.0. weak_k (10.0) sits 30 below it -- a real hole.
    The ECR veto is a structural no-op here (deliberately no `board`
    entries -- dynasty-overall ECR doesn't rank kickers at all, so every K
    ties at the sentinel and nothing outranks anything)."""
    rosters = {
        "u1": {"qb1", "weak_k"},
        "u2": {"qb2", "strong_k"},
        "u3": {"qb3", "mid_k", "depth_k"},
    }
    points = {
        "qb1": 1.0, "qb2": 1.0, "qb3": 1.0,
        "weak_k": 10.0, "strong_k": 100.0, "mid_k": 50.0, "depth_k": 40.0,
    }
    positions = {
        "qb1": "QB", "qb2": "QB", "qb3": "QB",
        "weak_k": "K", "strong_k": "K", "mid_k": "K", "depth_k": "K",
    }
    needs = build_draft_needs(
        rosters, {}, positions, ["QB", "K", "BN"], {}, {}, points=points
    )
    u1 = _by_owner(needs, "u1")
    u2 = _by_owner(needs, "u2")
    u3 = _by_owner(needs, "u3")
    assert u1.holes == ["K"]
    k_slot = next(s for s in u1.slots if s.position == "K")
    assert k_slot.margin == -30.0
    assert k_slot.is_hole is True
    assert k_slot.vetoed is False
    assert u2.holes == []
    assert u3.starters_by_slot["K"] == "mid_k"


def test_an_unranked_player_fills_his_slot_rather_than_emptying_it():
    """Mutation this catches: dropping a board-unmapped player from the
    value map entirely (outlook.py's OLD pattern) instead of sentineling
    him. With only one candidate for the slot he must still win it --
    proves he doesn't vanish, but NOT which direction the sentinel points
    (see the direction test below, added because this one can't tell)."""
    rosters = {"u1": {"unranked_te"}}
    positions = {"unranked_te": "TE"}
    needs = build_draft_needs(
        rosters, {"someone_else": 1.0}, positions, ["TE", "BN"], {}, {}
    )
    # He may well BE a hole -- he just must not vanish and leave an empty slot,
    # which is a different (and always-true) finding.
    assert needs[0].starters_by_slot["TE"] == "unranked_te"


def test_the_unranked_sentinel_ranks_worse_than_every_real_ecr_rank():
    """Mutation this catches: inverting UNRANKED_ECR_SENTINEL's sign (e.g.
    making it negative), which would have an unranked player outrank the
    #1 overall player and drag every replacement line to the top of its
    pool -- and the old single-player fixture above stays green either way,
    since with only one candidate he wins the slot regardless of which
    direction the sentinel points. This one puts a ranked and an unranked
    player in direct competition for the same slot: only a correctly-worse
    sentinel lets the ranked one win."""
    rosters = {"u1": {"unranked_te", "ranked_te"}}
    positions = {"unranked_te": "TE", "ranked_te": "TE"}
    board = {"ranked_te": 5.0}  # unranked_te absent -> gets the sentinel
    needs = build_draft_needs(
        rosters, board, positions, ["TE", "BN"], {}, {}
    )
    assert needs[0].starters_by_slot["TE"] == "ranked_te"


def test_the_replacement_line_comes_from_the_league_not_a_constant():
    """12 teams starting one QB -> the 12th-best QB in the league."""
    rosters = {f"u{i}": {f"qb{i}"} for i in range(1, 13)}
    board = {f"qb{i}": float(i) for i in range(1, 13)}
    positions = {f"qb{i}": "QB" for i in range(1, 13)}
    needs = build_draft_needs(rosters, board, positions, ["QB", "BN"], {}, {})
    assert all(n.holes == [] for n in needs)  # everyone is at or above the line


def test_bench_slots_are_never_holes():
    needs = build_draft_needs({"u1": set()}, {}, {}, ["BN", "IR"], {}, {})
    assert needs[0].holes == []


def test_hole_verdicts_are_deterministic_across_process_hash_seeds():
    """Mutation this catches: iterating a `set` (pids, or the starters pool)
    without a tie-break, so `solve_optimal_lineup`'s stable sort breaks ties
    on whatever arbitrary order that process's string hashing produced.

    Ties are the COMMON case here, not an edge case worth a defensive-only
    test: every board-unranked player shares UNRANKED_ECR_SENTINEL, so any
    roster with unranked depth is one large tie block, and which of two
    same-valued, DIFFERENT-position candidates wins a FLEX slot changes
    that position's leaguewide demand tally, which moves its replacement
    line, which can flip a completely different owner's verdict. Measured:
    with the ordering fix reverted, this exact fixture (12 teams, the
    league's real slot shape, ~45% unranked depth) produces different
    `holes` lists in roughly a third of PYTHONHASHSEED values tried.

    A single in-process call can't observe this -- string hashes, and so
    set iteration order, are fixed for the life of one interpreter, so the
    same buggy code looks perfectly reproducible if you only ever run it
    once per process. This spawns the real fixture as a fresh interpreter
    under three different hash seeds and asserts they agree, matching how
    the bug was actually found."""
    script = """
import json, random, sys
sys.path.insert(0, "src")
from sleeper_dynasty.engine.draft_needs import build_draft_needs

random.seed(42)
roster_positions = (
    ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX", "K", "DEF"]
    + ["BN"] * 10
)
positions_pool = ["RB", "WR", "TE"]
rosters, board, positions = {}, {}, {}
pid = 0
for i in range(1, 13):
    rosters[f"u{i}"] = set()
    pid += 1
    q = f"p{pid}"
    rosters[f"u{i}"].add(q)
    board[q] = float(i)
    positions[q] = "QB"
    for pos, n in (("RB", 2), ("WR", 2), ("TE", 1)):
        for _ in range(n):
            pid += 1
            p = f"p{pid}"
            rosters[f"u{i}"].add(p)
            board[p] = float(pid)
            positions[p] = pos
    for _ in range(6):
        pid += 1
        p = f"p{pid}"
        rosters[f"u{i}"].add(p)
        positions[p] = random.choice(positions_pool)
        if random.random() > 0.45:
            board[p] = float(pid)
        # else: absent from board -> UNRANKED_ECR_SENTINEL, tied with every
        # other unranked player at that position

needs = build_draft_needs(rosters, board, positions, roster_positions, {}, {})
print(json.dumps({n.user_id: n.holes for n in needs}, sort_keys=True))
"""
    results = []
    for seed in ("0", "1", "2"):
        proc = subprocess.run(
            [sys.executable, "-c", script],
            cwd=".",
            env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"},
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert proc.returncode == 0, proc.stderr
        results.append(json.loads(proc.stdout))
    assert results[0] == results[1] == results[2]


# --- Additional tests: boundary, ordering, position isolation, verdicts --


def test_replacement_line_is_strict_below_is_a_hole_at_is_not():
    """Mutation this catches: flipping the '<' comparison to '<=' (u11's
    verdict flips: his own ACTUAL STARTER sits exactly at the line) or to
    '>' (u1..u10's and u10's obviously-safe starters get wrongly flagged).

    u1..u9 hold ranks 1-9 (single QB each, never in question). u10 owns two
    QBs and starts the better one (rank 10), leaving rank 11 on the bench
    purely as pool depth. u11 owns exactly ONE QB, rank 12 -- his own real
    starter, not a benched extra -- which is deliberately made to land ON
    the line. u12 owns exactly one QB, rank 13, genuinely below it.

    12 teams -> line = the 12th-best of the full 13-player pool = rank 12's
    value. Earlier drafts of this test put the "at the line" rank on
    someone's BENCH, where '<' and '<=' are indistinguishable (nobody's
    actual starter sits there to observe the difference) -- fixed here so
    u11's own starter is the boundary case, not a spectator to it."""
    rosters = {f"u{i}": {f"qb{i}"} for i in range(1, 10)}
    rosters["u10"] = {"qb10", "qb11"}
    rosters["u11"] = {"qb12"}
    rosters["u12"] = {"qb13"}
    board = {f"qb{i}": float(i) for i in range(1, 14)}
    positions = {f"qb{i}": "QB" for i in range(1, 14)}
    needs = build_draft_needs(rosters, board, positions, ["QB", "BN"], {}, {})
    assert _by_owner(needs, "u11").starters_by_slot["QB"] == "qb12"
    assert _by_owner(needs, "u11").holes == []
    assert _by_owner(needs, "u12").holes == ["QB"]


def test_holes_are_sorted_most_severe_first():
    """Mutation this catches: sorting ascending (or not sorting at all)
    instead of descending on severity. Real positions keep u1's QB pick and
    TE pick from cross-contaminating each other (unlike a position-blind
    model, where the best-valued player of EITHER type would grab whichever
    slot solves first) -- u1's QB (rank 100, deficit ~97 vs the QB line)
    is a much worse hole than its TE (rank 20, deficit ~17 vs the TE line),
    so QB must lead."""
    rosters = {
        "u1": {"qb_u1", "te_u1"},
        "u2": {"qb_a", "qb_b", "te_a", "te_b"},
        "u3": {"qb_u3", "te_u3"},
    }
    board = {
        "qb_u1": 100.0, "qb_a": 1.0, "qb_b": 2.0, "qb_u3": 3.0,
        "te_u1": 20.0, "te_a": 1.0, "te_b": 2.0, "te_u3": 3.0,
    }
    positions = {
        "qb_u1": "QB", "qb_a": "QB", "qb_b": "QB", "qb_u3": "QB",
        "te_u1": "TE", "te_a": "TE", "te_b": "TE", "te_u3": "TE",
    }
    needs = build_draft_needs(
        rosters, board, positions, ["QB", "TE", "BN"], {}, {}
    )
    assert _by_owner(needs, "u1").holes == ["QB", "TE"]


def test_duplicate_slot_labels_get_distinct_starters_by_slot_keys():
    """Mutation this catches: a starters_by_slot dict keyed only by bare
    slot label, which would silently drop one of two RB starters (the
    second write overwrites the first). Two RB slots, two RB-caliber
    players -- both must show up, under two different keys."""
    rosters = {"u1": {"rb_good", "rb_ok"}}
    board = {"rb_good": 1.0, "rb_ok": 2.0}
    positions = {"rb_good": "RB", "rb_ok": "RB"}
    needs = build_draft_needs(
        rosters, board, positions, ["RB", "RB", "BN"], {}, {}
    )
    slots = needs[0].starters_by_slot
    assert set(slots.values()) == {"rb_good", "rb_ok"}
    assert len([v for v in slots.values() if v is not None]) == 2


def test_replacement_line_is_computed_per_position_not_leaguewide():
    """Mutation this catches: reverting to one shared leaguewide value pool
    instead of a per-position pool.

    Every owner here has an EQUALLY weak QB (ranks 50/60/70 -- nobody is
    good) and an EQUALLY strong RB (ranks 1/2/3 -- nobody is bad). A
    leaguewide-pool line would mix the strong RB values into the QB
    threshold: the 3rd-best value OVERALL is an RB's (-3), and u1's QB
    (-50) would wrongly fail that mixed bar. The correct per-position QB
    line is drawn only from the three QB values (worst of the three, -70)
    -- u1's QB (-50) is actually the BEST of the three weak ones and must
    clear it. Nobody in this league should show any hole at all."""
    rosters = {
        "u1": {"qb1", "rb1"},
        "u2": {"qb2", "rb2"},
        "u3": {"qb3", "rb3"},
    }
    board = {
        "qb1": 50.0, "qb2": 60.0, "qb3": 70.0,
        "rb1": 1.0, "rb2": 2.0, "rb3": 3.0,
    }
    positions = {
        "qb1": "QB", "qb2": "QB", "qb3": "QB",
        "rb1": "RB", "rb2": "RB", "rb3": "RB",
    }
    needs = build_draft_needs(
        rosters, board, positions, ["QB", "RB", "BN"], {}, {}
    )
    assert _by_owner(needs, "u1").holes == []


def test_demand_is_frozen_at_direct_slot_count_not_flex_inflated():
    """Position-room-model fix (2026-08-18): FLEX occupancy used to feed
    back into a position's demand tally (an RB started in FLEX counted as
    ANOTHER RB start leaguewide), diluting the replacement line for every
    owner who never put that position in FLEX at all -- the ChocGummyBear
    case from the spec (a real RB2 read as 'no hole' because other owners'
    FLEX choices inflated the RB line's depth). Demand is now the
    position's own direct starting-slot count x owner count, full stop --
    nobody drafts a FLEX.

    2 owners, roster = 1 direct RB slot + 1 FLEX (RB-only pool, so FLEX
    always resolves to an RB). Old model: demand['RB'] = 4 (2 owners x 2 RB
    starts each, FLEX included) -> line = 4th-best = 10.0 (rb2b's own
    value) -> u2's rb2b(10.0) sits exactly ON the line it helped define,
    no hole. New model: demand['RB'] = 2 (2 owners x 1 DIRECT RB slot) ->
    line = 2nd-best = 90.0 (rb1b's value) -> u2's whole roster (50.0, 10.0)
    sits well below it -- both a real hole. This also proves the FLEX
    occupant is still checked against its own real position's (RB) line,
    not a nonexistent 'FLEX' line -- u2's FLEX slot (rb2b) is flagged a
    hole exactly like its RB slot."""
    rosters = {"u1": {"rb1a", "rb1b"}, "u2": {"rb2a", "rb2b"}}
    points = {"rb1a": 100.0, "rb1b": 90.0, "rb2a": 50.0, "rb2b": 10.0}
    positions = {p: "RB" for p in points}
    needs = build_draft_needs(
        rosters, {}, positions, ["RB", "FLEX", "BN"], {}, {}, points=points
    )
    u1 = _by_owner(needs, "u1")
    u2 = _by_owner(needs, "u2")
    assert u1.starters_by_slot["RB"] == "rb1a"
    assert u1.starters_by_slot["FLEX"] == "rb1b"
    assert u1.holes == []
    assert u2.starters_by_slot["RB"] == "rb2a"
    assert u2.starters_by_slot["FLEX"] == "rb2b"
    assert u2.holes == ["RB"]
    for s in u2.slots:
        assert s.is_hole is True
        assert s.margin is not None and s.margin < 0


def test_flex_only_position_with_no_direct_slot_gets_no_line_at_all():
    """Final-review Finding 4 (docstring correction + pinned regression):
    `_direct_demand` only ever produces an entry for a slot label with
    EXACTLY ONE eligible position (`len(SLOT_ELIGIBILITY.get(slot)) == 1`)
    -- a FLEX-type label like "FLEX" itself never counts. If a league's
    `roster_positions` has NO direct single-position slot for some
    FLEX-eligible position at all, that position never gets an entry in
    `demand`, so it never gets an entry in `lines`/`ecr_lines` either
    (`_nth_best` only iterates `demand.items()`). Every occupant of that
    position -- however he got a starting slot, FLEX included -- then hits
    `lines.get(label) is None` in Pass 3 and reads `margin=None`,
    `is_hole=False`: NO verdict at all, not merely a deep one. This is the
    module's deliberate safe-failure direction (silence over a false
    verdict, same principle as the empty-slot handling above) -- not a bug.

    `roster_positions = ["QB", "FLEX", "BN"]`: `_direct_demand` sees
    "QB" (single-eligible, demand=2 for 2 owners) and "FLEX" (eligible =
    {RB, WR, TE}, more than one, skipped) -- `demand == {"QB": 2}`, no "TE"
    key ever exists. Both owners' only FLEX-eligible players are TE (no
    RB/WR anywhere in the fixture), so FLEX always resolves to a TE and its
    `slot_checks` label is "TE" (Pass 3 checks the occupant's real
    position, never the raw slot label). u2's TE (`te_terrible`) is given
    the single worst rank on the whole board (rank 999, versus u1's
    `te_elite` at rank 2) -- as bad a player as this fixture can construct
    -- specifically to prove the silence isn't a coincidence of a
    borderline value: even the worst possible occupant gets no line, no
    hole, no margin, because TE has no direct slot to draw one from.
    """
    rosters = {"u1": {"qb_elite", "te_elite"}, "u2": {"qb_weak", "te_terrible"}}
    board = {
        "qb_elite": 1.0, "qb_weak": 50.0,
        "te_elite": 2.0, "te_terrible": 999.0,
    }
    positions = {
        "qb_elite": "QB", "qb_weak": "QB",
        "te_elite": "TE", "te_terrible": "TE",
    }
    needs = build_draft_needs(
        rosters, board, positions, ["QB", "FLEX", "BN"], {}, {}
    )
    u2 = _by_owner(needs, "u2")
    assert u2.starters_by_slot["FLEX"] == "te_terrible"
    assert "TE" not in u2.holes
    te_slot = next(s for s in u2.slots if s.slot == "FLEX")
    assert te_slot.position == "TE"
    assert te_slot.margin is None
    assert te_slot.is_hole is False
    assert te_slot.vetoed is False


def test_an_empty_slot_is_rendered_as_empty_not_a_hole():
    """C1 fix (2026-08-17): an empty slot -- whether FLEX-type (no single
    real position to blame) or a genuine single-position slot with nobody
    on the roster -- has nobody to compare a replacement line against.
    Both now get `margin=None`/`is_hole=False`/`vetoed=False` and render as
    an empty slot, not a hole.

    Pre-fix, an empty single-position slot (QB here) got
    `margin=float("-inf")` and was pushed straight into `holes` -- which is
    exactly the non-finite value that reached `SlotStandingResp.margin` and
    500'd the whole draft board (Starlette's `JSONResponse.render` uses
    `allow_nan=False`). Whether an unfillable slot should count as a hole
    is a product question this arithmetic must not decide by accident."""
    rosters = {"u1": set()}
    needs = build_draft_needs(rosters, {}, {}, ["QB", "FLEX", "BN"], {}, {})
    u1 = needs[0]
    assert u1.starters_by_slot == {"QB": None, "FLEX": None}
    assert u1.holes == []
    assert len(u1.slots) == 2
    for s in u1.slots:
        assert s.margin is None
        assert s.is_hole is False
        assert s.vetoed is False


def test_margin_is_always_none_or_finite():
    """C1's own end-to-end guard, at the engine boundary: neither
    non-finite-margin root cause may reach `SlotStanding.margin`.

    `mystery_player` is position-unmapped, so he fills QB as a FALLBACK
    (`_solve_owner`'s unmapped-player path) -- QB's raw slot label is never
    counted into `demand` (only a `known`-source fill is), so it has no
    replacement line at all: the C1 case-2 path
    (`lines.get(label, float("-inf"))` -> `value - -inf` -> `+inf`, since
    QB is claimed before FLEX -- QB has the smaller `SLOT_ELIGIBILITY` set
    and is processed first). FLEX itself then comes up genuinely empty (no
    unmapped players left): the C1 case-1 path
    (`margin=float("-inf")` on the pre-fix code).

    Falsified: reverting either C1 fix (dropping the `math.isfinite(line)`
    guard, or restoring `margin=float("-inf")` on the empty branch) makes
    the `s.margin is None` assertions fail -- one of the two slots would
    come back `+inf` or `-inf` instead."""
    rosters = {"u1": {"mystery_player"}}
    positions: dict[str, str] = {}
    board = {"mystery_player": 5.0}
    needs = build_draft_needs(
        rosters, board, positions, ["QB", "FLEX", "BN"], {}, {}
    )
    u1 = needs[0]
    assert u1.starters_by_slot["QB"] == "mystery_player"
    assert u1.starters_by_slot["FLEX"] is None
    assert len(u1.slots) == 2
    for s in u1.slots:
        assert s.margin is None or math.isfinite(s.margin)
        assert s.margin is None, "no line / no occupant -- must not fabricate a number"
    assert u1.holes == []


def test_drafted_into_matches_the_picks_position_to_an_open_hole():
    """Mutation this catches: checking against starters_by_slot (who already
    started) rather than holes (what was open) -- a pick at a position with
    no hole must not count, and a pick at a position that WAS a hole must."""
    rosters = {"u1": {"qb_u1"}, "u2": {"qb_a", "qb_b"}, "u3": {"qb_u3"}}
    board = {"qb_u1": 100.0, "qb_a": 1.0, "qb_b": 2.0, "qb_u3": 3.0}
    positions = {"qb_u1": "QB", "qb_a": "QB", "qb_b": "QB", "qb_u3": "QB"}
    picks_by_owner = {"u1": [("new_rb", "RB"), ("new_qb", "QB")]}
    needs = build_draft_needs(
        rosters, board, positions, ["QB", "BN"], picks_by_owner, {}
    )
    u1 = _by_owner(needs, "u1")
    assert u1.holes == ["QB"]
    assert u1.drafted_into == ["QB"]
    assert u1.drafted_into_count == 1


def test_drafted_into_credit_is_capped_by_the_number_of_hole_instances():
    """Position-room-model fix (2026-08-18): a pick's position matching an
    open hole's LABEL used to credit unconditionally, so N picks at a
    position with exactly one hole slot all counted as 'drafted into' it --
    the waterboyboucher case from the spec (one -0.08 FLEX WR hole, four WR
    picks all credited), which reads as 'drafted four WRs, none of which
    ever helped' when the real gap is a single marginal slot.

    Two owners, one with a single RB hole (one starting RB slot, below the
    line) and two RB picks: the first pick credits and consumes the only
    hole slot; the second, identical-position pick has no capacity left
    and must NOT count."""
    rosters = {"u1": {"rb_bad"}, "u2": {"rb_good1", "rb_good2"}}
    points = {"rb_bad": 10.0, "rb_good1": 200.0, "rb_good2": 190.0}
    positions = {p: "RB" for p in points}
    picks_by_owner = {"u1": [("first_rb", "RB"), ("second_rb", "RB")]}
    needs = build_draft_needs(
        rosters, {}, positions, ["RB", "BN"], picks_by_owner, {}, points=points
    )
    u1 = _by_owner(needs, "u1")
    assert u1.holes == ["RB"]
    assert u1.drafted_into == ["RB"]
    assert u1.drafted_into_count == 1, (
        "only ONE RB starting slot was a hole -- only one pick can address it"
    )


def test_started_counts_only_the_credited_picks_with_a_recorded_start():
    """Started still gates on games_started > 0 -- verified under the
    capacity-capped model (two starting QB slots, both holes, so both of
    u1's two QB picks are legitimately credited; only one ever started)."""
    rosters = {
        "u1": {"qb_u1a", "qb_u1b"},
        "u2": {"qb_a", "qb_b", "qb_c", "qb_d"},
    }
    points = {
        "qb_u1a": 10.0, "qb_u1b": 9.0,
        "qb_a": 200.0, "qb_b": 190.0, "qb_c": 180.0, "qb_d": 170.0,
    }
    positions = {p: "QB" for p in points}
    picks_by_owner = {"u1": [("bench_qb", "QB"), ("started_qb", "QB")]}
    started_by_pick = {"bench_qb": 0, "started_qb": 5}
    needs = build_draft_needs(
        rosters, {}, positions, ["QB", "QB", "BN"], picks_by_owner,
        started_by_pick, points=points,
    )
    u1 = _by_owner(needs, "u1")
    assert u1.drafted_into_count == 2
    assert u1.started == 1


# --- Task 1 revision: points-based lines, severity, and the ECR veto -----


def test_the_line_is_drawn_on_points_not_ecr_when_points_are_present():
    """Mutation this catches: ranking the pool by ECR while `points` is
    supplied.

    qb1 is the league's ECR-WORST QB but its points-BEST -- the flip of an
    ECR-favorite/points-bust shape. That flip is deliberate: rule 3's veto
    exempts any player the market rates above its own ECR line, and a
    below-points, above-ECR player is *always* exactly that player -- the
    veto's final verdict for him is provably identical whether the line was
    drawn on points or on pure ECR (both reduce to "was he better than his
    own ECR line"), so that shape can never distinguish this mutation. The
    ECR-bad/points-good shape here can: a buggy ECR-only implementation
    would flag qb1 (ECR hates him), the correct one must not (points love
    him, and nothing vetoes a player for being *too good*). qb4 is pool
    depth (u3's bench) so the line isn't self-referentially defined by
    whichever player is being checked -- see
    `test_a_hole_carries_its_margin_in_points` for the same fixture shape
    without depth, which cannot report a nonzero margin at all.
    """
    rosters = {"u1": {"qb1"}, "u2": {"qb2"}, "u3": {"qb3", "qb4"}}
    board = {"qb1": 500.0, "qb2": 5.0, "qb3": 6.0, "qb4": 1.0}   # ECR hates qb1
    points = {"qb1": 300.0, "qb2": 150.0, "qb3": 140.0, "qb4": 10.0}  # points love qb1
    out = build_draft_needs(
        rosters, board, {p: "QB" for p in board}, ["QB", "BN"], {}, {},
        points=points,
    )
    holes = {n.user_id: n.holes for n in out}
    assert holes["u1"] == [], "qb1 is the points-best and must clear the line"


def test_points_are_not_inverted():
    """Mutation this catches: applying the ECR inversion to `points` too.

    Inverting a higher-is-better number starts the WORST player, and every
    other assertion here would still pass because the ordering is merely
    reversed, not broken.
    """
    rosters = {"u1": {"good", "bad"}}
    out = build_draft_needs(rosters, {}, {"good": "QB", "bad": "QB"},
                            ["QB", "BN"], {}, {},
                            points={"good": 300.0, "bad": 5.0})
    assert out[0].starters_by_slot["QB"] == "good"


def test_a_young_player_below_replacement_on_points_is_vetoed_by_ecr():
    """Mutation this catches: dropping the ECR veto.

    Without it a second-year breakout who barely played reads as a hole in a
    dynasty league, which is the false positive the veto exists to prevent.

    `filler` is pool depth (u3's bench) so `rookie` is unambiguously below
    the points line rather than tied with it -- with only 3 total QBs and 3
    starting slots the line would land on `rookie`'s own value (a starter
    can never be below the line his own inclusion helps define), which
    would make `holes["u1"] == []` true regardless of whether the veto
    exists at all. Falsified: dropping `filler` reproduces exactly that
    non-discriminating fixture.
    """
    rosters = {"u1": {"rookie"}, "u2": {"vet2"}, "u3": {"vet3", "filler"}}
    board = {"rookie": 5.0, "vet2": 90.0, "vet3": 95.0, "filler": 999.0}  # market loves the rookie
    points = {"rookie": 12.0, "vet2": 200.0, "vet3": 210.0, "filler": 50.0}
    out = {n.user_id: n.holes for n in build_draft_needs(
        rosters, board, {p: "QB" for p in board}, ["QB", "BN"], {}, {}, points=points)}
    assert out["u1"] == [], "ECR rates him above the line, so not a hole"


def test_every_owner_gets_a_softest_slot_even_with_no_holes():
    """Mutation this catches: only populating `slots` when holes exist --
    which would leave exactly the blank rows this revision is fixing. "The
    softest slot" is `min(slots, key=lambda s: s.margin)` (module docstring)
    -- there is no dedicated field for it any more, so this test derives it
    the same way a consumer would."""
    rosters = {f"u{i}": {f"qb{i}"} for i in range(1, 4)}
    out = build_draft_needs(rosters, {}, {f"qb{i}": "QB" for i in range(1, 4)},
                            ["QB", "BN"], {}, {},
                            points={f"qb{i}": 100.0 * i for i in range(1, 4)})
    for n in out:
        assert n.slots, "every owner has a starting slot, holes or not"
        softest = min(n.slots, key=lambda s: s.margin)
        assert softest.position == "QB"


def test_a_hole_carries_its_margin_in_points():
    """Mutation this catches: reporting the margin as a rank delta or as an
    absolute value -- a hole's margin must be NEGATIVE points below the line.

    `filler` is pool depth for the same reason as the veto test above: with
    exactly 3 QBs and 3 starting slots the line self-referentially equals
    qb1's own value (margin 0, not negative), which would make this
    assertion fail honestly rather than pass for the wrong reason -- it does
    NOT quietly launder a broken margin calculation into a false pass, so
    it's kept as the sharper regression signal for this fixture shape.
    """
    rosters = {"u1": {"qb1"}, "u2": {"qb2"}, "u3": {"qb3", "filler"}}
    points = {"qb1": 100.0, "qb2": 200.0, "qb3": 300.0, "filler": 150.0}
    out = {n.user_id: n for n in build_draft_needs(
        rosters, {}, {p: "QB" for p in points}, ["QB", "BN"], {}, {}, points=points)}
    qb_slot = next(s for s in out["u1"].slots if s.slot == "QB")
    assert qb_slot.margin < 0
    assert qb_slot.is_hole is True


# --- 2026-08-17 keyspace-fix revision --------------------------------------
#
# The defect this section guards: pre-fix, `holes`/`hole_margins` were keyed
# by bare POSITION LABEL ("RB") while `softest_slot`'s first element was a
# SLOT-INSTANCE key ("RB_2", from `_slot_keys`). The two keyspaces coincide
# only when a position has exactly one starting slot -- with two RB slots
# they can (and here, do) name two DIFFERENT slots: the real, un-rescued
# hole sits in one RB slot while the ECR-rescued (vetoed), MORE severe
# margin sits in the other, and the old two-field shape had no way to
# report both at once -- `softest_slot` would silently point at the vetoed
# slot while `holes`/`hole_margins` pointed at a different, less severe one,
# with nothing on the wire distinguishing "hole" from "vetoed". `slots` (one
# `SlotStanding` per starting-slot instance, each with its own `is_hole`/
# `vetoed`) is the fix: one keyspace, both verdicts independently readable.


def test_two_rb_slots_one_hole_one_vetoed_are_separately_identifiable():
    """Mutation this catches: collapsing `is_hole`/`vetoed` back onto a
    single position-keyed field (the pre-fix `holes`/`hole_margins` /
    `softest_slot` shape) instead of reporting them per SLOT INSTANCE. Two
    starting RB slots for u1: `rb_hole` (below the points line, ECR does
    NOT rescue it -- a real hole) and `rb_vetoed` (below the points line by
    MORE, but ECR rates it above its own line -- rescued). This is the
    concrete shape from the review: the real hole is the LESS severe
    margin, the vetoed slot is the MORE severe one, so a softest-margin-only
    read (the old `softest_slot`) would surface the vetoed slot while
    `holes` names the other one -- exactly the divergence the fix closes.

    `super1`/`super2` (u3, both start, ECR-good, points-great) and
    `depth1`/`depth2` (u3, bench-only, points-good) are pool depth: with
    demand["RB"] = 4 (u1's 2 known starters + u3's 2), the points line is
    depth2's own value (180) -- neither self-referential to u1's players nor
    to u3's starters -- and the parallel ECR line (drawn on the SAME `demand`
    tally, via `_ecr_value`) lands on depth1's inverted rank, with rb_vetoed
    rated far better than that line and rb_hole rated far worse.

    Falsified: reverting to the pre-fix keyspace (`holes`/`hole_margins`
    keyed by "RB", `softest_slot` a bare `(key, margin)` pair with no
    `is_hole`/`vetoed` distinction) cannot express "slot RB is a hole AND
    slot RB_2 is vetoed AND they are different slots" at all -- this test's
    per-slot assertions have no equivalent to even write against that shape,
    which is the defect itself. Confirmed red/green by hand: swapping the
    `is_hole`/`vetoed` assignment in the `value < line` branch of
    `build_draft_needs` (rescue sets `is_hole=True` instead of `vetoed=True`,
    and vice versa) flips both `is_hole`/`vetoed` assertions below; restoring
    the swap makes the file byte-identical again.
    """
    rosters = {
        "u1": {"rb_hole", "rb_vetoed"},
        "u3": {"super1", "super2", "depth1", "depth2"},
    }
    positions = {p: "RB" for p in (
        "rb_hole", "rb_vetoed", "super1", "super2", "depth1", "depth2")}
    points = {
        "rb_hole": 60.0, "rb_vetoed": 50.0,
        "super1": 500.0, "super2": 490.0, "depth1": 200.0, "depth2": 180.0,
    }
    # ECR ranks (lower = better): rb_vetoed is the market's darling despite
    # weak points; rb_hole is the market's least favorite too, so nothing
    # rescues him.
    board = {
        "rb_vetoed": 1.0, "super1": 10.0, "super2": 11.0,
        "depth1": 12.0, "depth2": 13.0, "rb_hole": 999.0,
    }
    out = {n.user_id: n for n in build_draft_needs(
        rosters, board, positions, ["RB", "RB", "BN", "BN"], {}, {},
        points=points,
    )}
    u1 = out["u1"]

    # The keyspace: exactly one slot per starting instance, findable by its
    # OWN key -- not by the position label both slots share.
    assert {s.slot for s in u1.slots} == {"RB", "RB_2"}

    hole_slot = next(s for s in u1.slots if s.is_hole)
    vetoed_slot = next(s for s in u1.slots if s.vetoed)
    assert hole_slot.slot != vetoed_slot.slot, (
        "the hole and the vetoed slot are two different RB starting "
        "instances -- collapsing them onto one position-keyed field is "
        "exactly the pre-fix defect"
    )
    assert hole_slot.is_hole is True and hole_slot.vetoed is False
    assert vetoed_slot.is_hole is False and vetoed_slot.vetoed is True

    # The concrete review case: the vetoed slot's margin is MORE severe
    # (more negative) than the real hole's -- a softest-margin-only read
    # would misname the vetoed slot as "the" hole.
    assert vetoed_slot.margin < hole_slot.margin

    # `holes` (position labels, derived from `is_hole` only) names the real
    # hole's position and is silent about the vetoed one.
    assert u1.holes == ["RB"]


def test_omitting_points_preserves_the_existing_ecr_behaviour():
    """Mutations this catches: (1) making `points` required -- every
    pre-revision call site (this one included) omits it and would TypeError.
    (2) defaulting `points` to `{}` in a way that zeroes every player's
    value instead of falling back to ECR (e.g. `points.get(pid, 0.0)`
    unconditionally rather than checking `points is not None`).

    The original two-owner, one-player-each fixture couldn't catch (2): with
    demand == pool size == 2, a zeroing bug flattens both to a tied 0.0 and
    `holes["u1"] == []` still holds -- by coincidence, not because the ECR
    fallback ran. This fixture adds real depth so a genuine ECR-drawn hole
    exists to lose: u4's QB (rank 50) is a real starter, clearly below the
    ECR line -- u5's bench QB (rank 5, never a starter, pure pool depth)
    keeps the line from landing on u4's own value. Under (2), every pooled
    value collapses to 0.0, the line collapses to 0.0 too, and u4's hole
    vanishes."""
    rosters = {
        "u1": {"qb1"},
        "u2": {"qb2"},
        "u3": {"qb3"},
        "u4": {"qb4"},
        "u5": {"qb5", "qb5b"},
    }
    board = {
        "qb1": 1.0, "qb2": 2.0, "qb3": 3.0,
        "qb4": 50.0,  # bad enough to sit below the line -- the real hole
        "qb5": 4.0, "qb5b": 5.0,  # qb5b: bench-only depth, never starts
    }
    positions = {p: "QB" for p in board}
    out = {n.user_id: n.holes for n in build_draft_needs(
        rosters, board, positions, ["QB", "BN"], {}, {})}
    assert out["u1"] == [] and out["u5"] == []
    assert out["u4"] == ["QB"], "ECR fallback must still find this real hole"


# --- I2 fix (2026-08-17): rank-matched points for a no-points starter -----
#
# The defect: `_value`'s old fallback for a player with no `points` entry
# was raw `-ecr` -- always negative -- compared directly against a
# points-drawn replacement line -- never negative. That mixing meant a
# no-points starter was ALWAYS below the line regardless of how good he
# actually was, manufacturing exactly the false hole this module exists to
# avoid; and when the line itself landed on such a player, every OTHER
# player at that position inherited a margin inflated by the whole
# `-ecr`-vs-points gap (six-figure margins, measured live).


def test_a_genuine_no_points_starter_is_not_automatically_a_hole():
    """`rookie_qb` has no prior-season points (a rookie/offseason pickup)
    but the league's best ECR at the position. Rank-matched, his points-space
    value should land near the league's BEST points-having QB, clearing the
    line comfortably -- not the guaranteed-below-any-points-line raw `-ecr`
    fallback the pre-fix code used.

    `filler_qb` is bench-only pool depth (never starts, points 50.0) so the
    line isn't self-referentially defined by the three actual starters'
    own values -- same discipline as the veto/margin tests above.

    Rank-match, worked by hand: ECR-ranked QB pool (ascending, best first):
    rookie_qb(1), vet_qb2(5), vet_qb3(6), filler_qb(50) -> rookie_qb is
    rank 0. Points-having QB pool (descending): vet_qb2(200), vet_qb3(190),
    filler_qb(50) -> rank 0 is vet_qb2's 200.0, so rookie_qb's rank-matched
    value is 200.0. `all_by_position["QB"]` = [200(rookie, matched), 200
    (vet_qb2), 190(vet_qb3), 50(filler)]; demand=3 (u1/u2/u3 each start
    exactly one) -> the 3rd-best = 190.0. rookie_qb's margin = 200 - 190 =
    +10 -- positive, not a hole, no veto needed.

    Falsified: reverting the rank-match fix (fallback straight to `-ecr` =
    -1.0 for rookie_qb) changes both the pool value AND the line (line
    becomes 50.0, rookie_qb's margin becomes -1 - 50 = -51 -- STILL not
    flagged as a hole, because the ECR veto rescues him too, so `holes`
    alone can't tell the fix apart from the bug). The exact `margin == 10.0`
    and `vetoed is False` assertions below can: the pre-fix numbers are
    `margin == -51.0` and `vetoed is True`.
    """
    rosters = {
        "u1": {"rookie_qb"},
        "u2": {"vet_qb2"},
        "u3": {"vet_qb3", "filler_qb"},
    }
    board = {
        "rookie_qb": 1.0, "vet_qb2": 5.0, "vet_qb3": 6.0, "filler_qb": 50.0,
    }
    points = {"vet_qb2": 200.0, "vet_qb3": 190.0, "filler_qb": 50.0}
    positions = {p: "QB" for p in board}
    needs = build_draft_needs(
        rosters, board, positions, ["QB", "BN"], {}, {}, points=points
    )
    u1 = _by_owner(needs, "u1")
    assert u1.holes == []
    qb_slot = next(s for s in u1.slots if s.slot == "QB")
    assert qb_slot.margin == 10.0
    assert qb_slot.is_hole is False
    assert qb_slot.vetoed is False


def test_a_line_landing_on_a_rank_matched_player_is_a_sane_margin():
    """The sharper I2 case: the replacement line itself lands ON a
    rank-matched (no-points) player's value, not merely above/below it --
    this is the shape that produced a measured six-figure margin pre-fix.

    `rookie_qb` (no points, best ECR) rank-matches to `vet_a`'s points
    (300.0, the only points-haver, so rank-matched idx 0 -> 300.0). u2 owns
    `vet_a` (starts, 300.0 points) plus bench-only depth `filler_a` (points
    50.0, never starts -- real pool depth so the line isn't
    self-referential to just {rookie_qb, vet_a}). `all_by_position["QB"]`
    = [300(rookie, matched), 300(vet_a), 50(filler_a)]; demand=2 (u1 and
    u2's own single starters) -> the 2nd-best of the sorted-descending pool
    is 300.0 -- the line lands exactly on the tied group containing
    rookie_qb's own rank-matched value. margin = 300 - 300 = 0.0: sane,
    single-digit, nowhere near the `UNRANKED_ECR_SENTINEL` (1e6) scale.

    Falsified: reverting the rank-match fix gives rookie_qb the raw `-ecr`
    fallback (-1.0). The pool becomes [300(vet_a), 50(filler_a), -1(rookie)]
    -> line = 50.0 (2nd-best) -> margin = -1 - 50 = -51.0, and the ECR veto
    rescues him (`vetoed=True`) rather than the fix's honest `margin=0.0`,
    `vetoed=False`.
    """
    rosters = {
        "u1": {"rookie_qb"},
        "u2": {"vet_a", "filler_a"},
    }
    board = {"rookie_qb": 1.0, "vet_a": 2.0, "filler_a": 20.0}
    points = {"vet_a": 300.0, "filler_a": 50.0}
    positions = {p: "QB" for p in board}
    needs = build_draft_needs(
        rosters, board, positions, ["QB", "BN"], {}, {}, points=points
    )
    u1 = _by_owner(needs, "u1")
    qb_slot = next(s for s in u1.slots if s.slot == "QB")
    assert qb_slot.margin == 0.0
    assert qb_slot.is_hole is False
    assert qb_slot.vetoed is False
    # The explicit "no six-figure numbers" guard from the brief.
    assert abs(qb_slot.margin) < 1000.0


# --- 2026-08-18 fix: the last six-figure-margin path -----------------------
#
# The defect: a rostered starter with a KNOWN position but NEITHER
# prior-season points NOR an ECR rank at all is never a candidate for the
# I2 rank-match above (that requires a `board` entry, which he doesn't have
# either) -- pre-fix he fell straight through `_value` to the raw
# `-UNRANKED_ECR_SENTINEL` (ECR scale, ~-1e6), compared directly against a
# points-drawn line. Measured live: `margin=-1,000,050.0`. Not a regression
# -- identical before the I2 rank-match work -- but the one case rank-
# matching structurally cannot reach, and user-visible garbage on a thin
# roster.


def test_a_pure_sentinel_starter_gets_a_points_scale_floor_not_a_six_figure_margin():
    """`mystery_qb` has NO board (ECR) entry and NO points entry at all --
    the one gap `_rank_matched_points`'s rank-match can't reach (it keys off
    a `board` entry). He is u1's ONLY QB, so he starts regardless of value
    (single-candidate slot) and gets his own `SlotStanding` to inspect.

    `ghost_qb` (u4) is the same "no board, no points" shape, deliberately
    placed in DIRECT COMPETITION with `weak_real_qb` -- a real player who is
    the WORST real points-haver in the entire league (10.0, below even the
    bench-depth fillers) -- for u4's single QB slot. If the sentinel-floor
    fix let a pure-unknown outrank a real player, `ghost_qb` would win here;
    with the fix, the floor (`min(real points at QB) - 1.0` = `10.0 - 1.0` =
    `9.0`) sits just BELOW even the worst real player, so `weak_real_qb`
    still wins -- "he does not outrank a real player" made concrete, not
    just asserted.

    `vet_qb` (u2, 200.0 points) and `filler_qb1`/`filler_qb2` (u3, 150.0/
    50.0 -- filler_qb1 starts, filler_qb2 is bench-only pool depth) round
    out the position so the replacement line isn't self-referential to
    {mystery_qb} alone. Worked by hand: `all_by_position["QB"]` = mystery_qb
    (floor 9.0), ghost_qb (floor 9.0), vet_qb (200.0), filler_qb1 (150.0),
    filler_qb2 (50.0), weak_real_qb (10.0) -- six values, sorted descending:
    [200, 150, 50, 10, 9, 9]. `demand["QB"]` = 4 (u1/u2/u3/u4 each start
    exactly one QB) -> line = 4th-best = 10.0 (weak_real_qb's own value).
    mystery_qb's margin = 9.0 - 10.0 = -1.0: sane, single-digit, nowhere
    near the `UNRANKED_ECR_SENTINEL` (1e6) scale, and still a hole (the ECR
    veto can't rescue him -- his ECR value is the sentinel too, always far
    below the position's ECR line).

    Falsified: reverting the floor fix (dropping the new loop in
    `_rank_matched_points`) sends mystery_qb/ghost_qb back to `_value`'s raw
    `-UNRANKED_ECR_SENTINEL` fallback (~-1,000,000.0). The pool becomes
    [200, 150, 50, 10, -1e6, -1e6] -> line stays 10.0 (still 4th-best, a
    real player) -> mystery_qb's margin becomes roughly `-1,000,000 - 10` =
    `-1,000,010.0` -- the measured six-figure signature this fix closes.
    `ghost_qb` still loses to `weak_real_qb` either way (an even MORE
    negative sentinel loses too), so that assertion alone doesn't
    discriminate the fix -- the margin-scale assertions below are what do.
    """
    rosters = {
        "u1": {"mystery_qb"},
        "u2": {"vet_qb"},
        "u3": {"filler_qb1", "filler_qb2"},
        "u4": {"ghost_qb", "weak_real_qb"},
    }
    positions = {p: "QB" for p in (
        "mystery_qb", "vet_qb", "filler_qb1", "filler_qb2",
        "ghost_qb", "weak_real_qb",
    )}
    # mystery_qb and ghost_qb appear in NEITHER board nor points -- the gap.
    board = {
        "vet_qb": 5.0, "filler_qb1": 10.0, "filler_qb2": 20.0,
        "weak_real_qb": 90.0,
    }
    points = {
        "vet_qb": 200.0, "filler_qb1": 150.0, "filler_qb2": 50.0,
        "weak_real_qb": 10.0,  # the league's worst real points-haver at QB
    }
    needs = build_draft_needs(
        rosters, board, positions, ["QB", "BN"], {}, {}, points=points
    )
    u1 = _by_owner(needs, "u1")
    u4 = _by_owner(needs, "u4")

    # He does not outrank a real player -- even the worst one in the league.
    assert u4.starters_by_slot["QB"] == "weak_real_qb"

    # His own margin is sane, not a six-figure sentinel artifact.
    qb_slot = next(s for s in u1.slots if s.slot == "QB")
    assert u1.starters_by_slot["QB"] == "mystery_qb"
    assert qb_slot.margin == -1.0
    assert abs(qb_slot.margin) < 1000.0, "no six-figure margins"
    assert qb_slot.is_hole is True
    assert qb_slot.vetoed is False, "the ECR veto can't rescue him -- his ECR value is the sentinel too"


# --- Pre-existing surfaces, unaffected by the revision --------------------


def test_a_position_unmapped_player_fills_his_slot_instead_of_emptying_it():
    """Mutation this catches: dropping a position-unmapped rostered player
    entirely (matching outlook.py's OLD "unmapped -> excluded" pattern for
    VALUE) instead of the fallback fill. u1's only player has no entry in
    `positions` at all -- he must still end up in the one starter slot
    rather than leaving it (and the resulting phantom hole) behind."""
    rosters = {"u1": {"mystery_player"}}
    board = {"mystery_player": 5.0}
    positions: dict[str, str] = {}
    needs = build_draft_needs(
        rosters, board, positions, ["QB", "BN"], {}, {}
    )
    assert needs[0].starters_by_slot["QB"] == "mystery_player"


# --- Biggest Needs redesign (2026-08-19): production summed from credited
# picks, replacing the panel's old "Started" figure. Reuses the SAME
# capacity-capped loop that already computes drafted_into/started -- no new
# pass, no new verdict logic.


def test_production_sums_only_the_credited_picks():
    """production_by_pick is summed only for picks that actually earn
    capacity-capped credit -- the same picks drafted_into counts, not every
    pick the owner made. Reuses the exact fixture shape from
    test_drafted_into_credit_is_capped_by_the_number_of_hole_instances: one
    real RB hole (u1, capacity 1), two RB picks -- only the first is
    credited, so only its production counts even though the second pick's
    production_by_pick entry is larger."""
    rosters = {"u1": {"rb_bad"}, "u2": {"rb_good1", "rb_good2"}}
    points = {"rb_bad": 10.0, "rb_good1": 200.0, "rb_good2": 190.0}
    positions = {p: "RB" for p in points}
    picks_by_owner = {"u1": [("first_rb", "RB"), ("second_rb", "RB")]}
    production_by_pick = {"first_rb": 14.2, "second_rb": 99.0}
    needs = build_draft_needs(
        rosters, {}, positions, ["RB", "BN"], picks_by_owner, {},
        points=points, production_by_pick=production_by_pick,
    )
    u1 = _by_owner(needs, "u1")
    assert u1.holes == ["RB"]
    assert u1.drafted_into_count == 1, "only the first RB pick has capacity to credit against"
    assert u1.production == 14.2, "second_rb's 99.0 must not count -- it was never credited"


def test_production_defaults_to_zero_when_the_param_is_omitted():
    """Every pre-existing call site in this file omits production_by_pick --
    it must default cleanly to 0.0 for every owner, not raise."""
    rosters = {f"u{i}": {f"qb{i}"} for i in range(1, 4)}
    needs = build_draft_needs(
        rosters, {}, {f"qb{i}": "QB" for i in range(1, 4)},
        ["QB", "BN"], {}, {},
        points={f"qb{i}": 100.0 * i for i in range(1, 4)},
    )
    assert all(n.production == 0.0 for n in needs)


def test_production_is_zero_for_a_credited_pick_missing_from_the_map():
    """A credited pick absent from production_by_pick (produced nothing, or
    the map is incomplete) contributes 0.0, not a KeyError -- same
    discipline as started_by_pick.get(pid, 0)."""
    rosters = {"u1": {"qb_u1"}, "u2": {"qb_a", "qb_b"}, "u3": {"qb_u3"}}
    board = {"qb_u1": 100.0, "qb_a": 1.0, "qb_b": 2.0, "qb_u3": 3.0}
    positions = {"qb_u1": "QB", "qb_a": "QB", "qb_b": "QB", "qb_u3": "QB"}
    picks_by_owner = {"u1": [("new_qb", "QB")]}
    needs = build_draft_needs(
        rosters, board, positions, ["QB", "BN"], picks_by_owner, {},
        production_by_pick={},
    )
    u1 = _by_owner(needs, "u1")
    assert u1.drafted_into_count == 1
    assert u1.production == 0.0
