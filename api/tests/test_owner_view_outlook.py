import pytest

from app.models.common import OwnerRef
from app.models.leaderboard import GMRow, PillarBreakdown, SignalBreakdown
from app.services.chain_cache import ChainCacheEntry
from app.services.owner_view import build_owner_detail


def _entry(**over):
    base = dict(
        league_id="L", chain=[], resolved_trades=[], grades={},
        owners={"uA": {"owner_name": "Alice"}, "uB": {"owner_name": "Bob"}},
        playoff_weeks_by_league={}, roster_to_user_by_league={},
        league_name_by_id={}, league_season_by_id={}, cached_at="2026-01-01",
    )
    base.update(over)
    return ChainCacheEntry(**base)


# The blob the reshaped builder writes: no `window`, no `trajectory`, and the
# three new draft-need keys plus the league age baseline.
_OUTLOOK_NEW = {
    "age_profile": {"avg_age_by_position": {"RB": 23.0},
                    "league_avg_age_by_position": {"RB": 25.4},
                    "overall_avg_age": 24.0, "aging_risks": [],
                    "core_young": [{"player_id": "wr1", "full_name": "WR1",
                                    "position": "WR", "age": 22}]},
    "draft_capital": {"picks_by_season": {"2027": 5},
                      "picks_by_season_round": {"2027-1": 2},
                      "net_vs_average": 3.0, "status": "pick-rich"},
    "draft_needs": [{"position": "TE", "urgency": "developing",
                     "reason": "1/2 TE(s) on roster",
                     "held": 1, "ideal": 2, "kind": "depth"}],
}

# A blob written BEFORE this change: it still carries `window`/`trajectory`
# (no SCHEMA_VERSION bump) and carries none of the new keys.
_OUTLOOK_PRE_FEATURE = {
    "window": "Peaking", "trajectory": "young + pick-rich",
    "age_profile": {"avg_age_by_position": {"RB": 23.0},
                    "overall_avg_age": 24.0, "aging_risks": [],
                    "core_young": []},
    "draft_capital": {"picks_by_season": {"2027": 5},
                      "picks_by_season_round": {"2027-1": 2},
                      "net_vs_average": 3.0, "status": "pick-rich"},
    "draft_needs": [{"position": "TE", "urgency": "developing",
                     "reason": "thin at TE"}],
}

_SIGNALS = {"uA": {"roster_value": 900.0, "draft_capital": 1200.0,
                   "draft_skill": 0.4, "youth": -24.0},
            "uB": {"roster_value": 100.0, "draft_capital": 0.0,
                   "draft_skill": -0.2, "youth": -27.0}}


def _entry_with_outlook(**over):
    return _entry(dynasty_outlooks={"uA": _OUTLOOK_NEW},
                  roster_ranks={"uA": {"rank": 1, "of": 2}},
                  outlook_signals=_SIGNALS, **over)


def _entry_with_pre_feature_outlook(**over):
    return _entry(dynasty_outlooks={"uA": _OUTLOOK_PRE_FEATURE},
                  outlook_signals=_SIGNALS, **over)


def _pillar(z: float, ranks: dict[str, int] | None = None) -> PillarBreakdown:
    return PillarBreakdown(
        weight=0.5, z=z, contribution=0,
        signals={k: SignalBreakdown(raw=0.0, z=z, weight=1.0, contribution=0)
                 for k in (ranks or {"s": 1})},
        signal_ranks=ranks or {},
    )


def _gm_row(*, rating: int, results_z: float = 0.0, assets_z: float = 0.0,
            assets_ranks: dict[str, int] | None = None) -> GMRow:
    return GMRow(
        rank=1, user_id="uA",
        owner=OwnerRef(user_id="uA", owner_name="Alice"),
        rating=rating, letter="B", model="v2_dynasty",
        pillars={"results": _pillar(results_z),
                 "assets": _pillar(assets_z, assets_ranks)},
        trend=0, trades=0, net_ktc=0.0,
        production_regular=0.0, production_playoff=0.0,
    )


# ---- the reshaped OutlookView ----

def test_window_is_derived_from_the_rating_not_read_off_the_blob():
    """The stage is DERIVED from the rating, never read off the blob.

    `_OUTLOOK_NEW` carries no `window` key at all, so a builder that read one
    off the blob returns None here rather than the stage this rating maps to.
    That is the property this guards -- the same one the "read it off the
    blob" mutation kills on the pre-feature fixture below.

    It does NOT guard where the block sits in the function. `gm_row` is a
    PARAMETER of build_owner_detail, in scope from the first line, so moving
    the assembly above the Franchise Rating block is invisible to this test.
    The one real ordering constraint is `is_redraft`, hoisted ~80 lines above
    the assembly, which the block reads to gate redraft out; moving the block
    above THAT raises UnboundLocalError."""
    entry = _entry_with_outlook()
    gm_row = _gm_row(rating=1600)
    detail = build_owner_detail(entry, "uA", gm_row=gm_row, total_owners=12)
    assert detail.outlook.window == "Contending"


