"""Pure parsers for nflverse CSV exports used by the injury-context feature.

Network fetching lives in ``engine/injury_data.py``; these functions take already-
parsed CSV rows (list of dict[str, str]) so they are trivially unit-testable offline.
"""

from __future__ import annotations

# nflverse rosters_weekly `status_description_abbr` codes that mean "missed to injury".
# R01 = Reserve/Injured (IR); the dominant, unambiguous injury-reserve code. Other reserve
# reasons (retired/suspended/DNR) are excluded; game-day Out / PUP fall to the soft snap signal.
INJURY_RESERVE_CODES = {"R01"}


def _int(v) -> int | None:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def parse_roster_status_rows(rows: list[dict]) -> dict[tuple[str, int, int], dict]:
    """rosters_weekly rows -> {(sleeper_id, season, week): InjuryWeek(high)} for IR (R01) rows."""
    out: dict[tuple[str, int, int], dict] = {}
    for r in rows:
        sid = (r.get("sleeper_id") or "").strip()
        code = (r.get("status_description_abbr") or "").strip()
        season, week = _int(r.get("season")), _int(r.get("week"))
        if not sid or season is None or week is None or code not in INJURY_RESERVE_CODES:
            continue
        out[(sid, season, week)] = {"missed": True, "confidence": "high",
                                    "source": f"roster_ir:{code}"}
    return out


def parse_snap_zero_rows(rows: list[dict]) -> dict[tuple[str, int, int], dict]:
    """snap_counts rows -> {(pfr_id, season, week): InjuryWeek(soft)} for all-zero-snap weeks."""
    out: dict[tuple[str, int, int], dict] = {}
    for r in rows:
        pid = (r.get("pfr_player_id") or "").strip()
        season, week = _int(r.get("season")), _int(r.get("week"))
        if not pid or season is None or week is None:
            continue
        snaps = sum(_int(r.get(k)) or 0 for k in ("offense_snaps", "defense_snaps", "st_snaps"))
        if snaps == 0:
            out[(pid, season, week)] = {"missed": True, "confidence": "soft",
                                        "source": "snap_count:0"}
    return out


def parse_pfr_to_sleeper(rows: list[dict]) -> dict[str, str]:
    """ff_playerids rows -> {pfr_id: sleeper_id} (only rows with both present)."""
    out: dict[str, str] = {}
    for r in rows:
        pfr = (r.get("pfr_id") or "").strip()
        sid = (r.get("sleeper_id") or "").strip()
        if pfr and sid:
            out[pfr] = sid
    return out
