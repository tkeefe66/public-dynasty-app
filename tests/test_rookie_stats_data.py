"""Shape, not values — values move on every regeneration, shape must not."""
import collections
import gzip
import json
from importlib.resources import files


def _load() -> dict:
    return json.loads(gzip.decompress(
        files("sleeper_dynasty.data").joinpath("rookie_stats.json.gz").read_bytes()))


def test_history_is_readable_and_non_trivial():
    assert len(_load()) > 200


def test_every_player_has_an_ecr_a_class_and_at_least_one_season():
    for sid, rec in _load().items():
        assert isinstance(sid, str) and sid
        assert isinstance(rec["ecr"], (int, float)) and rec["ecr"] > 0
        assert isinstance(rec["class"], int) and 2000 < rec["class"] < 2100
        assert rec["seasons"], f"{sid} has no seasons"


def test_seasons_are_numbered_from_one_and_contiguous():
    # `n` is seasons-since-draft and the cohort key depends on it. A gap would
    # silently compare a year-3 total against the year-2 bar.
    for sid, rec in _load().items():
        ns = [s["n"] for s in rec["seasons"]]
        assert ns == list(range(1, len(ns) + 1)), f"{sid} has non-contiguous seasons"


def test_component_stats_are_numeric_and_non_negative_where_they_must_be():
    # Yardage totals (passing/rushing/receiving) and interceptions can legitimately
    # go negative in nflverse's weekly data — a handful of stuffed carries or a
    # scramble behind the sticks nets a negative season total for a low-volume
    # player (37 such cells exist in the committed history). Counting stats (TDs,
    # receptions, 2pt conversions, fumbles lost) cannot, and never do.
    yardage_or_turnovers = {
        "passing_yards", "rushing_yards", "receiving_yards", "interceptions",
    }
    for rec in _load().values():
        for s in rec["seasons"]:
            for k, v in s.items():
                if k == "n":
                    continue
                assert isinstance(v, (int, float)), f"{k} is not numeric"
                assert v >= 0 or k in yardage_or_turnovers, f"{k} negative: {v}"


def test_no_points_are_committed():
    # Committing POINTS would bake one league's scoring into every league's
    # verdict. Only components ship; scoring happens per league at refresh.
    banned = {"fantasy_points", "fantasy_points_ppr", "points", "pts"}
    for rec in _load().values():
        for s in rec["seasons"]:
            assert not (banned & set(s)), "a points column reached the committed file"


def test_every_class_is_present_and_season_counts_decay_with_tenure():
    # The real signal that the extract worked. An older class must reach MORE
    # seasons than a younger one; if that ordering breaks, the per-season join
    # dropped years and the cohort keys are silently wrong. A byte count cannot
    # see this — which is why the size gate that flagged this file was a bad
    # proxy and this assertion replaces it.
    recs = _load().values()
    deepest = collections.defaultdict(int)
    for r in recs:
        deepest[r["class"]] = max(deepest[r["class"]], len(r["seasons"]))
    classes = sorted(deepest)
    assert len(classes) >= 4, "expected several rookie classes"
    for older, newer in zip(classes, classes[1:]):
        assert deepest[older] > deepest[newer], (
            f"class {older} should reach more seasons than {newer}")