def test_a_pre_feature_blob_serves_the_tab_with_the_new_keys_absent():
    """No SCHEMA_VERSION bump, so a blob written before this change still
    carries `window`/`trajectory` and carries NEITHER new key. It must render,
    and its stale keys must reach nothing."""
    detail = build_owner_detail(_entry_with_pre_feature_outlook(), "uA",
                                gm_row=_gm_row(rating=1300), total_owners=12)
    assert detail.outlook is not None
    assert detail.outlook.window == "Retooling"        # derived, not "Peaking"
    assert detail.outlook.age_profile.league_avg_age_by_position == {}
    assert all(n.held == 0 and n.ideal == 0 and n.kind == ""
               for n in detail.outlook.draft_needs)


def test_an_unrated_owner_has_no_stage():
    """classify_window always returned a label; this deliberately does not."""
    detail = build_owner_detail(_entry_with_outlook(), "uA",
                                gm_row=None, total_owners=12)
    assert detail.outlook is not None
    assert detail.outlook.window is None
    assert detail.outlook.results_z is None
    assert detail.outlook.assets_z is None
    assert detail.outlook.tilt is None
    assert detail.outlook.assets_signal_ranks == {}


def test_the_z_receipt_and_the_tilt_carry_the_right_sign():
    gm_row = _gm_row(rating=1600, results_z=0.84, assets_z=1.12)
    detail = build_owner_detail(_entry_with_outlook(), "uA",
                                gm_row=gm_row, total_owners=12)
    assert detail.outlook.results_z == 0.84
    assert detail.outlook.assets_z == 1.12
    assert detail.outlook.tilt == pytest.approx(0.28)


def test_assets_signal_ranks_reach_the_outlook_block():
    gm_row = _gm_row(rating=1600,
                     assets_ranks={"roster_value_share": 2, "draft_capital": 1})
    detail = build_owner_detail(_entry_with_outlook(), "uA",
                                gm_row=gm_row, total_owners=12)
    assert detail.outlook.assets_signal_ranks == {
        "roster_value_share": 2, "draft_capital": 1}


def test_the_new_draft_need_and_age_keys_reach_the_view():
    detail = build_owner_detail(_entry_with_outlook(), "uA",
                                gm_row=_gm_row(rating=1600), total_owners=12)
    assert detail.outlook.age_profile.league_avg_age_by_position == {"RB": 25.4}
    need = detail.outlook.draft_needs[0]
    assert (need.held, need.ideal, need.kind) == (1, 2, "depth")


def test_the_retired_fields_are_gone_from_the_response():
    detail = build_owner_detail(_entry_with_outlook(), "uA",
                                gm_row=_gm_row(rating=1600), total_owners=12)
    d = detail.outlook.model_dump()
    for dead in ("window_breakdown", "strength_score",
                 "trajectory_score", "trajectory"):
        assert dead not in d


# ---- the pre-existing owner-view contract ----

def test_outlook_exposed_when_present():
    resp = build_owner_detail(_entry_with_outlook(), "uA")
    assert resp is not None
    assert resp.outlook.draft_capital.total_value == 1200.0
    assert resp.roster_rank.rank == 1 and resp.roster_rank.of == 2
    # draft_skill rank: uA (0.4) ranks above uB (-0.2) -> rank 1 of 2
    assert resp.draft_skill.rank == 1 and resp.draft_skill.of == 2


def test_outlook_absent_degrades_gracefully():
    entry = _entry()  # pre-feature cache: no outlook fields
    resp = build_owner_detail(entry, "uA")
    assert resp is not None
    assert resp.outlook is None
    assert resp.roster_rank is None
    assert resp.draft_skill is None


def test_franchise_blurb_exposed_when_present():
    entry = _entry(
        franchise_blurbs={"uA": {"blurb": "Ascending and dangerous.",
                                 "facts_hash": "x", "generated_at": "t"}})
    resp = build_owner_detail(entry, "uA")
    assert resp.franchise_blurb == "Ascending and dangerous."


def test_franchise_blurb_absent_is_none():
    resp = build_owner_detail(_entry(), "uA")
    assert resp.franchise_blurb is None
    assert resp.franchise_lead is None
    assert resp.franchise_segments is None


