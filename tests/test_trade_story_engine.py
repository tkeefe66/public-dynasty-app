from datetime import datetime

from sleeper_dynasty.engine.trade_story import is_offseason, build_owner_strategy
from sleeper_dynasty.models.trade import (
    PlayerAsset, PickAsset, Trade, TradeSide, ResolvedTrade,
)


def test_is_offseason_true_in_summer_false_midseason():
    assert is_offseason(datetime(2024, 6, 14)) is True
    assert is_offseason(datetime(2024, 10, 6)) is False
    assert is_offseason(datetime(2024, 2, 1)) is True


def _rt(tx, month, mike_gets_player, season=2024):
    """Mike sends a 1st-round pick, gets a player (win-now). Tom the reverse."""
    pick = PickAsset(season=2025, round=1, original_owner_user_id="u_mike")
    player = PlayerAsset(player_id="p1", name="Bijan Robinson")
    mike = TradeSide(user_id="u_mike",
                     received=[player] if mike_gets_player else [pick],
                     given=[pick] if mike_gets_player else [player])
    tom = TradeSide(user_id="u_tom",
                    received=[pick] if mike_gets_player else [player],
                    given=[player] if mike_gets_player else [pick])
    t = Trade(transaction_id=tx, league_id="L", season=season, week=1,
              traded_at=datetime(season, month, 1),
              sides={"u_mike": mike, "u_tom": tom})
    return ResolvedTrade(trade=t, sides={"u_mike": mike, "u_tom": tom})


def test_owner_strategy_classifies_tilt_and_counts_first_round_sales():
    # Mike sends a 1st and receives a player in both deals (win-now);
    # Tom does the reverse (rebuild).
    resolved = [_rt("t1", 6, True), _rt("t2", 7, True)]
    grades = {
        "t1": {"snapshot_value_swing": {"u_mike": 900.0, "u_tom": -900.0}},
        "t2": {"snapshot_value_swing": {"u_mike": 940.0, "u_tom": -940.0}},
    }
    owners = {"u_mike": "Mike", "u_tom": "Tom"}
    strat = build_owner_strategy(resolved, grades, owners)
    assert strat["u_mike"].tilt == "win-now"
    assert strat["u_mike"].players_for_picks_count == 2
    assert strat["u_mike"].first_round_picks_sent == 2  # Mike SENT the firsts
    assert strat["u_mike"].net_ktc == 1840.0
    assert any("win-now" in t for t in strat["u_mike"].tendencies)
    assert strat["u_tom"].tilt == "rebuild"
    assert strat["u_tom"].first_round_picks_sent == 0
    assert strat["u_tom"].net_ktc == -1840.0


def test_first_round_sale_tendency_fires_after_three_deals():
    # Three win-now deals where Mike ships a 1st each time -> tendency fires.
    resolved = [_rt("t1", 6, True), _rt("t2", 7, True), _rt("t3", 8, True)]
    strat = build_owner_strategy(
        resolved, {}, {"u_mike": "Mike", "u_tom": "Tom"})
    assert any("sold a 1st" in t for t in strat["u_mike"].tendencies)


def test_owner_strategy_as_of_is_point_in_time():
    # Two Mike win-now deals: t1 in June, t2 in July.
    resolved = [_rt("t1", 6, True), _rt("t2", 7, True)]
    owners = {"u_mike": "Mike", "u_tom": "Tom"}
    # as_of == t2's date: only t1 counts (strictly-before excludes t2 itself).
    strat = build_owner_strategy(
        resolved, {}, owners, as_of=datetime(2024, 7, 1))
    assert strat["u_mike"].players_for_picks_count == 1
    assert strat["u_mike"].trades_count == 1
    # as_of == t1's date: no prior trades -> owner has no established pattern.
    strat0 = build_owner_strategy(
        resolved, {}, owners, as_of=datetime(2024, 6, 1))
    assert "u_mike" not in strat0
    # No cutoff: full history.
    full = build_owner_strategy(resolved, {}, owners)
    assert full["u_mike"].players_for_picks_count == 2


