> _Historical doc — paths/names have changed. Repo is now `Code Apps/public-dynasty` (GitHub `tkeefe66/public-dynasty-app`), Railway project **shimmering-nature**, live at https://ffbdynasty.com. Ignore stale refs to `sleeper-dynasty` / `sleeper-trade-grader` / `web-production-f949`._

# One-Sided Production Metrics (A-backend) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make the four production metrics (Total / Regular / Playoff / Toilet) **received-only** instead of `received − given` swings, rename the now-misnamed "swing" fields to honest `production_*` names through engine → cache → GM Rating → API → web, and keep all suites green.

**Architecture:** Two orthogonal changes done in three phases. **Phase 1 (semantic):** drop the phantom `given` term in `grade_hindsight_production`; no renames; only engine-computing tests change values; bump the cache schema. **Phase 2 (backend rename):** pure mechanical field/dict-key rename across engine + services + API models + backend tests (no behavior change). **Phase 3 (web rename):** mechanical TS rename + a URL-column backward-compat alias. Trade Value stays a swing throughout.

**Tech Stack:** Python (pytest, dataclasses, Pydantic v2, FastAPI), TypeScript/React (vitest).

**Spec:** `docs/superpowers/specs/2026-06-09-one-sided-production-metrics-design.md`

## Canonical rename table (used by Phases 2 & 3)

