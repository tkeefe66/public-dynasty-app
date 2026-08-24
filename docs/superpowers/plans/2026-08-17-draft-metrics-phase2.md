# Draft Metrics Implementation Plan (Phase 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the draft board say what a draft actually returned — a correct Start %, the full five-metric run, and Points Above Round replacing Total Points as the owner ranking.

**Architecture:** One new phase (`"started"`) on the existing per-pick points function fixes a silent undercount. Two derived figures (Start %, Points Above Round) are computed in the view layer from figures already persisted, so nothing new is cached. Both screens — the league board and the owner Draft tab — read the same fields.

**Tech Stack:** Python 3.11, pytest, FastAPI/Pydantic, Next.js 14 + TypeScript, vitest.

**Spec:** `docs/superpowers/specs/2026-08-17-draft-board-redesign-design.md`

**Depends on:** phase 1 (`docs/superpowers/plans/2026-08-17-rookie-ecr-baseline.md`), merged on `new-draft-board`.

## Global Constraints

- **Branch:** all work on `new-draft-board`. Never commit to `main`.
- **No `SCHEMA_VERSION` bump.** `production_started` is additive on `drafted_picks`, already in the always-recomputed value layer. Read with `.get()` defaults so a pre-feature row cannot raise.
- **The five metrics are a fixed vocabulary in a fixed order:** Trade Value · Total Points · Regular Season Points · Playoff Points · Toilet Bowl Points. Do not rename or reorder them.
- **Regular + Playoff + Toilet is LESS than Started**, and that is correct — a bye week and a placement game belong to no phase. **Never present those three as summing to anything.**
- **Start % is `None` when `production_total == 0`**, never `0%`. A pick that never scored has no ratio; `0%` rendered from `0/0` reads as a verdict.
- **Never render "KTC" in UI.** It is "Trade Value" / "Value".
- Tailwind's JIT scanner needs complete arbitrary-value class strings as **literal text in source**. Grid templates are spelled out one literal per combination; never build them by concatenation.
- **Below 701px every column survives** as an alternate rendering. Nothing is `display:none` with no replacement.
- **Test commands:** engine `pytest tests/` from repo root (bare `pytest` breaks — `api/tests` and `tests/` are both packages named `tests`). Backend `cd api && pytest -v` (some `test_grader_service.py` tests take ~30s each). Frontend `cd web && npx vitest --config tests/vitest.config.ts run` (bare `npx vitest run` silently uses NO config and fails on JSX).

## Context established before this plan

**Owner totals exclude unpaired roster-weeks, and that is correct.** `grader_io.py::_assemble_played_matchups` emits a roster-week only when Sleeper returns it as exactly two paired entries with at least one non-zero score. Byes, eliminated rosters, and unplayed weeks are dropped — in this league's 2025 season that is week 15 (4 roster-weeks), week 17 (4) and week 18 (all 12).

This was chased down because an independent reconstruction ran ~6% above the app across 7 of 12 owners. Reproducing the pairing filter gives **12/12 exact**. The app is right. **Every figure in this phase is computed from that same filtered set** — do not "fix" the discrepancy, and do not compute production from raw Sleeper matchups.

It is also the direct cause of the Start % bug below: those dropped weeks are why a phase-summed numerator cannot equal a bench-inclusive denominator.

---

### Task 1: The `"started"` phase

`production_total` is bench-inclusive across all weeks. The three phase tallies count only weeks classified regular / live-title-path / losers-bracket. **A bye week or a 3rd/5th-place placement game belongs to no phase and is counted nowhere** — `playoff_phase.py`'s own docstring says so: "anything absent is a dropped week (bye, winners placement game)".

So `(regular + playoff + toilet) / total` undercounts, and it undercounts *more* for better teams, because better teams get byes.

**Files:**
- Modify: `src/sleeper_dynasty/engine/draft_results.py` — `started_points_while_on_roster`
- Test: `tests/test_draft_results_started.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `started_points_while_on_roster(..., phase="started")` — started points across **every** week, no phase filter.

- [ ] **Step 1: Write the failing test**

Create `tests/test_draft_results_started.py`:

```python
from sleeper_dynasty.engine.draft_results import started_points_while_on_roster

