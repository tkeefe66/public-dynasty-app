# Dashboard Lead — Verdict Headline + Figure Strip Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the league dashboard's lead name the trade's winner and stop repeating its own figures, replacing the bordered right rail with a three-cell ruled figure strip.

**Architecture:** Three additive fields on the existing `LatestTrade` response model, derived at response time from the grade blob `_latest_trades` already reads (no cache change, no `SCHEMA_VERSION` bump). A new pure frontend module turns a `LatestTrade` into a headline string and a points reading; `HeadlineMoves` renders those into a fixed three-cell strip shared by all four league-phase sources.

**Tech Stack:** FastAPI + Pydantic (`api/`), Next.js 14 App Router + Tailwind against CSS custom-property tokens (`web/`), pytest, vitest + @testing-library/react.

**Spec:** `docs/superpowers/specs/2026-08-11-dashboard-lead-design.md`

## Global Constraints

Every task's requirements implicitly include these.

- **`POINTS` never takes a sign color.** Received-only totals are never negative; `text-pos`/`text-neg` are forbidden on that cell. Emphasis is `font-semibold` for the lens winner and `text-dim` for the other side.
- **`VALUE` is the one colored figure** — `text-pos` when positive, `text-neg` when negative, `text-dim` at zero. Sign always rendered; never invent a sign for zero.
- **The strip is always exactly three cells**, at every viewport, for every phase source. One render — no desktop/mobile duplication.
- **The left-hand number in every cell belongs to the value winner**, so one subject runs across the row.
- **Both sides at 0.0 production → a `--dim` em dash**, never `0.0 vs 0.0`.
- **Strip max width: 620px.**
- **Never render the string "KTC"** anywhere in `web/{app,components,lib}` — it is "Trade Value" / "Value". Data keys (`swing_ktc`, `net_ktc`) are fine.
- **No new design token, no new stamp slot, no new entry in `agate-rules.test.ts`'s `ALLOWED` map.**
- Backend changes are **additive only** — `swing_ktc`, `swing_prod`, and `assets_short` keep their current meaning and consumers (`TradeCard`, `TradesTab`, `lib/receipts.ts`).
- Figures are Geist Mono + `tabular` (`font-mono ... tabular`); labels are 8px mono uppercase `tracking-[0.1em] text-dim`.

## Ground Truth (verified against the live cache)

Checked against `~/.sleeper-dynasty/cache/chain_9000000000000000001.json`, 47 trades:

- Every trade has **exactly two sides**. The 3+ side branch is defensive, not hypothetical-common.
- `snapshot_value_swing` is zero-sum per uid (e.g. `{u_a: +593.0, u_b: -593.0}`).
- `production_total` is **received-only** per uid — both sides are ≥ 0. (Note: the existing fixture in `api/tests/test_aggregations.py` uses a zero-sum `{u_alice: 387.4, u_bob: -387.4}` shape, which does **not** match production data. New tests must use realistic non-negative values.)
- **17 of 47 trades (36%)** have a value winner different from the production winner — the split headline is the common case.
- **16 of 47 (34%)** have both sides at 0.0 production — the em-dash path carries a third of the league.

## File Structure

| File | Responsibility |
|---|---|
| `api/app/models/league.py` | `LatestTrade` gains `value_winner`, `production_winner`, `production_split` |
| `api/app/services/aggregations.py` | `_latest_trades` derives the three fields from the grade blob |
| `api/tests/test_latest_trade_winners.py` | **new** — derivation across agree / disagree / 3-way / missing-blob |
| `web/lib/types.ts` | mirror the three fields on the `LatestTrade` interface |
| `web/lib/trade-lead.ts` | **new** — pure `tradeHeadline()` + `pointsReading()`; no JSX, no React |
| `web/tests/trade-lead.test.ts` | **new** — every headline form and points reading |
| `web/components/HeadlineMoves.tsx` | `FigureTable` → `FigureStrip`; rail deleted; four sources emit three cells |
| `web/tests/HeadlineMoves.test.tsx` | strip rendering, colors, phase sources |
| `web/components/DashboardSkeleton.tsx` | drop the rail; same tracks as the live lead |
| `design_handoff_agate/DESIGN.md` | amend the lead's skeleton (the rail is gone) |
| `.claude/skills/agate-styling/SKILL.md` | add the strip to the reuse table |

---

### Task 1: Backend — the two winners and the production split

