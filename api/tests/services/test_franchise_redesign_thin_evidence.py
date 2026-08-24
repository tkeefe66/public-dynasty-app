"""Thin evidence: an owner with no completed season gets no rating at all.

The spec's "Thin evidence — absence, not a confident letter" section. The gate
lives at one chokepoint (``live_ratings``) so no surface can miss it, and it
removes the owner from the **z population**, not just from the display — a
placeholder 0.0 on ``expected_wins`` reads as "lost every all-play matchup in
every week", which drags the league mean and inflates the sd, re-grading
everyone else.
"""

from app.services.chain_cache import ChainCacheEntry
from app.services.franchise_redesign import live_ratings, rated_owners


def _season_record(wins: int, losses: int) -> dict:
    return {"wins": wins, "losses": losses, "ties": 0}


def _entry(*, owners: list[str], season_records: dict) -> ChainCacheEntry:
    """Three built-up/middling/down owners plus whatever extra uids are asked
    for, so a rating change from adding an owner is visible on the survivors."""
    tilt = {
        "u1": (0.70, 0.90, 0.10, 0.60, 0.55, 0.70),
        "u2": (0.50, 0.40, 0.00, 0.45, 0.35, 0.40),
        "u3": (0.30, 0.10, -0.10, 0.30, 0.20, 0.25),
        "newbie": (0.0, 0.0, 0.0, 0.20, 0.10, 0.15),
    }
    return ChainCacheEntry(
        league_id="L", chain=[], resolved_trades=[], grades={},
        owners={u: {"owner_name": u} for u in owners},
        playoff_weeks_by_league={}, roster_to_user_by_league={},
        league_name_by_id={}, league_season_by_id={},
        cached_at="2026-08-16T00:00:00+00:00",
        outcome_signals={
            u: {"expected_wins": tilt[u][0], "playoff_success": tilt[u][1],
                "luck": tilt[u][2]}
            for u in owners
        },
        outlook_signals={
            u: {"roster_value_share": tilt[u][3], "young_core_share": tilt[u][4],
                "draft_capital": tilt[u][5]}
            for u in owners
        },
        season_records=season_records,
    )


PLAYED = {"2025": {u: _season_record(7, 7) for u in ("u1", "u2", "u3")}}


def test_an_owner_with_no_completed_season_is_absent_from_the_ratings():
    entry = _entry(
        owners=["u1", "u2", "u3", "newbie"],
        # The live preseason shape: everyone has a 2026 row, nobody has played
        # it, and "newbie" took over a roster for a season not yet started.
        season_records={
            **PLAYED,
            "2026": {u: _season_record(0, 0) for u in ("u1", "u2", "u3", "newbie")},
        },
    )
    out = live_ratings(entry)
    assert "newbie" not in out
    assert set(out) == {"u1", "u2", "u3"}
    assert rated_owners(entry) == ["u1", "u2", "u3"]


def test_adding_an_unqualified_owner_does_not_move_any_qualified_rating():
    """The point of gating the population rather than the display."""
    without = live_ratings(_entry(owners=["u1", "u2", "u3"], season_records=PLAYED))
    with_newbie = live_ratings(_entry(
        owners=["u1", "u2", "u3", "newbie"],
        season_records={
            **PLAYED,
            "2026": {u: _season_record(0, 0) for u in ("u1", "u2", "u3", "newbie")},
        },
    ))
    assert set(with_newbie) == set(without)
    for uid in without:
        assert with_newbie[uid]["rating"] == without[uid]["rating"]
        assert with_newbie[uid]["pillars"] == without[uid]["pillars"]


def test_a_league_that_has_played_nothing_rates_nobody():
    """Otherwise every Results signal reads 0.0 for everyone, _stats floors the
    sd to zero, Results contributes nothing, and the league is graded A+ to D-
    purely on Assets — a confident spread over zero games."""
    entry = _entry(
        owners=["u1", "u2", "u3"],
        season_records={"2026": {u: _season_record(0, 0) for u in ("u1", "u2", "u3")}},
    )
    assert live_ratings(entry) == {}
    assert rated_owners(entry) == []


def test_a_season_under_the_anchor_week_floor_does_not_qualify_an_owner():
    entry = _entry(
        owners=["u1", "u2", "u3"],
        season_records={"2026": {u: _season_record(1, 1) for u in ("u1", "u2", "u3")}},
    )
    assert live_ratings(entry) == {}


def test_rated_owners_preserves_the_entry_owner_order():
    entry = _entry(owners=["u1", "u2", "u3"], season_records=PLAYED)
    assert rated_owners(entry) == ["u1", "u2", "u3"]


# --- The surfaces render the absence -----------------------------------------

def _preseason_entry() -> ChainCacheEntry:
    """Three owners with a 2025 season behind them plus a replacement manager
    who took over for a 2026 nobody has played — the live preseason case."""
    return _entry(
        owners=["u1", "u2", "u3", "newbie"],
        season_records={
            **PLAYED,
            "2026": {u: _season_record(0, 0) for u in ("u1", "u2", "u3", "newbie")},
        },
    )


def test_the_leaderboard_does_not_rank_an_unrated_owner():
    from app.services.leaderboard import build_leaderboard

    resp = build_leaderboard(_preseason_entry(), year="all", prev_ratings={})
    assert [r.user_id for r in resp.rows] == ["u1", "u2", "u3"]
    assert [r.rank for r in resp.rows] == [1, 2, 3]


def test_the_standings_row_carries_no_letter_for_an_unrated_owner():
    from app.services.aggregations import build_dashboard

    resp = build_dashboard(_preseason_entry(), "all", "ktc")
    by_uid = {r.user_id: r for r in resp.standings}
    assert by_uid["newbie"].gm_letter is None
    assert by_uid["newbie"].gm_rating is None
    assert by_uid["newbie"].gm_rank is None
    assert by_uid["u1"].gm_letter is not None


def test_the_owner_page_captions_a_replacement_manager_new_franchise():
    from app.services.owner_view import build_owner_detail

    detail = build_owner_detail(_preseason_entry(), "newbie")
    assert detail.franchise_rating is None
    assert detail.unrated_reason == "new_franchise"


def test_the_owner_page_captions_an_unplayed_league_first_season():
    from app.services.owner_view import build_owner_detail

    entry = _entry(
        owners=["u1", "u2", "u3"],
        season_records={"2026": {u: _season_record(0, 0) for u in ("u1", "u2", "u3")}},
    )
    detail = build_owner_detail(entry, "u1")
    assert detail.unrated_reason == "first_season"


def test_a_rated_owner_carries_no_unrated_reason():
    from app.services.owner_view import build_owner_detail

    detail = build_owner_detail(_preseason_entry(), "u1")
    assert detail.unrated_reason is None