# tests/test_trade_story_engine.py  (append)
from sleeper_dynasty.engine.trade_story import build_player_arc


def test_player_arc_season_high_playoff_split_and_decisive():
    # Mike (roster 1, league L season 2024) owns p_bijan after a week-1 trade.
    rt = _rt("t1", 9, True)  # in-season Sept trade, week 1
    matchups = {
        # week 5 regular: 10 pts, team wins by 4 -> decisive (10 > 4)
        ("L", 5, 1): {"players": ["p1"], "starters": ["p1"],
                      "players_points": {"p1": 10.0},
                      "team_points": 100.0, "opponent_points": 96.0},
        # week 9 regular: 20 pts, loss
        ("L", 9, 1): {"players": ["p1"], "starters": ["p1"],
                      "players_points": {"p1": 20.0},
                      "team_points": 90.0, "opponent_points": 110.0},
        # week 15 playoff: 34 pts season high
        ("L", 15, 1): {"players": ["p1"], "starters": ["p1"],
                       "players_points": {"p1": 34.0},
                       "team_points": 130.0, "opponent_points": 120.0},
        # week 16 benched (rostered, not started)
        ("L", 16, 1): {"players": ["p1"], "starters": [],
                       "players_points": {"p1": 5.0},
                       "team_points": 100.0, "opponent_points": 99.0},
    }
    arc = build_player_arc(
        pid="p1", player_name="Bijan Robinson", position="RB",
        owner_uid="u_mike", rt=rt, matchups=matchups,
        roster_to_user_by_league={"L": {1: "u_mike"}},
        playoff_weeks_by_league={"L": 15},
        league_season_by_id={"L": 2024},
    )
    assert arc.starter_weeks == 3
    assert arc.season_high_points == 34.0 and arc.season_high_week == 15
    assert arc.season_high_is_playoff is True
    assert arc.decisive_starts == 2  # week 5 and week 15 are both decisive wins
    assert arc.benched_weeks == 1
    # regular avg = (10+20)/2 = 15; playoff avg = 34; pct = +126.7
    assert round(arc.playoff_vs_regular_pct, 1) == 126.7
    # He played for this owner, so not flipped; phantom = his started points.
    assert arc.flipped is False
    assert arc.phantom_points == 64.0  # 10 + 20 + 34 (wk16 benched, excluded)


def test_player_arc_flags_a_flipped_player():
    # Mike RECEIVES p1 but never rosters him; p1 plays on roster 2 (someone
    # else) every week -> Mike flipped him before he suited up.
    rt = _rt("t1", 9, True)
    matchups = {
        ("L", 5, 2): {"players": ["p1"], "starters": ["p1"],
                      "players_points": {"p1": 18.0},
                      "team_points": 100.0, "opponent_points": 90.0},
        ("L", 6, 2): {"players": ["p1"], "starters": ["p1"],
                      "players_points": {"p1": 22.0},
                      "team_points": 100.0, "opponent_points": 90.0},
    }
    arc = build_player_arc(
        pid="p1", player_name="Saquon Barkley", position="RB",
        owner_uid="u_mike", rt=rt, matchups=matchups,
        roster_to_user_by_league={"L": {1: "u_mike", 2: "u_other"}},
        playoff_weeks_by_league={"L": 15},
        league_season_by_id={"L": 2024},
    )
    assert arc.starter_weeks == 0 and arc.benched_weeks == 0
    assert arc.points_total == 0.0     # nothing FOR Mike
    assert arc.phantom_points == 40.0  # 18 + 22 scored elsewhere
    assert arc.flipped is True


from sleeper_dynasty.engine.trade_story import build_trade_story_facts
from sleeper_dynasty.models.trade_story import OwnerStrategyFacts