Short form everywhere (unifies the spec's mixed naming). Engine serialized grade-dict keys come from `asdict(TradeGrade)`, so renaming the dataclass fields renames those keys too.

| Old name(s) | New name | Layer |
| --- | --- | --- |
| `hindsight_production_swing` | `production_total` | TradeGrade field + grade-dict key + TradeSideView |
| `hindsight_started_regular_swing` | `production_regular` | TradeGrade field + grade-dict key + TradeSideView |
| `hindsight_started_playoff_swing` | `production_playoff` | TradeGrade field + grade-dict key + TradeSideView |
| `hindsight_started_toilet_swing` | `production_toilet` | TradeGrade field + grade-dict key + TradeSideView |
| `net_production` | `production_total` | OwnerTradeRecord, StandingRow, SeasonArc, aggregation/owner_view dicts |
| `net_production_started_regular` | `production_regular` | OwnerTradeRecord, StandingRow, SeasonArc, agg/owner_view dicts |
| `net_production_started_playoff` | `production_playoff` | (same) |
| `net_production_started_toilet` | `production_toilet` | (same) |
| `net_regular` | `production_regular` | GMRow (leaderboard) |
| `net_playoff` | `production_playoff` | GMRow (leaderboard) |
| `net_toilet` | `production_toilet` | GMRow (leaderboard) |

**Never rename (Trade Value is still a swing):** `snapshot_value_swing`, `snapshot_ktc_swing`, `net_ktc`, `net_ktc_at_trade`, `net_ktc_aged`, `net_ktc_today_subset`, `at_trade_ktc_swing`, `aged_ktc_swing`.

**Test commands** (run from the right dir; single commands, no redirects):
- Engine: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && .venv/bin/python -m pytest tests/ -q`
- API: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/api" && .venv/bin/python -m pytest -q`
- Web: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/web" && npm test`

Use `git -C "/Users/tomkeefe/Code Apps/sleeper-dynasty"` for git.

---

# PHASE 1 — Semantic change (received-only)

## Task 1: `grade_hindsight_production` → received-only

**Files:**
- Modify: `src/sleeper_dynasty/engine/trade_grader.py` (`grade_hindsight_production`, ~lines 120-219)
- Modify: `api/app/services/chain_cache.py:11` (`SCHEMA_VERSION`)
- Test: `tests/test_trade_grader.py`

- [ ] **Step 1: Write the failing regression test** (append to `tests/test_trade_grader.py`)

This is the bug that motivated the change: a player you trade away scores in the
*other* team's toilet bowl; it must NOT affect your Toilet metric. Build the test from
the existing fixtures in that file (mirror how other `grade_trade`/`grade_hindsight_production`
tests set up `ResolvedTrade` + `matchups` + `phase_by_lwr`). The assertion:

```python
def test_production_is_received_only_not_swing():
    # A trade where the GIVEN-away player scores points (in any phase) post-trade.
    # Received-only => the given player's production does NOT subtract from the
    # trader's metric. Build rt with side u_a giving player "G" and receiving "R".
    # matchups: R scores 50 (started, regular) on u_a's roster; G scores 40
    # (started, regular) on the OTHER roster post-trade.
    # Expect u_a regular production == 50 (received only), NOT 50 - 40 == 10.
    rt, matchups, roster_to_user_by_league, phase_by_lwr, pws = _build_received_only_case()
    swings = grade_hindsight_production(
        rt, matchups, roster_to_user_by_league,
        starters_only=True, phase_filter="regular",
        phase_by_lwr=phase_by_lwr, playoff_week_start_by_league=pws,
    )
    assert swings["u_a"] == 50.0   # received only; given-away 40 ignored
```

Write `_build_received_only_case()` as a local helper in the test using the same dict
shapes the other tests in this file already use (look at an existing
`grade_hindsight_production` test for the exact `matchups` entry keys:
`team_points`/`opponent_points`/`starters`/`players`/`players_points`). The given-away
player G must be on a DIFFERENT roster than u_a post-trade so the old phantom term would
have counted it.

- [ ] **Step 2: Run to verify it fails**

Run the engine test command filtered: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && .venv/bin/python -m pytest tests/test_trade_grader.py::test_production_is_received_only_not_swing -q`
Expected: FAIL — currently returns `10.0` (50 − 40 phantom).

- [ ] **Step 3: Make production received-only**

In `grade_hindsight_production`, drop the `given`/phantom term. Change the per-uid loop
(~lines 204-214) from:

```python
    swings: dict[str, float] = {}
    for uid, side in rt.sides.items():
        received = 0.0
        for a in side.received:
            if isinstance(a, PlayerAsset):
                received += _received_points(a.player_id, uid)
        given = 0.0
        for a in side.given:
            if isinstance(a, PlayerAsset):
                given += _phantom_points(a.player_id)
        swings[uid] = received - given
        log.debug(
            "Hindsight swing for %s: received=%.1f given_phantom=%.1f swing=%.1f",
            uid, received, given, swings[uid],
        )
    return swings
```

to:

```python
    totals: dict[str, float] = {}
    for uid, side in rt.sides.items():
        received = 0.0
        for a in side.received:
            if isinstance(a, PlayerAsset):
                received += _received_points(a.player_id, uid)
        totals[uid] = received
        log.debug("Received-only production for %s: %.1f", uid, received)
    return totals
```

Delete the now-unused `_phantom_points` inner helper (~lines 191-202). Update the
function docstring: replace the `received − given_phantom` Returns line with
"``user_id -> received-only production`` (points scored by received assets while on the
acquiring roster; no phantom subtraction)."

- [ ] **Step 4: Bump the cache schema**

`api/app/services/chain_cache.py:11`: change `SCHEMA_VERSION = 2` to `SCHEMA_VERSION = 3`.
(The existing guard at line 63 re-grades cached entries on mismatch — values were swings,
now received-only.)

- [ ] **Step 5: Run engine tests, fix value expectations**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && .venv/bin/python -m pytest tests/ -q`
Other tests in `test_trade_grader.py` that asserted swing values (where a given-away
player scored) will now show received-only values. For each failure, recompute the
expected value as received-only (drop the given side) and update the assertion. Tests
where no given-away player scored are unaffected. Confirm the suite is green.

- [ ] **Step 6: Commit**

```bash
git -C "/Users/tomkeefe/Code Apps/sleeper-dynasty" add src/sleeper_dynasty/engine/trade_grader.py api/app/services/chain_cache.py tests/test_trade_grader.py
git -C "/Users/tomkeefe/Code Apps/sleeper-dynasty" commit -m "feat(engine): production metrics are received-only (drop phantom subtraction)

Total/Regular/Playoff/Toilet now count only points scored by received assets
while on the acquiring roster, tagged with the acquirer's bracket phase. Trade
Value stays a swing. Cache SCHEMA_VERSION 2->3 forces a one-time re-grade."
```

**Note:** API + web tests inject grade dicts as fixtures (not computed), so they still
pass after Phase 1 — their fixture numbers are now interpreted as received-only values,
which is fine. Field names are still the old swing names until Phase 2.

---

# PHASE 2 — Backend rename (mechanical, no behavior change)

Each task renames a coherent slice and ends green. Because renaming `TradeGrade` fields
changes the `asdict` grade-dict keys, the engine-field rename and all grade-dict-key
readers + fixtures must land together (Task 2). Then the API-model/response layer
(Task 3).

## Task 2: Rename engine grade fields + all grade-dict-key readers/fixtures

**Files (rename per the canonical table):**
- `src/sleeper_dynasty/models/trade.py` — `TradeGrade` fields (123-126), `OwnerTradeRecord` fields (137-140)
- `src/sleeper_dynasty/engine/trade_grader.py` — `grade_trade` TradeGrade kwargs (266-275), `aggregate_owner_records` (298-301)
- `src/sleeper_dynasty/engine/trade_story.py` — `.get("hindsight_*")` reads (207, 212, 217)
- `src/sleeper_dynasty/output/google_sheets.py` — attr reads (268-274) + OwnerTradeRecord attrs (312-315)
- `api/app/services/trade_view.py` — `.get("hindsight_*")` grade-dict reads (65-75)
- `api/app/services/aggregations.py` — `.get("hindsight_*")` grade reads (78-88, 98, 191); these feed `row[...]` keys renamed in Task 3 — for THIS task only change the `.get("hindsight_*")` engine-key reads
- `api/app/services/owner_view.py` — `.get("hindsight_*")` grade reads (36-41)
- Backend test fixtures that write grade dicts with old keys: `api/tests/test_trade.py` (35-38, 96), `api/tests/test_owner.py` (29-32, 112), `api/tests/test_aggregations.py` (45, 62), `api/tests/test_leaderboard.py` (15-18), `api/tests/test_grader_service.py` (337 + comments 332-335), `api/tests/test_refresh_rating_snapshot.py` (24-27)

- [ ] **Step 1: Rename the four grade-dict keys everywhere**

Apply, as whole-identifier replacements across the files above:
`hindsight_production_swing`→`production_total`, `hindsight_started_regular_swing`→`production_regular`,
`hindsight_started_playoff_swing`→`production_playoff`, `hindsight_started_toilet_swing`→`production_toilet`.
This covers TradeGrade dataclass fields, the `asdict` keys, every `.get("...")` read, and every test fixture key.

- [ ] **Step 2: Rename the OwnerTradeRecord fields**

`net_production`→`production_total`, `net_production_started_regular`→`production_regular`,
`net_production_started_playoff`→`production_playoff`, `net_production_started_toilet`→`production_toilet`
in `models/trade.py` (OwnerTradeRecord), `trade_grader.py::aggregate_owner_records`, and
`google_sheets.py::write_owner_standings`. (These are the ENGINE rollup; the API has its own dicts — Task 3.)

- [ ] **Step 3: Run engine + API suites**

Run engine: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && .venv/bin/python -m pytest tests/ -q` → green.
Run API: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/api" && .venv/bin/python -m pytest -q`.
At this point the API aggregation/owner row dicts still use `net_production*` keys internally
(Task 3 renames those); the `.get("production_*")` reads from grades now match the renamed
engine keys. Some API tests assert old API response field names — those are renamed in Task 3.
If API is red ONLY due to Task-3-owned names (response field assertions, `row["net_production*"]`),
that is expected; proceed to Task 3 and run API green there. If engine is red, fix here.

- [ ] **Step 4: Commit**

```bash
git -C "/Users/tomkeefe/Code Apps/sleeper-dynasty" add -A
git -C "/Users/tomkeefe/Code Apps/sleeper-dynasty" commit -m "refactor: rename engine grade/rollup production fields (swing->received-only names)"
```

## Task 3: Rename API model fields + service rollup dict keys + API tests

**Files (rename per the canonical table):**
- `api/app/models/trade.py` — `TradeSideView` fields (25-28) → `production_total/regular/playoff/toilet`
- `api/app/models/owner.py` — `SeasonArc` fields (11-14)
- `api/app/models/league.py` — `StandingRow` fields (43-46)
- `api/app/models/leaderboard.py` — `GMRow` fields (26-28): `net_regular/playoff/toilet` → `production_regular/playoff/toilet`
- `api/app/services/trade_view.py` — `TradeSideView` kwargs (65-75): `hindsight_*_swing=` → `production_*=`
- `api/app/services/aggregations.py` — `_blank()` keys (60-63), accumulators (78-88), `_records` reads (222-232), `StandingRow` kwargs (256-259): `net_production*` → `production_*`
- `api/app/services/owner_view.py` — `by_season` dict keys (52-62), `SeasonArc` kwargs (95-98): `net_production*` → `production_*`
- `api/app/services/leaderboard.py` — `owner_metrics` reads (32-34), sort key (61), `GMRow` kwargs (89-91): `net_production_started_*` reads → `production_*`; `net_regular/playoff/toilet=` kwargs → `production_*=`
- API tests: `test_trade.py` (62-64 assertions), `test_models.py` (38-41, 76, 99-102 kwargs), `test_owner.py` (78-80 assertions), `test_leaderboard.py` (109-111 inline dict), `test_aggregations.py` (any production assertions)

- [ ] **Step 1: Rename API model fields + all service dict keys/kwargs**

Apply whole-identifier replacements: `net_production`→`production_total`,
`net_production_started_regular`→`production_regular`, `net_production_started_playoff`→`production_playoff`,
`net_production_started_toilet`→`production_toilet`, `net_regular`→`production_regular`,
`net_playoff`→`production_playoff`, `net_toilet`→`production_toilet`, and the
`TradeSideView` kwargs `hindsight_production_swing=`→`production_total=`,
`hindsight_started_regular_swing=`→`production_regular=`, etc. Update the API test
assertions/fixtures to the new field names.

- [ ] **Step 2: Run API suite green**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/api" && .venv/bin/python -m pytest -q` → all pass.
Then re-run engine to confirm no regression: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && .venv/bin/python -m pytest tests/ -q`.

- [ ] **Step 3: Commit**

```bash
git -C "/Users/tomkeefe/Code Apps/sleeper-dynasty" add -A
git -C "/Users/tomkeefe/Code Apps/sleeper-dynasty" commit -m "refactor: rename API production fields to received-only semantics"
```

---

# PHASE 3 — Web rename (mechanical + URL alias)

## Task 4: Rename web TS fields + tests, with URL backward-compat alias

**Files:**
- `web/lib/types.ts` — `StandingRow` (46-49), `GMRow` (120-122), `SeasonArc` (136-139), `TradeSideView` (183-186)
- `web/components/CareerArc.tsx` — `LensKey` union (6-8), `LENSES` keys (12-15)
- `web/components/StandingsTable.tsx` — `COLS` keys (29,33,37,41), row property accesses (147-157)
- `web/components/TradeSidePanel.tsx` — property accesses (28-31)
- `web/lib/og-card-data.ts` — property accesses (59-60)
- `web/lib/standings-filter.ts` — `NUMERIC_COLUMNS` set members (10-11)
- `web/lib/url-state.ts` — add the decode alias (see Step 2)
- Web tests: `Leaderboard.test.tsx` (25-27), `og-card-data.test.ts` (11,14,84), `OwnerDeepDive.test.tsx` (10-11,20-21), `standings-filter.test.ts` (6-9,15), `StandingsTable.test.tsx` (16-17), `TradeSidePanel.test.tsx` (8-10), `url-state.test.ts` (14,19)

- [ ] **Step 1: Rename all TS interface fields + property accesses + fixtures**

Whole-identifier replacements per the canonical table across all web files above
(snake_case, no camelCase variants exist). This includes the `COLS`/`LENSES`/`NUMERIC_COLUMNS`
string ids (typed as `keyof StandingRow`/`keyof SeasonArc`, so they must track the field rename).

- [ ] **Step 2: Add URL backward-compat alias so old shared/bookmarked URLs still work**

Old URLs encode sort/filter columns as `sort=net_production.asc` or
`filter[net_production][gte]=50`. After renaming the column ids, decode must map the old
ids to the new ones. In `web/lib/url-state.ts`, in the decode path (where the `sort`
column and `filter` keys are parsed), apply this alias map to incoming column strings:

```ts
const LEGACY_COLUMN_ALIASES: Record<string, string> = {
  net_production: "production_total",
  net_production_started_regular: "production_regular",
  net_production_started_playoff: "production_playoff",
  net_production_started_toilet: "production_toilet",
};
const canonicalColumn = (c: string): string => LEGACY_COLUMN_ALIASES[c] ?? c;
```

Apply `canonicalColumn(...)` to the decoded sort column and to each decoded filter
column key. Encoding always uses the new names. (Do not alias `net_ktc` — unchanged.)

- [ ] **Step 3: Add an alias test** (to `web/tests/url-state.test.ts`)

```ts
it("decodes legacy production sort column to new name", () => {
  const state = decodeDashboardState(new URLSearchParams("sort=net_production.asc"));
  expect(state.sort).toEqual({ column: "production_total", direction: "asc" });
});
```

(Use the actual decode function name/signature from `url-state.ts`.)

- [ ] **Step 4: Run the web suite green**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/web" && npm test`
Also typecheck if the project has it: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/web" && npm run build` (or `npx tsc --noEmit`) to catch `keyof` mismatches.

- [ ] **Step 5: Commit**

```bash
git -C "/Users/tomkeefe/Code Apps/sleeper-dynasty" add -A
git -C "/Users/tomkeefe/Code Apps/sleeper-dynasty" commit -m "refactor(web): rename production fields + legacy URL column alias"
```

---

## Final verification

- [ ] Engine: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && .venv/bin/python -m pytest tests/ -q`
- [ ] API: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/api" && .venv/bin/python -m pytest -q`
- [ ] Web: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/web" && npm test`
- [ ] Grep for stragglers (should return nothing but unchanged `*ktc*` names):
      `git -C "/Users/tomkeefe/Code Apps/sleeper-dynasty" grep -nE "hindsight_(production|started)|net_production|net_(regular|playoff|toilet)\b" -- src api web ':!docs'`
- [ ] Sanity: the trade detail response now returns `production_total/regular/playoff/toilet`
      as received-only values (two positive tallies per side), and the GM leaderboard
      recomputes from received-only inputs.

## Self-review notes (addressed)

- **Semantic vs rename separated** — Phase 1 changes behavior with names intact (only
  engine-computing tests shift values); Phases 2-3 are pure renames. Each phase ends green.
- **`asdict` coupling** — renaming `TradeGrade` fields renames the serialized grade-dict
  keys, so Task 2 renames the dataclass fields AND every `.get("...")` reader AND every
  test fixture key together (one commit).
- **Trade Value untouched** — all `*ktc*` / `snapshot_value_swing` names preserved (it's
  still a swing); the final grep guards this.
- **URL persistence** — legacy sort/filter column ids aliased on decode so shared URLs
  survive the rename (Task 4 Step 2-3).
- **Out of scope (B):** toilet weight/sign and the outcomes-dominant GM redesign;
  `gm_rating.py::WEIGHTS` is untouched — only its inputs change (now received-only).
- **No data migration** — cache schema bump re-grades; cold-start contract handles it.
