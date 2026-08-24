# Franchise Score Redesign — Implementation Plan (Phase 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure the Franchise Rating around Results / Skill / Outlook (with a new lineup-skill signal and zero-sum trade-skill signals), and produce a side-by-side comparison of two candidate pillar-weightings so we can pick one — all without touching the live prod read path or UI.

**Architecture:** All new rating logic is **additive and parallel**. The legacy pillar tree (`outcomes`/`trade_impact`/`outlook`) in `leaderboard.py`/`aggregations.py` is left untouched so prod keeps serving the current rating. We add (1) redesign weight configs + a parametrized `compute_gm_ratings`, (2) two pure signal extractors (lineup efficiency, zero-sum trade skill), (3) a persisted `lineup_signals` cache field computed at refresh, (4) a parallel `franchise_redesign` service that assembles the new tree, and (5) a comparison script printing Model 1 vs Model 2 vs current per owner. UI wiring is **Phase 2**, after a model is locked.

**Tech Stack:** Python 3 (engine + FastAPI backend), pytest. Pure engine functions in `src/sleeper_dynasty/engine/`, API services in `api/app/services/`.

## Global Constraints

- **Never show "KTC" in any user-facing string** — it is "Trade Value" / "Value". (This phase has no UI; keep it in mind for naming.)
- **Five-metric vocabulary** stays: Trade Value / Total Points / Regular Season Points / Playoff Points / Toilet Bowl Points.
- **Non-breaking by default:** `compute_gm_ratings(owners)` with no extra args MUST return byte-identical results to today (legacy weights). The redesign is opt-in via explicit weight args.
- **Cache schema migrations:** adding a persisted `ChainCacheEntry` field requires bumping `SCHEMA_VERSION` (currently `14` → `15`) in `api/app/services/chain_cache.py`. A stale schema is treated as a cache miss and re-graded. Run `next build` before any deploy (not in this phase).
- **Letter/scale machinery unchanged:** `BASE=1500`, `SCALE=275`, `CLAMP=(800,2200)`, `LETTER_BANDS`, `rating_to_letter` are not modified.
- **Pillar weights are tunable starting points** — Model 1 (Results-primary) `0.55/0.30/0.15`; Model 2 (Two equal axes) `0.43/0.43/0.14`. Within-pillar Skill split: trade_value `0.25`, trade_production `0.20`, draft_skill `0.30`, lineup_skill `0.25`.
- **Trade skill is zero-sum and volume-independent:** average per trade (not sum), with small-sample shrinkage `n/(n+k)`, `k=2`. Non-traders land neutral.

---

## File Structure

- `src/sleeper_dynasty/engine/gm_rating.py` — **modify.** Parametrize `compute_gm_ratings` with optional `pillar_weights`/`signal_weights`; add `REDESIGN_SIGNAL_WEIGHTS` + `REDESIGN_PILLAR_WEIGHTS`.
- `src/sleeper_dynasty/engine/skill_signals.py` — **create.** Pure `lineup_skill_signals(...)` + `trade_skill_signals(...)`.
- `api/app/services/chain_cache.py` — **modify.** Add `lineup_signals` field; bump `SCHEMA_VERSION` to 15.
- `api/app/services/rating_signals.py` — **modify.** Add `compute_lineup_signals(supporting, owners)` adapter (supporting dict → pure fn).
- `api/app/services/grader_io.py` — **modify.** Add `roster_positions` to the per-league matchup bundle and `roster_positions_by_league` to the supporting bundle.
- `api/app/services/grader.py` — **modify.** Call `compute_lineup_signals` during refresh; persist on the entry.
- `api/app/services/franchise_redesign.py` — **create.** Parallel assembly: `build_redesign_pillars(entry, trades)` + `compute_redesign_ratings(entry, model)`.
- `scripts/compare_franchise_models.py` — **create.** CLI: load a cached chain, print Model 1 / Model 2 / current ratings + letters per owner.
- Tests: `tests/test_gm_rating.py` (extend), `tests/test_skill_signals.py` (create), `api/tests/test_rating_signals_lineup.py` (create), `api/tests/test_franchise_redesign.py` (create).

---

### Task 1: Parametrize `compute_gm_ratings` + add redesign weight configs

**Files:**
- Modify: `src/sleeper_dynasty/engine/gm_rating.py`
- Test: `tests/test_gm_rating.py`

**Interfaces:**
- Produces: `compute_gm_ratings(owners, *, pillar_weights: dict | None = None, signal_weights: dict | None = None) -> dict[str, dict]`. When both are `None`, behavior is identical to today. `REDESIGN_PILLAR_WEIGHTS: dict[str, dict[str, float]]` keyed `"results_primary"` / `"equal_axes"`; `REDESIGN_SIGNAL_WEIGHTS: dict[str, dict[str, float]]` keyed `"results"`/`"skill"`/`"outlook"`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_gm_rating.py`:

```python
from sleeper_dynasty.engine.gm_rating import (
    compute_gm_ratings, REDESIGN_PILLAR_WEIGHTS, REDESIGN_SIGNAL_WEIGHTS,
)