# One owner (u1 owns roster 1 in league "L"), one player "p".
# wk 1  regular season, started, 10.0
# wk 15 playoff window, started, 20.0, classified "playoff"
# wk 16 playoff window, started, 30.0, classified NOTHING — a bye. This is the
#       week the old formula lost.
# wk 17 playoff window, BENCHED, 40.0, classified "playoff"
MATCHUPS = {
    ("L", 1, 1): {"starters": ["p"], "players": ["p"], "players_points": {"p": 10.0}},
    ("L", 15, 1): {"starters": ["p"], "players": ["p"], "players_points": {"p": 20.0}},
    ("L", 16, 1): {"starters": ["p"], "players": ["p"], "players_points": {"p": 30.0}},
    ("L", 17, 1): {"starters": [], "players": ["p"], "players_points": {"p": 40.0}},
}
R2U = {"L": {1: "u1"}}
PHASES = {("L", 15, 1): "playoff", ("L", 17, 1): "playoff"}
PWS = {"L": 15}


def _pts(phase):
    return started_points_while_on_roster(
        "p", "u1", phase=phase, matchups=MATCHUPS, roster_to_user_by_league=R2U,
        phase_by_lwr=PHASES, playoff_week_start_by_league=PWS)


def test_total_is_bench_inclusive_across_every_week():
    assert _pts("total") == 100.0


def test_started_counts_every_started_week_regardless_of_phase():
    # 10 (regular) + 20 (playoff) + 30 (BYE — belongs to no phase) = 60.
    # The benched 40 is excluded because it was never started.
    assert _pts("started") == 60.0


def test_the_phase_tallies_still_exclude_the_bye_week():
    assert _pts("regular") == 10.0
    assert _pts("playoff") == 20.0
    assert _pts("toilet") == 0.0


def test_phases_sum_to_less_than_started_and_the_gap_is_the_bye():
    phases = _pts("regular") + _pts("playoff") + _pts("toilet")
    assert phases == 30.0
    assert _pts("started") - phases == 30.0  # exactly the bye week


def test_started_is_owner_gated_like_every_other_phase():
    assert started_points_while_on_roster(
        "p", "someone-else", phase="started", matchups=MATCHUPS,
        roster_to_user_by_league=R2U, phase_by_lwr=PHASES,
        playoff_week_start_by_league=PWS) == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_draft_results_started.py -v`
Expected: `test_started_counts_every_started_week_regardless_of_phase` FAILS with `assert 0.0 == 60.0` — `"started"` currently falls into the phase filter, matches no `wk_phase`, and returns 0.0.

- [ ] **Step 3: Implement**

In `src/sleeper_dynasty/engine/draft_results.py`, in `started_points_while_on_roster`, change the phase-filter guard from `if phase != "total":` to exempt `"started"` as well, and extend the docstring.

Replace this line:

```python
        if phase != "total":
```

with:

```python
        # "started" is started-only but phase-BLIND: a bye week and a placement
        # game belong to no phase, so filtering by phase would silently drop
        # them. That undercount is worse for better teams, because better teams
        # get byes — see the docstring.
        if phase not in ("total", "started"):
```

And add to the docstring's phase list, after the `"total"` line:

```
      - "started" -- started points in EVERY week, phase-blind. Regular +
        playoff + toilet is LESS than this: a bye or placement week belongs to
        no phase. Use this as the denominator's partner for Start %, never the
        sum of the three.
```

`started_only = phase != "total"` and `roster_field = "starters" if started_only else "players"` already do the right thing for `"started"` — do not change them.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_draft_results_started.py tests/test_draft_results.py tests/test_draft_results_baseline.py -v`
Expected: PASS. The existing files must pass unchanged.

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/draft_results.py tests/test_draft_results_started.py
git commit -m "fix(engine): add a phase-blind started tally, so byes stop vanishing"
```

---

### Task 2: Persist `production_started` per pick

**Files:**
- Modify: `src/sleeper_dynasty/engine/draft_results.py` — `build_drafted_pick_results`
- Modify: `api/app/services/grader.py` — the `_points` closure's phase list is unchanged; only the row gains a key
- Test: `tests/test_draft_results_started_field.py`

**Interfaces:**
- Consumes: `started_points_while_on_roster(..., phase="started")` (Task 1).
- Produces: `"production_started"` on every row emitted by `build_drafted_pick_results`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_draft_results_started_field.py`:

```python
from sleeper_dynasty.engine.draft_results import build_drafted_pick_results
from sleeper_dynasty.engine.draft_signals import DraftedPick

PICK = DraftedPick(
    draft_id="d1", round=1, slot=4, picks_in_round=12, player_id="111",
    drafter_id="u1", draft_season=2025, pick_no=4, draft_kind="rookie",
    is_keeper=False, gradeable=True)

# phase -> points, so the test can assert each lands in its own key.
BY_PHASE = {"total": 100.0, "started": 60.0, "regular": 10.0,
            "playoff": 20.0, "toilet": 0.0}


def _build():
    return build_drafted_pick_results(
        [PICK], ktc_floats={}, normalized_name_by_pid={}, names={}, positions={},
        extremes_by_name={}, acquired_set=set(),
        points_fn=lambda pid, uid, phase: BY_PHASE[phase],
        games_fn=lambda pid, uid: 3, current_holders={}, traded_away_set=set())


def test_production_started_is_emitted():
    assert _build()[0]["production_started"] == 60.0


def test_the_other_four_metrics_are_unchanged():
    row = _build()[0]
    assert row["production_total"] == 100.0
    assert row["production_regular"] == 10.0
    assert row["production_playoff"] == 20.0
    assert row["production_toilet"] == 0.0


def test_started_is_requested_with_its_own_phase_name():
    seen = []

    def spy(pid, uid, phase):
        seen.append(phase)
        return BY_PHASE[phase]

    build_drafted_pick_results(
        [PICK], ktc_floats={}, normalized_name_by_pid={}, names={}, positions={},
        extremes_by_name={}, acquired_set=set(), points_fn=spy,
        games_fn=lambda pid, uid: 0, current_holders={}, traded_away_set=set())
    assert "started" in seen
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_draft_results_started_field.py -v`
Expected: FAIL with `KeyError: 'production_started'`.

- [ ] **Step 3: Implement**

In `build_drafted_pick_results`, in the dict appended per pick, add immediately after the `"production_total"` line:

```python
            # Started points across EVERY week — the honest denominator partner
            # for Start %. Not the sum of the three phase tallies: a bye or a
            # placement week belongs to no phase and would vanish from that sum.
            "production_started": points_fn(p.player_id, p.drafter_id, "started"),
```

No change is needed in `grader.py` — its `_points` closure already forwards any `phase` string through to `started_points_while_on_roster`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_draft_results_started_field.py tests/test_draft_results.py tests/test_draft_results_baseline.py -v`
Expected: PASS, existing files unchanged.

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/draft_results.py tests/test_draft_results_started_field.py
git commit -m "feat(engine): persist production_started per drafted pick"
```

---

### Task 3: Points Above Round

Each pick's production minus the **class-round average**, summed per owner. Zero-sum within a class, which is the property that makes it fair: it rewards drafting well from a bad slot instead of rewarding whoever picked first.

Round-average rather than a per-slot curve because with 36 picks there is exactly one observation per slot, so "average at that slot" is that pick itself and every delta collapses to zero. It is also the pattern already in this file — `build_drafted_pick_results` groups `avg_slot_value` on `(draft_season, round)` for exactly this reason.

**Files:**
- Create: `src/sleeper_dynasty/engine/draft_par.py`
- Test: `tests/test_draft_par.py`

**Interfaces:**
- Consumes: rows from `build_drafted_pick_results`.
- Produces:
  - `round_averages(rows) -> dict[int, float]` — `{round: mean production_total}`
  - `points_above_round(rows) -> dict[str, float]` — `{drafter_id: summed PAR}`
  - `pick_par(row, averages) -> float`

- [ ] **Step 1: Write the failing test**

Create `tests/test_draft_par.py`:

```python
import pytest

from sleeper_dynasty.engine.draft_par import (
    pick_par, points_above_round, round_averages,
)


def row(rnd, total, uid="u1", **over):
    r = {"round": rnd, "production_total": total, "drafter_id": uid,
         "is_keeper": False, "gradeable": True}
    r.update(over)
    return r


ROWS = [
    row(1, 200.0, "a"), row(1, 100.0, "b"), row(1, 0.0, "c"),   # r1 avg 100
    row(2, 60.0, "a"), row(2, 30.0, "b"), row(2, 0.0, "c"),     # r2 avg 30
]


def test_round_averages_are_per_round():
    assert round_averages(ROWS) == {1: 100.0, 2: 30.0}


def test_pick_par_is_production_minus_its_own_rounds_average():
    avgs = round_averages(ROWS)
    assert pick_par(row(1, 200.0), avgs) == 100.0
    assert pick_par(row(2, 0.0), avgs) == -30.0


def test_par_sums_to_zero_across_the_class():
    # The property that makes it fair: it is zero-sum, so it measures drafting
    # well rather than picking early.
    assert sum(points_above_round(ROWS).values()) == pytest.approx(0.0)


def test_par_is_summed_per_owner():
    par = points_above_round(ROWS)
    assert par["a"] == pytest.approx(130.0)   # +100 (r1) +30 (r2)
    assert par["c"] == pytest.approx(-130.0)  # -100 (r1) -30 (r2)


def test_keeper_and_auction_picks_are_excluded_from_both_the_average_and_the_sum():
    # A keep is not a draft decision, and an auction's pick_no is the order
    # money changed hands. Leaving either in would move the yardstick every
    # real pick is measured against.
    rows = ROWS + [row(1, 900.0, "d", is_keeper=True),
                   row(1, 900.0, "e", gradeable=False)]
    assert round_averages(rows) == {1: 100.0, 2: 30.0}
    par = points_above_round(rows)
    assert "d" not in par and "e" not in par


def test_a_round_with_no_scorable_picks_is_absent_rather_than_zero():
    assert round_averages([row(3, 0.0, "a", is_keeper=True)]) == {}


def test_empty_input_is_empty_not_an_error():
    assert round_averages([]) == {}
    assert points_above_round([]) == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_draft_par.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sleeper_dynasty.engine.draft_par'`

- [ ] **Step 3: Implement**

Create `src/sleeper_dynasty/engine/draft_par.py`:

```python
"""Points Above Round — how much more a pick returned than its round's average.

Ranking a draft class by raw Total Points ranks draft POSITION: whoever picked
first tends to win, which is not a measure of anything the owner did. PAR
subtracts what a pick in the same round of the same class typically returned,
so it is **zero-sum within a class** and rewards drafting well from a bad slot.

Round-average rather than a per-slot expectation curve: with one observation
per slot, "the average at that slot" is that pick itself and every delta
collapses to zero. Rounds give a real sample. It is also the grouping
``build_drafted_pick_results`` already uses for ``avg_slot_value``.

Keepers and auction picks are excluded from BOTH the average and the sum — a
keep is not a draft decision, and an auction's ``pick_no`` is the order money
changed hands. Leaving either in would move the yardstick every real pick is
measured against.

Pure. No I/O.
"""

from __future__ import annotations

from collections import defaultdict


def _scored(rows: list[dict]) -> list[dict]:
    """Only picks this draft is answerable for.

    ``gradeable`` is absent on pre-feature rows, which predate auction support
    and were all snake/linear — default True rather than silently emptying them.
    """
    return [r for r in rows
            if not r.get("is_keeper") and r.get("gradeable", True)]


def round_averages(rows: list[dict]) -> dict[int, float]:
    """``{round: mean production_total}`` over scored picks.

    A round with no scored picks is absent rather than 0.0 — there is no
    yardstick for it, and 0.0 would read as one.
    """
    by_round: dict[int, list[float]] = defaultdict(list)
    for r in _scored(rows):
        by_round[int(r.get("round") or 0)].append(
            float(r.get("production_total") or 0.0))
    return {rnd: sum(v) / len(v) for rnd, v in by_round.items() if v}


def pick_par(row: dict, averages: dict[int, float]) -> float:
    """One pick's production minus its own round's average.

    A round absent from ``averages`` yields 0.0: the pick is unmeasured, and
    crediting or debiting it against a yardstick that does not exist would be
    an invention.
    """
    rnd = int(row.get("round") or 0)
    if rnd not in averages:
        return 0.0
    return float(row.get("production_total") or 0.0) - averages[rnd]


def points_above_round(rows: list[dict]) -> dict[str, float]:
    """``{drafter_id: summed PAR}`` over scored picks. Sums to ~0 per class."""
    averages = round_averages(rows)
    out: dict[str, float] = defaultdict(float)
    for r in _scored(rows):
        uid = str(r.get("drafter_id") or "")
        if not uid:
            continue
        out[uid] += pick_par(r, averages)
    return dict(out)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_draft_par.py -v`
