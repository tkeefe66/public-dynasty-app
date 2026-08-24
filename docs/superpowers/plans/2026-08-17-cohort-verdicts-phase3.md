# Cohort Verdicts Implementation Plan (Phase 2.5 + 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every drafted pick a measured verdict — **Hit / Average / Bust** — against what players ranked the same actually scored, and free the column space to show it.

**Architecture:** A committed table of raw per-season component stats for historically-ranked rookies is scored at refresh with each league's own settings, producing 25th/75th-percentile bars per `(ECR band, seasons held)` cohort. A pure engine module turns a pick's production into a verdict against its own cohort. Nothing about the verdict is a chosen threshold.

**Tech Stack:** Python 3.11, pytest, FastAPI/Pydantic, Next.js 14 + TypeScript, vitest.

**Spec:** `docs/superpowers/specs/2026-08-17-draft-board-redesign-design.md` — see **Verdict — Hit / Average / Bust** and **The column budget**.

**Depends on:** phases 1 and 2, on `new-draft-board`.

## Global Constraints

- **Branch:** all work on `new-draft-board`. Never commit to `main`. **Do not push** — PR #10 is open and updating it is the owner's call.
- **No `SCHEMA_VERSION` bump.** New per-pick fields are additive on `drafted_picks`, already in the always-recomputed value layer, read with `.get()` defaults.
- **The verdict must never feed Franchise Rating.** `engine/draft_signals.py::draft_skill` stays the only draft baseline that does.
- **Nothing is a chosen threshold.** Every bar is a percentile of real outcomes. If you find yourself writing a constant like `40.0` to mean "good", stop — that is the thing this phase exists to eliminate.
- **An unranked, keeper, or auction pick gets no verdict** — `""`, never a guess. Read from the same shared `scored` list `build_draft_review` and `draft_board_view` already filter on.
- **nflverse release path is `stats_player/stats_player_week_{season}.csv`.** The legacy `player_stats/` path returns 200 for 1999 and **404s for 2025** — it serves history only. Building on it silently costs the most recent season.
- **Never render "KTC"** — it is "Trade Value" / "Value".
- Tailwind's JIT scanner reads source as text: every grid template is a complete literal, never concatenated.
- **Below the breakpoint every column survives** as an alternate rendering. Nothing `display:none` with no replacement.
- **Test commands:** engine `pytest tests/` from repo root (bare `pytest` breaks). Backend `cd api && pytest -v` (~3 min; some `test_grader_service.py` tests take ~30s each). Frontend `cd web && npx vitest --config tests/vitest.config.ts run` (**always** pass the config flag).

---

### Task 1: Trim the board's pick columns (phase 2.5)

Phase 2 put the full five-metric run on the board's pick rows. A width audit then showed the table needs **988px before the Player column gets anything** once this phase adds Verdict — about 1188px of viewport for a legible name, against a gate of 870px. The gate had already moved once (701 → 870).

So the board's pick rows keep only what the board is for — *who drafted well* — and the per-phase split moves to the surfaces that ask about one manager.

**This partly reverses phase 2, deliberately.** Regular / Playoff / Toilet stay on the board's **owner rows** and in full on the owner Draft tab; only the **pick rows** lose them.

**Files:**
- Modify: `web/components/DraftBoard.tsx` (`PicksSection` + its grid literals)
- Modify: `web/components/DraftPicksMobile.tsx` (`PickCard` — the owner card keeps everything)
- Modify: `web/tests/draft-board.test.tsx`

**Interfaces:**
- Consumes: the existing `DraftBoardPick` fields — **no API change**. The fields stay on the response; the board stops rendering three of them on pick rows.
- Produces: `pickGrid(hasBaseline, hasProjected, graded)` reduced from eight literals to six.

- [ ] **Step 1: Write the failing test**

Add to `web/tests/draft-board.test.tsx`:

```tsx
it("keeps the board's pick rows to what the board is for", () => {
  // The board answers "who drafted well". Regular/Playoff/Toilet are a
  // question about one manager, so they live on the OWNER rows and the owner
  // Draft tab, not on 36 pick rows nobody scans. See the spec's column budget.
  render(<DraftBoard leagueId="lg" board={{ ...base, graded: true }} />);
  const desktop = screen.getByTestId("draft-picks-desktop");
  expect(within(desktop).queryByText("Regular")).toBeNull();
  expect(within(desktop).queryByText("Playoff")).toBeNull();
  expect(within(desktop).queryByText("Toilet")).toBeNull();
  // What stays:
  expect(within(desktop).getAllByText("Total Points").length).toBeGreaterThan(0);
  expect(within(desktop).getAllByText("Start %").length).toBeGreaterThan(0);
});

it("drops Projected once a class is graded, and keeps it while unplayed", () => {
  // A preseason estimate is superseded by what actually happened. On an
  // unplayed class it is the only forward-looking figure there is.
  const withProj = { ...base, picks: [{ ...base.picks[0], projected_points: 210.5 }] };
  const { rerender } = render(
    <DraftBoard leagueId="lg" board={{ ...withProj, graded: false }} />);
  expect(within(screen.getByTestId("draft-picks-desktop")).getAllByText("Proj").length)
    .toBeGreaterThan(0);
  rerender(<DraftBoard leagueId="lg" board={{ ...withProj, graded: true }} />);
  expect(within(screen.getByTestId("draft-picks-desktop")).queryByText("Proj")).toBeNull();
});

it("still shows every metric on the owner rows and the phone cards", () => {
  // The trim is about the BOARD'S PICK ROWS only. Losing these anywhere else
  // would be data loss, not editing.
  render(<DraftBoard leagueId="lg" board={{ ...base, graded: true }} />);
  const owners = screen.getByTestId("draft-owners-desktop");
  expect(within(owners).getAllByText("Regular").length).toBeGreaterThan(0);
  expect(within(owners).getAllByText("Playoff").length).toBeGreaterThan(0);
  expect(within(owners).getAllByText("Toilet").length).toBeGreaterThan(0);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest --config tests/vitest.config.ts run draft-board`
