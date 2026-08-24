"""Tests for normalize_player_name."""

from sleeper_dynasty.util.name_match import normalize_player_name


def test_initials_with_periods_match_no_periods():
    # The headline case: "A.J. Brown" on FantasyPros vs "AJ Brown" on
    # Sleeper. Both must collapse to the same key.
    assert normalize_player_name("A.J. Brown") == "aj brown"
    assert normalize_player_name("AJ Brown") == "aj brown"
    assert normalize_player_name("aj brown") == "aj brown"


def test_lowercases_input():
    assert normalize_player_name("Patrick Mahomes") == "patrick mahomes"
    assert normalize_player_name("PATRICK MAHOMES") == "patrick mahomes"


def test_strips_jr_suffix():
    assert normalize_player_name("Marvin Harrison Jr.") == "marvin harrison"
    assert normalize_player_name("Marvin Harrison Jr") == "marvin harrison"
    assert normalize_player_name("Marvin Harrison") == "marvin harrison"


def test_strips_sr_suffix():
    assert normalize_player_name("Odell Beckham Sr.") == "odell beckham"


def test_strips_roman_numeral_suffixes():
    assert normalize_player_name("Patrick Mahomes II") == "patrick mahomes"
    assert normalize_player_name("Cedric Tillman III") == "cedric tillman"
    assert normalize_player_name("Henry Ford IV") == "henry ford"
    assert normalize_player_name("Some Player V") == "some player"


def test_preserves_hyphen_in_compound_name():
    # "Amon-Ra St. Brown" — hyphen stays, periods go.
    assert normalize_player_name("Amon-Ra St. Brown") == "amon-ra st brown"
    assert normalize_player_name("amon-ra st brown") == "amon-ra st brown"


def test_strips_apostrophe():
    # D'Andre Swift and DAndre Swift should match.
    assert normalize_player_name("D'Andre Swift") == "dandre swift"
    assert normalize_player_name("DAndre Swift") == "dandre swift"
    # Ja'Marr Chase too.
    assert normalize_player_name("Ja'Marr Chase") == "jamarr chase"


def test_strips_commas():
    # Edge case: some sources list "Last, First" — we don't reorder it,
    # but at minimum the comma goes away.
    assert normalize_player_name("Mahomes, Patrick") == "mahomes patrick"


def test_collapses_multiple_internal_spaces():
    assert normalize_player_name("Patrick  Mahomes") == "patrick mahomes"
    assert normalize_player_name("Patrick   Mahomes") == "patrick mahomes"
    assert normalize_player_name("Patrick\tMahomes") == "patrick mahomes"


def test_strips_leading_trailing_whitespace():
    assert normalize_player_name("  Patrick Mahomes  ") == "patrick mahomes"
    assert normalize_player_name("\nPatrick Mahomes\n") == "patrick mahomes"


def test_identity_on_simple_name():
    assert normalize_player_name("Tyreek Hill") == "tyreek hill"


def test_empty_input():
    assert normalize_player_name("") == ""
    assert normalize_player_name(None) == ""  # type: ignore[arg-type]


def test_single_word_name():
    # Defenses are sometimes a single token ("Texans", "Broncos").
    assert normalize_player_name("Texans") == "texans"


def test_team_defense_name():
    assert normalize_player_name("Houston Texans") == "houston texans"


def test_does_not_strip_single_letter_token_that_is_not_suffix():
    # Make sure a name like "John A" doesn't lose the "A". We strip
    # "v" but not arbitrary single letters — the suffix set is exact.
    # ("A" is not in the suffix set, but lowercase "a" is also not.)
    assert normalize_player_name("John A") == "john a"


def test_suffix_only_stripped_from_end():
    # "Jr" appearing mid-name would be weird, but ensure we don't strip
    # it from a non-final position. (Concocted, but defensive.)
    assert normalize_player_name("Jr Smith") == "jr smith"


def test_keys_match_across_sources():
    # End-to-end: spot check that the dict-key use case works.
    sleeper_name = "A.J. Brown"
    fp_name = "AJ Brown"
    ktc_name = "aj brown"
    assert (
        normalize_player_name(sleeper_name)
        == normalize_player_name(fp_name)
        == normalize_player_name(ktc_name)
    )
