> _Historical doc — paths/names have changed. Repo is now `Code Apps/public-dynasty` (GitHub `tkeefe66/public-dynasty-app`), Railway project **shimmering-nature**, live at https://ffbdynasty.com. Ignore stale refs to `sleeper-dynasty` / `sleeper-trade-grader` / `web-production-f949`._

# Per-Player Stat Tables (A-frontend) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (inline) — the frontend tasks use live browser mockups, so stay in-session. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Break every trade metric down by player. Each side's haul renders as a stat table (metrics as columns, players as rows, winner-highlighted totals), on both the direct trade card and the "what it became" card.

**Architecture:** Backend exposes a per-asset `breakdown` (one `AssetLine` per player/pick) for both the direct grade and the became grade, plus gross `received_ktc` for the direct grade — computed by retaining the per-asset rows the engine already iterates. A new responsive `TradeStatTable` React component renders them: full 6-column table on desktop, Player·KTC·Total + tap-to-expand on mobile. Cache schema bumps to re-grade.

**Tech Stack:** Python (dataclasses, pytest, Pydantic v2), TypeScript/React (vitest, Tailwind).

**Spec:** `docs/superpowers/specs/2026-06-09-per-player-stat-tables-design.md`

**Test commands** (single commands, no redirects; `git -C "/Users/tomkeefe/Code Apps/sleeper-dynasty"` for git):
- Engine: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && .venv/bin/python -m pytest tests/ -q`
- API: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/api" && .venv/bin/python -m pytest -q`
- Web: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/web" && npx vitest run --config tests/vitest.config.ts`

---

# PHASE 1 — Engine

## Task 1: `AssetLine` + direct-grade breakdown

**Files:** `src/sleeper_dynasty/models/trade.py`, `src/sleeper_dynasty/engine/trade_grader.py`, test `tests/test_trade_grader.py`.

- [ ] **Step 1: Add the dataclass** (`models/trade.py`, near `TradeGrade`)

```python
@dataclass
class AssetLine:
    label: str                 # "Bijan Robinson" or "2027 1st"
    kind: str                  # "player" | "pick"
    player_id: str | None
    ktc: float
    production_total: float
    production_regular: float
    production_playoff: float
    production_toilet: float
```

Add two fields to `TradeGrade`:

```python
    received_ktc: dict[str, float] = field(default_factory=dict)
    breakdown: dict[str, list[AssetLine]] = field(default_factory=dict)
```

- [ ] **Step 2: Write the failing test** (append to `tests/test_trade_grader.py`)

```python
from sleeper_dynasty.engine.trade_grader import build_asset_breakdown

def test_direct_breakdown_per_player_and_pick():
    rt = _stub_resolved_trade(
        received_by_uid={
            "u1": [PlayerAsset("p_bijan", "Bijan"),
                   PickAsset(season=2027, round=1, original_owner_user_id="u1")],
            "u2": [PlayerAsset("p_adams", "Adams")],
        },
        given_by_uid={
            "u1": [PlayerAsset("p_adams", "Adams")],
            "u2": [PlayerAsset("p_bijan", "Bijan"),
                   PickAsset(season=2027, round=1, original_owner_user_id="u1")],
        },
    )
    ktc = {
        "p_bijan": KTCValue(name="Bijan", normalized_name="b", position="RB",
                            superflex_value=7500, one_qb_value=7400),
        "p_adams": KTCValue(name="Adams", normalized_name="a", position="WR",
                            superflex_value=6050, one_qb_value=6000),
    }
    matchups = {
        ("L", 3, 1): {"starters": ["p_bijan"], "players": ["p_bijan"],
                      "players_points": {"p_bijan": 20.0}},
        ("L", 3, 2): {"starters": ["p_adams"], "players": ["p_adams"],
                      "players_points": {"p_adams": 15.0}},
    }
    rows = build_asset_breakdown(
        rt, ktc_values=ktc, matchups=matchups,
        roster_to_user_by_league={"L": {1: "u1", 2: "u2"}},
        playoff_week_start_by_league={"L": 15}, fmt="superflex",
    )
    u1 = rows["u1"]
    # One player row + one pick row.
    bijan = next(r for r in u1 if r.player_id == "p_bijan")
    assert bijan.kind == "player"
    assert bijan.ktc == 7500.0
    assert bijan.production_total == 20.0
    assert bijan.production_regular == 20.0   # week 3 started, regular
    pick = next(r for r in u1 if r.kind == "pick")
    assert pick.production_total == 0.0       # picks don't score
    assert "2027" in pick.label
    # Row sums equal the side's existing per-side totals.
    g = grade_trade(rt, ktc_values=ktc, matchups=matchups,
                    roster_to_user_by_league={"L": {1: "u1", 2: "u2"}},
                    playoff_week_start_by_league={"L": 15}, fmt="superflex")
    assert g.production_total["u1"] == pytest.approx(sum(r.production_total for r in u1))
    assert g.received_ktc["u1"] == pytest.approx(sum(r.ktc for r in u1))
    assert g.breakdown["u1"] == u1
```

