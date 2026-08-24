> _Historical doc — paths/names have changed. Repo is now `Code Apps/public-dynasty` (GitHub `tkeefe66/public-dynasty-app`), Railway project **shimmering-nature**, live at https://ffbdynasty.com. Ignore stale refs to `sleeper-dynasty` / `sleeper-trade-grader` / `web-production-f949`._

# Season Records Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Record" column to the Owner Rankings table showing per-season W-L + finish for historical tabs, career W-L + best finish for all-time, and current W-L + rank for the current season.

**Architecture:** Compute per-season records (W-L, rank, champion/runner-up/playoffs) inside `compute_rating_signals` where `standings_by_season` and `brackets_by_season` are already available. Store as `season_records` on `ChainCacheEntry`. `build_dashboard()` formats the strings and attaches them to `StandingRow`. Frontend adds a "Record" column to both table views.

**Tech Stack:** Python/FastAPI, Next.js 14/TypeScript/Tailwind, pytest

**Test commands:**
- Engine + API: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && make test-api`
- Frontend: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/web" && npm run test -- --run`

---

## Data Shape

```python
# season_records[str(year)][uid] = {
#   "wins": int, "losses": int, "ties": int,
#   "rank": int,          # 1-based (1 = first place)
#   "total_teams": int,
#   "champion": bool,
#   "runner_up": bool,
#   "made_playoffs": bool,
# }
```

## Display Format

| Context | `season_record` | `best_finish` |
|---|---|---|
| Historical year | `"8-5"` | `"3rd"` |
| Current season (in play) | `"3-2"` | `"4th"` |
| Current season (no data) | `"—"` | `"—"` |
| All time | `"32-24"` (cumulative) | `"Won 2×"` / `"Runner-up 1×"` / `"Playoffs 3/4"` / `"—"` |

---

## File Map

| File | Change |
|---|---|
| `api/app/services/chain_cache.py` | Add `season_records` field |
| `api/app/services/rating_signals.py` | Compute `season_records`; change return to 4-tuple |
| `api/app/services/grader.py` | Unpack 4-tuple; store `season_records` on entry |
| `api/tests/test_rating_signals.py` | Fix 3-tuple → 4-tuple unpacking |
| `api/tests/test_rating_signals_draft.py` | Fix 3-tuple → 4-tuple unpacking |
| `api/tests/test_aggregations.py` | Add `season_records` to fixture; add record tests |
| `api/app/models/league.py` | Add `season_record` and `best_finish` to `StandingRow` |
| `api/app/services/aggregations.py` | Add `_ordinal()`, `_fmt_record()`; populate new fields |
| `web/lib/types.ts` | Add fields to `StandingRow` |
| `web/components/StandingsTable.tsx` | Add Record column; update grids + group header spacers |

---

## Task 1: Add `season_records` field to `ChainCacheEntry`

**Files:**
- Modify: `api/app/services/chain_cache.py`

- [ ] **Step 1: Add field after `draft_skill_by_season`**

```python
    # str(year) -> {uid -> season record dict}
    # Keys per uid: wins, losses, ties, rank (1-based), total_teams, champion, runner_up, made_playoffs
    season_records: dict[str, dict[str, dict]] = field(default_factory=dict)
```

No schema version bump needed (default_factory=dict → old caches get empty dict gracefully).

- [ ] **Step 2: Verify tests still pass**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && make test-api 2>&1 | tail -3
```
Expected: 186 passed.

- [ ] **Step 3: Commit**

```bash
git add api/app/services/chain_cache.py
git commit -m "feat(cache): add season_records field to ChainCacheEntry"
```

---

## Task 2: Compute `season_records` in `rating_signals.py`

**Files:**
- Modify: `api/app/services/rating_signals.py`
- Modify: `api/tests/test_rating_signals.py`
- Modify: `api/tests/test_rating_signals_draft.py`

- [ ] **Step 1: Add `season_records` computation before the return statement**

In `api/app/services/rating_signals.py`, add after the `season_draft_skill` block and before `return`:

```python
    # Per-season W-L records + playoff finishes (for the Record dashboard column).
    season_records: dict[str, dict[str, dict]] = {}
    for season, rows in standings_by_season.items():
        total_teams = len(rows)
        season_brackets = brackets_by_season.get(season, {})
        season_records[str(season)] = {}
        for row in rows:
            uid = row.owner_id
            br = season_brackets.get(uid, {})
            season_records[str(season)][uid] = {
                "wins": row.wins,
                "losses": row.losses,
                "ties": row.ties,
                "rank": row.rank + 1,          # standings.py is 0-indexed
                "total_teams": total_teams,
                "champion": bool(br.get("champion")),
                "runner_up": bool(br.get("runner_up")),
                "made_playoffs": int(br.get("rounds_won") or 0) > 0,
            }

    return osig, olsig, season_draft_skill, season_records
