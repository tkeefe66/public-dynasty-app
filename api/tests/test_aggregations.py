from __future__ import annotations

import pytest

from app.models.league import DashboardResp
from app.services.aggregations import build_dashboard
from app.services.chain_cache import ChainCacheEntry


def _sample_entry() -> ChainCacheEntry:
    return ChainCacheEntry(
        league_id="L_current",
        chain=[
            {"league_id": "L_current", "season": 2026, "name": "Bros", "total_rosters": 2, "playoff_week_start": 15},
            {"league_id": "L_prev", "season": 2024, "name": "Bros", "total_rosters": 2, "playoff_week_start": 15},
        ],
        resolved_trades=[
            {
                "trade": {
                    "transaction_id": "tx_2024", "league_id": "L_prev", "season": 2024,
                    "week": 2, "traded_at": "2024-09-12T00:00:00+00:00",
                    "sides": {},
                },
                "sides": {
                    "u_alice": {"user_id": "u_alice", "received": [{"name": "Bijan", "player_id": "p_b"}], "given": []},
                    "u_bob": {"user_id": "u_bob", "received": [], "given": [{"name": "Bijan", "player_id": "p_b"}]},
                },
            },
            {
                "trade": {
                    "transaction_id": "tx_2026", "league_id": "L_current", "season": 2026,
                    "week": 1, "traded_at": "2026-05-19T00:00:00+00:00",
                    "sides": {},
                },
                "sides": {
                    "u_alice": {"user_id": "u_alice", "received": [], "given": []},
                    "u_bob": {"user_id": "u_bob", "received": [], "given": []},
                },
            },
        ],
        grades={
            "tx_2024": {
                "trade_id": "tx_2024",
                "received_ktc": {"u_alice": 1450.0, "u_bob": 600.0},
                "snapshot_value_swing": {"u_alice": 1450.0, "u_bob": -1450.0},
                "production_total": {"u_alice": 387.4, "u_bob": -387.4},
                "realized_impact_received": {
                    "u_alice": {"starter_weeks": 18, "starter_points_contributed": 286.0,
                                "win_share_points": 198.0, "decisive_starts": 4, "playoff_starts": 2},
                    "u_bob": {"starter_weeks": 0, "starter_points_contributed": 0,
                              "win_share_points": 0, "decisive_starts": 0, "playoff_starts": 0},
                },
                "realized_impact_given": {
                    "u_alice": {"starter_weeks": 0, "starter_points_contributed": 0,
                                "win_share_points": 0, "decisive_starts": 0, "playoff_starts": 0},
                    "u_bob": {"starter_weeks": 18, "starter_points_contributed": 286.0,
                              "win_share_points": 198.0, "decisive_starts": 4, "playoff_starts": 2},
                },
            },
            "tx_2026": {
                "trade_id": "tx_2026",
                "received_ktc": {"u_alice": 0, "u_bob": 0},
                "snapshot_value_swing": {"u_alice": 0, "u_bob": 0},
                "production_total": {"u_alice": 0, "u_bob": 0},
                "realized_impact_received": {
                    "u_alice": {"starter_weeks": 0, "starter_points_contributed": 0,
                                "win_share_points": 0, "decisive_starts": 0, "playoff_starts": 0},
                    "u_bob": {"starter_weeks": 0, "starter_points_contributed": 0,
                              "win_share_points": 0, "decisive_starts": 0, "playoff_starts": 0},
                },
                "realized_impact_given": {
                    "u_alice": {"starter_weeks": 0, "starter_points_contributed": 0,
                                "win_share_points": 0, "decisive_starts": 0, "playoff_starts": 0},
                    "u_bob": {"starter_weeks": 0, "starter_points_contributed": 0,
                              "win_share_points": 0, "decisive_starts": 0, "playoff_starts": 0},
                },
            },
        },
        owners={"u_alice": {"owner_name": "Alice", "team_name": None, "avatar_url": None}, "u_bob": {"owner_name": "Bob", "team_name": None, "avatar_url": None}},
        playoff_weeks_by_league={"L_current": 15, "L_prev": 15},
        roster_to_user_by_league={"L_current": {1: "u_alice", 2: "u_bob"}, "L_prev": {1: "u_alice", 2: "u_bob"}},
        league_name_by_id={"L_current": "Bros", "L_prev": "Bros"},
        league_season_by_id={"L_current": 2026, "L_prev": 2024},
        outcome_signals={
            "u_alice": {"championships": 2, "playoff_depth": 4, "made_playoffs": 1.0,
                        "final_seed": 3.0, "points_for_rank": 3.0},
            "u_bob":   {"championships": 0, "playoff_depth": 0, "made_playoffs": 0.0,
                        "final_seed": 1.0, "points_for_rank": 1.0},
        },
        outlook_signals={
            "u_alice": {"roster_value": 60000.0, "draft_capital": 3200.0,
                        "draft_skill": 0.82, "youth": -25.0},
            "u_bob":   {"roster_value": 30000.0, "draft_capital": 800.0,
                        "draft_skill": 0.10, "youth": -29.0},
        },
        # No `window` / `trajectory` / axis-score keys: the standings' Window
        # is derived from the row's own Franchise Rating now, and nothing
        # reads a stage off this blob.
        dynasty_outlooks={
            "u_alice": {"age_profile": {"avg_age_by_position": {},
                                        "overall_avg_age": 25.0,
                                        "aging_risks": [], "core_young": []},
                        "draft_capital": {"picks_by_season": {},
                                          "picks_by_season_round": {},
                                          "net_vs_average": 0.0,
                                          "status": "neutral"},
                        "draft_needs": []},
            "u_bob":   {"age_profile": {"avg_age_by_position": {},
                                        "overall_avg_age": 28.0,
                                        "aging_risks": [], "core_young": []},
                        "draft_capital": {"picks_by_season": {},
                                          "picks_by_season_round": {},
                                          "net_vs_average": 0.0,
                                          "status": "neutral"},
                        "draft_needs": []},
        },
        season_ratings={
            "2024": {"u_alice": 1700, "u_bob": 1500, "u_carol": 1300},
            "2026": {"u_alice": 1800, "u_bob": 1500, "u_carol": 1200},
        },
        draft_skill_by_season={
            "2024": {"u_alice": 0.45, "u_bob": 0.10},
            "2026": {"u_alice": 0.62, "u_bob": 0.08},
        },
        season_records={
            "2024": {
                "u_alice": {"wins": 9, "losses": 4, "ties": 0, "rank": 1, "total_teams": 2,
                            "champion": True, "runner_up": False, "made_playoffs": True,
                            "playoff_place": 1, "rounds_won": 2},
                "u_bob":   {"wins": 4, "losses": 9, "ties": 0, "rank": 2, "total_teams": 2,
                            "champion": False, "runner_up": True, "made_playoffs": True,
                            "playoff_place": 2, "rounds_won": 1},
            },
            "2026": {
                "u_alice": {"wins": 2, "losses": 1, "ties": 0, "rank": 1, "total_teams": 2,
                            "champion": False, "runner_up": False, "made_playoffs": False},
                "u_bob":   {"wins": 1, "losses": 2, "ties": 0, "rank": 2, "total_teams": 2,
                            "champion": False, "runner_up": False, "made_playoffs": False},
            },
        },
        cached_at="2026-05-28T12:00:00Z",
        warnings=[],
    )


