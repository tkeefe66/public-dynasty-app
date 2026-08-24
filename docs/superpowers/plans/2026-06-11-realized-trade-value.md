# Realized Trade Value Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Trade Value's perpetual mark-to-market swing with a realized, received-only, tenure-bounded metric — each received asset frozen at the owner's relinquish boundary (held → today's KTC, flipped → KTC at flip date, dropped → 0) — and point the standings, trade detail, grade, and GM Rating at it.

**Architecture:** A new pure engine function (`engine/lineage.py::realized_received_values`) resolves each received asset's disposition from the trade history and prices it via injected price-provider callables. A thin API service (`api/app/services/realized_value.py`) wires the existing `KtcSnapshotStore` in as those providers (memoized per date). The grading orchestrator (`api/app/services/grader.py`) calls it per trade, overwrites each `TradeGrade.received_ktc` and per-asset breakdown `ktc` with realized values, and the aggregator rolls `net_ktc` from `received_ktc` instead of the swing. The mark-to-market `snapshot_value_swing` field is kept computed but demoted to a diagnostic (no longer the headline).

**Tech Stack:** Python 3.11+, dataclasses, pytest. FastAPI (API layer). The engine package stays pure (no `api` imports); providers are injected.

---

## Decisions (resolving the spec's open questions)

1. **Grade derivation.** Realized `net_ktc` is all-positive and on a new scale, so the fixed thresholds in `_letter_grade(net_ktc)` break. Replace with a **league-relative z-score grade**: z-score each owner's realized `net_ktc` across the league, bucket A/A−/B+/B/B−/C/D. This mirrors the GM-Rating z-machinery and is deterministic. `_letter_grade` changes signature to take the full row set.
2. **`net_ktc_at_trade` / `net_ktc_aged`.** *Keep as-is, untouched.* They still derive from `snapshot_value_swing` + `at_trade_value_swing` and now read as a secondary "mark-to-market then-vs-now" diagnostic. Out of scope to remove; not surfaced as the headline.
3. **`at_trade.py`.** *Keep.* Still powers the trade-detail "value at the time" context line + approx flag.
4. **Cache invalidation.** None needed beyond a normal refresh: `grade_trade` and the grading loop run on every refresh, so the next refresh recomputes realized grades. No cache-version bump required (no persisted realized snapshots exist yet).

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `src/sleeper_dynasty/engine/lineage.py` | pure disposition + realized valuation walk | **add** `realized_received_values` (+ a shared `_given_index` helper extracted from `build_trade_lineage`) |
| `tests/test_lineage_realized.py` | unit tests for the realized walk | **create** |
| `api/app/services/realized_value.py` | wire `KtcSnapshotStore` as price providers; per-trade realized totals + per-asset values | **create** |
| `api/tests/test_realized_value.py` | unit tests for the service seam | **create** |
| `api/app/services/grader.py` | call realized valuation in the grading stage; overwrite `received_ktc` + breakdown `ktc` | **modify** (grading loop, ~lines 138-172) |
| `api/app/services/aggregations.py` | roll `net_ktc` from `received_ktc`; z-score letter grade; hero/records/latest read `received_ktc` for the ktc lens | **modify** |
| `api/tests/test_aggregations.py` | update expectations to realized `net_ktc` + z-grade | **modify** |
| `web/lib/types.ts` + `web/components/StandingsTable.tsx` | Trade Value tooltip copy (no longer "swing"/zero-sum) | **modify** (copy only) |

The engine stays representation-pure (dict-form trades, injected providers); the API owns IO (snapshot store).

---

## Task 1: Extract a shared `_given_index` helper in lineage.py

This isolates the "(owner, asset_id) → date-ordered trades where the owner gave that asset" index so both `build_trade_lineage` and the new realized walk share one implementation (DRY).

**Files:**
- Modify: `src/sleeper_dynasty/engine/lineage.py`
- Test: `tests/test_lineage.py` (existing — must still pass)

- [ ] **Step 1: Add the helper above `build_trade_lineage`**

In `src/sleeper_dynasty/engine/lineage.py`, after `_asset_id` (line 26) add:

```python
def _given_index(trades: list[dict]) -> dict[tuple, list[dict]]:
    """(owner, asset_id) -> trades (date-ordered) where that owner GAVE the asset."""
    idx: dict[tuple, list[dict]] = {}
    ordered = sorted(trades, key=lambda r: r["trade"]["traded_at"])
    for r in ordered:
        for uid, side in (r.get("sides") or {}).items():
            for a in side.get("given") or []:
                aid = _asset_id(a)
                if aid:
                    idx.setdefault((uid, aid), []).append(r)
    return idx
```

- [ ] **Step 2: Use it inside `build_trade_lineage`**

Replace the inline `given_index` construction (lines 33-42) with:

```python
    trades = sorted(resolved_trades, key=lambda r: r["trade"]["traded_at"])
    given_index = _given_index(trades)
```

(Delete the old `for r in trades: ... given_index.setdefault(...)` loop.)

- [ ] **Step 3: Run the existing lineage tests to verify no regression**

Run: `pytest tests/test_lineage.py -v`
Expected: PASS (the refactor is behavior-preserving).

- [ ] **Step 4: Commit**

```bash
git add src/sleeper_dynasty/engine/lineage.py
git commit -m "refactor(engine): extract _given_index helper in lineage"
```

---

## Task 2: Realized valuation walk (pure engine)

The core. `realized_received_values` returns, per side, a list of realized values **index-aligned to that side's `received` assets that have an `_asset_id`** (same filter `build_asset_breakdown` uses, so breakdown rows and these values line up by index).

**Files:**
- Modify: `src/sleeper_dynasty/engine/lineage.py`
- Test: `tests/test_lineage_realized.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_lineage_realized.py`:

```python
from sleeper_dynasty.engine.lineage import realized_received_values


def _trade(tx, when, sides):
    return {"trade": {"transaction_id": tx, "traded_at": when,
                      "league_id": "L", "season": 2026, "week": 1},
            "sides": sides}


def _player(pid, name):
    return {"player_id": pid, "name": name}


def _pick(season, rnd, owner, drafted_id=None, drafted_name=None):
    return {"season": season, "round": rnd, "original_owner_user_id": owner,
            "drafted_player_id": drafted_id, "drafted_player_name": drafted_name}


# Price providers: today = lookup in TODAY; dated = lookup in DATED[date].
TODAY = {"B": 5000.0, "C": 4800.0, "X": 1500.0}
DATED = {"2027-09-01": {"C": 6000.0, "B": 5000.0}}


def price_player(pid, d_iso):
    table = TODAY if d_iso is None else DATED.get(d_iso[:10], TODAY)
    return float(table.get(pid, 0.0))


def price_pick(season, rnd, d_iso):
    return 0.0  # picks priced separately in dedicated tests below


def test_held_player_valued_at_today():
    # A receives C and still holds it -> today's KTC.
    trades = [_trade("t1", "2026-01-01T00:00:00", {
        "A": {"received": [_player("C", "C")], "given": [_player("B", "B")]},
        "D": {"received": [_player("B", "B")], "given": [_player("C", "C")]},
    })]
    out = realized_received_values(trades, "t1", {"C": "A", "B": "D"},
                                   price_player, price_pick)
    assert out["A"] == [4800.0]   # C today
    assert out["D"] == [5000.0]   # B today


def test_flipped_player_valued_at_flip_date():
    # A receives C, then flips C away on 2027-09-01 -> C's KTC at flip date (6000).
    trades = [
        _trade("t1", "2026-01-01T00:00:00", {
            "A": {"received": [_player("C", "C")], "given": [_player("B", "B")]},
            "D": {"received": [_player("B", "B")], "given": [_player("C", "C")]},
        }),
        _trade("t2", "2027-09-01T00:00:00", {
            "A": {"received": [_player("Z", "Z")], "given": [_player("C", "C")]},
            "E": {"received": [_player("C", "C")], "given": [_player("Z", "Z")]},
        }),
    ]
    out = realized_received_values(trades, "t1", {"C": "E", "B": "D"},
                                   price_player, price_pick)
    assert out["A"] == [6000.0]   # C frozen at flip date, NOT today's 4800


def test_dropped_player_is_zero():
    # A receives C, never flips it, not on current roster -> dropped -> 0.
    trades = [_trade("t1", "2026-01-01T00:00:00", {
        "A": {"received": [_player("C", "C")], "given": [_player("B", "B")]},
        "D": {"received": [_player("B", "B")], "given": [_player("C", "C")]},
    })]
    out = realized_received_values(trades, "t1", {"B": "D"},  # C absent from holders
                                   price_player, price_pick)
    assert out["A"] == [0.0]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/test_lineage_realized.py -v`