Expected: PASS, 7 tests.

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/draft_par.py tests/test_draft_par.py
git commit -m "feat(engine): Points Above Round, zero-sum within a draft class"
```

---

### Task 4: Surface the metrics on the league board

**Files:**
- Modify: `api/app/models/league.py` — `DraftBoardPick`, `DraftBoardOwner`
- Modify: `api/app/services/draft_board_view.py`
- Test: `api/tests/test_draft_board_metrics.py`

**Interfaces:**
- Consumes: `production_started` rows (Task 2), `points_above_round` (Task 3).
- Produces: `DraftBoardPick.production_started` / `.production_regular` / `.production_playoff` / `.production_toilet` / `.games_started`; `DraftBoardOwner.points_above_round` and the same four production fields plus `production_started`.

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_draft_board_metrics.py`:

```python
from app.services.draft_board_view import build_draft_board
from tests.helpers import minimal_chain_cache_entry


def pick(**over):
    r = dict(player_id="p1", full_name="A Rookie", position="RB", drafter_id="u1",
             round=1, slot=1, picks_in_round=12, pick_no=1, draft_season=2025,
             production_total=100.0, production_started=60.0,
             production_regular=10.0, production_playoff=20.0,
             production_toilet=0.0, games_started=3)
    r.update(over)
    return r


def _board(*picks):
    return build_draft_board(
        minimal_chain_cache_entry(drafted_picks=list(picks)), season=2025)


def test_the_five_metric_run_reaches_each_pick():
    p = _board(pick(), pick(player_id="p2", pick_no=2)).picks[0]
    assert (p.production_total, p.production_started, p.production_regular,
            p.production_playoff, p.production_toilet, p.games_started) == (
        100.0, 60.0, 10.0, 20.0, 0.0, 3)


def test_phases_sum_to_less_than_started_and_that_is_not_an_error():
    # A bye or placement week belongs to no phase. This is the contract, so it
    # is asserted rather than left as a surprise for the next reader.
    p = _board(pick(), pick(player_id="p2", pick_no=2)).picks[0]
    assert p.production_regular + p.production_playoff + p.production_toilet < p.production_started


def test_owner_points_above_round_is_zero_sum_across_the_class():
    b = _board(pick(drafter_id="a", production_total=200.0),
               pick(player_id="p2", pick_no=2, drafter_id="b", production_total=0.0))
    assert round(sum(o.points_above_round or 0.0 for o in b.owners), 6) == 0.0


def test_owners_are_sorted_by_points_above_round_when_graded():
    b = _board(pick(drafter_id="a", production_total=200.0),
               pick(player_id="p2", pick_no=2, drafter_id="b", production_total=0.0))
    assert b.graded is True
    assert [o.user_id for o in b.owners] == ["a", "b"]


def test_pre_feature_rows_default_rather_than_raise():
    # Rows written before phase 2 carry no production_started key.
    p = _board({"player_id": "p1", "full_name": "X", "position": "RB",
                "drafter_id": "u1", "round": 1, "slot": 1, "picks_in_round": 12,
                "pick_no": 1, "draft_season": 2025, "production_total": 0.0},
               {"player_id": "p2", "full_name": "Y", "position": "WR",
                "drafter_id": "u2", "round": 1, "slot": 2, "picks_in_round": 12,
                "pick_no": 2, "draft_season": 2025, "production_total": 0.0}).picks[0]
    assert p.production_started == 0.0
    assert p.games_started == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && pytest tests/test_draft_board_metrics.py -v`
Expected: FAIL with `AttributeError: 'DraftBoardPick' object has no attribute 'production_started'`

- [ ] **Step 3: Add the model fields**

In `api/app/models/league.py`, inside `class DraftBoardPick`, after `production_total`:

```python
    # Started points across EVERY week — phase-blind. Regular + Playoff +
    # Toilet is LESS than this, because a bye or placement week belongs to no
    # phase. Never present those three as summing to anything.
    production_started: float = 0.0
    production_regular: float = 0.0
    production_playoff: float = 0.0
    production_toilet: float = 0.0
    games_started: int = 0
```

Inside `class DraftBoardOwner`, after `production_total`:

```python
    production_started: float = 0.0
    production_regular: float = 0.0
    production_playoff: float = 0.0
    production_toilet: float = 0.0
    # Summed pick production minus each pick's round average. Zero-sum across
    # the class, so it measures drafting well rather than picking early. Null
    # when the class has nothing scorable.
    points_above_round: float | None = None
```

- [ ] **Step 4: Populate them in the view**

In `api/app/services/draft_board_view.py`:

Add to the `DraftBoardPick(...)` construction, after `production_total=...`:

```python
            production_started=float(r.get("production_started") or 0.0),
            production_regular=float(r.get("production_regular") or 0.0),
            production_playoff=float(r.get("production_playoff") or 0.0),
            production_toilet=float(r.get("production_toilet") or 0.0),
            games_started=int(r.get("games_started") or 0),
```

Import PAR at the top of the file, beside the existing `owner_adp_grades` import:

```python
from sleeper_dynasty.engine.draft_par import points_above_round
```

Before the owner loop, compute the per-owner rollups over `scored`:

```python
    # Every figure here comes from the SAME `scored` list the ADP grade uses,
    # so the two can never carry different definitions of "this owner's draft".
    par_by_owner = points_above_round(scored)
    by_owner: dict[str, dict] = {}
    for r in scored:
        uid = str(r.get("drafter_id") or "")
        acc = by_owner.setdefault(uid, {
            "production_started": 0.0, "production_regular": 0.0,
            "production_playoff": 0.0, "production_toilet": 0.0})
        for key in acc:
            acc[key] += float(r.get(key) or 0.0)
```

Add to the `DraftBoardOwner(...)` construction:

```python
            production_started=by_owner.get(uid, {}).get("production_started", 0.0),
            production_regular=by_owner.get(uid, {}).get("production_regular", 0.0),
            production_playoff=by_owner.get(uid, {}).get("production_playoff", 0.0),
            production_toilet=by_owner.get(uid, {}).get("production_toilet", 0.0),
            points_above_round=par_by_owner.get(uid),
```

Change the owner sort so a graded class ranks by PAR instead of raw production. Replace the existing `owners.sort(...)` key with:

```python
    # Best draft first. PAR when graded — ranking by raw Total Points ranks
    # draft POSITION, since whoever picked first tends to win. ADP delta
    # otherwise. Either way the figure sorted by is one the board shows.
    owners.sort(
        key=lambda o: (
            (o.points_above_round or 0.0) if graded
            else (o.adp_total_delta if o.adp_total_delta is not None else 0.0)
        ),
        reverse=True,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd api && pytest tests/test_draft_board_metrics.py tests/test_draft_board_view.py tests/test_draft_board_baseline.py -v`
Expected: PASS. The two existing files must pass unchanged.

- [ ] **Step 6: Commit**

```bash
git add api/app/models/league.py api/app/services/draft_board_view.py api/tests/test_draft_board_metrics.py
git commit -m "feat(api): five-metric run and Points Above Round on the draft board"
```

---

### Task 5: Render the metrics

**Files:**
- Modify: `web/lib/types.ts`
- Modify: `web/components/DraftBoard.tsx`
- Modify: `web/components/DraftPicksMobile.tsx`
- Test: `web/tests/draft-board.test.tsx`

**Interfaces:**
- Consumes: the fields added in Task 4.
- Produces: no new exports; two rendered tables.

- [ ] **Step 1: Add the TypeScript fields**

In `web/lib/types.ts`, add to `DraftBoardPick`:

```typescript
  production_started?: number;
  production_regular?: number;
  production_playoff?: number;
  production_toilet?: number;
  games_started?: number;
```

and to `DraftBoardOwner`:

```typescript
  production_started?: number;
  production_regular?: number;
  production_playoff?: number;
  production_toilet?: number;
  points_above_round?: number | null;
```

- [ ] **Step 2: Add the Start % helper and its test**

Add to `web/components/DraftBoard.tsx`, beside the existing `Signed` helper:

```tsx
/** Share of Total Points that came from the starting lineup.
 *
 *  Null — an em-dash — when nothing was scored. A pick that never scored has
 *  no ratio, and `0/0` rendered as "0%" reads as a verdict on the pick rather
 *  than an absence of data. */
function StartPct({ started, total }: { started?: number; total?: number }) {
  if (!total) return <span className="text-dim">—</span>;
  return <span>{Math.round((100 * (started ?? 0)) / total)}%</span>;
}
```

Add to `web/tests/draft-board.test.tsx`:

```tsx
it("renders an em-dash rather than 0% for a pick that never scored", () => {
  render(<DraftBoard leagueId="lg" board={{
    ...base, graded: true,
    picks: [{ ...base.picks[0], production_total: 0, production_started: 0 }],
  }} />);
  expect(screen.queryByText("0%")).toBeNull();
});

it("shows Start % as a whole percentage of Total Points", () => {
  render(<DraftBoard leagueId="lg" board={{
    ...base, graded: true,
    picks: [{ ...base.picks[0], production_total: 200, production_started: 60 }],
  }} />);
  expect(screen.getAllByText("30%").length).toBeGreaterThan(0);
});
```

