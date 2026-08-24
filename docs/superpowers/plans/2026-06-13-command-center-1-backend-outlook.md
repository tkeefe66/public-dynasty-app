# Command Center · Plan 1 — Backend Outlook Data Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compute the full dynasty outlook (age profile, draft capital, draft needs, window, trajectory) + a roster-value-rank proxy + draft-skill rank per owner during refresh, persist them on the chain cache, and expose them on the owner-detail API — all available year-round (no in-season projections required).

**Architecture:** A new pure engine module (`engine/outlook_build.py`) builds a `DynastyOutlook` per current roster using offseason-safe substitutes: position rankings derived from KTC value (not projections) and `projected_rank_pct` derived from the roster's KTC-value rank (the Option-2 proxy). The grader runs this stage after rating-signal computation and stores serialized outlooks + ranks on `ChainCacheEntry`; `build_owner_detail` reads them into new optional `OwnerDetailResp` fields. No UI in this plan — that's Plan 2.

**Tech Stack:** Python 3, pytest, FastAPI + Pydantic v2, dataclasses; TypeScript (types only).

This is **Plan 1 of 3** for the Franchise Command Center sub-project (spec:
`docs/superpowers/specs/2026-06-13-franchise-command-center-design.md`). Plan 2 = web tabbed
UI; Plan 3 = LLM franchise blurb.

---

## File Structure

- **Create** `src/sleeper_dynasty/engine/outlook_build.py` — offseason-safe outlook builder, roster-value rank helpers, JSON serializer. Pure.
- **Modify** `src/sleeper_dynasty/models/player.py` — add shared `build_players()` + `parse_birth_date()` (promoted from `cli.py`).
- **Modify** `src/sleeper_dynasty/cli.py` — delegate to the shared player builder.
- **Modify** `api/app/services/chain_cache.py` — add `dynasty_outlooks` + `roster_ranks` fields.
- **Modify** `api/app/services/grader.py` — new outlook stage; persist on entry.
- **Modify** `api/app/models/owner.py` — new view models + optional fields on `OwnerDetailResp`.
- **Modify** `api/app/services/owner_view.py` — populate new fields.
- **Modify** `web/lib/types.ts` — mirror the new response shape.
- **Tests:** `tests/test_outlook_build.py`, `tests/test_player_build.py`, `api/tests/test_owner_view_outlook.py` (paths follow existing test layout).

---

## Task 1: Shared player parser

Promote the raw→`Player` parser out of `cli.py` so the API can use it too.

**Files:**
- Modify: `src/sleeper_dynasty/models/player.py`
- Modify: `src/sleeper_dynasty/cli.py:207-251`
- Test: `tests/test_player_build.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_player_build.py
from datetime import date

from sleeper_dynasty.models.player import build_players, parse_birth_date


def test_parse_birth_date_iso_string():
    assert parse_birth_date("1996-07-26") == date(1996, 7, 26)


def test_parse_birth_date_malformed_is_none():
    assert parse_birth_date("not-a-date") is None
    assert parse_birth_date(None) is None


def test_build_players_maps_fields_and_skips_non_dicts():
    raw = {
        "p1": {"full_name": "Bijan Robinson", "position": "RB",
               "team": "ATL", "birth_date": "2001-12-30", "years_exp": 2},
        "p2": {"first_name": "Sam", "last_name": "LaPorta", "position": "TE"},
        "junk": ["not", "a", "dict"],
    }
    players = build_players(raw)
    assert "junk" not in players
    assert players["p1"].full_name == "Bijan Robinson"
    assert players["p1"].position == "RB"
    assert players["p1"].birth_date == date(2001, 12, 30)
    # full_name falls back to "first last"
    assert players["p2"].full_name == "Sam LaPorta"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_player_build.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_players'`.

- [ ] **Step 3: Add the functions to `models/player.py`**

