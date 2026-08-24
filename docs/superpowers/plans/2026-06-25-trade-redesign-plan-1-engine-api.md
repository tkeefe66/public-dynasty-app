# Trade Redesign — Plan 1: Engine + API Foundation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `production_started` metric (started points, all weeks), a per-side deployment `start_pct` that rolls through the flip lineage, and an engine-derived "twist" callout — surfaced on the trade-detail API response.

**Architecture:** Extend the existing `TradeGrade`/`AssetLine` dataclasses with one new started-all-weeks production figure (computed via the existing `_points_while_owned(starters_only=True)` with no phase filter). The API (`trade_view.py`) sums started/total over each side's *realized* breakdown rows (which already fold flipped-pick lineage) to produce `start_pct`, and selects a deterministic "twist" fact. No UI in this plan.

**Tech Stack:** Python 3.11, pytest, FastAPI, Pydantic. Engine in `src/sleeper_dynasty/`, backend in `api/`.

## Global Constraints

- Five headline metrics keep their names; the new one is **Started Points** (`production_started`) = received-only, **starters-only, all weeks** (NOT a phase split; NOT bench-inclusive).
- `production_started` ≠ `production_regular + production_playoff + production_toilet` — started placement/consolation weeks fall outside all three phase buckets. This is the whole reason the metric exists; a test must pin it.
- Production fields are **received-only** (points while owned post-trade). Picks carry 0 production.
- `start_pct = production_started / production_total`; when `production_total == 0`, `start_pct` is `None` (never divide by zero, never show a fake 0%).
- Run engine tests with `.venv/bin/python -m pytest` from repo root; API tests from `api/` with `../.venv/bin/python -m pytest`.
- Commit after each task. Branch: `trade-redesign`.

---

### Task 1: Engine — `production_started` metric

**Files:**
- Modify: `src/sleeper_dynasty/models/trade.py:113-127` (AssetLine), `:139-158` (TradeGrade)
- Modify: `src/sleeper_dynasty/engine/trade_grader.py` (`build_asset_breakdown` ~329-346, `grade_trade` ~389-446)
- Test: `tests/test_trade_grader.py`

**Interfaces:**
- Produces: `AssetLine.production_started: float`; `TradeGrade.production_started: dict[str, float]`. Both populated by `grade_trade(...)` and `build_asset_breakdown(...)` exactly like the existing started-phase fields, but with no `phase_filter`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_trade_grader.py`. This pins that started-all is its own thing: a player started in a regular week, a playoff week, and a **placement** week (phase `"placement"`, which is neither regular/playoff/toilet) — `production_started` must include all three started weeks, while the phase fields exclude the placement week, and `production_total` adds a benched week on top.

```python
from datetime import datetime
from sleeper_dynasty.models.trade import PlayerAsset, PickAsset, Trade, TradeSide, ResolvedTrade
from sleeper_dynasty.engine.trade_grader import grade_trade


def _started_trade():
    # Mike receives p1 (week-1 trade, league L season 2024, roster 1 = Mike).
    player = PlayerAsset(player_id="p1", name="Bijan Robinson")
    pick = PickAsset(season=2025, round=1, original_owner_user_id="u_mike")
    mike = TradeSide("u_mike", received=[player], given=[pick])
    tom = TradeSide("u_tom", received=[pick], given=[player])
    t = Trade("t1", "L", 2024, 1, datetime(2024, 9, 1),
              {"u_mike": mike, "u_tom": tom})
    return ResolvedTrade(trade=t, sides={"u_mike": mike, "u_tom": tom})


