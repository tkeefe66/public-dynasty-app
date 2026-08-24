# Window Receipt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the Window chip (Competing now / Peaking / Ascending / Descending / Rebuilding) a full traceable receipt: clicking it opens the owner page's Outlook tab, which leads with a quadrant map + six weighted-input bars explaining exactly why the label is what it is.

**Architecture:** The engine derives each axis score (Strength, Trajectory) as the sum of per-input contributions, so the receipt and the label can never disagree. The breakdown rides the existing `dynasty_outlooks` value layer (recomputed every refresh, no `SCHEMA_VERSION` bump), flows through `owner_view` into `OutlookView`, and renders in a new `WindowSection` component. Spec: `docs/superpowers/specs/2026-08-03-window-receipt-design.md`.

**Tech Stack:** Python dataclasses (engine), Pydantic (API), Next.js 14 + Tailwind CSS-token classes (web), pytest + vitest.

## Global Constraints

- Never show "KTC" in any UI string — it is "Trade Value" / "Value"; the receipt row is labeled "Roster value".
- No LLM anywhere in this feature — the summary sentence is deterministic frontend code.
- `classify_window` thresholds and the five-label taxonomy are unchanged.
- Missing breakdown (pre-upgrade cache) must degrade to the current label-only view at every layer — no 500s.
- Every quadrant region carries a text label — stage identity is never color-alone.
- Frontend colors come from the existing chip palette (`rgba(74,222,128,…)` green, `rgba(129,140,248,…)` indigo, `rgba(251,191,36,…)` amber, `rgba(248,113,113,…)` red) and CSS tokens (`--pos`, `--window`, `--warn`, `--neg`, `--accent`); text always wears ink tokens, never region fills.
- Run commands from repo root unless the step says otherwise. Engine tests: `pytest`. API tests: `cd api && pytest`. Web tests: `cd web && npx vitest run`.

---

### Task 1: Engine — WindowInput/WindowBreakdown dataclasses + axis-row builders

**Files:**
- Modify: `src/sleeper_dynasty/engine/dynasty.py` (around lines 280–352, the "Window classification" section)
- Test: `tests/test_dynasty.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `WindowInput(key, raw, score, weight, contribution)` and `WindowBreakdown(strength_score, trajectory_score, strength_inputs, trajectory_inputs, capital_status)` dataclasses; `strength_inputs(roster_rank_pct, playoff_rate) -> list[WindowInput]`; `trajectory_inputs(youth_quality_pct, draft_skill_z, draft_capital_pct_rank, yoy_rating_delta) -> list[WindowInput]`. `compute_strength_score` / `compute_trajectory_score` keep their exact signatures and numeric behavior.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_dynasty.py` (it already imports `pytest` patterns; add the new names to the existing `from sleeper_dynasty.engine.dynasty import (...)` at the top: `strength_inputs`, `trajectory_inputs`):

```python
def test_strength_inputs_sum_to_score():
    rows = strength_inputs(roster_rank_pct=0.3, playoff_rate=0.6)
    assert [r.key for r in rows] == ["roster_value_rank", "playoff_rate"]
    assert sum(r.weight for r in rows) == pytest.approx(1.0)
    assert sum(r.contribution for r in rows) == pytest.approx(
        compute_strength_score(roster_rank_pct=0.3, playoff_rate=0.6))


def test_trajectory_inputs_sum_to_score():
    rows = trajectory_inputs(
        youth_quality_pct=0.25, draft_skill_z=0.5,
        draft_capital_pct_rank=0.4, yoy_rating_delta=-80.0)
    assert [r.key for r in rows] == [
        "draft_skill", "draft_capital", "youth", "yoy_momentum"]
    assert sum(r.weight for r in rows) == pytest.approx(1.0)
    assert sum(r.contribution for r in rows) == pytest.approx(
        compute_trajectory_score(
            youth_quality_pct=0.25, draft_skill_z=0.5,
            draft_capital_pct_rank=0.4, yoy_rating_delta=-80.0))


def test_window_input_contribution_is_weight_times_score():
    for r in trajectory_inputs(0.2, -1.0, 0.9, 250.0):
        assert r.contribution == pytest.approx(r.weight * r.score)
        assert 0.0 <= r.score <= 100.0
```

If `import pytest` is missing at the top of the file, add it.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_dynasty.py -v -k "inputs_sum or contribution_is"`
Expected: FAIL with `ImportError: cannot import name 'strength_inputs'`

- [ ] **Step 3: Implement dataclasses and builders**

In `src/sleeper_dynasty/engine/dynasty.py`, in the "Window classification" section, add above `compute_strength_score`:

```python
@dataclass
class WindowInput:
    """One weighted input to a window axis score."""

    key: str            # stable id, e.g. "roster_value_rank"
    raw: float          # the input as consumed (pct, z-score, delta, …)
    score: float        # normalized 0-100
    weight: float       # weight within its axis (axis weights sum to 1.0)
    contribution: float # weight * score


