import pytest

from app.services.draft_board_view import build_draft_board


class _Entry:
    league_id = "lg"
    owners = {"u1": {"display_name": "Alice"}, "u2": {"display_name": "Bob"}}

    def __init__(self, picks, capabilities=None, draft_needs=None):
        self.drafted_picks = picks
        # Default matches every pre-existing test in this file: a bare
        # {"format": "redraft"} carries no roster_continuity/multiyear_history
        # keys at all, which is exactly what a pre-feature capabilities blob
        # looks like -- `.get(...)` on the missing keys is falsy either way.
        self.capabilities = (
            capabilities if capabilities is not None else {"format": "redraft"}
        )
        # NOTE: deliberately no `draft_needs` attribute unless passed --
        # `getattr(entry, "draft_needs", None)` in draft_board_view.py is
        # what a real pre-feature ChainCacheEntry predating this field looks
        # like from the outside.
        if draft_needs is not None:
            self.draft_needs = draft_needs


def _pick(pid, uid, pick_no, season=2026, **kw):
    row = {
        "player_id": pid, "full_name": pid.upper(), "position": "RB",
        "drafter_id": uid, "round": 1, "slot": pick_no,
        "picks_in_round": 2, "draft_season": season, "pick_no": pick_no,
        "is_keeper": False, "gradeable": True, "draft_kind": "full",
        "production_total": 0.0, "adp": None, "adp_delta": None,
        "projected_points": None,
    }
    row.update(kw)
    return row


def test_board_lists_picks_in_draft_order():
    entry = _Entry([_pick("p2", "u2", 2), _pick("p1", "u1", 1)])
    board = build_draft_board(entry, season=2026)
    assert [p.player_id for p in board.picks] == ["p1", "p2"]


def test_board_is_ungraded_before_any_production():
    entry = _Entry([_pick("p1", "u1", 1), _pick("p2", "u2", 2)])
    assert build_draft_board(entry, season=2026).graded is False


def test_board_is_graded_once_production_exists():
    entry = _Entry([
        _pick("p1", "u1", 1, production_total=100.0),
        _pick("p2", "u2", 2),
    ])
    assert build_draft_board(entry, season=2026).graded is True


def test_owner_rows_carry_adp_total_and_coverage():
    entry = _Entry([
        _pick("p1", "u1", 1, adp=12.0, adp_delta=-11.0),
        _pick("p2", "u1", 3, adp=None, adp_delta=None),
    ])
    board = build_draft_board(entry, season=2026)
    row = next(o for o in board.owners if o.user_id == "u1")
    assert row.adp_total_delta == pytest.approx(-11.0)
    assert row.graded_picks == 1
    assert row.total_picks == 2


def test_seasons_lists_every_available_class_newest_first():
    entry = _Entry([
        _pick("p1", "u1", 1, season=2025), _pick("p2", "u2", 2, season=2025),
        _pick("p3", "u1", 1, season=2026), _pick("p4", "u2", 2, season=2026),
    ])
    assert build_draft_board(entry, season=2026).seasons == [2026, 2025]


def test_unknown_season_returns_none():
    assert build_draft_board(_Entry([_pick("p1", "u1", 1)]), season=1999) is None


def test_empty_picks_returns_none():
    assert build_draft_board(_Entry([]), season=2026) is None


def test_keeper_picks_appear_on_the_board_but_not_in_the_owner_grade():
    entry = _Entry([
        _pick("p1", "u1", 1, is_keeper=True, adp=1.0, adp_delta=0.0),
        _pick("p2", "u1", 2, adp=20.0, adp_delta=-18.0),
    ])
    board = build_draft_board(entry, season=2026)
    assert len(board.picks) == 2
    assert any(p.is_keeper for p in board.picks)
    row = next(o for o in board.owners if o.user_id == "u1")
    assert row.graded_picks == 1


# --- One definition of "this owner's draft" ---------------------------------