def test_build_trade_story_facts_picks_winner_and_offseason():
    rt = _rt("t1", 6, True)  # June (offseason), Mike receives the player
    grade = {
        "snapshot_value_swing": {"u_mike": 1840.0, "u_tom": -1840.0},
        "production_total": {"u_mike": 41.2, "u_tom": -41.2},
        "production_regular": {"u_mike": 30.0, "u_tom": -30.0},
    }
    owner_strategy = {
        "u_mike": OwnerStrategyFacts("u_mike", "Mike", 12, -4, 7, 2, 1,
                                     "win-now", 3200.0, []),
        "u_tom": OwnerStrategyFacts("u_tom", "Tom", 9, 5, 1, 4, 3,
                                    "rebuild", -1800.0, []),
    }
    facts = build_trade_story_facts(
        rt=rt, grade=grade, owner_strategy=owner_strategy,
        owners_display={"u_mike": "Mike", "u_tom": "Tom"},
        matchups={}, roster_to_user_by_league={}, playoff_weeks_by_league={},
        league_season_by_id={"L": 2024},
        positions={"p1": "RB"},
    )
    assert facts.is_offseason is True
    assert facts.winner_user_id == "u_mike"
    assert facts.margins["ktc"] == 1840.0
    assert 0.73 < facts.lopsidedness <= 0.74  # 1840/2500
    assert facts.owners["u_tom"]["tilt"] == "rebuild"
    mike_side = next(s for s in facts.sides if s["user_id"] == "u_mike")
    assert mike_side["player_arcs"][0]["player"] == "Bijan Robinson"


def _pick_facts_inputs(flip: bool):
    """A trade where u_a receives a 2026 1st (slot drafted Makai Lemon). When
    `flip` is True a later trade has u_a flip that pick away as a pick."""
    recv = PickAsset(season=2026, round=1, original_owner_user_id="u_x",
                     drafted_player_id="ML", drafted_player_name="Makai Lemon")
    a_side = TradeSide(user_id="u_a", received=[recv], given=[])
    b_side = TradeSide(user_id="u_b", received=[], given=[recv])
    t1 = Trade(transaction_id="t1", league_id="L", season=2025, week=10,
               traded_at=datetime(2025, 11, 7),
               sides={"u_a": a_side, "u_b": b_side})
    rt = ResolvedTrade(trade=t1, sides={"u_a": a_side, "u_b": b_side})

    def adict(a):
        return {"season": a.season, "round": a.round,
                "original_owner_user_id": a.original_owner_user_id,
                "drafted_player_id": a.drafted_player_id,
                "drafted_player_name": a.drafted_player_name}
    dicts = [{"trade": {"transaction_id": "t1", "traded_at": "2025-11-07T00:00:00"},
              "sides": {"u_a": {"user_id": "u_a", "received": [adict(recv)], "given": []},
                        "u_b": {"user_id": "u_b", "received": [], "given": [adict(recv)]}}}]
    if flip:
        swap = {"season": 2026, "round": 1, "original_owner_user_id": "u_y",
                "drafted_player_id": "JP", "drafted_player_name": "Jadarian Price"}
        dicts.append({"trade": {"transaction_id": "t2", "traded_at": "2026-05-02T00:00:00"},
                      "sides": {"u_a": {"user_id": "u_a", "received": [swap], "given": [adict(recv)]},
                                "u_c": {"user_id": "u_c", "received": [adict(recv)], "given": [swap]}}})
    return rt, dicts


def _build_facts(rt, dicts=None):
    return build_trade_story_facts(
        rt=rt, grade={}, owner_strategy={},
        owners_display={"u_a": "A", "u_b": "B"},
        matchups={}, roster_to_user_by_league={}, playoff_weeks_by_league={},
        league_season_by_id={"L": 2025}, positions={}, resolved_trades=dicts)


def test_pick_outcome_suppresses_draftee_and_reports_realized_terminal():
    # u_a flipped the pick before the draft — never realized Makai Lemon, but
    # ultimately landed Jadarian Price through the swap.
    rt, dicts = _pick_facts_inputs(flip=True)
    facts = _build_facts(rt, dicts)
    a = next(s for s in facts.sides if s["user_id"] == "u_a")
    po = a["pick_outcomes"][0]
    assert po["became_player"] is None
    assert po["flipped_for"] == "Jadarian Price"