def test_build_dashboard_all_years_includes_every_trade():
    e = _sample_entry()
    resp = build_dashboard(e, year="all", lens="ktc")
    assert isinstance(resp, DashboardResp)
    assert resp.selected_year == "all"
    assert resp.selected_lens == "ktc"
    # net_ktc is realized received_ktc (all-positive); alice (1450) sorts above bob (600).
    assert resp.standings[0].owner.owner_name == "Alice"
    assert resp.standings[0].rank == 1
    assert resp.standings[0].net_ktc == 1450
    assert resp.standings[1].net_ktc == 600


def test_build_dashboard_year_filter_only_counts_that_year():
    e = _sample_entry()
    resp = build_dashboard(e, year=2024, lens="ktc")
    # Both trades are graded same per-side, but only 2024 should drive standings.
    alice = next(r for r in resp.standings if r.user_id == "u_alice")
    assert alice.trades == 1
    assert alice.net_ktc == 1450


def test_build_dashboard_no_trades_for_year_yields_zero_standings():
    e = _sample_entry()
    resp = build_dashboard(e, year=2025, lens="ktc")
    for row in resp.standings:
        assert row.trades == 0
        assert row.net_ktc == 0


def test_build_dashboard_hero_stats_top_gm_set():
    e = _sample_entry()
    resp = build_dashboard(e, year="all", lens="ktc")
    # Alice has stronger signals -> highest GM rating -> top_gm
    assert resp.hero_stats.top_gm.owner == "Alice"
    assert resp.hero_stats.top_gm.owner_user_id == "u_alice"
    assert resp.hero_stats.top_gm.value != "—"
    # Best roster: alice has higher roster_value signal
    assert resp.hero_stats.best_roster.owner == "Alice"
    # Draft ace: alice has higher draft_skill signal
    assert resp.hero_stats.draft_ace.owner == "Alice"


