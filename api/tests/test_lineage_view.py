# tests/test_lineage_view.py
from app.services.chain_cache import ChainCacheEntry
from app.services.trade_view import build_trade_detail


def _entry():
    rt = {"trade": {"transaction_id": "t1", "traded_at": "2025-08-20T00:00:00",
                    "week": 1, "season": 2025, "league_id": "L"},
          "sides": {"u_a": {"user_id": "u_a", "received": [{"player_id": "4866", "name": "Saquon Barkley", "via_pick": None}], "given": []},
                    "u_b": {"user_id": "u_b", "received": [], "given": [{"player_id": "4866", "name": "Saquon Barkley", "via_pick": None}]}}}
    return ChainCacheEntry(
        league_id="L", chain=[], resolved_trades=[rt], grades={},
        owners={"u_a": {"owner_name": "A"}, "u_b": {"owner_name": "B"}},
        playoff_weeks_by_league={}, roster_to_user_by_league={},
        league_name_by_id={"L": "Bros"}, league_season_by_id={"L": 2025},
        cached_at="now", current_holders={"4866": "u_a"})


def test_detail_includes_lineage():
    resp = build_trade_detail(_entry(), "t1")
    assert "u_a" in resp.lineage
    assert resp.lineage["u_a"][0].label == "Saquon Barkley"
    assert resp.lineage["u_a"][0].terminal_state == "on_roster"


def _pick(season, rnd, orig, drafted_id=None, drafted_name=None):
    return {"season": season, "round": rnd, "original_owner_user_id": orig,
            "drafted_player_id": drafted_id, "drafted_player_name": drafted_name}


def _flipped_pick_entry():
    # u_a received a 2026 1st (slot drafted Makai Lemon) but flipped it as a
    # pick to u_c before the draft, swapping into a 2026 1st that became
    # Jadarian Price. The breakdown row label carries the "(Makai Lemon)"
    # annotation from the slot resolution.
    ml = _pick(2026, 1, "u_x", drafted_id="ML", drafted_name="Makai Lemon")
    jp = _pick(2026, 1, "u_y", drafted_id="JP", drafted_name="Jadarian Price")
    t1 = {"trade": {"transaction_id": "t1", "traded_at": "2025-11-07T00:00:00",
                    "week": 10, "season": 2025, "league_id": "L"},
          "sides": {"u_a": {"user_id": "u_a", "received": [ml], "given": []},
                    "u_b": {"user_id": "u_b", "received": [], "given": [ml]}}}
    t2 = {"trade": {"transaction_id": "t2", "traded_at": "2026-05-02T00:00:00",
                    "week": 0, "season": 2026, "league_id": "L"},
          "sides": {"u_a": {"user_id": "u_a", "received": [jp], "given": [ml]},
                    "u_c": {"user_id": "u_c", "received": [ml], "given": [jp]}}}
    grades = {"t1": {"breakdown": {"u_a": [
        {"label": "2026 1st (Makai Lemon)", "kind": "pick", "player_id": None,
         "ktc": 4866.0, "production_total": 0.0, "production_regular": 0.0,
         "production_playoff": 0.0, "production_toilet": 0.0}]}}}
    return ChainCacheEntry(
        league_id="L", chain=[], resolved_trades=[t1, t2], grades=grades,
        owners={"u_a": {"owner_name": "A"}, "u_b": {"owner_name": "B"},
                "u_c": {"owner_name": "C"}},
        playoff_weeks_by_league={}, roster_to_user_by_league={},
        league_name_by_id={"L": "Bros"}, league_season_by_id={"L": 2025},
        cached_at="now", current_holders={})


def test_flipped_as_pick_strips_draftee_annotation():
    resp = build_trade_detail(_flipped_pick_entry(), "t1")
    side = next(s for s in resp.sides if s.user_id == "u_a")
    row = side.breakdown[0]
    assert row.flip is not None and row.flip.to_owner == "C"
    assert row.label == "2026 1st"  # "(Makai Lemon)" dropped — u_a never realized him


