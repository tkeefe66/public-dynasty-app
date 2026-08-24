# Injury Context — Phase 2a Implementation Plan (substrate + detection + display)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Annotate the production timeline with **games a received player missed to injury, by phase (regular/playoff/toilet)** — sourced free from nflverse `rosters_weekly` (IR status, `sleeper_id`-native) + `snap_counts` (soft 0-snap signal) + Sleeper live status — rendered as chart markers + an "Injury Impact" block. (Points-lost estimate is Phase 2b, separate plan.)

**Architecture:** A new engine module fetches nflverse CSVs (stdlib `csv`, cached via `FileCache`) and builds a `{(sleeper_id, season, week): InjuryWeek}` map with `high`/`soft` confidence. A pure classifier turns that + the existing matchups/phase data + each received player's tenure into per-player games-missed-by-phase. The grader computes this at refresh (never failing the refresh), caches it on `ChainCacheEntry`, and the API surfaces a per-received-player `injury` block consumed by the production card.

**Tech Stack:** Python 3.11 / pytest / `httpx` (async, already a dep) / stdlib `csv` (NO new deps). FastAPI + Pydantic (api). Next.js 14 + React + inline SVG + vitest (web). Frontend interactive components need `"use client"`; verify with `cd web && npm run build` (tsc+vitest don't catch a missing directive).

**Spec:** `docs/superpowers/specs/2026-06-25-injury-context-design.md`

**Test commands:** engine `.venv/bin/python -m pytest tests/ -q`; api `.venv/bin/python -m pytest api/tests/ -q -p no:randomly`; web `cd web && npx vitest run --config tests/vitest.config.ts`; types `cd web && npx tsc --noEmit`. (Bare `pytest -q` from root fails collection — run `tests/` and `api/tests/` separately. Use `.venv/bin/python`, never bare `python3`.)

**Key shared names (consistent across tasks):**
- `InjuryWeek = {"missed": bool, "confidence": "high" | "soft", "source": str}`
- Injury map type: `dict[tuple[str, int, int], InjuryWeek]` keyed `(sleeper_id, season, week)`.
- nflverse `rosters_weekly` status codes treated as **high-confidence injury**: `{"RES", "PUP", "RSN"}`. `"INA"` and snap-count-0 are **soft**.
- Phases: `"regular" | "playoff" | "toilet"` (reuse `phase_by_lwr` + `playoff_week_start_by_league`).

---

## Task 1: nflverse CSV parsers (pure)

Pure functions that turn already-parsed CSV rows into normalized structures. No network — fully unit-tested with hand-built row dicts.

**Files:**
- Create: `src/sleeper_dynasty/api/nflverse.py`
- Test: `tests/test_nflverse_parse.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_nflverse_parse.py
from sleeper_dynasty.api.nflverse import (
    parse_roster_status_rows, parse_snap_zero_rows, parse_pfr_to_sleeper, HIGH_STATUS,
)


def test_high_status_set():
    assert HIGH_STATUS == {"RES", "PUP", "RSN"}


def test_parse_roster_status_high_and_skip_active():
    rows = [
        {"sleeper_id": "p1", "season": "2025", "week": "5", "status": "RES"},
        {"sleeper_id": "p1", "season": "2025", "week": "6", "status": "ACT"},
        {"sleeper_id": "p2", "season": "2025", "week": "5", "status": "PUP"},
        {"sleeper_id": "",   "season": "2025", "week": "5", "status": "RES"},  # no sleeper id -> skip
    ]
    out = parse_roster_status_rows(rows)
    assert out[("p1", 2025, 5)] == {"missed": True, "confidence": "high", "source": "roster_status:RES"}
    assert ("p1", 2025, 6) not in out        # ACT is not an injury-miss
    assert out[("p2", 2025, 5)]["confidence"] == "high"
    assert all(k[0] for k in out)            # rows without sleeper_id dropped


def test_parse_snap_zero_rows_by_pfr():
    rows = [
        {"pfr_player_id": "X1", "season": "2025", "week": "5", "offense_snaps": "0", "defense_snaps": "0", "st_snaps": "0"},
        {"pfr_player_id": "X1", "season": "2025", "week": "6", "offense_snaps": "12", "defense_snaps": "0", "st_snaps": "0"},
    ]
    out = parse_snap_zero_rows(rows)
    assert ("X1", 2025, 5) in out            # all-zero -> candidate missed
    assert ("X1", 2025, 6) not in out        # played snaps -> not missed


def test_parse_pfr_to_sleeper():
    rows = [
        {"pfr_id": "X1", "sleeper_id": "p1"},
        {"pfr_id": "X2", "sleeper_id": ""},   # no sleeper id -> skip
        {"pfr_id": "",   "sleeper_id": "p3"},
    ]
    assert parse_pfr_to_sleeper(rows) == {"X1": "p1"}
```

- [ ] **Step 2: Run to verify it fails** — `.venv/bin/python -m pytest tests/test_nflverse_parse.py -q` → FAIL (module missing).

- [ ] **Step 3: Implement**

```python
# src/sleeper_dynasty/api/nflverse.py
"""Pure parsers for nflverse CSV exports used by the injury-context feature.

Network fetching lives in ``engine/injury_data.py``; these functions take already-
parsed CSV rows (list of dict[str, str]) so they are trivially unit-testable offline.
"""

from __future__ import annotations

# rosters_weekly `status` codes that unambiguously mean "missed the game to injury".
HIGH_STATUS = {"RES", "PUP", "RSN"}


def _int(v) -> int | None:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def parse_roster_status_rows(rows: list[dict]) -> dict[tuple[str, int, int], dict]:
    """rosters_weekly rows -> {(sleeper_id, season, week): InjuryWeek} for HIGH_STATUS only."""
    out: dict[tuple[str, int, int], dict] = {}
    for r in rows:
        sid = (r.get("sleeper_id") or "").strip()
        status = (r.get("status") or "").strip()
        season, week = _int(r.get("season")), _int(r.get("week"))
        if not sid or season is None or week is None or status not in HIGH_STATUS:
            continue
        out[(sid, season, week)] = {"missed": True, "confidence": "high",
                                    "source": f"roster_status:{status}"}
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
```

- [ ] **Step 4: Run to verify it passes** — `.venv/bin/python -m pytest tests/test_nflverse_parse.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/api/nflverse.py tests/test_nflverse_parse.py
git commit -m "feat(engine): nflverse CSV parsers for injury status + snap zeros + id crosswalk"
```

---

## Task 2: nflverse fetch + cache + unified injury map

Fetch the CSVs over httpx, parse via Task 1, combine into one `(sleeper_id, season, week) -> InjuryWeek` map (high wins over soft), cache the normalized JSON via `FileCache`. The combine logic is unit-tested; fetching is a thin injectable seam.

**Files:**
- Create: `src/sleeper_dynasty/engine/injury_data.py`
- Test: `tests/test_injury_data.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_injury_data.py
from sleeper_dynasty.engine.injury_data import combine_injury_map


def test_combine_prefers_high_over_soft_and_maps_pfr():
    roster_high = {("p1", 2025, 5): {"missed": True, "confidence": "high", "source": "roster_status:RES"}}
    snap_soft_by_pfr = {
        ("X1", 2025, 5): {"missed": True, "confidence": "soft", "source": "snap_count:0"},  # X1 -> p1 (already high)
        ("X2", 2025, 7): {"missed": True, "confidence": "soft", "source": "snap_count:0"},  # X2 -> p9 (new soft)
    }
    pfr_to_sleeper = {"X1": "p1", "X2": "p9"}
    out = combine_injury_map(roster_high, snap_soft_by_pfr, pfr_to_sleeper)
    assert out[("p1", 2025, 5)]["confidence"] == "high"   # high wins, not downgraded by soft
    assert out[("p9", 2025, 7)]["confidence"] == "soft"   # soft mapped pfr->sleeper
    assert ("X2", 2025, 7) not in out                      # keyed by sleeper id, not pfr
```

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Implement**

```python
# src/sleeper_dynasty/engine/injury_data.py
"""Fetch + cache nflverse injury signals, exposed as a (sleeper_id, season, week) map.

High-confidence misses come from rosters_weekly IR/reserve status (sleeper_id native);
soft misses from snap_counts all-zero weeks (pfr_id, mapped via the ff_playerids
crosswalk). High always wins over soft for the same key.
"""

from __future__ import annotations

import csv
import io
import logging

import httpx

from sleeper_dynasty.api.nflverse import (
    parse_roster_status_rows, parse_snap_zero_rows, parse_pfr_to_sleeper,
)

log = logging.getLogger(__name__)

_ROSTER_URL = "https://github.com/nflverse/nflverse-data/releases/download/weekly_rosters/roster_weekly_{season}.csv"
_SNAP_URL = "https://github.com/nflverse/nflverse-data/releases/download/snap_counts/snap_counts_{season}.csv"
_IDS_URL = "https://github.com/dynastyprocess/data/raw/master/files/db_playerids.csv"
_CACHE_TTL_HISTORICAL = 365 * 24 * 3600
_CACHE_TTL_CURRENT = 12 * 3600


def combine_injury_map(roster_high, snap_soft_by_pfr, pfr_to_sleeper):
    """Merge high (sleeper-keyed) + soft (pfr-keyed, remapped) into one sleeper-keyed map.
    High confidence is never overwritten by soft."""
    out = dict(roster_high)
    for (pfr, season, week), info in snap_soft_by_pfr.items():
        sid = pfr_to_sleeper.get(pfr)
        if not sid:
            continue
        key = (sid, season, week)
        if key in out and out[key]["confidence"] == "high":
            continue
        out[key] = info
    return out


def _fetch_csv_rows(url: str) -> list[dict]:
    """GET a CSV and return rows as list[dict]. Raises on HTTP error."""
    resp = httpx.get(url, timeout=60.0, follow_redirects=True)
    resp.raise_for_status()
    return list(csv.DictReader(io.StringIO(resp.text)))


def build_injury_map(
    seasons: list[int],
    *,
    cache=None,
    current_season: int | None = None,
    fetch_rows=_fetch_csv_rows,
) -> dict[tuple[str, int, int], dict]:
    """Build the unified injury map for the given seasons. Caches the normalized
    per-season JSON via FileCache (long TTL for past seasons). ``fetch_rows`` is
    injectable for tests. Any per-season failure logs and is skipped (degrade, never raise)."""
    ids_rows = []
    try:
        ids_rows = fetch_rows(_IDS_URL)
    except Exception:
        log.warning("nflverse ff_playerids fetch failed; soft snap signal disabled", exc_info=True)
    pfr_to_sleeper = parse_pfr_to_sleeper(ids_rows)

    merged: dict[tuple[str, int, int], dict] = {}
    for season in seasons:
        ck = f"nflverse_injury_{season}.json"
        ttl = _CACHE_TTL_CURRENT if season == current_season else _CACHE_TTL_HISTORICAL
        cached = cache.read(ck, max_age_seconds=ttl) if cache else None
        if cached is not None:
            for k, v in cached.items():
                sid, s, w = k.split("|")
                merged[(sid, int(s), int(w))] = v
            continue
        try:
            roster_high = parse_roster_status_rows(fetch_rows(_ROSTER_URL.format(season=season)))
            snap_soft = parse_snap_zero_rows(fetch_rows(_SNAP_URL.format(season=season)))
        except Exception:
            log.warning("nflverse fetch failed for season %s; skipping", season, exc_info=True)
            continue
        season_map = combine_injury_map(roster_high, snap_soft, pfr_to_sleeper)
        if cache:
            cache.write(ck, {f"{sid}|{s}|{w}": v for (sid, s, w), v in season_map.items()})
        merged.update(season_map)
    return merged
```

- [ ] **Step 4: Run to verify it passes** — `.venv/bin/python -m pytest tests/test_injury_data.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/injury_data.py tests/test_injury_data.py
git commit -m "feat(engine): fetch+cache nflverse injury map (high roster status + soft snap zeros)"
```

> **Live-URL verification (manual, not a test):** after this task, run a one-off `.venv/bin/python -c "from sleeper_dynasty.engine.injury_data import _fetch_csv_rows, _ROSTER_URL; print(len(_fetch_csv_rows(_ROSTER_URL.format(season=2024))))"` to confirm the URL/asset names resolve. If nflverse renamed the release/asset, fix the three URL constants. Tests stay offline via the `fetch_rows` seam.

---

## Task 3: Games-missed-by-phase classifier (pure)

Per received player on a side, count games missed to injury by phase, within their on-roster tenure, using the injury map + matchups + phase classification.

**Files:**
- Create: `src/sleeper_dynasty/engine/injury.py`
- Test: `tests/test_injury_classifier.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_injury_classifier.py
from sleeper_dynasty.engine.injury import games_missed_by_phase


def _phase_fn(season, week):
    # week 16 in 2024 is a playoff (title-path) week; else regular
    return "playoff" if (season, week) == (2024, 16) else "regular"


def test_counts_missed_by_phase_within_owned_weeks():
    # player "p1" owned by u1 in 2024 weeks 14-16; injured (high) wk15 (regular) + wk16 (playoff);
    # wk14 they played. owned_weeks is the set of (season, week) the player was on uid's roster.
    owned_weeks = {(2024, 14), (2024, 15), (2024, 16)}
    played_weeks = {(2024, 14)}  # weeks pid actually appeared in players_points for uid
    injury_map = {
        ("p1", 2024, 15): {"missed": True, "confidence": "high", "source": "roster_status:RES"},
        ("p1", 2024, 16): {"missed": True, "confidence": "high", "source": "roster_status:RES"},
    }
    res = games_missed_by_phase("p1", owned_weeks, played_weeks, injury_map, _phase_fn)
    assert res["games_missed"] == {"regular": 1, "playoff": 1, "toilet": 0}
    assert sorted((w, c["confidence"]) for w, c in res["missed_weeks"]) == \
        [((2024, 15), "high"), ((2024, 16), "high")]


def test_played_week_not_counted_even_if_flagged():
    owned_weeks = {(2024, 14)}
    played_weeks = {(2024, 14)}            # they played, so not a miss
    injury_map = {("p1", 2024, 14): {"missed": True, "confidence": "soft", "source": "snap_count:0"}}
    res = games_missed_by_phase("p1", owned_weeks, played_weeks, injury_map, _phase_fn)
    assert res["games_missed"] == {"regular": 0, "playoff": 0, "toilet": 0}
```

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Implement**

```python
# src/sleeper_dynasty/engine/injury.py
"""Classify a received player's injury-missed games by phase, over their owned weeks."""

from __future__ import annotations

from typing import Callable


def games_missed_by_phase(
    player_id: str,
    owned_weeks: set[tuple[int, int]],
    played_weeks: set[tuple[int, int]],
    injury_map: dict[tuple[str, int, int], dict],
    phase_fn: Callable[[int, int], str],
) -> dict:
    """A missed-to-injury game = a week the player was on the owner's roster, did NOT play,
    and is injury-flagged. Counted into the week's phase. ``phase_fn(season, week) ->
    'regular'|'playoff'|'toilet'|'dropped'`` (dropped/None weeks are ignored).

    Returns {"games_missed": {regular, playoff, toilet}, "missed_weeks": [((season,week), info)]}.
    """
    counts = {"regular": 0, "playoff": 0, "toilet": 0}
    missed: list[tuple[tuple[int, int], dict]] = []
    for (season, week) in owned_weeks:
        if (season, week) in played_weeks:
            continue
        info = injury_map.get((player_id, season, week))
        if not info or not info.get("missed"):
            continue
        phase = phase_fn(season, week)
        if phase not in counts:
            continue
        counts[phase] += 1
        missed.append(((season, week), info))
    missed.sort(key=lambda m: m[0])
    return {"games_missed": counts, "missed_weeks": missed}
```

- [ ] **Step 4: Run to verify it passes** — `.venv/bin/python -m pytest tests/test_injury_classifier.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/injury.py tests/test_injury_classifier.py
git commit -m "feat(engine): games-missed-by-phase injury classifier"
```

---

## Task 4: Keep Sleeper live injury fields

Surface the current injury badge by keeping the injury fields the players dump already returns.

**Files:**
- Modify: `src/sleeper_dynasty/models/player.py` (add optional fields)
- Create: `tests/test_player_injury_fields.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_player_injury_fields.py
from sleeper_dynasty.api.nflverse import HIGH_STATUS  # noqa (sanity import path)
from sleeper_dynasty.engine.injury_live import live_injury


def test_live_injury_currently_out():
    raw = {"injury_status": "Out", "injury_start_date": "2026-09-10", "injury_body_part": "Knee"}
    li = live_injury(raw)
    assert li == {"currently_out": True, "status": "Out", "body_part": "Knee", "since": "2026-09-10"}


def test_live_injury_healthy():
    assert live_injury({"injury_status": None})["currently_out"] is False
    assert live_injury({})["currently_out"] is False
```

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Implement**

Add a tiny pure helper (keep parsing out of the model). Create `src/sleeper_dynasty/engine/injury_live.py`:

```python
# src/sleeper_dynasty/engine/injury_live.py
"""Map a Sleeper players-dump raw record to a live-injury summary for the 'currently out' badge."""

from __future__ import annotations

# Sleeper injury_status values that mean a player is not available / hobbled right now.
_OUT_LIKE = {"Out", "IR", "PUP", "Doubtful", "Suspended"}


def live_injury(raw: dict) -> dict:
    status = (raw or {}).get("injury_status")
    return {
        "currently_out": status in _OUT_LIKE,
        "status": status,
        "body_part": (raw or {}).get("injury_body_part"),
        "since": (raw or {}).get("injury_start_date"),
    }
```

(No change to the `Player` dataclass is required — the grader uses the raw dict directly. This keeps the helper focused and testable. The `models/player.py` Modify entry is dropped; this file is the unit.)

- [ ] **Step 4: Run to verify it passes** — `.venv/bin/python -m pytest tests/test_player_injury_fields.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/injury_live.py tests/test_player_injury_fields.py
git commit -m "feat(engine): live injury summary from Sleeper players dump"
```

---

## Task 5: Injury payload builder (per trade, per received player)

Assemble the per-(trade, side, player) injury block at refresh, mirroring `compute_production_series_payload`. Reuses `side_value_tenures` for received players and the matchups/phase data for owned/played weeks.

**Files:**
- Modify: `api/app/services/grader.py` (add `compute_injury_payload`)
- Test: `api/tests/test_compute_injury_payload.py`

- [ ] **Step 1: Write the failing test**

```python
# api/tests/test_compute_injury_payload.py
from app.services.grader import compute_injury_payload


def test_injury_payload_shape(simple_two_team_chain):
    """Reuse the simple_two_team_chain fixture from test_compute_production_series.py
    (one 2-team trade, L1 2024, u1 received p1). Extend it here with:
      - matchups so p1 is on u1's roster in weeks 5,6 but only PLAYS week 5
      - injury_map flagging p1 OUT (high) week 6 (a regular-season week)
      - raw_players {p1: {injury_status: 'Out', injury_body_part: 'Knee'}}
    """
    f = simple_two_team_chain
    payload = compute_injury_payload(
        resolved_dicts=f.resolved_dicts, matchups=f.matchups,
        roster_to_user_by_league=f.roster_to_user_by_league,
        league_season_by_id=f.league_season_by_id, current_holders=f.current_holders,
        drop_index=f.drop_index, phase_by_lwr=f.phase_by_lwr,
        playoff_week_start_by_league=f.playoff_week_start_by_league,
        injury_map={("p1", 2024, 6): {"missed": True, "confidence": "high", "source": "roster_status:RES"}},
        raw_players={"p1": {"injury_status": "Out", "injury_body_part": "Knee", "injury_start_date": "2024-10-01"}},
    )
    tx = f.resolved_dicts[0]["trade"]["transaction_id"]
    inj = payload["trade_injury"][tx]["u1"]["p1"]
    assert inj["games_missed"]["regular"] == 1
    assert inj["currently_out"] is True and inj["out_detail"]
    assert inj["missed_weeks"] == [[2024, 6, "high"]]
```

> Extend the `simple_two_team_chain` fixture (in `api/tests/test_compute_production_series.py` or conftest) so `matchups` has p1 in `players` for (L1,5,rid) and (L1,6,rid) but in `players_points` only for week 5. Confirm the league season maps L1→2024 and weeks 5/6 classify regular.

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Implement** — add to `api/app/services/grader.py`:

```python
def compute_injury_payload(
    *,
    resolved_dicts: list[dict],
    matchups: dict,
    roster_to_user_by_league: dict,
    league_season_by_id: dict,
    current_holders: dict,
    drop_index: dict,
    phase_by_lwr: dict,
    playoff_week_start_by_league: dict,
    injury_map: dict,
    raw_players: dict,
) -> dict:
    """Per-trade per-side per-received-player injury block.

    Returns {"trade_injury": tx -> uid -> player_id -> {
        games_missed:{regular,playoff,toilet}, missed_weeks:[[season,week,confidence]],
        currently_out:bool, out_detail:str|None }}.
    """
    from sleeper_dynasty.engine.lineage import side_value_tenures
    from sleeper_dynasty.engine.injury import games_missed_by_phase
    from sleeper_dynasty.engine.injury_live import live_injury

    def _owned_played(pid: str, uid: str):
        """Return (owned_weeks, played_weeks, phase_fn) for pid on uid across the chain.
        owned/played keyed by (season, week); phase_fn(season,week) uses the per-(lg,wk,rid) phase."""
        owned: set[tuple[int, int]] = set()
        played: set[tuple[int, int]] = set()
        phase_by_sw: dict[tuple[int, int], str] = {}
        for (lg, wk, rid), entry in matchups.items():
            if roster_to_user_by_league.get(lg, {}).get(rid) != uid:
                continue
            if pid not in (entry.get("players") or []):
                continue
            season = league_season_by_id.get(lg, 0)
            owned.add((season, wk))
            ps = playoff_week_start_by_league.get(lg, 15)
            phase = "regular" if wk < ps else phase_by_lwr.get((lg, wk, rid), "dropped")
            phase_by_sw[(season, wk)] = phase
            pts = (entry.get("players_points") or {})
            if pid in pts:
                played.add((season, wk))
        return owned, played, (lambda s, w: phase_by_sw.get((s, w), "dropped"))

    def _received_player_ids(tx, uid):
        tens = side_value_tenures(resolved_dicts, tx, uid, which="received",
                                  current_holders=current_holders, drop_index=drop_index)
        return [t.player_id for t in tens if t.kind == "player" and t.player_id]

    trade_injury: dict = {}
    for r in resolved_dicts:
        tx = r["trade"]["transaction_id"]
        for uid in (r.get("sides") or {}):
            for pid in _received_player_ids(tx, uid):
                owned, played, phase_fn = _owned_played(pid, uid)
                gm = games_missed_by_phase(pid, owned, played, injury_map, phase_fn)
                total_missed = sum(gm["games_missed"].values())
                li = live_injury(raw_players.get(pid) or {})
                if total_missed == 0 and not li["currently_out"]:
                    continue  # nothing to report for this player
                out_detail = None
                if li["currently_out"]:
                    bp = f" ({li['body_part']})" if li.get("body_part") else ""
                    since = f" since {li['since']}" if li.get("since") else ""
                    out_detail = f"{li['status']}{bp}{since}".strip()
                trade_injury.setdefault(tx, {}).setdefault(uid, {})[pid] = {
                    "games_missed": gm["games_missed"],
                    "missed_weeks": [[s, w, info["confidence"]] for (s, w), info in gm["missed_weeks"]],
                    "currently_out": li["currently_out"],
                    "out_detail": out_detail,
                }
    return {"trade_injury": trade_injury}
```

(Phase classification is the per-`(season,week)` closure built inside `_owned_played` from the per-`(lg,wk,rid)` phase — no module-level phase function is needed here.)

- [ ] **Step 4: Run to verify it passes** — `.venv/bin/python -m pytest api/tests/test_compute_injury_payload.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add api/app/services/grader.py api/tests/test_compute_injury_payload.py
git commit -m "feat(api): compute_injury_payload (per-received-player games-missed + live status)"
```

---

## Task 6: Cache fields + pipeline wiring + SCHEMA_VERSION bump

**Files:**
- Modify: `api/app/services/chain_cache.py` (add `trade_injury` field; bump `SCHEMA_VERSION` 8 → 9)
- Modify: `api/app/services/grader.py` (`run`: build injury map, call `compute_injury_payload`, assign to entry)
- Test: `api/tests/test_chain_cache.py` (add round-trip)

- [ ] **Step 1: Write the failing test**

```python
# api/tests/test_chain_cache.py  (add)
def test_entry_carries_injury_field():
    from app.services.chain_cache import ChainCacheEntry
    e = ChainCacheEntry()
    e.trade_injury = {"t1": {"u1": {"p1": {"games_missed": {"regular": 1, "playoff": 0, "toilet": 0},
                                           "missed_weeks": [[2024, 6, "high"]],
                                           "currently_out": False, "out_detail": None}}}}
    assert e.trade_injury["t1"]["u1"]["p1"]["games_missed"]["regular"] == 1
```

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Implement**

In `chain_cache.py`: bump `SCHEMA_VERSION = 9` (from 8) and add after the production fields:
```python
    # injury context (Phase 2a): tx -> uid -> player_id -> injury block
    trade_injury: dict = field(default_factory=dict)
```

In `grader.py` `run`, right after the production stage's try/except (where `production_payload` is assigned), add a sibling injury stage (own try/except so it never fails the refresh):
```python
        try:
            from sleeper_dynasty.engine.injury_data import build_injury_map
            seasons = sorted({s for s in league_season_by_id.values() if s})
            injury_map = build_injury_map(
                seasons, cache=(league_cache.file_cache if league_cache else None),
                current_season=max(seasons) if seasons else None,
            )
            injury_payload = compute_injury_payload(
                resolved_dicts=resolved_dicts, matchups=supporting["matchups"],
                roster_to_user_by_league=supporting["roster_to_user_by_league"],
                league_season_by_id=supporting["league_season_by_id"],
                current_holders=current_holders, drop_index=drop_index,
                phase_by_lwr=supporting.get("phase_by_lwr") or {},
                playoff_week_start_by_league=supporting.get("playoff_week_start_by_league") or {},
                injury_map=injury_map, raw_players=raw_players,
            )
            entry.trade_injury = injury_payload["trade_injury"]
        except Exception:
            log.exception("injury-context stage failed")
```

> Confirm the exact handle for a `FileCache` instance in `run` (grep `FileCache` / `league_cache` / `file_cache`). If `league_cache` doesn't expose a `FileCache`, construct one: `from sleeper_dynasty.cache import FileCache; FileCache(cache_dir) if cache_dir else None`. Ensure this block is AFTER `resolved_dicts` and `raw_players` exist and BEFORE the `ChainCacheEntry(...)` construction; if the entry is built via constructor kwargs, add `trade_injury=injury_payload["trade_injury"]` there instead of attribute assignment, with a safe default `{}` initialized before the try.

- [ ] **Step 4: Run to verify it passes** — `.venv/bin/python -m pytest api/tests/test_chain_cache.py api/tests/test_compute_injury_payload.py -q` → PASS. Also `.venv/bin/python -m pytest api/tests/ -k "grader or chain_cache or refresh" -q -p no:randomly` → PASS.

- [ ] **Step 5: Commit**

```bash
git add api/app/services/chain_cache.py api/app/services/grader.py api/tests/test_chain_cache.py
git commit -m "feat(api): persist injury payload on ChainCacheEntry; wire injury stage; bump SCHEMA_VERSION 9"
```

---

## Task 7: API model + trade-detail assembly

**Files:**
- Modify: `api/app/models/trade.py` (add `PlayerInjuryView`; add `injury` to `PlayerProductionView` OR a parallel `trade_injury` map on `TradeDetailResp`)
- Modify: `api/app/services/trade_view.py`
- Test: `api/tests/test_trade_view_injury.py`

Decision: surface a parallel map `injury: dict[str, dict[str, PlayerInjuryView]]` (uid -> player_id -> view) on `TradeDetailResp`, keeping it independent of the production-players list (simpler join on the frontend by player_id).

- [ ] **Step 1: Write the failing test**

```python
# api/tests/test_trade_view_injury.py
from app.services.trade_view import build_trade_detail


def test_trade_detail_surfaces_injury(trade_detail_fixture):
    """Extend the trade_detail_fixture entry with:
      entry.trade_injury = {"t1": {"u1": {"p1": {"games_missed": {"regular":1,"playoff":1,"toilet":0},
        "missed_weeks": [[2024,16,"high"]], "currently_out": True, "out_detail": "Out (Knee)"}}}}
    """
    resp = build_trade_detail(**trade_detail_fixture)
    v = resp.injury["u1"]["p1"]
    assert v.games_missed["playoff"] == 1
    assert v.currently_out is True
    assert v.missed_weeks == [[2024, 16, "high"]]
```

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Implement**

In `api/app/models/trade.py`:
```python
class PlayerInjuryView(BaseModel):
    games_missed: dict[str, int] = {}                 # {"regular","playoff","toilet"}
    missed_weeks: list[list] = []                      # [[season, week, confidence], ...]
    currently_out: bool = False
    out_detail: str | None = None
```
Add to `TradeDetailResp`: `injury: dict[str, dict[str, PlayerInjuryView]] = {}`  # uid -> player_id -> view

In `trade_view.py` (beside the production assembly):
```python
    from app.models.trade import PlayerInjuryView
    injury_raw = (getattr(entry, "trade_injury", None) or {}).get(trade_id) or {}
    injury_view = {
        uid: {pid: PlayerInjuryView(**blk) for pid, blk in by_pid.items()}
        for uid, by_pid in injury_raw.items()
    }
```
Pass `injury=injury_view` into `TradeDetailResp(...)`.

- [ ] **Step 4: Run to verify it passes** — `.venv/bin/python -m pytest api/tests/test_trade_view_injury.py -q` and `.venv/bin/python -m pytest api/tests/ -k trade_view -q -p no:randomly` → PASS.

- [ ] **Step 5: Commit**

```bash
git add api/app/models/trade.py api/app/services/trade_view.py api/tests/test_trade_view_injury.py
git commit -m "feat(api): surface per-received-player injury on trade detail"
```

---

## Task 8: Frontend — injury markers + Injury Impact block

**Files:**
- Modify: `web/lib/types.ts` (add `PlayerInjury`; `injury?` on `TradeDetailResp`)
- Modify: `web/components/ProductionTimeline.tsx` (accept optional per-line injury markers)
- Modify: `web/components/TradeProductionCard.tsx` (pass markers for the drilled player; render Injury Impact block)
- Test: `web/tests/TradeProductionCard.test.tsx` (extend)

- [ ] **Step 1: Add types** (`web/lib/types.ts`)

```ts
export interface PlayerInjury {
  games_missed: { regular: number; playoff: number; toilet: number };
  missed_weeks: [number, number, "high" | "soft"][];   // [season, week, confidence]
  currently_out: boolean;
  out_detail?: string | null;
}
```
Add to `TradeDetailResp`: `injury?: Record<string, Record<string, PlayerInjury>>;  // uid -> player_id -> injury`

- [ ] **Step 2: Write the failing test** (`web/tests/TradeProductionCard.test.tsx` — add)

```tsx
import { test, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
test("renders Injury Impact block for an injured received player", () => {
  render(
    <TradeProductionCard
      axis={[[2024, 15], [2024, 16]]}
      series={{ u1: { total: [{season:2024,week:15,value:0},{season:2024,week:16,value:0}], regular:[], playoff:[], toilet:[] } }}
      verdict={{ total: { label: "x", sentence: "y", tone: "neutral" } }}
      names={{ u1: "Tom" }}
      players={{ u1: [{ player_id: "p1", series: { total:[{season:2024,week:15,value:0},{season:2024,week:16,value:0}], regular:[], playoff:[], toilet:[] } }] }}
      injury={{ u1: { p1: { games_missed: { regular: 0, playoff: 1, toilet: 0 }, missed_weeks: [[2024,16,"high"]], currently_out: true, out_detail: "Out (Knee)" } } }}
      playerName={(id) => (id === "p1" ? "Bijan" : id)}
    />,
  );
  expect(screen.getByText(/injury impact/i)).toBeInTheDocument();
  expect(screen.getByText(/Bijan/)).toBeInTheDocument();
  expect(screen.getByText(/1 playoff/i)).toBeInTheDocument();
  expect(screen.getByText(/Out \(Knee\)/)).toBeInTheDocument();
});
```

- [ ] **Step 3: Implement**

`ProductionTimeline.tsx` — extend `TimelineLine` with optional `markers?: {season:number; week:number; confidence:"high"|"soft"}[]`, and in the SVG, after drawing each polyline, draw a small circle at each marker's (x,y) on that line (`x` = axis index of the (season,week); `y` = that line's value at that index; solid fill for `high`, hollow stroke for `soft`). Skip markers whose (season,week) isn't on the axis.