def test_production_started_counts_all_started_weeks_incl_placement():
    rt = _started_trade()
    matchups = {
        # regular started: 10
        ("L", 5, 1): {"players": ["p1"], "starters": ["p1"],
                      "players_points": {"p1": 10.0},
                      "team_points": 100.0, "opponent_points": 90.0},
        # playoff started (winners bracket): 20
        ("L", 15, 1): {"players": ["p1"], "starters": ["p1"],
                       "players_points": {"p1": 20.0},
                       "team_points": 100.0, "opponent_points": 90.0},
        # placement game started (3rd-place; neither winners nor losers bracket): 7
        ("L", 16, 1): {"players": ["p1"], "starters": ["p1"],
                       "players_points": {"p1": 7.0},
                       "team_points": 100.0, "opponent_points": 90.0},
        # benched regular week: 4 (counts toward total, not started)
        ("L", 6, 1): {"players": ["p1"], "starters": [],
                      "players_points": {"p1": 4.0},
                      "team_points": 100.0, "opponent_points": 90.0},
    }
    phase_by_lwr = {("L", 15, 1): "playoff", ("L", 16, 1): "placement"}
    grade = grade_trade(
        rt, ktc_values={}, matchups=matchups,
        roster_to_user_by_league={"L": {1: "u_mike"}},
        playoff_week_start_by_league={"L": 15},
        phase_by_lwr=phase_by_lwr,
        league_season_by_id={"L": 2024},
    )
    started = grade.production_started["u_mike"]
    phases = (grade.production_regular["u_mike"]
              + grade.production_playoff["u_mike"]
              + grade.production_toilet["u_mike"])
    assert started == 37.0            # 10 + 20 + 7 (all started weeks)
    assert phases == 30.0             # 10 + 20 (placement excluded from phases)
    assert started > phases           # the metric is NOT the phase sum
    assert grade.production_total["u_mike"] == 41.0   # +4 benched
    # per-asset line carries it too
    line = grade.breakdown["u_mike"][0]
    assert line.production_started == 37.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_trade_grader.py::test_production_started_counts_all_started_weeks_incl_placement -v`
Expected: FAIL — `AttributeError: 'TradeGrade' object has no attribute 'production_started'` (and/or AssetLine).

- [ ] **Step 3: Add the dataclass fields**

In `src/sleeper_dynasty/models/trade.py`, `AssetLine` (after `production_toilet`):

```python
    production_toilet: float
    production_started: float = 0.0   # starters-only, all weeks (not a phase split)
```

In `TradeGrade` (after `production_toilet`):

```python
    production_toilet: dict[str, float] = field(default_factory=dict)
    production_started: dict[str, float] = field(default_factory=dict)
```

- [ ] **Step 4: Compute it in the engine**

In `src/sleeper_dynasty/engine/trade_grader.py`, `build_asset_breakdown`, the `PlayerAsset` branch — add `production_started` to the `AssetLine(...)` (starters_only, no phase_filter):

```python
                    production_toilet=_points_while_owned(
                        a.player_id, uid, starters_only=True, phase_filter="toilet", **common),
                    production_started=_points_while_owned(
                        a.player_id, uid, starters_only=True, **common),
```

In the `PickAsset` branch, add `production_started=0.0` to the `AssetLine(...)`:

```python
                    production_total=0.0, production_regular=0.0,
                    production_playoff=0.0, production_toilet=0.0,
                    production_started=0.0,
```

In `grade_trade`, the `TradeGrade(...)` return — add after `production_toilet`:

```python
        production_toilet=grade_hindsight_production(
            rt, phase_filter="toilet", **started_common
        ),
        production_started=grade_hindsight_production(
            rt, **{k: v for k, v in started_common.items()}
        ),
```

Note: `started_common` already sets `starters_only=True`; passing it with **no** `phase_filter` yields started-all-weeks. (If `grade_hindsight_production` requires `phase_filter` to default to "all weeks" when omitted, confirm its signature defaults `phase_filter=None` → no filtering; it does, per the bench/started callers.)

In the per-side rollup loop (the `rec.production_* += g.production_*` block ~443), add:

```python
            rec.production_toilet += g.production_toilet.get(uid, 0.0)
            rec.production_started += g.production_started.get(uid, 0.0)
```

(Only if `OwnerTradeRecord` is extended; if that aggregate isn't needed yet, skip the rollup line and leave `OwnerTradeRecord` unchanged — `production_started` on the per-trade `TradeGrade` is what Plan 1 needs.)

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_trade_grader.py::test_production_started_counts_all_started_weeks_incl_placement -v`
Expected: PASS.

- [ ] **Step 6: Run the full grader + story suites for regressions**

Run: `.venv/bin/python -m pytest tests/test_trade_grader.py tests/test_trade_grader_tiering.py tests/test_trade_story_engine.py -q`
Expected: all PASS (existing AssetLine constructions still valid because `production_started` defaults to 0.0).

- [ ] **Step 7: Commit**

```bash
git add src/sleeper_dynasty/models/trade.py src/sleeper_dynasty/engine/trade_grader.py tests/test_trade_grader.py
git commit -m "feat(engine): add production_started (started points, all weeks)"
```

---

### Task 2: API — surface `production_started` + per-side `start_pct`

**Files:**
- Modify: `api/app/models/trade.py` (AssetLine model ~:30, TradeSideView ~:53-70)
- Modify: `api/app/services/trade_view.py` (`build_trade_detail` ~205-240)
- Test: `api/tests/test_trade_view_story.py` (or the nearest trade_view test module)

**Interfaces:**
- Consumes: `AssetLine.production_started` (Task 1).
- Produces: API `AssetLine.production_started: float`; `TradeSideView.production_started: float` and `TradeSideView.start_pct: float | None`. `start_pct` is computed over the side's **realized** breakdown rows so flipped-pick became-players fold in.

- [ ] **Step 1: Write the failing test**