Expected: FAIL with `ImportError: cannot import name 'realized_received_values'`.

- [ ] **Step 3: Implement `realized_received_values`**

In `src/sleeper_dynasty/engine/lineage.py`, after `terminal_assets`, add:

```python
from typing import Callable


def realized_received_values(
    resolved_trades: list[dict],
    root_trade_id: str,
    current_holders: dict[str, str],
    price_player: Callable[[str, str | None], float],
    price_pick: Callable[[int, int, str | None], float],
) -> dict[str, list[float]]:
    """Realized value of each side's received haul, frozen at the owner's
    relinquish boundary.

    Per received asset (held → today / flipped → flip date / dropped → 0):
      - ``price_player(player_id, date_iso | None)`` returns the player's KTC at
        the dated snapshot (None = today).
      - ``price_pick(season, round, date_iso | None)`` returns the round-level
        pick value (None = today).

    Returns ``{user_id: [value, ...]}`` index-aligned to that side's ``received``
    assets that carry an ``_asset_id`` (same filter ``build_asset_breakdown``
    uses), so breakdown rows and these values line up by index.
    """
    idx = _given_index(resolved_trades)

    def _first_flip_date(owner: str, aid, since: str) -> str | None:
        flips = [r for r in idx.get((owner, aid), [])
                 if r["trade"]["traded_at"] > since]
        return flips[0]["trade"]["traded_at"][:10] if flips else None

    def _player_value(pid: str, owner: str, since: str) -> float:
        flip_date = _first_flip_date(owner, ("player", pid), since)
        if flip_date is not None:
            return price_player(pid, flip_date)          # flipped → flip-date KTC
        if current_holders.get(pid) == owner:
            return price_player(pid, None)               # held → today
        return 0.0                                       # dropped

    def _asset_value(a: dict, owner: str, since: str) -> float:
        aid = _asset_id(a)
        if aid[0] == "player":
            return _player_value(a["player_id"], owner, since)
        # pick
        flip_date = _first_flip_date(owner, aid, since)
        if flip_date is not None:
            return price_pick(a["season"], a["round"], flip_date)  # flipped as a pick
        dpid = a.get("drafted_player_id")
        if dpid:
            return _player_value(dpid, owner, since)      # drafted → resolve player
        return price_pick(a["season"], a["round"], None)  # undrafted future pick, held

    root = next(r for r in resolved_trades
                if r["trade"]["transaction_id"] == root_trade_id)
    since = root["trade"]["traded_at"]
    out: dict[str, list[float]] = {}
    for uid, side in (root.get("sides") or {}).items():
        out[uid] = [_asset_value(a, uid, since)
                    for a in (side.get("received") or []) if _asset_id(a)]
    return out
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_lineage_realized.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Add pick-disposition tests**

Append to `tests/test_lineage_realized.py`:

```python
PICK_TODAY = {(2027, 1): 900.0}
PICK_DATED = {"2028-09-01": {(2027, 1): 700.0}}


def _pp_today(pid, d_iso):
    return float(TODAY.get(pid, 0.0))


def _pp_pick(season, rnd, d_iso):
    table = PICK_TODAY if d_iso is None else PICK_DATED.get(d_iso[:10], PICK_TODAY)
    return float(table.get((season, rnd), 0.0))


def test_pick_flipped_before_draft_uses_flip_date_pick_value():
    trades = [
        _trade("t1", "2026-01-01T00:00:00", {
            "A": {"received": [_pick(2027, 1, "A")], "given": [_player("B", "B")]},
            "D": {"received": [_player("B", "B")], "given": [_pick(2027, 1, "A")]},
        }),
        _trade("t2", "2028-09-01T00:00:00", {
            "A": {"received": [_player("Z", "Z")], "given": [_pick(2027, 1, "A")]},
            "E": {"received": [_pick(2027, 1, "A")], "given": [_player("Z", "Z")]},
        }),
    ]
    out = realized_received_values(trades, "t1", {}, _pp_today, _pp_pick)
    assert out["A"] == [700.0]   # pick frozen at flip date