@dataclass
class WindowBreakdown:
    """Full receipt for a window classification: both axis scores derived
    as the sum of their inputs' contributions, so receipt and label can
    never disagree."""

    strength_score: float
    trajectory_score: float
    strength_inputs: list[WindowInput]
    trajectory_inputs: list[WindowInput]
    capital_status: str  # "pick-rich" | "neutral" | "pick-poor" tiebreaker


def strength_inputs(
    roster_rank_pct: float, playoff_rate: float,
) -> list[WindowInput]:
    """The Strength axis as per-input rows; the score is their sum."""
    rows = [
        ("roster_value_rank", roster_rank_pct, (1 - roster_rank_pct) * 100, 0.60),
        ("playoff_rate", playoff_rate, playoff_rate * 100, 0.40),
    ]
    return [
        WindowInput(key=k, raw=r, score=s, weight=w, contribution=w * s)
        for k, r, s, w in rows
    ]


def trajectory_inputs(
    youth_quality_pct: float,
    draft_skill_z: float,
    draft_capital_pct_rank: float,
    yoy_rating_delta: float,
) -> list[WindowInput]:
    """The Trajectory axis as per-input rows; the score is their sum."""
    youth_score = min(100.0, youth_quality_pct * 250)             # 40% young = 100
    skill_score = max(0.0, min(100.0, 50 + draft_skill_z * 25))   # z=0 → 50
    capital_score = (1 - draft_capital_pct_rank) * 100
    yoy_score = max(0.0, min(100.0, (yoy_rating_delta + 200) / 4))  # ±200 → 0-100
    rows = [
        ("draft_skill", draft_skill_z, skill_score, 0.40),
        ("draft_capital", draft_capital_pct_rank, capital_score, 0.30),
        ("youth", youth_quality_pct, youth_score, 0.15),
        ("yoy_momentum", yoy_rating_delta, yoy_score, 0.15),
    ]
    return [
        WindowInput(key=k, raw=r, score=s, weight=w, contribution=w * s)
        for k, r, s, w in rows
    ]
```

Then replace the bodies of the two compute functions with sums over the builders (keep their signatures and docstrings; delete the now-duplicated normalization math and the weight comment block from `compute_trajectory_score` — it moves into `trajectory_inputs`):

```python
def compute_strength_score(roster_rank_pct: float, playoff_rate: float) -> float:
    ...existing docstring...
    return sum(i.contribution for i in strength_inputs(roster_rank_pct, playoff_rate))


def compute_trajectory_score(
    youth_quality_pct: float,
    draft_skill_z: float,
    draft_capital_pct_rank: float,
    yoy_rating_delta: float,
) -> float:
    ...existing docstring...
    return sum(i.contribution for i in trajectory_inputs(
        youth_quality_pct, draft_skill_z, draft_capital_pct_rank,
        yoy_rating_delta))
```

Move the "Youth gets less weight" comment from the old `compute_trajectory_score` body into `trajectory_inputs` next to the weights.

- [ ] **Step 4: Run the full engine suite**

Run: `pytest tests/test_dynasty.py -v`
Expected: ALL PASS — the new tests plus every pre-existing `compute_*`/`classify_window` test (the sums are algebraically identical to the old formulas).

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/dynasty.py tests/test_dynasty.py
git commit -m "feat(engine): window axis scores derived from per-input receipt rows"
```

---

### Task 2: Engine — attach `window_breakdown` to the outlook and serialize it

**Files:**
- Modify: `src/sleeper_dynasty/engine/dynasty.py` (`DynastyOutlook` at ~line 80, `build_dynasty_outlook` at ~line 604)
- Modify: `src/sleeper_dynasty/engine/outlook_build.py` (`outlook_to_dict`, ~line 139)
- Test: `tests/test_dynasty.py`

**Interfaces:**
- Consumes: Task 1's `WindowBreakdown`, `strength_inputs`, `trajectory_inputs`.
- Produces: `DynastyOutlook.window_breakdown: WindowBreakdown | None` (default `None`); `outlook_to_dict(...)["window_breakdown"]` — a dict `{strength_score, trajectory_score, capital_status, strength_inputs: [{key, raw, score, weight, contribution}], trajectory_inputs: [...]}` or `None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_dynasty.py` (add `from sleeper_dynasty.engine.outlook_build import outlook_to_dict` at the top; the file already defines `_make_player` and imports `Roster`):