def test_keepers_are_shown_but_not_scored():
    """Before this the ADP grade skipped keepers while the production ranking
    summed them — the same response carried two different definitions of an
    owner's draft."""
    entry = _Entry([
        _pick("p1", "u1", 1, production_total=100.0, adp=5.0, adp_delta=-4.0),
        _pick("kept", "u1", 2, production_total=900.0, is_keeper=True,
              adp=1.0, adp_delta=1.0),
    ])
    board = build_draft_board(entry, season=2026)
    # The keeper still renders as a result...
    assert [p.player_id for p in board.picks] == ["p1", "kept"]
    # ...and is absent from every scored figure.
    row = next(o for o in board.owners if o.user_id == "u1")
    assert row.production_total == pytest.approx(100.0)
    assert row.total_picks == 1
    assert row.adp_total_delta == pytest.approx(-4.0)


def test_auction_picks_are_shown_but_not_scored():
    entry = _Entry([
        _pick("p1", "u1", 1, production_total=100.0),
        _pick("bid", "u1", 2, production_total=900.0, gradeable=False),
    ])
    board = build_draft_board(entry, season=2026)
    assert [p.player_id for p in board.picks] == ["p1", "bid"]
    row = next(o for o in board.owners if o.user_id == "u1")
    assert row.production_total == pytest.approx(100.0)
    assert row.total_picks == 1


def test_an_all_auction_board_has_results_but_no_owner_grades():
    """"Results only, no grade" taken literally: the picks render and every
    owner who drafted is listed, but no grade is fabricated from chronological
    pick order — the deltas come back null, not zero.

    Owners are listed rather than omitted because an absent row reads as "this
    owner had no draft", which is false. A null figure reads as "no grade",
    which is true.
    """
    entry = _Entry([
        _pick("p1", "u1", 1, production_total=100.0, gradeable=False),
        _pick("p2", "u2", 2, production_total=50.0, gradeable=False),
    ])
    board = build_draft_board(entry, season=2026)
    assert len(board.picks) == 2
    assert {o.user_id for o in board.owners} == {"u1", "u2"}
    assert all(o.adp_total_delta is None and o.graded_picks == 0
               for o in board.owners)
    # Auction points are not this draft's doing, so the class is not "graded".
    assert board.graded is False


def test_rows_without_a_gradeable_key_still_score():
    """Pre-feature rows predate auction support and were all snake/linear."""
    row = _pick("p1", "u1", 1, production_total=100.0)
    del row["gradeable"]
    board = build_draft_board(_Entry([row]), season=2026)
    assert next(o for o in board.owners if o.user_id == "u1").total_picks == 1


# --- follow-ups: every owner is listed; graded reflects scorable picks -------

def test_owner_with_only_keepers_still_appears_in_the_ranking():
    """Vanishing from the board is not the same as having nothing to show. An
    owner who only kept players still drafted in this class and must be listed
    — with a null ADP grade, which is the absent-not-zero convention, not a
    0.0 that would read as a league-average draft."""
    entry = _Entry([
        _pick("p1", "u1", 1, is_keeper=True),
        _pick("p2", "u2", 2, adp=20.0, adp_delta=-18.0),
    ])
    board = build_draft_board(entry, season=2026)
    assert {o.user_id for o in board.owners} == {"u1", "u2"}
    kept = next(o for o in board.owners if o.user_id == "u1")
    assert kept.adp_total_delta is None
    assert kept.graded_picks == 0


def test_owner_with_only_auction_picks_still_appears():
    entry = _Entry([
        _pick("p1", "u1", 1, gradeable=False),
        _pick("p2", "u2", 2, adp=20.0, adp_delta=-18.0),
    ])
    board = build_draft_board(entry, season=2026)
    assert {o.user_id for o in board.owners} == {"u1", "u2"}


def test_graded_ignores_production_from_unscorable_picks():
    """A keeper's points are real but are not this draft's doing. If they set
    `graded`, an all-keeper class would claim to be graded while the owners
    section had nothing to rank."""
    entry = _Entry([
        _pick("p1", "u1", 1, is_keeper=True, production_total=300.0),
        _pick("p2", "u2", 2, gradeable=False, production_total=250.0),
    ])
    assert build_draft_board(entry, season=2026).graded is False


# ---------------------------------------------------------------------------
# Phase 5 Task 6 — "Going in" needs (chain-cache-field quartet, part 4/4:
# view-side fallback on a pre-feature entry; the other three live in
# test_chain_cache.py and test_grader_service.py) plus the two format gates.
# ---------------------------------------------------------------------------