def test_pick_drafted_and_held_uses_drafted_player_today():
    # Pick received, drafted to player C, still held -> today's C.
    trades = [_trade("t1", "2026-01-01T00:00:00", {
        "A": {"received": [_pick(2027, 1, "A", drafted_id="C", drafted_name="C")],
              "given": [_player("B", "B")]},
        "D": {"received": [_player("B", "B")],
              "given": [_pick(2027, 1, "A", drafted_id="C", drafted_name="C")]},
    })]
    out = realized_received_values(trades, "t1", {"C": "A"}, _pp_today, _pp_pick)
    assert out["A"] == [4800.0]   # today's C, not the pick table
```

- [ ] **Step 6: Run all realized tests**

Run: `pytest tests/test_lineage_realized.py -v`
Expected: PASS (5 tests).

- [ ] **Step 7: Commit**

```bash
git add src/sleeper_dynasty/engine/lineage.py tests/test_lineage_realized.py
git commit -m "feat(engine): realized received-value walk (held/flipped/dropped)"
```

---

## Task 3: API service — wire the snapshot store as price providers

**Files:**
- Create: `api/app/services/realized_value.py`
- Test: `api/tests/test_realized_value.py`

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_realized_value.py`:

```python
from datetime import date

from app.services.realized_value import make_price_providers


class _FakeStore:
    """match() returns a dated snapshot keyed by name -> object with .superflex_value."""
    def __init__(self, by_date):
        self._by_date = by_date  # {date: {normalized_name: KTCValueLike}}

    def match(self, d, cutoff):
        snap = self._by_date.get(d)
        return (snap, d, False) if snap is not None else (None, None, False)


class _V:
    def __init__(self, sf):
        self.superflex_value = sf


def test_price_player_today_and_dated():
    today_ktc = {"C": _V(4800)}
    store = _FakeStore({date(2027, 9, 1): {"cee": _V(6000)}})
    raw_players = {"C": {"full_name": "Cee"}}  # resolve_ktc_to_player_id maps name->pid
    pp, _ = make_price_providers(
        store=store, raw_players=raw_players,
        today_ktc_by_pid=today_ktc, today_pick_table={},
        cutoff=date(2026, 5, 1),
    )
    assert pp("C", None) == 4800.0                 # today
    assert pp("C", "2027-09-01") == 6000.0         # dated snapshot
```

> Note: the dated branch goes through `resolve_ktc_to_player_id`, which maps the
> snapshot's normalized names to player_ids using `raw_players`. The fixture name
> `"cee"` / full_name `"Cee"` must normalize-match player_id `"C"`. If the
> matcher's normalization differs, adjust the fixture name to match (see
> `app/services/grader_io.py::resolve_ktc_to_player_id`).

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest api/tests/test_realized_value.py -v`
Expected: FAIL with `ModuleNotFoundError: app.services.realized_value`.

- [ ] **Step 3: Implement the service**

Create `api/app/services/realized_value.py`:

```python
"""Wire KtcSnapshotStore into the engine's realized-value price providers.

Builds two memoized callables — price_player / price_pick — that the engine's
``realized_received_values`` uses to value an asset at a flip date (or today).
Dated snapshots are resolved once per distinct date. When no snapshot exists for
a flip date (e.g. before the snapshot history began), falls back to today's
tables — the best available price — accepting that pre-history flips can't be
frozen exactly.
"""

from __future__ import annotations

from datetime import date
from typing import Callable

from app.services.at_trade import BACKFILL_CUTOFF
from app.services.grader_io import resolve_ktc_to_player_id
from sleeper_dynasty.api.ktc import build_pick_value_table
from sleeper_dynasty.engine.lineage import realized_received_values


def _sf(v) -> float:
    sf = getattr(v, "superflex_value", None)
    return float(sf) if v is not None and sf is not None else 0.0


