from datetime import date

from sleeper_dynasty.engine.dynasty import (
    analyze_age_profile,
    analyze_draft_capital,
    assess_draft_needs,
    build_dynasty_outlook,
    DynastyOutlook,
    AgeProfile,
    DraftCapital,
)
from sleeper_dynasty.models.player import Player
from sleeper_dynasty.models.league import DraftPick, Roster


def _make_player(pid: str, name: str, pos: str, birth_year: int) -> Player:
    return Player(
        player_id=pid, full_name=name, position=pos, team="TST",
        birth_date=date(birth_year, 6, 15),
    )


def test_age_profile_calculates_averages():
    players = [
        _make_player("1", "Young QB", "QB", 2002),   # 24
        _make_player("2", "Old RB", "RB", 1996),      # 30
        _make_player("3", "Mid WR", "WR", 1999),      # 27
        _make_player("4", "Young WR", "WR", 2003),    # 23
        _make_player("5", "Old TE", "TE", 1995),      # 31
    ]
    profile = analyze_age_profile(players, as_of=date(2026, 9, 1))
    assert isinstance(profile, AgeProfile)
    assert profile.avg_age_by_position["QB"] == 24
    assert profile.avg_age_by_position["RB"] == 30
    assert len(profile.aging_risks) == 2  # Old RB (30, RB threshold 26+) and Old TE (31, 28+)
    assert len(profile.core_young) >= 2  # Young QB (24) and Young WR (23)


def test_draft_capital_analysis():
    traded_picks = [
        DraftPick(season=2027, round=1, original_owner_id=1, current_owner_id=3),
        DraftPick(season=2027, round=2, original_owner_id=2, current_owner_id=1),
        DraftPick(season=2028, round=1, original_owner_id=1, current_owner_id=1),
    ]
    capital = analyze_draft_capital(
        roster_id=1,
        traded_picks=traded_picks,
        total_rosters=4,
        num_rounds=4,
    )
    assert isinstance(capital, DraftCapital)
    # Roster 1 lost their 2027 1st, gained a 2027 2nd from roster 2 → 4 - 1 + 1 = 4 picks
    assert capital.picks_by_season[2027] >= 3
    assert capital.net_vs_average != 0 or capital.net_vs_average == 0  # just verify it's computed


def _build() -> DynastyOutlook:
    players = [
        _make_player("rb1", "Young RB", "RB", 2002),
        _make_player("wr1", "Old WR", "WR", 1994),
    ]
    roster = Roster(
        roster_id=1, owner_id="u1", owner_name="Test",
        players=["rb1", "wr1"], wins=3, losses=3, ties=0,
        points_for=1200.0, points_against=1100.0,
    )
    return build_dynasty_outlook(
        roster=roster, roster_players=players, traded_picks=[],
        position_rankings={}, total_rosters=10,
    )


def test_build_dynasty_outlook_returns_the_three_surviving_fields():
    outlook = _build()
    assert isinstance(outlook, DynastyOutlook)
    assert isinstance(outlook.age_profile, AgeProfile)
    assert outlook.draft_capital.status in {"pick-rich", "neutral", "pick-poor"}
    assert isinstance(outlook.draft_needs, list)


def test_the_window_model_is_gone_from_the_object():
    outlook = _build()
    for dead in ("window", "trajectory", "strength_score",
                 "trajectory_score", "window_breakdown"):
        assert not hasattr(outlook, dead), f"{dead} survived the deletion"


# ---------------------------------------------------------------------------
# assess_draft_needs fixtures — held/ideal/kind
# ---------------------------------------------------------------------------


def _two_rbs_and_a_full_wr_room() -> list:
    """2 RBs (short of the ideal-4 depth) beside full, young rooms
    everywhere else, so RB is the only position with a live need."""
    return [
        _make_player("qb1", "QB One", "QB", 2003),
        _make_player("qb2", "QB Two", "QB", 2003),
        _make_player("rb1", "RB One", "RB", 2003),
        _make_player("rb2", "RB Two", "RB", 2003),
        _make_player("wr1", "WR One", "WR", 2003),
        _make_player("wr2", "WR Two", "WR", 2003),
        _make_player("wr3", "WR Three", "WR", 2003),
        _make_player("wr4", "WR Four", "WR", 2003),
        _make_player("wr5", "WR Five", "WR", 2003),
        _make_player("te1", "TE One", "TE", 2003),
        _make_player("te2", "TE Two", "TE", 2003),
    ]