```python
def _outlook_with_breakdown():
    players = [
        _make_player("rb1", "Young RB", "RB", 2002),
        _make_player("wr1", "Old WR", "WR", 1994),
    ]
    roster = Roster(
        roster_id=1, owner_id="u1", owner_name="Test",
        players=["rb1", "wr1"], wins=3, losses=3, ties=0,
        points_for=1200.0, points_against=1100.0,
    )
    return build_dynasty_outlook(
        roster=roster, roster_players=players, traded_picks=[],
        projected_rank_pct=0.2, position_rankings={}, total_rosters=10,
        ktc_value_by_player={"rb1": 6000.0, "wr1": 2000.0},
        draft_skill=1.0, playoff_rate=0.8, yoy_rating_delta=100.0,
        draft_capital_pct_rank=0.3,
    )


def test_build_dynasty_outlook_attaches_breakdown():
    outlook = _outlook_with_breakdown()
    wb = outlook.window_breakdown
    assert wb is not None
    assert wb.strength_score == outlook.strength_score
    assert wb.trajectory_score == outlook.trajectory_score
    assert len(wb.strength_inputs) == 2
    assert len(wb.trajectory_inputs) == 4
    assert wb.capital_status == outlook.draft_capital.status
    assert sum(i.contribution for i in wb.strength_inputs) == pytest.approx(
        wb.strength_score, abs=0.06)  # axis score is rounded to 1 decimal


def test_outlook_to_dict_serializes_breakdown():
    d = outlook_to_dict(_outlook_with_breakdown())
    wb = d["window_breakdown"]
    assert wb is not None
    assert set(wb) == {"strength_score", "trajectory_score", "capital_status",
                       "strength_inputs", "trajectory_inputs"}
    row = wb["strength_inputs"][0]
    assert set(row) == {"key", "raw", "score", "weight", "contribution"}
    assert row["key"] == "roster_value_rank"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_dynasty.py -v -k "attaches_breakdown or serializes_breakdown"`
Expected: FAIL — `DynastyOutlook` has no attribute `window_breakdown` / KeyError `window_breakdown`.

- [ ] **Step 3: Implement**

In `dynasty.py`, add the field to `DynastyOutlook` (after `trajectory_score`):

```python
    window_breakdown: "WindowBreakdown | None" = None
```

(`WindowBreakdown` is defined later in the file, hence the string annotation. If the dataclass ordering fights you, move the `WindowInput`/`WindowBreakdown` definitions above `DynastyOutlook` and drop the quotes.)

In `build_dynasty_outlook`, replace the two score computations with the row builders and build the breakdown (the `strength = compute_strength_score(...)` / `trajectory = compute_trajectory_score(...)` block at ~line 604):

```python
    s_rows = strength_inputs(
        roster_rank_pct=projected_rank_pct, playoff_rate=playoff_rate)
    t_rows = trajectory_inputs(
        youth_quality_pct=youth_quality_pct, draft_skill_z=draft_skill,
        draft_capital_pct_rank=draft_capital_pct_rank,
        yoy_rating_delta=yoy_rating_delta)
    strength = sum(i.contribution for i in s_rows)
    trajectory = sum(i.contribution for i in t_rows)
```

and in the `DynastyOutlook(...)` constructor call add:

```python
        window_breakdown=WindowBreakdown(
            strength_score=round(strength, 1),
            trajectory_score=round(trajectory, 1),
            strength_inputs=s_rows,
            trajectory_inputs=t_rows,
            capital_status=draft_capital.status,
        ),
```

In `outlook_build.py::outlook_to_dict`, add a serializer helper above `outlook_to_dict` and a key to the returned dict (after `"trajectory_score"`):

```python
def _window_input_dict(i) -> dict:
    return {
        "key": i.key,
        "raw": round(i.raw, 4),
        "score": round(i.score, 1),
        "weight": i.weight,
        "contribution": round(i.contribution, 1),
    }
```

```python
        "window_breakdown": (
            {
                "strength_score": wb.strength_score,
                "trajectory_score": wb.trajectory_score,
                "capital_status": wb.capital_status,
                "strength_inputs": [
                    _window_input_dict(i) for i in wb.strength_inputs],
                "trajectory_inputs": [
                    _window_input_dict(i) for i in wb.trajectory_inputs],
            }
            if (wb := outlook.window_breakdown) is not None else None
        ),
```

- [ ] **Step 4: Run the full engine suite**

Run: `pytest -v`
Expected: ALL PASS (CLI suite included — `outlook_to_dict` gains a key, loses nothing).

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/dynasty.py src/sleeper_dynasty/engine/outlook_build.py tests/test_dynasty.py
git commit -m "feat(engine): persist window breakdown on the dynasty outlook"
```

---

### Task 3: API — expose the breakdown on `OutlookView`

**Files:**
- Modify: `api/app/models/owner.py` (~line 65, above `OutlookView`)
- Modify: `api/app/services/owner_view.py` (~lines 144–163, the outlook block)
- Test: `api/tests/test_owner_view_outlook.py`

**Interfaces:**
- Consumes: the cached outlook dict shape from Task 2 (`raw_ol["window_breakdown"]`, `raw_ol["strength_score"]`, `raw_ol["trajectory_score"]`).
- Produces: `WindowInputView(key, raw, score, weight, contribution)`, `WindowBreakdownView(strength_score, trajectory_score, capital_status, strength_inputs, trajectory_inputs)`; `OutlookView` gains `strength_score: float | None = None`, `trajectory_score: float | None = None`, `window_breakdown: WindowBreakdownView | None = None`.

- [ ] **Step 1: Write the failing tests**

In `api/tests/test_owner_view_outlook.py`, add a module-level fixture dict and two tests (the file already defines `_entry` and a full `dynasty_outlooks` fixture in `test_outlook_exposed_when_present` — copy that outlook dict as the base):

```python
WINDOW_BREAKDOWN = {
    "strength_score": 28.0, "trajectory_score": 41.1,
    "capital_status": "pick-poor",
    "strength_inputs": [
        {"key": "roster_value_rank", "raw": 0.8, "score": 20.0,
         "weight": 0.6, "contribution": 12.0},
        {"key": "playoff_rate", "raw": 0.4, "score": 40.0,
         "weight": 0.4, "contribution": 16.0},
    ],
    "trajectory_inputs": [
        {"key": "draft_skill", "raw": 0.5, "score": 62.5,
         "weight": 0.4, "contribution": 25.0},
        {"key": "draft_capital", "raw": 0.9, "score": 10.0,
         "weight": 0.3, "contribution": 3.0},
        {"key": "youth", "raw": 0.2, "score": 50.0,
         "weight": 0.15, "contribution": 7.5},
        {"key": "yoy_momentum", "raw": -50.0, "score": 37.5,
         "weight": 0.15, "contribution": 5.6},
    ],
}