def test_pick_outcome_keeps_draftee_when_pick_kept():
    # u_a held the pick (no later flip) — the draftee claim stands, no flip.
    rt, dicts = _pick_facts_inputs(flip=False)
    facts = _build_facts(rt, dicts)
    a = next(s for s in facts.sides if s["user_id"] == "u_a")
    po = a["pick_outcomes"][0]
    assert po["became_player"] == "Makai Lemon"
    assert po["flipped_for"] is None


def test_pick_outcome_draftee_kept_without_lineage_context():
    # Backward-compat: no resolved_trades passed -> unchanged behavior.
    rt, _ = _pick_facts_inputs(flip=True)
    facts = _build_facts(rt, None)
    a = next(s for s in facts.sides if s["user_id"] == "u_a")
    assert a["pick_outcomes"][0]["became_player"] == "Makai Lemon"
    assert a["pick_outcomes"][0]["flipped_for"] is None


def test_player_arc_flags_drafted_then_dropped_before_season():
    # Mike RECEIVES p1 (think: a draftee) but never rosters him in any matchup,
    # and he is NOT in current_holders -> cut before he ever played.
    rt = _rt("t1", 9, True)
    arc = build_player_arc(
        pid="p1", player_name="Cut Guy", position="WR",
        owner_uid="u_mike", rt=rt, matchups={},
        roster_to_user_by_league={"L": {1: "u_mike"}},
        playoff_weeks_by_league={"L": 15},
        league_season_by_id={"L": 2024},
        current_holders={},  # nobody holds him -> dropped
    )
    assert arc.dropped is True
    assert arc.flipped is False
    assert arc.last_rostered_week is None
    assert arc.starter_weeks == 0 and arc.benched_weeks == 0


def test_player_arc_kept_player_not_dropped_and_tracks_last_week():
    rt = _rt("t1", 9, True)
    matchups = {
        ("L", 5, 1): {"players": ["p1"], "starters": ["p1"],
                      "players_points": {"p1": 10.0},
                      "team_points": 100.0, "opponent_points": 96.0},
        ("L", 8, 1): {"players": ["p1"], "starters": [],  # benched wk 8
                      "players_points": {"p1": 4.0},
                      "team_points": 100.0, "opponent_points": 96.0},
    }
    arc = build_player_arc(
        pid="p1", player_name="Kept Guy", position="RB",
        owner_uid="u_mike", rt=rt, matchups=matchups,
        roster_to_user_by_league={"L": {1: "u_mike"}},
        playoff_weeks_by_league={"L": 15},
        league_season_by_id={"L": 2024},
        current_holders={"p1": "u_mike"},  # still held -> not dropped
    )
    assert arc.dropped is False
    assert arc.last_rostered_week == 8  # appeared (started wk5, benched wk8)


def test_player_arc_flipped_beats_dropped():
    # Received, never rostered here, but scored elsewhere -> flipped, not cut.
    rt = _rt("t1", 9, True)
    matchups = {
        ("L", 5, 2): {"players": ["p1"], "starters": ["p1"],
                      "players_points": {"p1": 18.0},
                      "team_points": 100.0, "opponent_points": 90.0},
    }
    arc = build_player_arc(
        pid="p1", player_name="Flipped Guy", position="RB",
        owner_uid="u_mike", rt=rt, matchups=matchups,
        roster_to_user_by_league={"L": {1: "u_mike", 2: "u_other"}},
        playoff_weeks_by_league={"L": 15},
        league_season_by_id={"L": 2024},
        current_holders={},  # not held, but he was flipped
    )
    assert arc.flipped is True
    assert arc.dropped is False


from sleeper_dynasty.models.trade_story import facts_hash


