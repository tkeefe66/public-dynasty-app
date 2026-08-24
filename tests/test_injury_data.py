from sleeper_dynasty.engine.injury_data import combine_injury_map


def test_snap_failure_keeps_roster_high():
    from sleeper_dynasty.engine.injury_data import build_injury_map
    ROSTER = [{"sleeper_id": "p1", "season": "2026", "week": "5", "status": "RES", "status_description_abbr": "R01"}]
    def fake_fetch(url):
        if "snap_counts" in url:
            raise RuntimeError("404")
        if "db_playerids" in url:
            return []
        return ROSTER
    m = build_injury_map([2026], current_season=2026, fetch_rows=fake_fetch)
    assert m[("p1", 2026, 5)]["confidence"] == "high"   # roster survived the snap failure


def test_combine_prefers_high_over_soft_and_maps_pfr():
    roster_high = {("p1", 2025, 5): {"missed": True, "confidence": "high", "source": "roster_status:RES"}}
    snap_soft_by_pfr = {
        ("X1", 2025, 5): {"missed": True, "confidence": "soft", "source": "snap_count:0"},
        ("X2", 2025, 7): {"missed": True, "confidence": "soft", "source": "snap_count:0"},
    }
    pfr_to_sleeper = {"X1": "p1", "X2": "p9"}
    out = combine_injury_map(roster_high, snap_soft_by_pfr, pfr_to_sleeper)
    assert out[("p1", 2025, 5)]["confidence"] == "high"
    assert out[("p9", 2025, 7)]["confidence"] == "soft"
    assert ("X2", 2025, 7) not in out