def test_window_breakdown_exposed_when_present():
    outlook = {
        "window": "Descending", "trajectory": "aging + pick-poor",
        "strength_score": 28.0, "trajectory_score": 41.1,
        "window_breakdown": WINDOW_BREAKDOWN,
        "age_profile": {"avg_age_by_position": {}, "overall_avg_age": 27.0,
                        "aging_risks": [], "core_young": []},
        "draft_capital": {"picks_by_season": {}, "picks_by_season_round": {},
                          "net_vs_average": -2.0, "status": "pick-poor"},
        "draft_needs": [],
    }
    resp = build_owner_detail(_entry(dynasty_outlooks={"uA": outlook}), "uA")
    ov = resp.outlook
    assert ov.strength_score == 28.0
    assert ov.trajectory_score == 41.1
    assert ov.window_breakdown.capital_status == "pick-poor"
    assert [i.key for i in ov.window_breakdown.strength_inputs] == [
        "roster_value_rank", "playoff_rate"]
    assert len(ov.window_breakdown.trajectory_inputs) == 4
    assert ov.window_breakdown.trajectory_inputs[0].contribution == 25.0


def test_window_breakdown_absent_degrades_gracefully():
    # Pre-upgrade cached outlook dict: no breakdown keys at all.
    outlook = {
        "window": "Ascending", "trajectory": "young + pick-rich",
        "age_profile": {"avg_age_by_position": {}, "overall_avg_age": 24.0,
                        "aging_risks": [], "core_young": []},
        "draft_capital": {"picks_by_season": {}, "picks_by_season_round": {},
                          "net_vs_average": 3.0, "status": "pick-rich"},
        "draft_needs": [],
    }
    resp = build_owner_detail(_entry(dynasty_outlooks={"uA": outlook}), "uA")
    assert resp.outlook.window == "Ascending"
    assert resp.outlook.strength_score is None
    assert resp.outlook.trajectory_score is None
    assert resp.outlook.window_breakdown is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd api && pytest tests/test_owner_view_outlook.py -v`
Expected: the two new tests FAIL (`OutlookView` has no field `strength_score` → pydantic ignores unknown kwargs, so the first test fails on the attribute assert; the second may fail on `strength_score` attribute error). Pre-existing tests still PASS.

- [ ] **Step 3: Implement**

In `api/app/models/owner.py`, above `OutlookView`:

```python
class WindowInputView(BaseModel):
    key: str
    raw: float
    score: float
    weight: float
    contribution: float


class WindowBreakdownView(BaseModel):
    strength_score: float
    trajectory_score: float
    capital_status: str
    strength_inputs: list[WindowInputView]
    trajectory_inputs: list[WindowInputView]
```

and extend `OutlookView`:

```python
class OutlookView(BaseModel):
    window: str
    trajectory: str
    strength_score: float | None = None
    trajectory_score: float | None = None
    window_breakdown: WindowBreakdownView | None = None
    age_profile: AgeProfileView
    draft_capital: DraftCapitalView
    draft_needs: list[DraftNeedView] = []
```

In `api/app/services/owner_view.py`, inside the `if raw_ol:` block, add before building `OutlookView` and pass the three new kwargs (import `WindowBreakdownView` alongside the existing `OutlookView` import):

```python
        wb = raw_ol.get("window_breakdown")
        outlook_view = OutlookView(
            window=raw_ol["window"], trajectory=raw_ol["trajectory"],
            strength_score=raw_ol.get("strength_score"),
            trajectory_score=raw_ol.get("trajectory_score"),
            window_breakdown=WindowBreakdownView(**wb) if wb else None,
            ...existing age_profile/draft_capital/draft_needs kwargs unchanged...
        )
```

- [ ] **Step 4: Run the API suite**

Run: `cd api && pytest -v`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add api/app/models/owner.py api/app/services/owner_view.py api/tests/test_owner_view_outlook.py
git commit -m "feat(api): expose window breakdown on the owner outlook view"
```

---

### Task 4: Frontend — types, window lib, and the `WindowSection` component

**Files:**
- Modify: `web/lib/types.ts` (~line 212, `OutlookView`)
- Create: `web/lib/window.ts`
- Create: `web/components/ownerdeepdive/WindowSection.tsx`
- Test: `web/tests/ownerdeepdive/WindowSection.test.tsx`