def _build_facts_ch(rt, dicts, current_holders, matchups=None):
    return build_trade_story_facts(
        rt=rt, grade={}, owner_strategy={},
        owners_display={"u_a": "A", "u_b": "B"},
        matchups=matchups or {}, roster_to_user_by_league={"L": {1: "u_a"}},
        playoff_weeks_by_league={"L": 15},
        league_season_by_id={"L": 2025}, positions={},
        resolved_trades=dicts, current_holders=current_holders)


def test_kept_pick_draftee_is_terminal_state_kept():
    # u_a held the pick, drafted Makai Lemon, and still rosters him.
    rt, dicts = _pick_facts_inputs(flip=False)
    facts = _build_facts_ch(rt, dicts, current_holders={"ML": "u_a"})
    a = next(s for s in facts.sides if s["user_id"] == "u_a")
    po = a["pick_outcomes"][0]
    assert po["became_player"] == "Makai Lemon"
    assert po["terminal_state"] == "kept"
    assert po["dropped_before_week"] is None


def test_drafted_then_dropped_pick_sets_dropped_state_and_changes_hash():
    # Same trade, but u_a no longer holds Makai Lemon (cut, never played).
    rt, dicts = _pick_facts_inputs(flip=False)
    kept = _build_facts_ch(rt, dicts, current_holders={"ML": "u_a"})
    dropped = _build_facts_ch(rt, dicts, current_holders={})  # ML not held

    a = next(s for s in dropped.sides if s["user_id"] == "u_a")
    po = a["pick_outcomes"][0]
    assert po["terminal_state"] == "dropped"
    assert po["dropped_before_week"] == 0  # never played a snap

    # The drop must change the packet so the story re-fires.
    assert facts_hash(kept) != facts_hash(dropped)


def test_realized_players_lists_terminal_player_from_a_pick():
    # realized_players is built from terminal_assets (the bounded walk), so the
    # draftee shows up by NAME regardless of matchup production.
    rt, dicts = _pick_facts_inputs(flip=False)
    facts = _build_facts_ch(rt, dicts, current_holders={"ML": "u_a"})
    a = next(s for s in facts.sides if s["user_id"] == "u_a")
    names = [p["player"] for p in a["realized_players"]]
    assert "Makai Lemon" in names


def test_direct_received_player_kept_is_not_dropped():
    # Mike directly receives p1 and still rosters him -> dropped must be False.
    rt = _rt("t1", 9, True)
    facts = build_trade_story_facts(
        rt=rt, grade={}, owner_strategy={},
        owners_display={"u_mike": "Mike", "u_tom": "Tom"},
        matchups={}, roster_to_user_by_league={"L": {1: "u_mike"}},
        playoff_weeks_by_league={"L": 15},
        league_season_by_id={"L": 2024}, positions={"p1": "RB"},
        current_holders={"p1": "u_mike"},
    )
    mike = next(s for s in facts.sides if s["user_id"] == "u_mike")
    assert mike["player_arcs"][0]["dropped"] is False


def test_direct_received_player_cut_is_dropped():
    # Mike directly receives p1, never plays him, and no longer holds him -> cut.
    rt = _rt("t1", 9, True)
    facts = build_trade_story_facts(
        rt=rt, grade={}, owner_strategy={},
        owners_display={"u_mike": "Mike", "u_tom": "Tom"},
        matchups={}, roster_to_user_by_league={"L": {1: "u_mike"}},
        playoff_weeks_by_league={"L": 15},
        league_season_by_id={"L": 2024}, positions={"p1": "RB"},
        current_holders={},  # not held anywhere
    )
    mike = next(s for s in facts.sides if s["user_id"] == "u_mike")
    assert mike["player_arcs"][0]["dropped"] is True