```

- [ ] **Step 2: Fix `test_rating_signals.py` 3-tuple unpacking**

In `api/tests/test_rating_signals.py`, find:
```python
    osig, olsig = compute_rating_signals(supporting, current_holders)
```
Change to:
```python
    osig, olsig, _, _ = compute_rating_signals(supporting, current_holders)
```

- [ ] **Step 3: Fix `test_rating_signals_draft.py` 3-tuple unpacking**

In `api/tests/test_rating_signals_draft.py`, find all lines matching `_, outlook = compute_rating_signals(...)` and change each to:
```python
    _, outlook, _, _ = compute_rating_signals(...)
```
(There are 4 such lines — update all of them.)

- [ ] **Step 4: Run tests**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && make test-api 2>&1 | tail -3
```
Expected: 186 passed.

- [ ] **Step 5: Commit**

```bash
git add api/app/services/rating_signals.py api/tests/test_rating_signals.py api/tests/test_rating_signals_draft.py
git commit -m "feat(signals): compute season_records (W-L + finish) per owner; return as 4th value"
```

---

## Task 3: Store `season_records` in `grader.py`

**Files:**
- Modify: `api/app/services/grader.py`

- [ ] **Step 1: Update 3-tuple unpack to 4-tuple**

Find in `api/app/services/grader.py`:
```python
        outcome_signals, outlook_signals, draft_skill_by_season = {}, {}, {}
        try:
            from app.services.rating_signals import compute_rating_signals
            outcome_signals, outlook_signals, draft_skill_by_season = compute_rating_signals(
```

Change to:
```python
        outcome_signals, outlook_signals, draft_skill_by_season, season_records_from_signals = {}, {}, {}, {}
        try:
            from app.services.rating_signals import compute_rating_signals
            outcome_signals, outlook_signals, draft_skill_by_season, season_records_from_signals = compute_rating_signals(
```

- [ ] **Step 2: Store on entry**

Find the `ChainCacheEntry(...)` constructor call (around line 337). Find the line with `draft_skill_by_season=draft_skill_by_season,` and add immediately after:

```python
            season_records=season_records_from_signals,
```

- [ ] **Step 3: Run tests**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && make test-api 2>&1 | tail -3
```
Expected: 186 passed.

- [ ] **Step 4: Commit**

```bash
git add api/app/services/grader.py
git commit -m "feat(grader): store season_records on ChainCacheEntry from rating signals"
```

---

## Task 4: Add `season_record` and `best_finish` to `StandingRow`

**Files:**
- Modify: `api/app/models/league.py`

- [ ] **Step 1: Add two new optional fields after `draft_capital_value`**

```python
    draft_capital_value: float = 0.0
    season_record: str | None = None   # "8-5" (year view) or "32-24" (all-time)
    best_finish: str | None = None     # "3rd" (year view) or "Won 2×" (all-time)
```

- [ ] **Step 2: Run tests**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && make test-api 2>&1 | tail -3
```
Expected: 186 passed.

- [ ] **Step 3: Commit**

```bash
git add api/app/models/league.py
git commit -m "feat(models): add season_record and best_finish to StandingRow"
```

---

## Task 5: Populate record fields in `build_dashboard()`

**Files:**
- Modify: `api/app/services/aggregations.py`
- Modify: `api/tests/test_aggregations.py`

- [ ] **Step 1: Add `season_records` to `_sample_entry()` fixture in `test_aggregations.py`**

Find `_sample_entry()` and add `season_records` after `draft_skill_by_season`:

```python
season_records={
    "2024": {
        "u_alice": {"wins": 9, "losses": 4, "ties": 0, "rank": 1, "total_teams": 2,
                    "champion": True, "runner_up": False, "made_playoffs": True},
        "u_bob":   {"wins": 4, "losses": 9, "ties": 0, "rank": 2, "total_teams": 2,
                    "champion": False, "runner_up": True, "made_playoffs": True},
    },
    "2026": {
        "u_alice": {"wins": 2, "losses": 1, "ties": 0, "rank": 1, "total_teams": 2,
                    "champion": False, "runner_up": False, "made_playoffs": False},
        "u_bob":   {"wins": 1, "losses": 2, "ties": 0, "rank": 2, "total_teams": 2,
                    "champion": False, "runner_up": False, "made_playoffs": False},
    },
},
```

- [ ] **Step 2: Write failing tests**

Add to `api/tests/test_aggregations.py`:

```python
def test_standing_row_season_record_historical_year():
    e = _sample_entry()
    resp = build_dashboard(e, year=2024, lens="ktc")
    alice = next(r for r in resp.standings if r.user_id == "u_alice")
    assert alice.season_record == "9-4"
    assert alice.best_finish == "1st"


def test_standing_row_season_record_all_time():
    e = _sample_entry()
    resp = build_dashboard(e, year="all", lens="ktc")
    alice = next(r for r in resp.standings if r.user_id == "u_alice")
    # career: 9+2 = 11 wins, 4+1 = 5 losses across 2024+2026
    assert alice.season_record == "11-5"
    # alice won championship in 2024
    assert alice.best_finish == "Won 1×"


def test_standing_row_no_record_when_season_missing():
    e = _sample_entry()
    resp = build_dashboard(e, year=2025, lens="ktc")  # no 2025 in season_records
    for row in resp.standings:
        assert row.season_record is None
        assert row.best_finish is None
```

- [ ] **Step 3: Run to confirm failure**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && make test-api 2>&1 | grep -E "FAILED|season_record" | head -5
```
Expected: 3 failures on the new tests.

- [ ] **Step 4: Add helper functions and populate fields in `aggregations.py`**

Add these helpers near the top of `aggregations.py` (after imports):

```python
def _ordinal(n: int) -> str:
    """1 → '1st', 2 → '2nd', 3 → '3rd', 4+ → 'Nth'."""
    if 11 <= (n % 100) <= 13:
        return f"{n}th"
    return f"{n}{('th', 'st', 'nd', 'rd', 'th', 'th', 'th', 'th', 'th', 'th')[n % 10]}"


def _fmt_record(uid: str, year: Year, season_records: dict) -> tuple[str | None, str | None]:
    """Return (season_record, best_finish) strings for one owner.

    Returns (None, None) when no record data is available for the requested year.
    """
    sr = season_records or {}

    if year == "all":
        # Career: sum W-L across all seasons; derive best finish from per-season flags.
        if not sr:
            return None, None
        total_w = total_l = total_t = champs = finals = playoffs = seasons = 0
        for yr_data in sr.values():
            rec = (yr_data or {}).get(uid) or {}
            if not rec:
                continue
            total_w += rec.get("wins", 0)
            total_l += rec.get("losses", 0)
            total_t += rec.get("ties", 0)
            seasons += 1
            if rec.get("champion"):
                champs += 1
            elif rec.get("runner_up"):
                finals += 1
            if rec.get("made_playoffs"):
                playoffs += 1
        if seasons == 0:
            return None, None
        record_str = f"{total_w}-{total_l}" if total_t == 0 else f"{total_w}-{total_l}-{total_t}"
        if champs > 0:
            finish_str = f"Won {champs}×" if champs > 1 else "Won 1×"
        elif finals > 0:
            finish_str = f"Runner-up {finals}×" if finals > 1 else "Runner-up"
        elif playoffs > 0:
            finish_str = f"Playoffs {playoffs}/{seasons}"
        else:
            finish_str = "—"
        return record_str, finish_str

    else:  # specific year
        yr_data = sr.get(str(year)) or {}
        rec = yr_data.get(uid) or {}
        if not rec:
            return None, None
        w, l, t = rec.get("wins", 0), rec.get("losses", 0), rec.get("ties", 0)
        rank = rec.get("rank", 0)
        record_str = f"{w}-{l}" if t == 0 else f"{w}-{l}-{t}"
        finish_str = _ordinal(rank) if rank > 0 else "—"
        # Show "—" for seasons with no games played yet (0-0 record)
        if w == 0 and l == 0 and t == 0:
            return "—", "—"
        return record_str, finish_str
```

Then in `build_dashboard()`, inside the `StandingRow(...)` constructor, add after `draft_capital_value=...`:

```python
            **dict(zip(
                ("season_record", "best_finish"),
                _fmt_record(r["user_id"], year, entry.season_records or {}),
            )),