The realized breakdown already exists as `enriched_breakdown[uid]` (a list of API `AssetLine`s, including became rows for flipped picks). Test that `start_pct` = sum(started)/sum(total) over those rows, and that a flipped pick that became 2 players folds both in.

```python
# api/tests/test_trade_view_start_pct.py
from app.services.trade_view import _side_start_pct


def test_start_pct_rolls_up_realized_rows():
    # Two realized rows: a kept player + a became-player from a flipped pick.
    rows = [
        {"production_started": 600.0, "production_total": 705.0},  # Bijan kept
        {"production_started": 90.0, "production_total": 240.0},   # became MHJ
        {"production_started": 20.0, "production_total": 65.0},    # became Wright
    ]
    pct = _side_start_pct(rows)
    assert round(pct, 3) == round((600 + 90 + 20) / (705 + 240 + 65), 3)  # 0.703


def test_start_pct_none_when_no_total():
    assert _side_start_pct([{"production_started": 0.0, "production_total": 0.0}]) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && ../.venv/bin/python -m pytest tests/test_trade_view_start_pct.py -v`
Expected: FAIL — `ImportError: cannot import name '_side_start_pct'`.

- [ ] **Step 3: Add the helper + wire it in**

In `api/app/services/trade_view.py`, add a module-level helper (accepts either AssetLine objects or dicts):

```python
def _side_start_pct(rows) -> float | None:
    """Deployment %: started ÷ total over a side's realized rows. None if total is 0."""
    def g(r, k):
        return getattr(r, k, None) if not isinstance(r, dict) else r.get(k)
    started = sum(float(g(r, "production_started") or 0.0) for r in rows)
    total = sum(float(g(r, "production_total") or 0.0) for r in rows)
    return (started / total) if total > 0 else None
```

In `build_trade_detail`, where each `TradeSideView(...)` is built, add (alongside `production_total=...`):

```python
            production_started=float(
                (grade.get("production_started") or {}).get(uid, 0) or 0
            ),
            start_pct=_side_start_pct(enriched_breakdown.get(uid, [])),
```

- [ ] **Step 4: Add the Pydantic fields**

In `api/app/models/trade.py`, the `AssetLine` response model (near `production_total: float = 0.0`):

```python
    production_total: float = 0.0
    production_started: float = 0.0
```

In `TradeSideView` (near its `production_total: float`):

```python
    production_total: float
    production_started: float = 0.0
    start_pct: float | None = None
```

- [ ] **Step 5: Run test + full trade_view suite**

Run: `cd api && ../.venv/bin/python -m pytest tests/test_trade_view_start_pct.py tests/test_trade_view_story.py -v`
Expected: PASS (new + existing).

- [ ] **Step 6: Commit**

```bash
git add api/app/models/trade.py api/app/services/trade_view.py api/tests/test_trade_view_start_pct.py
git commit -m "feat(api): surface production_started + per-side start_pct"
```

---

### Task 3: API — engine-derived "twist" callout

**Files:**
- Modify: `api/app/services/trade_view.py` (add selector + attach to response)
- Modify: `api/app/models/trade.py` (`TradeDetailResp` ~:149 — add `twist` field; add a `TwistView` model)
- Test: `api/tests/test_trade_view_twist.py`

**Interfaces:**
- Consumes: per-side realized rows (with `production_started`, `production_total`, `start_pct`, `terminal_state`, `flip`), owner display names.
- Produces: `TradeDetailResp.twist: TwistView | None` where `TwistView = {kind: str, owner: str, label: str, detail: str}`. `kind ∈ {"dropped", "low_deploy", "flip", "none"}`.

- [ ] **Step 1: Write the failing test**

```python
# api/tests/test_trade_view_twist.py
from app.services.trade_view import _select_twist


def test_twist_prefers_dropped_high_value_asset():
    sides = [
        {"owner_name": "Tom", "start_pct": 0.4, "breakdown": [
            {"label": "Nick Chubb", "terminal_state": "dropped", "ktc": 0.0,
             "production_total": 118.0},
        ]},
        {"owner_name": "Mikey", "start_pct": 0.85, "breakdown": [
            {"label": "Bijan Robinson", "terminal_state": "on_roster", "ktc": 9998.0,
             "production_total": 705.0},
        ]},
    ]
    t = _select_twist(sides)
    assert t["kind"] == "dropped" and t["owner"] == "Tom"
    assert "Chubb" in t["detail"]


def test_twist_falls_back_to_low_deployment():
    sides = [
        {"owner_name": "Tom", "start_pct": 0.40, "breakdown": [
            {"label": "X", "terminal_state": "on_roster", "ktc": 100.0, "production_total": 50.0}]},
        {"owner_name": "Mikey", "start_pct": 0.88, "breakdown": [
            {"label": "Y", "terminal_state": "on_roster", "ktc": 100.0, "production_total": 50.0}]},
    ]
    t = _select_twist(sides)
    assert t["kind"] == "low_deploy" and t["owner"] == "Tom"


def test_twist_none_when_unremarkable():
    sides = [
        {"owner_name": "A", "start_pct": 0.8, "breakdown": [
            {"label": "X", "terminal_state": "on_roster", "ktc": 100.0, "production_total": 50.0}]},
        {"owner_name": "B", "start_pct": 0.82, "breakdown": [
            {"label": "Y", "terminal_state": "on_roster", "ktc": 100.0, "production_total": 50.0}]},
    ]
    assert _select_twist(sides)["kind"] == "none"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && ../.venv/bin/python -m pytest tests/test_trade_view_twist.py -v`