def test_story_winner_and_margin_use_realized_received_ktc_not_snapshot():
    # The screenshot bug: snapshot_value_swing (mark-to-market) credits the
    # dropped pick at full market and screams "+2600 heist", but realized
    # received value (dropped -> 0) is near-even. The verdict must follow the
    # realized number the receipts show, not the snapshot diagnostic.
    rt = _rt("t1", 5, True)  # offseason May trade
    grade = {
        "snapshot_value_swing": {"u_tom": 2600.0, "u_mike": -2600.0},
        "received_ktc": {"u_tom": 3508.0, "u_mike": 3291.0},
    }
    facts = build_trade_story_facts(
        rt=rt, grade=grade, owner_strategy={},
        owners_display={"u_mike": "Mike", "u_tom": "Tom"},
        matchups={}, roster_to_user_by_league={}, playoff_weeks_by_league={},
        league_season_by_id={"L": 2024}, positions={})
    assert facts.winner_user_id == "u_tom"            # realized winner
    assert round(facts.margins["ktc"], 0) == 217.0    # realized gap, not 2600
    assert facts.lopsidedness < 0.3                   # close, not a heist


def test_story_winner_flips_to_realized_when_snapshot_disagrees():
    # Snapshot favors Mike; realized (what each side actually kept) favors Tom.
    rt = _rt("t1", 5, True)
    grade = {
        "snapshot_value_swing": {"u_mike": 1500.0, "u_tom": -1500.0},
        "received_ktc": {"u_mike": 1000.0, "u_tom": 4000.0},
    }
    facts = build_trade_story_facts(
        rt=rt, grade=grade, owner_strategy={},
        owners_display={"u_mike": "Mike", "u_tom": "Tom"},
        matchups={}, roster_to_user_by_league={}, playoff_weeks_by_league={},
        league_season_by_id={"L": 2024}, positions={})
    assert facts.winner_user_id == "u_tom"
    assert round(facts.margins["ktc"], 0) == 3000.0   # 4000 - 1000


def test_story_falls_back_to_snapshot_when_no_realized_value():
    # CLI path / no snapshot store: received_ktc absent -> use the swing.
    rt = _rt("t1", 5, True)
    grade = {"snapshot_value_swing": {"u_mike": 1840.0, "u_tom": -1840.0}}
    facts = build_trade_story_facts(
        rt=rt, grade=grade, owner_strategy={},
        owners_display={"u_mike": "Mike", "u_tom": "Tom"},
        matchups={}, roster_to_user_by_league={}, playoff_weeks_by_league={},
        league_season_by_id={"L": 2024}, positions={})
    assert facts.winner_user_id == "u_mike"
    assert round(facts.margins["ktc"], 0) == 1840.0


def test_given_summary_player_with_position():
    # _rt("t1", 9, True) -> Mike receives player p1 (Bijan Robinson), Tom receives a 2025 1st pick.
    # So: Tom's given = [PlayerAsset(p1, "Bijan Robinson")], Mike's given = [PickAsset(2025, round=1)]
    rt = _rt("t1", 9, True)
    facts = build_trade_story_facts(
        rt=rt, grade={}, owner_strategy={},
        owners_display={"u_mike": "Mike", "u_tom": "Tom"},
        matchups={}, roster_to_user_by_league={}, playoff_weeks_by_league={},
        league_season_by_id={"L": 2024}, positions={"p1": "RB"})
    tom = next(s for s in facts.sides if s["user_id"] == "u_tom")
    mike = next(s for s in facts.sides if s["user_id"] == "u_mike")
    assert tom["given_summary"] == "Bijan Robinson (RB)"
    assert mike["given_summary"] == "2025 1st pick"


def test_received_summary_mirrors_given_summary():
    # Mike receives Bijan (a player), Tom receives a 2025 1st pick.
    rt = _rt("t1", 9, True)
    facts = build_trade_story_facts(
        rt=rt, grade={}, owner_strategy={},
        owners_display={"u_mike": "Mike", "u_tom": "Tom"},
        matchups={}, roster_to_user_by_league={}, playoff_weeks_by_league={},
        league_season_by_id={"L": 2024}, positions={"p1": "RB"})
    mike = next(s for s in facts.sides if s["user_id"] == "u_mike")
    tom = next(s for s in facts.sides if s["user_id"] == "u_tom")
    assert mike["received_summary"] == "Bijan Robinson (RB)"
    assert mike["given_summary"] == "2025 1st pick"
    assert tom["received_summary"] == "2025 1st pick"
    assert tom["given_summary"] == "Bijan Robinson (RB)"