Expected: the first two FAIL — the pick rows currently render Regular/Playoff/Toilet and render Proj alongside them when graded.

- [ ] **Step 3: Reduce the grid literals from eight to six**

`graded` now implies **no** projection, so the `hasProjected × graded` combination disappears. In `web/components/DraftBoard.tsx` replace the eight `GRID_P*` constants and `pickGrid` with:

```tsx
/* Six literals: hasBaseline × (graded | hasProjected | neither). `graded`
   implies no Projected — a preseason estimate is superseded by what actually
   happened — so the two never coexist and the eighth/seventh combinations
   cannot occur. Spelled out because Tailwind's JIT scanner needs each complete
   arbitrary-value class as literal source text; an interpolated template
   silently loses its columns in a production build while every test passes. */
const GRID_P_PLAIN = "grid-cols-[30px_120px_minmax(0,1fr)]";
const GRID_P_PROJ = "grid-cols-[30px_120px_minmax(0,1fr)_60px]";
const GRID_P_GRADED = "grid-cols-[30px_120px_minmax(0,1fr)_60px_56px_40px]";
const GRID_PB_PLAIN = "grid-cols-[30px_120px_minmax(0,1fr)_46px_50px]";
const GRID_PB_PROJ = "grid-cols-[30px_120px_minmax(0,1fr)_46px_50px_60px]";
const GRID_PB_GRADED = "grid-cols-[30px_120px_minmax(0,1fr)_46px_50px_60px_56px_40px]";

function pickGrid(hasBaseline: boolean, hasProjected: boolean, graded: boolean): string {
  if (hasBaseline && graded) return GRID_PB_GRADED;
  if (hasBaseline && hasProjected) return GRID_PB_PROJ;
  if (hasBaseline) return GRID_PB_PLAIN;
  if (graded) return GRID_P_GRADED;
  if (hasProjected) return GRID_P_PROJ;
  return GRID_P_PLAIN;
}
```

Graded pick columns are now: **Total Points** (60) · **Start %** (56) · **GS** (40).

- [ ] **Step 4: Remove the three headers and three cells, and gate Proj on `!graded`**

In `PicksSection`, delete the `Regular` / `Playoff` / `Toilet` `columnheader` elements and their matching `cell` elements in the body row. Change the Projected header and cell conditions from `hasProjected` to `hasProjected && !board.graded`.

In `DraftPicksMobile.tsx`'s **`PickCard`** only, remove the same three `Stat` entries. **Do not touch `OwnerGroup`** — the owner card keeps every figure, and the desktop owner table keeps its columns.

- [ ] **Step 5: Run the suite**

Run: `cd web && npx vitest --config tests/vitest.config.ts run`
Expected: PASS including `furniture-rules.test.ts`. Satisfy the guard by fixing code, never by an exception entry.

- [ ] **Step 6: Verify the width claim**

```bash
cd "/Users/tomkeefe/Code Apps/public-dynasty"
python3 -c "
t=[30,120,46,50,60,56,40]           # GRID_PB_GRADED fixed tracks
need=sum(t)+ (len(t)+1)*10 + 28     # +1 gap for the Player track, Row px-3.5
print('needs', need, 'px before Player; at 870vw Player gets', 870-48-2-need, 'px')
assert 870-48-2-need > 150, 'Player column must clear 150px at the current gate'
print('OK — Player clears 150px at the 870px gate')
"
```

Expected: `OK`. If it fails, the trim did not free enough and the plan needs revisiting before Task 6 adds Verdict.

- [ ] **Step 7: Commit**

```bash
git add web/components/DraftBoard.tsx web/components/DraftPicksMobile.tsx web/tests/draft-board.test.tsx
git commit -m "refactor(web): board pick rows carry only what the board is for"
```

---

### Task 2: Extract the rookie component-stat history

The verdict bars are **league-scoring-specific** — this league's 6-point pass TDs moved the ECR 9–12 hit bar from 166.5 to 194.4 against nflverse's 4-point PPR column. So a table of *points* cannot ship. The **inputs** can: raw per-season component stats for the ~470 historically-ranked rookies, scored with each league's own settings at refresh.

**Files:**
- Create: `scripts/extract_rookie_stats.py`
- Create: `src/sleeper_dynasty/data/rookie_stats.json.gz`
- Test: `tests/test_rookie_stats_data.py`

**Interfaces:**
- Consumes: `engine/rookie_board.py::ROOKIE_ECR_TYPE`, `api/player_ids.build_fantasypros_to_sleeper` (phase 1).
- Produces: the packaged resource `sleeper_dynasty.data/rookie_stats.json.gz` — `{sleeper_id: {"ecr": float, "class": int, "seasons": [{season, stats...}, ...]}}`.

- [ ] **Step 1: Write the extract script**

Create `scripts/extract_rookie_stats.py`:

```python
"""Regenerate the committed rookie component-stat history.

    pip install -e '.[dev]'
    PYTHONPATH=src python3 scripts/extract_rookie_stats.py

WHY COMPONENTS AND NOT POINTS. The verdict bars are percentiles of fantasy
points, and fantasy points depend on the league's own scoring — 6-point pass
TDs versus 4 moves a QB-heavy cohort's bar by ~30 points. A committed table of
POINTS would be correct for exactly one league. Committing the raw components
and scoring them per league at refresh is correct for all of them.

WHY THIS PATH. nflverse renamed the release: `player_stats/player_stats_2025.csv`
404s while `player_stats/player_stats_1999.csv` still returns 200, so the legacy
path serves history only and silently omits the most recent season. Verify with:

    curl -sL -o /dev/null -w '%{http_code}\\n' \\
      https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_2025.csv

WHY THIS FILE HAS AN END DATE. It carries classes up to whenever it was last
generated. Re-run to extend it. A maintenance task, not a runtime one.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

from sleeper_dynasty.api.player_ids import IDS_URL, build_fantasypros_to_sleeper
from sleeper_dynasty.engine.rookie_board import ROOKIE_ECR_TYPE

STATS_URL = ("https://github.com/nflverse/nflverse-data/releases/download/"
             "stats_player/stats_player_week_%d.csv")
ECR_PARQUET = ("https://raw.githubusercontent.com/dynastyprocess/data/"
               "master/files/db_fpecr.parquet")
OUT = Path(__file__).resolve().parents[1] / "src/sleeper_dynasty/data/rookie_stats.json.gz"

# Every component this app's scoring settings can price. Anything absent from a
# league's settings simply scores 0 — but a component missing from THIS list can
# never be priced at all, so it is the real contract.
COMPONENTS = (
    "passing_yards", "passing_tds", "interceptions", "passing_2pt_conversions",
    "rushing_yards", "rushing_tds", "rushing_2pt_conversions",
    "receptions", "receiving_yards", "receiving_tds", "receiving_2pt_conversions",
    "sack_fumbles_lost", "rushing_fumbles_lost", "receiving_fumbles_lost",
)
# Classes whose rookie season has completed. Extend as seasons finish.
CLASSES = (2021, 2022, 2023, 2024, 2025)
# The window a class's May board falls in. 2020's board sat outside a narrower
# window and was silently skipped in an earlier pass; this is deliberately wide.
BOARD_FROM, BOARD_TO = "-04-20", "-05-31"


def _num(row, key):
    try:
        return float(row.get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


def main() -> int:
    import pyarrow.parquet as pq

    raw_ids = urllib.request.urlopen(IDS_URL).read().decode("utf-8", "replace")
    xw = build_fantasypros_to_sleeper(list(csv.DictReader(io.StringIO(raw_ids))))
    print(f"crosswalk: {len(xw)} fantasypros -> sleeper")

    with urllib.request.urlopen(ECR_PARQUET) as r:
        table = pq.read_table(io.BytesIO(r.read()),
                              columns=["ecr_type", "id", "ecr", "scrape_date"])
    cols = {c: table.column(c).to_pylist()
            for c in ("ecr_type", "id", "ecr", "scrape_date")}

    def norm(d):
        return d.isoformat() if hasattr(d, "isoformat") else str(d)[:10]

    # One board per class: the latest inside that class's May window.
    boards: dict[int, dict[str, float]] = {}
    picked: dict[int, str] = {}
    for i in range(table.num_rows):
        if cols["ecr_type"][i] != ROOKIE_ECR_TYPE or cols["ecr"][i] is None:
            continue
        day = norm(cols["scrape_date"][i])
        year = int(day[:4])
        if year not in CLASSES or not (f"{year}{BOARD_FROM}" <= day <= f"{year}{BOARD_TO}"):
            continue
        if picked.get(year, "") > day:
            continue
        if picked.get(year) != day:
            picked[year], boards[year] = day, {}
        sid = xw.get(str(cols["id"][i]))
        if sid:  # unmapped is dropped, never zero-ranked
            boards[year][sid] = round(float(cols["ecr"][i]), 2)
    for y in sorted(boards):
        print(f"  class {y}: board {picked[y]}, {len(boards[y])} ranked")

    # Component stats per (player, season), regular season only.
    per_season: dict[int, dict[str, dict]] = {}
    for season in range(min(CLASSES), max(CLASSES) + 1):
        txt = urllib.request.urlopen(STATS_URL % season).read().decode("utf-8", "replace")
        acc: dict[str, dict] = defaultdict(lambda: dict.fromkeys(COMPONENTS, 0.0))
        for row in csv.DictReader(io.StringIO(txt)):
            if (row.get("season_type") or "REG") != "REG":
                continue
            tot = acc[row["player_id"]]
            for c in COMPONENTS:
                tot[c] += _num(row, c)
        per_season[season] = acc
        print(f"  stats {season}: {len(acc)} players")

    gsis = {}
    for r in csv.DictReader(io.StringIO(raw_ids)):
        fp, g = (r.get("fantasypros_id") or "").strip(), (r.get("gsis_id") or "").strip()
        sl = xw.get(fp)
        if sl and g and g != "NA":
            gsis[sl] = g

    out: dict[str, dict] = {}
    for cls_year, board in boards.items():
        for sid, ecr in board.items():
            g = gsis.get(sid)
            if not g:
                continue
            seasons = []
            for n, season in enumerate(range(cls_year, max(CLASSES) + 1), start=1):
                stats = per_season.get(season, {}).get(g)
                if stats is None:
                    break
                seasons.append({"n": n, **{k: round(v, 2) for k, v in stats.items()}})
            if seasons:
                out[sid] = {"ecr": ecr, "class": cls_year, "seasons": seasons}

    if not out:
        print("refusing to write an empty history", file=sys.stderr)
        return 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    blob = gzip.compress(json.dumps(out, separators=(",", ":"), sort_keys=True).encode(), 9)
    OUT.write_bytes(blob)
    print(f"wrote {OUT} — {len(out)} players, {OUT.stat().st_size/1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Generate the file**

```bash
cd "/Users/tomkeefe/Code Apps/public-dynasty"
PYTHONPATH=src /opt/homebrew/bin/python3.11 scripts/extract_rookie_stats.py
```

Expected: five classes, each with a May board, and a few hundred players. **If it reports 0 players, or the file is under 20KB, STOP and report BLOCKED** — committing an empty or truncated history would poison every verdict permanently.

- [ ] **Step 3: Write the shape test**

Create `tests/test_rookie_stats_data.py`:

```python
"""Shape, not values — values move on every regeneration, shape must not."""
import gzip
import json
from importlib.resources import files


