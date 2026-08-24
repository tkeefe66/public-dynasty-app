"""Quartet for the `bracket_watch` cache field (see the chain-cache-field skill):
round-trip, pre-feature default, surface fallback, plus the API shape.

The grader-stamps-it leg lives in test_grader_service.py, where the fake
client and phase wiring already exist.
"""
from app.models.league import BracketWatch, DashboardResp, StandingRow
from app.services.aggregations import _bracket_watch
from app.services.chain_cache import ChainCache, ChainCacheEntry

from tests.helpers import minimal_chain_cache_entry

WATCH = {
    "season": 2025,
    "entered": 6,
    "alive": ["u1", "u5"],
    "alive_count": 2,
    "eliminated": ["u6", "u4", "u3", "u2"],
    "top_seed_user_id": "u1",
    "top_seed": 1,
}


def _row(uid, playoff_pts):
    return StandingRow(
        rank=1, user_id=uid, owner={"user_id": uid, "owner_name": uid.upper()},
        net_ktc=0.0, production_total=0.0, production_regular=0.0,
        production_playoff=playoff_pts, production_toilet=0.0, trades=0,
        grade="B",
    )


ROWS = [_row("u1", 210.5), _row("u5", 284.6), _row("u9", 0.0)]


def _entry(**over):
    base = dict(
        league_id="L1",
        owners={u: {"owner_name": u.upper()} for u in
                ("u1", "u2", "u3", "u4", "u5", "u6", "u9")},
    )
    base.update(over)
    return minimal_chain_cache_entry(**base)


# --- 1. round-trip -------------------------------------------------------
def test_bracket_watch_round_trips_through_the_cache(tmp_path):
    cache = ChainCache(cache_dir=tmp_path)
    cache.write("L1", _entry(bracket_watch=WATCH))
    assert cache.read("L1").bracket_watch == WATCH


# --- 2. pre-feature default ---------------------------------------------
def test_entry_defaults_to_an_empty_bracket_watch():
    assert ChainCacheEntry.__dataclass_fields__["bracket_watch"].default_factory() == {}


def test_pre_feature_entry_reads_as_empty():
    assert _entry().bracket_watch == {}


# --- 3. surface fallback -------------------------------------------------
def test_pre_feature_entry_surfaces_no_watch():
    """An entry graded before the field existed must not 500 the dashboard."""
    assert _bracket_watch(_entry(), "post", ROWS) is None


def test_only_surfaced_during_the_postseason():
    for phase in ("regular", "draft", "offseason"):
        assert _bracket_watch(_entry(bracket_watch=WATCH), phase, ROWS) is None


def test_an_empty_alive_list_surfaces_nothing():
    """Rather than an 'Alive 0 of 6' lead, which reads as a bug."""
    empty = {**WATCH, "alive": [], "alive_count": 0}
    assert _bracket_watch(_entry(bracket_watch=empty), "post", ROWS) is None


# --- 4. API shape --------------------------------------------------------
def test_dashboard_resp_carries_bracket_watch():
    assert "bracket_watch" in DashboardResp.model_fields
    assert DashboardResp.model_fields["bracket_watch"].default is None


def test_surfaces_alive_owners_with_refs():
    watch = _bracket_watch(_entry(bracket_watch=WATCH), "post", ROWS)
    assert isinstance(watch, BracketWatch)
    assert watch.alive_count == 2
    assert watch.entered == 6
    assert [o.owner_name for o in watch.alive] == ["U1", "U5"]


def test_names_the_top_surviving_seed():
    watch = _bracket_watch(_entry(bracket_watch=WATCH), "post", ROWS)
    assert watch.top_seed == 1
    assert watch.top_seed_owner.owner_name == "U1"


def test_playoff_points_leader_comes_from_the_standings_on_the_same_page():
    """Read from the rows this response already built, so the lead can never
    disagree with the table underneath it."""
    watch = _bracket_watch(_entry(bracket_watch=WATCH), "post", ROWS)
    assert watch.playoff_points_leader.owner_name == "U5"
    assert watch.playoff_points == 284.6


def test_no_playoff_points_yet_leaves_the_leader_unnamed():
    """Before the first playoff game nobody has any — naming a leader off a
    field of zeros would be arbitrary."""
    zeros = [_row("u1", 0.0), _row("u5", 0.0)]
    watch = _bracket_watch(_entry(bracket_watch=WATCH), "post", zeros)
    assert watch.playoff_points_leader is None
    assert watch.playoff_points is None


def test_missing_seed_leaves_the_seed_cell_unnamed():
    unseeded = {**WATCH, "top_seed_user_id": None, "top_seed": None}
    watch = _bracket_watch(_entry(bracket_watch=unseeded), "post", ROWS)
    assert watch.top_seed_owner is None
    assert watch.top_seed is None