**Files:**
- Modify: `api/app/models/league.py:72-79`
- Modify: `api/app/services/aggregations.py:428-458` (`_latest_trades`)
- Test: `api/tests/test_latest_trade_winners.py` (create)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `LatestTrade.value_winner: OwnerRef | None`, `LatestTrade.production_winner: OwnerRef | None`, `LatestTrade.production_split: tuple[float, float] | None`. Task 2 mirrors these names verbatim in TypeScript.

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_latest_trade_winners.py`:

```python
from __future__ import annotations

from app.services.aggregations import _latest_trades
from tests.helpers import minimal_chain_cache_entry


def _entry(grade: dict | None) -> object:
    """A two-side trade between Alice and Bob, with `grade` as its grade blob."""
    return minimal_chain_cache_entry(
        owners={
            "u_alice": {"owner_name": "Alice"},
            "u_bob": {"owner_name": "Bob"},
        },
        grades={"tx1": {"trade_id": "tx1", **grade}} if grade is not None else {},
    )


def _trade(sides: dict | None = None) -> dict:
    return {
        "trade": {
            "transaction_id": "tx1", "league_id": "L", "season": 2026,
            "week": 2, "traded_at": "2025-08-29T00:00:00+00:00", "sides": {},
        },
        "sides": sides if sides is not None else {
            "u_alice": {"user_id": "u_alice", "received": [{"name": "Barkley", "player_id": "p1"}], "given": []},
            "u_bob": {"user_id": "u_bob", "received": [{"name": "Montgomery", "player_id": "p2"}], "given": []},
        },
    }


def test_winners_agree_when_one_side_leads_both_lenses():
    entry = _entry({
        "snapshot_value_swing": {"u_alice": 1450.0, "u_bob": -1450.0},
        "production_total": {"u_alice": 179.8, "u_bob": 58.3},
    })
    (t,) = _latest_trades(entry, [_trade()])
    assert t.value_winner is not None and t.value_winner.owner_name == "Alice"
    assert t.production_winner is not None and t.production_winner.owner_name == "Alice"
    # Ordered by the VALUE winner, so the left number is always the same person.
    assert t.production_split == (179.8, 58.3)


def test_winners_can_disagree_and_the_split_still_leads_with_the_value_winner():
    entry = _entry({
        "snapshot_value_swing": {"u_alice": 1450.0, "u_bob": -1450.0},
        "production_total": {"u_alice": 58.3, "u_bob": 179.8},
    })
    (t,) = _latest_trades(entry, [_trade()])
    assert t.value_winner.owner_name == "Alice"
    assert t.production_winner.owner_name == "Bob"
    assert t.production_split == (58.3, 179.8)


def test_three_way_trade_has_winners_but_no_split():
    sides = {
        f"u_{n}": {"user_id": f"u_{n}", "received": [], "given": []}
        for n in ("alice", "bob", "carol")
    }
    entry = minimal_chain_cache_entry(
        owners={f"u_{n}": {"owner_name": n.title()} for n in ("alice", "bob", "carol")},
        grades={"tx1": {
            "trade_id": "tx1",
            "snapshot_value_swing": {"u_alice": 900.0, "u_bob": -400.0, "u_carol": -500.0},
            "production_total": {"u_alice": 10.0, "u_bob": 20.0, "u_carol": 5.0},
        }},
    )
    (t,) = _latest_trades(entry, [_trade(sides)])
    assert t.value_winner.owner_name == "Alice"
    assert t.production_winner.owner_name == "Bob"
    assert t.production_split is None


def test_missing_grade_blob_leaves_every_new_field_none():
    (t,) = _latest_trades(_entry(None), [_trade()])
    assert t.value_winner is None
    assert t.production_winner is None
    assert t.production_split is None


def test_existing_swing_fields_are_unchanged():
    entry = _entry({
        "snapshot_value_swing": {"u_alice": 1450.0, "u_bob": -1450.0},
        "production_total": {"u_alice": 179.8, "u_bob": 58.3},
    })
    (t,) = _latest_trades(entry, [_trade()])
    assert t.swing_ktc == 1450.0
    assert t.swing_prod == 179.8 - 58.3
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd api && pytest tests/test_latest_trade_winners.py -v`
Expected: FAIL — `AttributeError: 'LatestTrade' object has no attribute 'value_winner'`

- [ ] **Step 3: Add the fields to the model**

In `api/app/models/league.py`, extend `LatestTrade`:

```python
class LatestTrade(BaseModel):
    trade_id: str
    date: str
    week: int
    parties: list[OwnerRef]
    assets_short: str
    swing_ktc: float
    swing_prod: float
    # The dashboard lead names a winner. Both are derived at response time from
    # the grade blob (no cache field, no SCHEMA_VERSION bump). None when the
    # grade blob is missing or carries fewer than two graded sides.
    value_winner: OwnerRef | None = None
    production_winner: OwnerRef | None = None
    # (value winner's received total, the other side's) — ordered by the VALUE
    # winner so the lead's left-hand figure is always the same person. Only for
    # exactly-two-side trades; None otherwise.
    production_split: tuple[float, float] | None = None