def test_build_dashboard_headline_trades_ranked_by_swing():
    e = _sample_entry()
    resp = build_dashboard(e, year="all", lens="ktc")
    assert len(resp.headline_trades) >= 1
    # tx_2024 has the bigger Trade Value swing (1450) vs tx_2026 (0).
    assert resp.headline_trades[0].trade_id == "tx_2024"
    assert resp.headline_trades[0].swing_ktc == 1450.0
    # Ranked by swing, descending — the most consequential move leads.
    swings = [t.swing_ktc for t in resp.headline_trades]
    assert swings == sorted(swings, reverse=True)


def test_build_dashboard_headline_trades_respect_year_filter():
    e = _sample_entry()
    resp24 = build_dashboard(e, year=2024, lens="ktc")
    assert [t.trade_id for t in resp24.headline_trades] == ["tx_2024"]
    # No trades in 2025 → empty headline list, not stale carryover.
    resp25 = build_dashboard(e, year=2025, lens="ktc")
    assert resp25.headline_trades == []


def test_net_ktc_rolls_from_realized_received_ktc():
    from app.services.aggregations import _aggregate_owner_rows

    entry = ChainCacheEntry(
        league_id="L",
        chain=[{"league_id": "L", "season": 2026, "name": "Bros", "total_rosters": 2, "playoff_week_start": 15}],
        resolved_trades=[
            {
                "trade": {
                    "transaction_id": "t1", "league_id": "L", "season": 2026,
                    "week": 1, "traded_at": "2026-05-19T00:00:00+00:00", "sides": {},
                },
                "sides": {
                    "A": {"user_id": "A", "received": [], "given": []},
                    "D": {"user_id": "D", "received": [], "given": []},
                },
            },
        ],
        grades={
            "t1": {
                "received_ktc": {"A": 6000.0, "D": 4100.0},
                "snapshot_value_swing": {"A": 1900.0, "D": -1900.0},
                "production_total": {"A": 0.0, "D": 0.0},
            },
        },
        owners={"A": {"owner_name": "A", "team_name": None, "avatar_url": None},
                "D": {"owner_name": "D", "team_name": None, "avatar_url": None}},
        playoff_weeks_by_league={"L": 15},
        roster_to_user_by_league={"L": {1: "A", 2: "D"}},
        league_name_by_id={"L": "Bros"},
        league_season_by_id={"L": 2026},
        cached_at="2026-05-28T12:00:00Z",
        warnings=[],
    )
    rows = _aggregate_owner_rows(entry, list(entry.resolved_trades))
    assert rows["A"]["net_ktc"] == 6000.0  # realized received, not the swing (1900)
    assert rows["D"]["net_ktc"] == 4100.0