`TradeProductionCard.tsx`:
- When drilled into a side, attach `markers` to each per-player line from `injury?.[view]?.[player_id]?.missed_weeks` (map `[s,w,conf]` → `{season:s, week:w, confidence:conf}`).
- Add an **Injury Impact** block under the chart: for each uid, for each player in `injury[uid]` with `games_missed` total > 0 OR `currently_out`, render a line: `"{playerName(pid)} · missed {total} ({regular} reg, {playoff} playoff, {toilet} TB) {out_detail ? '· ' + out_detail : ''}"`. Use the existing chip/`text-dim` styles. Omit phases with 0 in the summary text (e.g. show "1 playoff" only).
- Ensure the file still begins with `"use client"` (it uses hooks).

Wire the prop on the trade page: `web/app/league/[id]/trade/[tid]/page.tsx` → add `injury={data.injury}` to `<TradeProductionCard>`.

- [ ] **Step 4: Verify**

`cd web && npx vitest run TradeProductionCard ProductionTimeline --config tests/vitest.config.ts` → PASS. `cd web && npx tsc --noEmit` → clean. `cd web && npm run build` → succeeds (catches any missing `"use client"`).

- [ ] **Step 5: Commit**

```bash
git add web/lib/types.ts web/components/ProductionTimeline.tsx web/components/TradeProductionCard.tsx web/tests/TradeProductionCard.test.tsx "web/app/league/[id]/trade/[tid]/page.tsx"
git commit -m "feat(web): injury markers on drill lines + Injury Impact block"
```