Add these imports near the top of `src/sleeper_dynasty/models/player.py` (it already imports `date`):

```python
from datetime import date, datetime
from typing import Any
```

Append to `src/sleeper_dynasty/models/player.py`:

```python
def parse_birth_date(raw: Any) -> date | None:
    """Parse a Sleeper ``birth_date`` (ISO string like "1996-07-26") into a date.

    Missing or malformed values degrade gracefully to ``None``.
    """
    if not raw:
        return None
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str):
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


def build_players(raw_players: dict[str, Any]) -> dict[str, Player]:
    """Convert the raw Sleeper players-NFL dump into ``Player`` objects."""
    players: dict[str, Player] = {}
    for pid, raw in raw_players.items():
        if not isinstance(raw, dict):
            continue
        full_name = (
            raw.get("full_name")
            or f"{raw.get('first_name', '')} {raw.get('last_name', '')}".strip()
            or pid
        )
        players[pid] = Player(
            player_id=pid,
            full_name=full_name,
            position=raw.get("position") or "",
            team=raw.get("team"),
            birth_date=parse_birth_date(raw.get("birth_date")),
            years_exp=raw.get("years_exp"),
        )
    return players
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_player_build.py -v`
Expected: PASS.

- [ ] **Step 5: Point `cli.py` at the shared functions**

In `src/sleeper_dynasty/cli.py`, delete the local `_parse_birth_date` (lines ~207-222) and `_build_players` (lines ~225-251) and replace their usages. Add to the cli imports:

```python
from sleeper_dynasty.models.player import build_players as _build_players
from sleeper_dynasty.models.player import parse_birth_date as _parse_birth_date
```

(Aliasing keeps existing call sites unchanged.)

- [ ] **Step 6: Run the engine suite to confirm nothing broke**

Run: `pytest -q`
Expected: PASS (same count as before, plus the 4 new tests).

- [ ] **Step 7: Commit**

```bash
git add src/sleeper_dynasty/models/player.py src/sleeper_dynasty/cli.py tests/test_player_build.py
git commit -m "refactor(engine): share Player parser between cli and api"
```

---

## Task 2: Offseason-safe outlook builder (pure helpers)

**Files:**
- Create: `src/sleeper_dynasty/engine/outlook_build.py`
- Test: `tests/test_outlook_build.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_outlook_build.py
from sleeper_dynasty.engine.outlook_build import (
    ktc_position_rankings, roster_value_rank_pct, roster_value_ranks,
)
from sleeper_dynasty.models.league import Roster


def _roster(rid, owner, players):
    return Roster(roster_id=rid, owner_id=owner, players=players,
                  wins=0, losses=0, ties=0, points_for=0.0, points_against=0.0)


def test_ktc_position_rankings_orders_by_value_desc():
    rosters = [_roster(1, "uA", ["wr1", "wr2"]), _roster(2, "uB", ["wr3"])]
    positions = {"wr1": "WR", "wr2": "WR", "wr3": "WR"}
    ktc = {"wr1": 100.0, "wr2": 900.0, "wr3": 500.0}
    rankings = ktc_position_rankings(rosters, positions, ktc)
    assert rankings["WR"] == ["wr2", "wr3", "wr1"]


def test_roster_value_rank_pct_best_is_zero_worst_is_one():
    pct = roster_value_rank_pct({1: 300.0, 2: 100.0, 3: 200.0})
    assert pct[1] == 0.0      # best
    assert pct[2] == 1.0      # worst
    assert 0.0 < pct[3] < 1.0


def test_roster_value_ranks_one_based_with_total():
    ranks = roster_value_ranks({"uA": 300.0, "uB": 100.0, "uC": 200.0})
    assert ranks["uA"] == {"rank": 1, "of": 3}
    assert ranks["uB"] == {"rank": 3, "of": 3}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_outlook_build.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sleeper_dynasty.engine.outlook_build'`.