def test_letter_grade_is_league_relative():
    from app.services.aggregations import _letter_grade
    net = {"A": 18000.0, "B": 9000.0, "C": -2000.0, "D": -11000.0}
    # mean 3500, pop sd ~10965 -> z ~ {A:+1.32, B:+0.50, C:-0.50, D:-1.32}
    assert _letter_grade(net) == {"A": "A", "B": "B+", "C": "B−", "D": "D"}


def test_standings_at_trade_aggregate_over_subset():
    e = _sample_entry()
    # net_ktc sums realized received_ktc (1000 + 500 = 1500).
    # The at_trade/aged diagnostic still derives from the swing subset:
    #   tx_2024: today-swing=1000, at-trade=800 (aged +200).
    #   tx_2026: today-swing=500, blank at-trade -> excluded from both subsets.
    e.grades["tx_2024"]["received_ktc"] = {"u_alice": 1000.0, "u_bob": 0.0}
    e.grades["tx_2024"]["snapshot_value_swing"] = {"u_alice": 1000.0, "u_bob": -1000.0}
    e.grades["tx_2024"]["at_trade_value_swing"] = {"u_alice": 800.0, "u_bob": -800.0}
    e.grades["tx_2024"]["aged_value_swing"] = {"u_alice": 200.0, "u_bob": -200.0}
    e.grades["tx_2026"]["received_ktc"] = {"u_alice": 500.0, "u_bob": 0.0}
    e.grades["tx_2026"]["snapshot_value_swing"] = {"u_alice": 500.0, "u_bob": -500.0}
    e.grades["tx_2026"]["at_trade_value_swing"] = None

    resp = build_dashboard(e, year="all", lens="ktc")
    alice = next(r for r in resp.standings if r.user_id == "u_alice")
    assert alice.net_ktc == 1500.0           # realized received: 1000 + 500
    assert alice.net_ktc_at_trade == 800.0   # subset {tx_2024}
    assert alice.net_ktc_aged == 200.0       # 1000 - 800 over {tx_2024}


def test_standings_gm_rating_and_rank_populated():
    e = _sample_entry()
    resp = build_dashboard(e, year="all", lens="ktc")
    # All rows should have gm_rating and gm_rank set
    for row in resp.standings:
        assert row.gm_rating is not None
        assert row.gm_rank is not None
    # Alice has stronger signals -> should rank higher
    alice = next(r for r in resp.standings if r.user_id == "u_alice")
    bob = next(r for r in resp.standings if r.user_id == "u_bob")
    assert alice.gm_rank < bob.gm_rank
    assert alice.gm_rating > bob.gm_rating


def test_standings_window_and_draft_capital_populated():
    """`window` is the stage derived from the SAME rating on the row, so the
    standings and /owner/{uid} can never disagree about a franchise's stage."""
    from sleeper_dynasty.engine.gm_rating import STAGE_BANDS, rating_to_stage
    e = _sample_entry()
    resp = build_dashboard(e, year="all", lens="ktc")
    alice = next(r for r in resp.standings if r.user_id == "u_alice")
    bob = next(r for r in resp.standings if r.user_id == "u_bob")
    assert alice.window == rating_to_stage(alice.gm_rating)
    assert bob.window == rating_to_stage(bob.gm_rating)
    # Both are real stage strings, not a leftover from the blob (which no
    # longer carries one) — a two-owner league can legitimately land both
    # franchises in the same band, so their stages are NOT asserted distinct.
    assert {alice.window, bob.window} <= {
        s for _, s in STAGE_BANDS} | {"Rebuilding"}
    assert alice.draft_capital_value == 3200.0
    assert bob.draft_capital_value == 800.0


def test_standings_gm_trend_zero_without_prev_ratings():
    e = _sample_entry()
    resp = build_dashboard(e, year="all", lens="ktc")
    assert all(r.gm_trend == 0 for r in resp.standings)