**Interfaces:**
- Consumes: Task 3's response shape.
- Produces: TS types `WindowInput`, `WindowBreakdown`; `OutlookView` gains `strength_score?`, `trajectory_score?`, `window_breakdown?`; `web/lib/window.ts` exports `windowPillStyle(window: string): React.CSSProperties`, `WINDOW_INPUT_LABELS: Record<string, string>`, `formatWindowRaw(key: string, raw: number): string`; `WindowSection({ window, breakdown }: { window: string; breakdown?: WindowBreakdown | null })` renders `null` without a breakdown. Test ids: `window-section`, `window-dot`, `window-input-row`.

- [ ] **Step 1: Add the types**

In `web/lib/types.ts`, above `OutlookView`:

```ts
export interface WindowInput {
  key: string;
  raw: number;
  score: number;   // normalized 0-100
  weight: number;  // axis weights sum to 1
  contribution: number;
}

export interface WindowBreakdown {
  strength_score: number;
  trajectory_score: number;
  capital_status: string;
  strength_inputs: WindowInput[];
  trajectory_inputs: WindowInput[];
}
```

and extend `OutlookView`:

```ts
export interface OutlookView {
  window: string;
  trajectory: string;
  strength_score?: number | null;
  trajectory_score?: number | null;
  window_breakdown?: WindowBreakdown | null;
  age_profile: AgeProfileView;
  draft_capital: DraftCapitalView;
  draft_needs: DraftNeedView[];
}
```

- [ ] **Step 2: Write the failing tests**

Create `web/tests/ownerdeepdive/WindowSection.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { WindowSection } from "../../components/ownerdeepdive/WindowSection";
import { WindowBreakdown } from "../../lib/types";

const BREAKDOWN: WindowBreakdown = {
  strength_score: 28, trajectory_score: 41.1, capital_status: "pick-poor",
  strength_inputs: [
    { key: "roster_value_rank", raw: 0.8, score: 20, weight: 0.6, contribution: 12 },
    { key: "playoff_rate", raw: 0.4, score: 40, weight: 0.4, contribution: 16 },
  ],
  trajectory_inputs: [
    { key: "draft_skill", raw: 0.5, score: 62.5, weight: 0.4, contribution: 25 },
    { key: "draft_capital", raw: 0.9, score: 10, weight: 0.3, contribution: 3 },
    { key: "youth", raw: 0.2, score: 50, weight: 0.15, contribution: 7.5 },
    { key: "yoy_momentum", raw: -50, score: 37.5, weight: 0.15, contribution: 5.6 },
  ],
};

describe("WindowSection", () => {
  it("renders six input rows with labels, raws, and weights", () => {
    render(<WindowSection window="Descending" breakdown={BREAKDOWN} />);
    expect(screen.getAllByTestId("window-input-row")).toHaveLength(6);
    expect(screen.getByText("Roster value")).toBeInTheDocument();
    expect(screen.getByText("Draft capital")).toBeInTheDocument();
    expect(screen.getByText("bottom 20%")).toBeInTheDocument();   // roster raw 0.8
    expect(screen.getByText(/40% of seasons/)).toBeInTheDocument(); // playoff raw
  });

  it("plots the team dot at (trajectory, 100 - strength)", () => {
    render(<WindowSection window="Descending" breakdown={BREAKDOWN} />);
    const dot = screen.getByTestId("window-dot");
    expect(dot.style.left).toBe("41.1%");
    expect(dot.style.top).toBe("72%");
  });

  it("labels the weak cell by capital status", () => {
    render(
      <WindowSection window="Rebuilding"
        breakdown={{ ...BREAKDOWN, capital_status: "pick-rich" }} />,
    );
    // Region label + header chip both say Rebuilding.
    expect(screen.getAllByText("Rebuilding").length).toBeGreaterThanOrEqual(2);
  });

  it("renders nothing without a breakdown", () => {
    const { container } = render(
      <WindowSection window="Ascending" breakdown={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd web && npx vitest run tests/ownerdeepdive/WindowSection.test.tsx`
Expected: FAIL — module `components/ownerdeepdive/WindowSection` not found.

- [ ] **Step 4: Create `web/lib/window.ts`**