> NOTE: confirm the `Roster` constructor kwargs against `src/sleeper_dynasty/models/league.py`. If field names differ, adjust the `_roster` helper to match; the helpers under test only read `roster.roster_id` and `roster.players`.

- [ ] **Step 3: Create the module with the three helpers**

```python
# src/sleeper_dynasty/engine/outlook_build.py
"""Offseason-safe construction of dynasty outlooks for the API refresh.

The CLI builds outlooks from Monte-Carlo projections; those don't exist in the
offseason. Here we substitute KTC value for both inputs ``build_dynasty_outlook``
needs: position rankings (by KTC desc) and ``projected_rank_pct`` (by roster
KTC-value rank). Pure and unit-tested.
"""

from __future__ import annotations

from datetime import date

from sleeper_dynasty.engine.dynasty import DynastyOutlook, build_dynasty_outlook
from sleeper_dynasty.models.league import DraftPick, Roster
from sleeper_dynasty.models.player import Player


def ktc_position_rankings(
    rosters: list[Roster],
    positions: dict[str, str],
    ktc_value_by_player: dict[str, float],
) -> dict[str, list[str]]:
    """position -> player_ids across the league, ranked by KTC value (best first).

    Offseason-safe substitute for projection-based rankings.
    """
    by_pos: dict[str, list[str]] = {}
    for r in rosters:
        for pid in (r.players or []):
            pos = positions.get(pid)
            if not pos:
                continue
            by_pos.setdefault(pos, []).append(pid)
    for pids in by_pos.values():
        pids.sort(key=lambda p: ktc_value_by_player.get(p, 0.0), reverse=True)
    return by_pos


def roster_value_rank_pct(
    roster_value_by_roster: dict[int, float],
) -> dict[int, float]:
    """roster_id -> percentile (0.0 best, 1.0 worst) by roster KTC value desc."""
    ordered = sorted(
        roster_value_by_roster,
        key=lambda r: roster_value_by_roster[r], reverse=True)
    denom = max(1, len(ordered) - 1)
    return {rid: i / denom for i, rid in enumerate(ordered)}


def roster_value_ranks(
    roster_value_by_owner: dict[str, float],
) -> dict[str, dict[str, int]]:
    """uid -> {'rank': 1-based, 'of': N} by roster value desc (current owners)."""
    ordered = sorted(
        roster_value_by_owner,
        key=lambda u: roster_value_by_owner[u], reverse=True)
    n = len(ordered)
    return {uid: {"rank": i + 1, "of": n} for i, uid in enumerate(ordered)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_outlook_build.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/outlook_build.py tests/test_outlook_build.py
git commit -m "feat(engine): offseason-safe outlook rank helpers"
```

---

## Task 3: Outlook builder + JSON serializer

**Files:**
- Modify: `src/sleeper_dynasty/engine/outlook_build.py`
- Test: `tests/test_outlook_build.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_outlook_build.py
import json
from datetime import date

from sleeper_dynasty.engine.outlook_build import (
    build_outlooks_by_owner, outlook_to_dict,
)
from sleeper_dynasty.models.player import Player


def _player(pid, pos, birth):
    return Player(player_id=pid, full_name=pid.upper(), position=pos,
                  team="X", birth_date=birth)


def test_build_and_serialize_outlook_is_json_safe():
    rosters = [_roster(1, "uA", ["rb1", "wr1"]), _roster(2, "uB", ["qb1"])]
    players = {
        "rb1": _player("rb1", "RB", date(1990, 1, 1)),   # old RB -> aging risk
        "wr1": _player("wr1", "WR", date(2003, 1, 1)),   # young WR -> core young
        "qb1": _player("qb1", "QB", date(1998, 1, 1)),
    }
    positions = {"rb1": "RB", "wr1": "WR", "qb1": "QB"}
    ktc = {"rb1": 200.0, "wr1": 800.0, "qb1": 500.0}
    outlooks = build_outlooks_by_owner(
        rosters=rosters, players=players, traded_picks=[], positions=positions,
        ktc_value_by_player=ktc, roster_to_user={1: "uA", 2: "uB"},
        total_rosters=2, num_rounds=4)
    assert set(outlooks) == {"uA", "uB"}
    d = outlook_to_dict(outlooks["uA"], as_of=date(2026, 1, 1))
    # round-trips through JSON (no date objects, no tuple keys)
    json.dumps(d)
    assert d["window"]
    assert isinstance(d["age_profile"]["aging_risks"], list)
    assert any(p["player_id"] == "rb1" for p in d["age_profile"]["aging_risks"])
    assert any(p["player_id"] == "wr1" for p in d["age_profile"]["core_young"])
    assert d["draft_capital"]["status"] in ("pick-rich", "neutral", "pick-poor")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_outlook_build.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_outlooks_by_owner'`.

