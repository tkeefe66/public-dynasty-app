from sleeper_dynasty.api.nflverse import (
    parse_roster_status_rows, parse_snap_zero_rows, parse_pfr_to_sleeper, INJURY_RESERVE_CODES,
)


def test_injury_reserve_codes():
    assert INJURY_RESERVE_CODES == {"R01"}  # Reserve/Injured (IR)


def test_parse_roster_status_uses_r01_description():
    rows = [
        {"sleeper_id": "p1", "season": "2025", "week": "5", "status": "RES", "status_description_abbr": "R01"},  # IR -> injury
        {"sleeper_id": "p2", "season": "2025", "week": "5", "status": "RES", "status_description_abbr": "R05"},  # Retired -> NOT injury
        {"sleeper_id": "p3", "season": "2025", "week": "6", "status": "ACT", "status_description_abbr": ""},     # active -> no
        {"sleeper_id": "",   "season": "2025", "week": "5", "status": "RES", "status_description_abbr": "R01"},  # no sleeper id -> skip
    ]
    out = parse_roster_status_rows(rows)
    assert out[("p1", 2025, 5)] == {"missed": True, "confidence": "high", "source": "roster_ir:R01"}
    assert ("p2", 2025, 5) not in out      # retired reserve is not an injury miss
    assert ("p3", 2025, 6) not in out
    assert all(k[0] for k in out)


def test_parse_snap_zero_rows_by_pfr():
    rows = [
        {"pfr_player_id": "X1", "season": "2025", "week": "5", "offense_snaps": "0", "defense_snaps": "0", "st_snaps": "0"},
        {"pfr_player_id": "X1", "season": "2025", "week": "6", "offense_snaps": "12", "defense_snaps": "0", "st_snaps": "0"},
    ]
    out = parse_snap_zero_rows(rows)
    assert ("X1", 2025, 5) in out
    assert ("X1", 2025, 6) not in out


def test_parse_pfr_to_sleeper():
    rows = [
        {"pfr_id": "X1", "sleeper_id": "p1"},
        {"pfr_id": "X2", "sleeper_id": ""},
        {"pfr_id": "",   "sleeper_id": "p3"},
    ]
    assert parse_pfr_to_sleeper(rows) == {"X1": "p1"}