```ts
import type React from "react";

/** Stage chip fills — the one palette for window identity everywhere. */
export function windowPillStyle(window: string): React.CSSProperties {
  if (window === "Competing now" || window === "Peaking") return { background: "rgba(74,222,128,0.12)", color: "var(--pos)" };
  if (window === "Ascending") return { background: "rgba(129,140,248,0.12)", color: "var(--window)" };
  if (window === "Descending") return { background: "rgba(251,191,36,0.12)", color: "var(--warn)" };
  return { background: "rgba(248,113,113,0.10)", color: "var(--neg)" }; // Rebuilding
}

export const WINDOW_INPUT_LABELS: Record<string, string> = {
  roster_value_rank: "Roster value",
  playoff_rate: "Playoff rate",
  draft_skill: "Draft skill",
  draft_capital: "Draft capital",
  youth: "Youth",
  yoy_momentum: "Momentum",
};

/** League-percentile raws (0 = best) read as top/bottom shares. */
function pctl(raw: number): string {
  return raw <= 0.5
    ? `top ${Math.max(1, Math.round(raw * 100))}%`
    : `bottom ${Math.max(1, Math.round((1 - raw) * 100))}%`;
}

export function formatWindowRaw(key: string, raw: number): string {
  switch (key) {
    case "roster_value_rank": return pctl(raw);
    case "playoff_rate": return `${Math.round(raw * 100)}% of seasons`;
    case "draft_skill": return `z ${raw >= 0 ? "+" : ""}${raw.toFixed(1)}`;
    case "draft_capital": return pctl(raw);
    case "youth": return `${Math.round(raw * 100)}% of value ≤25`;
    case "yoy_momentum": return `${raw >= 0 ? "+" : ""}${Math.round(raw)} pts YoY`;
    default: return String(raw);
  }
}
```

- [ ] **Step 5: Create `web/components/ownerdeepdive/WindowSection.tsx`**

```tsx
"use client";

import { WindowBreakdown, WindowInput } from "@/lib/types";
import { windowPillStyle, WINDOW_INPUT_LABELS, formatWindowRaw } from "@/lib/window";
import { Card, CardHead } from "./ui";

// Stage regions in plot coordinates (x = Trajectory 0-100 left→right,
// y = plot-space top offset, i.e. 100 - Strength). Mirrors classify_window
// exactly: strength ≥60 band split at trajectory 50; middle 40-60 band split
// at 40; weak <40 band with the ≥68 Ascending cut and the capital tiebreak.
type Region = { x: number; y: number; w: number; h: number; label: string; fill: string };

const FILLS = {
  comp: "rgba(74,222,128,0.14)",
  peak: "rgba(74,222,128,0.07)",
  asc: "rgba(129,140,248,0.10)",
  desc: "rgba(251,191,36,0.10)",
  reb: "rgba(248,113,113,0.08)",
};

function regions(capitalStatus: string): Region[] {
  const pickRich = capitalStatus === "pick-rich";
  return [
    { x: 50, y: 0, w: 50, h: 40, label: "Competing now", fill: FILLS.comp },
    { x: 0, y: 0, w: 50, h: 40, label: "Peaking", fill: FILLS.peak },
    { x: 40, y: 40, w: 60, h: 20, label: "Ascending", fill: FILLS.asc },
    { x: 0, y: 40, w: 40, h: 20, label: "Descending", fill: FILLS.desc },
    { x: 68, y: 60, w: 32, h: 40, label: "Ascending", fill: FILLS.asc },
    { x: 0, y: 60, w: 68, h: 40,
      label: pickRich ? "Rebuilding" : "Descending",
      fill: pickRich ? FILLS.reb : FILLS.desc },
  ];
}

/** Deterministic one-liner: name the axis scores and the trajectory extremes. */
function summarize(b: WindowBreakdown, window: string): string {
  const byScore = [...b.trajectory_inputs].sort((a, z) => z.score - a.score);
  const led = WINDOW_INPUT_LABELS[byScore[0].key].toLowerCase();
  const drag = WINDOW_INPUT_LABELS[byScore[byScore.length - 1].key].toLowerCase();
  return `Strength ${Math.round(b.strength_score)} · Trajectory ${Math.round(b.trajectory_score)} — led by ${led}, dragged by ${drag} → ${window}.`;
}

function InputRow({ i }: { i: WindowInput }) {
  return (
    <div data-testid="window-input-row" className="grid grid-cols-[110px_1fr_auto] items-center gap-2 py-1">
      <div className="text-[12px] leading-tight">
        {WINDOW_INPUT_LABELS[i.key] ?? i.key}
        <span className="block text-[10px] text-dim">{formatWindowRaw(i.key, i.raw)}</span>
      </div>
      <div className="h-2 rounded bg-bg overflow-hidden">
        <div className="h-full rounded" style={{ width: `${Math.max(2, Math.min(100, i.score))}%`, background: "var(--accent)" }} />
      </div>
      <div className="font-mono text-[10px] text-dim tabular whitespace-nowrap">
        {i.contribution.toFixed(1)} pts · w {Math.round(i.weight * 100)}%
      </div>
    </div>
  );
}

export function WindowSection({ window, breakdown }: {
  window: string;
  breakdown?: WindowBreakdown | null;
}) {
  if (!breakdown) return null;
  return (
    <Card data-testid="window-section">
      <CardHead title="Why this window" />
      <div className="flex items-center gap-2 mb-2">
        <span className="px-1.5 py-0.5 rounded text-[11px] font-semibold whitespace-nowrap" style={windowPillStyle(window)}>
          {window}
        </span>
        <span className="text-[12px] text-dim">{summarize(breakdown, window)}</span>
      </div>

      {/* Quadrant: x = Trajectory, y = Strength (top = 100). Every region is
          text-labeled — stage identity is never color-alone. */}
      <div className="relative h-44 rounded border border-[var(--divider)] overflow-hidden mb-3" role="img"
        aria-label={`Strength ${breakdown.strength_score}, Trajectory ${breakdown.trajectory_score}: ${window}`}>
        {regions(breakdown.capital_status).map((r, idx) => (
          <div key={idx} className="absolute flex items-start justify-start p-1"
            style={{ left: `${r.x}%`, top: `${r.y}%`, width: `${r.w}%`, height: `${r.h}%`, background: r.fill }}>
            <span className="text-[9px] uppercase tracking-wide text-dim">{r.label}</span>
          </div>
        ))}
        <div data-testid="window-dot"
          className="absolute w-2.5 h-2.5 rounded-full -translate-x-1/2 -translate-y-1/2"
          style={{ left: `${breakdown.trajectory_score}%`, top: `${100 - breakdown.strength_score}%`, background: "var(--accent)", boxShadow: "0 0 0 2px var(--surface)" }}
        />
        <span className="absolute bottom-0.5 right-1 text-[9px] text-dim">Trajectory →</span>
        <span className="absolute top-0.5 left-1 text-[9px] text-dim">Strength ↑</span>
      </div>

      <div className="grid gap-x-6 gap-y-1 sm:grid-cols-2">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-wide text-dim mb-1">
            Strength {breakdown.strength_score.toFixed(0)}
          </div>
          {breakdown.strength_inputs.map((i) => <InputRow key={i.key} i={i} />)}
        </div>
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-wide text-dim mb-1">
            Trajectory {breakdown.trajectory_score.toFixed(0)}
          </div>
          {breakdown.trajectory_inputs.map((i) => <InputRow key={i.key} i={i} />)}
        </div>
      </div>
    </Card>
  );
}
```