def test_standings_gm_trend_with_prev_ratings():
    e = _sample_entry()
    # Prior snapshot had bob #1, alice #2 -> alice climbed, bob dropped
    prev = {"u_bob": 2000, "u_alice": 1000}
    resp = build_dashboard(e, year="all", lens="ktc", prev_ratings=prev)
    alice = next(r for r in resp.standings if r.user_id == "u_alice")
    bob = next(r for r in resp.standings if r.user_id == "u_bob")
    assert alice.gm_trend > 0   # moved up
    assert bob.gm_trend < 0    # moved down


def test_standings_sorted_by_gm_rating_by_default():
    e = _sample_entry()
    resp = build_dashboard(e, year="all", lens="ktc")
    ratings = [r.gm_rating for r in resp.standings]
    assert ratings == sorted(ratings, reverse=True)


def test_hero_stats_biggest_weekly_rise_flat_without_prev():
    e = _sample_entry()
    resp = build_dashboard(e, year="all", lens="ktc")
    assert resp.hero_stats.biggest_weekly_rise.value == "—"


def test_hero_stats_biggest_weekly_rise_with_prev():
    e = _sample_entry()
    prev = {"u_bob": 2000, "u_alice": 1000}
    resp = build_dashboard(e, year="all", lens="ktc", prev_ratings=prev)
    # year="all" -> all-time mode: baseline = season_ratings["2024"] (first season).
    # Alice was rank 1 in 2024, still rank 1 now; Bob rank 2 then and now.
    # No positional change -> "—" (prev_ratings not used in all-time mode).
    assert resp.hero_stats.biggest_weekly_rise.value == "—"


def test_rise_card_all_time_label_and_value():
    """year='all' -> Biggest All-Time Riser, baseline = first season scoped."""
    e = _sample_entry()
    resp = build_dashboard(e, year="all", lens="ktc", is_in_season=False)
    card = resp.hero_stats.biggest_weekly_rise
    assert card.label == "Biggest All-Time Riser"
    assert card.value in ("—", "▲1")


def test_rise_card_past_season_label():
    """viewing year=2024 (past completed) -> Biggest Year Riser."""
    e = _sample_entry()
    resp = build_dashboard(e, year=2024, lens="ktc", is_in_season=False)
    card = resp.hero_stats.biggest_weekly_rise
    assert card.label == "Biggest Year Riser"
    # No season_ratings["2023"] exists -> baseline empty -> value="—"
    assert card.value == "—"


def test_rise_card_off_season_label():
    """current season, off-season months -> Biggest Off-Season Riser."""
    e = _sample_entry()
    # current season = max chain season = 2026; is_in_season=False
    resp = build_dashboard(e, year=2026, lens="ktc", is_in_season=False)
    card = resp.hero_stats.biggest_weekly_rise
    assert card.label == "Biggest Off-Season Riser"
    assert card.value in ("—", "▲1", "▲2")


def test_rise_card_in_season_label():
    """current season + in-season months -> Biggest Weekly Rise."""
    e = _sample_entry()
    prev = {"u_carol": 1800, "u_bob": 1500, "u_alice": 1200}  # alice was rank 3
    resp = build_dashboard(e, year=2026, lens="ktc", is_in_season=True, prev_ratings=prev)
    card = resp.hero_stats.biggest_weekly_rise
    assert card.label == "Biggest Weekly Rise"
    assert card.owner == "Alice"  # alice climbed from rank 3 to rank 1 = +2
    assert card.value == "▲2"


def test_standing_row_season_record_historical_year():
    e = _sample_entry()
    resp = build_dashboard(e, year=2024, lens="ktc")
    alice = next(r for r in resp.standings if r.user_id == "u_alice")
    bob = next(r for r in resp.standings if r.user_id == "u_bob")
    assert alice.season_record == "9-4"
    # alice was champion in 2024 → 1st place (with trophy), not reg-season rank
    assert alice.best_finish == "1st 🏆"
    # bob was runner-up → 2nd place
    assert bob.best_finish == "2nd"