- [ ] **Step 3: Add the builder + serializer**

Append to `src/sleeper_dynasty/engine/outlook_build.py`:

```python
def build_outlooks_by_owner(
    *,
    rosters: list[Roster],
    players: dict[str, Player],
    traded_picks: list[DraftPick],
    positions: dict[str, str],
    ktc_value_by_player: dict[str, float],
    roster_to_user: dict[int, str],
    total_rosters: int,
    num_rounds: int = 4,
) -> dict[str, DynastyOutlook]:
    """Build a DynastyOutlook per current owner uid (offseason-safe).

    position_rankings come from KTC; projected_rank_pct from roster-value rank.
    """
    rankings = ktc_position_rankings(rosters, positions, ktc_value_by_player)
    rv_by_roster = {
        r.roster_id: sum(
            ktc_value_by_player.get(pid, 0.0) for pid in (r.players or []))
        for r in rosters
    }
    rank_pct = roster_value_rank_pct(rv_by_roster)
    out: dict[str, DynastyOutlook] = {}
    for r in rosters:
        uid = roster_to_user.get(r.roster_id)
        if not uid:
            continue
        roster_players = [
            players[pid] for pid in (r.players or []) if pid in players]
        out[uid] = build_dynasty_outlook(
            roster=r,
            roster_players=roster_players,
            traded_picks=traded_picks,
            projected_rank_pct=rank_pct.get(r.roster_id, 0.5),
            position_rankings=rankings,
            total_rosters=total_rosters,
            num_rounds=num_rounds,
        )
    return out


def _player_lite(p: Player, as_of: date) -> dict:
    return {
        "player_id": p.player_id,
        "full_name": p.full_name,
        "position": p.position,
        "age": p.age(as_of=as_of),
    }


def outlook_to_dict(outlook: DynastyOutlook, as_of: date | None = None) -> dict:
    """JSON-safe serialization (Players -> lite dicts; tuple keys -> strings)."""
    ref = as_of or date.today()
    ap = outlook.age_profile
    dc = outlook.draft_capital
    return {
        "window": outlook.window,
        "trajectory": outlook.trajectory,
        "age_profile": {
            "avg_age_by_position": ap.avg_age_by_position,
            "overall_avg_age": ap.overall_avg_age,
            "aging_risks": [_player_lite(p, ref) for p in ap.aging_risks],
            "core_young": [_player_lite(p, ref) for p in ap.core_young],
        },
        "draft_capital": {
            "picks_by_season": {
                str(k): v for k, v in dc.picks_by_season.items()},
            "picks_by_season_round": {
                f"{s}-{rd}": v for (s, rd), v in dc.picks_by_season_round.items()},
            "net_vs_average": dc.net_vs_average,
            "status": dc.status,
        },
        "draft_needs": [
            {"position": n.position, "urgency": n.urgency, "reason": n.reason}
            for n in outlook.draft_needs
        ],
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_outlook_build.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/outlook_build.py tests/test_outlook_build.py
git commit -m "feat(engine): build + json-serialize dynasty outlook per owner"
```