def test_this_trade_tilt_win_now_and_rebuild():
    # Mike receives the player + sends a pick (win-now); Tom the reverse.
    rt = _rt("t1", 9, True)
    facts = build_trade_story_facts(
        rt=rt, grade={}, owner_strategy={},
        owners_display={"u_mike": "Mike", "u_tom": "Tom"},
        matchups={}, roster_to_user_by_league={}, playoff_weeks_by_league={},
        league_season_by_id={"L": 2024}, positions={"p1": "RB"})
    mike = next(s for s in facts.sides if s["user_id"] == "u_mike")
    tom = next(s for s in facts.sides if s["user_id"] == "u_tom")
    assert mike["this_trade_tilt"] == "win-now"
    assert tom["this_trade_tilt"] == "rebuild"


def test_fits_career_tilt_breaks_when_trade_opposes_pattern():
    # THE BUG: Tom is a career rebuilder, but in THIS trade he RECEIVED the
    # player and SENT picks (a win-now move). That breaks his pattern; the
    # packet must say so deterministically so the story never inverts it into
    # "he sold the receiver for picks".
    rt = _rt("t1", 9, False)  # Tom gets the player, Mike gets the pick
    owner_strategy = {
        "u_mike": OwnerStrategyFacts("u_mike", "Mike", 9, 5, 1, 4, 3,
                                     "rebuild", -1800.0, []),
        "u_tom": OwnerStrategyFacts("u_tom", "Tom", 12, -4, 7, 2, 1,
                                    "rebuild", 3200.0, []),
    }
    facts = build_trade_story_facts(
        rt=rt, grade={}, owner_strategy=owner_strategy,
        owners_display={"u_mike": "Mike", "u_tom": "Tom"},
        matchups={}, roster_to_user_by_league={}, playoff_weeks_by_league={},
        league_season_by_id={"L": 2024}, positions={"p1": "RB"})
    tom = next(s for s in facts.sides if s["user_id"] == "u_tom")
    assert tom["this_trade_tilt"] == "win-now"
    assert tom["fits_career_tilt"] == "breaks"


def test_fits_career_tilt_fits_when_aligned():
    # Mike is a career win-now buyer; this trade is win-now too -> fits.
    rt = _rt("t1", 9, True)  # Mike gets the player (win-now)
    owner_strategy = {
        "u_mike": OwnerStrategyFacts("u_mike", "Mike", 12, -4, 7, 2, 1,
                                     "win-now", 3200.0, []),
    }
    facts = build_trade_story_facts(
        rt=rt, grade={}, owner_strategy=owner_strategy,
        owners_display={"u_mike": "Mike", "u_tom": "Tom"},
        matchups={}, roster_to_user_by_league={}, playoff_weeks_by_league={},
        league_season_by_id={"L": 2024}, positions={"p1": "RB"})
    mike = next(s for s in facts.sides if s["user_id"] == "u_mike")
    assert mike["fits_career_tilt"] == "fits"


def test_fits_career_tilt_na_without_established_pattern():
    # No owner_strategy entry (e.g. the owner's first deal) -> nothing to
    # compare against, so neither fits nor breaks.
    rt = _rt("t1", 9, True)
    facts = build_trade_story_facts(
        rt=rt, grade={}, owner_strategy={},
        owners_display={"u_mike": "Mike", "u_tom": "Tom"},
        matchups={}, roster_to_user_by_league={}, playoff_weeks_by_league={},
        league_season_by_id={"L": 2024}, positions={"p1": "RB"})
    mike = next(s for s in facts.sides if s["user_id"] == "u_mike")
    assert mike["fits_career_tilt"] == "n/a"