- [ ] **Step 3: Add the columns to both renderings**

In `DraftBoard.tsx`'s `PicksSection`, add columns after Total Points, in the fixed vocabulary order: **Start %**, **Regular Season**, **Playoff**, **Toilet Bowl**, **GS**. In `OwnersSection`, replace the Total Points sort column's prominence with **Points Above Round** (rendered via `Signed`) and add the same production run.

**Spell out every grid template as a complete literal string**, one per combination, extending the existing `GRID_*` constants. Tailwind's JIT scanner cannot see a template built by interpolation, and an interpolated grid silently loses its columns in a production build while every test still passes.

In `DraftPicksMobile.tsx`, add the same figures as labelled `Stat` cells. **Every column must survive below 701px** — this screen's own header docstring makes that binding, because draft night on a phone is its primary audience.

- [ ] **Step 4: Run both suites**

Run: `cd web && npx vitest --config tests/vitest.config.ts run`
Expected: PASS including `furniture-rules.test.ts`. Satisfy the drift guard by fixing your code — never by adding a file to an exception list.

- [ ] **Step 5: Commit**

```bash
git add web/lib/types.ts web/components/DraftBoard.tsx web/components/DraftPicksMobile.tsx web/tests/draft-board.test.tsx
git commit -m "feat(web): Start %, the five-metric run, and Points Above Round"
```

---

### Task 6: The owner Draft tab

The two screens must not diverge: same figures, same `scored` list, same definitions.

**Files:**
- Modify: `api/app/models/owner.py` — `DraftPickResult`
- Modify: `api/app/services/owner_view.py`
- Modify: `web/components/ownerdeepdive/PastPicksTable.tsx`
- Test: `api/tests/test_owner_draft_metrics.py`

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_owner_draft_metrics.py`:

```python
from app.models.owner import DraftPickResult


def test_draft_pick_result_carries_started_points():
    r = DraftPickResult(
        player_id="p", full_name="X", position="RB", round=1, slot=1,
        picks_in_round=12, draft_season=2025, acquired_via_trade=False,
        current_value=0.0, lowest_value=0.0, highest_value=0.0,
        avg_slot_value=0.0, production_total=100.0, production_started=60.0,
        production_regular=10.0, production_playoff=20.0, production_toilet=0.0)
    assert r.production_started == 60.0


def test_production_started_defaults_for_pre_feature_rows():
    r = DraftPickResult(
        player_id="p", full_name="X", position="RB", round=1, slot=1,
        picks_in_round=12, draft_season=2025, acquired_via_trade=False,
        current_value=0.0, lowest_value=0.0, highest_value=0.0,
        avg_slot_value=0.0, production_total=0.0, production_regular=0.0,
        production_playoff=0.0, production_toilet=0.0)
    assert r.production_started == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && pytest tests/test_owner_draft_metrics.py -v`
Expected: FAIL — `DraftPickResult` has no `production_started`.

- [ ] **Step 3: Implement**

In `api/app/models/owner.py`, add to `DraftPickResult` after `production_total`:

```python
    # Phase-blind started points. Regular + Playoff + Toilet is LESS than this;
    # the gap is bye and placement weeks, which belong to no phase.
    production_started: float = 0.0
```

In `api/app/services/owner_view.py`, where `DraftPickResult` rows are built from `drafted_picks`, add `production_started=float(r.get("production_started") or 0.0),`.

In `web/components/ownerdeepdive/PastPicksTable.tsx`, add a **Start %** column beside Total Points, using the same null-when-zero rule as the board. Extend its existing literal grid templates — that file already spells out every combination for the Tailwind JIT scanner; follow the idiom rather than collapsing it.

- [ ] **Step 4: Run both suites**

Run: `cd api && pytest tests/test_owner_draft_metrics.py tests/test_owner_view_draft_picks.py tests/test_owner_draft_picks.py -v`
Then: `cd web && npx vitest --config tests/vitest.config.ts run`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/app/models/owner.py api/app/services/owner_view.py web/components/ownerdeepdive/PastPicksTable.tsx api/tests/test_owner_draft_metrics.py
git commit -m "feat: Start % on the owner Draft tab, matching the board"
```