_NEEDS_ROW = {
    "user_id": "u1", "holes": ["QB", "TE"], "drafted_into": ["TE"],
    "started": 1, "drafted_into_count": 1,
}


def _full_caps(**overrides):
    caps = {
        "format": "dynasty", "future_picks": True,
        "roster_continuity": True, "multiyear_history": True,
    }
    caps.update(overrides)
    return caps


def test_needs_is_none_on_a_pre_feature_entry():
    """Quartet #4: an entry predating this feature (no `draft_needs`
    attribute at all -- exactly what a JSON blob written before the field
    existed decodes into) must serve `.needs` as None, not raise. Mutation
    this catches: `_needs_for_season` reading `entry.draft_needs` directly
    (no `getattr` default) would raise AttributeError instead of falling
    back, 500ing the whole board response for every league cached before
    this feature shipped."""
    entry = _Entry([_pick("p1", "u1", 1, season=2026)],
                    capabilities=_full_caps())
    assert not hasattr(entry, "draft_needs")
    board = build_draft_board(entry, season=2026)
    assert board is not None
    assert board.needs is None


def test_needs_is_served_when_present_and_capable():
    """The positive case the gate tests below are contrasted against: real
    draft_needs data, a fully-capable league, the requested season present
    -> served, mapped onto OwnerNeedsResp.

    Mutation this catches: keying the lookup by the wrong season (e.g.
    `str(season - 1)`, verified live during round 1) or reading the raw dict
    straight through instead of constructing `OwnerNeedsResp` both make
    `board.needs` come back `None` or plain dicts without `.user_id`."""
    entry = _Entry(
        [_pick("p1", "u1", 1, season=2026)],
        capabilities=_full_caps(),
        draft_needs={"2026": [_NEEDS_ROW]},
    )
    board = build_draft_board(entry, season=2026)
    assert board.needs is not None
    assert board.needs[0].user_id == "u1"
    assert board.needs[0].holes == ["QB", "TE"]
    assert board.needs[0].drafted_into_count == 1


_NEEDS_ROW_WITH_SLOTS = {
    "user_id": "u1", "holes": ["QB", "TE"], "drafted_into": ["TE"],
    "started": 1, "drafted_into_count": 1,
    "slots": [
        {"slot": "QB", "position": "QB", "margin": -12.5,
         "is_hole": True, "vetoed": False},
        {"slot": "TE", "position": "TE", "margin": -3.0,
         "is_hole": True, "vetoed": False},
        {"slot": "RB_2", "position": "RB", "margin": -20.0,
         "is_hole": False, "vetoed": True},
    ],
}


def test_needs_row_round_trips_slots():
    """2026-08-17 keyspace-fix revision: `slots` (one `SlotStanding` per
    starting-slot instance, replacing the old position-keyed `hole_margins`
    and the slot-instance-keyed `softest_slot`) is a field on `OwnerNeedsResp`
    -- a row that carries it must come back through `OwnerNeedsResp` exactly,
    not silently dropped.

    Mutation this catches: adding the field to `OwnerNeedsResp` but reading
    it off some OTHER shape at the `_needs_for_season` call site (or
    dropping it from the dict before construction) would still pass every
    OTHER test in this file -- they all use `_NEEDS_ROW`, the pre-revision
    shape with no such key, so only a row that actually carries non-default
    values can catch a value silently getting lost. The RB_2 entry in
    particular proves the keyspace fix: a `vetoed` slot sharing a position
    label ("RB") with a different, un-vetoed hole slot must round-trip as
    its own distinguishable entry, not collapse into one position-keyed
    value."""
    entry = _Entry(
        [_pick("p1", "u1", 1, season=2026)],
        capabilities=_full_caps(),
        draft_needs={"2026": [_NEEDS_ROW_WITH_SLOTS]},
    )
    board = build_draft_board(entry, season=2026)
    slots = board.needs[0].slots
    assert len(slots) == 3
    by_key = {s.slot: s for s in slots}
    assert by_key["QB"].margin == -12.5 and by_key["QB"].is_hole is True
    assert by_key["TE"].margin == -3.0 and by_key["TE"].is_hole is True
    assert by_key["RB_2"].vetoed is True and by_key["RB_2"].is_hole is False
    assert by_key["RB_2"].position == "RB"