def _load() -> dict:
    return json.loads(gzip.decompress(
        files("sleeper_dynasty.data").joinpath("rookie_stats.json.gz").read_bytes()))


def test_history_is_readable_and_non_trivial():
    assert len(_load()) > 200


def test_every_player_has_an_ecr_a_class_and_at_least_one_season():
    for sid, rec in _load().items():
        assert isinstance(sid, str) and sid
        assert isinstance(rec["ecr"], (int, float)) and rec["ecr"] > 0
        assert isinstance(rec["class"], int) and 2000 < rec["class"] < 2100
        assert rec["seasons"], f"{sid} has no seasons"


def test_seasons_are_numbered_from_one_and_contiguous():
    # `n` is seasons-since-draft and the cohort key depends on it. A gap would
    # silently compare a year-3 total against the year-2 bar.
    for sid, rec in _load().items():
        ns = [s["n"] for s in rec["seasons"]]
        assert ns == list(range(1, len(ns) + 1)), f"{sid} has non-contiguous seasons"


def test_component_stats_are_numeric_and_non_negative_where_they_must_be():
    for rec in _load().values():
        for s in rec["seasons"]:
            for k, v in s.items():
                if k == "n":
                    continue
                assert isinstance(v, (int, float)), f"{k} is not numeric"
                assert v >= 0 or k == "interceptions", f"{k} negative: {v}"


def test_no_points_are_committed():
    # Committing POINTS would bake one league's scoring into every league's
    # verdict. Only components ship; scoring happens per league at refresh.
    banned = {"fantasy_points", "fantasy_points_ppr", "points", "pts"}
    for rec in _load().values():
        for s in rec["seasons"]:
            assert not (banned & set(s)), "a points column reached the committed file"
```

- [ ] **Step 4: Run it**

Run: `pytest tests/test_rookie_stats_data.py -v`
Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
git add scripts/extract_rookie_stats.py src/sleeper_dynasty/data/rookie_stats.json.gz tests/test_rookie_stats_data.py
git commit -m "feat(data): commit rookie component-stat history for cohort scoring"
```

---

### Task 3: Score the cohorts

**Files:**
- Create: `src/sleeper_dynasty/engine/rookie_cohorts.py`
- Test: `tests/test_rookie_cohorts.py`

**Interfaces:**
- Consumes: the packaged `rookie_stats.json.gz` (Task 2), threaded in by the caller — this module is **pure**.
- Produces:
  - `ECR_EDGES: tuple[float, ...]` and `band(ecr) -> int`
  - `score_season(stats: dict, scoring: dict) -> float`
  - `build_cohorts(history: dict, scoring: dict, *, min_n: int = 8) -> dict[str, tuple[float, float, float]]` keyed `"{band}|{n}"` → `(p25, median, p75)`
  - `verdict(total: float | None, ecr: float | None, seasons_held: int, cohorts: dict) -> str` → `"hit" | "average" | "bust" | ""`

- [ ] **Step 1: Write the failing test**

Create `tests/test_rookie_cohorts.py`:

```python
import pytest

from sleeper_dynasty.engine.rookie_cohorts import (
    band, build_cohorts, score_season, verdict,
)

SCORING = {"pass_yd": 0.04, "pass_td": 6.0, "pass_int": -1.0, "rec": 1.0,
           "rec_yd": 0.1, "rec_td": 6.0, "rush_yd": 0.1, "rush_td": 6.0}


def test_bands_are_continuous_with_no_gaps():
    # ECR is FRACTIONAL. Integer bands with gaps once dumped 32 of 389 players
    # into the bottom cohort and manufactured false hits.
    assert band(4.0) == band(1.0)
    assert band(8.7) == band(9.0) - 0 or band(8.7) == band(8.0) + 1  # lands somewhere
    for e in (0.5, 4.0, 4.01, 8.7, 12.5, 18.2, 24.0, 36.9, 60.1, 999.0):
        assert isinstance(band(e), int)
    # Monotone: a worse rank never lands in a better band.
    ranks = [1.0, 4.0, 4.5, 8.0, 8.7, 12.0, 12.5, 18.0, 24.0, 36.0, 60.0, 200.0]
    assert [band(r) for r in ranks] == sorted(band(r) for r in ranks)


def test_score_season_prices_components_with_the_leagues_own_settings():
    stats = {"passing_yards": 4000, "passing_tds": 30, "interceptions": 10}
    # 4000*0.04 + 30*6 - 10 = 160 + 180 - 10
    assert score_season(stats, SCORING) == pytest.approx(330.0)


def test_six_point_pass_tds_score_higher_than_four():
    stats = {"passing_tds": 30}
    assert score_season(stats, {"pass_td": 6.0}) > score_season(stats, {"pass_td": 4.0})


def test_an_absent_component_scores_zero_rather_than_raising():
    assert score_season({"receiving_yards": 100}, {"rec_yd": 0.1}) == pytest.approx(10.0)
    assert score_season({}, SCORING) == 0.0


def _history(n_players: int, per_season_td: float) -> dict:
    return {
        str(i): {"ecr": 2.0, "class": 2021,
                 "seasons": [{"n": 1, "receiving_tds": per_season_td},
                             {"n": 2, "receiving_tds": per_season_td}]}
        for i in range(n_players)
    }


def test_cohorts_are_keyed_by_band_and_seasons_held():
    c = build_cohorts(_history(10, 2.0), {"rec_td": 6.0})
    assert f"{band(2.0)}|1" in c
    assert f"{band(2.0)}|2" in c


def test_cumulative_totals_grow_with_seasons_held():
    c = build_cohorts(_history(10, 2.0), {"rec_td": 6.0})
    assert c[f"{band(2.0)}|2"][1] > c[f"{band(2.0)}|1"][1]


def test_a_thin_cell_is_omitted_rather_than_computed_from_too_few_players():
    # A bar from four players is noise wearing a percentile's authority.
    assert build_cohorts(_history(4, 2.0), {"rec_td": 6.0}) == {}


def test_verdict_reads_against_the_cohorts_own_bars():
    cohorts = {"0|1": (10.0, 50.0, 90.0)}
    assert verdict(100.0, 2.0, 1, cohorts) == "hit"
    assert verdict(50.0, 2.0, 1, cohorts) == "average"
    assert verdict(5.0, 2.0, 1, cohorts) == "bust"


def test_verdict_is_empty_when_the_pick_is_unranked_or_the_cell_is_missing():
    cohorts = {"0|1": (10.0, 50.0, 90.0)}
    assert verdict(100.0, None, 1, cohorts) == ""   # unranked
    assert verdict(None, 2.0, 1, cohorts) == ""     # no production figure
    assert verdict(100.0, 2.0, 9, cohorts) == ""    # no cell for 9 seasons held


def test_verdict_falls_back_to_the_nearest_lower_n_with_coverage():
    # A pick held 3 seasons, with cells only for 1 and 2, is judged at 2 —
    # never invented, never silently compared against year-1 bars.
    cohorts = {"0|1": (10.0, 50.0, 90.0), "0|2": (20.0, 100.0, 180.0)}
    assert verdict(200.0, 2.0, 3, cohorts) == "hit"
    assert verdict(50.0, 2.0, 3, cohorts) == "bust"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_rookie_cohorts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sleeper_dynasty.engine.rookie_cohorts'`

- [ ] **Step 3: Implement**

Create `src/sleeper_dynasty/engine/rookie_cohorts.py`:

```python
"""Hit / Average / Bust, measured against what comparable picks actually scored.

A threshold like "beat your round average by 40 points" is a number somebody
made up. This module has none: a pick is a **Hit** if it beat three-quarters of
the players ranked where it was ranked, a **Bust** if it fell below a quarter of
them, and **Average** in between. Every bar is a percentile of real outcomes.

Two things make the comparison fair:

- **Cohorts are keyed by (ECR band, seasons held)**, and the totals are
  cumulative. A pick held one season is judged against what its peers had
  accumulated after one season, never against their careers.
- **Scoring is the league's own.** The committed history carries raw components,
  not points, because 6-point passing touchdowns move a QB-heavy cohort's bar by
  roughly thirty points against 4-point ones.

Pure. No I/O — callers thread in the history and the league's scoring settings.
"""

from __future__ import annotations

import statistics as st
from collections import defaultdict

# Upper bounds, inclusive. CONTINUOUS — ECR is fractional (8.7, 12.5, 18.2), and
# integer ranges with gaps once dumped 32 of 389 players into the bottom cohort,
# manufacturing false hits for anyone whose rank fell between two bands.
ECR_EDGES: tuple[float, ...] = (4.0, 8.0, 12.0, 18.0, 24.0, 36.0, 60.0)

# nflverse component -> this app's scoring-settings key.
_PRICED: tuple[tuple[str, str], ...] = (
    ("passing_yards", "pass_yd"), ("passing_tds", "pass_td"),
    ("interceptions", "pass_int"), ("passing_2pt_conversions", "pass_2pt"),
    ("rushing_yards", "rush_yd"), ("rushing_tds", "rush_td"),
    ("rushing_2pt_conversions", "rush_2pt"),
    ("receptions", "rec"), ("receiving_yards", "rec_yd"),
    ("receiving_tds", "rec_td"), ("receiving_2pt_conversions", "rec_2pt"),
    ("sack_fumbles_lost", "fum_lost"), ("rushing_fumbles_lost", "fum_lost"),
    ("receiving_fumbles_lost", "fum_lost"),
)


def band(ecr: float) -> int:
    """Which cohort an ECR falls in. Every real number lands in exactly one."""
    for i, hi in enumerate(ECR_EDGES):
        if ecr <= hi:
            return i
    return len(ECR_EDGES)


def score_season(stats: dict, scoring: dict) -> float:
    """Price one season's components with a league's settings.

    A component the league does not price contributes 0 rather than raising —
    a league with no 2-point setting is not an error, it just scores none.
    """
    total = 0.0
    for component, key in _PRICED:
        value = stats.get(component)
        if not value:
            continue
        total += float(value) * float(scoring.get(key) or 0.0)
    return total


def build_cohorts(
    history: dict, scoring: dict, *, min_n: int = 8,
) -> dict[str, tuple[float, float, float]]:
    """``{"band|n": (p25, median, p75)}`` over cumulative totals.

    A cell with fewer than ``min_n`` players is **omitted**, not computed. A
    percentile drawn from four players is noise wearing a percentile's
    authority, and a verdict is not worth issuing from it.
    """
    buckets: dict[str, list[float]] = defaultdict(list)
    for rec in (history or {}).values():
        ecr = rec.get("ecr")
        if ecr is None:
            continue
        b = band(float(ecr))
        cumulative = 0.0
        for season in rec.get("seasons") or []:
            cumulative += score_season(season, scoring)
            buckets[f"{b}|{int(season['n'])}"].append(cumulative)

    out: dict[str, tuple[float, float, float]] = {}
    for key, values in buckets.items():
        if len(values) < min_n:
            continue
        values.sort()
        p25 = values[min(len(values) - 1, int(0.25 * len(values)))]
        p75 = values[min(len(values) - 1, int(0.75 * len(values)))]
        out[key] = (p25, st.median(values), p75)
    return out


def verdict(
    total: float | None,
    ecr: float | None,
    seasons_held: int,
    cohorts: dict[str, tuple[float, float, float]],
) -> str:
    """``"hit" | "average" | "bust"``, or ``""`` when it cannot be judged.

    Falls back ONE step to ``seasons_held - 1`` when the exact cell is missing
    or too thin — a pick held three seasons against cells for one and two is
    judged at two. Never upward (that would measure a three-season total
    against a one-season bar and call nearly everything a hit) and never more
    than one step down either: a pick held nine seasons with coverage only at
    n=1 must read as unjudgeable, not get silently compared to a rookie-year
    bar just because SOME earlier cell happens to exist.
    """
    if total is None or ecr is None or seasons_held < 1:
        return ""
    b = band(float(ecr))
    for n in (int(seasons_held), int(seasons_held) - 1):
        if n < 1:
            break
        cell = cohorts.get(f"{b}|{n}")
        if cell:
            p25, _median, p75 = cell
            return "hit" if total > p75 else "bust" if total < p25 else "average"
    return ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_rookie_cohorts.py -v`