---

## Task 4: Persist outlooks + ranks on `ChainCacheEntry`

**Files:**
- Modify: `api/app/services/chain_cache.py:14-43`

- [ ] **Step 1: Add the two fields**

In the `ChainCacheEntry` dataclass (after `outlook_signals`), add:

```python
    # uid -> serialized DynastyOutlook (see engine/outlook_build.outlook_to_dict)
    dynasty_outlooks: dict[str, dict[str, Any]] = field(default_factory=dict)
    # uid -> {"rank": int, "of": int} by current roster KTC value
    roster_ranks: dict[str, dict[str, int]] = field(default_factory=dict)
```

Both use `field(default_factory=dict)`, so older cache files (which lack these keys) still deserialize via `ChainCacheEntry(**raw)` — missing keys fall back to the default. No schema bump required for read-compat.

- [ ] **Step 2: Verify deserialization of a pre-feature entry still works**

Run: `pytest api/tests -q -k cache` (or the existing chain-cache test module)
Expected: PASS — existing cache round-trip tests still green.

> If there is no chain-cache test, add a minimal one constructing `ChainCacheEntry(**raw)` from a dict missing the new keys and asserting the defaults are `{}`.

- [ ] **Step 3: Commit**

```bash
git add api/app/services/chain_cache.py
git commit -m "feat(api): persist dynasty outlooks + roster ranks on chain cache"
```

---

## Task 5: Grader outlook stage

Build outlooks + ranks during refresh and store them on the entry. Best-effort:
a failure here must never fail the refresh.

**Files:**
- Modify: `api/app/services/grader.py` (after the `compute_rating_signals` call, ~line 289, before the entry is constructed ~line 290+)

- [ ] **Step 1: Add the stage**

Immediately after the `compute_rating_signals` try/except block in `GraderService.run`, insert:

```python
        # --- Dynasty outlooks + roster-value ranks (offseason-safe). ---
        dynasty_outlooks: dict[str, dict] = {}
        roster_ranks: dict[str, dict] = {}
        try:
            from sleeper_dynasty.engine.outlook_build import (
                build_outlooks_by_owner, outlook_to_dict, roster_value_ranks,
            )
            from sleeper_dynasty.models.player import build_players
            players_obj = build_players(raw_players)
            positions = supporting.get("positions") or {}
            ktc_now = supporting["ktc_by_player_id"]
            ktc_floats = {
                pid: float(v.superflex_value)
                for pid, v in ktc_now.items()
                if v is not None and v.superflex_value is not None
            }
            r2u_current = {r.roster_id: r.owner_id for r in current_rosters}
            outlooks = build_outlooks_by_owner(
                rosters=current_rosters, players=players_obj,
                traded_picks=traded_picks, positions=positions,
                ktc_value_by_player=ktc_floats, roster_to_user=r2u_current,
                total_rosters=len(current_rosters),
                num_rounds=num_draft_rounds)
            dynasty_outlooks = {
                uid: outlook_to_dict(ol) for uid, ol in outlooks.items()}
            # rv was computed above for strength tiers; reuse it for ranks.
            roster_ranks = roster_value_ranks(rv)
        except Exception:
            log.exception("dynasty outlook stage skipped")
```

> NOTE: `rv` (owner_id -> roster KTC value) is built earlier in `run` for `strength_tiers`
> (grader.py ~line 130). If `rv` is not in scope at this point, recompute it inline:
> `rv = {r.owner_id: sum(float(ktc_now[p].superflex_value) for p in (r.players or []) if ktc_now.get(p) and ktc_now[p].superflex_value is not None) for r in current_rosters}`.

- [ ] **Step 2: Pass the new fields into the `ChainCacheEntry(...)` constructor**