```

- [ ] **Step 4: Derive them in `_latest_trades`**

In `api/app/services/aggregations.py`, inside the `for rt in sorted_trades:` loop, after `prod_vals` is computed and before `out.append(...)`:

```python
        # The lead's verdict. argmax over the zero-sum value swing and over the
        # received-only production tally — the two can legitimately disagree
        # (36% of trades in a real league), which is the story worth telling.
        value_winner_uid = max(ktc_swings_by_uid, key=ktc_swings_by_uid.get) if ktc_swings_by_uid else None
        prod_winner_uid = max(prod_swings, key=prod_swings.get) if prod_swings else None
        production_split = None
        if value_winner_uid is not None and len(prod_swings) == 2:
            other_uid = next(u for u in prod_swings if u != value_winner_uid)
            production_split = (
                float(prod_swings[value_winner_uid]),
                float(prod_swings[other_uid]),
            )
```

where `ktc_swings_by_uid` is the swing dict keyed by uid — add it just above, next to the existing `ktc_swing_vals` line:

```python
        ktc_swings_by_uid = g.get("snapshot_value_swing") or {}
        ktc_swing_vals = list(ktc_swings_by_uid.values())
```

Then pass them into the constructor:

```python
            swing_prod=float(max(prod_vals) - min(prod_vals)) if len(prod_vals) >= 2 else 0.0,
            value_winner=owner_ref(entry, value_winner_uid) if value_winner_uid else None,
            production_winner=owner_ref(entry, prod_winner_uid) if prod_winner_uid else None,
            production_split=production_split,
        ))
```

Guard: if `value_winner_uid` is in `prod_swings` but the trade has two sides whose uids differ from the value-swing dict's, `next(...)` raises `StopIteration`. It can't happen — both dicts are keyed off the same graded sides — but if it ever does, that is a real data bug and should surface loudly rather than silently produce a wrong split.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd api && pytest tests/test_latest_trade_winners.py -v`
Expected: PASS, 5 tests

- [ ] **Step 6: Run the full backend suite for regressions**

Run: `cd api && pytest -q`
Expected: PASS. `test_aggregations.py` and `test_trades_list_route.py` both build `LatestTrade`; the new fields default to `None`, so they must not break.

- [ ] **Step 7: Commit**

```bash
git add api/app/models/league.py api/app/services/aggregations.py api/tests/test_latest_trade_winners.py
git commit -m "feat(api): LatestTrade names its value and production winners"
```

---

### Task 2: Frontend — the pure copy and figure module

**Files:**
- Modify: `web/lib/types.ts:72-80`
- Create: `web/lib/trade-lead.ts`
- Test: `web/tests/trade-lead.test.ts` (create)

**Interfaces:**
- Consumes: the `LatestTrade` fields from Task 1.
- Produces:
  - `tradeHeadline(t: LatestTrade): string`
  - `type PointsReading = { kind: "unscored" } | { kind: "split"; left: string; right: string; winner: "left" | "right" }`
  - `pointsReading(t: LatestTrade): PointsReading`

  Task 3 imports all three.

- [ ] **Step 1: Mirror the backend fields in `web/lib/types.ts`**

Extend the existing `LatestTrade` interface (leave `swing_ktc`/`swing_prod` alone — `TradeCard`, `TradesTab`, and `lib/receipts.ts` read them):

```ts
export interface LatestTrade {
  trade_id: string;
  date: string;
  week: number;
  parties: OwnerRef[];
  assets_short: string;
  swing_ktc: number;
  swing_prod: number;
  /** Winner of the zero-sum Trade Value swing. Null on a pre-feature payload
   *  or a trade with fewer than two graded sides. */
  value_winner?: OwnerRef | null;
  /** Winner of the received-only production tally. Can differ from
   *  value_winner — that divergence is the lead's story. */
  production_winner?: OwnerRef | null;
  /** [value winner's received total, the other side's]. Ordered by the VALUE
   *  winner so the lead's left-hand figure is always the same person.
   *  Two-side trades only. */
  production_split?: [number, number] | null;
}
```

- [ ] **Step 2: Write the failing test**

