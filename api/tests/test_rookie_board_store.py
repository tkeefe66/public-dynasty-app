from datetime import date

import pytest

from app.services.rookie_board_store import EcrBoardStore, RookieBoardStore


@pytest.fixture
def store(tmp_path):
    return RookieBoardStore(tmp_path)


def test_committed_history_loads_from_the_package(store):
    assert len(store.committed()) > 200


def test_capture_daily_writes_once(store):
    assert store.capture_daily({"111": 1.0}, date(2026, 9, 1)) is True
    assert store.capture_daily({"111": 9.9}, date(2026, 9, 1)) is False
    assert store.all_boards()["2026-09-01"] == {"111": 1.0}


def test_capture_daily_refuses_an_empty_board(store):
    # An empty result means the fetch failed; capture is write-once, so storing
    # it would poison the baseline forever.
    assert store.capture_daily({}, date(2026, 9, 1)) is False
    assert "2026-09-01" not in store.all_boards()


def test_resolve_for_draft_uses_a_captured_board_on_the_draft_day(store):
    store.capture_daily({"111": 3.0}, date(2026, 9, 1))
    assert store.resolve_for_draft("d1", date(2026, 9, 1)) == {"111": 3.0}


def test_resolve_for_draft_never_uses_a_later_board(store):
    store.capture_daily({"111": 3.0}, date(2026, 9, 10))
    # Nothing captured on-or-before, and the committed history ends well before
    # 2026-09; a later board must not be handed back.
    assert store.resolve_for_draft("d1", date(2026, 9, 1)) != {"111": 3.0}


def test_resolve_for_draft_is_pinned_write_once(store):
    store.capture_daily({"111": 3.0}, date(2026, 9, 1))
    first = store.resolve_for_draft("d1", date(2026, 9, 5))
    store.capture_daily({"111": 99.0}, date(2026, 9, 3))
    assert store.resolve_for_draft("d1", date(2026, 9, 5)) == first


def test_resolve_for_draft_returns_none_before_all_history(store):
    assert store.resolve_for_draft("d1", date(2015, 5, 1)) is None


def test_committed_history_serves_a_real_past_draft(store):
    board = store.resolve_for_draft("d-2025", date(2025, 5, 16))
    assert board is not None and len(board) > 50


def test_resolve_for_draft_rejects_a_stale_board_and_writes_no_pin(store, tmp_path):
    # A draft dated far past the end of committed history has no board within
    # MAX_BOARD_AGE_DAYS on-or-before it. resolve_for_draft must return None
    # AND must not write a pin — a pin for a rejected board would freeze the
    # wrong-class corruption permanently, since re-running the extractor
    # cannot undo an existing pin.
    draft_id = "d-far-future"
    drafted_on = date(2099, 1, 1)
    assert store.resolve_for_draft(draft_id, drafted_on) is None
    pin_path = tmp_path / "rookie_ecr" / f"{draft_id}.json"
    assert not pin_path.exists()


def test_a_captured_board_wins_over_a_committed_board_of_the_same_date(store):
    # The committed history is a build-time snapshot; a capture is the fresher
    # observation of the same day. Reversing the merge in all_boards() would
    # make the store permanently ignore every capture for a date the shipped
    # history already covers — and no other test overlaps the two sources, so
    # nothing else here would catch it.
    committed = store.committed()
    assert committed, "committed history must be non-empty for this test to mean anything"
    day = max(committed)
    assert store.capture_daily({"sentinel": 1.0}, date.fromisoformat(day)) is True
    assert store.all_boards()[day] == {"sentinel": 1.0}


def test_two_board_types_do_not_share_a_pin_path(tmp_path):
    """resolve_for_draft pins WRITE-ONCE. If a rookie board and a
    dynasty-overall board for the same draft shared a path, the first writer
    would permanently poison the second — the same class of failure
    capture_daily's empty-refusal exists to prevent."""
    rookie = EcrBoardStore(tmp_path, subdir="rookie_ecr", packaged="rookie_ecr.json.gz")
    dyn = EcrBoardStore(tmp_path, subdir="dynasty_ecr", packaged="dynasty_ecr.json.gz")
    assert rookie._pin_path("draft1") != dyn._pin_path("draft1")


def test_rookie_board_store_alias_is_the_generic_store():
    assert RookieBoardStore is EcrBoardStore


def test_named_constructors_bind_subdir_packaged_and_max_age_together(tmp_path):
    """Each named constructor must bind its own (subdir, packaged filename,
    max_age_days) triple. The bug this guards: EcrBoardStore's bare
    constructor defaults to the rookie's 60-day bound, so a dynasty-overall
    store built without explicitly passing DYNASTY_OVERALL_MAX_BOARD_AGE_DAYS
    would silently inherit the wrong staleness bound. The fix is to make a
    mismatched combination unable to be expressed at a call site — so this
    test asserts on the three facts landing together, not merely on the
    values in isolation (a test that only checked dynasty_overall's
    max_age_days == 45 would stay green even if a future edit also renamed
    MAX_BOARD_AGE_DAYS's value to 45, or wired the wrong packaged file
    alongside the right number)."""
    from sleeper_dynasty.engine.rookie_board import (
        DYNASTY_OVERALL_MAX_BOARD_AGE_DAYS, MAX_BOARD_AGE_DAYS,
    )

    rookie = EcrBoardStore.rookie(tmp_path)
    do = EcrBoardStore.dynasty_overall(tmp_path)
    dsf = EcrBoardStore.dynasty_superflex(tmp_path)

    assert (rookie._dir.name, rookie._packaged, rookie._max_age_days) == (
        "rookie_ecr", "rookie_ecr.json.gz", MAX_BOARD_AGE_DAYS)
    assert (do._dir.name, do._packaged, do._max_age_days) == (
        "dynasty_ecr", "dynasty_ecr.json.gz", DYNASTY_OVERALL_MAX_BOARD_AGE_DAYS)
    assert (dsf._dir.name, dsf._packaged, dsf._max_age_days) == (
        "dynasty_sf_ecr", "dynasty_sf_ecr.json.gz", DYNASTY_OVERALL_MAX_BOARD_AGE_DAYS)

    # The regression this whole fix exists to prevent: a dynasty store must
    # NOT carry the rookie's age bound, even though it's the constructor's
    # positional/keyword default.
    assert do._max_age_days != MAX_BOARD_AGE_DAYS
    assert dsf._max_age_days != MAX_BOARD_AGE_DAYS

    # All three pin timelines stay isolated from one another.
    assert len({rookie._dir, do._dir, dsf._dir}) == 3


def test_dynasty_overall_named_constructor_resolves_a_real_recent_draft(tmp_path):
    # Exercises the constructor end-to-end against the committed data file
    # Task 3 shipped, not just its __init__ arguments.
    store = EcrBoardStore.dynasty_overall(tmp_path)
    board = store.resolve_for_draft("d-2025-do", date(2025, 5, 16))
    assert board is not None and len(board) > 400