def test_redesign_weight_configs_are_normalized():
    for model, pw in REDESIGN_PILLAR_WEIGHTS.items():
        assert set(pw) == {"results", "skill", "outlook"}, model
        assert abs(sum(pw.values()) - 1.0) < 1e-9, model
    for pillar, sw in REDESIGN_SIGNAL_WEIGHTS.items():
        assert abs(sum(sw.values()) - 1.0) < 1e-9, pillar
    assert set(REDESIGN_SIGNAL_WEIGHTS["skill"]) == {
        "trade_value", "trade_production", "draft_skill", "lineup_skill"
    }


def test_default_call_unchanged_by_parametrization():
    # Two owners, legacy tree. Passing no weights must equal passing the
    # module defaults explicitly (proves defaults are wired, behavior intact).
    owners = {
        "a": {"outcomes": {"championships": 1.0}, "trade_impact": {"value": 10.0},
              "outlook": {"roster_value": 100.0}},
        "b": {"outcomes": {"championships": 0.0}, "trade_impact": {"value": -10.0},
              "outlook": {"roster_value": 50.0}},
    }
    from sleeper_dynasty.engine.gm_rating import PILLAR_WEIGHTS, SIGNAL_WEIGHTS
    base = compute_gm_ratings(owners)
    explicit = compute_gm_ratings(
        owners, pillar_weights=PILLAR_WEIGHTS, signal_weights=SIGNAL_WEIGHTS)
    assert base == explicit


