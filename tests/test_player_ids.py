from sleeper_dynasty.api.player_ids import (
    build_fantasypros_to_sleeper, build_id_map, clean_id,
)


def test_clean_id_strips_pandas_float_suffix():
    assert clean_id("31002.0") == "31002"


def test_clean_id_rejects_r_null_tokens():
    # R writes its null as the literal "NA"; unfiltered it becomes a catch-all
    # key that swallows every unmapped player into one wrong person.
    for token in ("NA", "na", "N/A", "", "  ", "nan", "None", "null"):
        assert clean_id(token) == ""


def test_build_id_map_skips_rows_missing_either_side():
    rows = [
        {"fantasypros_id": "1234", "sleeper_id": "4046"},
        {"fantasypros_id": "NA", "sleeper_id": "9999"},
        {"fantasypros_id": "5678", "sleeper_id": "NA"},
        {"fantasypros_id": "", "sleeper_id": ""},
    ]
    assert build_id_map(rows, source_col="fantasypros_id") == {"1234": "4046"}


def test_build_id_map_first_row_wins_on_duplicate():
    rows = [
        {"fantasypros_id": "1234", "sleeper_id": "aaa"},
        {"fantasypros_id": "1234", "sleeper_id": "bbb"},
    ]
    assert build_id_map(rows, source_col="fantasypros_id") == {"1234": "aaa"}


def test_build_fantasypros_to_sleeper_reads_the_right_column():
    rows = [{"fantasypros_id": "1234", "yahoo_id": "777", "sleeper_id": "4046"}]
    assert build_fantasypros_to_sleeper(rows) == {"1234": "4046"}