def make_price_providers(
    *, store, raw_players, today_ktc_by_pid, today_pick_table, cutoff=None,
) -> tuple[Callable[[str, str | None], float], Callable[[int, int, str | None], float]]:
    if cutoff is None:
        cutoff = BACKFILL_CUTOFF
    cache: dict[date, tuple[dict, dict]] = {}

    def _tables(d_iso: str | None):
        if d_iso is None:
            return today_ktc_by_pid, today_pick_table
        d = date.fromisoformat(d_iso[:10])
        if d not in cache:
            snap, _, _ = store.match(d, cutoff)
            if snap is None:
                cache[d] = (today_ktc_by_pid, today_pick_table)  # fallback to today
            else:
                cache[d] = (resolve_ktc_to_player_id(snap, raw_players),
                            build_pick_value_table(snap))
        return cache[d]

    def price_player(pid: str, d_iso: str | None) -> float:
        ktc, _ = _tables(d_iso)
        return _sf(ktc.get(pid))

    def price_pick(season: int, rnd: int, d_iso: str | None) -> float:
        _, pick_table = _tables(d_iso)
        return _sf(pick_table.get((season, rnd)))

    return price_player, price_pick


def compute_realized(
    resolved_dicts: list[dict],
    *,
    current_holders: dict[str, str],
    price_player: Callable[[str, str | None], float],
    price_pick: Callable[[int, int, str | None], float],
) -> dict[str, dict[str, list[float]]]:
    """{transaction_id: {user_id: [per-received-asset realized value, ...]}}."""
    out: dict[str, dict[str, list[float]]] = {}
    for rt in resolved_dicts:
        tx = rt["trade"]["transaction_id"]
        out[tx] = realized_received_values(
            resolved_dicts, tx, current_holders, price_player, price_pick)
    return out
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest api/tests/test_realized_value.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/app/services/realized_value.py api/tests/test_realized_value.py
git commit -m "feat(api): realized-value price providers over KtcSnapshotStore"
```

---

## Task 4: Integrate realized values into the grading stage

Overwrite each trade's `received_ktc` and per-asset breakdown `ktc` with realized values. `snapshot_value_swing` stays computed (diagnostic).

**Files:**
- Modify: `api/app/services/grader.py` (the grading stage, after the at_trade block, ~lines 156-172)

- [ ] **Step 1: Add the realized stage after the at_trade block**

In `api/app/services/grader.py`, immediately after the `if snapshot_store is not None:` at_trade block (ends line 172, before `await progress_cb("stories", ...)`), insert:

```python
        # Realized Trade Value: reprice each side's received haul to what the
        # owner actually realized (held → today, flipped → flip date, dropped → 0).
        # Overwrites received_ktc + per-asset breakdown ktc; snapshot_value_swing
        # stays as a mark-to-market diagnostic.
        if snapshot_store is not None:
            from app.services.realized_value import compute_realized, make_price_providers
            price_player, price_pick = make_price_providers(
                store=snapshot_store, raw_players=raw_players,
                today_ktc_by_pid=supporting["ktc_by_player_id"],
                today_pick_table=supporting["pick_value_table"],
            )
            realized = compute_realized(
                resolved_dicts, current_holders=current_holders,
                price_player=price_player, price_pick=price_pick)
            for tx, by_uid in realized.items():
                g = grades.get(tx)
                if g is None:
                    continue
                g["received_ktc"] = {uid: float(sum(vals)) for uid, vals in by_uid.items()}
                for uid, vals in by_uid.items():
                    rows = (g.get("breakdown") or {}).get(uid) or []
                    for i, v in enumerate(vals):
                        if i < len(rows):
                            rows[i]["ktc"] = float(v)
