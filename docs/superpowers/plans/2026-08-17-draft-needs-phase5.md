# Draft Needs (Phase 5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reconstruct each roster as it stood on draft day, decide which starting slots were holes, and report on the league draft board whether the draft addressed them.

**Architecture:** Three dependent seams. (1) A new `LeaguePlatform.get_roster_transactions` plus bundle plumbing, because 16% of roster-changing events are invisible to the existing filtered feeds. (2) A generalised ECR board path for `dynasty-overall`, reusing phase 1's parser and store rather than forking them. (3) Pure engine modules for reconstruction and hole detection, a value-layer cache field, and a "Going in" panel.

**Tech Stack:** Python 3.12 engine (pure modules + pytest), FastAPI backend, Next.js 14 + Tailwind against `.design/` tokens, vitest.

**Spec:** `docs/superpowers/specs/2026-08-17-draft-needs-phase5-design.md` — read it. It carries measured numbers and several traps that will each produce a silently wrong answer.

## Global Constraints

- **Branch `new-draft-board`. Never commit to `main`** (it auto-deploys). **Do NOT push** — the controller handles pushes. PR #10 is merged and closed; this work needs a new PR.
- **Never render "KTC"** in UI. It is "Trade Value" / "Value".
- **Needs is display-only and must NEVER feed Franchise Rating.** It rests on a reconstruction, a third-party ranking and a replacement line. The moment an inference feeds a rating, staleness becomes silently wrong.
- **No `SCHEMA_VERSION` bump.** Additive display data, `default_factory` + read-time fallback (the `league_phase` / `capabilities` precedent).
- **Value layer, always recomputed** — never a frozen rollup. The freeze predicate keys on trades only, so a completed draft would not invalidate it.
- Reuse `.design/` primitives; never add a `web/tests/furniture-rules.test.ts` exception entry.
- Verify: `pytest tests/` (engine, from repo root), `cd api && pytest tests/` (backend), `cd web && npx vitest --config tests/vitest.config.ts run` (a bare `npx vitest run` silently uses NO config and fails on JSX), `npx tsc --noEmit`. A bare `pytest` from the root breaks — `api/tests` and `tests/` are both packages named "tests".
- `npx tsc --noEmit` emits two PRE-EXISTING errors about `.next/types/app/preview/page.ts`. Any OTHER error is yours.
- **Falsify every test you add**: mutate the code it guards, confirm it fails, restore, confirm byte-identical. Report the mutation.

## File Structure

| File | Responsibility |
|---|---|
| `src/sleeper_dynasty/api/platform.py` | +`get_roster_transactions` on the Protocol |
| `src/sleeper_dynasty/api/sleeper.py` | Sleeper implementation (third filter over the memoised feed) |
| `src/sleeper_dynasty/engine/trade_history.py` | `raw_roster_txs` into the cached bundle |
| `api/app/services/league_raw_cache.py` | key-presence guard so stale bundles are a miss |
| `tests/helpers.py`, `tests/test_platform_protocol.py` | doubles + protocol guard gain the new name |
| `src/sleeper_dynasty/engine/rookie_board.py` | `parse_latest_board` takes an `ecr_type` |
| `api/app/services/rookie_board_store.py` | parameterised subdir/packaged file |
| `scripts/extract_ecr_boards.py` | generalised extractor (from `extract_rookie_boards.py`) |
| `src/sleeper_dynasty/data/dynasty_ecr.json.gz`, `dynasty_sf_ecr.json.gz` | committed board history |
| `src/sleeper_dynasty/engine/roster_asof.py` | **new, pure** — roster as of a date |
| `src/sleeper_dynasty/engine/draft_needs.py` | **new, pure** — holes, replacement line, verdicts |
| `api/app/services/grader.py` | stamps `draft_needs` in the value layer |
| `api/app/models/league.py` | `OwnerNeeds`, `DraftBoardResp.needs` |
| `api/app/services/draft_board_view.py` | assembles `needs` onto the response |
| `web/components/DraftGoingIn.tsx` | **new** — the panel + its `EntryCard` mobile body |