Note: `Card` may not forward `data-testid` — check `web/components/ownerdeepdive/ui.tsx`; if it only takes `children`/`className`, wrap the `Card` in `<div data-testid="window-section">` instead. Match `CardHead`'s actual props (check its signature in `ui.tsx`; if it wants children or a different prop name, adapt the call — the visible text must be "Why this window").

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd web && npx vitest run tests/ownerdeepdive/WindowSection.test.tsx`
Expected: PASS (4 tests).

- [ ] **Step 7: Commit**

```bash
git add web/lib/types.ts web/lib/window.ts web/components/ownerdeepdive/WindowSection.tsx web/tests/ownerdeepdive/WindowSection.test.tsx
git commit -m "feat(web): WindowSection receipt — quadrant map + weighted input bars"
```

---

### Task 5: Frontend — lead the Outlook tab with the receipt

**Files:**
- Modify: `web/components/OwnerDeepDive.tsx` (~line 199, the outlook tab block)
- Test: `web/tests/OwnerDeepDive.test.tsx`

**Interfaces:**
- Consumes: Task 4's `WindowSection` and `WindowBreakdown` type.
- Produces: the Outlook tab renders `WindowSection` as its first block when `detail.outlook.window_breakdown` is present.

- [ ] **Step 1: Write the failing test**

In `web/tests/OwnerDeepDive.test.tsx`, after the `DETAIL_WITH_OUTLOOK` constant, add:

```tsx
const DETAIL_WITH_WINDOW_BREAKDOWN: OwnerDetailResp = {
  ...DETAIL_WITH_OUTLOOK,
  outlook: {
    ...DETAIL_WITH_OUTLOOK.outlook!,
    strength_score: 28,
    trajectory_score: 41.1,
    window_breakdown: {
      strength_score: 28, trajectory_score: 41.1, capital_status: "pick-rich",
      strength_inputs: [
        { key: "roster_value_rank", raw: 0.8, score: 20, weight: 0.6, contribution: 12 },
        { key: "playoff_rate", raw: 0.4, score: 40, weight: 0.4, contribution: 16 },
      ],
      trajectory_inputs: [
        { key: "draft_skill", raw: 0.5, score: 62.5, weight: 0.4, contribution: 25 },
        { key: "draft_capital", raw: 0.9, score: 10, weight: 0.3, contribution: 3 },
        { key: "youth", raw: 0.2, score: 50, weight: 0.15, contribution: 7.5 },
        { key: "yoy_momentum", raw: -50, score: 37.5, weight: 0.15, contribution: 5.6 },
      ],
    },
  },
};
```

and a test (follow the file's existing async userEvent pattern):

```tsx
  it("leads the Outlook tab with the Window receipt when a breakdown exists", async () => {
    const user = userEvent.setup();
    render(<OwnerDeepDive leagueId="L" detail={DETAIL_WITH_WINDOW_BREAKDOWN} />);
    await user.click(screen.getByRole("tab", { name: /outlook/i }));
    expect(screen.getByTestId("window-section")).toBeInTheDocument();
    expect(screen.getAllByTestId("window-input-row")).toHaveLength(6);
  });

  it("omits the Window receipt on pre-upgrade caches", async () => {
    const user = userEvent.setup();
    render(<OwnerDeepDive leagueId="L" detail={DETAIL_WITH_OUTLOOK} />);
    await user.click(screen.getByRole("tab", { name: /outlook/i }));
    expect(screen.queryByTestId("window-section")).not.toBeInTheDocument();
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && npx vitest run tests/OwnerDeepDive.test.tsx`
Expected: the first new test FAILs (no `window-section`); the second may already pass — that's fine.

- [ ] **Step 3: Implement**

In `web/components/OwnerDeepDive.tsx`: add `import { WindowSection } from "./ownerdeepdive/WindowSection";` and make the outlook tab block start with it:

```tsx
        {activeTab === "outlook" && detail.outlook && (
          <div className="space-y-3">
            <WindowSection
              window={detail.outlook.window}
              breakdown={detail.outlook.window_breakdown}
            />
            <Card>
              ...existing StatStrip card unchanged...
```

(`WindowSection` returns `null` without a breakdown, so no conditional is needed here.)

- [ ] **Step 4: Run the web unit suite**

Run: `cd web && npx vitest run`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add web/components/OwnerDeepDive.tsx web/tests/OwnerDeepDive.test.tsx
git commit -m "feat(web): owner Outlook tab leads with the Window receipt"
```

---

### Task 6: Frontend — Window chip navigates to the receipt; tooltip tells the truth

**Files:**
- Modify: `web/components/StandingsTable.tsx` (tooltip at ~line 52, `windowPillStyle` at ~line 114, chip at ~lines 344–355)
- Test: `web/tests/StandingsTable.test.tsx`

**Interfaces:**
- Consumes: Task 4's `windowPillStyle` from `web/lib/window.ts`; the owner page's existing `?tab=` deep-link (`OwnerDeepDive.initialTab`).
- Produces: clicking a Window chip pushes `/league/{leagueId}/owner/{user_id}?tab=outlook`.

- [ ] **Step 1: Write the failing test**

In `web/tests/StandingsTable.test.tsx` (the `push` mock and `GM_ROWS` fixture already exist), add:

```tsx
  it("navigates to the owner Outlook tab when a Window chip is clicked", async () => {
    const user = userEvent.setup();
    render(<StandingsTable leagueId="123" rows={GM_ROWS} year="all" currentSeason={2026} />);
    // Table renders mobile + desktop sections; first chip is enough.
    await user.click(screen.getAllByRole("button", { name: "Competing now" })[0]);
    expect(push).toHaveBeenCalledWith("/league/123/owner/u1?tab=outlook");
  });
```

- [ ] **Step 2: Run tests to verify it fails**

Run: `cd web && npx vitest run tests/StandingsTable.test.tsx`
Expected: new test FAILs — no button named "Competing now" (chip is a span today).

- [ ] **Step 3: Implement**

In `web/components/StandingsTable.tsx`:

1. Delete the local `windowPillStyle` function and add `import { windowPillStyle } from "../lib/window";` (match the file's existing import style for `../lib/...` vs `@/lib/...`).
2. Replace the chip span (~line 345) with a click-target inside the row link — `router` already exists in the component:

```tsx
                  {r.window ? (
                    <button
                      type="button"
                      title="See why — full window breakdown"
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        router.push(`/league/${leagueId}/owner/${r.user_id}?tab=outlook`);
                      }}
                      className="px-1.5 py-0.5 rounded text-[10px] font-semibold font-sans whitespace-nowrap cursor-pointer hover:underline"
                      style={windowPillStyle(r.window)}
                    >
                      {r.window}
                    </button>
                  ) : (
                    <span className="font-mono text-[12px] text-dim">—</span>
                  )}
```

If the mobile card section also renders a window chip (search the file for other `windowPillStyle` call sites), apply the same button treatment there.

3. Fix the header tooltip (~line 52):

```ts
    tooltip: { title: "Roster Window", body: "Dynasty stage from Strength (60% roster value rank + 40% all-time playoff rate) × Trajectory (40% draft skill + 30% draft capital + 15% youth + 15% year-over-year momentum). Click a chip for the full breakdown. Reflects today, not the year filter." },
```

- [ ] **Step 4: Run the web unit suite**

Run: `cd web && npx vitest run`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add web/components/StandingsTable.tsx web/tests/StandingsTable.test.tsx
git commit -m "feat(web): Window chip links to its receipt; honest formula tooltip"
```

---

### Task 7: Full verification

**Files:** none (verification only).

- [ ] **Step 1: Run every suite**

Run from repo root:

```bash
pytest -v
cd api && pytest -v && cd ..
cd web && npx vitest run && cd ..
```

Expected: ALL PASS in all three suites.

- [ ] **Step 2: Type-check the web app**

Run: `cd web && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Visual sanity check**

Start `make dev-api` and `make dev-web`, open a cached league's standings, click a Window chip → lands on the owner page's Outlook tab with the receipt leading; regions labeled, dot plotted, six bars with raw values and weights; a pre-refresh league (no breakdown yet) shows the old label-only Outlook without errors. Eyeball the quadrant for label collisions at narrow widths.

- [ ] **Step 4: Final commit if any fixes were needed**

```bash
git add -A && git commit -m "fix: window receipt polish from verification pass"
```

(Skip if the tree is clean.)