def test_finish_label_place_for_playoffs_pick_for_toilet():
    from app.services.aggregations import _finish_label
    # Winners bracket → championship place.
    assert _finish_label({"playoff_place": 1}) == "1st 🏆"
    assert _finish_label({"playoff_place": 3}) == "3rd"
    assert _finish_label({"playoff_place": 6}) == "6th"
    # Losers (toilet) bracket → draft pick; toilet champ = 1.01.
    assert _finish_label({"toilet_place": 1}) == "1.01 🚽"
    assert _finish_label({"toilet_place": 4}) == "1.04"
    # Older cached records without placement fields fall back to flags.
    assert _finish_label({"champion": True}) == "1st 🏆"
    assert _finish_label({"made_playoffs": True}) == "Playoffs"
    assert _finish_label({}) == "—"


def test_standing_row_season_record_all_time():
    e = _sample_entry()
    resp = build_dashboard(e, year="all", lens="ktc")
    alice = next(r for r in resp.standings if r.user_id == "u_alice")
    # career: 9+2 = 11 wins, 4+1 = 5 losses across 2024+2026
    assert alice.season_record == "11-5"
    # alice won 1 championship → one trophy, no other badges
    assert alice.best_finish == "🏆"


def test_alltime_finish_badge_composition():
    from app.services.aggregations import _fmt_record
    sr = {
        "2021": {"u": {"wins": 10, "losses": 4, "champion": True, "made_playoffs": True, "rounds_won": 3}},
        "2022": {"u": {"wins": 9, "losses": 5, "champion": True, "made_playoffs": True, "rounds_won": 3}},
        "2023": {"u": {"wins": 8, "losses": 6, "runner_up": True, "made_playoffs": True, "rounds_won": 2}},
        "2024": {"u": {"wins": 6, "losses": 8, "made_playoffs": True, "rounds_won": 0}},  # made playoffs, lost R1
        "2025": {"u": {"wins": 3, "losses": 11, "toilet_place": 1}},                      # won the toilet bowl
    }
    _record, finish, _playoff = _fmt_record("u", "all", sr)
    assert finish == "🏆🏆 🚽"


def test_standing_row_no_record_when_season_missing():
    e = _sample_entry()
    resp = build_dashboard(e, year=2025, lens="ktc")  # no 2025 in season_records
    for row in resp.standings:
        assert row.season_record is None
        assert row.best_finish is None


def test_build_dashboard_surfaces_league_phase():
    e = _sample_entry()
    e.league_phase = {"phase": "regular", "season": 2026, "week": 5}
    resp = build_dashboard(e, year="all", lens="ktc")
    assert resp.phase == "regular"
    assert resp.phase_season == 2026
    assert resp.phase_week == 5


def _recap_blob():
    return {
        "season": "2026", "week": 4,
        "high_score": {"user_id": "u_a", "points": 140.0},
        "blowout": {"winner_user_id": "u_a", "loser_user_id": "u_b", "margin": 50.0},
        "traded_points": {"user_id": "u_b", "points": 21.5},
    }


def test_build_dashboard_surfaces_week_recap_with_owner_refs():
    e = _sample_entry()
    e.league_phase = {"phase": "regular", "season": 2026, "week": 5}
    e.week_recap = _recap_blob()
    resp = build_dashboard(e, year="all", lens="ktc")
    assert resp.week_recap is not None
    assert resp.week_recap.week == 4
    assert resp.week_recap.high_score.points == 140.0
    # Owner refs are attached at assembly so names honor the same overrides
    # every other row does — the blob itself only carries user ids.
    assert resp.week_recap.high_score.owner is not None
    assert resp.week_recap.high_score.owner.owner_name
    assert resp.week_recap.blowout.loser is not None
    assert resp.week_recap.traded_points is not None
    assert resp.week_recap.traded_points.points == 21.5


def test_week_recap_is_none_on_pre_feature_entry():
    # Surface fallback: an entry cached before the field exists has {}, and the
    # lead keeps its placeholder until the next refresh stamps a real recap.
    e = _sample_entry()
    e.league_phase = {"phase": "regular", "season": 2026, "week": 5}
    resp = build_dashboard(e, year="all", lens="ktc")
    assert resp.week_recap is None