Find where `entry = ChainCacheEntry(...)` is built (grader.py, near the `outcome_signals=...,
outlook_signals=...,` kwargs ~line 308) and add:

```python
            dynasty_outlooks=dynasty_outlooks,
            roster_ranks=roster_ranks,
```

- [ ] **Step 3: Manual smoke check**

Run a refresh against a known cached league (or the existing grader integration test if
present) and confirm no new warnings and that the entry carries the fields:

Run: `pytest api/tests -q -k grader`
Expected: PASS. If no grader test exists, skip — Task 7's test covers the read path.

- [ ] **Step 4: Commit**

```bash
git add api/app/services/grader.py
git commit -m "feat(api): compute + persist dynasty outlooks during refresh"
```

---

## Task 6: API view models

**Files:**
- Modify: `api/app/models/owner.py`

- [ ] **Step 1: Add the view models + optional fields**

Add to `api/app/models/owner.py` (before `OwnerDetailResp`):

```python
class PlayerLite(BaseModel):
    player_id: str
    full_name: str
    position: str
    age: int | None = None


class AgeProfileView(BaseModel):
    avg_age_by_position: dict[str, float]
    overall_avg_age: float
    aging_risks: list[PlayerLite] = []
    core_young: list[PlayerLite] = []


class DraftCapitalView(BaseModel):
    picks_by_season: dict[str, int]
    picks_by_season_round: dict[str, int]
    net_vs_average: float
    status: str
    total_value: float = 0.0   # KTC value of held future picks (outlook signal)


class DraftNeedView(BaseModel):
    position: str
    urgency: str
    reason: str


class OutlookView(BaseModel):
    window: str
    trajectory: str
    age_profile: AgeProfileView
    draft_capital: DraftCapitalView
    draft_needs: list[DraftNeedView] = []


class RankView(BaseModel):
    rank: int
    of: int


class DraftSkillView(BaseModel):
    score: float
    rank: int
    of: int
```

Then add these optional fields to `OwnerDetailResp`:

```python
    outlook: OutlookView | None = None
    roster_rank: RankView | None = None
    draft_skill: DraftSkillView | None = None
```

- [ ] **Step 2: Confirm the module imports cleanly**

Run: `python -c "import app.models.owner"` from the `api/` directory (or `pytest api/tests -q -k owner`).
Expected: no import error.

- [ ] **Step 3: Commit**

```bash
git add api/app/models/owner.py
git commit -m "feat(api): outlook view models on OwnerDetailResp"
```

---

## Task 7: Populate the new fields in `owner_view`

**Files:**
- Modify: `api/app/services/owner_view.py`
- Test: `api/tests/test_owner_view_outlook.py`

- [ ] **Step 1: Write the failing test**