Expected: PASS, 11 tests.

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/rookie_cohorts.py tests/test_rookie_cohorts.py
git commit -m "feat(engine): cohort-measured Hit/Average/Bust, no invented thresholds"
```

---

### Task 4: Seasons held, per pick

The verdict compares owner-gated production against a cohort at the same point in a career, so it needs **how many seasons the owner held the player** — not how many have elapsed.

**Files:**
- Modify: `src/sleeper_dynasty/engine/draft_results.py`
- Test: `tests/test_seasons_held.py`

**Interfaces:**
- Produces: `seasons_held_while_on_roster(pid, uid, *, matchups, roster_to_user_by_league, league_season_by_id) -> int`, and a `"seasons_held"` key on every row from `build_drafted_pick_results`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_seasons_held.py`:

```python
from sleeper_dynasty.engine.draft_results import seasons_held_while_on_roster

MATCHUPS = {
    ("L25", 1, 1): {"players": ["p"], "starters": [], "players_points": {}},
    ("L25", 9, 1): {"players": ["p"], "starters": [], "players_points": {}},
    ("L26", 3, 1): {"players": ["p"], "starters": [], "players_points": {}},
    ("L26", 4, 2): {"players": ["p"], "starters": [], "players_points": {}},
}
R2U = {"L25": {1: "u1"}, "L26": {1: "u1", 2: "u2"}}
SEASONS = {"L25": 2025, "L26": 2026}


def _held(uid):
    return seasons_held_while_on_roster(
        "p", uid, matchups=MATCHUPS, roster_to_user_by_league=R2U,
        league_season_by_id=SEASONS)


def test_counts_distinct_seasons_not_weeks():
    # Two weeks in 2025 and one in 2026 is TWO seasons, not three.
    assert _held("u1") == 2


def test_a_week_on_another_owners_roster_does_not_count():
    assert _held("u2") == 1


def test_a_player_never_held_counts_zero():
    assert seasons_held_while_on_roster(
        "nobody", "u1", matchups=MATCHUPS, roster_to_user_by_league=R2U,
        league_season_by_id=SEASONS) == 0


def test_one_week_is_a_whole_season():
    # A pick traded away in week 2 was still held THAT season; judging him
    # against a zero-season cohort is not possible, and against a full-season
    # cohort is the honest comparison for the time he was there.
    single = {("L25", 2, 1): {"players": ["p"], "starters": [], "players_points": {}}}
    assert seasons_held_while_on_roster(
        "p", "u1", matchups=single, roster_to_user_by_league=R2U,
        league_season_by_id=SEASONS) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_seasons_held.py -v`
Expected: FAIL — `cannot import name 'seasons_held_while_on_roster'`.

- [ ] **Step 3: Implement**

Add to `src/sleeper_dynasty/engine/draft_results.py`, beside `started_games_while_on_roster`:

```python
def seasons_held_while_on_roster(
    pid: str,
    uid: str,
    *,
    matchups: dict[tuple[str, int, int], dict],
    roster_to_user_by_league: dict[str, dict[int, str]],
    league_season_by_id: dict[str, int],
) -> int:
    """How many distinct NFL seasons ``uid`` held ``pid`` for at least one week.

    This is the cohort key, and it is deliberately **seasons held**, not seasons
    elapsed. Production is owner-gated — it stops the day the player is traded
    away — so measuring it against a cohort that kept accruing would brand every
    good pick you ever sold a bust. One week counts as the whole season: the
    alternative is a fractional cohort that does not exist.
    """
    seasons: set[int] = set()
    for (lg, _wk, rid), entry in matchups.items():
        if roster_to_user_by_league.get(lg, {}).get(rid) != uid:
            continue
        if pid not in (entry.get("players") or []):
            continue
        season = league_season_by_id.get(lg)
        if season:
            seasons.add(int(season))
    return len(seasons)
```

Then add a `seasons_fn` parameter to `build_drafted_pick_results` — `seasons_fn: Callable[[str, str], int] | None = None` — and emit on each row:

```python
            "seasons_held": seasons_fn(p.player_id, p.drafter_id) if seasons_fn else 0,
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_seasons_held.py tests/test_draft_results.py tests/test_draft_results_baseline.py tests/test_draft_results_started_field.py -v`
Expected: PASS, existing files unchanged.

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/draft_results.py tests/test_seasons_held.py
git commit -m "feat(engine): seasons-held per pick, the cohort key"
```

---

### Task 5: Wire the verdict through the grader

**Files:**
- Modify: `api/app/services/grader.py`
- Test: `api/tests/test_grader_verdict.py`

**Interfaces:**
- Consumes: `rookie_cohorts.build_cohorts` / `verdict` (Task 3), `seasons_held_while_on_roster` (Task 4).
- Produces: `"verdict"` on every `drafted_picks` row.

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_grader_verdict.py`:

```python
"""The seam, not the whole refresh — `test_grader_service.py` runs ~30s a test."""
import gzip
import json
from importlib.resources import files

from sleeper_dynasty.engine.rookie_cohorts import build_cohorts, verdict


def _history():
    return json.loads(gzip.decompress(
        files("sleeper_dynasty.data").joinpath("rookie_stats.json.gz").read_bytes()))


PPR_6PT = {"pass_yd": 0.04, "pass_td": 6.0, "pass_int": -1.0, "rush_yd": 0.1,
           "rush_td": 6.0, "rec": 1.0, "rec_yd": 0.1, "rec_td": 6.0,
           "fum_lost": -1.0}


def test_the_committed_history_yields_usable_cohorts():
    cohorts = build_cohorts(_history(), PPR_6PT)
    assert len(cohorts) >= 10, "too few cells with coverage to grade a class"


def test_top_band_bars_exceed_bottom_band_bars_at_the_same_n():
    cohorts = build_cohorts(_history(), PPR_6PT)
    top, bottom = cohorts.get("0|1"), cohorts.get("7|1")
    assert top and bottom, "expected both a top and a bottom band at n=1"
    assert top[1] > bottom[1], "a 1.01-calibre cohort must outscore a deep one"


def test_league_scoring_moves_the_bars():
    # The whole reason components are committed instead of points.
    six = build_cohorts(_history(), PPR_6PT)
    four = build_cohorts(_history(), {**PPR_6PT, "pass_td": 4.0})
    assert six != four


def test_a_pick_that_beat_its_cohort_reads_hit():
    cohorts = build_cohorts(_history(), PPR_6PT)
    cell = cohorts.get("0|1")
    assert cell, "expected a top-band year-one cell"
    assert verdict(cell[2] + 1.0, 1.0, 1, cohorts) == "hit"
    assert verdict(cell[0] - 1.0, 1.0, 1, cohorts) == "bust"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && pytest tests/test_grader_verdict.py -v`
Expected: PASS once Tasks 2–3 have landed — these characterise the committed data against the engine. If `test_the_committed_history_yields_usable_cohorts` fails, the extract in Task 2 produced too little and must be regenerated before wiring anything.

- [ ] **Step 3: Wire it**

In `api/app/services/grader.py`, inside the existing best-effort rookie-ECR `try` block (the one whose `except` logs `"rookie ECR fetch skipped; those columns drop"`), after the board resolution loop, build the cohorts once from the packaged history and the league's own `scoring_settings` — the same `latest.scoring_settings` the ADP block already reads. Then thread `seasons_fn` and the resolved cohorts into the `build_drafted_pick_results` call so each row gets its `"verdict"`.

Keep it best-effort: a failure drops the Verdict column, never the refresh. Follow the shape of the rookie-board loop directly above it.

- [ ] **Step 4: Run the backend draft tests**

Run: `cd api && pytest tests/test_grader_verdict.py tests/test_grader_rookie_ecr.py tests/test_draft_board_view.py tests/test_draft_board_metrics.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/app/services/grader.py api/tests/test_grader_verdict.py
git commit -m "feat(api): score each pick against its ECR cohort at refresh"
```

---

### Task 6: Surface the Verdict column

**Files:**
- Modify: `api/app/models/league.py`, `api/app/models/owner.py`
- Modify: `api/app/services/draft_board_view.py`, `api/app/services/owner_view.py`
- Modify: `web/lib/types.ts`, `web/components/DraftBoard.tsx`, `web/components/DraftPicksMobile.tsx`, `web/components/ownerdeepdive/PastPicksTable.tsx`
- Test: `api/tests/test_draft_board_verdict.py`, `web/tests/draft-board.test.tsx`

- [ ] **Step 1: Write the failing backend test**

Create `api/tests/test_draft_board_verdict.py`:

```python
from app.services.draft_board_view import build_draft_board
from tests.helpers import minimal_chain_cache_entry


def pick(**over):
    r = dict(player_id="p1", full_name="A Rookie", position="RB", drafter_id="u1",
             round=1, slot=1, picks_in_round=12, pick_no=1, draft_season=2025,
             production_total=200.0, verdict="hit")
    r.update(over)
    return r


def _board(*picks):
    return build_draft_board(
        minimal_chain_cache_entry(drafted_picks=list(picks)), season=2025)


def test_verdict_reaches_the_response():
    assert _board(pick(), pick(player_id="p2", pick_no=2)).picks[0].verdict == "hit"


def test_a_pre_feature_row_has_an_empty_verdict_not_a_guess():
    b = _board({"player_id": "p1", "full_name": "X", "position": "RB",
                "drafter_id": "u1", "round": 1, "slot": 1, "picks_in_round": 12,
                "pick_no": 1, "draft_season": 2025, "production_total": 0.0},
               {"player_id": "p2", "full_name": "Y", "position": "WR",
                "drafter_id": "u2", "round": 1, "slot": 2, "picks_in_round": 12,
                "pick_no": 2, "draft_season": 2025, "production_total": 0.0})
    assert b.picks[0].verdict == ""


def test_the_board_reports_whether_any_pick_carries_a_verdict():
    # The column is dropped entirely when nothing can be judged — a header over
    # a column of dashes is worse than no column.
    assert _board(pick(), pick(player_id="p2", pick_no=2)).has_verdicts is True
    assert _board(pick(verdict=""), pick(player_id="p2", pick_no=2, verdict="")).has_verdicts is False
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd api && pytest tests/test_draft_board_verdict.py -v`
Expected: FAIL — `DraftBoardPick` has no `verdict`.