def _resolution_flip_entry():
    # Real-data shape: u_a received the 2024 1st (slot drafted Marvin Harrison)
    # then flipped it before the draft for Bijan Robinson. That flip is the
    # pick's RESOLUTION trade, so the resolver models the flipped asset as the
    # drafted PLAYER carrying via_pick (not a bare pick) — the exact case the
    # pick-id flip lookup misses. u_a never rostered Marvin, so the row's
    # "(Marvin Harrison)" annotation must be dropped.
    mh_pick = _pick(2024, 1, "u_x", drafted_id="MH", drafted_name="Marvin Harrison")
    mh_via = {"player_id": "MH", "name": "Marvin Harrison",
              "via_pick": _pick(2024, 1, "u_x")}
    bijan = {"player_id": "BJ", "name": "Bijan Robinson", "via_pick": None}
    t1 = {"trade": {"transaction_id": "t1", "traded_at": "2023-08-09T00:00:00",
                    "week": 1, "season": 2023, "league_id": "L"},
          "sides": {"u_a": {"user_id": "u_a", "received": [mh_pick], "given": []},
                    "u_b": {"user_id": "u_b", "received": [], "given": [mh_pick]}}}
    t2 = {"trade": {"transaction_id": "t2", "traded_at": "2023-11-18T00:00:00",
                    "week": 11, "season": 2023, "league_id": "L"},
          "sides": {"u_a": {"user_id": "u_a", "received": [bijan], "given": [mh_via]},
                    "u_c": {"user_id": "u_c", "received": [mh_via], "given": [bijan]}}}
    grades = {"t1": {"breakdown": {"u_a": [
        {"label": "2024 1st (Marvin Harrison)", "kind": "pick", "player_id": None,
         "ktc": 9998.0, "production_total": 0.0, "production_regular": 0.0,
         "production_playoff": 0.0, "production_toilet": 0.0}]}}}
    return ChainCacheEntry(
        league_id="L", chain=[], resolved_trades=[t1, t2], grades=grades,
        owners={"u_a": {"owner_name": "A"}, "u_b": {"owner_name": "B"},
                "u_c": {"owner_name": "C"}},
        playoff_weeks_by_league={}, roster_to_user_by_league={},
        league_name_by_id={"L": "Bros"}, league_season_by_id={"L": 2023},
        cached_at="now", current_holders={"BJ": "u_a"})


def test_resolution_trade_flip_strips_draftee_annotation():
    resp = build_trade_detail(_resolution_flip_entry(), "t1")
    side = next(s for s in resp.sides if s.user_id == "u_a")
    row = side.breakdown[0]
    assert row.flip is not None and row.flip.to_owner == "C"
    assert row.label == "2024 1st"  # "(Marvin Harrison)" dropped — drafted by u_c


def _player_flip_entry():
    # u_a received Nico Collins, then flipped him to u_c for Stefon Diggs, who is
    # currently on u_a's roster. The became line for Diggs should carry his
    # roster status (on_roster), just like a kept asset does.
    nc = {"player_id": "NC", "name": "Nico Collins", "via_pick": None}
    sd = {"player_id": "SD", "name": "Stefon Diggs", "via_pick": None}
    t1 = {"trade": {"transaction_id": "t1", "traded_at": "2024-08-01T00:00:00",
                    "week": 1, "season": 2024, "league_id": "L"},
          "sides": {"u_a": {"user_id": "u_a", "received": [nc], "given": []},
                    "u_b": {"user_id": "u_b", "received": [], "given": [nc]}}}
    t2 = {"trade": {"transaction_id": "t2", "traded_at": "2024-10-08T00:00:00",
                    "week": 5, "season": 2024, "league_id": "L"},
          "sides": {"u_a": {"user_id": "u_a", "received": [sd], "given": [nc]},
                    "u_c": {"user_id": "u_c", "received": [nc], "given": [sd]}}}
    grades = {"t1": {"breakdown": {"u_a": [
        {"label": "Nico Collins", "kind": "player", "player_id": "NC",
         "ktc": 5000.0, "production_total": 0.0, "production_regular": 0.0,
         "production_playoff": 0.0, "production_toilet": 0.0}]}}}
    became = {"t1": {"grades": {"u_a": {"breakdown": [
        {"label": "Stefon Diggs", "kind": "player", "player_id": "SD",
         "ktc": 2139.0, "production_total": 220.6, "production_regular": 192.2,
         "production_playoff": 0.0, "production_toilet": 28.4}]}}}}
    return ChainCacheEntry(
        league_id="L", chain=[], resolved_trades=[t1, t2], grades=grades,
        became_grades=became,
        owners={"u_a": {"owner_name": "A"}, "u_b": {"owner_name": "B"},
                "u_c": {"owner_name": "C"}},
        playoff_weeks_by_league={}, roster_to_user_by_league={},
        league_name_by_id={"L": "Bros"}, league_season_by_id={"L": 2024},
        cached_at="now", current_holders={"SD": "u_a"})


def test_flipped_player_became_carries_terminal_state():
    resp = build_trade_detail(_player_flip_entry(), "t1")
    side = next(s for s in resp.sides if s.user_id == "u_a")
    row = side.breakdown[0]
    assert row.flip is not None and row.flip.to_owner == "C"
    diggs = next(b for b in row.flip.became if b.label == "Stefon Diggs")
    assert diggs.terminal_state == "on_roster"  # currently rostered by u_a