```python
# api/tests/test_owner_view_outlook.py
from app.services.chain_cache import ChainCacheEntry
from app.services.owner_view import build_owner_detail


def _entry(**over):
    base = dict(
        league_id="L", chain=[], resolved_trades=[], grades={},
        owners={"uA": {"owner_name": "Alice"}, "uB": {"owner_name": "Bob"}},
        playoff_weeks_by_league={}, roster_to_user_by_league={},
        league_name_by_id={}, league_season_by_id={}, cached_at="2026-01-01",
    )
    base.update(over)
    return ChainCacheEntry(**base)


def test_outlook_exposed_when_present():
    entry = _entry(
        dynasty_outlooks={"uA": {
            "window": "Ascending", "trajectory": "young + pick-rich",
            "age_profile": {"avg_age_by_position": {"RB": 23.0},
                            "overall_avg_age": 24.0, "aging_risks": [],
                            "core_young": [{"player_id": "wr1",
                                            "full_name": "WR1",
                                            "position": "WR", "age": 22}]},
            "draft_capital": {"picks_by_season": {"2027": 5},
                              "picks_by_season_round": {"2027-1": 2},
                              "net_vs_average": 3.0, "status": "pick-rich"},
            "draft_needs": [{"position": "TE", "urgency": "developing",
                             "reason": "thin at TE"}],
        }},
        roster_ranks={"uA": {"rank": 1, "of": 2}},
        outlook_signals={"uA": {"roster_value": 900.0, "draft_capital": 1200.0,
                                "draft_skill": 0.4, "youth": -24.0},
                         "uB": {"roster_value": 100.0, "draft_capital": 0.0,
                                "draft_skill": -0.2, "youth": -27.0}},
    )
    resp = build_owner_detail(entry, "uA")
    assert resp is not None
    assert resp.outlook.window == "Ascending"
    assert resp.outlook.draft_capital.total_value == 1200.0
    assert resp.roster_rank.rank == 1 and resp.roster_rank.of == 2
    # draft_skill rank: uA (0.4) ranks above uB (-0.2) -> rank 1 of 2
    assert resp.draft_skill.rank == 1 and resp.draft_skill.of == 2


def test_outlook_absent_degrades_gracefully():
    entry = _entry()  # pre-feature cache: no outlook fields
    resp = build_owner_detail(entry, "uA")
    assert resp is not None
    assert resp.outlook is None
    assert resp.roster_rank is None
    assert resp.draft_skill is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest api/tests/test_owner_view_outlook.py -v`
Expected: FAIL (`AttributeError`/`None` — fields not populated yet).

- [ ] **Step 3: Populate the fields in `build_owner_detail`**

Add the imports at the top of `api/app/services/owner_view.py`:

```python
from app.models.owner import (
    AgeProfileView, DraftCapitalView, DraftNeedView, DraftSkillView,
    OutlookView, OwnerDetailResp, OwnerTradeRow, PlayerLite, RankView, SeasonArc,
)
```

Just before the `return OwnerDetailResp(...)` at the end, assemble the optional blocks:

```python
    # --- Optional outlook block (null on pre-feature caches). ---
    outlook_view: OutlookView | None = None
    raw_ol = (entry.dynasty_outlooks or {}).get(user_id)
    if raw_ol:
        ol_sig = (entry.outlook_signals or {}).get(user_id, {})
        ap = raw_ol["age_profile"]
        dc = raw_ol["draft_capital"]
        outlook_view = OutlookView(
            window=raw_ol["window"], trajectory=raw_ol["trajectory"],
            age_profile=AgeProfileView(
                avg_age_by_position=ap["avg_age_by_position"],
                overall_avg_age=ap["overall_avg_age"],
                aging_risks=[PlayerLite(**p) for p in ap["aging_risks"]],
                core_young=[PlayerLite(**p) for p in ap["core_young"]]),
            draft_capital=DraftCapitalView(
                picks_by_season=dc["picks_by_season"],
                picks_by_season_round=dc["picks_by_season_round"],
                net_vs_average=dc["net_vs_average"], status=dc["status"],
                total_value=float(ol_sig.get("draft_capital", 0.0) or 0.0)),
            draft_needs=[DraftNeedView(**n) for n in raw_ol["draft_needs"]])

    roster_rank_view: RankView | None = None
    raw_rank = (entry.roster_ranks or {}).get(user_id)
    if raw_rank:
        roster_rank_view = RankView(rank=raw_rank["rank"], of=raw_rank["of"])

    # --- Draft-skill rank across all owners with a score. ---
    draft_skill_view: DraftSkillView | None = None
    skills = {
        u: float(sig.get("draft_skill", 0.0) or 0.0)
        for u, sig in (entry.outlook_signals or {}).items()
        if "draft_skill" in sig
    }
    if user_id in skills:
        ordered = sorted(skills, key=lambda u: skills[u], reverse=True)
        draft_skill_view = DraftSkillView(
            score=skills[user_id],
            rank=ordered.index(user_id) + 1, of=len(ordered))
```

Then add to the `OwnerDetailResp(...)` constructor kwargs:

```python
        outlook=outlook_view,
        roster_rank=roster_rank_view,
        draft_skill=draft_skill_view,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest api/tests/test_owner_view_outlook.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Run the full API suite**

Run: `pytest api/tests -q`
Expected: PASS — existing owner-view tests unaffected (new fields default null).

- [ ] **Step 6: Commit**

```bash
git add api/app/services/owner_view.py api/tests/test_owner_view_outlook.py
git commit -m "feat(api): expose outlook, roster rank, draft skill on owner detail"
```

---

## Task 8: Mirror the new shape in TypeScript types

No UI yet (Plan 2), but keep the contract in sync so Plan 2 starts from a typed response.

**Files:**
- Modify: `web/lib/types.ts`

- [ ] **Step 1: Add the types**

Add to `web/lib/types.ts` (near `OwnerDetailResp`):

```typescript
export interface PlayerLite {
  player_id: string;
  full_name: string;
  position: string;
  age: number | null;
}

export interface AgeProfileView {
  avg_age_by_position: Record<string, number>;
  overall_avg_age: number;
  aging_risks: PlayerLite[];
  core_young: PlayerLite[];
}

export interface DraftCapitalView {
  picks_by_season: Record<string, number>;
  picks_by_season_round: Record<string, number>;
  net_vs_average: number;
  status: string;
  total_value: number;
}

export interface DraftNeedView {
  position: string;
  urgency: string;
  reason: string;
}

export interface OutlookView {
  window: string;
  trajectory: string;
  age_profile: AgeProfileView;
  draft_capital: DraftCapitalView;
  draft_needs: DraftNeedView[];
}

export interface RankView { rank: number; of: number; }
export interface DraftSkillView { score: number; rank: number; of: number; }
```

Then extend the existing `OwnerDetailResp` interface with optional fields:

```typescript
  outlook?: OutlookView | null;
  roster_rank?: RankView | null;
  draft_skill?: DraftSkillView | null;
```

- [ ] **Step 2: Typecheck**

Run: `cd web && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add web/lib/types.ts
git commit -m "feat(web): types for outlook on OwnerDetailResp"
```

---

## Self-Review

**Spec coverage:**
- Dynasty outlook (age/young core/aging risk, draft capital, needs, window/trajectory) → Tasks 2, 3, 5, 6, 7. ✓
- Roster-value-rank proxy → Tasks 2, 5, 7 (`roster_value_ranks`, `roster_rank`). ✓
- Past draft skill (score + rank) → Task 7 (`draft_skill` from already-persisted `outlook_signals`). ✓
- Persistence through the shared refresh path → Tasks 4, 5. ✓
- Backward-compatible API (new fields optional; pre-feature caches degrade) → Tasks 4, 6, 7 (`test_outlook_absent_degrades_gracefully`). ✓
- Per-owner compute failure never breaks refresh → Task 5 (try/except). ✓
- Franchise blurb → **deferred to Plan 3** (intentional, not a gap).
- Web tabbed UI → **deferred to Plan 2** (intentional). ✓

**Placeholder scan:** none — every code step has concrete content. Two NOTE callouts flag
constructor-kwarg verification (`Roster`) and `rv` scope, which are confirm-and-adjust, not
placeholders.

**Type consistency:** `outlook_to_dict` output keys match `AgeProfileView`/`DraftCapitalView`/
`DraftNeedView`/`OutlookView` (Task 3 ↔ Task 6 ↔ Task 7). `roster_value_ranks` returns
`{"rank","of"}` consumed by `RankView` (Task 2 ↔ 6 ↔ 7). `total_value` is sourced from
`outlook_signals[uid]["draft_capital"]` (the KTC holdings value per `rating_signals.py:120`),
not from the count in `DraftCapital.net_vs_average` — consistent across Tasks 5/7.
TS interfaces (Task 8) mirror the Pydantic models field-for-field.
