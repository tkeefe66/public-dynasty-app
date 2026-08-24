"""Tests for FantasyProsProjection and KTCValue (de)serialization."""

from sleeper_dynasty.models.player import FantasyProsProjection, KTCValue


def test_fantasypros_projection_roundtrip_full():
    proj = FantasyProsProjection(
        name="Jalen Hurts",
        normalized_name="jalen hurts",
        team="PHI",
        position="QB",
        stats={
            "pass_att": 498.5,
            "pass_yd": 3830.1,
            "pass_td": 28.6,
            "pass_int": 12.3,
            "rush_att": 120.7,
            "rush_yd": 594.8,
            "rush_td": 11.7,
            "fum_lost": 4.1,
        },
        projected_points_ppr=376.9,
        projected_points_high=410.0,
        projected_points_low=340.0,
    )
    d = proj.to_dict()
    # Sanity-check shape so a downstream consumer of the cache file
    # knows what to expect.
    assert d["name"] == "Jalen Hurts"
    assert d["team"] == "PHI"
    assert d["stats"]["pass_td"] == 28.6
    assert d["projected_points_ppr"] == 376.9

    back = FantasyProsProjection.from_dict(d)
    assert back == proj


def test_fantasypros_projection_roundtrip_no_high_low():
    proj = FantasyProsProjection(
        name="Travis Kelce",
        normalized_name="travis kelce",
        team="KC",
        position="TE",
        stats={"rec": 95.0, "rec_yd": 1100.0, "rec_td": 8.0, "fum_lost": 0.5},
        projected_points_ppr=240.5,
    )
    d = proj.to_dict()
    assert d["projected_points_high"] is None
    assert d["projected_points_low"] is None

    back = FantasyProsProjection.from_dict(d)
    assert back == proj


def test_fantasypros_from_dict_string_coercion():
    # JSON cache round-trips floats fine, but if cache content is hand
    # edited, numbers might come back as ints — make sure we coerce.
    d = {
        "name": "Patrick Mahomes",
        "normalized_name": "patrick mahomes",
        "team": "KC",
        "position": "QB",
        "stats": {"pass_yd": 4500},
        "projected_points_ppr": 350,  # int
        "projected_points_high": None,
        "projected_points_low": None,
    }
    back = FantasyProsProjection.from_dict(d)
    assert back.projected_points_ppr == 350.0


def test_ktc_value_roundtrip_full():
    v = KTCValue(
        name="Bijan Robinson",
        normalized_name="bijan robinson",
        position="RB",
        superflex_value=9989,
        one_qb_value=9994,
        superflex_position_rank=1,
        one_qb_position_rank=1,
    )
    d = v.to_dict()
    assert d["superflex_value"] == 9989
    assert d["one_qb_position_rank"] == 1

    back = KTCValue.from_dict(d)
    assert back == v


def test_ktc_value_roundtrip_partial():
    # A player who only shows up in one ranking set.
    v = KTCValue(
        name="Some Backup QB",
        normalized_name="some backup qb",
        position="QB",
        superflex_value=4500,
        one_qb_value=None,
        superflex_position_rank=25,
        one_qb_position_rank=None,
    )
    back = KTCValue.from_dict(v.to_dict())
    assert back == v
    assert back.one_qb_value is None