```

> `resolved_dicts` is already computed in `run()` (line 236: `resolved_dicts = [_to_dict(rt) for rt in resolved]`). **Move that line up** to just before this block so it's available (it currently sits at line 236, after the stories stage). Cut line 236 and paste it immediately before the realized block.

- [ ] **Step 2: Verify the move + insertion didn't break the pipeline**

Run: `pytest api/tests/ -k "grader or chain_cache" -v`
Expected: PASS (existing grader/cache tests still green; `received_ktc` now realized).

- [ ] **Step 3: Commit**

```bash
git add api/app/services/grader.py
git commit -m "feat(api): reprice received_ktc + breakdown to realized values in grading"
```

---

## Task 5: Roll `net_ktc` from realized `received_ktc` + z-score grade

**Files:**
- Modify: `api/app/services/aggregations.py`
- Test: `api/tests/test_aggregations.py`

- [ ] **Step 1: Write the failing test**

Add to `api/tests/test_aggregations.py` (follow the file's existing `ChainCacheEntry` fixture style; adapt the helper names to those already in the file):

```python
def test_net_ktc_rolls_from_realized_received_ktc(make_entry):
    # Two owners, one trade; received_ktc is the realized per-side value.
    entry = make_entry(
        owners={"A": {"owner_name": "A"}, "D": {"owner_name": "D"}},
        resolved_trades=[{"trade": {"transaction_id": "t1", "season": 2026,
                                    "traded_at": "2026-01-01T00:00:00",
                                    "league_id": "L", "week": 1},
                          "sides": {"A": {"received": [], "given": []},
                                    "D": {"received": [], "given": []}}}],
        grades={"t1": {"received_ktc": {"A": 6000.0, "D": 4100.0},
                       "snapshot_value_swing": {"A": 1900.0, "D": -1900.0},
                       "production_total": {"A": 0.0, "D": 0.0}}},
    )
    from app.services.aggregations import _aggregate_owner_rows
    rows = _aggregate_owner_rows(entry, list(entry.resolved_trades))
    assert rows["A"]["net_ktc"] == 6000.0   # realized received, not the swing
    assert rows["D"]["net_ktc"] == 4100.0
```

> If `test_aggregations.py` has no `make_entry` fixture, build the `ChainCacheEntry`
> inline exactly as the other tests in that file do (match their construction).

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest api/tests/test_aggregations.py::test_net_ktc_rolls_from_realized_received_ktc -v`
Expected: FAIL (`net_ktc` currently rolls from `snapshot_value_swing`, so A = 1900, not 6000).

- [ ] **Step 3: Change the rollup source**

In `api/app/services/aggregations.py::_aggregate_owner_rows` (lines 69-90), change the iteration from `snapshot_value_swing` to `received_ktc`:

```python
    for rt in trades:
        g = _grade_for(entry, rt["trade"]["transaction_id"])
        received = g.get("received_ktc") or {}
        swing = g.get("snapshot_value_swing") or {}
        for uid, val in received.items():
            row = rows.setdefault(uid, _blank(uid))
            row["net_ktc"] += float(val or 0)               # realized headline
            at_map = g.get("at_trade_value_swing") or {}
            if uid in at_map:
                row["net_ktc_at_trade"] += float(at_map[uid] or 0)
                row["net_ktc_today_subset"] += float(swing.get(uid, 0) or 0)
            row["production_total"] += float(
                (g.get("production_total") or {}).get(uid, 0) or 0
            )
            row["production_regular"] += float(
                (g.get("production_regular") or {}).get(uid, 0) or 0
            )
            row["production_playoff"] += float(
                (g.get("production_playoff") or {}).get(uid, 0) or 0
            )
            row["production_toilet"] += float(
                (g.get("production_toilet") or {}).get(uid, 0) or 0
            )
            row["trades"] += 1
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest api/tests/test_aggregations.py::test_net_ktc_rolls_from_realized_received_ktc -v`
Expected: PASS.

- [ ] **Step 5: Write the failing z-grade test**

Add to `api/tests/test_aggregations.py`:

```python
def test_letter_grade_is_league_relative():
    from app.services.aggregations import _letter_grade
    # Highest realized net_ktc in the league earns the top grade.
    net = {"A": 18000.0, "B": 9000.0, "C": -2000.0, "D": -11000.0}
    grades = _letter_grade(net)
    assert grades["A"] == "A"
    assert grades["D"] == "D"
    assert grades["A"] != grades["C"]
```

- [ ] **Step 6: Run it to verify it fails**

Run: `pytest api/tests/test_aggregations.py::test_letter_grade_is_league_relative -v`
Expected: FAIL (`_letter_grade` currently takes a single float, not a dict).

