from sleeper_dynasty.api.ktc import (
    build_pick_value_table, build_pick_value_table_tiered, parse_pick_name_tiered,
)
from sleeper_dynasty.models.player import KTCValue


def _pick(name, sf):
    return KTCValue(name=name, normalized_name=name.lower(), position="PICK",
                    superflex_value=sf, one_qb_value=sf)


def test_parse_pick_name_tiered():
    assert parse_pick_name_tiered("2027 Early 1st") == (2027, 1, "early")
    assert parse_pick_name_tiered("2027 Late 2nd") == (2027, 2, "late")
    assert parse_pick_name_tiered("2027 1st") == (2027, 1, "")
    assert parse_pick_name_tiered("Josh Allen") is None


def test_tiered_table_keeps_tiers_unaveraged():
    vals = {
        "a": _pick("2027 Early 1st", 9000),
        "b": _pick("2027 Late 1st", 4000),
    }
    t = build_pick_value_table_tiered(vals)
    assert t[(2027, 1, "early")].superflex_value == 9000
    assert t[(2027, 1, "late")].superflex_value == 4000
    # round-average table still averages them (unchanged behavior)
    r = build_pick_value_table(vals)
    assert r[(2027, 1)].superflex_value == 6500
