"""The seam, not the whole refresh — `test_grader_service.py` runs ~30s a test."""
import gzip
import json
from importlib.resources import files

from sleeper_dynasty.engine.rookie_cohorts import build_cohorts, verdict


def _history():
    return json.loads(gzip.decompress(
        files("sleeper_dynasty.data").joinpath("rookie_stats.json.gz").read_bytes()))


PPR_6PT = {"pass_yd": 0.04, "pass_td": 6.0, "pass_int": -1.0, "rush_yd": 0.1,
           "rush_td": 6.0, "rec": 1.0, "rec_yd": 0.1, "rec_td": 6.0,
           "fum_lost": -1.0}


def test_the_committed_history_yields_usable_cohorts():
    cohorts = build_cohorts(_history(), PPR_6PT)
    assert len(cohorts) >= 10, "too few cells with coverage to grade a class"


def test_top_band_bars_exceed_bottom_band_bars_at_the_same_n():
    cohorts = build_cohorts(_history(), PPR_6PT)
    top, bottom = cohorts.get("0|1"), cohorts.get("7|1")
    assert top and bottom, "expected both a top and a bottom band at n=1"
    assert top[1] > bottom[1], "a 1.01-calibre cohort must outscore a deep one"


def test_league_scoring_moves_the_bars():
    # The whole reason components are committed instead of points.
    six = build_cohorts(_history(), PPR_6PT)
    four = build_cohorts(_history(), {**PPR_6PT, "pass_td": 4.0})
    assert six != four


def test_a_pick_that_beat_its_cohort_reads_hit():
    cohorts = build_cohorts(_history(), PPR_6PT)
    cell = cohorts.get("0|1")
    assert cell, "expected a top-band year-one cell"
    assert verdict(cell[2] + 1.0, 1.0, 1, cohorts) == "hit"
    assert verdict(cell[0] - 1.0, 1.0, 1, cohorts) == "bust"