- [ ] **Step 3: Run — expect fail** (`ImportError: build_asset_breakdown`).

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && .venv/bin/python -m pytest tests/test_trade_grader.py::test_direct_breakdown_per_player_and_pick -q`

- [ ] **Step 4: Implement**

First extract the per-player points walk to a module-level helper (the current closure inside `grade_hindsight_production`). Add to `trade_grader.py`:

```python
def _points_while_owned(
    pid: str, uid: str, *,
    matchups, roster_to_user_by_league, rt,
    league_season_by_id=None, starters_only=False,
    phase_filter=None, phase_by_lwr=None, playoff_week_start_by_league=None,
) -> float:
    """Points pid scored while owned by uid, post-trade, optionally phase-gated."""
    league_season_by_id = league_season_by_id or {}
    phase_by_lwr = phase_by_lwr or {}
    playoff_week_start_by_league = playoff_week_start_by_league or {}
    roster_field = "starters" if starters_only else "players"
    total = 0.0
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
        total += float((entry.get("players_points") or {}).get(pid, 0.0) or 0.0)
    return total
```

Add a pick-label helper and the breakdown builder:

```python
def _pick_label(a: PickAsset) -> str:
    if getattr(a, "drafted_player_name", None):
        return f"{a.season} R{a.round} ({a.drafted_player_name})"
    ordinal = {1: "1st", 2: "2nd", 3: "3rd"}.get(a.round, f"{a.round}th")
    return f"{a.season} {ordinal}"

def build_asset_breakdown(
    rt, *, ktc_values, matchups, roster_to_user_by_league,
    league_season_by_id=None, phase_by_lwr=None,
    playoff_week_start_by_league=None, pick_values=None, fmt="superflex",
) -> dict[str, list[AssetLine]]:
    league_season_by_id = league_season_by_id or {}
    out: dict[str, list[AssetLine]] = {}
    for uid, side in rt.sides.items():
        rows: list[AssetLine] = []
        for a in side.received:
            ktc = _ktc_value(a, ktc_values, fmt, pick_values)
            if isinstance(a, PlayerAsset):
                common = dict(
                    matchups=matchups, roster_to_user_by_league=roster_to_user_by_league,
                    rt=rt, league_season_by_id=league_season_by_id,
                    phase_by_lwr=phase_by_lwr,
                    playoff_week_start_by_league=playoff_week_start_by_league,
                )
                rows.append(AssetLine(
                    label=a.name, kind="player", player_id=a.player_id, ktc=ktc,
                    production_total=_points_while_owned(a.player_id, uid, **common),
                    production_regular=_points_while_owned(a.player_id, uid, starters_only=True, phase_filter="regular", **common),
                    production_playoff=_points_while_owned(a.player_id, uid, starters_only=True, phase_filter="playoff", **common),
                    production_toilet=_points_while_owned(a.player_id, uid, starters_only=True, phase_filter="toilet", **common),
                ))
            elif isinstance(a, PickAsset):
                rows.append(AssetLine(
                    label=_pick_label(a), kind="pick", player_id=None, ktc=ktc,
                    production_total=0.0, production_regular=0.0,
                    production_playoff=0.0, production_toilet=0.0,
                ))
            # FaabAsset: skip (zero value, not a roster contributor).
        out[uid] = rows
    return out
```

In `grade_trade`, populate the new fields:

```python
    breakdown = build_asset_breakdown(
        rt, ktc_values=ktc_values, matchups=matchups,
        roster_to_user_by_league=roster_to_user_by_league,
        league_season_by_id=league_season_by_id, phase_by_lwr=phase_by_lwr or {},
        playoff_week_start_by_league=playoff_week_start_by_league,
        pick_values=pick_values, fmt=fmt,
    )
    received_ktc = {uid: sum(r.ktc for r in rows) for uid, rows in breakdown.items()}