Expected: FAIL — `cannot import name '_select_twist'`.

- [ ] **Step 3: Implement the selector**

In `api/app/services/trade_view.py`:

```python
def _select_twist(sides) -> dict:
    """Pick one engine-derived 'twist' fact for the hero callout.

    Priority: a dropped asset (the haul evaporated) > a clearly low deployment
    side (<50% started while the other side is healthy) > nothing.
    """
    def rows(s):
        return s.get("breakdown") or []
    # 1. dropped asset, highest total points among dropped
    dropped = []
    for s in sides:
        for r in rows(s):
            if (r.get("terminal_state") == "dropped"):
                dropped.append((s["owner_name"], r))
    if dropped:
        owner, r = max(dropped, key=lambda t: float(t[1].get("production_total") or 0.0))
        return {"kind": "dropped", "owner": owner, "label": "Dropped",
                "detail": f"{owner} dropped {r.get('label')}"}
    # 2. low deployment (a side started <50% while another cleared 70%)
    pcts = [(s["owner_name"], s.get("start_pct")) for s in sides if s.get("start_pct") is not None]
    if pcts:
        low_owner, low = min(pcts, key=lambda t: t[1])
        high = max((p for _, p in pcts), default=0.0)
        if low < 0.5 and high >= 0.7:
            return {"kind": "low_deploy", "owner": low_owner, "label": "Barely played",
                    "detail": f"{low_owner} started just {round(low * 100)}% of the haul"}
    return {"kind": "none", "owner": "", "label": "", "detail": ""}
```

- [ ] **Step 4: Add the response model + attach**

In `api/app/models/trade.py`, add a model and field:

```python
class TwistView(BaseModel):
    kind: str
    owner: str
    label: str
    detail: str
```

Add to `TradeDetailResp`:

```python
    twist: TwistView | None = None
```

In `build_trade_detail`, after the side views are assembled, build a lightweight list of dicts for the selector and attach to the response. Convert `TradeSideView`s to the dict shape the selector reads (owner_name, start_pct, breakdown rows as dicts with label/terminal_state/ktc/production_total). Set `twist=TwistView(**_select_twist(side_dicts))` when kind != "none", else `None`.

- [ ] **Step 5: Run test + trade_view suite**

Run: `cd api && ../.venv/bin/python -m pytest tests/test_trade_view_twist.py tests/test_trade_view_story.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add api/app/models/trade.py api/app/services/trade_view.py api/tests/test_trade_view_twist.py
git commit -m "feat(api): engine-derived twist callout for trade hero"
```

---

## Self-Review

**Spec coverage (Plan 1 scope only):**
- `production_started` metric → Task 1 ✓
- start% rollup through lineage → Task 2 ✓ (over realized `enriched_breakdown`)
- engine-computed callouts → Task 3 (twist) ✓; started/value margins are trivially derivable on the FE from `production_started` + `received_ktc` per side (no task needed) ✓
- at-trade value surfacing → already present (`at_trade_ktc_swing` in `build_trade_detail`); no Plan 1 task ✓
- LLM structured story, hero/table/chart UI → **Plans 2 & 3** (out of scope here) ✓

**Placeholder scan:** Step 4 of Task 1 and Step 4 of Task 3 reference existing structures ("the per-side rollup loop", "after the side views are assembled") rather than full file rewrites — acceptable because exact line anchors and the inserted code are given; the implementer edits in place. No TBD/TODO.

**Type consistency:** `production_started` is `float` on both AssetLine dataclass and AssetLine Pydantic model; `start_pct: float | None`; `_side_start_pct` returns `float | None`; `_select_twist` returns the dict that `TwistView` consumes. Names consistent across tasks.

**Open verification for the implementer:** confirm `grade_hindsight_production` treats an omitted `phase_filter` as "all weeks" (it does for the existing bench/started callers); if it requires an explicit sentinel, pass `phase_filter=None`.
