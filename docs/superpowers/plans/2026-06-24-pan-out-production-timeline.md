> _Historical doc — paths/names have changed. Repo is now `Code Apps/public-dynasty` (GitHub `tkeefe66/public-dynasty-app`), Railway project **shimmering-nature**, live at https://ffbdynasty.com. Ignore stale refs to `sleeper-dynasty` / `sleeper-trade-grader` / `web-production-f949`._

# Pan-Out Production Timeline Implementation Plan (Phase 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the KTC-value "DID IT PAN OUT?" curves (per-trade + owner-aggregate) with cumulative *production* timelines on a real (season, week) calendar axis, with a metric switch (Total/Regular/Playoff/Toilet), a side toggle, per-player/per-trade drill, and a production-margin verdict.

**Architecture:** A pure per-week production primitive mirrors the existing `value_series`/`lineage` split. `trade_grader.player_week_points` returns per-`(season,week)` points for a player while owned (the existing `_points_while_owned` becomes its sum). A new pure module `engine/production_series.py` holds the calendar axis + cumulative + merge + verdict math. The grader assembles a payload (per-trade per-side per-metric cumulative series + verdicts, owner received/given aggregates) cached on `ChainCacheEntry`. The API surfaces it; new React components render a combined timeline.

**Tech Stack:** Python 3.11 / pytest / dataclasses (engine), FastAPI + Pydantic (api), Next.js 14 + React + inline SVG + Tailwind + vitest (web).

**Spec:** `docs/superpowers/specs/2026-06-24-pan-out-production-timeline-design.md`

**Key shared names (must stay consistent across tasks):**
- `WeekKey = tuple[int, int]` — `(season, week)`.
- Metrics: `"total" | "regular" | "playoff" | "toilet"`.
- `METRIC_GATES: dict[str, tuple[bool, str | None]]` = `{"total": (False, None), "regular": (True, "regular"), "playoff": (True, "playoff"), "toilet": (True, "toilet")}` — `(starters_only, phase_filter)`.
- JSON series point: `[season, week, value]` (3-element list). Frontend type: `{ season, week, value }`.
- `MIN_GAMES_FOR_VERDICT = 3` — fewer post-trade weeks of data ⇒ "too early".

---

## Task 1: Extract per-week points in the engine (refactor, no behavior change)

Pull the per-week accumulation loop out of `_points_while_owned` into a reusable `player_week_points` that returns `{(season, week): points}`. `_points_while_owned` becomes `sum(...values())`, so existing grader tests still pass.

**Files:**
- Modify: `src/sleeper_dynasty/engine/trade_grader.py:218-252`
- Test: `tests/engine/test_player_week_points.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/engine/test_player_week_points.py
from sleeper_dynasty.engine.trade_grader import player_week_points
from sleeper_dynasty.engine.trade_history import ResolvedTrade  # adjust import if ResolvedTrade lives elsewhere
from tests.engine.conftest import make_resolved_trade  # reuse existing helper if present; else build inline


def _matchups():
    # (league_id, week, roster_id) -> entry. Player "p1" on roster 1 (user "u1").
    return {
        ("L1", 5, 1): {"players": ["p1"], "starters": ["p1"], "players_points": {"p1": 10.0}},
        ("L1", 6, 1): {"players": ["p1"], "starters": [],     "players_points": {"p1": 7.0}},  # benched
    }


def test_player_week_points_returns_per_week_started_and_total(make_rt_week4_L1_u1):
    rt = make_rt_week4_L1_u1  # a ResolvedTrade in L1 week 4, side u1 (fixture, see Step 3 note)
    r2u = {"L1": {1: "u1"}}
    total = player_week_points("p1", "u1", matchups=_matchups(), roster_to_user_by_league=r2u,
                               rt=rt, league_season_by_id={"L1": 2024}, starters_only=False)
    assert total == {(2024, 5): 10.0, (2024, 6): 7.0}
    started = player_week_points("p1", "u1", matchups=_matchups(), roster_to_user_by_league=r2u,
                                 rt=rt, league_season_by_id={"L1": 2024}, starters_only=True)
    assert started == {(2024, 5): 10.0}  # week 6 benched → omitted
```

> Note: reuse whatever ResolvedTrade construction the existing `tests/engine/test_trade_grader.py` uses (grep it for `ResolvedTrade(` / a `make_resolved_trade` helper) to build `make_rt_week4_L1_u1` — a trade in league `L1`, season 2024, week 4, with side `u1`. If those tests use a fixture, add this one beside them in that file instead of a new file.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/engine/test_player_week_points.py -v`
Expected: FAIL — `ImportError: cannot import name 'player_week_points'`.

- [ ] **Step 3: Implement `player_week_points` and refactor `_points_while_owned`**

Replace `trade_grader.py:218-252` with:

```python
def player_week_points(
    pid: str,
    uid: str,
    *,
    matchups: dict[tuple[str, int, int], dict],
    roster_to_user_by_league: dict[str, dict[int, str]],
    rt: "ResolvedTrade",
    league_season_by_id: dict[str, int] | None = None,
    starters_only: bool = False,
    phase_filter: str | None = None,
    phase_by_lwr: dict[tuple[str, int, int], str] | None = None,
    playoff_week_start_by_league: dict[str, int] | None = None,
) -> dict[tuple[int, int], float]:
    """Points ``pid`` scored each (season, week) while owned by ``uid``, post-trade,
    optionally gated on a bracket phase. Keys are ``(season, week)``; weeks with no
    qualifying entry are omitted. The per-week basis behind the production timeline;
    ``_points_while_owned`` is its sum."""
    league_season_by_id = league_season_by_id or {}
    phase_by_lwr = phase_by_lwr or {}
    playoff_week_start_by_league = playoff_week_start_by_league or {}
    roster_field = "starters" if starters_only else "players"
    out: dict[tuple[int, int], float] = {}
    for (lg, wk, rid), entry in matchups.items():
        if not _is_post_trade(lg, wk, rt, league_season_by_id):
            continue
        if roster_to_user_by_league.get(lg, {}).get(rid) != uid:
            continue
        if phase_filter:
            ps = playoff_week_start_by_league.get(lg, 15)
            phase = "regular" if wk < ps else phase_by_lwr.get((lg, wk, rid), "dropped")
            if phase != phase_filter:
                continue
        if pid not in (entry.get(roster_field) or []):
            continue
        season = league_season_by_id.get(lg, 0)
        pts = float((entry.get("players_points") or {}).get(pid, 0.0) or 0.0)
        out[(season, wk)] = out.get((season, wk), 0.0) + pts
    return out


def _points_while_owned(
    pid: str,
    uid: str,
    *,
    matchups: dict[tuple[str, int, int], dict],
    roster_to_user_by_league: dict[str, dict[int, str]],
    rt: "ResolvedTrade",
    league_season_by_id: dict[str, int] | None = None,
    starters_only: bool = False,
    phase_filter: str | None = None,
    phase_by_lwr: dict[tuple[str, int, int], str] | None = None,
    playoff_week_start_by_league: dict[str, int] | None = None,
) -> float:
    """Points ``pid`` scored while owned by ``uid``, post-trade, optionally gated on a
    bracket phase. Sum of ``player_week_points``."""
    return sum(player_week_points(
        pid, uid, matchups=matchups, roster_to_user_by_league=roster_to_user_by_league,
        rt=rt, league_season_by_id=league_season_by_id, starters_only=starters_only,
        phase_filter=phase_filter, phase_by_lwr=phase_by_lwr,
        playoff_week_start_by_league=playoff_week_start_by_league,
    ).values())
```

- [ ] **Step 4: Run the new test + the full existing grader suite**

Run: `pytest tests/engine/test_player_week_points.py tests/engine/test_trade_grader.py -v`
Expected: PASS (new test passes; `_points_while_owned` behavior unchanged so existing tests stay green).

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/trade_grader.py tests/engine/test_player_week_points.py
git commit -m "refactor(engine): extract player_week_points; _points_while_owned sums it"
```

---

## Task 2: Pure production-series math module

A dependency-free module for the calendar axis, cumulative accumulation, and merging — the production analog of `value_series`'s pure helpers.