def test_needs_row_without_slots_still_deserialises():
    """A pre-revision cached row (predating `slots`, and its now-deleted
    predecessors `hole_margins`/`softest_slot`) must still deserialise --
    per the no-SCHEMA_VERSION-bump contract (`draft_needs` is a value-layer
    field, always recomputed; see the chain-cache-field skill), a stale row
    simply lacks the field rather than being invalid. `_NEEDS_ROW` is
    exactly that pre-revision shape -- every other test in this file uses it
    unmodified, which is what makes this assertion worth pinning explicitly
    rather than leaving it as an accidental side effect of those tests
    merely not raising.

    Mutation this catches: declaring `slots` on `OwnerNeedsResp` WITHOUT a
    default (i.e. a required field) makes `OwnerNeedsResp(**_NEEDS_ROW)`
    raise a pydantic ValidationError instead of falling back --
    `_needs_for_season` isn't wrapped in a try/except, so that exception
    would propagate out of `build_draft_board` and 500 the whole board
    response for every league cached before this revision shipped."""
    assert "slots" not in _NEEDS_ROW
    entry = _Entry(
        [_pick("p1", "u1", 1, season=2026)],
        capabilities=_full_caps(),
        draft_needs={"2026": [_NEEDS_ROW]},
    )
    board = build_draft_board(entry, season=2026)
    assert board.needs[0].slots == []


def test_a_redraft_league_gets_no_needs_at_all():
    """Redraft leagues have no roster continuity to reconstruct a draft-day
    roster from -- `roster_continuity: False`. Data is deliberately present
    for the season (as if the grader's own gate had a bug and stamped it
    anyway) so this proves the VIEW itself refuses to serve it, not merely
    that nothing was ever computed. Mutation this catches: dropping the
    `roster_continuity`/`multiyear_history` check from `_needs_for_season`
    (or checking only one of the two) would leak this stale data through."""
    entry = _Entry(
        [_pick("p1", "u1", 1, season=2025)],
        capabilities=_full_caps(format="redraft", roster_continuity=False),
        draft_needs={"2025": [_NEEDS_ROW]},
    )
    assert build_draft_board(entry, season=2025).needs is None


def test_a_keeper_league_gets_no_needs_at_all():
    """Pre-merge fix I1 (BLOCKER): keeper leagues cannot be reconstructed at
    all, and `roster_continuity`/`multiyear_history` alone do not exclude
    them -- `_CONTINUOUS_FORMATS = {"dynasty", "keeper"}` means a keeper
    league reports `roster_continuity: True` same as dynasty, and a 2+season
    keeper chain reports `multiyear_history: True` too. Without a dedicated
    format check this test's `_full_caps(format="keeper")` would sail through
    both existing conditions.

    The reconstruction itself is why keeper must be excluded, not merely
    inconsistent with dynasty: keepers enter the new season THROUGH THE
    DRAFT (`is_keeper` on a pick), never via a transaction, so
    `roster_asof`'s transaction-only model has no signal for the annual
    release of every non-keeper and hands back the whole prior roster as
    "still there" -- every slot full, zero holes leaguewide, for every owner.
    That is the "confidently wrong, not absent" failure this exclusion
    prevents from ever reaching a keeper league's board.

    Data is deliberately present for the season (as if the grader's gate had
    a bug and stamped it anyway), matching the redraft/first-season tests
    above: this proves the VIEW's own re-check, not merely that nothing was
    ever computed. Mutation this catches: dropping the
    `capabilities.get("format") == "dynasty"` clause from
    `_needs_for_season` (leaving only the roster_continuity/multiyear_history
    checks, which a keeper league also satisfies) lets this stale data
    through and `board.needs` comes back non-None."""
    entry = _Entry(
        [_pick("p1", "u1", 1, season=2025)],
        capabilities=_full_caps(format="keeper"),
        draft_needs={"2025": [_NEEDS_ROW]},
    )
    assert build_draft_board(entry, season=2025).needs is None