Create `web/tests/trade-lead.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { tradeHeadline, pointsReading } from "../lib/trade-lead";
import { LatestTrade } from "../lib/types";

function trade(over: Partial<LatestTrade> = {}): LatestTrade {
  return {
    trade_id: "tx1", date: "2025-08-29", week: 2,
    parties: [
      { user_id: "u_a", owner_name: "Bobby" },
      { user_id: "u_b", owner_name: "Joey" },
    ],
    assets_short: "David Montgomery ↔ Saquon Barkley",
    swing_ktc: 12483, swing_prod: 121.5,
    value_winner: { user_id: "u_a", owner_name: "Bobby" },
    production_winner: { user_id: "u_a", owner_name: "Bobby" },
    production_split: [179.8, 58.3],
    ...over,
  };
}

describe("tradeHeadline", () => {
  it("names one winner when both lenses agree", () => {
    expect(tradeHeadline(trade())).toBe("Bobby won this one on both counts.");
  });

  it("names the tension when the lenses disagree", () => {
    const t = trade({
      production_winner: { user_id: "u_b", owner_name: "Joey" },
      production_split: [58.3, 179.8],
    });
    expect(tradeHeadline(t)).toBe("Bobby won the value. Joey won the field.");
  });

  it("falls back to both names when a winner is missing", () => {
    const t = trade({ value_winner: null, production_winner: null });
    expect(tradeHeadline(t)).toBe(
      "Bobby & Joey's trade is still the loudest swing on the board.",
    );
  });

  it("falls back when only the production winner is missing", () => {
    const t = trade({ production_winner: null });
    expect(tradeHeadline(t)).toBe(
      "Bobby & Joey's trade is still the loudest swing on the board.",
    );
  });
});

describe("pointsReading", () => {
  it("reads head-to-head with the value winner on the left", () => {
    expect(pointsReading(trade())).toEqual({
      kind: "split", left: "179.8", right: "58.3", winner: "left",
    });
  });

  it("marks the right side as the winner when the lenses disagree", () => {
    const t = trade({
      production_winner: { user_id: "u_b", owner_name: "Joey" },
      production_split: [58.3, 179.8],
    });
    expect(pointsReading(t)).toEqual({
      kind: "split", left: "58.3", right: "179.8", winner: "right",
    });
  });

  it("is unscored when neither side has scored — never 0.0 vs 0.0", () => {
    expect(pointsReading(trade({ production_split: [0, 0] }))).toEqual({ kind: "unscored" });
  });

  it("is unscored for a trade with more than two sides — swing_prod is a spread, not a total", () => {
    expect(pointsReading(trade({ production_split: null }))).toEqual({ kind: "unscored" });
    // Even with a large spread on the payload the cell stays unscored, rather
    // than printing a figure the POINTS label would misdescribe.
    expect(pointsReading(trade({ production_split: null, swing_prod: 250.4 })))
      .toEqual({ kind: "unscored" });
  });
});
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd web && npx vitest --config tests/vitest.config.ts run tests/trade-lead.test.ts`
Expected: FAIL — cannot resolve `../lib/trade-lead`

- [ ] **Step 4: Write the module**

Create `web/lib/trade-lead.ts`:

```ts
import { LatestTrade } from "./types";

/* ---------------------------------------------------------------------------
 * The dashboard lead's verdict, as pure functions so the copy rules are
 * testable without rendering. Both readings are deterministic — no LLM, and
 * no claim the payload can't support.
 * ------------------------------------------------------------------------ */

/** Two forms, selected by whether the two lenses agree, plus a fallback for a
 *  payload that predates the winner fields or a trade with too few graded
 *  sides. The fallback is the pre-verdict headline, kept verbatim. */
export function tradeHeadline(t: LatestTrade): string {
  const value = t.value_winner;
  const production = t.production_winner;
  if (value && production) {
    return value.user_id === production.user_id
      ? `${value.owner_name} won this one on both counts.`
      : `${value.owner_name} won the value. ${production.owner_name} won the field.`;
  }
  const names = t.parties.map((p) => p.owner_name).join(" & ");
  return `${names}'s trade is still the loudest swing on the board.`;
}

export type PointsReading =
  | { kind: "unscored" }
  | { kind: "split"; left: string; right: string; winner: "left" | "right" };