def test_week_recap_withheld_outside_the_regular_season():
    e = _sample_entry()
    e.league_phase = {"phase": "post", "season": 2026, "week": 16}
    e.week_recap = _recap_blob()  # stale blob from the last regular-season refresh
    resp = build_dashboard(e, year="all", lens="ktc")
    assert resp.week_recap is None


def test_week_recap_withheld_on_a_partial_blob():
    e = _sample_entry()
    e.league_phase = {"phase": "regular", "season": 2026, "week": 5}
    blob = _recap_blob()
    del blob["blowout"]["winner_user_id"]
    e.week_recap = blob
    resp = build_dashboard(e, year="all", lens="ktc")
    assert resp.week_recap is None


def test_build_dashboard_phase_defaults_offseason_on_pre_phase_entry():
    # Entries cached before the phase field exist -> graceful fallback until
    # the next refresh stamps the real phase.
    e = _sample_entry()
    resp = build_dashboard(e, year="all", lens="ktc")
    assert resp.phase == "offseason"
    assert resp.phase_season == 2026  # newest chain season
    assert resp.phase_week is None


def test_standings_window_uses_this_leagues_own_band_unit(monkeypatch):
    """WIRING. The stage must be banded on the league's OWN rating spread, via
    the single `league_stage_sd` helper — not on the reference POINTS_PER_SD.

    Asserting `window == rating_to_stage(rating)` cannot catch this: on a
    fixture whose spread happens to sit near the reference, both units agree.
    So spy on the actual argument instead.
    """
    import app.services.aggregations as agg
    from app.services.franchise_redesign import league_stage_sd, live_ratings

    seen: list[float | None] = []
    real = agg.rating_to_stage
    monkeypatch.setattr(
        agg, "rating_to_stage",
        lambda rating, *, sd=None: (seen.append(sd), real(rating, sd=sd))[1],
    )
    e = _sample_entry()
    expected = league_stage_sd(
        {u: r["rating"] for u, r in live_ratings(e).items()})
    resp = agg.build_dashboard(e, year="all", lens="ktc")

    assert [r.window for r in resp.standings].count(None) == 0
    assert seen, "rating_to_stage was never called — the spy proved nothing"
    assert expected is not None
    assert set(seen) == {expected}, (
        f"standings banded on {set(seen)}, not the league's own unit {expected}")


def test_standings_window_is_none_for_a_rated_owner_with_no_outlook():
    """REGRESSION. A departed owner keeps a Franchise Rating (his seasons are
    in the books) but holds no current roster, so refresh writes him no
    `dynasty_outlooks` entry. `owner_view` gates its whole Outlook block on
    that blob, so /owner/{uid} shows him no stage at all. The standings row
    must agree BY CONSTRUCTION — a stage is a claim about a roster's
    competitive window, and there is no roster to make it about.

    Observed on league 1312102152725884928: 16 owners, 16 rated, 12 with
    outlooks — the four departed owners were labelled "Retooling"/"Rebuilding"
    on a page whose own Outlook tab does not exist.

    Deriving `window` from the rating alone dropped the implicit gate the
    previous `(dynasty_outlooks.get(uid) or {}).get("window")` read carried.
    """
    e = _sample_entry()
    # u_bob is rated (he has season_records) but holds no current roster.
    del e.dynasty_outlooks["u_bob"]

    resp = build_dashboard(e, year="all", lens="ktc")
    alice = next(r for r in resp.standings if r.user_id == "u_alice")
    bob = next(r for r in resp.standings if r.user_id == "u_bob")

    assert bob.gm_rating is not None, (
        "fixture is inert: bob must be RATED for this to test anything")
    assert bob.window is None, (
        "a rated owner with no dynasty_outlooks entry has no competitive "
        "window — the owner page shows none, so the standings must not "
        f"invent one (got {bob.window!r})")
    # And the gate is per-owner, not a blanket off-switch: the roster-holding
    # owner still gets his stage.
    assert alice.window is not None