def test_redesign_tree_runs_and_centers_on_base():
    # A single-owner league has sd==0 everywhere -> every z is 0 -> rating == BASE.
    owners = {
        "solo": {
            "results": {"championships": 1.0, "playoff_depth": 2.0,
                        "made_playoffs": 1.0, "final_seed": 5.0, "points_for_rank": 4.0},
            "skill": {"trade_value": 3.0, "trade_production": 1.0,
                      "draft_skill": 0.5, "lineup_skill": 0.9},
            "outlook": {"roster_value": 100.0, "draft_capital": 10.0, "youth": -25.0},
        }
    }
    out = compute_gm_ratings(
        owners,
        pillar_weights=REDESIGN_PILLAR_WEIGHTS["results_primary"],
        signal_weights=REDESIGN_SIGNAL_WEIGHTS)
    assert out["solo"]["rating"] == 1500
    assert set(out["solo"]["pillars"]) == {"results", "skill", "outlook"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_gm_rating.py -k "redesign or parametrization" -v`
Expected: FAIL with `ImportError` / `cannot import name 'REDESIGN_PILLAR_WEIGHTS'`.

- [ ] **Step 3: Implement the parametrization + configs**

In `src/sleeper_dynasty/engine/gm_rating.py`, add after the existing `SIGNAL_WEIGHTS` block (after line 28):

```python
# --- Redesign (Results / Skill / Outlook). Additive: the live read path still
# uses the legacy PILLAR_WEIGHTS/SIGNAL_WEIGHTS above. Pass these explicitly to
# compute_gm_ratings to score the new tree. Weights are tunable v1 starting points.
REDESIGN_SIGNAL_WEIGHTS = {
    "results": {
        "championships": 0.35, "playoff_depth": 0.25, "made_playoffs": 0.15,
        "final_seed": 0.15, "points_for_rank": 0.10,
    },
    "skill": {
        "trade_value": 0.25, "trade_production": 0.20,
        "draft_skill": 0.30, "lineup_skill": 0.25,
    },
    "outlook": {"roster_value": 0.45, "draft_capital": 0.30, "youth": 0.25},
}
REDESIGN_PILLAR_WEIGHTS = {
    "results_primary": {"results": 0.55, "skill": 0.30, "outlook": 0.15},
    "equal_axes": {"results": 0.43, "skill": 0.43, "outlook": 0.14},
}
```

Then change the `compute_gm_ratings` signature (line 69) and the two weight references inside it. New signature:

```python
def compute_gm_ratings(
    owners: dict[str, dict[str, dict[str, float]]],
    *,
    pillar_weights: dict[str, float] | None = None,
    signal_weights: dict[str, dict[str, float]] | None = None,
) -> dict[str, dict]:
```

Immediately after the docstring, before `uids = list(owners)`, add:

```python
    pw = pillar_weights if pillar_weights is not None else PILLAR_WEIGHTS
    sw = signal_weights if signal_weights is not None else SIGNAL_WEIGHTS
```

Then replace `SIGNAL_WEIGHTS.items()` (line 85) with `sw.items()`, `PILLAR_WEIGHTS.items()` (line 93) with `pw.items()`, and `SIGNAL_WEIGHTS[pillar]` (line 96) with `sw[pillar]`. No other lines change.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_gm_rating.py -v`
Expected: PASS (new tests + all pre-existing `test_gm_rating.py` tests still green — proves non-breaking).

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/gm_rating.py tests/test_gm_rating.py
git commit -m "feat(gm-rating): parametrize compute_gm_ratings + redesign weight configs"
```

---

### Task 2: Pure lineup-skill signal extractor

**Files:**
- Create: `src/sleeper_dynasty/engine/skill_signals.py`
- Test: `tests/test_skill_signals.py`

**Interfaces:**
- Consumes: `engine.lineup.solve_optimal_lineup(roster_positions, players)` → `(set, float)`.
- Produces: `lineup_skill_signals(*, matchups, roster_positions_by_league, positions, roster_to_user_by_league, owners) -> dict[str, dict[str, float]]`, each value `{"lineup_skill": efficiency}` where `efficiency = Σ actual_started_points / Σ optimal_points` over all the owner's roster-weeks (`0.0` if the owner has no scored weeks).

- [ ] **Step 1: Write the failing test**

Create `tests/test_skill_signals.py`:

```python
from sleeper_dynasty.engine.skill_signals import lineup_skill_signals


def test_lineup_efficiency_perfect_and_imperfect():
    # One league "L", QB + FLEX slots. Two owners.
    # Owner A (roster 1) started optimally; Owner B (roster 2) benched their stud.
    roster_positions = ["QB", "FLEX", "BN"]
    matchups = {
        ("L", 1, 1): {
            "starters": ["qb1", "rb1"], "players": ["qb1", "rb1", "wr_bench"],
            "players_points": {"qb1": 20.0, "rb1": 15.0, "wr_bench": 5.0},
        },
        ("L", 1, 2): {
            # Started qb2 + the weak WR; benched the 18-pt RB. Optimal = 25+18=43,
            # actual = 25+4 = 29 -> efficiency 29/43.
            "starters": ["qb2", "wr_weak"], "players": ["qb2", "wr_weak", "rb_bench"],
            "players_points": {"qb2": 25.0, "wr_weak": 4.0, "rb_bench": 18.0},
        },
    }
    out = lineup_skill_signals(
        matchups=matchups,
        roster_positions_by_league={"L": roster_positions},
        positions={"qb1": "QB", "rb1": "RB", "wr_bench": "WR",
                   "qb2": "QB", "wr_weak": "WR", "rb_bench": "RB"},
        roster_to_user_by_league={"L": {1: "A", 2: "B"}},
        owners=["A", "B"],
    )
    assert out["A"]["lineup_skill"] == 1.0           # 35/35 optimal
    assert abs(out["B"]["lineup_skill"] - 29.0 / 43.0) < 1e-9
    # An owner with no games scores 0.0 (no division by zero).
    out2 = lineup_skill_signals(
        matchups={}, roster_positions_by_league={}, positions={},
        roster_to_user_by_league={}, owners=["C"])
    assert out2["C"]["lineup_skill"] == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_skill_signals.py::test_lineup_efficiency_perfect_and_imperfect -v`
Expected: FAIL with `ModuleNotFoundError: skill_signals`.

- [ ] **Step 3: Implement the extractor**

Create `src/sleeper_dynasty/engine/skill_signals.py`:

```python
"""Pure extractors for the redesigned Franchise Rating's Skill pillar.

- ``lineup_skill_signals``: per-owner weekly lineup efficiency (did the owner
  start their best players?) — Σ actual-started points / Σ optimal points over
  every roster-week. Reuses the production-tested optimal-lineup solver.
- ``trade_skill_signals``: per-owner zero-sum trade skill, averaged per trade
  (volume-independent) with small-sample shrinkage. Non-traders land neutral.
"""

from __future__ import annotations

from sleeper_dynasty.engine.lineup import solve_optimal_lineup


def lineup_skill_signals(
    *,
    matchups: dict[tuple[str, int, int], dict],
    roster_positions_by_league: dict[str, list[str]],
    positions: dict[str, str],
    roster_to_user_by_league: dict[str, dict[int, str]],
    owners: list[str],
) -> dict[str, dict[str, float]]:
    """Per-owner lineup efficiency across all roster-weeks.

    ``matchups`` is keyed ``(league_id, week, roster_id)`` with per-entry
    ``starters``/``players``/``players_points`` (see grader_io._assemble_played_matchups).
    Efficiency is ``Σ actual / Σ optimal``; an owner with no scored weeks gets 0.0.
    """
    actual: dict[str, float] = {u: 0.0 for u in owners}
    optimal: dict[str, float] = {u: 0.0 for u in owners}

    for (lg, _week, rid), m in matchups.items():
        uid = (roster_to_user_by_league.get(lg) or {}).get(rid)
        if uid is None:
            continue
        actual.setdefault(uid, 0.0)
        optimal.setdefault(uid, 0.0)
        rpos = roster_positions_by_league.get(lg) or []
        pts = m.get("players_points") or {}
        player_map = {
            pid: (positions[pid], float(pts.get(pid, 0.0) or 0.0))
            for pid in (m.get("players") or [])
            if positions.get(pid)
        }
        _, opt_total = solve_optimal_lineup(rpos, player_map)
        act_total = sum(
            float(pts.get(pid, 0.0) or 0.0) for pid in (m.get("starters") or [])
        )
        actual[uid] += act_total
        optimal[uid] += opt_total

    return {
        u: {"lineup_skill": (actual[u] / optimal[u]) if optimal[u] > 0 else 0.0}
        for u in actual
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_skill_signals.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/skill_signals.py tests/test_skill_signals.py
git commit -m "feat(skill-signals): pure lineup-efficiency extractor"
```

---

### Task 3: Pure zero-sum trade-skill signal extractor

**Files:**
- Modify: `src/sleeper_dynasty/engine/skill_signals.py`
- Test: `tests/test_skill_signals.py`

**Interfaces:**
- Produces: `trade_skill_signals(trades, owners, *, k: float = 2.0) -> dict[str, dict[str, float]]`. `trades` is a list of `{"value_swing": {uid: float}, "production": {uid: float}}` — `value_swing` is the per-side zero-sum market swing (`snapshot_value_swing`); `production` is each side's received `production_total`. Each value is `{"trade_value": float, "trade_production": float}`. Per owner: average the per-trade `value_swing` and the per-trade *recentered* production (`p_uid − trade_mean(p)`, zero-sum within the trade), then shrink toward 0 by `n/(n+k)`. A non-trader gets `{0.0, 0.0}`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_skill_signals.py`:

```python
from sleeper_dynasty.engine.skill_signals import trade_skill_signals


def test_trade_skill_zero_sum_and_shrinkage():
    # A fleeces B once: +30 value, A's haul produced 80 vs B's 20.
    trades = [{
        "value_swing": {"A": 30.0, "B": -30.0},
        "production": {"A": 80.0, "B": 20.0},
    }]
    out = trade_skill_signals(trades, owners=["A", "B", "C"], k=2.0)
    # n=1 -> shrink = 1/(1+2) = 1/3. value avg = swing itself.
    assert abs(out["A"]["trade_value"] - 30.0 / 3.0) < 1e-9
    assert abs(out["B"]["trade_value"] - (-30.0 / 3.0)) < 1e-9
    # production recentered: mean=50 -> A:+30, B:-30; avg over 1 trade, shrink 1/3.
    assert abs(out["A"]["trade_production"] - 30.0 / 3.0) < 1e-9
    assert abs(out["B"]["trade_production"] - (-30.0 / 3.0)) < 1e-9
    # Non-trader C sits exactly neutral.
    assert out["C"] == {"trade_value": 0.0, "trade_production": 0.0}


def test_trade_skill_averages_not_sums_volume():
    # Owner X makes two neutral trades; Owner Y makes one identical neutral trade.
    # Averaging (not summing) means volume alone never moves the metric: both X and
    # Y have the same per-trade average; shrinkage differs only by sample size.
    neutral = {"value_swing": {"X": 0.0, "Z": 0.0}, "production": {"X": 10.0, "Z": 10.0}}
    out = trade_skill_signals([neutral, neutral, dict(neutral, value_swing={"Y": 0.0, "Z": 0.0}, production={"Y": 10.0, "Z": 10.0})],
                              owners=["X", "Y", "Z"])
    assert out["X"]["trade_value"] == 0.0
    assert out["Y"]["trade_value"] == 0.0
    assert out["X"]["trade_production"] == 0.0  # recentered neutral -> 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_skill_signals.py -k trade_skill -v`
Expected: FAIL with `ImportError: cannot import name 'trade_skill_signals'`.

- [ ] **Step 3: Implement the extractor**

Append to `src/sleeper_dynasty/engine/skill_signals.py`:

```python
def trade_skill_signals(
    trades: list[dict],
    owners: list[str],
    *,
    k: float = 2.0,
) -> dict[str, dict[str, float]]:
    """Per-owner zero-sum trade skill, averaged per trade with shrinkage.

    Each trade is ``{"value_swing": {uid: float}, "production": {uid: float}}``:
    ``value_swing`` is the per-side zero-sum market-value swing; ``production`` is
    each side's received production total. Production is recentered per trade
    (``p_uid - mean(p)``) so it is zero-sum across the sides. Per owner we average
    across their trades, then shrink toward neutral by ``n / (n + k)`` to damp
    one-trade spikes. Non-traders get ``{0.0, 0.0}`` — i.e. league-neutral.
    """
    val_sum: dict[str, float] = {u: 0.0 for u in owners}
    prod_sum: dict[str, float] = {u: 0.0 for u in owners}
    n: dict[str, int] = {u: 0 for u in owners}

    for t in trades:
        vs = t.get("value_swing") or {}
        pr = t.get("production") or {}
        sides = set(vs) | set(pr)
        pmean = (sum(pr.values()) / len(pr)) if pr else 0.0
        for uid in sides:
            val_sum.setdefault(uid, 0.0)
            prod_sum.setdefault(uid, 0.0)
            n.setdefault(uid, 0)
            val_sum[uid] += float(vs.get(uid, 0.0) or 0.0)
            prod_sum[uid] += float(pr.get(uid, 0.0) or 0.0) - pmean
            n[uid] += 1

    out: dict[str, dict[str, float]] = {}
    for u in n:
        c = n[u]
        shrink = c / (c + k) if c else 0.0
        out[u] = {
            "trade_value": (val_sum[u] / c * shrink) if c else 0.0,
            "trade_production": (prod_sum[u] / c * shrink) if c else 0.0,
        }
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_skill_signals.py -v`
Expected: PASS (both lineup and trade tests).

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/skill_signals.py tests/test_skill_signals.py
git commit -m "feat(skill-signals): zero-sum trade-skill extractor (avg per trade + shrinkage)"
```

---

### Task 4: Persist lineup signals at refresh (cache field + supporting wiring)

**Files:**
- Modify: `api/app/services/chain_cache.py` (new field + `SCHEMA_VERSION` bump)
- Modify: `api/app/services/rating_signals.py` (supporting→pure adapter)
- Modify: `api/app/services/grader_io.py` (carry `roster_positions` per league)
- Modify: `api/app/services/grader.py` (compute + persist during refresh)
- Test: `api/tests/test_rating_signals_lineup.py`

**Interfaces:**
- Consumes: `engine.skill_signals.lineup_skill_signals(...)` (Task 2); `supporting` keys `matchups`, `positions`, `roster_to_user_by_league`, and the new `roster_positions_by_league`.
- Produces: `rating_signals.compute_lineup_signals(supporting: dict, owners: list[str]) -> dict[str, dict[str, float]]`; new persisted field `ChainCacheEntry.lineup_signals: dict[str, dict[str, float]]` (uid → `{"lineup_skill": float}`).

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_rating_signals_lineup.py`:

```python
from app.services.rating_signals import compute_lineup_signals


def test_compute_lineup_signals_reads_supporting_bundle():
    supporting = {
        "matchups": {
            ("L", 1, 1): {
                "starters": ["qb1", "rb1"], "players": ["qb1", "rb1", "wr_b"],
                "players_points": {"qb1": 20.0, "rb1": 15.0, "wr_b": 5.0},
            },
        },
        "roster_positions_by_league": {"L": ["QB", "FLEX", "BN"]},
        "positions": {"qb1": "QB", "rb1": "RB", "wr_b": "WR"},
        "roster_to_user_by_league": {"L": {1: "A"}},
    }
    out = compute_lineup_signals(supporting, owners=["A", "B"])
    assert out["A"]["lineup_skill"] == 1.0       # started optimally
    assert out["B"]["lineup_skill"] == 0.0       # no games


def test_compute_lineup_signals_degrades_without_roster_positions():
    # Missing roster_positions_by_league must not raise; returns zeros.
    out = compute_lineup_signals({"matchups": {}}, owners=["A"])
    assert out == {"A": {"lineup_skill": 0.0}}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest api/tests/test_rating_signals_lineup.py -v`
Expected: FAIL with `ImportError: cannot import name 'compute_lineup_signals'`.

- [ ] **Step 3a: Add the adapter**

In `api/app/services/rating_signals.py`, add the import near the top (with the other `sleeper_dynasty.engine` imports):

```python
from sleeper_dynasty.engine.skill_signals import lineup_skill_signals
```

Add this function at module level (after `compute_rating_signals`):

```python
def compute_lineup_signals(
    supporting: dict, owners: list[str]
) -> dict[str, dict[str, float]]:
    """Per-owner lineup efficiency from the refresh ``supporting`` bundle.

    Degrades to zeros (never raises) when the bundle predates
    ``roster_positions_by_league`` so a wiring gap can't break refresh.
    """
    return lineup_skill_signals(
        matchups=supporting.get("matchups") or {},
        roster_positions_by_league=supporting.get("roster_positions_by_league") or {},
        positions=supporting.get("positions") or {},
        roster_to_user_by_league=supporting.get("roster_to_user_by_league") or {},
        owners=list(owners),
    )
```

- [ ] **Step 3b: Add the cache field + bump schema**

In `api/app/services/chain_cache.py`:
- Change line 11 to: `SCHEMA_VERSION = 15  # bumped: lineup_signals (Franchise Rating redesign)`
- Add this field to `ChainCacheEntry` (next to `outlook_signals`, after line 40):

```python
    # GM-rating Skill pillar: per-owner lineup efficiency {uid: {"lineup_skill": float}}.
    # Redesign signal; empty on pre-migration caches.
    lineup_signals: dict[str, dict[str, float]] = field(default_factory=dict)
```

- [ ] **Step 3c: Carry roster_positions through the supporting bundle**

In `api/app/services/grader_io.py`, in `_league_matchup_bundle` add to the `bundle` dict (after the `"matchups": matchups,` line, ~line 154):

```python
        "roster_positions": list(getattr(lg, "roster_positions", []) or []),
```

Then find the block in this file (or wherever `pull_supporting_data` assembles `roster_to_user_by_league` from per-league bundles) that builds `roster_to_user_by_league`, and add a sibling that builds `roster_positions_by_league` the same way — mapping each `league_id` to its bundle's `roster_positions`. Mirror the exact pattern used for `roster_to_user_by_league` (key by league_id, value = the bundle field). Add the resulting dict to the returned `supporting` under key `"roster_positions_by_league"`.

> Note: `compute_lineup_signals` degrades to zeros if this key is absent, so this step can be verified end-to-end by the integration smoke (Task 6) — the unit test in Step 1 already pins the adapter contract.

- [ ] **Step 3d: Compute + persist during refresh**

In `api/app/services/grader.py`, right after the `compute_rating_signals` try/except block (after line 716), add:

```python
        lineup_signals: dict[str, dict[str, float]] = {}
        try:
            from app.services.rating_signals import compute_lineup_signals
            lineup_signals = compute_lineup_signals(
                supporting, list(supporting["owners"]))
        except Exception:
            log.exception("lineup-skill signal computation skipped")
```

Then add `lineup_signals=lineup_signals,` to the `ChainCacheEntry(...)` constructor (next to `outlook_signals=outlook_signals,`, ~line 852).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest api/tests/test_rating_signals_lineup.py -v && pytest tests/ api/tests/ -q`
Expected: new tests PASS; full suite still green (cache schema bump doesn't break existing tests — older fixtures are treated as misses, not errors).

- [ ] **Step 5: Commit**

```bash
git add api/app/services/chain_cache.py api/app/services/rating_signals.py \
        api/app/services/grader_io.py api/app/services/grader.py \
        api/tests/test_rating_signals_lineup.py
git commit -m "feat(rating): persist per-owner lineup-skill signal at refresh (schema 15)"
```

---

### Task 5: Parallel redesign rating assembly service

**Files:**
- Create: `api/app/services/franchise_redesign.py`
- Test: `api/tests/test_franchise_redesign.py`

**Interfaces:**
- Consumes: `ChainCacheEntry` (`outcome_signals`, `outlook_signals`, `lineup_signals`, `grades`, `resolved_trades`, `owners`); `aggregations._filter_trades_by_year`; `engine.skill_signals.trade_skill_signals`; `engine.gm_rating.compute_gm_ratings`, `REDESIGN_PILLAR_WEIGHTS`, `REDESIGN_SIGNAL_WEIGHTS`.
- Produces:
  - `build_redesign_pillars(entry, trades) -> dict[str, dict[str, dict[str, float]]]` — uid → `{"results":..., "skill":..., "outlook":...}`.
  - `compute_redesign_ratings(entry, model: str) -> dict[str, dict]` — full `compute_gm_ratings` output under `REDESIGN_PILLAR_WEIGHTS[model]`.

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_franchise_redesign.py`:

```python
from app.services.chain_cache import ChainCacheEntry
from app.services.franchise_redesign import (
    build_redesign_pillars, compute_redesign_ratings,
)


def _entry() -> ChainCacheEntry:
    return ChainCacheEntry(
        league_id="L", chain=[], resolved_trades=[
            {"trade": {"transaction_id": "t1", "season": 2024}},
        ],
        grades={"t1": {
            "snapshot_value_swing": {"A": 30.0, "B": -30.0},
            "production_total": {"A": 80.0, "B": 20.0},
        }},
        owners={"A": {}, "B": {}},
        playoff_weeks_by_league={}, roster_to_user_by_league={},
        league_name_by_id={}, league_season_by_id={}, cached_at="2026-06-26T00:00:00Z",
        outcome_signals={"A": {"championships": 1.0}, "B": {"championships": 0.0}},
        outlook_signals={
            "A": {"roster_value": 100.0, "draft_capital": 10.0, "draft_skill": 0.5, "youth": -24.0},
            "B": {"roster_value": 80.0, "draft_capital": 5.0, "draft_skill": 0.1, "youth": -26.0},
        },
        lineup_signals={"A": {"lineup_skill": 0.95}, "B": {"lineup_skill": 0.80}},
    )


def test_build_redesign_pillars_shapes_skill_from_all_sources():
    entry = _entry()
    pillars = build_redesign_pillars(entry, entry.resolved_trades)
    skill_a = pillars["A"]["skill"]
    assert set(skill_a) == {"trade_value", "trade_production", "draft_skill", "lineup_skill"}
    assert skill_a["draft_skill"] == 0.5          # re-homed from outlook
    assert skill_a["lineup_skill"] == 0.95        # from lineup_signals
    assert skill_a["trade_value"] > 0             # A fleeced B
    # draft_skill is NOT in the outlook pillar anymore.
    assert set(pillars["A"]["outlook"]) == {"roster_value", "draft_capital", "youth"}
    assert pillars["A"]["results"] == {"championships": 1.0}


def test_compute_redesign_ratings_ranks_a_over_b_both_models():
    entry = _entry()
    for model in ("results_primary", "equal_axes"):
        ratings = compute_redesign_ratings(entry, model)
        assert ratings["A"]["rating"] > ratings["B"]["rating"], model
        assert set(ratings["A"]["pillars"]) == {"results", "skill", "outlook"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest api/tests/test_franchise_redesign.py -v`
Expected: FAIL with `ModuleNotFoundError: franchise_redesign`.

- [ ] **Step 3: Implement the service**

Create `api/app/services/franchise_redesign.py`:

```python
"""Parallel Franchise-Rating assembly for the redesign (Results / Skill / Outlook).

Kept separate from leaderboard.py/aggregations.py so the live read path is
untouched while we compare candidate weightings. Reads only persisted
ChainCacheEntry fields; the per-trade skill signals are derived from
``entry.grades`` (zero-sum value swing + per-side received production).
"""

from __future__ import annotations

from typing import Any

from app.services.aggregations import Year, _filter_trades_by_year
from app.services.chain_cache import ChainCacheEntry
from sleeper_dynasty.engine.gm_rating import (
    REDESIGN_PILLAR_WEIGHTS, REDESIGN_SIGNAL_WEIGHTS, compute_gm_ratings,
)
from sleeper_dynasty.engine.skill_signals import trade_skill_signals


def _trade_records(entry: ChainCacheEntry, trades: list[dict[str, Any]]) -> list[dict]:
    """Per-trade {value_swing, production} from the persisted grades."""
    records: list[dict] = []
    for rt in trades:
        g = entry.grades.get(rt["trade"]["transaction_id"]) or {}
        records.append({
            "value_swing": g.get("snapshot_value_swing") or {},
            "production": g.get("production_total") or {},
        })
    return records


def build_redesign_pillars(
    entry: ChainCacheEntry, trades: list[dict[str, Any]]
) -> dict[str, dict[str, dict[str, float]]]:
    """uid -> {"results", "skill", "outlook"} signal sub-dicts for compute_gm_ratings."""
    owners = list(entry.owners)
    outcomes = entry.outcome_signals or {}
    outlook = entry.outlook_signals or {}
    lineup = entry.lineup_signals or {}
    trade_skill = trade_skill_signals(_trade_records(entry, trades), owners)

    pillars: dict[str, dict[str, dict[str, float]]] = {}
    for uid in owners:
        ol = outlook.get(uid, {})
        ts = trade_skill.get(uid, {"trade_value": 0.0, "trade_production": 0.0})
        pillars[uid] = {
            "results": outcomes.get(uid, {}),
            "skill": {
                "trade_value": ts["trade_value"],
                "trade_production": ts["trade_production"],
                "draft_skill": float(ol.get("draft_skill") or 0.0),
                "lineup_skill": float((lineup.get(uid) or {}).get("lineup_skill") or 0.0),
            },
            "outlook": {
                "roster_value": float(ol.get("roster_value") or 0.0),
                "draft_capital": float(ol.get("draft_capital") or 0.0),
                "youth": float(ol.get("youth") or 0.0),
            },
        }
    return pillars


def compute_redesign_ratings(
    entry: ChainCacheEntry, model: str, *, year: Year = "all"
) -> dict[str, dict]:
    """Full compute_gm_ratings output under the named redesign model."""
    trades = _filter_trades_by_year(entry, year)
    pillars = build_redesign_pillars(entry, trades)
    return compute_gm_ratings(
        pillars,
        pillar_weights=REDESIGN_PILLAR_WEIGHTS[model],
        signal_weights=REDESIGN_SIGNAL_WEIGHTS,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest api/tests/test_franchise_redesign.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/app/services/franchise_redesign.py api/tests/test_franchise_redesign.py
git commit -m "feat(rating): parallel redesign rating assembly (Results/Skill/Outlook)"
```

---

### Task 6: Comparison script — Model 1 vs Model 2 vs current

**Files:**
- Create: `scripts/compare_franchise_models.py`
- (No new unit test — this is an operator tool; correctness of its inputs is covered by Tasks 1–5.)

**Interfaces:**
- Consumes: `ChainCache.read`, `leaderboard.all_time_ratings` (current), `franchise_redesign.compute_redesign_ratings` (both models), `gm_rating.rating_to_letter`, `identity.owner_name`.

- [ ] **Step 1: Write the script**

Create `scripts/compare_franchise_models.py`:

```python
"""Compare Franchise Rating models for one league chain.

Prints every owner's rating + letter under the current (legacy) rating and the
two redesign candidates (Results-primary, Two-equal-axes), sorted by Model 1.

The league must already be refreshed locally on schema 15+ (so the cached entry
carries lineup_signals). Run a refresh first if the lineup column reads 0.

Usage:
    python scripts/compare_franchise_models.py <league_id> [--cache-dir DIR]
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from app.services.chain_cache import ChainCache
from app.services.franchise_redesign import compute_redesign_ratings
from app.services.identity import owner_name
from app.services.leaderboard import all_time_ratings
from sleeper_dynasty.engine.gm_rating import rating_to_letter


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("league_id")
    ap.add_argument(
        "--cache-dir",
        default=os.environ.get(
            "TRADE_GRADER_CACHE_DIR",
            str(Path.home() / ".sleeper-dynasty" / "cache"),
        ),
    )
    args = ap.parse_args()

    entry = ChainCache(cache_dir=Path(args.cache_dir)).read(
        args.league_id, max_age_seconds=10**12
    )
    if entry is None:
        raise SystemExit(
            f"No cached chain for league {args.league_id} on the current schema. "
            f"Refresh the league first (GET /api/league/{args.league_id}/refresh)."
        )

    current = all_time_ratings(entry)
    m1 = compute_redesign_ratings(entry, "results_primary")
    m2 = compute_redesign_ratings(entry, "equal_axes")

    def cell(uid: str, ratings: dict) -> str:
        if uid not in ratings:
            return "    —    "
        r = ratings[uid]["rating"] if isinstance(ratings[uid], dict) else ratings[uid]
        return f"{r:>4} {rating_to_letter(r):<2}"

    rows = sorted(
        entry.owners, key=lambda u: m1[u]["rating"] if u in m1 else 0, reverse=True
    )
    header = f"{'Owner':<22}{'Current':>11}{'Model1 R-prim':>15}{'Model2 Equal':>15}"
    print(header)
    print("-" * len(header))
    for uid in rows:
        name = (owner_name(entry, uid) or uid)[:21]
        print(f"{name:<22}{cell(uid, current):>11}{cell(uid, m1):>15}{cell(uid, m2):>15}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke-run the script**

Run (from repo root, with the API venv that has `app` + `sleeper_dynasty` importable — same env as `make dev-api`):

```bash
PYTHONPATH=api python scripts/compare_franchise_models.py <a-refreshed-league-id>
```

Expected: a 4-column table (Owner / Current / Model1 / Model2), one row per owner, sorted by Model 1 rating. If the league isn't cached on schema 15, it prints the "Refresh the league first" message — refresh, then re-run.

- [ ] **Step 3: Commit**

```bash
git add scripts/compare_franchise_models.py
git commit -m "feat(tools): franchise-model comparison script (current vs Model 1/2)"
```

---

### Task 7: Full verification + decision gate

**Files:** none (verification only).

- [ ] **Step 1: Run the whole backend + engine suite**

Run: `make test` (or `pytest -q && pytest api/tests -q`)
Expected: all green. Confirms the redesign is additive — no legacy rating test regressed.

- [ ] **Step 2: Refresh a real league locally and run the comparison**

Start the backend (`make dev-api`), refresh a known league (`GET /api/league/<id>/refresh`), then:

```bash
PYTHONPATH=api python scripts/compare_franchise_models.py <id>
```

Inspect the table for face validity against intuition (the original complaint was "results feel wrong"). Sanity checks to apply:
- A heavy-but-bad trader is no longer inflated by trade *volume*.
- A strong draft-built non-trader is no longer dragged to the bottom by trades.
- Lineup-skill spreads owners sensibly (efficiency typically ~0.85–0.98).

- [ ] **Step 3: DECISION GATE — pick a model**

Present the comparison table to the user and decide **Model 1 (Results-primary)** vs **Model 2 (Two equal axes)**, plus any weight tuning. This selection drives Phase 2.

**Phase 2 (separate plan, after the decision):** swap the live read path (`leaderboard.owner_pillars` + `aggregations._all_time_ratings` → the redesign tree under the chosen model), update `GMRow.pillars` consumers and the Overview "Why this grade" UI (`OverviewTab.tsx`) to the `results`/`skill`/`outlook` keys, update the LLM pillar-highlight keys (`blurb_gen.BLURB_PROMPT_VERSION` bump to regenerate), run `next build`, and deploy (schema already bumped this phase). Do **not** start Phase 2 until the model is locked.

---

## Self-Review

**Spec coverage:**
- Results/Skill/Outlook pillar tree → Task 1 (configs) + Task 5 (assembly). ✓
- Trade skill replaces volume (zero-sum value + production, avg per trade, shrinkage, non-trader neutral) → Task 3 + Task 5. ✓
- Lineup skill (optimal-vs-actual, reuse `solve_optimal_lineup`) → Task 2 + Task 4. ✓
- Draft skill re-homed into Skill → Task 5 (`build_redesign_pillars` reads `outlook_signals[...]["draft_skill"]` into the skill pillar; outlook pillar excludes it). ✓
- Two models, build both, comparison artifact, decide before UI → Task 1 (weights) + Task 6 (script) + Task 7 (gate). ✓
- Cache migration (schema bump) → Task 4. ✓
- Non-breaking prod path / UI deferred → enforced by parallel service; Phase 2 note in Task 7. ✓
- Received-only production stats stay as descriptive trade stats → untouched (legacy aggregations/leaderboard unchanged). ✓

**Placeholder scan:** Task 4 Step 3c references the `roster_to_user_by_league` assembly pattern rather than quoting it (that merge code wasn't read during planning); mitigated by `compute_lineup_signals` degrading to zeros and the Task 6/7 smoke verifying the wired value. No "TODO"/"TBD"/"add error handling"-style gaps elsewhere.

**Type consistency:** `compute_gm_ratings(..., pillar_weights=, signal_weights=)` keyword names match across Tasks 1/5. `lineup_skill_signals`/`trade_skill_signals` signatures match between definition (Tasks 2/3), the adapter (Task 4), and the service (Task 5). `lineup_signals` field shape `{uid: {"lineup_skill": float}}` is consistent across Tasks 2/4/5. Trade-record shape `{"value_swing", "production"}` matches between Task 3 tests, Task 5 `_trade_records`, and the grades fields (`snapshot_value_swing`, `production_total`) confirmed in `aggregations._aggregate_owner_rows`.