---

### Task 7: Record the reconciliation finding in the spec

The "owner totals exclude unpaired roster-weeks" behaviour is non-obvious, it is now load-bearing for PAR, and an independent reconstruction that does not reproduce it lands ~6% high. Undocumented, it gets rediscovered as a bug.

**Files:**
- Modify: `docs/superpowers/specs/2026-08-17-draft-board-redesign-design.md`

- [ ] **Step 1: Add the note**

In the spec's **Metrics** section, immediately before "### The Started % trap", insert:

```markdown
### What counts as a played week

`grader_io.py::_assemble_played_matchups` emits a roster-week only when Sleeper
returns it as **exactly two paired entries with at least one non-zero score**.
Byes, eliminated rosters and unplayed weeks are dropped — in this league's 2025
season, week 15 (4 roster-weeks), week 17 (4) and week 18 (all 12).

Every production figure in this design is computed over that filtered set. An
independent reconstruction that reads raw Sleeper matchups instead lands about
**6% high** across most owners; reproducing the pairing filter reconciles it to
12/12 exact. The app is correct.

This is also the direct cause of the Started % trap below: those dropped weeks
are why a phase-summed numerator cannot equal a bench-inclusive denominator.
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/specs/2026-08-17-draft-board-redesign-design.md
git commit -m "docs: record why owner totals exclude unpaired roster-weeks"
```

---

### Task 8: Full-suite verification

- [ ] **Step 1: Run every suite**

```bash
pytest tests/
cd api && pytest -v && cd ..
cd web && npx vitest --config tests/vitest.config.ts run && cd ..
```

Expected: all PASS. Do not proceed on a failure.

- [ ] **Step 2: Confirm the reconciliation invariant on real data**

```bash
cd "/Users/tomkeefe/Code Apps/public-dynasty"
python3 - <<'PY'
from sleeper_dynasty.engine.draft_par import points_above_round, round_averages
rows = [
    {"round": 1, "production_total": 200.0, "drafter_id": "a"},
    {"round": 1, "production_total": 100.0, "drafter_id": "b"},
    {"round": 2, "production_total": 60.0, "drafter_id": "a"},
    {"round": 2, "production_total": 0.0, "drafter_id": "b"},
]
par = points_above_round(rows)
print("round averages:", round_averages(rows))
print("PAR:", par, "sum:", round(sum(par.values()), 9))
assert abs(sum(par.values())) < 1e-9, "PAR must be zero-sum within a class"
print("zero-sum invariant holds")
PY
```

Expected: `zero-sum invariant holds`. If PAR does not sum to zero, the exclusion rules diverged between `round_averages` and `points_above_round` — fix before shipping, because a non-zero-sum PAR quietly advantages whoever held the excluded picks.

- [ ] **Step 3: Commit any fixes**

Do **not** push. The branch already has an open PR (#10); pushing is the repository owner's call.

---

## Self-Review

**Spec coverage (phase 2 only).** The `"started"` phase → Task 1. `production_started` persisted → Task 2. Start % as `started/total`, null at zero → Tasks 5 and 6. Points Above Round on Total Points, zero-sum, keeper/auction excluded → Task 3, surfaced in Task 4. The five-metric run on both screens → Tasks 4–6. "Regular + Playoff + Toilet never presented as a sum" → asserted in Task 4's test and stated in three docstrings. No `SCHEMA_VERSION` bump → `production_started` is additive on `drafted_picks` in the value layer, with `.get()` defaults proven by Task 4's pre-feature test.

**Deferred to later phases:** cohort Hit/Average/Bust verdicts (phase 3), the grouped sortable header and per-column tooltips and the nav entry (phase 4), needs reconstruction (phase 5).

**Type consistency.** `production_started` is spelled identically in `draft_results.py`, `draft_board_view.py`, `league.py`, `owner.py`, `owner_view.py` and `types.ts`. `points_above_round` is both the engine function name and the `DraftBoardOwner` field name — deliberate, so the field's provenance is unambiguous. `round_averages` / `pick_par` / `points_above_round` are used with the same signatures in Task 3's tests and Task 4's view code.

**One known imprecision, accepted.** `pick_par` returns 0.0 for a round absent from `averages`, which can only happen when that round has no scored picks — in which case the pick itself is unscored and excluded from the sum anyway. The branch is unreachable from `points_above_round`; it exists so `pick_par` is safe to call directly from a future per-pick surface.