**Files:**
- Create: `src/sleeper_dynasty/engine/production_series.py`
- Test: `tests/engine/test_production_series.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/engine/test_production_series.py
from sleeper_dynasty.engine.production_series import (
    METRIC_GATES, week_axis, cumulative, merge_week_points,
)


def test_metric_gates():
    assert METRIC_GATES["total"] == (False, None)
    assert METRIC_GATES["regular"] == (True, "regular")
    assert METRIC_GATES["playoff"] == (True, "playoff")
    assert METRIC_GATES["toilet"] == (True, "toilet")


def test_week_axis_sorts_across_seasons():
    matchups = {("L1", 17, 1): {}, ("L1", 1, 1): {}, ("L2", 2, 1): {}}
    season = {"L1": 2024, "L2": 2025}
    assert week_axis(matchups, season) == [(2024, 1), (2024, 17), (2025, 2)]


def test_cumulative_runs_and_holds_flat_on_gaps():
    axis = [(2024, 1), (2024, 2), (2024, 3)]
    wp = {(2024, 1): 10.0, (2024, 3): 5.0}  # nothing week 2
    assert cumulative(wp, axis) == [((2024, 1), 10.0), ((2024, 2), 10.0), ((2024, 3), 15.0)]


def test_merge_week_points_adds():
    a = {(2024, 1): 10.0, (2024, 2): 3.0}
    b = {(2024, 2): 4.0, (2024, 3): 1.0}
    assert merge_week_points([a, b]) == {(2024, 1): 10.0, (2024, 2): 7.0, (2024, 3): 1.0}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/engine/test_production_series.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the module**

```python
# src/sleeper_dynasty/engine/production_series.py
"""Pure helpers behind the production-over-tenure timeline.

The production analog of ``value_series``'s pure math. Callers (the grader) build
per-(season, week) point dicts via ``trade_grader.player_week_points`` and use these
to align them to a shared calendar axis and accumulate them. Dependency-free and
trivially testable. ``WeekKey`` is ``(season, week)``; the global axis is the sorted
union of weeks present in the chain's matchups.
"""

from __future__ import annotations

WeekKey = tuple[int, int]

# metric -> (starters_only, phase_filter) for trade_grader.player_week_points.
METRIC_GATES: dict[str, tuple[bool, str | None]] = {
    "total": (False, None),
    "regular": (True, "regular"),
    "playoff": (True, "playoff"),
    "toilet": (True, "toilet"),
}


def week_axis(
    matchups: dict[tuple[str, int, int], dict],
    league_season_by_id: dict[str, int],
) -> list[WeekKey]:
    """Sorted unique ``(season, week)`` across all matchup entries."""
    keys = {
        (league_season_by_id.get(lg, 0), wk)
        for (lg, wk, _rid) in matchups
    }
    return sorted(keys)


def cumulative(week_points: dict[WeekKey, float], axis: list[WeekKey]) -> list[tuple[WeekKey, float]]:
    """Running total of ``week_points`` over ``axis``; flat across weeks with no points."""
    running = 0.0
    out: list[tuple[WeekKey, float]] = []
    for wk in axis:
        running += week_points.get(wk, 0.0)
        out.append((wk, running))
    return out


def merge_week_points(dicts: list[dict[WeekKey, float]]) -> dict[WeekKey, float]:
    """Element-wise sum of per-week point dicts."""
    out: dict[WeekKey, float] = {}
    for d in dicts:
        for wk, pts in d.items():
            out[wk] = out.get(wk, 0.0) + pts
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/engine/test_production_series.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/production_series.py tests/engine/test_production_series.py
git commit -m "feat(engine): production_series pure math (axis, cumulative, merge)"
```

---

## Task 3: Production verdict

A pure verdict for the head-to-head (per-trade) and the owner aggregate, replacing the KTC-based `per_trade_verdict`/`aggregate_verdict`. Margin-based with an honest "too early" state.

**Files:**
- Modify: `src/sleeper_dynasty/engine/production_series.py`
- Test: `tests/engine/test_production_verdict.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/engine/test_production_verdict.py
from sleeper_dynasty.engine.production_series import head_to_head_verdict, aggregate_production_verdict


def test_too_early_when_few_games():
    v = head_to_head_verdict(totals={"u1": 50.0, "u2": 10.0}, n_games=1, metric="total")
    assert v["tone"] == "neutral"
    assert "too early" in v["sentence"].lower()
    assert v["winner_uid"] is None


def test_clear_winner_named_with_margin():
    v = head_to_head_verdict(totals={"u1": 900.0, "u2": 705.0}, n_games=20, metric="total",
                             names={"u1": "Tom", "u2": "Mikey"})
    assert v["winner_uid"] == "u1"
    assert v["tone"] == "good"
    assert "Tom" in v["sentence"] and "195" in v["sentence"]


def test_dead_even():
    v = head_to_head_verdict(totals={"u1": 500.0, "u2": 498.0}, n_games=20, metric="total")
    assert v["winner_uid"] is None
    assert v["label"].lower().startswith("dead") or "even" in v["label"].lower()