- [ ] **Step 7: Replace `_letter_grade` with a z-score grade**

In `api/app/services/aggregations.py`, replace `_letter_grade` (lines 38-51) with:

```python
def _letter_grade(net_ktc_by_uid: dict[str, float]) -> dict[str, str]:
    """League-relative letter grade from realized net_ktc, via z-score buckets.

    Realized Trade Value is all-positive and league-specific, so absolute
    thresholds don't transfer. z-score across the league instead."""
    vals = list(net_ktc_by_uid.values())
    n = len(vals)
    if n == 0:
        return {}
    mean = sum(vals) / n
    sd = (sum((v - mean) ** 2 for v in vals) / n) ** 0.5

    def bucket(z: float) -> str:
        if z >= 1.25:
            return "A"
        if z >= 0.75:
            return "A−"
        if z >= 0.25:
            return "B+"
        if z >= -0.25:
            return "B"
        if z >= -0.75:
            return "B−"
        if z >= -1.25:
            return "C"
        return "D"

    if sd == 0:
        return {uid: "B" for uid in net_ktc_by_uid}
    return {uid: bucket((v - mean) / sd) for uid, v in net_ktc_by_uid.items()}
```

- [ ] **Step 8: Update the `build_dashboard` call site**

In `api/app/services/aggregations.py::build_dashboard` (lines 248-266), compute grades once and look up per row:

```python
    sorted_rows = sorted(
        rows.values(), key=lambda r: r["net_ktc"], reverse=True
    )
    grade_by_uid = _letter_grade({r["user_id"]: r["net_ktc"] for r in sorted_rows})
    standings = [
        StandingRow(
            rank=i + 1,
            user_id=r["user_id"], owner=owner_ref(entry, r["user_id"]),
            net_ktc=r["net_ktc"], production_total=r["production_total"],
            production_regular=r["production_regular"],
            production_playoff=r["production_playoff"],
            production_toilet=r["production_toilet"],
            trades=r["trades"],
            grade=grade_by_uid.get(r["user_id"], "B"),
            net_ktc_at_trade=r["net_ktc_at_trade"],
            net_ktc_aged=r["net_ktc_today_subset"] - r["net_ktc_at_trade"],
        )
        for i, r in enumerate(sorted_rows)
    ]
```

- [ ] **Step 9: Run the grade test to verify it passes**

Run: `pytest api/tests/test_aggregations.py -v`
Expected: PASS (both new tests + the rest of the file; fix any other test in the file that asserted the old absolute-threshold grade or `net_ktc`-from-swing behavior to match the realized model).

- [ ] **Step 10: Commit**

```bash
git add api/app/services/aggregations.py api/tests/test_aggregations.py
git commit -m "feat(api): net_ktc from realized received_ktc; league-relative z-grade"
```

---

## Task 6: Point hero/records/latest-trades value lens at `received_ktc`

The ktc lens should now read realized received value (head-to-head), not the swing.

**Files:**
- Modify: `api/app/services/aggregations.py` (`_trade_swing`, `_latest_trades`)

- [ ] **Step 1: Update `_trade_swing` for the ktc lens**

In `api/app/services/aggregations.py::_trade_swing` (lines 94-100), change the ktc branch:

```python
def _trade_swing(
    grade: dict[str, Any], lens: Lens, uid: str
) -> float:
    if lens == "production":
        return float((grade.get("production_total") or {}).get(uid, 0) or 0)
    # ktc (default): realized received Trade Value (head-to-head, not a swing)
    return float((grade.get("received_ktc") or {}).get(uid, 0) or 0)
```

- [ ] **Step 2: Update `_latest_trades` ktc field**

In `_latest_trades` (line 190), change:

```python
        ktc_swings = g.get("received_ktc") or {}
```

(leave `prod_swings = g.get("production_total") or {}` unchanged.)

- [ ] **Step 3: Run aggregation + dashboard tests**

Run: `pytest api/tests/test_aggregations.py -v`
Expected: PASS (adjust any hero-stat test that asserted swing-based ktc values to the realized head-to-head numbers).

- [ ] **Step 4: Commit**

```bash
git add api/app/services/aggregations.py
git commit -m "feat(api): hero + latest-trades ktc lens reads realized received_ktc"
```