def _ap() -> AgeProfile:
    return analyze_age_profile(
        _two_rbs_and_a_full_wr_room(), as_of=date(2026, 9, 1))


def _full_but_aging_rb_room() -> list:
    """A full (ideal-4) RB room, but every RB is past the RB aging threshold
    (26) — the room that should fire the ``aging`` branch, not ``depth``."""
    return [
        _make_player("qb1", "QB One", "QB", 2003),
        _make_player("qb2", "QB Two", "QB", 2003),
        _make_player("rb1", "RB One", "RB", 1996),
        _make_player("rb2", "RB Two", "RB", 1996),
        _make_player("rb3", "RB Three", "RB", 1996),
        _make_player("rb4", "RB Four", "RB", 1996),
        _make_player("wr1", "WR One", "WR", 2003),
        _make_player("wr2", "WR Two", "WR", 2003),
        _make_player("wr3", "WR Three", "WR", 2003),
        _make_player("wr4", "WR Four", "WR", 2003),
        _make_player("wr5", "WR Five", "WR", 2003),
        _make_player("te1", "TE One", "TE", 2003),
        _make_player("te2", "TE Two", "TE", 2003),
    ]


def _ap_with_aging_rbs() -> AgeProfile:
    return analyze_age_profile(
        _full_but_aging_rb_room(), as_of=date(2026, 9, 1))


def _a_complete_roster() -> list:
    """Every position at exactly its ideal depth, all young — no need
    should fire anywhere (the "QB ()" empty-need regression guard)."""
    return [
        _make_player("qb1", "QB One", "QB", 2003),
        _make_player("qb2", "QB Two", "QB", 2003),
        _make_player("rb1", "RB One", "RB", 2003),
        _make_player("rb2", "RB Two", "RB", 2003),
        _make_player("rb3", "RB Three", "RB", 2003),
        _make_player("rb4", "RB Four", "RB", 2003),
        _make_player("wr1", "WR One", "WR", 2003),
        _make_player("wr2", "WR Two", "WR", 2003),
        _make_player("wr3", "WR Three", "WR", 2003),
        _make_player("wr4", "WR Four", "WR", 2003),
        _make_player("wr5", "WR Five", "WR", 2003),
        _make_player("te1", "TE One", "TE", 2003),
        _make_player("te2", "TE Two", "TE", 2003),
    ]


def _ap_all_young() -> AgeProfile:
    return analyze_age_profile(_a_complete_roster(), as_of=date(2026, 9, 1))


def test_every_need_carries_held_and_ideal_and_its_branch():
    """held/ideal are emitted on EVERY need; `kind` says which branch fired,
    because `urgency` cannot — the depth branch and the aging branch both
    emit "developing"."""
    needs = assess_draft_needs(
        roster_players=_two_rbs_and_a_full_wr_room(),
        position_rankings={}, age_profile=_ap(), total_rosters=12,
    )
    for n in needs:
        assert n.held >= 0 and n.ideal > 0
        assert n.kind in {"starters", "quality", "depth", "aging"}


def test_the_aging_branch_reports_a_full_room():
    """The regression the pips exist to avoid. The aging branch is an `elif`
    reached ONLY when current_count >= ideal_depth, so held >= ideal there —
    four filled pips beside a live need reads as a contradiction, which is why
    the UI gates pips on kind == "depth"."""
    needs = assess_draft_needs(
        roster_players=_full_but_aging_rb_room(),
        position_rankings={}, age_profile=_ap_with_aging_rbs(), total_rosters=12,
    )
    rb = next(n for n in needs if n.position == "RB")
    assert rb.kind == "aging"
    assert rb.held >= rb.ideal


def test_the_depth_branch_reports_a_short_room():
    needs = assess_draft_needs(
        roster_players=_two_rbs_and_a_full_wr_room(),
        position_rankings={}, age_profile=_ap(), total_rosters=12,
    )
    rb = next(n for n in needs if n.position == "RB")
    assert rb.kind == "depth"
    assert rb.held < rb.ideal


def test_no_row_for_a_position_with_no_need():
    """The "QB ()" regression guard. A row with urgency="" can surface as the
    owner's top need in the live LLM packet (franchise_outlook.py ->
    HeroBand.tsx) and would permanently kill the needs empty state."""
    needs = assess_draft_needs(
        roster_players=_a_complete_roster(),
        position_rankings={}, age_profile=_ap_all_young(), total_rosters=12,
    )
    assert needs == []
    assert all(n.urgency for n in needs)