- [ ] **Step 3: Add the fields**

`DraftBoardPick` and `DraftPickResult` each gain:

```python
    # "hit" | "average" | "bust" | "" — empty when unranked, keeper, auction,
    # or the cohort cell has too few players. Never a guess.
    verdict: str = ""
```

`DraftBoardResp` gains `has_verdicts: bool = False`, set in `draft_board_view.py` from `any(r.get("verdict") for r in rows)`. Both views read `str(r.get("verdict") or "")`.

- [ ] **Step 4: Render it**

Add a **Verdict** column to the board's pick rows (between Slot +/- and Total Points) and to `PastPicksTable`, gated on `has_verdicts`. Extend each file's literal grid constants — one per combination, never interpolated.

Render as coloured mono text following `PastPicksTable`'s existing status treatment: Hit `text-pos-strong`, Bust `text-neg-strong`, Average `text-dim`. **The word carries the meaning; the colour only restates it** — that is the same licence the `Now` column runs on.

Add the mobile counterpart in `DraftPicksMobile`'s `PickCard`.

- [ ] **Step 5: Run both suites and re-check the width**

```bash
cd api && pytest tests/test_draft_board_verdict.py tests/test_draft_board_view.py -v && cd ..
cd web && npx vitest --config tests/vitest.config.ts run && cd ..
python3 -c "
t=[30,120,46,50,66,60,56,40]   # + Verdict (66)
need=sum(t)+(len(t)+1)*10+28
print('needs',need,'before Player; at 870vw Player gets',870-48-2-need,'px')
assert 870-48-2-need > 120, 'Verdict pushed Player under 120px — revisit the column budget'
print('OK')
"
```

- [ ] **Step 6: Commit**

```bash
git add api/app/models/ api/app/services/ web/lib/types.ts web/components/ api/tests/test_draft_board_verdict.py web/tests/draft-board.test.tsx
git commit -m "feat: Hit/Average/Bust on the board and the owner Draft tab"
```

---

### Task 7: Full-suite verification

- [ ] **Step 1: Run everything**

```bash
pytest tests/
cd api && pytest -v && cd ..
cd web && npx vitest --config tests/vitest.config.ts run && cd ..
```

- [ ] **Step 2: Confirm the packaged data survives the image**

```bash
docker build -f api/Dockerfile -t trade-grader-api:local .
docker run --rm trade-grader-api:local python -c "
from importlib.resources import files
for name in ('rookie_ecr.json.gz', 'rookie_stats.json.gz'):
    b = files('sleeper_dynasty.data').joinpath(name).read_bytes()
    print(name, len(b), 'bytes'); assert len(b) > 10_000
print('both packaged files reach the image')
"
```

**If this fails the feature is silently dead in production** while working perfectly in development — the same failure the `package-data` glob exists to prevent.

- [ ] **Step 3: Do not push**

PR #10 is open; updating it is the repository owner's call.

---

## Self-Review

**Spec coverage.** Column budget → Task 1. Committed components rather than points → Task 2, asserted by `test_no_points_are_committed`. Continuous ECR bands → Task 3, asserted by the monotone test. League-scored bars → Task 3 + Task 5's `test_league_scoring_moves_the_bars`. Owner-gated window (`N = seasons held`) → Task 4. Thin cells omitted, fallback exactly one step to `n - 1`, never further and never upward → Task 3. Empty verdict for unranked/keeper/auction → Tasks 3 and 6. No `SCHEMA_VERSION` bump → additive row keys with `.get()` defaults, proven by Task 6's pre-feature test. Verdict never feeds Franchise Rating → no task touches `draft_signals.py` or `gm_rating.py`.

**Deferred to phase 4/5:** the grouped sortable header (blocked on `GroupedHead` reaching `.design/`), per-column tooltips, the nav entry, needs reconstruction.

**Type consistency.** `verdict` is the engine function name, the row key, and both model field names — deliberate, so provenance is unambiguous. `seasons_held` is spelled identically in `draft_results.py` and `rookie_cohorts.verdict`'s parameter. `build_cohorts`'s `"{band}|{n}"` key format is used identically in Task 3's tests and Task 5's.

**One accepted imprecision.** `verdict` falls back **exactly one step**, to `n - 1`, and returns no verdict if that cell is also missing — so a pick held five seasons with a cell only at four is judged at four, and a pick held five seasons with coverage only at three or below is unjudgeable. The comparison is an owner-gated cumulative total over N seasons against a cohort's cumulative total over the same N; falling back k steps compares an N-season total against an (N−k)-season bar, and the resulting inflation toward *Hit* grows with k. At k=1 it is modest and is often the only alternative to no verdict at all. At k=8 — a pick held nine seasons judged against a rookie-year bar — it would make almost anything a Hit, which is why the walk is bounded to one step rather than continuing down to the nearest coverage. The alternative — refusing to judge whenever the exact cell is thin — loses more than it protects, and coverage thins only at high `n` where few picks survive. Stated here so it is a known, bounded reading rather than a discovered surprise.
