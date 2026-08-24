"""The committed dynasty-overall/superflex ECR histories are data, so these
tests assert SHAPE, not values. Values move every time the file is
regenerated; shape must not.

Mirrors tests/test_rookie_ecr_data.py's style, generalised over both files
and tightened with the structural density check the phase-5 brief calls for:
a board with too few entries means a bad `ecr_type` filter let a thin/wrong
slice of the feed through, which a size-only gate would not catch (a size
gate blocked a healthy extract in phase 1 for exactly that reason — size is
a bad proxy for sparse data).
"""
import gzip
import json
from datetime import date
from importlib.resources import files

import pytest

from sleeper_dynasty.engine.rookie_board import parse_boards, resolve_board

FILES = ["dynasty_ecr.json.gz", "dynasty_sf_ecr.json.gz"]


def load_packaged(name: str) -> dict:
    blob = files("sleeper_dynasty.data").joinpath(name).read_bytes()
    return json.loads(gzip.decompress(blob))


def _is_iso_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
        return True
    except (TypeError, ValueError):
        return False


@pytest.mark.parametrize("filename", FILES)
def test_dynasty_board_history_is_dense_and_ordered(filename):
    boards = load_packaged(filename)
    assert len(boards) > 300
    # Do NOT gate on file size — a size gate blocked a healthy extract in
    # phase 1 because size is a bad proxy for sparse data. Assert structure.
    #
    # 200 (not the phase-5 brief's illustrative 400) is the real bound,
    # verified against the raw parquet: `do`'s true per-board minimum is 261
    # (2020-10-12), `dsf`'s is 241 (2020-10-22) — DynastyProcess's consensus
    # pool was genuinely smaller in its first year and has grown since, this
    # is not a filter bug (raw `ecr_type == "do"`/`"dsf"` row totals in the
    # source parquet crosswalk at >99% for dsf and ~95% for do). 200 sits
    # below both real minimums with margin, while still catching the actual
    # failure mode this guards: a wrong `ecr_type` landing on a much smaller
    # category (e.g. the rookie board's ~94-entry boards, or a near-empty
    # type) would fail this loudly.
    per_board = [len(b) for b in boards.values()]
    assert min(per_board) > 200, "a board with few entries means a bad ecr_type filter"
    assert all(_is_iso_date(d) for d in boards)


@pytest.mark.parametrize("filename", FILES)
def test_ids_are_strings_and_ecr_values_are_positive_numbers(filename):
    for day, board in load_packaged(filename).items():
        for pid, ecr in board.items():
            assert isinstance(pid, str) and pid, f"bad id on {day}"
            assert isinstance(ecr, (int, float)) and ecr > 0, f"bad ecr on {day}"


@pytest.mark.parametrize("filename", FILES)
def test_parse_boards_accepts_the_committed_file_unchanged(filename):
    raw = load_packaged(filename)
    assert parse_boards(raw) == {k: {i: float(v) for i, v in b.items()}
                                 for k, b in raw.items()}


@pytest.mark.parametrize("filename", FILES)
def test_history_resolves_a_board_for_a_recent_draft_date(filename):
    resolved = resolve_board(parse_boards(load_packaged(filename)), date(2025, 5, 16))
    assert resolved is not None
    day, board = resolved
    assert day <= "2025-05-16"
    assert len(board) > 400