```

Add `received_ktc=received_ktc, breakdown=breakdown` to the `TradeGrade(...)` return.
(Import `AssetLine`, `PickAsset` are already imported; confirm imports.) Optionally
refactor `grade_hindsight_production`'s inner `_received_points` to delegate to
`_points_while_owned` — not required for green, keep if clean.

- [ ] **Step 5: Run** the test + full engine suite green. Commit:

```bash
git -C "/Users/tomkeefe/Code Apps/sleeper-dynasty" add -A
git -C "/Users/tomkeefe/Code Apps/sleeper-dynasty" commit -m "feat(engine): per-asset direct-grade breakdown + gross received KTC"
```

## Task 2: Became-grade breakdown

**Files:** `src/sleeper_dynasty/engine/regrade.py`, test `tests/test_regrade.py`.

- [ ] **Step 1: Write the failing test** — assert `build_became_grade` returns a
`breakdown` list per uid whose rows sum to the existing `ktc`/`production`/`regular`/
`playoff`/`toilet` totals, and that a terminal player row carries its label + player_id.
Mirror the existing regrade test fixtures in `tests/test_regrade.py`.

- [ ] **Step 2: Run — expect fail** (`breakdown` key missing).

- [ ] **Step 3: Implement** — in `build_became_grade`, accumulate per-asset rows
alongside the existing scalar totals:

```python
        rows: list[dict] = []
        for a in assets:
            labels.append(a["label"])
            if a["kind"] == "player":
                pid = a["player_id"]
                v = ktc_values.get(pid)
                a_ktc = _from_ktc(v, fmt)
                ptot = _production_while_owned(pid, uid, starters_only=False, phase_filter=None, **common)
                preg = _production_while_owned(pid, uid, starters_only=True, phase_filter="regular", **common)
                ppla = _production_while_owned(pid, uid, starters_only=True, phase_filter="playoff", **common)
                ptoi = _production_while_owned(pid, uid, starters_only=True, phase_filter="toilet", **common)
                ktc += a_ktc; production += ptot; regular += preg; playoff += ppla; toilet += ptoi
                rows.append({"label": a["label"], "kind": "player", "player_id": pid,
                             "ktc": a_ktc, "production_total": ptot, "production_regular": preg,
                             "production_playoff": ppla, "production_toilet": ptoi})
            else:
                a_ktc = _from_ktc(pick_values.get((a["season"], a["round"])), fmt)
                ktc += a_ktc
                rows.append({"label": a["label"], "kind": "pick", "player_id": None,
                             "ktc": a_ktc, "production_total": 0.0, "production_regular": 0.0,
                             "production_playoff": 0.0, "production_toilet": 0.0})
        out[uid] = {"ktc": ktc, "production": production, "regular": regular,
                    "playoff": playoff, "toilet": toilet,
                    "terminal_labels": labels, "breakdown": rows}
```

(Move the existing per-phase `_production_while_owned` calls into this loop so each is
computed once and reused for both the total and the row.)

- [ ] **Step 4: Run** test + engine suite green. Commit:

```bash
git -C "/Users/tomkeefe/Code Apps/sleeper-dynasty" commit -am "feat(engine): per-terminal-player breakdown in became grade"
```

---

# PHASE 2 — API

## Task 3: Expose breakdown + received_ktc; bump cache

**Files:** `api/app/services/chain_cache.py`, `api/app/models/trade.py`, `api/app/services/trade_view.py`, tests `api/tests/test_trade.py`.

- [ ] **Step 1:** Bump `SCHEMA_VERSION` 3 → 4 in `chain_cache.py`.

- [ ] **Step 2: Write the failing API test** (`api/tests/test_trade.py`) — extend the
grade fixture with `received_ktc` + `breakdown` (and became `breakdown`), assert the
serialized response carries `received_ktc` and `breakdown` per side with the row fields,
and that `sum(row.production_total) == side.production_total`.

- [ ] **Step 3: Implement** — add the Pydantic model + fields:

```python
class AssetLine(BaseModel):
    label: str
    kind: str
    player_id: str | None = None
    ktc: float
    production_total: float
    production_regular: float
    production_playoff: float
    production_toilet: float
