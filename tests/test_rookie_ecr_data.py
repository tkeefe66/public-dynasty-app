"""The committed history is data, so the test asserts its SHAPE, not its values.

Values move every time the file is regenerated; shape must not.
"""
import gzip
import json
from datetime import date
from importlib.resources import files

from sleeper_dynasty.engine.rookie_board import parse_boards, resolve_board


def _load() -> dict:
    blob = files("sleeper_dynasty.data").joinpath("rookie_ecr.json.gz").read_bytes()
    return json.loads(gzip.decompress(blob))


def test_committed_history_is_readable_and_non_empty():
    boards = _load()
    assert len(boards) > 200, "history should carry several years of weekly boards"


def test_every_key_is_an_iso_date_and_every_board_is_non_empty():
    for day, board in _load().items():
        date.fromisoformat(day)  # raises if malformed
        assert board, f"{day} is an empty board"


def test_ids_are_strings_and_ecr_values_are_positive_numbers():
    for day, board in _load().items():
        for pid, ecr in board.items():
            assert isinstance(pid, str) and pid, f"bad id on {day}"
            assert isinstance(ecr, (int, float)) and ecr > 0, f"bad ecr on {day}"


def test_parse_boards_accepts_the_committed_file_unchanged():
    raw = _load()
    assert parse_boards(raw) == {k: {i: float(v) for i, v in b.items()}
                                 for k, b in raw.items()}


def test_history_resolves_a_board_for_a_recent_draft_date():
    resolved = resolve_board(parse_boards(_load()), date(2025, 5, 16))
    assert resolved is not None
    day, board = resolved
    assert day <= "2025-05-16"
    assert len(board) > 50