def test_a_first_season_startup_dynasty_gets_no_needs():
    """roster_continuity is True but there is no prior roster — the same
    situation as redraft, and multiyear_history is what distinguishes it.
    Data is present for the season for the same reason as the redraft test
    above: this proves the view's gate, not an absence of computed data."""
    entry = _Entry(
        [_pick("p1", "u1", 1, season=2025)],
        capabilities=_full_caps(multiyear_history=False),
        draft_needs={"2025": [_NEEDS_ROW]},
    )
    assert build_draft_board(entry, season=2025).needs is None


def test_graded_is_true_once_a_scorable_pick_has_played():
    entry = _Entry([
        _pick("p1", "u1", 1, is_keeper=True, production_total=300.0),
        _pick("p2", "u2", 2, production_total=10.0),
    ])
    assert build_draft_board(entry, season=2026).graded is True


# ---------------------------------------------------------------------------
# C1 (CRITICAL, 2026-08-17): non-finite SlotStandingResp.margin 500s the
# whole draft board. A unit test that stops at the Pydantic model boundary
# (`.model_dump()`/`jsonable_encoder` alone) does NOT catch this -- both
# round-trip `float("-inf")`/`float("inf")` without complaint. The actual
# crash lives one layer further out, in the exact `JSONResponse` every
# FastAPI route in this app returns through: Starlette's
# `JSONResponse.render` calls `json.dumps(..., allow_nan=False)`, which
# raises `ValueError: Out of range float values are not JSON compliant`.
# This test drives the assembled `DraftBoardResp` through that real path.
# ---------------------------------------------------------------------------


def test_draft_board_resp_serialises_through_the_real_json_response_path():
    """The engine fix (`engine/draft_needs.py`) means `margin` should never
    be non-finite any more -- but this guard exists precisely so a FUTURE
    regression (a new call site, a reverted fix) fails HERE, in a fast unit
    test, rather than 500ing a live page. Uses `_NEEDS_ROW_WITH_SLOTS`
    (real, finite margins) for the "must not raise" half.

    The canary is the point: mutating one slot's margin to `float("-inf")`
    and re-serialising proves this test actually exercises the failure
    mode, rather than passing by accident because nothing in the fixture
    ever touches `margin` on the way through `jsonable_encoder`."""
    from fastapi.encoders import jsonable_encoder
    from starlette.responses import JSONResponse

    entry = _Entry(
        [_pick("p1", "u1", 1, season=2026)],
        capabilities=_full_caps(),
        draft_needs={"2026": [_NEEDS_ROW_WITH_SLOTS]},
    )
    board = build_draft_board(entry, season=2026)

    # Must not raise -- real, finite margins serialise cleanly.
    JSONResponse(content=jsonable_encoder(board))

    # Canary: a non-finite margin must still be rejected by this exact path.
    board.needs[0].slots[0].margin = float("-inf")
    with pytest.raises(ValueError):
        JSONResponse(content=jsonable_encoder(board))


def test_a_null_margin_round_trips_through_owner_needs_resp():
    """C1's actual wire shape post-fix: `engine/draft_needs.py` now emits
    `margin=None` for an empty slot or a slot with no replacement line
    (never a non-finite float). `SlotStandingResp.margin` must accept `None`
    -- a required `float` field here would raise a pydantic
    `ValidationError` the moment a fresh (post-fix) cache row reaches
    `_needs_for_season`, 500ing the whole board exactly the way the
    non-finite float used to.

    Falsified: reverting `SlotStandingResp.margin`'s type from `float |
    None` back to `float` makes this raise `pydantic_core.ValidationError`
    instead of constructing cleanly."""
    row = {
        "user_id": "u1", "holes": [], "drafted_into": [], "started": 0,
        "drafted_into_count": 0,
        "slots": [
            {"slot": "QB", "position": "QB", "margin": None,
             "is_hole": False, "vetoed": False},
        ],
    }
    entry = _Entry(
        [_pick("p1", "u1", 1, season=2026)],
        capabilities=_full_caps(),
        draft_needs={"2026": [row]},
    )
    board = build_draft_board(entry, season=2026)
    assert board.needs[0].slots[0].margin is None