def test_given_summary_player_no_position():
    rt = _rt("t1", 9, True)
    facts = build_trade_story_facts(
        rt=rt, grade={}, owner_strategy={},
        owners_display={"u_mike": "Mike", "u_tom": "Tom"},
        matchups={}, roster_to_user_by_league={}, playoff_weeks_by_league={},
        league_season_by_id={"L": 2024}, positions={})
    tom = next(s for s in facts.sides if s["user_id"] == "u_tom")
    assert tom["given_summary"] == "Bijan Robinson"


def test_given_summary_ordinals():
    from datetime import datetime
    from sleeper_dynasty.models.trade import PickAsset, Trade, TradeSide, ResolvedTrade
    p2 = PickAsset(season=2026, round=2, original_owner_user_id="u_a")
    p4 = PickAsset(season=2027, round=4, original_owner_user_id="u_a")
    p5 = PickAsset(season=2027, round=5, original_owner_user_id="u_a")
    a_side = TradeSide(user_id="u_a", received=[], given=[p2, p4, p5])
    b_side = TradeSide(user_id="u_b", received=[p2, p4, p5], given=[])
    t = Trade(transaction_id="t1", league_id="L", season=2025, week=1,
              traded_at=datetime(2025, 6, 1),
              sides={"u_a": a_side, "u_b": b_side})
    rt = ResolvedTrade(trade=t, sides={"u_a": a_side, "u_b": b_side})
    facts = build_trade_story_facts(
        rt=rt, grade={}, owner_strategy={},
        owners_display={"u_a": "A", "u_b": "B"},
        matchups={}, roster_to_user_by_league={}, playoff_weeks_by_league={},
        league_season_by_id={}, positions={})
    a = next(s for s in facts.sides if s["user_id"] == "u_a")
    assert a["given_summary"] == "2026 2nd pick · 2027 4th pick · 2027 5th pick"
    b = next(s for s in facts.sides if s["user_id"] == "u_b")
    assert b["given_summary"] == ""


def test_season_underway_false_when_no_post_trade_games():
    # A trade whose season has not started: no post-trade matchups exist, so no
    # received asset has taken the field. season_underway must be False so the
    # story writer never reads the all-zero arcs as "never played".
    rt = _rt("t1", 6, True)  # June (offseason), 2024 season not yet underway here
    facts = build_trade_story_facts(
        rt=rt, grade={}, owner_strategy={},
        owners_display={"u_mike": "Mike", "u_tom": "Tom"},
        matchups={}, roster_to_user_by_league={"L": {1: "u_mike"}},
        playoff_weeks_by_league={"L": 15},
        league_season_by_id={"L": 2024}, positions={"p1": "RB"},
    )
    assert facts.season_underway is False
    assert facts.to_dict()["season_underway"] is False


def test_season_underway_true_when_post_trade_games_exist():
    # Same trade, but post-trade games have been played -> the season is underway
    # and a 0 for a player is meaningful, so season_underway is True.
    rt = _rt("t1", 9, True)  # in-season Sept trade, week 1, season 2024
    matchups = {
        ("L", 5, 1): {"players": ["p1"], "starters": ["p1"],
                      "players_points": {"p1": 10.0},
                      "team_points": 100.0, "opponent_points": 96.0},
        ("L", 9, 1): {"players": ["p1"], "starters": ["p1"],
                      "players_points": {"p1": 20.0},
                      "team_points": 90.0, "opponent_points": 110.0},
    }
    facts = build_trade_story_facts(
        rt=rt, grade={}, owner_strategy={},
        owners_display={"u_mike": "Mike", "u_tom": "Tom"},
        matchups=matchups, roster_to_user_by_league={"L": {1: "u_mike"}},
        playoff_weeks_by_league={"L": 15},
        league_season_by_id={"L": 2024}, positions={"p1": "RB"},
    )
    assert facts.season_underway is True