def test_franchise_lead_and_segments_exposed_when_present():
    entry = _entry(franchise_blurbs={"uA": {
        "lead": "The league's top roster, and its youngest.",
        "blurb": "73% of value sits with Malik Nabers.",
        "segments": [{"text": "73%", "mark": "num"},
                     {"text": " of value sits with ", "mark": None},
                     {"text": "Malik Nabers", "mark": "who"},
                     {"text": ".", "mark": None}],
        "facts_hash": "x", "generated_at": "t"}})
    resp = build_owner_detail(entry, "uA")
    assert resp.franchise_lead == "The league's top roster, and its youngest."
    assert [s.mark for s in resp.franchise_segments] == [
        "num", None, "who", None]
    assert resp.franchise_segments[2].text == "Malik Nabers"
    # The plain text stays the fallback and stays reconcilable with the
    # segments — the two must never say different things.
    assert "".join(s.text for s in resp.franchise_segments) == \
        resp.franchise_blurb


def test_a_pre_marks_cached_blurb_falls_back_to_plain_text():
    """A v2 record has a blurb and nothing else. It must render as prose, not
    as an empty panel."""
    entry = _entry(franchise_blurbs={"uA": {"blurb": "Ascending and dangerous.",
                                            "facts_hash": "x"}})
    resp = build_owner_detail(entry, "uA")
    assert resp.franchise_blurb == "Ascending and dangerous."
    assert resp.franchise_lead is None
    assert resp.franchise_segments is None


def test_a_malformed_segment_list_degrades_rather_than_500s():
    """The cache is a blob on disk; a shape that is not a list of {text, mark}
    must not take the whole owner page down."""
    for junk in ("not a list", [{"nope": 1}], [None], [{"text": 5}]):
        entry = _entry(franchise_blurbs={"uA": {
            "blurb": "Ascending.", "segments": junk}})
        resp = build_owner_detail(entry, "uA")
        assert resp.franchise_blurb == "Ascending."
        assert resp.franchise_segments is None


def test_an_unknown_mark_name_in_the_cache_degrades_to_plain():
    """A mark the renderer does not know is not a wrong colour, it is prose."""
    entry = _entry(franchise_blurbs={"uA": {
        "blurb": "Ascending now.",
        "segments": [{"text": "Ascending", "mark": "shout"},
                     {"text": " now.", "mark": None}]}})
    resp = build_owner_detail(entry, "uA")
    assert [s.mark for s in resp.franchise_segments] == [None, None]


def test_owner_window_uses_this_leagues_own_band_unit(monkeypatch):
    """WIRING. The owner page must band the stage on THIS league's realized
    rating spread, from the same `league_stage_sd` helper the standings row
    calls — one derivation, not two that can drift.

    `gm_row` carries one owner's rating and so cannot supply a spread; the
    league-wide read is what this guards. Spying on the argument is the only
    way to see it: on a fixture whose spread sits near the reference unit both
    band sets agree, so an output assertion would pass either way.
    """
    import app.services.owner_view as ov
    from app.services.franchise_redesign import league_stage_sd, live_ratings

    entry = _entry_with_outlook(
        outcome_signals={
            "uA": {"expected_wins": 0.65, "playoff_success": 0.80, "luck": 0.10},
            "uB": {"expected_wins": 0.35, "playoff_success": 0.10, "luck": -0.10},
        },
        season_records={"2024": {
            "uA": {"wins": 10, "losses": 4, "ties": 0},
            "uB": {"wins": 4, "losses": 10, "ties": 0},
        }},
    )
    expected = league_stage_sd(live_ratings(entry))
    assert expected is not None, "fixture produced no rated league to band on"

    seen: list[float | None] = []
    real = ov.rating_to_stage
    monkeypatch.setattr(
        ov, "rating_to_stage",
        lambda rating, *, sd=None: (seen.append(sd), real(rating, sd=sd))[1],
    )
    detail = build_owner_detail(entry, "uA", gm_row=_gm_row(rating=1600),
                                total_owners=2)
    assert detail.outlook is not None and detail.outlook.window is not None
    assert seen == [expected], (
        f"owner page banded on {seen}, not the league's own unit {expected}")


def test_owner_window_degrades_to_the_fixed_bands_when_ratings_blow_up(
        monkeypatch):
    """The league-wide read is a NEW failure path on a page that used to need
    only `gm_row`. It must fall back to the reference bands, never 500."""
    import app.services.owner_view as ov

    def boom(_entry):
        raise RuntimeError("signals corrupt")
    monkeypatch.setattr(
        "app.services.franchise_redesign.live_ratings", boom)
    detail = build_owner_detail(_entry_with_outlook(), "uA",
                                gm_row=_gm_row(rating=1600), total_owners=12)
    assert detail.outlook is not None
    assert detail.outlook.window == ov.rating_to_stage(1600)   # fixed bands
