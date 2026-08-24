from datetime import date, timedelta

import pytest

from sleeper_dynasty.engine.rookie_board import (
    DYNASTY_OVERALL_MAX_BOARD_AGE_DAYS, MAX_BOARD_AGE_DAYS, board_delta,
    parse_boards, parse_latest_board, resolve_board,
)

BOARDS = {
    "2025-05-09": {"111": 1.0, "222": 2.5},
    "2025-05-16": {"111": 1.0, "222": 2.9, "333": 7.6},
    "2025-05-23": {"111": 1.0, "222": 4.0},
}


def test_parse_boards_coerces_ids_to_str_and_ecr_to_float():
    raw = {"2025-05-16": {111: "1.05", "222": 2}}
    assert parse_boards(raw) == {"2025-05-16": {"111": 1.05, "222": 2.0}}


def test_parse_boards_drops_unusable_entries():
    raw = {"2025-05-16": {"111": None, "222": "not-a-number", "333": 3.0}}
    assert parse_boards(raw) == {"2025-05-16": {"333": 3.0}}


def test_parse_boards_drops_a_date_with_nothing_usable():
    # An empty board is indistinguishable from a failed fetch downstream.
    raw = {"2025-05-16": {"111": None}, "2025-05-23": {"222": 1.0}}
    assert parse_boards(raw) == {"2025-05-23": {"222": 1.0}}


def test_resolve_board_prefers_the_drafts_own_day():
    day, board = resolve_board(BOARDS, date(2025, 5, 16))
    assert day == "2025-05-16"
    assert board["333"] == 7.6


def test_resolve_board_falls_back_to_the_nearest_earlier_day():
    day, _ = resolve_board(BOARDS, date(2025, 5, 15))
    assert day == "2025-05-09"


def test_resolve_board_never_returns_a_later_board():
    # Grading against a board published after the draft is hindsight, which is
    # the entire failure this resolver exists to prevent.
    assert resolve_board(BOARDS, date(2025, 5, 1)) is None


def test_resolve_board_returns_none_when_empty():
    assert resolve_board({}, date(2025, 5, 16)) is None


def test_board_delta_positive_means_taken_later_than_consensus():
    assert board_delta(pick_no=10, ecr=4.0) == 6.0


def test_board_delta_negative_means_a_reach():
    assert board_delta(pick_no=2, ecr=9.0) == -7.0


def test_board_delta_is_none_for_an_unranked_player():
    # Ungraded on this baseline is not the same as scoring zero.
    assert board_delta(pick_no=10, ecr=None) is None


CROSSWALK = {"fp1": "111", "fp2": "222", "fp3": "333"}


def test_parse_latest_board_filters_non_rookie_rows():
    rows = [
        {"ecr_type": "drk", "id": "fp1", "ecr": "1.0", "scrape_date": "2026-08-14"},
        {"ecr_type": "do", "id": "fp2", "ecr": "2.0", "scrape_date": "2026-08-14"},
    ]
    day, board = parse_latest_board(rows, CROSSWALK)
    assert day == "2026-08-14"
    assert board == {"111": 1.0}


def test_parse_latest_board_drops_unmapped_ids():
    rows = [
        {"ecr_type": "drk", "id": "fp1", "ecr": "1.0", "scrape_date": "2026-08-14"},
        {"ecr_type": "drk", "id": "fp-unknown", "ecr": "2.0", "scrape_date": "2026-08-14"},
    ]
    day, board = parse_latest_board(rows, CROSSWALK)
    assert day == "2026-08-14"
    assert board == {"111": 1.0}


def test_parse_latest_board_drops_unusable_ecr():
    rows = [
        {"ecr_type": "drk", "id": "fp1", "ecr": "not-a-number", "scrape_date": "2026-08-14"},
        {"ecr_type": "drk", "id": "fp2", "ecr": None, "scrape_date": "2026-08-14"},
        {"ecr_type": "drk", "id": "fp3", "ecr": "3.0", "scrape_date": "2026-08-14"},
    ]
    day, board = parse_latest_board(rows, CROSSWALK)
    assert day == "2026-08-14"
    assert board == {"333": 3.0}


def test_parse_latest_board_returns_none_when_nothing_usable():
    rows = [
        {"ecr_type": "do", "id": "fp1", "ecr": "1.0", "scrape_date": "2026-08-14"},
        {"ecr_type": "drk", "id": "fp-unknown", "ecr": "2.0", "scrape_date": "2026-08-14"},
    ]
    assert parse_latest_board(rows, CROSSWALK) is None
    assert parse_latest_board([], CROSSWALK) is None


STALE_BOARDS = {"2026-01-01": {"111": 1.0}}


def test_resolve_board_accepts_a_board_exactly_at_the_age_bound():
    drafted_on = date(2026, 1, 1) + timedelta(days=MAX_BOARD_AGE_DAYS)
    day, board = resolve_board(STALE_BOARDS, drafted_on)
    assert day == "2026-01-01"
    assert board == {"111": 1.0}


def test_resolve_board_rejects_a_board_one_day_past_the_age_bound():
    drafted_on = date(2026, 1, 1) + timedelta(days=MAX_BOARD_AGE_DAYS + 1)
    assert resolve_board(STALE_BOARDS, drafted_on) is None


def test_parse_latest_board_picks_the_newest_scrape_date():
    rows = [
        {"ecr_type": "drk", "id": "fp1", "ecr": "1.0", "scrape_date": "2026-08-07"},
        {"ecr_type": "drk", "id": "fp2", "ecr": "2.0", "scrape_date": "2026-08-14"},
        {"ecr_type": "drk", "id": "fp3", "ecr": "3.0", "scrape_date": "2026-08-14"},
    ]
    day, board = parse_latest_board(rows, CROSSWALK)
    assert day == "2026-08-14"
    assert board == {"222": 2.0, "333": 3.0}


def test_parse_latest_board_selects_by_ecr_type():
    rows = [
        {"ecr_type": "drk", "id": "fp1", "ecr": 1.0, "scrape_date": "2025-05-01"},
        {"ecr_type": "do",  "id": "fp1", "ecr": 40.0, "scrape_date": "2025-05-01"},
        {"ecr_type": "dsf", "id": "fp1", "ecr": 22.0, "scrape_date": "2025-05-01"},
    ]
    cw = {"fp1": "s1"}
    assert parse_latest_board(rows, cw, "do") == ("2025-05-01", {"s1": 40.0})
    assert parse_latest_board(rows, cw, "dsf") == ("2025-05-01", {"s1": 22.0})
    assert parse_latest_board(rows, cw, "drk") == ("2025-05-01", {"s1": 1.0})


def test_dynasty_overall_age_bound_is_narrower_than_the_rookie_one():
    # The rookie bound's slack exists mostly to avoid confusing a board with
    # the NEXT rookie class ~9 months out. Dynasty-overall has no "wrong
    # class" it could be mistaken for, so nothing justifies borrowing 60.
    assert DYNASTY_OVERALL_MAX_BOARD_AGE_DAYS < MAX_BOARD_AGE_DAYS