---

### Task 1: `get_roster_transactions` on the protocol, and into the bundle

**Files:**
- Modify: `src/sleeper_dynasty/api/platform.py`, `src/sleeper_dynasty/api/sleeper.py`, `src/sleeper_dynasty/engine/trade_history.py`, `api/app/services/league_raw_cache.py`, `tests/helpers.py`, `tests/test_platform_protocol.py`
- Test: `tests/test_sleeper_protocol_conformance.py`, `api/tests/test_league_raw_cache.py`

**Interfaces:**
- Produces: `async def get_roster_transactions(self, league_id: str) -> list[dict]` on `LeaguePlatform` and `SleeperClient`; `bundle["raw_roster_txs"]` from `trade_history`. Tasks 4 and 6 consume both.

**Why this exists (measured, not assumed):** `get_trade_transactions` filters `type == "trade"`; `get_drop_transactions` filters non-trade **with a non-empty `drops`** (`sleeper.py:260`). An add that drops nobody passes neither. In the real league that is **63 of 400 transactions in 2025 (16%)** and 14 of 128 in 2026.

- [ ] **Step 1: Write the failing conformance test**

```python
# tests/test_sleeper_protocol_conformance.py
@pytest.mark.asyncio
async def test_get_roster_transactions_includes_adds_with_no_drops():
    """The gap this method exists to close. An add that drops nobody is
    invisible to get_trade_transactions AND get_drop_transactions."""
    client = _client_with_transactions([
        {"type": "waiver", "status": "complete", "transaction_id": "a",
         "adds": {"111": 1}, "drops": None, "status_updated": 1746230400000},
        {"type": "free_agent", "status": "complete", "transaction_id": "b",
         "adds": {"222": 2}, "drops": {"333": 2}, "status_updated": 1746230500000},
        {"type": "trade", "status": "complete", "transaction_id": "c",
         "adds": {"444": 1}, "drops": {"555": 2}, "status_updated": 1746230600000},
        {"type": "waiver", "status": "failed", "transaction_id": "d",
         "adds": {"666": 1}, "drops": None, "status_updated": 1746230700000},
    ])
    out = await client.get_roster_transactions("L1")
    ids = {t["transaction_id"] for t in out}
    assert ids == {"a", "b", "c"}          # the add-only one is INCLUDED
    assert "d" not in ids                   # a failed waiver never touched a roster
    # and the existing feeds still do NOT see it, which is the point
    assert "a" not in {t["transaction_id"] for t in await client.get_drop_transactions("L1")}
```

- [ ] **Step 2: Run it, watch it fail**

Run: `pytest tests/test_sleeper_protocol_conformance.py -k roster_transactions -v`
Expected: FAIL — `AttributeError: get_roster_transactions`.

- [ ] **Step 3: Add the Protocol method and the Sleeper implementation**

In `platform.py`, beside `get_trade_transactions` / `get_drop_transactions`. In `sleeper.py`, a third filter over `_all_week_transactions` — **keep the single-slot memo**; a third caller is precisely why it exists. Filter `status == "complete"` only (the 2025 feed carries 28 failed waivers).

- [ ] **Step 4: Verify it passes**

Run: `pytest tests/test_sleeper_protocol_conformance.py -v`

- [ ] **Step 5: Update the two guards that would silently stop guarding**