/** The POINTS cell. Received-only totals read head-to-head ("179.8 vs 58.3"),
 *  never as a swing — Trade Value is the only swing metric. A lens both sides
 *  left at zero is unscored, matching the trade page
 *  (trade_view.py::_realized_lens_totals): an offseason trade whose players
 *  haven't taken a snap must not read as a 0.0-vs-0.0 result.
 *
 *  Three or more sides (production_split null) is also unscored. There is no
 *  head-to-head to draw, and the only production figure the payload carries —
 *  swing_prod — is a spread across every side, not any one owner's total;
 *  printing it under a POINTS label would misdescribe it. */
export function pointsReading(t: LatestTrade): PointsReading {
  const split = t.production_split;
  if (!split) return { kind: "unscored" };
  const [left, right] = split;
  if (left === 0 && right === 0) return { kind: "unscored" };
  return {
    kind: "split",
    left: left.toFixed(1),
    right: right.toFixed(1),
    winner: right > left ? "right" : "left",
  };
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd web && npx vitest --config tests/vitest.config.ts run tests/trade-lead.test.ts`
Expected: PASS, 10 tests

- [ ] **Step 6: Commit**

```bash
git add web/lib/types.ts web/lib/trade-lead.ts web/tests/trade-lead.test.ts
git commit -m "feat(web): pure verdict-copy and points-reading module for the lead"
```

---

### Task 3: Frontend — the figure strip replaces the rail

**Files:**
- Modify: `web/components/HeadlineMoves.tsx` (whole file)
- Test: `web/tests/HeadlineMoves.test.tsx`

**Interfaces:**
- Consumes: `tradeHeadline`, `pointsReading`, `PointsReading` from Task 2.
- Produces: nothing later tasks import. `HeadlineMoves` keeps its `{ data, leagueId }` props.

- [ ] **Step 1: Write the failing tests**

Append to `web/tests/HeadlineMoves.test.tsx`. The existing `data()`/`trade()` fixture helpers at the top of that file need the new fields — add them to the `trade()` helper first:

```ts
// in the existing trade() helper, alongside swing_ktc/swing_prod:
    value_winner: { user_id: "u_tom", owner_name: "Tom" },
    production_winner: { user_id: "u_tom", owner_name: "Tom" },
    production_split: [140.0, 19.5] as [number, number],
```

Then the new block:

```tsx
describe("HeadlineMoves — the figure strip", () => {
  it("renders exactly three cells, once — no desktop/mobile duplication", () => {
    render(<HeadlineMoves data={data()} leagueId="L1" />);
    expect(screen.getAllByText("Value")).toHaveLength(1);
    expect(screen.getAllByText("Points")).toHaveLength(1);
    expect(screen.getAllByText("Since")).toHaveLength(1);
  });

  it("names the winner in the headline instead of both parties", () => {
    render(<HeadlineMoves data={data()} leagueId="L1" />);
    expect(screen.getByText("Tom won this one on both counts.")).toBeInTheDocument();
  });

  it("keeps every figure out of the body prose", () => {
    render(<HeadlineMoves data={data()} leagueId="L1" />);
    const body = screen.getByText(/traded/i);
    expect(body.textContent).not.toMatch(/\d,\d{3}/);   // no +1,450
    expect(body.textContent).not.toMatch(/\d+\.\d/);    // no 120.5
  });

  it("colors VALUE by sign and never colors POINTS", () => {
    render(<HeadlineMoves data={data()} leagueId="L1" />);
    const value = screen.getByText("+1,450");
    expect(value.className).toMatch(/text-pos/);
    const points = screen.getByTestId("lead-points");
    expect(points.innerHTML).not.toMatch(/text-pos|text-neg/);
  });

  it("weights the winning production figure and dims the losing one", () => {
    render(<HeadlineMoves data={data()} leagueId="L1" />);
    const points = screen.getByTestId("lead-points");
    expect(within(points).getByText("140.0").className).toMatch(/font-semibold/);
    expect(within(points).getByText("19.5").className).toMatch(/text-dim/);
  });

  it("shows an em dash rather than 0.0 vs 0.0 when neither side has scored", () => {
    const t = { ...trade(), production_split: [0, 0] as [number, number] };
    render(<HeadlineMoves data={data({ headline_trades: [t] })} leagueId="L1" />);
    expect(screen.getByTestId("lead-points").textContent).toBe("—");
  });

  it("keeps the strip on the week-recap source too", () => {
    render(
      <HeadlineMoves
        data={data({
          phase: "regular", phase_week: 5,
          week_recap: {
            season: "2026", week: 4,
            high_score: { user_id: "u_a", owner: owner("Alice"), points: 140 },
            blowout: {
              winner_user_id: "u_a", winner: owner("Alice"),
              loser_user_id: "u_b", loser: owner("Bob"), margin: 50,
            },
            traded_points: { user_id: "u_b", owner: owner("Bob"), points: 21.5 },
          },
        })}
        leagueId="L1"
      />,
    );
    expect(screen.getAllByText("High")).toHaveLength(1);
    expect(screen.getAllByText("Blowout")).toHaveLength(1);
    expect(screen.getAllByText("Traded")).toHaveLength(1);
  });
});
```

Add `within` to the existing `@testing-library/react` import at the top of the file if it isn't already there.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd web && npx vitest --config tests/vitest.config.ts run tests/HeadlineMoves.test.tsx`
Expected: FAIL — `Value` found twice (desktop + mobile copies still render), no `lead-points` testid.

- [ ] **Step 3: Replace `FigureRow`/`FigureTable` with the strip**

In `web/components/HeadlineMoves.tsx`, replace the `FigureRow` type and the `FigureTable` component with:

```tsx
/** One strip cell: a whisper label over a figure. Always three per lead, at
 *  every viewport and in every phase — the lead is one fixed skeleton and only
 *  the source changes, so the page never reflows across the season. */
type FigureCell = { label: string; value: ReactNode; testId?: string };

/* ---------------------------------------------------------------------------
 * The figure strip (docs/superpowers/specs/2026-08-11-dashboard-lead-design.md).
 * Replaces the bordered right rail: depth in this system is rules, not boxes.
 * Capped at 620px — across the full 1180px a figure lands every ~390px and the
 * three read as unrelated facts instead of one reading.
 * ------------------------------------------------------------------------ */
function FigureStrip({ cells }: { cells: FigureCell[] }) {
  return (
    <Ruled className="mt-4 max-w-[620px]">
      <Rule className="grid grid-cols-3 gap-4 px-2 items-center">
        {cells.map((c) => (
          <span
            key={c.label}
            className="min-w-0 truncate font-mono text-[8px] uppercase tracking-[0.1em] text-dim"
          >
            {c.label}
          </span>
        ))}
      </Rule>
      <Rule className="grid grid-cols-3 gap-4 px-2 items-center">
        {cells.map((c) => (
          <span
            key={c.label}
            data-testid={c.testId}
            className="min-w-0 truncate font-mono text-[11px] tabular"
          >
            {c.value}
          </span>
        ))}
      </Rule>
    </Ruled>
  );
}

/** The POINTS cell. No sign color — received-only totals are never negative,
 *  so a sign color would be permanently green and mean nothing (DESIGN.md:
 *  color rides signed numbers only). The lens winner is weighted; the other
 *  side and the "vs" whisper. */
function PointsCell({ reading }: { reading: PointsReading }) {
  if (reading.kind === "unscored") return <span className="text-dim">—</span>;
  const leftWins = reading.winner === "left";
  return (
    <>
      <span className={leftWins ? "font-semibold" : "text-dim"}>{reading.left}</span>
      <span className="text-dim"> vs </span>
      <span className={leftWins ? "text-dim" : "font-semibold"}>{reading.right}</span>
    </>
  );
}
```

Change `LeadContent`'s `figureRows: FigureRow[]` to `cells: FigureCell[]`, and drop `figureTitle` — the strip has no title; the kicker already names the lead.

- [ ] **Step 4: Rewrite the four phase sources to emit cells**

`tradeOfWeekContent` — headline and body come from Task 2's module:

```tsx
  return {
    kicker,
    phaseNote,
    headline: tradeHeadline(trade),
    body: `${trade.assets_short}, traded ${fmtDate(trade.date)}.`,
    href: `/league/${leagueId}/trade/${trade.trade_id}`,
    cells: [
      {
        label: "Value",
        value: <span className={signColor(trade.swing_ktc)}>{fmtSigned(trade.swing_ktc)}</span>,
      },
      { label: "Points", value: <PointsCell reading={pointsReading(trade)} />, testId: "lead-points" },
      { label: "Since", value: <span className="text-dim">{fmtDate(trade.date)}</span> },
    ],
  };
```

`signColor` is the same helper `StandingsTable.tsx` uses — add it locally:

```tsx
function signColor(n: number): string {
  return n > 0 ? "text-pos" : n < 0 ? "text-neg" : "text-dim";
}
```

The empty-trade branch keeps its headline, body, and `Browse trades →` button, with three dim placeholder cells:

```tsx
      cells: [
        { label: "Value", value: <span className="text-dim">—</span> },
        { label: "Points", value: <span className="text-dim">—</span>, testId: "lead-points" },
        { label: "Since", value: <span className="text-dim">—</span> },
      ],
```

`weekRecapContent` — the recap's own figures, name and number in one cell:

```tsx
    cells: [
      { label: "High", value: <><span className="font-semibold">{high}</span> {recap.high_score.points.toFixed(1)}</> },
      { label: "Blowout", value: <><span className="font-semibold">{winner}</span> +{recap.blowout.margin.toFixed(1)}</> },
      {
        label: "Traded",
        value: traded
          ? <><span className="font-semibold">{who(traded)}</span> {traded.points.toFixed(1)}</>
          : <span className="text-dim">—</span>,
      },
    ],
```

Its no-recap placeholder branch keeps the same three labels with `<span className="text-dim">—</span>` values. `bracketWatchContent` keeps its three labels (`Alive`, `Seed`, `Playoff pts`) with the same dim placeholders — leave its `TODO(bracket-watch-payload)` comment intact.

- [ ] **Step 5: Delete the two-column grid and the duplicated render**

Replace the component's return body:

```tsx
  return (
    <section className="mb-8">
      <div className="tap flex items-baseline justify-between border-b border-rule pt-4 pb-1.5">
        <span className="font-mono text-[9px] uppercase tracking-[0.16em] text-dim">{lead.kicker}</span>
        <span className="font-mono text-[9px] uppercase tracking-[0.12em] text-dim">{lead.phaseNote}</span>
      </div>

      <div className="font-display text-[25px] font-extrabold tracking-[-0.035em] leading-[1.05] mt-3 max-w-[24ch]">
        {headline}
      </div>
      <p className="mt-2 max-w-[46ch] text-[12px] leading-relaxed text-body">{lead.body}</p>
      {lead.actionHref && (
        <Button as="link" href={lead.actionHref} className="mt-3 inline-block px-3 py-2">
          {lead.actionLabel}
        </Button>
      )}

      <FigureStrip cells={lead.cells} />

      {lead.href && (
        <div className="flex justify-end max-w-[620px] mt-2">
          <Link href={lead.href} className="font-mono text-[9px] uppercase tracking-[0.12em] hover:underline">
            Read the trade →
          </Link>
        </div>
      )}
    </section>
  );
```

Add the imports: `import { tradeHeadline, pointsReading, type PointsReading } from "@/lib/trade-lead";`

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd web && npx vitest --config tests/vitest.config.ts run tests/HeadlineMoves.test.tsx`
Expected: PASS. Four pre-existing tests in that file assert the old lead and must be updated — not deleted, each still covers something real:

1. **"links the headline to the trade's detail page"** — `getByRole("link", { name: /Tom & Mike/ })`. The headline is now `"Tom won this one on both counts."` and the trade link moved to `Read the trade →`. Change to:
   ```tsx
   expect(screen.getByRole("link", { name: /Read the trade/ }))
     .toHaveAttribute("href", "/league/L1/trade/tx1");
   ```
2. **"shows the kicker, phase note, and real swing figures — never invented"** — drop the `"+120.5"` assertion (`swing_prod` no longer renders; the split does) and keep `"+1,450"`. Add `expect(screen.getByTestId("lead-points").textContent).toBe("140.0 vs 19.5");`
3. **"gives the figures the rail — no subject column repeating the headline"** — written against the two-column `FigureTable`. Replace its body with an assertion that the strip's figure rule holds three cells:
   ```tsx
   expect(screen.getByText("Value").parentElement!.childElementCount).toBe(3);
   ```
4. **"keeps a visible placeholder when no recap has landed yet"** — `getAllByText("—").length >= 6` assumed the block rendered twice. The strip renders once, so change `6` to `3`.

The `/Tom & Mike/` link assertion near the end of the file (the trade-of-the-week regression test) needs the same treatment as (1).

- [ ] **Step 7: Run the whole frontend suite plus the Agate guard**

Run: `cd web && npx vitest --config tests/vitest.config.ts run`
Expected: PASS, including `tests/agate-rules.test.ts`.

- [ ] **Step 8: Commit**

```bash
git add web/components/HeadlineMoves.tsx web/tests/HeadlineMoves.test.tsx
git commit -m "feat(web): dashboard lead verdict headline + figure strip"
```

---

### Task 4: Skeleton parity and the design-system amendment

**Files:**
- Modify: `web/components/DashboardSkeleton.tsx:77-90`
- Modify: `design_handoff_agate/DESIGN.md`
- Modify: `.claude/skills/agate-styling/SKILL.md`
- Test: `web/tests/DashboardSkeleton.test.tsx`

**Interfaces:**
- Consumes: the strip markup from Task 3.
- Produces: nothing.

- [ ] **Step 1: Write the failing test**

Add to `web/tests/DashboardSkeleton.test.tsx`:

```tsx
it("lays the lead out on the same tracks as the live lead — no rail", () => {
  const { container } = render(<DashboardSkeleton />);
  // The 210px/250px right rail is gone from both; a mismatch here is the
  // 40px shift this skeleton exists to prevent.
  expect(container.innerHTML).not.toContain("210px");
  expect(container.innerHTML).not.toContain("250px");
  expect(container.innerHTML).toContain("620px");
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd web && npx vitest --config tests/vitest.config.ts run tests/DashboardSkeleton.test.tsx`
Expected: FAIL — `210px` still present.

- [ ] **Step 3: Drop the rail from the skeleton**

In `web/components/DashboardSkeleton.tsx`, replace the whole lead block (the comment through the closing `</div>` of the two-column grid) with:

```tsx
      {/* The lead — kicker/phase row, headline + body, three-cell figure strip
          on the same 620px measure the live lead uses (HeadlineMoves). */}
      <div className="mb-8">
        <div className="tap flex items-baseline justify-between border-b border-rule pt-4 pb-1.5">
          <Bar className="h-[9px] w-28" />
          <Bar className="h-[9px] w-16" />
        </div>
        <div className="mt-3">
          <Bar className="h-[22px] w-[62%]" />
          <Bar className="mt-2 h-[22px] w-[38%]" />
          <Bar className="mt-3 h-[10px] w-[46%]" />
        </div>
        <Ruled className="mt-4 max-w-[620px]">
          {Array.from({ length: 2 }).map((_, r) => (
            <Rule key={r} className="grid grid-cols-3 gap-4 px-2 items-center">
              {Array.from({ length: 3 }).map((_, c) => (
                <Bar key={c} className={r === 0 ? "h-[8px] w-10" : "h-[10px] w-16"} />
              ))}
            </Rule>
          ))}
        </Ruled>
      </div>
```

- [ ] **Step 4: Run it to verify it passes**

Run: `cd web && npx vitest --config tests/vitest.config.ts run tests/DashboardSkeleton.test.tsx`
Expected: PASS

- [ ] **Step 5: Amend the design system**

In `design_handoff_agate/DESIGN.md`, find the lead's description under the named rules ("The lead, by phase") and replace the bordered-right-rail skeleton with the strip. Add a sentence recording the change and why, in the file's own voice:

> **The Lead Is Rules, Not A Box.** The lead's figures sit on a three-cell ruled strip beneath the body, capped at 620px — not in a bordered rail. The rail was drawn in `Dynasty Directions.dc.html` Fig. 2a.1 and shipped, but it forced a 250px column to carry a subject, a label, and a figure, and all three ellipsed; across the full measure the same three figures read as unrelated facts. Depth here is rules. The strip is three cells at every viewport and in every phase, so the page never reflows across the season.

In `.claude/skills/agate-styling/SKILL.md`, add a row to the "Reuse, don't invent" table:

| Lead figure strip | `HeadlineMoves.tsx` — `FigureStrip` | three cells, 620px cap, one render at every width |

- [ ] **Step 6: Verify the full suite and lint**

Run: `make test`
Expected: PASS both suites.

Run: `cd web && npx tsc --noEmit && npm run lint 2>&1 | grep -c "Error:"`
Expected: tsc silent; error count `20` — the pre-existing `MethodologyContent.tsx` unescaped-entity errors, unchanged. Any other number means this work introduced a lint error.

- [ ] **Step 7: Commit**

```bash
git add web/components/DashboardSkeleton.tsx web/tests/DashboardSkeleton.test.tsx design_handoff_agate/DESIGN.md .claude/skills/agate-styling/SKILL.md
git commit -m "fix(web): skeleton matches the lead's tracks; DESIGN.md records the strip"
```

---

## Verification before calling it done

- [ ] `make test` passes (backend + frontend).
- [ ] `cd web && npx tsc --noEmit` is silent.
- [ ] `npm run lint` error count is still exactly 20 (all in `MethodologyContent.tsx`).
- [ ] Local visual check at 390px, 768px, and 1180px, both themes: the strip's three cells never truncate, the body carries no figures, and the headline names a winner. The live cache has 17 split-verdict trades, so both headline forms are reachable with real data.
- [ ] Deploy per the `railway-deploy` skill (push to `main` auto-deploys both services); confirm `/` → 302, `/login` → 200.