def test_aggregate_margin_and_too_early():
    early = aggregate_production_verdict(received_total=0.0, given_total=0.0, n_games=0, metric="total")
    assert "too early" in early["sentence"].lower()
    won = aggregate_production_verdict(received_total=1200.0, given_total=888.0, n_games=40,
                                       metric="total", n_trades=7)
    assert won["tone"] == "good"
    assert "312" in won["sentence"] and "7" in won["sentence"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/engine/test_production_verdict.py -v`
Expected: FAIL — `head_to_head_verdict` undefined.

- [ ] **Step 3: Implement the verdicts**

Append to `src/sleeper_dynasty/engine/production_series.py`:

```python
MIN_GAMES_FOR_VERDICT = 3
# A margin under this fraction of the leader's total reads as "dead even".
_EVEN_FRACTION = 0.02

_METRIC_NOUN = {
    "total": "total points",
    "regular": "regular-season points",
    "playoff": "playoff points",
    "toilet": "toilet-bowl points",
}


def _too_early(metric: str, extra: dict) -> dict:
    return {
        "label": "Too early.",
        "sentence": f"Too early to tell — not enough games yet to judge {_METRIC_NOUN[metric]}.",
        "tone": "neutral",
        **extra,
    }


def head_to_head_verdict(
    *,
    totals: dict[str, float],
    n_games: int,
    metric: str,
    names: dict[str, str] | None = None,
) -> dict:
    """Who won the production battle for one trade, on one metric.

    ``totals`` is uid -> final cumulative points. Returns
    ``{"label", "sentence", "tone", "winner_uid", "totals"}``.
    """
    names = names or {}
    base = {"winner_uid": None, "totals": {u: float(v) for u, v in totals.items()}}
    if n_games < MIN_GAMES_FOR_VERDICT or not totals:
        return _too_early(metric, base)
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    (top_uid, top_val) = ranked[0]
    runner_val = ranked[1][1] if len(ranked) > 1 else 0.0
    margin = top_val - runner_val
    noun = _METRIC_NOUN[metric]
    if top_val <= 0 or margin < _EVEN_FRACTION * (top_val or 1):
        return {
            "label": "Dead even.",
            "sentence": f"Both sides have produced about the same {noun} so far.",
            "tone": "neutral", **base,
        }
    name = names.get(top_uid, "One side")
    big = margin >= 0.25 * top_val
    return {
        "label": "Won the production battle." if not big else "Lopsided.",
        "sentence": f"{name} is ahead by {round(margin):,} {noun}.",
        "tone": "good",
        "winner_uid": top_uid,
        "totals": base["totals"],
    }


def aggregate_production_verdict(
    *,
    received_total: float,
    given_total: float,
    n_games: int,
    metric: str,
    n_trades: int = 0,
) -> dict:
    """Owner-wide: did their hauls out-produce what they shipped out, on one metric.

    Returns ``{"label", "sentence", "tone", "received_total", "given_total"}``.
    """
    base = {"received_total": float(received_total), "given_total": float(given_total)}
    if n_games < MIN_GAMES_FOR_VERDICT:
        return _too_early(metric, base)
    margin = received_total - given_total
    noun = _METRIC_NOUN[metric]
    trades = f"{n_trades} trade{'s' if n_trades != 1 else ''}"
    if abs(margin) < _EVEN_FRACTION * (max(received_total, given_total) or 1):
        return {
            "label": "Break-even.",
            "sentence": f"Across {trades}, your hauls have produced about as much {noun} as what you shipped out.",
            "tone": "neutral", **base,
        }
    if margin > 0:
        return {
            "label": "Net positive.",
            "sentence": f"Across {trades}, your hauls have produced +{round(margin):,} {noun} more than what you shipped out.",
            "tone": "good", **base,
        }
    return {
        "label": "Net negative.",
        "sentence": f"Across {trades}, what you shipped out has produced {round(abs(margin)):,} more {noun} than your hauls.",
        "tone": "bad", **base,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/engine/test_production_verdict.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/production_series.py tests/engine/test_production_verdict.py
git commit -m "feat(engine): production verdicts (head-to-head + aggregate, too-early)"
```

---

## Task 4: Grader payload builder

Assemble the cached payload: per-trade per-side per-metric cumulative received series + head-to-head verdict; owner received/given aggregates + aggregate verdict; the shared week axis. Mirrors `compute_value_series_payload`.

**Design notes (locked):**
- Per-trade chart plots each side's **received** cumulative line; for the dominant 2-team case side A received == side B gave, so the combined chart is a true head-to-head. Verdict compares received totals across sides.
- Owner **received** aggregate = merge of that owner's received per-week points across all their trades. Owner **given** aggregate = for each asset the owner gave, the terminal player's production while held by its **current owner** (`current_holders`), post that trade — "what your given-away assets are producing for whoever has them now" (final-owner approximation; documented).
- Received terminal player ids come from `side_value_tenures(which="received")`, taking `t.player_id` where `t.kind == "player"` (picks resolve to drafted players there; unresolved picks contribute nothing).

**Files:**
- Modify: `api/app/services/grader.py:49-97`
- Test: `api/tests/test_compute_production_series.py`

- [ ] **Step 1: Write the failing test**

```python
# api/tests/test_compute_production_series.py
from app.services.grader import compute_production_series_payload


def test_payload_shapes_and_axis(simple_two_team_chain):
    """simple_two_team_chain fixture supplies: resolved_dicts (one 2-team trade,
    L1 season 2024 week 4; u1 received player p1, u2 received player p2),
    matchups with p1 on u1 and p2 on u2 in weeks 5-6, roster maps, season map,
    current_holders, drop_index, phase data, names."""
    f = simple_two_team_chain
    payload = compute_production_series_payload(
        resolved_dicts=f.resolved_dicts,
        matchups=f.matchups,
        roster_to_user_by_league=f.roster_to_user_by_league,
        league_season_by_id=f.league_season_by_id,
        current_holders=f.current_holders,
        drop_index=f.drop_index,
        phase_by_lwr=f.phase_by_lwr,
        playoff_week_start_by_league=f.playoff_week_start_by_league,
        names=f.names,
    )
    assert payload["production_week_axis"]  # [[season, week], ...]
    tx = f.resolved_dicts[0]["trade"]["transaction_id"]
    total_series_u1 = payload["trade_production_series"][tx]["u1"]["total"]
    # cumulative & non-decreasing
    vals = [v for _s, _w, v in total_series_u1]
    assert vals == sorted(vals)
    assert vals[-1] > 0
    # all four metrics present
    assert set(payload["trade_production_series"][tx]["u1"]) == {"total", "regular", "playoff", "toilet"}
    # verdict per metric
    assert "total" in payload["trade_production_verdict"][tx]
    # owner aggregate has received + given per metric
    assert set(payload["owner_production_series"]["u1"]) == {"received", "given"}
    assert "total" in payload["owner_production_series"]["u1"]["received"]
```

> Build `simple_two_team_chain` as a fixture in `api/tests/conftest.py` (or local). Model it on the resolved-trade dicts the existing `api/tests/test_*grader*`/`test_trade_view*` use — grep for `resolved_dicts` / `"sides"` fixtures and copy the shape (`{"trade": {"transaction_id", "traded_at", "week", ...}, "sides": {uid: {"received": [...], "given": [...]}}}`). One trade, two sides, each side `received` one player asset (`{"player_id": ...}`) and `given` the other's.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest api/tests/test_compute_production_series.py -v`
Expected: FAIL — `compute_production_series_payload` undefined.

- [ ] **Step 3: Implement the builder**

Add to `api/app/services/grader.py` (beside `compute_value_series_payload`):

```python
def compute_production_series_payload(
    *,
    resolved_dicts: list[dict],
    matchups: dict[tuple[str, int, int], dict],
    roster_to_user_by_league: dict[str, dict[int, str]],
    league_season_by_id: dict[str, int],
    current_holders: dict[str, str],
    drop_index: dict[tuple[str, str], str],
    phase_by_lwr: dict[tuple[str, int, int], str],
    playoff_week_start_by_league: dict[str, int],
    names: dict[str, str],
) -> dict:
    """Pure builder for the production-timeline payload cached on ChainCacheEntry.

    Returns ``trade_production_series`` (tx -> uid -> metric -> [[season, week, val]]),
    ``trade_production_verdict`` (tx -> metric -> verdict), ``owner_production_series``
    (uid -> {"received"|"given"} -> metric -> series), ``owner_production_verdict``
    (uid -> metric -> verdict), and ``production_week_axis`` ([[season, week], ...]).
    """
    from sleeper_dynasty.engine.lineage import side_value_tenures
    from sleeper_dynasty.engine.production_series import (
        METRIC_GATES, week_axis, cumulative, merge_week_points,
        head_to_head_verdict, aggregate_production_verdict,
    )
    from sleeper_dynasty.engine.trade_grader import player_week_points

    axis = week_axis(matchups, league_season_by_id)
    metrics = list(METRIC_GATES)

    # rt lookup by transaction_id (player_week_points needs the ResolvedTrade for
    # post-trade gating). resolved_dicts entries carry the ResolvedTrade under "rt"
    # if available; otherwise reconstruct via the same path build_trade_history uses.
    rt_by_tx = {r["trade"]["transaction_id"]: r["rt"] for r in resolved_dicts if r.get("rt")}

    def _wp(pid: str, owner: str, rt, starters_only: bool, phase_filter: str | None):
        return player_week_points(
            pid, owner, matchups=matchups,
            roster_to_user_by_league=roster_to_user_by_league, rt=rt,
            league_season_by_id=league_season_by_id, starters_only=starters_only,
            phase_filter=phase_filter, phase_by_lwr=phase_by_lwr,
            playoff_week_start_by_league=playoff_week_start_by_league,
        )

    def _received_player_ids(tx: str, uid: str) -> list[str]:
        tenures = side_value_tenures(resolved_dicts, tx, uid, which="received",
                                     current_holders=current_holders, drop_index=drop_index)
        return [t.player_id for t in tenures if t.kind == "player" and t.player_id]

    def _given_player_ids(tx: str, uid: str) -> list[str]:
        tenures = side_value_tenures(resolved_dicts, tx, uid, which="given",
                                     current_holders=current_holders, drop_index=drop_index)
        return [t.player_id for t in tenures if t.kind == "player" and t.player_id]

    def _trade_week_key(r: dict) -> tuple[int, int]:
        lg = r["trade"].get("league_id")
        return (league_season_by_id.get(lg, 0), int(r["trade"].get("week") or 0))

    def _n_games(trade_wk: tuple[int, int]) -> int:
        return sum(1 for wk in axis if wk > trade_wk)

    trade_series: dict[str, dict[str, dict[str, list]]] = {}
    trade_verdict: dict[str, dict[str, dict]] = {}
    # owner per-week accumulators: uid -> side -> metric -> list[per-week dicts]
    owner_acc: dict[str, dict[str, dict[str, list]]] = {}

    for r in resolved_dicts:
        tx = r["trade"]["transaction_id"]
        rt = rt_by_tx.get(tx)
        if rt is None:
            continue
        trade_wk = _trade_week_key(r)
        n = _n_games(trade_wk)
        per_side: dict[str, dict[str, list]] = {}
        per_metric_totals: dict[str, dict[str, float]] = {m: {} for m in metrics}
        for uid in (r.get("sides") or {}):
            recv_pids = _received_player_ids(tx, uid)
            per_side[uid] = {}
            for m in metrics:
                so, pf = METRIC_GATES[m]
                merged = merge_week_points([_wp(p, uid, rt, so, pf) for p in recv_pids])
                series = cumulative(merged, axis)
                per_side[uid][m] = [[s, w, v] for (s, w), v in series]
                per_metric_totals[m][uid] = series[-1][1] if series else 0.0
                # owner received aggregate
                owner_acc.setdefault(uid, {"received": {}, "given": {}})
                owner_acc[uid]["received"].setdefault(m, []).append(merged)
            # owner given aggregate: given player's production under its CURRENT owner
            given_pids = _given_player_ids(tx, uid)
            for m in metrics:
                so, pf = METRIC_GATES[m]
                given_merged = merge_week_points([
                    _wp(p, current_holders.get(p, ""), rt, so, pf)
                    for p in given_pids if current_holders.get(p)
                ])
                owner_acc.setdefault(uid, {"received": {}, "given": {}})
                owner_acc[uid]["given"].setdefault(m, []).append(given_merged)
        trade_series[tx] = per_side
        trade_verdict[tx] = {
            m: head_to_head_verdict(totals=per_metric_totals[m], n_games=n, metric=m, names=names)
            for m in metrics
        }

    # finalize owner aggregates
    owner_series: dict[str, dict[str, dict[str, list]]] = {}
    owner_verdict: dict[str, dict[str, dict]] = {}
    trades_by_owner: dict[str, int] = {}
    for r in resolved_dicts:
        for uid in (r.get("sides") or {}):
            trades_by_owner[uid] = trades_by_owner.get(uid, 0) + 1
    # earliest trade week per owner → n_games for the aggregate verdict
    earliest: dict[str, tuple[int, int]] = {}
    for r in resolved_dicts:
        wk = _trade_week_key(r)
        for uid in (r.get("sides") or {}):
            if uid not in earliest or wk < earliest[uid]:
                earliest[uid] = wk
    for uid, sides in owner_acc.items():
        owner_series[uid] = {"received": {}, "given": {}}
        for side in ("received", "given"):
            for m in metrics:
                merged = merge_week_points(sides[side].get(m, []))
                series = cumulative(merged, axis)
                owner_series[uid][side][m] = [[s, w, v] for (s, w), v in series]
        n = sum(1 for wk in axis if wk > earliest.get(uid, (9999, 99)))
        owner_verdict[uid] = {}
        for m in metrics:
            rt_tot = owner_series[uid]["received"][m][-1][2] if owner_series[uid]["received"][m] else 0.0
            gv_tot = owner_series[uid]["given"][m][-1][2] if owner_series[uid]["given"][m] else 0.0
            owner_verdict[uid][m] = aggregate_production_verdict(
                received_total=rt_tot, given_total=gv_tot, n_games=n, metric=m,
                n_trades=trades_by_owner.get(uid, 0),
            )

    return {
        "trade_production_series": trade_series,
        "trade_production_verdict": trade_verdict,
        "owner_production_series": owner_series,
        "owner_production_verdict": owner_verdict,
        "production_week_axis": [[s, w] for (s, w) in axis],
    }
```

> If `resolved_dicts` entries do not already carry the `ResolvedTrade` under `"rt"`, add it where `resolved_dicts` is built (grep the grader run for where dicts are produced from `ResolvedTrade` objects — likely a `_to_dict`/serialization step — and attach `d["rt"] = rt`). The cache stores only the JSON payload, so `"rt"` lives only in the in-memory `resolved_dicts` used here.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest api/tests/test_compute_production_series.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/app/services/grader.py api/tests/test_compute_production_series.py
git commit -m "feat(api): compute_production_series_payload (per-trade + owner aggregates)"
```

---

## Task 5: Persist on ChainCacheEntry and wire into the refresh pipeline

**Files:**
- Modify: `api/app/services/chain_cache.py:62-68`
- Modify: `api/app/services/grader.py` (the `run` method, where `compute_value_series_payload` is currently called — grep `compute_value_series_payload` and the `value_series` stage)
- Test: `api/tests/test_chain_cache.py` (add field round-trip) — or extend existing cache test

- [ ] **Step 1: Write the failing test**

```python
# api/tests/test_chain_cache.py  (add)
from app.services.chain_cache import ChainCacheEntry


def test_entry_carries_production_fields(tmp_path):
    e = ChainCacheEntry()
    e.trade_production_series = {"t1": {"u1": {"total": [[2024, 5, 10.0]]}}}
    e.production_week_axis = [[2024, 5]]
    # round-trips through the cache's to/from dict (use whatever (de)serializer the
    # cache uses; grep test_chain_cache.py for the existing write/read helper)
    assert e.trade_production_series["t1"]["u1"]["total"] == [[2024, 5, 10.0]]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest api/tests/test_chain_cache.py::test_entry_carries_production_fields -v`
Expected: FAIL — `AttributeError`/dataclass has no such field.

- [ ] **Step 3: Add the fields**

In `api/app/services/chain_cache.py`, after `value_series_dates` (line 68), add:

```python
    # production timeline (Phase 1). Mirrors the value-series fields but keyed by
    # (season, week) and per metric ("total"|"regular"|"playoff"|"toilet").
    # trade_production_series: tx -> uid -> metric -> [[season, week, points], ...]
    trade_production_series: dict = field(default_factory=dict)
    # trade_production_verdict: tx -> metric -> verdict dict
    trade_production_verdict: dict = field(default_factory=dict)
    # owner_production_series: uid -> {"received"|"given"} -> metric -> series
    owner_production_series: dict = field(default_factory=dict)
    # owner_production_verdict: uid -> metric -> verdict dict
    owner_production_verdict: dict = field(default_factory=dict)
    # production_week_axis: [[season, week], ...]
    production_week_axis: list = field(default_factory=list)
```

> If `ChainCacheEntry` serialization is explicit (not `asdict`), grep the cache module for where fields are written/read and add these alongside the value-series ones so they persist.

- [ ] **Step 4: Wire into the pipeline**

In `grader.py`'s `run`, where `compute_value_series_payload(...)` is called and its result assigned onto the entry (grep `compute_value_series_payload`), add a sibling call. The supporting data dict already carries `matchups`, `roster_to_user_by_league`, `league_season_by_id`, `phase_by_lwr`/playoff data, and `owners_display` (names). Use the same `current_holders`/`drop_index` passed to the value-series builder:

```python
            prod = compute_production_series_payload(
                resolved_dicts=resolved_dicts,
                matchups=supporting["matchups"],
                roster_to_user_by_league=supporting["roster_to_user_by_league"],
                league_season_by_id=supporting["league_season_by_id"],
                current_holders=current_holders,
                drop_index=drop_index,
                phase_by_lwr=supporting.get("phase_by_lwr") or {},
                playoff_week_start_by_league=supporting.get("playoff_week_start_by_league") or {},
                names=supporting["owners_display"],
            )
            entry.trade_production_series = prod["trade_production_series"]
            entry.trade_production_verdict = prod["trade_production_verdict"]
            entry.owner_production_series = prod["owner_production_series"]
            entry.owner_production_verdict = prod["owner_production_verdict"]
            entry.production_week_axis = prod["production_week_axis"]
```

> Confirm the exact key names in `supporting` by reading `api/app/services/grader_io.py` (`pull_supporting_data`). If `phase_by_lwr`/`playoff_week_start_by_league` aren't already in `supporting`, they are computed near the value-series call — reuse those locals. Keep this inside the existing `value_series` stage's try/except so a production failure never fails the refresh.

- [ ] **Step 5: Run tests + commit**

Run: `pytest api/tests/test_chain_cache.py -v`
Expected: PASS.

```bash
git add api/app/services/chain_cache.py api/app/services/grader.py api/tests/test_chain_cache.py
git commit -m "feat(api): persist production timeline on ChainCacheEntry; compute at refresh"
```

---

## Task 6: API response models

**Files:**
- Modify: `api/app/models/trade.py` (after `PerTradeVerdictView`, ~line 121-145)
- Modify: the owner response model (grep `value_progression` in `api/app/models/` to find the owner model file)
- Test: `api/tests/test_models_production.py`

- [ ] **Step 1: Write the failing test**

```python
# api/tests/test_models_production.py
from app.models.trade import ProductionPoint, ProductionVerdictView, TradeDetailResp


def test_production_point_and_verdict():
    p = ProductionPoint(season=2024, week=5, value=10.0)
    assert (p.season, p.week, p.value) == (2024, 5, 10.0)
    v = ProductionVerdictView(label="Won the production battle.", sentence="Tom is ahead by 195 total points.",
                              tone="good", winner_uid="u1", totals={"u1": 900.0, "u2": 705.0})
    assert v.winner_uid == "u1"


def test_trade_detail_has_production_fields():
    r = TradeDetailResp.model_construct()
    assert hasattr(r, "production_series")
    assert hasattr(r, "production_verdict")
    assert hasattr(r, "production_week_axis")
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest api/tests/test_models_production.py -v`
Expected: FAIL — names undefined.

- [ ] **Step 3: Implement the models**

In `api/app/models/trade.py` after `PerTradeVerdictView`:

```python
class ProductionPoint(BaseModel):
    season: int
    week: int
    value: float


class ProductionVerdictView(BaseModel):
    label: str
    sentence: str
    tone: str  # good | bad | neutral
    winner_uid: str | None = None
    totals: dict[str, float] = {}
```

Add to `TradeDetailResp` (alongside `value_series`/`value_verdict`):

```python
    # production timeline (Phase 1): uid -> metric -> [points]; metric -> verdict
    production_series: dict[str, dict[str, list[ProductionPoint]]] = {}
    production_verdict: dict[str, ProductionVerdictView] = {}
    production_week_axis: list[list[int]] = []
```

In the owner response model file (where `value_progression`/`value_verdict` live), add:

```python
    production_series: dict[str, dict[str, list[ProductionPoint]]] = {}  # side -> metric -> points
    production_verdict: dict[str, ProductionVerdictView] = {}            # metric -> verdict
    production_week_axis: list[list[int]] = []
```

> Import `ProductionPoint`/`ProductionVerdictView` into the owner model module from `app.models.trade`.

- [ ] **Step 4: Run to verify it passes** — `pytest api/tests/test_models_production.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add api/app/models/ api/tests/test_models_production.py
git commit -m "feat(api): production timeline response models"
```

---

## Task 7: Trade-detail assembly

Surface the cached per-trade production series + per-metric verdict on the trade detail response.

**Files:**
- Modify: `api/app/services/trade_view.py:118-137` (the value-series assembly block)
- Test: `api/tests/test_trade_view_production.py`

- [ ] **Step 1: Write the failing test**

```python
# api/tests/test_trade_view_production.py
from app.services.trade_view import build_trade_detail


def test_trade_detail_surfaces_production(trade_detail_fixture):
    """trade_detail_fixture: a ChainCacheEntry with trade_production_series /
    trade_production_verdict / production_week_axis populated for trade 't1',
    plus the args build_trade_detail needs. Grep test_trade_view*.py for the
    existing entry fixture and extend it."""
    resp = build_trade_detail(**trade_detail_fixture)
    assert resp.production_week_axis  # [[season, week], ...]
    assert "u1" in resp.production_series
    assert "total" in resp.production_series["u1"]
    assert resp.production_series["u1"]["total"][0].season >= 2000
    assert resp.production_verdict["total"].tone in {"good", "bad", "neutral"}
```

- [ ] **Step 2: Run to verify it fails** — `pytest api/tests/test_trade_view_production.py -v` → FAIL.

- [ ] **Step 3: Implement assembly**

In `trade_view.py`, alongside the value-series block (after `value_verdict_view` is built), add:

```python
    from app.models.trade import ProductionPoint, ProductionVerdictView

    prod_series_raw = (getattr(entry, "trade_production_series", None) or {}).get(trade_id) or {}
    production_series_view: dict[str, dict[str, list[ProductionPoint]]] = {}
    for uid, by_metric in prod_series_raw.items():
        production_series_view[uid] = {
            metric: [ProductionPoint(season=s, week=w, value=v) for s, w, v in pts]
            for metric, pts in by_metric.items()
        }
    prod_verdict_raw = (getattr(entry, "trade_production_verdict", None) or {}).get(trade_id) or {}
    production_verdict_view = {
        metric: ProductionVerdictView(**vd) for metric, vd in prod_verdict_raw.items()
    }
    production_week_axis = list(getattr(entry, "production_week_axis", None) or [])
```

Then pass these into the `TradeDetailResp(...)` constructor:

```python
        production_series=production_series_view,
        production_verdict=production_verdict_view,
        production_week_axis=production_week_axis,
```

- [ ] **Step 4: Run to verify it passes** — `pytest api/tests/test_trade_view_production.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add api/app/services/trade_view.py api/tests/test_trade_view_production.py
git commit -m "feat(api): surface per-trade production timeline + verdict"
```

---

## Task 8: Owner-aggregate assembly

Replace the KTC `_aggregate_value_view` output with the production aggregate on the owner detail response.

**Files:**
- Modify: `api/app/services/owner_view.py:141-142, 224-225` (and add a `_aggregate_production_view` helper near `_aggregate_value_view` at line 16-40)
- Test: `api/tests/test_owner_view_production.py`

- [ ] **Step 1: Write the failing test**

```python
# api/tests/test_owner_view_production.py
from app.services.owner_view import build_owner_detail  # adjust to the actual entry point


def test_owner_detail_surfaces_production(owner_detail_fixture):
    """owner_detail_fixture: ChainCacheEntry with owner_production_series /
    owner_production_verdict populated for user 'u1', plus build args. Extend the
    existing owner_view test fixture."""
    resp = build_owner_detail(**owner_detail_fixture)
    assert "received" in resp.production_series
    assert "total" in resp.production_series["received"]
    assert resp.production_verdict["total"].tone in {"good", "bad", "neutral"}
    assert resp.production_week_axis
```

- [ ] **Step 2: Run to verify it fails** — `pytest api/tests/test_owner_view_production.py -v` → FAIL.

- [ ] **Step 3: Implement assembly**

In `owner_view.py`, where `owner_value_series`/`_aggregate_value_view` are read (lines 141-142) and where the response is built (224-225), add the production equivalents:

```python
    from app.models.trade import ProductionPoint, ProductionVerdictView

    prod_raw = (getattr(entry, "owner_production_series", None) or {}).get(user_id) or {}
    production_series = {
        side: {
            metric: [ProductionPoint(season=s, week=w, value=v) for s, w, v in pts]
            for metric, pts in by_metric.items()
        }
        for side, by_metric in prod_raw.items()
    }
    prod_verdict_raw = (getattr(entry, "owner_production_verdict", None) or {}).get(user_id) or {}
    production_verdict = {m: ProductionVerdictView(**vd) for m, vd in prod_verdict_raw.items()}
    production_week_axis = list(getattr(entry, "production_week_axis", None) or [])
```

Pass into the owner response constructor:

```python
        production_series=production_series,
        production_verdict=production_verdict,
        production_week_axis=production_week_axis,
```

- [ ] **Step 4: Run to verify it passes** — `pytest api/tests/test_owner_view_production.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add api/app/services/owner_view.py api/tests/test_owner_view_production.py
git commit -m "feat(api): surface owner production aggregate + verdict"
```

---

## Task 9: Frontend types

**Files:**
- Modify: `web/lib/types.ts` (near `ValuePoint`/`ValueSidesView`, lines 338-378, and the owner type at 252-253, and the trade type at 377-378)
- Test: none (type-only); covered by component tests below.

- [ ] **Step 1: Add types**

```ts
// web/lib/types.ts
export interface ProductionPoint {
  season: number;
  week: number;
  value: number;
}

export type ProductionMetric = "total" | "regular" | "playoff" | "toilet";

export interface ProductionVerdict {
  label: string;
  sentence: string;
  tone: "good" | "bad" | "neutral";
  winner_uid?: string | null;
  totals?: Record<string, number>;
}

// per-trade: uid -> metric -> points
export type TradeProductionSeries = Record<string, Record<ProductionMetric, ProductionPoint[]>>;
// owner: side -> metric -> points
export type OwnerProductionSeries = Record<"received" | "given", Record<ProductionMetric, ProductionPoint[]>>;
```

Add to the trade-detail interface (near lines 377-378):

```ts
  production_series?: TradeProductionSeries;
  production_verdict?: Record<string, ProductionVerdict>;
  production_week_axis?: [number, number][];
```

Add to the owner-detail interface (near 252-253):

```ts
  production_series?: OwnerProductionSeries;
  production_verdict?: Record<string, ProductionVerdict>;
  production_week_axis?: [number, number][];
```

- [ ] **Step 2: Typecheck** — Run: `cd web && npx tsc --noEmit` → PASS (no usages yet).

- [ ] **Step 3: Commit**

```bash
git add web/lib/types.ts
git commit -m "feat(web): production timeline types"
```

---

## Task 10: `ProductionTimeline` chart component

A reusable component that draws cumulative lines on a `(season, week)` axis with season-boundary gridlines, a metric switch, and a side toggle. Used by both the per-trade and owner cards (Tasks 10b/11).

**Files:**
- Create: `web/components/ProductionTimeline.tsx`
- Test: `web/tests/ProductionTimeline.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// web/tests/ProductionTimeline.test.tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { ProductionTimeline } from "../components/ProductionTimeline";

const axis: [number, number][] = [[2024, 4], [2024, 5], [2024, 6]];
const lines = [
  { key: "u1", label: "Tom", color: "var(--pos)", byMetric: {
      total: [{ season: 2024, week: 4, value: 0 }, { season: 2024, week: 5, value: 10 }, { season: 2024, week: 6, value: 25 }],
      regular: [], playoff: [], toilet: [],
  } },
  { key: "u2", label: "Mikey", color: "var(--neg)", byMetric: {
      total: [{ season: 2024, week: 4, value: 0 }, { season: 2024, week: 5, value: 8 }, { season: 2024, week: 6, value: 14 }],
      regular: [], playoff: [], toilet: [],
  } },
];

test("renders a polyline per visible line and switches metric", () => {
  const { container } = render(
    <ProductionTimeline axis={axis} lines={lines} defaultMetric="total" />,
  );
  expect(container.querySelectorAll("polyline").length).toBe(2);
  // metric switch present
  expect(screen.getByRole("button", { name: /total/i })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /playoff/i }));
  // playoff series empty → no polylines
  expect(container.querySelectorAll("polyline").length).toBe(0);
});
```

- [ ] **Step 2: Run to verify it fails** — Run: `cd web && npm run test -- ProductionTimeline` → FAIL (no component).

- [ ] **Step 3: Implement the component**

```tsx
// web/components/ProductionTimeline.tsx
import { useState } from "react";
import type { ProductionMetric, ProductionPoint } from "../lib/types";