```

Wait, that's awkward. Better: compute it separately:

```python
    season_recs = entry.season_records or {}
```

Then inside the standings loop, before `StandingRow(...)`:
```python
        _record, _finish = _fmt_record(r["user_id"], year, season_recs)
```

And in `StandingRow(...)`:
```python
            season_record=_record,
            best_finish=_finish,
```

Full updated standings list comprehension inside `build_dashboard`:

```python
    season_recs = entry.season_records or {}
    standings = []
    for i, r in enumerate(sorted_rows):
        _record, _finish = _fmt_record(r["user_id"], year, season_recs)
        standings.append(StandingRow(
            rank=i + 1,
            user_id=r["user_id"],
            owner=owner_ref(entry, r["user_id"]),
            net_ktc=r["net_ktc"],
            production_total=r["production_total"],
            production_regular=r["production_regular"],
            production_playoff=r["production_playoff"],
            production_toilet=r["production_toilet"],
            trades=r["trades"],
            grade=grade_by_uid.get(r["user_id"], "B"),
            net_ktc_at_trade=r["net_ktc_at_trade"],
            net_ktc_aged=r["net_ktc_today_subset"] - r["net_ktc_at_trade"],
            gm_rating=ratings.get(r["user_id"]),
            gm_rank=gm_rank_by_uid.get(r["user_id"]),
            gm_trend=gm_trend_by_uid.get(r["user_id"], 0),
            window=(dynasty_outlooks.get(r["user_id"]) or {}).get("window"),
            draft_capital_value=float(
                (outlook_signals.get(r["user_id"]) or {}).get("draft_capital") or 0
            ),
            season_record=_record,
            best_finish=_finish,
        ))
```

Note: you must replace the existing list comprehension (currently using `[StandingRow(...) for i, r in enumerate(sorted_rows)]`) with this `for` loop.

- [ ] **Step 5: Run tests**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && make test-api 2>&1 | tail -3
```
Expected: all 189 passing.

- [ ] **Step 6: Commit**

```bash
git add api/app/services/aggregations.py api/tests/test_aggregations.py
git commit -m "feat(dashboard): populate season_record and best_finish on StandingRow; add _ordinal + _fmt_record helpers"
```

---

## Task 6: Frontend — types + Record column in table

**Files:**
- Modify: `web/lib/types.ts`
- Modify: `web/components/StandingsTable.tsx`

- [ ] **Step 1: Add fields to `StandingRow` in `web/lib/types.ts`**

After `draft_capital_value?: number;` add:

```typescript
  season_record?: string | null;
  best_finish?: string | null;
```

- [ ] **Step 2: Add "Record" column to `COLS_INTEL` in `StandingsTable.tsx`**

After the `owner_name` entry, add:

```typescript
  {
    key: "season_record", plain: "Record",
    tooltip: { title: "Record", body: "Career W-L record and best playoff finish across all seasons." },
  },
```

And add to `COLS_HIST` the same (right after `owner_name`):

```typescript
  {
    key: "season_record", plain: "Record",
    tooltip: { title: "Record", body: "Regular-season W-L and final standing for this season." },
  },
```

- [ ] **Step 3: Update grid templates to add one column after Owner**

Change `gridCls`:

```typescript
  const gridCls = showIntel
    ? "w-full grid grid-cols-[24px_1.4fr_0.7fr_0.7fr_0.8fr_1fr_0.85fr_0.85fr_52px]"
    : "w-full grid grid-cols-[24px_1.5fr_0.7fr_1fr_0.9fr_0.9fr_56px]";
```

- [ ] **Step 4: Update group header spacers**

The "Trade Metrics" group header row uses empty `<div>`s for non-trade columns. The trade columns are always the last 4. Adding Record shifts non-trade count from 4→5 (intel) and 2→3 (historical):

```tsx
        <div className={`${gridCls} gap-2`}>
          <div /><div /><div />
          {showIntel && <><div /><div /></>}
          <div className="col-span-4 flex items-center gap-2 pb-1.5 pt-0.5">
            <div className="flex-1 h-px bg-divider opacity-50" />
            <span className="font-mono text-[9px] uppercase tracking-[0.1em] text-dim whitespace-nowrap">
              Trade Metrics{typeof year === "number" ? ` · ${year}` : ""}
            </span>
            <div className="flex-1 h-px bg-divider opacity-50" />
          </div>
        </div>
```

