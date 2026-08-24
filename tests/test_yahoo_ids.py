from sleeper_dynasty.api.yahoo_ids import build_yahoo_to_sleeper


def test_maps_yahoo_id_to_sleeper_id():
    rows = [{"yahoo_id": "31002", "sleeper_id": "4034", "name": "Alvin Kamara"}]
    assert build_yahoo_to_sleeper(rows) == {"31002": "4034"}


def test_rows_missing_either_id_are_skipped():
    rows = [
        {"yahoo_id": "31002", "sleeper_id": "4034"},
        {"yahoo_id": "", "sleeper_id": "5000"},
        {"yahoo_id": "31003", "sleeper_id": ""},
        {"yahoo_id": "31004"},
        {"sleeper_id": "6000"},
    ]
    assert build_yahoo_to_sleeper(rows) == {"31002": "4034"}


def test_ids_are_normalized_to_strings_without_float_suffixes():
    """The CSV round-trips numeric columns through pandas, so an id can
    arrive as "31002.0". Left alone it would never match a Yahoo key."""
    rows = [{"yahoo_id": "31002.0", "sleeper_id": "4034.0"}]
    assert build_yahoo_to_sleeper(rows) == {"31002": "4034"}


def test_whitespace_is_stripped():
    rows = [{"yahoo_id": " 31002 ", "sleeper_id": " 4034 "}]
    assert build_yahoo_to_sleeper(rows) == {"31002": "4034"}


def test_first_row_wins_on_a_duplicate_yahoo_id():
    """Deterministic rather than last-write-wins, so two runs over the same
    CSV can never disagree."""
    rows = [
        {"yahoo_id": "31002", "sleeper_id": "4034"},
        {"yahoo_id": "31002", "sleeper_id": "9999"},
    ]
    assert build_yahoo_to_sleeper(rows) == {"31002": "4034"}


def test_r_style_null_tokens_are_not_treated_as_ids():
    """Observed live: the upstream CSV writes R's null as the text "NA", and
    one real row carries yahoo_id "NA". Taken literally it would become a
    catch-all key that silently resolves every unmapped Yahoo player to one
    wrong person."""
    rows = [
        {"yahoo_id": "NA", "sleeper_id": "13269"},
        {"yahoo_id": "na", "sleeper_id": "1"},
        {"yahoo_id": "NaN", "sleeper_id": "2"},
        {"yahoo_id": "31002", "sleeper_id": "NA"},
        {"yahoo_id": "31003", "sleeper_id": "4034"},
    ]
    assert build_yahoo_to_sleeper(rows) == {"31003": "4034"}


def test_empty_input_is_an_empty_map_not_an_error():
    assert build_yahoo_to_sleeper([]) == {}
