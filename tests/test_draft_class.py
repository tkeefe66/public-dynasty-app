import pytest

from sleeper_dynasty.engine.draft_class import (
    DraftClass, build_draft_classes, build_draft_picks,
)


def _draft(draft_id, season, player_type, *, league_id="lg", status="complete",
           dtype="snake", teams=12):
    return {
        "draft_id": draft_id, "league_id": league_id, "season": str(season),
        "status": status, "type": dtype,
        "settings": {"rounds": 4, "teams": teams, "player_type": player_type},
    }


# --- format selection ---

def test_dynasty_keeps_rookie_drafts_and_drops_the_startup():
    drafts = {"lg": [_draft("d_start", 2022, 0), _draft("d_rook", 2023, 1)]}
    out = build_draft_classes(
        drafts_by_league=drafts, league_format="dynasty", origin_season=2022)
    assert [c.draft_id for c in out] == ["d_rook"]
    assert out[0].kind == "rookie"
    assert out[0].axis == "blend"


def test_dynasty_keeps_a_rookie_draft_held_in_the_origin_season():
    """A league that ran a startup AND a rookie draft in year one keeps the
    rookie class — player_type discriminates, the season no longer does."""
    drafts = {"lg": [_draft("d_start", 2022, 0), _draft("d_rook", 2022, 1)]}
    out = build_draft_classes(
        drafts_by_league=drafts, league_format="dynasty", origin_season=2022)
    assert [c.draft_id for c in out] == ["d_rook"]


def test_redraft_keeps_every_full_draft_including_year_one():
    drafts = {"lg": [_draft("d1", 2024, 0), _draft("d2", 2025, 0)]}
    out = build_draft_classes(
        drafts_by_league=drafts, league_format="redraft", origin_season=2024)
    assert [c.draft_id for c in out] == ["d1", "d2"]
    assert all(c.kind == "full" for c in out)
    assert all(c.axis == "production" for c in out)


def test_keeper_grades_on_production_like_redraft():
    drafts = {"lg": [_draft("d1", 2024, 0)]}
    out = build_draft_classes(
        drafts_by_league=drafts, league_format="keeper", origin_season=2024)
    assert out[0].axis == "production"
    assert out[0].kind == "full"


def test_incomplete_drafts_are_excluded():
    drafts = {"lg": [_draft("d1", 2025, 1, status="drafting")]}
    assert build_draft_classes(
        drafts_by_league=drafts, league_format="dynasty", origin_season=2024) == []


def test_auction_is_ingested_but_not_gradeable():
    drafts = {"lg": [_draft("d1", 2025, 0, dtype="auction")]}
    out = build_draft_classes(
        drafts_by_league=drafts, league_format="redraft", origin_season=2025)
    assert out[0].gradeable is False
    assert out[0].draft_type == "auction"


def test_missing_player_type_falls_back_to_the_origin_season_heuristic():
    """Older Sleeper drafts may not carry player_type. Dynasty then falls back
    to the previous rule rather than silently grading the startup."""
    d_start = _draft("d_start", 2022, 0)
    d_late = _draft("d_late", 2023, 0)
    for d in (d_start, d_late):
        del d["settings"]["player_type"]
    out = build_draft_classes(
        drafts_by_league={"lg": [d_start, d_late]},
        league_format="dynasty", origin_season=2022)
    assert [c.draft_id for c in out] == ["d_late"]


# --- pick normalization ---

def _cls(draft_id="d1", season=2025, kind="full", teams=12, axis="production"):
    return DraftClass(
        draft_id=draft_id, league_id="lg", season=season, kind=kind,
        draft_type="snake", teams=teams, gradeable=True, axis=axis)


def test_picks_carry_kind_keeper_flag_and_overall_pick_number():
    picks = {"d1": [
        {"round": 1, "draft_slot": 1, "pick_no": 1, "player_id": "p1",
         "picked_by": "u1", "is_keeper": None},
        {"round": 2, "draft_slot": 3, "pick_no": 15, "player_id": "p2",
         "picked_by": "u2", "is_keeper": True},
    ]}
    out = build_draft_picks(
        classes=[_cls()], picks_by_draft_id=picks, roster_to_user_by_league={})
    assert [p.player_id for p in out] == ["p1", "p2"]
    assert out[0].is_keeper is False
    assert out[1].is_keeper is True
    assert out[0].draft_kind == "full"
    assert out[1].pick_no == 15