export interface TimelineLine {
  key: string;
  label: string;
  color: string;
  byMetric: Record<ProductionMetric, ProductionPoint[]>;
}

const METRICS: ProductionMetric[] = ["total", "regular", "playoff", "toilet"];
const METRIC_LABEL: Record<ProductionMetric, string> = {
  total: "Total", regular: "Regular", playoff: "Playoff", toilet: "Toilet",
};

export function ProductionTimeline({
  axis, lines, defaultMetric = "total",
}: {
  axis: [number, number][];
  lines: TimelineLine[];
  defaultMetric?: ProductionMetric;
}) {
  const [metric, setMetric] = useState<ProductionMetric>(defaultMetric);
  const W = 360, H = 120;
  const series = lines.map((l) => ({ ...l, pts: l.byMetric[metric] || [] }));
  const allVals = series.flatMap((s) => s.pts.map((p) => p.value));
  const max = Math.max(...allVals, 1);
  const n = axis.length;
  const x = (i: number) => (n <= 1 ? 0 : (i / (n - 1)) * W);
  const y = (v: number) => H - (v / max) * H;
  // season-boundary gridlines: first index of each new season
  const boundaries: number[] = [];
  axis.forEach(([s], i) => { if (i > 0 && s !== axis[i - 1][0]) boundaries.push(i); });
  const path = (pts: ProductionPoint[]) =>
    pts.map((p, i) => `${x(i)},${y(p.value)}`).join(" ");

  return (
    <div>
      <div className="flex gap-1 mb-2">
        {METRICS.map((m) => (
          <button
            key={m}
            onClick={() => setMetric(m)}
            className={`font-mono text-[10px] uppercase tracking-wider px-2 py-0.5 rounded ${
              m === metric ? "bg-ink text-bg" : "text-dim hover:text-ink"
            }`}
          >
            {METRIC_LABEL[m]}
          </button>
        ))}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" className="rounded-md bg-surface">
        {boundaries.map((i) => (
          <line key={i} x1={x(i)} y1="0" x2={x(i)} y2={H} stroke="var(--divider)" strokeDasharray="2 3" />
        ))}
        {series.map((s) =>
          s.pts.length > 1 ? (
            <polyline key={s.key} points={path(s.pts)} fill="none" stroke={s.color} strokeWidth="3" />
          ) : null,
        )}
      </svg>
      <div className="flex gap-4 mt-2 font-mono text-[10px] uppercase tracking-wider text-dim">
        {series.map((s) => (
          <span key={s.key} className="flex items-center gap-1">
            <span className="inline-block w-3 h-0.5" style={{ background: s.color }} /> {s.label}
          </span>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run to verify it passes** — `cd web && npm run test -- ProductionTimeline` → PASS.

- [ ] **Step 5: Commit**

```bash
git add web/components/ProductionTimeline.tsx web/tests/ProductionTimeline.test.tsx
git commit -m "feat(web): ProductionTimeline chart (metric switch, season gridlines)"
```

---

## Task 10b: Per-trade card + wire into trade page; remove old card

**Files:**
- Create: `web/components/TradeProductionCard.tsx`
- Modify: `web/app/league/[id]/trade/[tid]/page.tsx` (replace `TradeValueProgress` usage)
- Delete: `web/components/TradeValueProgress.tsx`, `web/tests/TradeValueProgress.test.tsx`
- Test: `web/tests/TradeProductionCard.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// web/tests/TradeProductionCard.test.tsx
import { render, screen } from "@testing-library/react";
import { TradeProductionCard } from "../components/TradeProductionCard";

test("renders title, verdict, and a chart", () => {
  render(
    <TradeProductionCard
      axis={[[2024, 4], [2024, 5]]}
      series={{ u1: { total: [{ season: 2024, week: 4, value: 0 }, { season: 2024, week: 5, value: 10 }], regular: [], playoff: [], toilet: [] } }}
      verdict={{ total: { label: "Won the production battle.", sentence: "Tom is ahead by 10 total points.", tone: "good", winner_uid: "u1", totals: { u1: 10 } } }}
      names={{ u1: "Tom" }}
    />,
  );
  expect(screen.getByText(/did it pan out/i)).toBeInTheDocument();
  expect(screen.getByText(/Won the production battle/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run to verify it fails** — `cd web && npm run test -- TradeProductionCard` → FAIL.

- [ ] **Step 3: Implement the card**

```tsx
// web/components/TradeProductionCard.tsx
import { useState } from "react";
import type {
  ProductionMetric, ProductionPoint, ProductionVerdict, TradeProductionSeries,
} from "../lib/types";
import { ProductionTimeline, type TimelineLine } from "./ProductionTimeline";

const COLORS = ["var(--pos)", "var(--neg)", "var(--accent)", "var(--ink)"];

export function TradeProductionCard({
  axis, series, verdict, names,
}: {
  axis: [number, number][];
  series: TradeProductionSeries;
  verdict?: Record<string, ProductionVerdict>;
  names: Record<string, string>;
}) {
  const uids = Object.keys(series || {});
  const [metric] = useState<ProductionMetric>("total");
  if (!axis?.length || uids.length === 0) return null;
  const lines: TimelineLine[] = uids.map((uid, i) => ({
    key: uid,
    label: names[uid] || uid,
    color: COLORS[i % COLORS.length],
    byMetric: series[uid],
  }));
  const v = verdict?.[metric];
  const tint = v?.tone === "good" ? "bg-pos/10" : v?.tone === "bad" ? "bg-neg/10" : "bg-surface";
  return (
    <div className="bg-surface border border-divider rounded-card p-4">
      <div className="font-mono text-[10px] uppercase tracking-widest text-dim mb-2">
        did it pan out?
      </div>
      <ProductionTimeline axis={axis} lines={lines} defaultMetric={metric} />
      {v && (
        <div className={`mt-3 rounded-md p-2.5 text-[13px] ${tint}`}>
          <strong>{v.label}</strong> {v.sentence}
        </div>
      )}
    </div>
  );
}
```

> Note: the metric switch lives inside `ProductionTimeline`; the verdict here keys off `"total"` for the headline (a later refinement can lift `metric` into this card so the verdict follows the switch — out of scope for Phase 1 minimal, but acceptable to wire via a shared state hook if trivial).

- [ ] **Step 4: Wire into the trade page; remove the old card**

In `web/app/league/[id]/trade/[tid]/page.tsx`, replace the two `TradeValueProgress` renders with a single `TradeProductionCard`:

```tsx
import { TradeProductionCard } from "@/components/TradeProductionCard";
// ...
{detail.production_week_axis && detail.production_series && (
  <TradeProductionCard
    axis={detail.production_week_axis}
    series={detail.production_series}
    verdict={detail.production_verdict}
    names={ownerNamesById}  // existing uid->name map on the page; grep the page for the owners map
  />
)}
```

Remove the `TradeValueProgress` import and both usages. Then delete the files:

```bash
git rm web/components/TradeValueProgress.tsx web/tests/TradeValueProgress.test.tsx
```

- [ ] **Step 5: Run tests + typecheck**

Run: `cd web && npm run test -- TradeProductionCard && npx tsc --noEmit`
Expected: PASS; no references to the deleted component remain.

- [ ] **Step 6: Commit**

```bash
git add web/components/TradeProductionCard.tsx web/tests/TradeProductionCard.test.tsx "web/app/league/[id]/trade/[tid]/page.tsx"
git commit -m "feat(web): per-trade production timeline card; remove KTC pan-out card"
```

---

## Task 11: Rework owner-aggregate `ValueProgressionCard` → production

**Files:**
- Modify: `web/components/ownerdeepdive/ValueProgressionCard.tsx` (repurpose to production; rename export to `ProductionProgressionCard` and keep file or rename file — rename file to `ProductionProgressionCard.tsx`)
- Modify: `web/components/ownerdeepdive/OverviewTab.tsx` (update import + props)
- Modify: `web/tests/ValueProgressionCard.test.tsx` → rename to `ProductionProgressionCard.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// web/tests/ProductionProgressionCard.test.tsx
import { render, screen } from "@testing-library/react";
import { ProductionProgressionCard } from "../components/ownerdeepdive/ProductionProgressionCard";

test("renders received vs given timeline and aggregate verdict", () => {
  render(
    <ProductionProgressionCard
      axis={[[2024, 4], [2024, 5]]}
      series={{
        received: { total: [{ season: 2024, week: 4, value: 0 }, { season: 2024, week: 5, value: 20 }], regular: [], playoff: [], toilet: [] },
        given: { total: [{ season: 2024, week: 4, value: 0 }, { season: 2024, week: 5, value: 12 }], regular: [], playoff: [], toilet: [] },
      }}
      verdict={{ total: { label: "Net positive.", sentence: "Across 3 trades, your hauls have produced +8 total points more than what you shipped out.", tone: "good" } }}
    />,
  );
  expect(screen.getByText(/did your trades pan out/i)).toBeInTheDocument();
  expect(screen.getByText(/Net positive/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run to verify it fails** — `cd web && npm run test -- ProductionProgressionCard` → FAIL.

- [ ] **Step 3: Implement (replace the file contents)**

Create `web/components/ownerdeepdive/ProductionProgressionCard.tsx`:

```tsx
import type {
  ProductionMetric, ProductionVerdict, OwnerProductionSeries,
} from "../../lib/types";
import { ProductionTimeline, type TimelineLine } from "../ProductionTimeline";

export function ProductionProgressionCard({
  axis, series, verdict,
}: {
  axis: [number, number][];
  series?: OwnerProductionSeries;
  verdict?: Record<string, ProductionVerdict>;
}) {
  const metric: ProductionMetric = "total";
  if (!axis?.length || !series) {
    return (
      <div className="bg-surface border border-divider rounded-card p-4">
        <div className="font-mono text-[10px] uppercase tracking-widest text-dim mb-2">
          did your trades pan out?
        </div>
        <p className="text-[12px] text-dim">No trades to chart yet.</p>
      </div>
    );
  }
  const lines: TimelineLine[] = [
    { key: "received", label: "What you got", color: "var(--pos)", byMetric: series.received },
    { key: "given", label: "What you gave up", color: "var(--neg)", byMetric: series.given },
  ];
  const v = verdict?.[metric];
  const tint = v?.tone === "good" ? "bg-pos/10" : v?.tone === "bad" ? "bg-neg/10" : "bg-surface";
  return (
    <div className="bg-surface border border-divider rounded-card p-4">
      <div className="font-mono text-[10px] uppercase tracking-widest text-dim mb-2">
        did your trades pan out?
      </div>
      <ProductionTimeline axis={axis} lines={lines} defaultMetric={metric} />
      {v && (
        <div className={`mt-3 rounded-md p-2.5 text-[13px] ${tint}`}>
          <strong>{v.label}</strong> {v.sentence}
        </div>
      )}
    </div>
  );
}
```

Delete the old file/test:

```bash
git rm web/components/ownerdeepdive/ValueProgressionCard.tsx web/tests/ValueProgressionCard.test.tsx
```

- [ ] **Step 4: Update `OverviewTab.tsx`**

Replace the `ValueProgressionCard` import + usage with:

```tsx
import { ProductionProgressionCard } from "./ProductionProgressionCard";
// ...
<ProductionProgressionCard
  axis={owner.production_week_axis ?? []}
  series={owner.production_series}
  verdict={owner.production_verdict}
/>
```

> Replace the old `progression={...} verdict={...}` props. Grep `OverviewTab.tsx` for the owner object's variable name to bind `owner.production_*`.

- [ ] **Step 5: Run tests + typecheck**

Run: `cd web && npm run test -- ProductionProgressionCard && npx tsc --noEmit`
Expected: PASS; no `ValueProgressionCard` references remain.

- [ ] **Step 6: Commit**

```bash
git add web/components/ownerdeepdive/ProductionProgressionCard.tsx web/tests/ProductionProgressionCard.test.tsx web/components/ownerdeepdive/OverviewTab.tsx
git commit -m "feat(web): owner production-aggregate card replaces KTC progression"
```

---

## Task 12: Retire the unused value-series path + full verification

The per-trade `value_series`/`value_verdict` fields and the `_aggregate_value_view` helper are now unused by the UI. Remove the dead UI-facing path; keep `engine/value_series.py` only if another consumer remains (grep before deleting).

**Files:**
- Modify: `api/app/services/trade_view.py` (remove `value_series`/`value_verdict` assembly if no longer consumed)
- Modify: `api/app/services/owner_view.py` (remove `_aggregate_value_view` + `value_progression`/`value_verdict` if unused)
- Modify: `api/app/models/trade.py` + owner model (drop now-unused `value_series`/`value_verdict`/`value_progression` fields **only if** nothing else reads them)
- Modify: `api/app/services/grader.py` (drop `compute_value_series_payload` call + the `trade_value_series`/`owner_value_series`/`value_series_dates` cache writes **only if** unused)

- [ ] **Step 1: Find remaining consumers**

Run:
```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty"
grep -rn "value_series\|value_verdict\|value_progression\|ValueSidesView\|PerTradeVerdict\|aggregate_verdict\|TradeValueSpark" web/ api/ src/ | grep -v "production"
```
Expected: a list. Anything under `web/` should be gone after Tasks 10b/11. If `engine/value_series.py` / `lineage.side_value_tenures` are still imported by the production builder (they are — `side_value_tenures` lives in `lineage.py`, and `production_series.py` does not import `value_series.py`), keep `lineage.py`. `engine/value_series.py` (the KTC pricing series) may now be unused — confirm via grep before deciding.

- [ ] **Step 2: Remove dead code (guided by Step 1)**

Delete only what Step 1 proves unused. Keep `lineage.py` (`side_value_tenures` is used by the production builder). For each removal, re-run the grep to confirm no dangling references.

- [ ] **Step 3: Full backend + engine test suite**

Run: `pytest -v`
Expected: PASS (no references to removed symbols; all production tests green).

- [ ] **Step 4: Full frontend suite + typecheck + lint**

Run: `cd web && npm run test && npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 5: Manual smoke (optional but recommended)**

Run `make dev-api` + `make dev-web`, open a trade detail page and an owner deep-dive, confirm the timeline renders with a real season/week axis, metric switch works, and the verdict reads sensibly (not "Boring").

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: retire unused KTC value-series UI path"
```

---

## Task 13: Per-player and per-trade drill series in the payload

Extend `compute_production_series_payload` to also emit, per metric: each received **player's** own cumulative series (for the per-trade card drill) and each owner's **per-trade** received line (for the owner card drill). Both reuse work already done in Task 4.

**Files:**
- Modify: `api/app/services/grader.py` (`compute_production_series_payload`)
- Test: `api/tests/test_compute_production_series.py` (extend)

- [ ] **Step 1: Write the failing test**

```python
def test_payload_has_per_player_and_per_trade_drill(simple_two_team_chain):
    f = simple_two_team_chain
    payload = compute_production_series_payload(
        resolved_dicts=f.resolved_dicts, matchups=f.matchups,
        roster_to_user_by_league=f.roster_to_user_by_league,
        league_season_by_id=f.league_season_by_id, current_holders=f.current_holders,
        drop_index=f.drop_index, phase_by_lwr=f.phase_by_lwr,
        playoff_week_start_by_league=f.playoff_week_start_by_league, names=f.names,
    )
    tx = f.resolved_dicts[0]["trade"]["transaction_id"]
    players = payload["trade_production_players"][tx]["u1"]
    assert players and "player_id" in players[0] and "total" in players[0]["byMetric"]
    trades = payload["owner_production_trades"]["u1"]
    assert trades and "trade_id" in trades[0] and "total" in trades[0]["byMetric"]
```

- [ ] **Step 2: Run to verify it fails** — `pytest api/tests/test_compute_production_series.py::test_payload_has_per_player_and_per_trade_drill -v` → FAIL (KeyError).

- [ ] **Step 3: Implement**

Inside `compute_production_series_payload`, add accumulators and per-player series. In the per-trade loop, after computing `recv_pids` for a `uid`, build each player's own series:

```python
    trade_players: dict[str, dict[str, list]] = {}
    owner_trades: dict[str, list] = {}
```

Within the `for uid in ...` block (after `per_side[uid]` is built):

```python
            players_out = []
            for pid in recv_pids:
                by_metric = {}
                for m in metrics:
                    so, pf = METRIC_GATES[m]
                    s = cumulative(_wp(pid, uid, rt, so, pf), axis)
                    by_metric[m] = [[sy, w, v] for (sy, w), v in s]
                players_out.append({"player_id": pid, "byMetric": by_metric})
            trade_players.setdefault(tx, {})[uid] = players_out
            owner_trades.setdefault(uid, []).append({
                "trade_id": tx,
                "byMetric": {m: per_side[uid][m] for m in metrics},
            })
```

Add both to the returned dict:

```python
        "trade_production_players": trade_players,
        "owner_production_trades": owner_trades,
```

- [ ] **Step 4: Run to verify it passes** — `pytest api/tests/test_compute_production_series.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add api/app/services/grader.py api/tests/test_compute_production_series.py
git commit -m "feat(api): per-player + per-trade drill series in production payload"
```

---

## Task 14: Cache fields for drill series

**Files:**
- Modify: `api/app/services/chain_cache.py` (after the production fields from Task 5)
- Modify: `api/app/services/grader.py` `run` (assign the two new payload keys onto the entry)

- [ ] **Step 1: Add fields**

```python
    # drill series. trade_production_players: tx -> uid -> [{player_id, byMetric}]
    trade_production_players: dict = field(default_factory=dict)
    # owner_production_trades: uid -> [{trade_id, byMetric}]
    owner_production_trades: dict = field(default_factory=dict)
```

- [ ] **Step 2: Assign in `run`** (beside the Task 5 assignments):

```python
            entry.trade_production_players = prod["trade_production_players"]
            entry.owner_production_trades = prod["owner_production_trades"]
```

- [ ] **Step 3: Test + commit** — Run: `pytest api/tests/test_chain_cache.py -v` → PASS.

```bash
git add api/app/services/chain_cache.py api/app/services/grader.py
git commit -m "feat(api): persist production drill series on ChainCacheEntry"
```

---

## Task 15: Drill models + API assembly

**Files:**
- Modify: `api/app/models/trade.py` (add drill views; add fields to `TradeDetailResp` + owner model)
- Modify: `api/app/services/trade_view.py` (surface per-player drill)
- Modify: `api/app/services/owner_view.py` (surface per-trade drill)
- Test: `api/tests/test_trade_view_production.py`, `api/tests/test_owner_view_production.py` (extend)

- [ ] **Step 1: Write failing tests**

```python
# add to test_trade_view_production.py
def test_trade_detail_has_per_player_drill(trade_detail_fixture):
    resp = build_trade_detail(**trade_detail_fixture)
    assert "u1" in resp.production_players
    assert resp.production_players["u1"][0].player_id
    assert "total" in resp.production_players["u1"][0].series

# add to test_owner_view_production.py
def test_owner_detail_has_per_trade_drill(owner_detail_fixture):
    resp = build_owner_detail(**owner_detail_fixture)
    assert resp.production_trades and resp.production_trades[0].trade_id
    assert "total" in resp.production_trades[0].series
```

- [ ] **Step 2: Run to verify they fail** — both → FAIL.

- [ ] **Step 3: Implement**

In `api/app/models/trade.py`:

```python
class PlayerProductionView(BaseModel):
    player_id: str
    series: dict[str, list[ProductionPoint]] = {}  # metric -> points


class TradeProductionView(BaseModel):
    trade_id: str
    series: dict[str, list[ProductionPoint]] = {}  # metric -> points
```

Add `production_players: dict[str, list[PlayerProductionView]] = {}` to `TradeDetailResp`, and `production_trades: list[TradeProductionView] = []` to the owner model (import the two views there).

In `trade_view.py` (beside the Task 7 block):

```python
    from app.models.trade import PlayerProductionView
    players_raw = (getattr(entry, "trade_production_players", None) or {}).get(trade_id) or {}
    production_players_view = {
        uid: [
            PlayerProductionView(
                player_id=p["player_id"],
                series={m: [ProductionPoint(season=s, week=w, value=v) for s, w, v in pts]
                        for m, pts in p["byMetric"].items()},
            )
            for p in plist
        ]
        for uid, plist in players_raw.items()
    }
```
Pass `production_players=production_players_view` into `TradeDetailResp(...)`.

In `owner_view.py` (beside the Task 8 block):

```python
    from app.models.trade import TradeProductionView
    trades_raw = (getattr(entry, "owner_production_trades", None) or {}).get(user_id) or []
    production_trades = [
        TradeProductionView(
            trade_id=t["trade_id"],
            series={m: [ProductionPoint(season=s, week=w, value=v) for s, w, v in pts]
                    for m, pts in t["byMetric"].items()},
        )
        for t in trades_raw
    ]
```
Pass `production_trades=production_trades` into the owner response.

- [ ] **Step 4: Run to verify they pass** — both test files → PASS.

- [ ] **Step 5: Commit**

```bash
git add api/app/models/trade.py api/app/services/trade_view.py api/app/services/owner_view.py api/tests/test_trade_view_production.py api/tests/test_owner_view_production.py
git commit -m "feat(api): surface per-player + per-trade production drill"
```

---

## Task 16: Side toggle + drill in the cards

The toggle and drill live in the cards (which choose the lines), not in `ProductionTimeline`. Add frontend types first, then a view-state toggle to each card.

**Files:**
- Modify: `web/lib/types.ts` (drill types; add to trade/owner interfaces)
- Modify: `web/components/TradeProductionCard.tsx` (side toggle → per-player drill)
- Modify: `web/components/ownerdeepdive/ProductionProgressionCard.tsx` (got/gave toggle → per-trade drill)
- Test: extend `web/tests/TradeProductionCard.test.tsx`, `web/tests/ProductionProgressionCard.test.tsx`

- [ ] **Step 1: Add types**

```ts
// web/lib/types.ts
export interface PlayerProduction { player_id: string; series: Record<ProductionMetric, ProductionPoint[]>; }
export interface TradeProduction { trade_id: string; series: Record<ProductionMetric, ProductionPoint[]>; }
```
Add `production_players?: Record<string, PlayerProduction[]>;` to the trade-detail interface and `production_trades?: TradeProduction[];` to the owner interface.

- [ ] **Step 2: Write failing tests**

```tsx
// TradeProductionCard.test.tsx — add
test("isolating a side drills into its players", () => {
  render(
    <TradeProductionCard
      axis={[[2024, 4], [2024, 5]]}
      series={{ u1: { total: [{season:2024,week:4,value:0},{season:2024,week:5,value:10}], regular:[], playoff:[], toilet:[] },
                u2: { total: [{season:2024,week:4,value:0},{season:2024,week:5,value:8}], regular:[], playoff:[], toilet:[] } }}
      players={{ u1: [{ player_id: "p1", series: { total:[{season:2024,week:4,value:0},{season:2024,week:5,value:10}], regular:[], playoff:[], toilet:[] } }] }}
      verdict={{ total: { label:"Won.", sentence:"x", tone:"good", winner_uid:"u1", totals:{u1:10,u2:8} } }}
      names={{ u1: "Tom", u2: "Mikey" }}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: /^Tom$/ }));
  // now showing Tom's players → "both" button visible to return
  expect(screen.getByRole("button", { name: /both/i })).toBeInTheDocument();
});
```
(Add the analogous "by trade" test to `ProductionProgressionCard.test.tsx`.)

- [ ] **Step 3: Implement the trade card toggle/drill**

Replace `TradeProductionCard` body's line construction with view state:

```tsx
import { useState } from "react";
// add prop: players?: Record<string, PlayerProduction[]>;
  const [view, setView] = useState<"both" | string>("both");
  const sideLines: TimelineLine[] = uids.map((uid, i) => ({
    key: uid, label: names[uid] || uid, color: COLORS[i % COLORS.length], byMetric: series[uid],
  }));
  const drill = view !== "both" && players?.[view]
    ? players[view].map((p, i) => ({ key: p.player_id, label: p.player_id, color: COLORS[i % COLORS.length], byMetric: p.series }))
    : null;
  const lines = drill ?? sideLines;
```
Add a toggle row above `<ProductionTimeline>`:

```tsx
      <div className="flex gap-1 mb-2">
        <button onClick={() => setView("both")} className={chip(view === "both")}>Both</button>
        {uids.map((uid) => (
          <button key={uid} onClick={() => setView(uid)} className={chip(view === uid)}>{names[uid] || uid}</button>
        ))}
      </div>
```
where `chip(active)` returns the same class string used by the metric buttons in `ProductionTimeline` (`font-mono text-[10px] uppercase tracking-wider px-2 py-0.5 rounded ` + active/inactive). Player labels (`p.player_id`) should resolve to names from the page's existing player map — pass a `playerName?: (id: string) => string` prop and use it for the drill label; default to the id.

- [ ] **Step 4: Implement the owner card toggle/drill** — same pattern in `ProductionProgressionCard`: views `both | got | gave`, plus a `by trade` view that maps `production_trades` to lines (label = trade_id, resolved to a date/label via a passed `tradeLabel?: (id) => string`).

- [ ] **Step 5: Run tests + typecheck**

Run: `cd web && npm run test -- TradeProductionCard ProductionProgressionCard && npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 6: Wire the new props** in the trade page (`production_players={detail.production_players}` + a `playerName` resolver from the page's asset data) and `OverviewTab` (`production_trades` + a `tradeLabel` resolver). Then commit:

```bash
git add web/lib/types.ts web/components/TradeProductionCard.tsx web/components/ownerdeepdive/ProductionProgressionCard.tsx web/tests/TradeProductionCard.test.tsx web/tests/ProductionProgressionCard.test.tsx "web/app/league/[id]/trade/[tid]/page.tsx" web/components/ownerdeepdive/OverviewTab.tsx
git commit -m "feat(web): side/got-gave toggle + per-player/per-trade drill"
```

- [ ] **Step 7: Re-run full verification** (Task 12 steps 3-4): `pytest -v` and `cd web && npm run test && npx tsc --noEmit` → all PASS.

---

## Self-review notes

- **Spec coverage:** §1 engine (Tasks 1-2), §2 owner aggregate (Tasks 4, 8, 11), §3 API (Tasks 6-8, 15), §4 verdict reframing (Task 3), §5 frontend combined chart + **side toggle** (Task 16) + metric switch (Task 10) + **per-player/per-trade drill** (Tasks 13, 15, 16), §6 edge cases (3-team via N lines; offseason/pick-zero via cumulative math), §7 testing (every task TDD). All approved-design features are now planned — no trims.
- **Verdict-follows-metric:** the cards render the `"total"` verdict as headline while the metric switch lives in `ProductionTimeline`. Lifting metric state into the cards so the verdict tracks the switch is a small enhancement; flagged, not required for Phase 1.
- **Naming consistency check:** `WeekKey` (season, week) and the 4 metric keys are used identically across Tasks 1-16; payload keys (`trade_production_series`, `trade_production_verdict`, `owner_production_series`, `owner_production_verdict`, `production_week_axis`, `trade_production_players`, `owner_production_trades`) match between grader (Tasks 4, 13), cache (Tasks 5, 14), and API assembly (Tasks 7, 8, 15). Model names (`ProductionPoint`, `ProductionVerdictView`, `PlayerProductionView`, `TradeProductionView`) are consistent across API and mirrored in TS (`ProductionPoint`, `ProductionVerdict`, `PlayerProduction`, `TradeProduction`).
