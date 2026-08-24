"""The adapted cache pair. No bump and no new persisted computation, so the
standard quartet's "grader stamps it" and "pre-feature default" collapse into
these two."""

from app.services.chain_cache import ChainCache
from tests.helpers import minimal_chain_cache_entry


def test_the_two_new_dynasty_outlook_keys_round_trip(tmp_path):
    entry = minimal_chain_cache_entry(dynasty_outlooks={"uA": {
        "age_profile": {
            "avg_age_by_position": {"RB": 26.5},
            "league_avg_age_by_position": {"RB": 25.9},
            "overall_avg_age": 26.0, "aging_risks": [], "core_young": []},
        "draft_capital": {"picks_by_season": {}, "picks_by_season_round": {},
                          "net_vs_average": 0.0, "status": "neutral"},
        "draft_needs": [{"position": "RB", "urgency": "developing",
                         "reason": "2/4 RB(s) on roster",
                         "held": 2, "ideal": 4, "kind": "depth"}],
    }})
    cache = ChainCache(cache_dir=tmp_path)
    cache.write(entry.league_id, entry)
    back = cache.read(entry.league_id)
    ol = back.dynasty_outlooks["uA"]
    assert ol["age_profile"]["league_avg_age_by_position"] == {"RB": 25.9}
    assert ol["draft_needs"][0]["held"] == 2
    assert ol["draft_needs"][0]["kind"] == "depth"


def test_schema_version_is_unchanged():
    """A bump would 409 every league until rebuild for no correctness gain."""
    from app.services.chain_cache import SCHEMA_VERSION
    assert SCHEMA_VERSION == 17