(Intel: 3 base + 2 conditional = 5 spacers + span-4 = 9 ✓. Historical: 3 spacers + span-4 = 7 ✓.)

- [ ] **Step 5: Add Record cell to the intel desktop row**

In the `{showIntel ? (<>...</>) : (<>...</>)}` block, after the Owner `<div>` and before the GM Rating `<div>`, add the Record cell:

```tsx
                <div className="min-w-0">
                  <div className="font-mono text-[12px]">{r.season_record ?? "—"}</div>
                  {r.best_finish && r.best_finish !== "—" && (
                    <div className="font-mono text-[10px] text-dim mt-0.5">{r.best_finish}</div>
                  )}
                </div>
```

- [ ] **Step 6: Add Record cell to the historical desktop row**

In the historical branch (the `else` block that renders `<div className="text-dim text-[11px]">{r.rank}</div>` and Owner), add after Owner:

```tsx
                <div className="min-w-0">
                  <div className="font-mono text-[12px]">{r.season_record ?? "—"}</div>
                  {r.best_finish && r.best_finish !== "—" && (
                    <div className="font-mono text-[10px] text-dim mt-0.5">{r.best_finish}</div>
                  )}
                </div>
```

- [ ] **Step 7: Add Record to mobile view**

The mobile view currently shows `# · Owner · [GM Rating or Trade Value] · Grade`. Update the header and rows to show Record instead of GM Rating / Trade Value in position 3 on all views:

Change the mobile grid to `grid-cols-[24px_minmax(0,1fr)_72px_54px]` and the 3rd column:

Header:
```tsx
          <div className="text-right">Record</div>
```

Row (replacing the conditional GM Rating / Trade Value cell):
```tsx
            <div className="text-right font-mono text-[11px]">
              <div>{r.season_record ?? "—"}</div>
              {r.best_finish && r.best_finish !== "—" && (
                <div className="text-[10px] text-dim">{r.best_finish}</div>
              )}
            </div>
```

- [ ] **Step 8: TypeScript check + tests**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/web" && npx tsc --noEmit 2>&1 | head -5
npm run test -- --run 2>&1 | tail -5
```
Expected: no errors, 83 tests passing.

- [ ] **Step 9: Commit**

```bash
git add web/lib/types.ts web/components/StandingsTable.tsx
git commit -m "feat(dashboard): add Record column showing W-L + finish for each year view"
```

---

## Task 7: Deploy and verify

- [ ] **Step 1: Push and deploy**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && git push origin main
railway up --service api --detach -m "feat: season records — W-L + finish in Owner Rankings"
railway up --service web --detach -m "feat: Record column in Owner Rankings table"
```

- [ ] **Step 2: Poll deployments**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && until railway deployment list --service api --limit 1 --json 2>/dev/null | python3 -c "import sys,json; s=json.load(sys.stdin)[0]['status']; print('api:',s); exit(0 if s in ['SUCCESS','FAILED','CRASHED'] else 1)" 2>/dev/null; do sleep 10; done && until railway deployment list --service web --limit 1 --json 2>/dev/null | python3 -c "import sys,json; s=json.load(sys.stdin)[0]['status']; print('web:',s); exit(0 if s in ['SUCCESS','FAILED','CRASHED'] else 1)" 2>/dev/null; do sleep 10; done
```

- [ ] **Step 3: Force refresh**

```bash
curl -s -N "https://web-production-f949.up.railway.app/api/league/9000000000000000001/refresh?force=true" | grep -E "stage.*done|error"
```

- [ ] **Step 4: Verify via API**

```bash
# All-time: career record + best finish
curl -s "https://web-production-f949.up.railway.app/api/league/9000000000000000001" | python3 -c "
import sys,json
d=json.load(sys.stdin)
for r in d['standings'][:4]:
    print(r['owner']['owner_name'], '|', r.get('season_record'), '|', r.get('best_finish'))
"

# Historical: per-season record + rank
curl -s "https://web-production-f949.up.railway.app/api/league/9000000000000000001?year=2025" | python3 -c "
import sys,json
d=json.load(sys.stdin)
for r in d['standings'][:4]:
    print(r['owner']['owner_name'], '|', r.get('season_record'), '|', r.get('best_finish'))
"
```

Expected: real W-L strings and finish labels populated.