---

## Task 9: Full verification

- [ ] **Step 1:** `.venv/bin/python -m pytest tests/ -q` → all PASS.
- [ ] **Step 2:** `.venv/bin/python -m pytest api/tests/ -q -p no:randomly` → all PASS.
- [ ] **Step 3:** `cd web && npx vitest run --config tests/vitest.config.ts` → all PASS.
- [ ] **Step 4:** `cd web && npx tsc --noEmit` && `cd web && npm run build` → clean (build catches missing `"use client"`).
- [ ] **Step 5 (manual):** run the live-URL check from Task 2 to confirm nflverse URLs resolve for a real season.
- [ ] **Step 6:** commit any final fixes.

---

## Self-review notes

- **Spec coverage:** §1 data layer (Tasks 1-2, 4), §2 detection (Tasks 3, 5), §3 games-missed-by-phase (Tasks 3, 5), §5 storage+API (Tasks 6-7), §6 frontend markers+block (Task 8), §7 edge cases (high/soft in Tasks 1-3; bye/played-week exclusion in Task 3; degrade-never-fail in Tasks 2, 6), §8 testing (every task TDD). **§4 points-lost is intentionally Phase 2b — NOT in this plan.**
- **Deliberate scope cut for 2a:** no points-lost estimate, no owner-aggregate roll-up, no body-part beyond Sleeper live status. Each is named where deferred.
- **No-network tests:** the only network is in `injury_data._fetch_csv_rows`, isolated behind the `fetch_rows` injection seam; all parse/combine/classify/assembly logic is tested offline. Live URLs are verified by a manual one-off, not a unit test.
- **Naming consistency:** `InjuryWeek` dict shape (`missed`/`confidence`/`source`), `HIGH_STATUS={RES,PUP,RSN}`, the `trade_injury` payload key, and `PlayerInjuryView`/`PlayerInjury` fields (`games_missed`/`missed_weeks`/`currently_out`/`out_detail`) match across engine → grader → cache → API → web.
- **SCHEMA_VERSION** bumped 8→9 (Task 6) per the cache-migration rule.