- `tests/helpers.py:27` `_DERIVED_FROM_GET_TRANSACTIONS` — add `"get_roster_transactions"`. Without this every double wired through `wire_transaction_protocol` (CLAUDE.md's sanctioned path) silently lacks the method.
- `tests/test_platform_protocol.py:42-47` — add the name to `required`. It asserts `required <= set(dir(...))`, so omitting it does not fail; it just stops guarding.

- [ ] **Step 6: Plumb it into the cached bundle**

`trade_history.py` around line 387: add `"raw_roster_txs": raw_roster_txs` beside `raw_trades`/`raw_drops`, fetched the same way.

**Why this matters:** for a sealed season (`status == "complete"`) the bundle is served from `LeagueRawCache` and the two existing feeds are never called — no HTTP, and the memo never reached. A `get_roster_transactions` called from anywhere else would trigger a **fresh 18-week walk per sealed league-season**, exactly the doubling the memo prevents.

- [ ] **Step 7: Write the failing stale-bundle test, then add the guard**

```python
# api/tests/test_league_raw_cache.py
def test_a_bundle_without_raw_roster_txs_reads_as_a_miss(tmp_path):
    """Every sealed-season bundle written before this feature lacks the key.
    Without a guard it returns successfully with zero roster transactions and
    no error — the reconstruction would silently be built on nothing."""
    cache = LeagueRawCache(tmp_path)
    cache.write_trade_bundle("L1", {
        "users": {}, "roster_to_user": {}, "raw_trades": [], "raw_drops": [],
        "drafts": [], "draft_picks_by_draft_id": {},
    })  # note: no raw_roster_txs
    assert cache.read_trade_bundle("L1") is None
```

Then add the guard to `read_trade_bundle`, following `grader_io.py:142`'s existing pattern (`if cached is not None and "winners_bracket" in cached`) — a key-presence check that treats a stale bundle as a miss.

- [ ] **Step 8: Full suites, then commit**

```bash
pytest tests/ -q && (cd api && pytest tests/ -q)
git add src/sleeper_dynasty/api/platform.py src/sleeper_dynasty/api/sleeper.py \
        src/sleeper_dynasty/engine/trade_history.py api/app/services/league_raw_cache.py \
        tests/helpers.py tests/test_platform_protocol.py \
        tests/test_sleeper_protocol_conformance.py api/tests/test_league_raw_cache.py
git commit -m "feat(api): get_roster_transactions, the unfiltered feed reconstruction needs"
```

---

### Task 2: Generalise the ECR board parser and store

**Files:**
- Modify: `src/sleeper_dynasty/engine/rookie_board.py`, `api/app/services/rookie_board_store.py`
- Test: `tests/test_rookie_board.py`, `api/tests/test_rookie_board_store.py`

**Interfaces:**
- Produces: `parse_latest_board(rows, crosswalk, ecr_type)` and a store parameterised by `(subdir, packaged_file)`. Task 3 and Task 5 consume both.

**Read first, because the spec's first draft got this wrong:** `resolve_board` (`rookie_board.py:103`) is **already generic** — it takes parsed boards and never sees an `ecr_type`. The function hardcoding `ROOKIE_ECR_TYPE` is **`parse_latest_board` (`:75`)**. Generalise that one. `parse_boards` (`:38`) is already generic.

- [ ] **Step 1: Write the failing parser test**

```python
def test_parse_latest_board_selects_by_ecr_type():
    rows = [
        {"ecr_type": "drk", "id": "fp1", "ecr": 1.0, "scrape_date": "2025-05-01"},
        {"ecr_type": "do",  "id": "fp1", "ecr": 40.0, "scrape_date": "2025-05-01"},
        {"ecr_type": "dsf", "id": "fp1", "ecr": 22.0, "scrape_date": "2025-05-01"},
    ]
    cw = {"fp1": "s1"}
    assert parse_latest_board(rows, cw, "do") == ("2025-05-01", {"s1": 40.0})
    assert parse_latest_board(rows, cw, "dsf") == ("2025-05-01", {"s1": 22.0})
    assert parse_latest_board(rows, cw, "drk") == ("2025-05-01", {"s1": 1.0})
```

- [ ] **Step 2: Run it, watch it fail** — `TypeError: takes 2 positional arguments but 3 were given`.

- [ ] **Step 3: Add the `ecr_type` parameter**

Keep `ROOKIE_ECR_TYPE` as the default so existing callers are untouched. `scripts/extract_rookie_boards.py:37` imports the constant — leave that import working.

- [ ] **Step 4: Document why `MAX_BOARD_AGE_DAYS` does not transfer**

`MAX_BOARD_AGE_DAYS = 60` (`:100`) is justified by a **rookie-class** argument — a board from a different rookie class is ~9 months away, so 60 days separates "stale" from "about different players". For `do`/`dsf` an old board is only stale. The `max_age_days` parameter already exists on `resolve_board`; pick a value for the dynasty path and write the reasoning into the docstring rather than reusing 60 by inertia.

- [ ] **Step 5: Write the failing store-collision test**

```python
def test_two_board_types_do_not_share_a_pin_path(tmp_path):
    """resolve_for_draft pins WRITE-ONCE. If a rookie board and a
    dynasty-overall board for the same draft shared a path, the first writer
    would permanently poison the second — the same class of failure
    capture_daily's empty-refusal exists to prevent."""
    rookie = EcrBoardStore(tmp_path, subdir="rookie_ecr", packaged="rookie_ecr.json.gz")
    dyn    = EcrBoardStore(tmp_path, subdir="dynasty_ecr", packaged="dynasty_ecr.json.gz")
    assert rookie._pin_path("draft1") != dyn._pin_path("draft1")
```

- [ ] **Step 6: Parameterise the store**

`_SUBDIR` (`:32`) and `_PACKAGED` (`:34`) become constructor arguments. Keep a rookie-configured alias so existing call sites do not change in this task.

- [ ] **Step 7: Run both suites and commit**

```bash
pytest tests/test_rookie_board.py -q && (cd api && pytest tests/test_rookie_board_store.py -q)
git commit -m "refactor(engine,api): ECR board parser and store take a board type"
```

---

### Task 3: Extract and commit the dynasty-overall boards

**Files:**
- Create: `scripts/extract_ecr_boards.py` (generalised from `scripts/extract_rookie_boards.py`)
- Create: `src/sleeper_dynasty/data/dynasty_ecr.json.gz`, `src/sleeper_dynasty/data/dynasty_sf_ecr.json.gz`
- Test: `tests/test_ecr_data_files.py`

**Interfaces:**
- Consumes: Task 2's `parse_boards`/`parse_latest_board` with an `ecr_type`.
- Produces: two committed `.json.gz` files. Task 5 resolves boards from them.

**Two traps carried from phase 1, both of which cost a session there:**

1. **Use `db_fpecr.parquet`, never `db_fpecr.csv.gz`.** The csv is frozen at 2025-08-08 and exceeds GitHub's 100MB cap while gunzipping cleanly — success-shaped staleness that would silently cost the whole current class.
2. **R's literal `"NA"` must be filtered** from the crosswalk or it becomes a catch-all key.

**Expected size, so a surprise is recognisable:** rookie is 309 boards × ~94 entries = 29,082 → 74KB gzipped. Dynasty-overall is 360 boards × 751–956 → **~300,000 entries, roughly 700–800KB gzipped**; `dsf` similar. `pyproject.toml:35` already globs `data/*.json.gz`, so **no packaging change is needed**.

- [ ] **Step 1: Write the structural assertion test**

```python
def test_dynasty_board_history_is_dense_and_ordered():
    boards = load_packaged("dynasty_ecr.json.gz")
    assert len(boards) > 300
    # Do NOT gate on file size — a size gate blocked a healthy extract in
    # phase 1 because size is a bad proxy for sparse data. Assert structure.
    per_board = [len(b) for b in boards.values()]
    assert min(per_board) > 400, "a board with few entries means a bad ecr_type filter"
    assert all(_is_iso_date(d) for d in boards)
```

- [ ] **Step 2: Run it, watch it fail** — the data file does not exist.

- [ ] **Step 3: Generalise the extraction script**

`ecr_type` and output path become arguments. Keep the parquet-not-csv rationale in the docstring, and **state the regeneration obligation**: the committed history has an end date, and a fresh install deployed long after generation has a gap until its first capture.

- [ ] **Step 4: Run it for `do` and `dsf`, then verify the test passes**

- [ ] **Step 5: Commit**

```bash
git add scripts/extract_ecr_boards.py src/sleeper_dynasty/data/dynasty_ecr.json.gz \
        src/sleeper_dynasty/data/dynasty_sf_ecr.json.gz tests/test_ecr_data_files.py
git commit -m "feat(data): commit dynasty-overall ECR board history"
```

---

### Task 4: `roster_asof.py` — the roster on draft day

**Files:**
- Create: `src/sleeper_dynasty/engine/roster_asof.py`
- Test: `tests/test_roster_asof.py`

**Interfaces:**
- Consumes: Task 1's transaction shape.
- Produces: `def roster_asof(seed: dict[str, set[str]], transactions: list[dict], roster_to_user: dict[int, str], as_of: datetime) -> dict[str, set[str]]` — owner_id → player_ids. Task 5 consumes it.

**Pure. No I/O, no client.** Transactions in, roster out.

**The seed is NOT `get_rosters`.** That returns Sleeper's **live** state, which for a rolled-over dynasty league may already reflect offseason moves the reconstruction would then apply twice. The caller (Task 6) builds the seed from `supporting["matchups"]` — the highest week present for the prior season's league id, per roster, from the `"players"` array each entry already carries (`grader_io.py:122-129`), mapped through `roster_to_user_by_league`.

- [ ] **Step 1: Write the failing tests**

```python
def test_applies_adds_and_drops_in_timestamp_order():
    seed = {"u1": {"p1", "p2"}}
    txs = [
        {"status_updated": 200, "adds": {"p3": 1}, "drops": {"p1": 1}},
        {"status_updated": 100, "adds": {"p9": 1}, "drops": None},
    ]
    out = roster_asof(seed, txs, {1: "u1"}, as_of=_dt(300))
    assert out["u1"] == {"p2", "p3", "p9"}

def test_ignores_transactions_after_the_cutoff():
    seed = {"u1": {"p1"}}
    txs = [{"status_updated": 500, "adds": {"p2": 1}, "drops": None}]
    assert roster_asof(seed, txs, {1: "u1"}, as_of=_dt(300))["u1"] == {"p1"}

def test_a_transaction_with_no_timestamp_is_skipped_not_guessed():
    # Measured: 0 of 528 real transactions lack one. Defensive invariant only —
    # do NOT build a skip counter for the UI, it would always render 0.
    seed = {"u1": {"p1"}}
    txs = [{"adds": {"p2": 1}, "drops": None}]
    assert roster_asof(seed, txs, {1: "u1"}, as_of=_dt(300))["u1"] == {"p1"}

def test_is_owner_keyed_not_roster_id_keyed():
    """Roster ids are not stable across a league chain."""
    seed = {"u1": {"p1"}}
    txs = [{"status_updated": 100, "adds": {"p2": 7}, "drops": None}]
    out = roster_asof(seed, txs, {7: "u1"}, as_of=_dt(300))
    assert out["u1"] == {"p1", "p2"}

def test_does_not_mutate_the_seed():
    seed = {"u1": {"p1"}}
    roster_asof(seed, [{"status_updated": 100, "adds": {"p2": 1}, "drops": None}],
                {1: "u1"}, as_of=_dt(300))
    assert seed == {"u1": {"p1"}}
```

- [ ] **Step 2: Run, watch fail. Step 3: Implement. Step 4: Verify.**

Note Sleeper's `adds`/`drops` map `player_id -> roster_id`, so the roster id is the **value**, not the key.

- [ ] **Step 5: Commit** — `feat(engine): reconstruct a roster as of a date`

---

### Task 5: `draft_needs.py` — holes, replacement line, verdicts

**Files:**
- Create: `src/sleeper_dynasty/engine/draft_needs.py`
- Test: `tests/test_draft_needs.py`

**Interfaces:**
- Consumes: Task 4's roster map, Task 2/3's boards, `engine/lineup.py::solve_optimal_lineup`.
- Produces: `def build_draft_needs(rosters, board, positions, roster_positions, picks_by_owner, started_by_pick) -> list[OwnerNeeds]`.

**CONTROLLER CORRECTION (found during Task 5) — `positions: dict[str, str]` is REQUIRED and was missing from my original signature.**
`solve_optimal_lineup` takes `players: dict[str, tuple[str, float]]` whose first element IS the fantasy position, but `roster_asof` yields a bare id set and `parse_latest_board` strips the board to a bare float. Without a position map the module cannot compute a *positional* replacement line at all — and "the 12th-best player overall" is not "the 12th-best QB", so every hole on a real multi-position roster comes out wrong, and plausibly wrong.

**Task 6 supplies it at no extra fetch:** the Sleeper catalog is already loaded at `api/app/services/grader.py:514` (`raw_players = await client.get_players()`) and each entry carries `p.get("position")` — see `grader_io.py:260-265` for the existing access pattern.

**CONTROLLER RULING (pre-flight scan) — two types, two names.** `OwnerNeeds` here is a **plain dataclass in `engine/draft_needs.py`**. Task 6's wire type is a *separate* Pydantic model named **`OwnerNeedsResp`**, with a mapping function at the boundary. One name for two types across a boundary is the `SortDir` problem from phase 4: it drifts the moment one side gains a field.

**The engine dataclass MAY carry more than the wire model.** It has `starters_by_slot: dict[str, str | None]` — which is what makes the hole verdict testable and debuggable — and that field is deliberately **not** exposed on `OwnerNeedsResp`. The API carries what the panel renders, nothing more.

**Four traps, each of which produces a silently wrong answer:**

1. **ECR is a RANK; the solver wants a VALUE.** `solve_optimal_lineup` sorts `reverse=True` on the float (`lineup.py:73-75`) and takes the first eligible — raw ECR in means the **worst** players start. Invert it. This gets its own test.
2. **Discard the returned total** — it becomes a sum of inverted ranks and means nothing. `starters, _ = solve_optimal_lineup(...)`, matching `outlook.py:124`.
3. **Strip `K` and `DEF` from `roster_positions` before the solve.** The solver filters only `BENCH_SLOTS = {"BN","IR","TAXI"}` (`lineup.py:36,62`). Leave them in with no K/DEF players in the map and those slots come back empty — and an empty slot is trivially below any replacement line, so **every owner gets two permanent phantom holes**.
4. **An unranked rostered player needs a sentinel.** `outlook.py:120-123` drops unmapped players; here that empties the slot and manufactures the same phantom hole. The sentinel must rank worse than every ranked player but better than nobody.

**Greedy is optimal for this league** — live `roster_positions` is `['QB','RB','RB','WR','WR','TE','FLEX','FLEX','K','DEF','BN'×10]`, whose eligibility sets form a laminar family (every pair nested or disjoint). No caveat applies.

- [ ] **Step 1: Write the failing tests**

```python
def test_ecr_rank_is_inverted_so_the_best_player_starts():
    """The single easiest thing to get backwards. Raw ECR in = worst starts."""
    board = {"qb_elite": 1.0, "qb_bad": 300.0}
    rosters = {"u1": {"qb_elite", "qb_bad"}}
    needs = build_draft_needs(rosters, board, ["QB", "BN"], {}, {})
    assert _starter_for(needs, "u1", "QB") == "qb_elite"

def test_k_and_def_slots_never_become_holes():
    """Not stripping them gives EVERY owner two permanent phantom holes."""
    rosters = {"u1": {"qb1"}}
    needs = build_draft_needs(rosters, {"qb1": 1.0}, ["QB", "K", "DEF"], {}, {})
    assert "K" not in needs[0].holes and "DEF" not in needs[0].holes

def test_an_unranked_player_fills_his_slot_rather_than_emptying_it():
    rosters = {"u1": {"unranked_te"}}
    needs = build_draft_needs(rosters, {"someone_else": 1.0}, ["TE", "BN"], {}, {})
    # He may well BE a hole — he just must not vanish and leave an empty slot,
    # which is a different (and always-true) finding.
    assert needs[0].starters_by_slot["TE"] == "unranked_te"

def test_the_replacement_line_comes_from_the_league_not_a_constant():
    """12 teams starting one QB -> the 12th-best QB in the league."""
    rosters = {f"u{i}": {f"qb{i}"} for i in range(1, 13)}
    board = {f"qb{i}": float(i) for i in range(1, 13)}
    needs = build_draft_needs(rosters, board, ["QB", "BN"], {}, {})
    assert all(n.holes == [] for n in needs)  # everyone is at or above the line

def test_bench_slots_are_never_holes():
    needs = build_draft_needs({"u1": set()}, {}, ["BN", "IR"], {}, {})
    assert needs[0].holes == []
```

- [ ] **Step 2: Run, watch fail. Step 3: Implement. Step 4: Verify.**

Verdicts: `drafted_into` is the set of the owner's picks whose position matches an open hole; `started` counts those with `games_started > 0`. Sort `holes` most-severe first (furthest below the line).

- [ ] **Step 5: Commit** — `feat(engine): draft-day holes against a league-relative replacement line`

---

### Task 6: Grader wiring, cache field, API contract

**Files:**
- Modify: `api/app/services/grader.py`, `api/app/models/chain_cache.py`, `api/app/models/league.py`, `api/app/services/draft_board_view.py`
- Test: `api/tests/test_grader_service.py`, `api/tests/test_chain_cache.py`, `api/tests/test_draft_board_view.py`

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces: `ChainCacheEntry.draft_needs: dict[str, list[dict]]` (season as a **string** key, `default_factory=dict`, holds at most one season — see the shipped § API contract in the design spec, corrected 2026-08-17 by `0b3789d`); **`OwnerNeedsResp`** Pydantic model with `user_id`, `holes: list[str]`, `drafted_into: list[str]`, `started: int`, `drafted_into_count: int`; `DraftBoardResp.needs: list[OwnerNeedsResp] | None`.

**CONTROLLER RULING (pre-flight scan):** the wire model is `OwnerNeedsResp`, deliberately a different name from Task 5's engine dataclass `OwnerNeeds`, with a mapping function at the boundary. Task 5's `starters_by_slot` is **not** carried onto the wire model — the API surface carries what the panel renders.

**Placement: the VALUE layer, always recomputed.** Not a frozen rollup. `refresh_delta.py:28-31` derives new-transaction ids from **trades only**, so a completed draft does not invalidate the freeze — a frozen blob would be copied from an entry predating the draft and the panel would be missing for the newest class during exactly the draft window where it is the point. It is also microseconds, not the expensive tier. It sits with `drafted_picks`, which it must agree with.

**Gate on `roster_continuity` AND `multiyear_history`.** The second is not redundant: a first-season startup dynasty league has `roster_continuity: True` but no prior roster, identical to redraft. `needs` is `None` — **absent, not an empty list** — so the frontend omits the panel.

Compute best-effort (`try`/`except` + `log.exception`) so a refresh never fails on it.

- [ ] **Step 1–4: The `chain-cache-field` test quartet** (see that skill). All four, in order: round-trip through `ChainCache`; pre-feature entry defaults to `{}`; the grader stamps it (**prove the test bites by mutating the wiring out** — set `PYTHONPYCACHEPREFIX`, macOS pycache gotcha); `build_draft_board` serves the fallback on a pre-feature entry.

Heads-up: `test_grader_service.py` tests run ~30s each (MagicMock clients fall into real retry/backoff). Scope pytest to what you are adding while iterating.

- [ ] **Step 5: Write the failing gate tests**

```python
def test_a_redraft_league_gets_no_needs_at_all():
    assert build_draft_board(_redraft_entry(), season=2025).needs is None

def test_a_first_season_startup_dynasty_gets_no_needs():
    """roster_continuity is True but there is no prior roster — the same
    situation as redraft, and multiyear_history is what distinguishes it."""
    assert build_draft_board(_startup_entry(), season=2025).needs is None
```

- [ ] **Step 6: Build the seed from matchups** — highest week present for the prior season's league id, per roster, from `supporting["matchups"]`'s `"players"` (`grader_io.py:122-129`), mapped via `roster_to_user_by_league`. **Not `get_rosters`** (live state; see Task 4).

- [ ] **Step 7: Full backend suite, then commit**

```bash
cd api && pytest tests/ -q
git commit -m "feat(api): stamp draft needs in the value layer and serve them on the board"
```

---

### Task 7: The "Going in" panel

**Files:**
- Create: `web/components/DraftGoingIn.tsx`
- Modify: `web/components/DraftBoard.tsx`, `web/lib/types.ts`, `web/lib/draft-columns.ts`
- Test: `web/tests/DraftGoingIn.test.tsx`, extend `web/tests/draft-columns.test.ts`

**Interfaces:**
- Consumes: `DraftBoardResp.needs` from Task 6.

**Layout:** a fourth `Panel` below Picks, one `Row` per owner.

| Owner | Holes going in | Drafted into | Started |
|---|---|---|---|
| Mikey | QB · TE | TE | 1/1 |
| Dan | RB | — | — |
| Sam | — | — | — |

- **`Started` is a fraction** (`started`/`drafted_into_count`), not yes/no — an owner with two picks into two holes, one started, has no cell in a scalar column. Degrades to `—` when they drafted into none.
- **An owner with no holes renders `—`, never an empty row.** "Went in with a complete starting lineup" is a real finding, not missing data.
- **Mobile is an `EntryCard` per owner**, and any interaction drives both bodies from one array.
- **No colour on the verdicts** beyond sanctioned tone tokens — a hole is not a failure.
- The panel is **omitted entirely** when `needs` is `null`.

**Width — cut against the real budget, not the breakpoint.** `910 − 48px Shell padding − 2px Panel border = 860px`, and `minWidthPx` further charges 10px per gap and 28px cell padding, so a four-column grid has **`860 − 30 − 28 = 802px`** of track budget. Getting this wrong cost a full round in phase 4.

- [ ] **Step 1: Write the failing tests**

```tsx
it("renders an em-dash for an owner with no holes, not an empty row", () => {
  render(<DraftGoingIn needs={[{ user_id: "u1", holes: [], drafted_into: [],
                                 started: 0, drafted_into_count: 0 }]} owners={OWNERS} />);
  expect(screen.getByTestId("going-in-holes-u1")).toHaveTextContent("—");
});

it("renders Started as a fraction over the picks that addressed a hole", () => {
  render(<DraftGoingIn needs={[{ user_id: "u1", holes: ["QB", "TE"],
                                 drafted_into: ["TE", "QB"], started: 1,
                                 drafted_into_count: 2 }]} owners={OWNERS} />);
  expect(screen.getByTestId("going-in-started-u1")).toHaveTextContent("1/2");
});

it("omits the panel entirely when needs is null", () => {
  render(<DraftBoard board={{ ...BOARD, needs: null }} leagueId="1" />);
  expect(screen.queryByTestId("draft-going-in")).toBeNull();
});
```

- [ ] **Step 2: Run, watch fail. Step 3: Implement. Step 4: Verify.**

- [ ] **Step 5: Add the grid to the width-gate test**

Extend `web/tests/draft-columns.test.ts` so the new template is checked by the same `WIDTH_GATE_BUDGET_PX` assertion as every other one.

- [ ] **Step 6: Full frontend run, then commit**

```bash
cd web && npx vitest --config tests/vitest.config.ts run && npx tsc --noEmit && npm run build
git commit -m "feat(web): the Going in panel"
```

---

## Notes for the controller

- **The three seams are dependent.** Tasks 1 → 4/6 (data path), 2 → 3 → 5 (board data), and 7 last. Tasks 2 and 3 can run before or beside Task 1; Tasks 4–7 cannot start before their inputs exist.
- **Do NOT plan a probe task for the offseason week range.** It was resolved during spec review: Sleeper files every offseason transaction under leg 1, all 105 pre-season 2025 moves sit inside week 1's rows, and `range(1, 19)` is correct.
- The spec's numbers are measured against the real league, not estimated. If an implementer's observation contradicts one, that is worth surfacing rather than quietly working around.