---

## Task 7: Trade-detail copy + web tooltip — Trade Value is no longer a swing

`trade_view.py` already exposes `received_ktc` per side (line 120-122), and `web/components/TradeStatTable.tsx` renders per-asset `ktc` totals — both now carry realized values automatically. Only the **explanatory copy** needs to stop saying "swing" / "today's market value."

**Files:**
- Modify: `web/components/StandingsTable.tsx` (the Trade Value column tooltip)

- [ ] **Step 1: Update the Trade Value tooltip copy**

In `web/components/StandingsTable.tsx`, in the `COLS` array, replace the `net_ktc` tooltip:

```tsx
  {
    key: "net_ktc", plain: "Trade Value",
    tooltip: { title: "Trade value (realized)", body: "Realized market value of what this owner's trades brought in: each received asset valued at what they got for it — today's KTC if still held, its value when they flipped it, or 0 if dropped. Received-only, like the points columns.", formula: "Σ realized value of received assets" },
  },
```

- [ ] **Step 2: Verify the web app typechecks**

Run: `cd web && npx tsc --noEmit`
Expected: no output (clean).

- [ ] **Step 3: Commit**

```bash
git add web/components/StandingsTable.tsx
git commit -m "docs(web): Trade Value tooltip reflects realized (received-only) definition"
```

---

## Task 8: Full-suite regression + smoke

**Files:** none (verification only).

- [ ] **Step 1: Run the engine + API suites**

Run: `pytest -q && pytest api/tests -q`
Expected: PASS. Triage any failure that asserted the old swing-based `net_ktc`, absolute-threshold grade, or hero ktc swing — update those expectations to the realized model (do not weaken assertions to pass; recompute the correct realized expected value).

- [ ] **Step 2: Manual smoke (optional, needs a warm cache)**

Run: `make dev-api` + `make dev-web`, refresh a league, confirm the standings Trade Value column is all-positive (received-only), grades spread A→D league-relatively, and a trade-detail page's per-asset KTC totals reflect realized values (a flipped asset shows its flip-date value, a dropped asset shows 0).

- [ ] **Step 3: Final commit (if any test expectations were updated)**

```bash
git add -A
git commit -m "test: align expectations to realized Trade Value"
```

---

## Self-Review

**Spec coverage:**
- Realized model (held/flipped/dropped, picks) → Task 2. ✓
- Disposition inferred from trade history (no drop ingestion) → Task 2 `_player_value`. ✓
- Flip-date pricing via `KtcSnapshotStore.match` → Task 3. ✓
- `received_ktc` becomes realized; breakdown repriced → Task 4. ✓
- `net_ktc` rolls from realized → Task 5. ✓
- Letter grade re-derived (open question 1) → Task 5 z-grade. ✓
- Not zero-sum / hero+records read received → Task 6. ✓
- GM Rating `value` signal: `leaderboard.owner_pillars` reads `r["net_ktc"]`, which is now realized — **no code change needed**, picks up automatically. Verified by Task 8 GM-rating tests staying green. ✓
- Trade Value back on summary cards: that lives on the `feat/league-summary-cards` branch; this branch makes the number meaningful (non-zero-sum). Re-adding the card is a follow-up on that branch, noted in the roadmap memory, **not a task here**. ✓
- Data constraint (pre-history flips) → Task 3 fallback-to-today + comment. ✓
- `net_ktc_at_trade`/`net_ktc_aged` kept (open question 2), `at_trade.py` kept (open question 3), no cache bump (open question 4) → Decisions section. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code. The one "adapt to existing fixture" note (Task 5 Step 1) points at a concrete pattern in the same file, not a placeholder.

**Type consistency:** `realized_received_values(resolved_trades, root_trade_id, current_holders, price_player, price_pick) -> dict[str, list[float]]` used identically in Task 2 (def), Task 3 (`compute_realized`), and Task 4 (call). `make_price_providers(...)` returns `(price_player, price_pick)` consumed in Task 4. `_letter_grade(dict) -> dict` updated at its only call site (Task 5 Step 8). `received_ktc` is the shared key across Tasks 4/5/6 and existing `trade_view.py`.