def test_pick_number_is_derived_when_sleeper_omits_it():
    picks = {"d1": [
        {"round": 2, "draft_slot": 1, "player_id": "p1", "picked_by": "u1"},
    ]}
    out = build_draft_picks(
        classes=[_cls(teams=12)], picks_by_draft_id=picks,
        roster_to_user_by_league={})
    assert out[0].pick_no == 13


def test_drafter_falls_back_to_the_slot_rosters_current_owner():
    picks = {"d1": [
        {"round": 1, "draft_slot": 1, "pick_no": 1, "player_id": "p1",
         "picked_by": None, "roster_id": 4},
    ]}
    out = build_draft_picks(
        classes=[_cls()], picks_by_draft_id=picks,
        roster_to_user_by_league={"lg": {4: "u9"}})
    assert out[0].drafter_id == "u9"


def test_picks_inherit_gradeable_from_their_class():
    """An auction class's picks must carry gradeable=False through to the
    per-pick DraftedPick rows — draft_skill and ADP grading both key off the
    pick, not the class, so the flag has to survive normalization."""
    picks = {"d1": [
        {"round": 1, "draft_slot": 1, "pick_no": 1, "player_id": "p1",
         "picked_by": "u1"},
    ]}
    auction_cls = DraftClass(
        draft_id="d1", league_id="lg", season=2025, kind="full",
        draft_type="auction", teams=12, gradeable=False, axis="production")
    out = build_draft_picks(
        classes=[auction_cls], picks_by_draft_id=picks,
        roster_to_user_by_league={})
    assert out[0].gradeable is False


def test_picks_without_a_player_or_drafter_are_dropped():
    picks = {"d1": [
        {"round": 1, "draft_slot": 1, "pick_no": 1, "player_id": None,
         "picked_by": "u1"},
        {"round": 1, "draft_slot": 2, "pick_no": 2, "player_id": "p2",
         "picked_by": None},
    ]}
    out = build_draft_picks(
        classes=[_cls()], picks_by_draft_id=picks, roster_to_user_by_league={})
    assert out == []


# --- player_type is a POOL RESTRICTION, not a draft kind ---------------------

def test_dynasty_keeps_an_open_pool_rookie_draft_from_a_later_season():
    """Real league (Dynasty Chill, 2026): a 4-round rookie draft that leaves
    `player_type` at 0 so managers *may* also take a veteran free agent. 28 of
    its 48 picks were rookies. `player_type=0` means "the pool is open", NOT
    "this is a startup" — and a startup drafts whole rosters in the league's
    first season, not four rounds in its second.

    Treating open-pool as startup discarded this league's only draft every
    year, which the season heuristic it replaced got right.
    """
    drafts = {"lg": [_draft("d_start", 2024, 0), _draft("d_rook", 2026, 0)]}
    out = build_draft_classes(
        drafts_by_league=drafts, league_format="dynasty", origin_season=2024)
    assert [c.draft_id for c in out] == ["d_rook"]
    assert out[0].kind == "rookie"


def test_dynasty_still_drops_the_open_pool_startup_in_the_origin_season():
    drafts = {"lg": [_draft("d_start", 2024, 0)]}
    assert build_draft_classes(
        drafts_by_league=drafts, league_format="dynasty",
        origin_season=2024) == []


def test_player_type_1_still_wins_over_the_season_test():
    """A rookies-only draft is a rookie class even in the origin season — the
    positive signal is trusted outright."""
    drafts = {"lg": [_draft("d_start", 2024, 0), _draft("d_rook", 2024, 1)]}
    out = build_draft_classes(
        drafts_by_league=drafts, league_format="dynasty", origin_season=2024)
    assert [c.draft_id for c in out] == ["d_rook"]