```

On `TradeSideView` add `received_ktc: float = 0.0` and `breakdown: list[AssetLine] = []`.
On `BecameMetrics` add `breakdown: list[AssetLine] = []`. In `trade_view.build_trade_detail`,
read `grade.get("received_ktc")` per uid and map `grade.get("breakdown")` rows onto
`AssetLine`; map `became[...]["breakdown"]` likewise. (The grade dict already serializes
the engine `AssetLine` via `asdict`.)

- [ ] **Step 4: Run** API suite green. Commit:

```bash
git -C "/Users/tomkeefe/Code Apps/sleeper-dynasty" commit -am "feat(api): expose per-player breakdown + received KTC on trade detail"
```

---

# PHASE 3 — Frontend (live mockups)

## Task 4: Types

**File:** `web/lib/types.ts`.

- [ ] Add the TS interface and fields (mirror the API):

```ts
export interface AssetLine {
  label: string;
  kind: "player" | "pick";
  player_id: string | null;
  ktc: number;
  production_total: number;
  production_regular: number;
  production_playoff: number;
  production_toilet: number;
}
```

Add `received_ktc: number;` and `breakdown: AssetLine[];` to `TradeSideView`; add
`breakdown: AssetLine[];` to `BecameMetrics`. Commit.

## Task 5: `TradeStatTable` component

**File:** `web/components/TradeStatTable.tsx` (new), test `web/tests/TradeStatTable.test.tsx`.

- [ ] **Step 1: Write the component.** Props:

```ts
interface Totals { ktc: number; total: number; regular: number; playoff: number; toilet: number; }
interface Props {
  ownerName: string;
  rows: AssetLine[];
  totals: Totals;
  compare?: Totals;   // other side's totals, for winner highlight
}
```

Behavior:
- Sort rows: players by `production_total` desc, then pick rows by `ktc` desc.
- Desktop (`hidden sm:table`): columns `Player | KTC | Tot | Reg | Ply | Toi`. Numeric
  cells `tabular`, right-aligned. Pick rows show `—` for the four point columns.
- TOTAL row (bold). For each column where `compare` exists and this side's value is
  strictly greater, the total cell gets `text-pos` (winner). Ties/lower stay `text-ink`.
- Mobile (`sm:hidden`): each player is a `<details>` row showing `Player · KTC · Total`;
  `<summary>` is tappable, expanded content lists Regular/Playoff/Toilet. Totals row
  (Player·KTC·Total) always visible and winner-highlighted.
- Tokens: `bg-surface border border-divider rounded-card`, `text-dim` headers
  (`font-mono text-[10px] uppercase tracking-widest`), `text-ink` body. AA both themes.
- Number formatting: KTC `Math.round(n).toLocaleString()`, points `n.toFixed(1)`.

- [ ] **Step 2: Write tests** — renders a row per asset; sorts picks last; the higher
side's total column is highlighted; pick row shows `—` for points. Run web suite.

- [ ] **Step 3: Commit.**

## Task 6: Wire-in + live mockups

**Files:** `web/app/league/[id]/trade/[tid]/page.tsx`, `web/components/TradeBecame.tsx`, `web/components/TradeSidePanel.tsx`, tests.

- [ ] **Step 1: Became card** — replace `SideCard`'s five `Metric` rows with
`<TradeStatTable ownerName={...} rows={m.breakdown} totals={{ktc:m.ktc, total:m.production, regular:m.regular, playoff:m.playoff, toilet:m.toilet}} compare={otherSideTotals} />`.
Keep the "What it became" section header and the empty-haul filter.

- [ ] **Step 2: Direct trade page** — render a `TradeStatTable` per side using
`side.breakdown` + totals `{ktc: side.received_ktc, total: side.production_total, ...}`,
comparing against the other side. Keep the **"Gave"** list (from `side.given`, via
`AssetRender`). Slim `TradeSidePanel` to owner header + Gave list (remove its Market/Points
sections, now in the table) — or replace it inline on the page. Decide here.

- [ ] **Step 3: Live mockups.** Start a temp preview route with realistic 2-side and
3-side mock data (as in the earlier scoreboard preview), run `next dev` on a spare port,
screenshot light + dark + a narrow (mobile) viewport with Playwright, and iterate on:
desktop two-table density (side-by-side vs stacked), winner-highlight treatment
(`text-pos` vs subtle cell tint), and the mobile collapse. Remove the temp route before
finishing.

- [ ] **Step 4:** Update affected web tests (`TradeBecame.test.tsx`, `TradeSidePanel.test.tsx`,
`OwnerDeepDive`/OG if they assert removed rows). Run web suite + `npx tsc --noEmit` green.

- [ ] **Step 5: Commit.**

---

## Final verification

- [ ] Engine: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && .venv/bin/python -m pytest tests/ -q`
- [ ] API: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/api" && .venv/bin/python -m pytest -q`
- [ ] Web: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/web" && npx vitest run --config tests/vitest.config.ts` and `npx tsc --noEmit`
- [ ] Manual smoke (optional): real refresh → trade detail shows per-player tables, row
      sums match the totals, mobile collapses.

## Self-review notes (addressed)

- **Row sums = totals:** every grade keeps its existing per-side totals; the breakdown is
  additive and unit-tested to sum to them (no drift, existing total tests untouched).
- **Picks:** KTC-only rows, `—` for points, sorted last — both grades.
- **`asdict` serialization:** engine `AssetLine` dataclass serializes into the cached grade
  dict automatically; the API maps it to the Pydantic `AssetLine`.
- **Cache bump (4):** re-grade picks up the new fields; cold-start contract handles it.
- **Live-iterate items** (desktop density, highlight style, TradeSidePanel slim-vs-replace)
  are explicitly deferred to Task 6 Step 3, not guessed.
- **Out of scope:** GM Rating redesign + toilet sign (B).
