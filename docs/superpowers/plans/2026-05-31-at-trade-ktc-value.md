> _Historical doc — paths/names have changed. Repo is now `Code Apps/public-dynasty` (GitHub `tkeefe66/public-dynasty-app`), Railway project **shimmering-nature**, live at https://ffbdynasty.com. Ignore stale refs to `sleeper-dynasty` / `sleeper-trade-grader` / `web-production-f949`._

# At-Trade KTC Value Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show each trade's KTC value **as of its trade date** (plus the aged delta vs today), captured opportunistically from daily KTC snapshots, backfilling only post-draft trades with today's snapshot.

**Architecture:** A new `KtcSnapshotStore` persists one dated KTC table per day on refresh. A new at-trade grading pass values each resolved trade against the snapshot matched to its date — valuing picks **as picks** (dated round-level value, ignoring the drafted-player annotation). Per-trade results land in the stored `grades` dict; owner aggregates are summed in the existing API aggregation layer. Frontend shows At Trade + Δ Aged. The "today" lens, `ChainCache` blob, and 409/SSE contract are unchanged.

**Tech Stack:** Python 3.11, dataclasses/pydantic, pytest + pytest-asyncio (API), Next.js/TS (web). Spec: `docs/superpowers/specs/2026-05-31-at-trade-ktc-value-design.md`.

Engine tests: `.venv/bin/python -m pytest tests/ -q --import-mode=importlib`. API tests: `cd api && ../.venv/bin/python -m pytest -q`. Web typecheck: `cd web && npx tsc --noEmit`.

---

## File Structure

- `api/app/services/ktc_snapshot_store.py` — **new.** Capture + 3-branch match.
- `api/app/services/at_trade.py` — **new.** At-trade grading pass + `BACKFILL_CUTOFF`.
- `src/sleeper_dynasty/engine/trade_grader.py` — `_ktc_value`/`grade_snapshot_value` gain `ignore_drafted_player`.
- `api/app/services/grader_io.py` — extract `resolve_ktc_to_player_id`; capture hook; thread store.
- `api/app/services/grader.py` — build store, run at-trade pass, merge fields + aged into grades.
- `api/app/services/trade_view.py` + `api/app/models/trade.py` — per-trade at-trade fields.
- `api/app/services/aggregations.py` + `api/app/services/owner_view.py` + `api/app/models/owner.py` — owner at-trade aggregate.
- `web/lib/types.ts`, `web/components/TradeSidePanel.tsx`, `web/components/OwnersTab.tsx` — UI.

---

## Task 1: `KtcSnapshotStore`

**Files:**
- Create: `api/app/services/ktc_snapshot_store.py`
- Test: `api/tests/test_ktc_snapshot_store.py`

- [ ] **Step 1: Write the failing tests** — create `api/tests/test_ktc_snapshot_store.py`:

```python
from __future__ import annotations

from datetime import date

from app.services.ktc_snapshot_store import KtcSnapshotStore
from sleeper_dynasty.models.player import KTCValue


def _vals(qb=8000):
    return {
        "josh allen": KTCValue(name="Josh Allen", normalized_name="josh allen",
                               position="QB", superflex_value=qb, one_qb_value=qb - 100),
        "2027 1st": KTCValue(name="2027 Early 1st", normalized_name="2027 early 1st",
                             position="PICK", superflex_value=6000, one_qb_value=5800),
    }


def test_capture_writes_once_per_day(tmp_path):
    store = KtcSnapshotStore(cache_dir=tmp_path)
    assert store.capture(_vals(), date(2026, 5, 31)) is True
    assert store.capture(_vals(qb=1), date(2026, 5, 31)) is False  # already exists
    snap = store._load(store._path(date(2026, 5, 31)))
    assert snap["josh allen"].superflex_value == 8000  # not overwritten


def test_capture_skips_empty(tmp_path):
    store = KtcSnapshotStore(cache_dir=tmp_path)
    assert store.capture({}, date(2026, 5, 31)) is False
    assert store.list_dates() == []


def test_match_returns_latest_on_or_before(tmp_path):
    store = KtcSnapshotStore(cache_dir=tmp_path)
    store.capture(_vals(qb=7000), date(2026, 5, 20))
    store.capture(_vals(qb=8000), date(2026, 5, 28))
    snap, d, approx = store.match(date(2026, 5, 30), cutoff=date(2026, 5, 1))
    assert d == date(2026, 5, 28) and approx is False
    assert snap["josh allen"].superflex_value == 8000


def test_match_backfill_uses_earliest_when_post_cutoff(tmp_path):
    store = KtcSnapshotStore(cache_dir=tmp_path)
    store.capture(_vals(), date(2026, 5, 31))           # only a later snapshot exists
    snap, d, approx = store.match(date(2026, 5, 3), cutoff=date(2026, 5, 1))
    assert d == date(2026, 5, 31) and approx is True    # earliest, flagged approx
    assert snap is not None


def test_match_blank_before_cutoff(tmp_path):
    store = KtcSnapshotStore(cache_dir=tmp_path)
    store.capture(_vals(), date(2026, 5, 31))
    snap, d, approx = store.match(date(2026, 3, 15), cutoff=date(2026, 5, 1))
    assert snap is None and d is None and approx is False


def test_corrupt_file_ignored(tmp_path):
    store = KtcSnapshotStore(cache_dir=tmp_path)
    store.capture(_vals(), date(2026, 5, 31))
    (tmp_path / "snapshots" / "ktc_2026-05-31.json").write_text("{ not json")
    assert store.match(date(2026, 5, 31), cutoff=date(2026, 5, 1)) == (None, None, False)
```

- [ ] **Step 2: Run to verify failure** — `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/api" && ../.venv/bin/python -m pytest tests/test_ktc_snapshot_store.py -q` → `ModuleNotFoundError`.

- [ ] **Step 3: Implement** — create `api/app/services/ktc_snapshot_store.py`:

```python
"""Dated KTC snapshots for at-trade valuation.

One JSON file per calendar day (snapshots/ktc_YYYY-MM-DD.json) holding the raw
name-keyed KTC table (includes pick entries). Captured opportunistically on
refresh. Snapshots are immutable history — no TTL.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

from sleeper_dynasty.models.player import KTCValue

log = logging.getLogger(__name__)

_SUBDIR = "snapshots"


class KtcSnapshotStore:
    def __init__(self, cache_dir: Path):
        self.dir = Path(cache_dir) / _SUBDIR
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, d: date) -> Path:
        return self.dir / f"ktc_{d.isoformat()}.json"

    def capture(self, ktc_values: dict[str, KTCValue], today: date) -> bool:
        """Write today's snapshot if absent and non-empty. Returns True if written."""
        if not ktc_values:
            return False
        path = self._path(today)
        if path.exists():
            return False
        path.write_text(json.dumps([v.to_dict() for v in ktc_values.values()]))
        return True

    def _load(self, path: Path) -> dict[str, KTCValue] | None:
        if not path.exists():
            return None
        try:
            rows = json.loads(path.read_text())
            return {v.normalized_name: v for v in (KTCValue.from_dict(r) for r in rows)}
        except (OSError, ValueError, KeyError) as e:
            log.warning("KTC snapshot unreadable (%s); ignoring", e)
            return None

    def list_dates(self) -> list[date]:
        out: list[date] = []
        for p in self.dir.glob("ktc_*.json"):
            try:
                out.append(date.fromisoformat(p.stem[len("ktc_"):]))
            except ValueError:
                continue
        return sorted(out)

    def match(
        self, trade_date: date, cutoff: date
    ) -> tuple[dict[str, KTCValue] | None, date | None, bool]:
        """Snapshot to value a trade made on trade_date.

        1. latest snapshot with date <= trade_date  -> (snap, date, approx=False)
        2. else if trade_date >= cutoff             -> earliest snapshot, approx=True
        3. else                                     -> (None, None, False)
        A snapshot that fails to load is treated as absent.
        """
        dates = self.list_dates()
        if not dates:
            return (None, None, False)
        before = [d for d in dates if d <= trade_date]
        if before:
            d = max(before)
            snap = self._load(self._path(d))
            return (snap, d, False) if snap is not None else (None, None, False)
        if trade_date >= cutoff:
            d = min(dates)
            snap = self._load(self._path(d))
            return (snap, d, True) if snap is not None else (None, None, False)
        return (None, None, False)
```

- [ ] **Step 4: Run** → PASS (6 tests). **Step 5: Commit**
```bash
git add api/app/services/ktc_snapshot_store.py api/tests/test_ktc_snapshot_store.py
git commit -m "feat: KtcSnapshotStore captures + matches dated KTC tables"
```

---

## Task 2: `ignore_drafted_player` flag on the snapshot lens

**Files:**
- Modify: `src/sleeper_dynasty/engine/trade_grader.py` (`_ktc_value` ~29-61, `grade_snapshot_value` ~64-75)
- Test: `tests/test_trade_grader.py`

At-trade valuation must treat a traded pick as a **pick** (dated pick table), never the player it became — because at trade time it wasn't drafted.

- [ ] **Step 1: Write the failing test** — append to `tests/test_trade_grader.py`:

```python
def test_ignore_drafted_player_values_pick_via_table():
    # A pick annotated with its drafted player. With ignore_drafted_player=True
    # it must use the pick table, NOT the player's KTC.
    rt = _stub_resolved_trade(
        received_by_uid={
            "u1": [PickAsset(season=2026, round=1, original_owner_user_id="u_a",
                             drafted_player_id="p_x", drafted_player_name="X")],
            "u2": [],
        },
        given_by_uid={
            "u1": [],
            "u2": [PickAsset(season=2026, round=1, original_owner_user_id="u_a",
                             drafted_player_id="p_x", drafted_player_name="X")],
        },
    )
    ktc = {"p_x": KTCValue(name="X", normalized_name="x", position="WR",
                           superflex_value=9000, one_qb_value=8900)}
    pick_values = {(2026, 1): KTCValue(name="2026 R1", normalized_name="2026 r1",
                                       position="PICK", superflex_value=5000, one_qb_value=4800)}
    swings = grade_snapshot_value(rt, ktc, fmt="superflex", pick_values=pick_values,
                                  ignore_drafted_player=True)
    assert swings["u1"] == pytest.approx(5000)   # pick-table value, not 9000
    assert swings["u2"] == pytest.approx(-5000)
```

- [ ] **Step 2: Run** → FAIL (`unexpected keyword argument 'ignore_drafted_player'`).

- [ ] **Step 3: Implement** — in `src/sleeper_dynasty/engine/trade_grader.py`, add the param to `_ktc_value` and `grade_snapshot_value`. Replace the `PickAsset` branch of `_ktc_value` and both signatures:

`_ktc_value` signature gains `ignore_drafted_player: bool = False` (last param), and its PickAsset branch becomes:

```python
    if isinstance(asset, PickAsset):
        if asset.drafted_player_id is not None and not ignore_drafted_player:
            v = ktc.get(asset.drafted_player_id)
            if v is None:
                log.warning(
                    "No KTC value for drafted pick player %s (%s, %d round %d)",
                    asset.drafted_player_id, asset.drafted_player_name,
                    asset.season, asset.round,
                )
            return _from_ktc(v)
        table = pick_values or {}
        return _from_ktc(table.get((asset.season, asset.round)))
    return 0.0
```

`grade_snapshot_value` gains `ignore_drafted_player: bool = False` and forwards it:

```python
def grade_snapshot_value(
    rt: ResolvedTrade,
    ktc_values: dict[str, KTCValue],
    fmt: str = "superflex",
    pick_values: dict[tuple[int, int], KTCValue] | None = None,
    ignore_drafted_player: bool = False,
) -> dict[str, float]:
    """Compute snapshot KTC value swing per side."""
    swings: dict[str, float] = {}
    for uid, side in rt.sides.items():
        received = sum(_ktc_value(a, ktc_values, fmt, pick_values, ignore_drafted_player)
                       for a in side.received)
        given = sum(_ktc_value(a, ktc_values, fmt, pick_values, ignore_drafted_player)
                    for a in side.given)
        swings[uid] = received - given
    return swings
```

(`grade_trade` is unchanged — it calls `grade_snapshot_value` without the flag, so the today lens keeps using the drafted player.)

- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/test_trade_grader.py -q --import-mode=importlib` → PASS. **Step 5: Commit**
```bash
git add src/sleeper_dynasty/engine/trade_grader.py tests/test_trade_grader.py
git commit -m "feat: ignore_drafted_player flag values picks as picks (for at-trade)"
```

---

## Task 3: Extract `resolve_ktc_to_player_id`

**Files:**
- Modify: `api/app/services/grader_io.py` (the inline KTC name→player_id match, ~80-89)
- Test: `api/tests/test_grader_io.py`

The today path and each dated snapshot both need KTC keyed by `player_id`. Extract the **KTC-only** match (NOT the FantasyCalc fallback — FC is current-only and must not pollute dated snapshots).

- [ ] **Step 1: Write the failing test** — append to `api/tests/test_grader_io.py`:

```python
def test_resolve_ktc_to_player_id_matches_by_name():
    from app.services.grader_io import resolve_ktc_to_player_id
    from sleeper_dynasty.models.player import KTCValue

    ktc = {"josh allen": KTCValue(name="Josh Allen", normalized_name="josh allen",
                                  position="QB", superflex_value=8000, one_qb_value=7900)}
    raw_players = {"p_allen": {"full_name": "Josh Allen", "position": "QB"},
                   "p_other": {"full_name": "Nobody KTC", "position": "WR"}}
    out = resolve_ktc_to_player_id(ktc, raw_players)
    assert out["p_allen"].superflex_value == 8000
    assert "p_other" not in out
```

- [ ] **Step 2: Run** → FAIL (`cannot import name 'resolve_ktc_to_player_id'`).

- [ ] **Step 3: Implement + refactor** — in `api/app/services/grader_io.py`, add:

```python
def resolve_ktc_to_player_id(
    ktc_values: dict[str, KTCValue], raw_players: dict
) -> dict[str, KTCValue]:
    """Map name-keyed KTC values onto Sleeper player_ids (KTC only, no FC)."""
    out: dict[str, KTCValue] = {}
    for pid, p in raw_players.items():
        if not isinstance(p, dict):
            continue
        full = (p.get("full_name") or
                f"{p.get('first_name','')} {p.get('last_name','')}".strip())
        v = ktc_values.get(normalize_player_name(full)) if full else None
        if v is not None:
            out[pid] = v
    return out
```

Then in `pull_supporting_data`, replace the inline loop that builds
`ktc_by_player_id` (the `for pid, p in raw_players.items(): ...` block) with:

```python
    ktc_by_player_id: dict[str, KTCValue] = resolve_ktc_to_player_id(ktc_values, raw_players)
```

(The FantasyCalc fallback loop that follows stays exactly as-is.)

- [ ] **Step 4: Run** the api suite → PASS (new test + existing, behavior unchanged). **Step 5: Commit**
```bash
git add api/app/services/grader_io.py api/tests/test_grader_io.py
git commit -m "refactor: extract resolve_ktc_to_player_id (reused by at-trade)"
```

---

## Task 4: Capture snapshot on refresh

**Files:**
- Modify: `api/app/services/grader_io.py` (`pull_supporting_data` signature + after KTC fetch)
- Test: `api/tests/test_grader_io.py`

- [ ] **Step 1: Write the failing test** — append to `api/tests/test_grader_io.py`:

```python
@pytest.mark.asyncio
async def test_pull_supporting_data_captures_snapshot(tmp_path, monkeypatch):
    import app.services.grader_io as mod
    async def _ktc(): 
        from sleeper_dynasty.models.player import KTCValue
        return {"josh allen": KTCValue(name="Josh Allen", normalized_name="josh allen",
                                       position="QB", superflex_value=8000, one_qb_value=7900)}
    async def _fc(): return {}
    monkeypatch.setattr(mod, "fetch_ktc_values", _ktc)
    monkeypatch.setattr(mod, "fetch_fantasycalc_values", _fc)

    from app.services.ktc_snapshot_store import KtcSnapshotStore
    store = KtcSnapshotStore(cache_dir=tmp_path)
    await pull_supporting_data(_StubClientNoLeagues(), [], players={"p_allen": {"full_name": "Josh Allen"}},
                               snapshot_store=store)
    assert len(store.list_dates()) == 1   # today's snapshot written
```

Add this stub near the top of the test file if not present:

```python
class _StubClientNoLeagues:
    async def get_players(self): return {}
```

- [ ] **Step 2: Run** → FAIL (`unexpected keyword argument 'snapshot_store'`).

- [ ] **Step 3: Implement** — change `pull_supporting_data` signature to add `snapshot_store=None`:

```python
async def pull_supporting_data(
    client, chain, players=None, league_cache=None, snapshot_store=None,
) -> dict[str, Any]:
```

Immediately after `pick_value_table = build_pick_value_table(ktc_values)` (which follows the KTC fetch), add:

```python
    if snapshot_store is not None and ktc_values:
        from datetime import date
        snapshot_store.capture(ktc_values, date.today())
```

- [ ] **Step 4: Run** the api suite → PASS. **Step 5: Commit**
```bash
git add api/app/services/grader_io.py api/tests/test_grader_io.py
git commit -m "feat: capture today's KTC snapshot during pull_supporting_data"
```

---

## Task 5: At-trade grading pass

**Files:**
- Create: `api/app/services/at_trade.py`
- Test: `api/tests/test_at_trade.py`

- [ ] **Step 1: Write the failing tests** — create `api/tests/test_at_trade.py`:

```python
from __future__ import annotations

from datetime import date, datetime, timezone

from app.services.at_trade import compute_at_trade, BACKFILL_CUTOFF
from app.services.ktc_snapshot_store import KtcSnapshotStore
from sleeper_dynasty.models.player import KTCValue
from sleeper_dynasty.models.trade import (
    PickAsset, PlayerAsset, ResolvedTrade, Trade, TradeSide,
)


def _rt(tx_id, traded_at, received_by_uid, given_by_uid):
    sides = {uid: TradeSide(uid, list(received_by_uid[uid]), list(given_by_uid[uid]))
             for uid in received_by_uid}
    t = Trade(transaction_id=tx_id, league_id="L", season=2026, week=1,
              traded_at=traded_at, sides=sides)
    return ResolvedTrade(trade=t, sides=sides)


def _store_with_today(tmp_path, d):
    store = KtcSnapshotStore(cache_dir=tmp_path)
    store.capture({
        "josh allen": KTCValue(name="Josh Allen", normalized_name="josh allen",
                               position="QB", superflex_value=8000, one_qb_value=7900),
        "2026 early 1st": KTCValue(name="2026 Early 1st", normalized_name="2026 early 1st",
                                   position="PICK", superflex_value=5000, one_qb_value=4800),
    }, d)
    return store


def _players():
    return {"p_allen": {"full_name": "Josh Allen", "position": "QB"}}


def test_backfilled_trade_values_player_and_picks(tmp_path):
    store = _store_with_today(tmp_path, date(2026, 5, 31))
    rt = _rt("tx1", datetime(2026, 5, 3, tzinfo=timezone.utc),
             received_by_uid={"u1": [PlayerAsset("p_allen", "Josh Allen")], "u2": []},
             given_by_uid={"u1": [], "u2": [PlayerAsset("p_allen", "Josh Allen")]})
    out = compute_at_trade([rt], _players(), store)
    g = out["tx1"]
    assert g["at_trade_approx"] is True            # before first capture, post-cutoff
    assert g["at_trade_snapshot_date"] == "2026-05-31"
    assert g["at_trade_value_swing"]["u1"] == 8000.0


def test_pick_valued_as_pick_not_drafted_player(tmp_path):
    store = _store_with_today(tmp_path, date(2026, 5, 31))
    # A pick annotated with a drafted player; at-trade must use the pick table.
    rt = _rt("tx2", datetime(2026, 5, 10, tzinfo=timezone.utc),
             received_by_uid={
                 "u1": [PickAsset(season=2026, round=1, original_owner_user_id="u1",
                                  drafted_player_id="p_allen", drafted_player_name="Josh Allen")],
                 "u2": []},
             given_by_uid={
                 "u1": [],
                 "u2": [PickAsset(season=2026, round=1, original_owner_user_id="u1",
                                  drafted_player_id="p_allen", drafted_player_name="Josh Allen")]})
    out = compute_at_trade([rt], _players(), store)
    assert out["tx2"]["at_trade_value_swing"]["u1"] == 5000.0   # pick table, not 8000


def test_pre_cutoff_trade_is_blank(tmp_path):
    store = _store_with_today(tmp_path, date(2026, 5, 31))
    rt = _rt("tx3", datetime(2026, 3, 1, tzinfo=timezone.utc),
             received_by_uid={"u1": [PlayerAsset("p_allen", "Josh Allen")], "u2": []},
             given_by_uid={"u1": [], "u2": [PlayerAsset("p_allen", "Josh Allen")]})
    out = compute_at_trade([rt], _players(), store)
    assert out["tx3"]["at_trade_value_swing"] is None
    assert out["tx3"]["at_trade_approx"] is False
```

- [ ] **Step 2: Run** → FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement** — create `api/app/services/at_trade.py`:

```python
"""At-trade KTC valuation: value each trade against the snapshot matched to its date."""

from __future__ import annotations

from datetime import date

from app.services.grader_io import resolve_ktc_to_player_id
from sleeper_dynasty.api.ktc import build_pick_value_table
from sleeper_dynasty.engine.trade_grader import grade_snapshot_value

# Trades on/after this date may be backfilled with today's snapshot (post-draft,
# values settled). Earlier trades stay blank — FA + the NFL draft moved KTC.
BACKFILL_CUTOFF = date(2026, 5, 1)


def compute_at_trade(resolved_trades, raw_players, store, cutoff=BACKFILL_CUTOFF):
    """Return {transaction_id: {at_trade_value_swing|None, at_trade_approx, at_trade_snapshot_date}}.

    Picks are valued as picks (dated pick table), never the drafted player.
    Dated tables are built once per distinct trade date.
    """
    by_date: dict[date, tuple] = {}
    out: dict[str, dict] = {}
    for rt in resolved_trades:
        d = rt.trade.traded_at.date()
        if d not in by_date:
            snap, snap_date, approx = store.match(d, cutoff)
            if snap is None:
                by_date[d] = (None, None, None, False)
            else:
                ktc_by_pid = resolve_ktc_to_player_id(snap, raw_players)
                pick_table = build_pick_value_table(snap)
                by_date[d] = (ktc_by_pid, pick_table, snap_date, approx)
        ktc_by_pid, pick_table, snap_date, approx = by_date[d]
        tx = rt.trade.transaction_id
        if ktc_by_pid is None:
            out[tx] = {"at_trade_value_swing": None, "at_trade_approx": False,
                       "at_trade_snapshot_date": None}
        else:
            swing = grade_snapshot_value(rt, ktc_by_pid, fmt="superflex",
                                         pick_values=pick_table, ignore_drafted_player=True)
            out[tx] = {"at_trade_value_swing": swing, "at_trade_approx": approx,
                       "at_trade_snapshot_date": snap_date.isoformat()}
    return out
```

- [ ] **Step 4: Run** → PASS (3 tests). **Step 5: Commit**
```bash
git add api/app/services/at_trade.py api/tests/test_at_trade.py
git commit -m "feat: at-trade grading pass (picks as picks, post-cutoff backfill)"
```

---

## Task 6: Wire at-trade into `GraderService.run`

**Files:**
- Modify: `api/app/services/grader.py` (`run`)
- Test: `api/tests/test_grader_service.py`

- [ ] **Step 1: Write the failing test** — append to `api/tests/test_grader_service.py`:

```python
@pytest.mark.asyncio
async def test_run_merges_at_trade_fields_into_grades(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from datetime import date
    import app.services.grader_io as gio
    import app.services.at_trade as at_trade_mod
    from app.services.grader import GraderService

    # One sealed league with one trade of Josh Allen, dated post-cutoff.
    leagues = [SimpleNamespace(league_id="L1", season=2026, name="Bros",
                               playoff_week_start=15, total_rosters=2, status="complete")]
    trade_tx = {"transaction_id": "tx1", "type": "trade", "status": "complete",
                "leg": 1, "created": 1746230400000,  # 2026-05-03
                "roster_ids": [1, 2], "adds": {"p_allen": 2}, "drops": {"p_allen": 1},
                "draft_picks": [], "waiver_budget": []}

    class C:
        async def walk_league_history(self, lid): return leagues
        async def get_players(self): return {"p_allen": {"full_name": "Josh Allen", "position": "QB"}}
        async def get_users(self, lid): return {"u_a": {"display_name": "A"}, "u_b": {"display_name": "B"}}
        async def get_rosters(self, lid):
            return [SimpleNamespace(roster_id=1, owner_id="u_a"),
                    SimpleNamespace(roster_id=2, owner_id="u_b")]
        async def get_transactions(self, lid, w): return [trade_tx] if w == 1 else []
        async def get_drafts(self, lid): return []
        async def get_draft_picks(self, did): return []
        @property
        def _client(self):
            class H:
                async def get(self, url):
                    class R:
                        def raise_for_status(self): pass
                        def json(self): return []
                    return R()
            return H()

    async def _ktc():
        from sleeper_dynasty.models.player import KTCValue
        return {"josh allen": KTCValue(name="Josh Allen", normalized_name="josh allen",
                                       position="QB", superflex_value=8000, one_qb_value=7900)}
    async def _fc(): return {}
    monkeypatch.setattr(gio, "fetch_ktc_values", _ktc)
    monkeypatch.setattr(gio, "fetch_fantasycalc_values", _fc)
    # Pin the backfill cutoff so the 2026-05-03 trade is in range regardless of today.
    monkeypatch.setattr(at_trade_mod, "BACKFILL_CUTOFF", date(2020, 1, 1))

    async def cb(*a, **k): pass
    entry = await GraderService().run(client=C(), current_league_id="L1",
                                      progress_cb=cb, cache_dir=tmp_path)
    g = entry.grades["tx1"]
    assert "at_trade_value_swing" in g
    assert g["at_trade_value_swing"]["u_b"] == 8000.0      # received Allen
    assert g["aged_value_swing"]["u_b"] == 0.0             # today == at-trade (same snapshot)
    assert g["at_trade_approx"] is True
```

- [ ] **Step 2: Run** → FAIL (`KeyError: 'at_trade_value_swing'`).

- [ ] **Step 3: Implement** — in `api/app/services/grader.py`:

Add imports:
```python
from app.services.ktc_snapshot_store import KtcSnapshotStore
from app.services.at_trade import compute_at_trade
```

After `league_cache` is constructed (Task added it in Phase 2), construct the
snapshot store from the same `cache_dir`:
```python
        snapshot_store = (
            KtcSnapshotStore(cache_dir=cache_dir) if cache_dir is not None else None
        )
```

Pass the store into supporting data — change the `_pull_supporting_data(...)`
call to add `snapshot_store=snapshot_store`:
```python
        supporting = await _pull_supporting_data(
            client, chain, players=raw_players, league_cache=league_cache,
            snapshot_store=snapshot_store,
        )
```

After the grading loop builds `grades` (the `for rt in resolved:` loop) and
BEFORE constructing `ChainCacheEntry`, add the at-trade merge:
```python
        if snapshot_store is not None:
            at_trade = compute_at_trade(resolved, raw_players, snapshot_store)
            for rt in resolved:
                tx = rt.trade.transaction_id
                info = at_trade.get(tx) or {}
                g = grades.get(tx)
                if g is None:
                    continue
                g["at_trade_value_swing"] = info.get("at_trade_value_swing")
                g["at_trade_approx"] = info.get("at_trade_approx", False)
                g["at_trade_snapshot_date"] = info.get("at_trade_snapshot_date")
                at = info.get("at_trade_value_swing")
                today = g.get("snapshot_value_swing") or {}
                g["aged_value_swing"] = (
                    {uid: float(today.get(uid, 0.0)) - float(at[uid]) for uid in at}
                    if at else None
                )
```

(`grades[tx]` is the `_to_dict`'d `TradeGrade` — a plain dict — so assigning new
keys is fine; they serialize into the `ChainCache` blob automatically.)

- [ ] **Step 4: Run** the api suite → PASS. **Step 5: Commit**
```bash
git add api/app/services/grader.py api/tests/test_grader_service.py
git commit -m "feat: GraderService merges at-trade swing + aged delta into grades"
```

---

## Task 7: Per-trade API surface

**Files:**
- Modify: `api/app/models/trade.py` (`TradeSideView`), `api/app/services/trade_view.py`
- Test: `api/tests/test_trade.py` (or wherever trade-detail is tested)

- [ ] **Step 1: Write the failing test** — append to `api/tests/test_trade.py`:

```python
def test_trade_detail_includes_at_trade_fields():
    from app.services.trade_view import build_trade_detail
    from app.services.chain_cache import ChainCacheEntry

    entry = ChainCacheEntry(
        league_id="L1",
        chain=[], league_name_by_id={"L1": "Bros"}, league_season_by_id={"L1": 2026},
        display_names={"u_a": "A", "u_b": "B"}, playoff_weeks_by_league={"L1": 15},
        roster_to_user_by_league={"L1": {1: "u_a", 2: "u_b"}},
        resolved_trades=[{
            "trade": {"transaction_id": "tx1", "league_id": "L1", "season": 2026,
                      "week": 1, "traded_at": "2026-05-03T00:00:00+00:00"},
            "sides": {"u_b": {"received": [], "given": []}},
        }],
        grades={"tx1": {
            "snapshot_value_swing": {"u_b": 8500.0},
            "at_trade_value_swing": {"u_b": 8000.0},
            "aged_value_swing": {"u_b": 500.0},
            "at_trade_approx": True, "at_trade_snapshot_date": "2026-05-31",
            "hindsight_production_swing": {"u_b": 0.0},
        }},
        cached_at="t", warnings=[],
    )
    resp = build_trade_detail(entry, "tx1")
    side = next(s for s in resp.sides if s.user_id == "u_b")
    assert side.at_trade_ktc_swing == 8000.0
    assert side.aged_ktc_swing == 500.0
    assert side.at_trade_approx is True
```

- [ ] **Step 2: Run** → FAIL (`at_trade_ktc_swing` not a field).

- [ ] **Step 3: Implement** — in `api/app/models/trade.py`, add to `TradeSideView`:

```python
    at_trade_ktc_swing: float | None = None
    aged_ktc_swing: float | None = None
    at_trade_approx: bool = False
    at_trade_snapshot_date: str | None = None
```

In `api/app/services/trade_view.py`, inside the side loop, read them from `grade`
and pass to `TradeSideView(...)`:

```python
        at_swing = (grade.get("at_trade_value_swing") or {})
        aged = (grade.get("aged_value_swing") or {})
        sides.append(TradeSideView(
            ...,  # existing fields
            at_trade_ktc_swing=(float(at_swing[uid]) if uid in at_swing else None),
            aged_ktc_swing=(float(aged[uid]) if uid in aged else None),
            at_trade_approx=bool(grade.get("at_trade_approx", False)),
            at_trade_snapshot_date=grade.get("at_trade_snapshot_date"),
        ))
```

(Note: `at_trade_value_swing` may be `None` in the grade for blank trades; `(... or {})` handles that so `uid` lookups return None → field stays None.)

- [ ] **Step 4: Run** → PASS. **Step 5: Commit**
```bash
git add api/app/models/trade.py api/app/services/trade_view.py api/tests/test_trade.py
git commit -m "feat: trade-detail API exposes at-trade + aged KTC swing"
```

---

## Task 8: Owner aggregate API surface

**Files:**
- Modify: `api/app/services/owner_view.py`, `api/app/models/owner.py`, and `api/app/services/aggregations.py` (`_aggregate_owner_rows`)
- Test: `api/tests/test_owner.py` + `api/tests/test_aggregations.py`

Aggregate at-trade swing **only over trades that have at-trade data**, and aged over that same subset.

- [ ] **Step 1: Write the failing test** — append to `api/tests/test_owner.py`:

```python
def test_owner_detail_at_trade_aggregate_over_subset():
    from app.services.owner_view import build_owner_detail
    from app.services.chain_cache import ChainCacheEntry

    def grade(today, at):
        g = {"snapshot_value_swing": {"u_a": today}, "hindsight_production_swing": {"u_a": 0.0}}
        if at is not None:
            g["at_trade_value_swing"] = {"u_a": at}
            g["aged_value_swing"] = {"u_a": today - at}
        else:
            g["at_trade_value_swing"] = None
        return g

    entry = ChainCacheEntry(
        league_id="L1", chain=[], league_name_by_id={}, league_season_by_id={},
        display_names={"u_a": "A"}, playoff_weeks_by_league={},
        roster_to_user_by_league={},
        resolved_trades=[
            {"trade": {"transaction_id": "t1", "season": 2026, "league_id": "L1"}},
            {"trade": {"transaction_id": "t2", "season": 2026, "league_id": "L1"}},
        ],
        grades={"t1": grade(1000.0, 800.0), "t2": grade(500.0, None)},  # t2 blank at-trade
        cached_at="t", warnings=[],
    )
    resp = build_owner_detail(entry, "u_a")
    # net_ktc over all trades = 1500; at-trade over subset {t1} = 800; aged = 1000-800 = 200.
    assert resp.totals_by_lens["ktc"] == 1500.0
    assert resp.totals_by_lens["ktc_at_trade"] == 800.0
    assert resp.totals_by_lens["ktc_aged"] == 200.0
```

- [ ] **Step 2: Run** → FAIL (`ktc_at_trade` missing).

- [ ] **Step 3: Implement** — in `api/app/services/owner_view.py`, accumulate the subset sums inside the existing trade loop (after the `net_ktc += swing` line):

```python
        at_map = grade.get("at_trade_value_swing") or {}
        if user_id in at_map:
            at_swing = float(at_map[user_id] or 0)
            net_ktc_at_trade += at_swing
            net_ktc_today_subset += swing       # today value for the SAME trade
```

Initialize `net_ktc_at_trade = 0.0` and `net_ktc_today_subset = 0.0` near the
other accumulators, and extend `totals_by_lens`:

```python
        totals_by_lens={"ktc": net_ktc, "production": net_prod,
                        "impact": float(impact_count),
                        "ktc_at_trade": net_ktc_at_trade,
                        "ktc_aged": net_ktc_today_subset - net_ktc_at_trade},
```

`OwnerDetailResp.totals_by_lens` is already `dict[str, float]`, so no model
change is needed for these keys.

Also extend the Owners-tab rows in `aggregations.py` `_aggregate_owner_rows`: add
`"net_ktc_at_trade": 0.0, "net_ktc_today_subset": 0.0` to each row's init dict
(both the pre-seeded and the `setdefault` blocks), and inside the swing loop:

```python
            at_map = g.get("at_trade_value_swing") or {}
            if uid in at_map:
                row["net_ktc_at_trade"] += float(at_map[uid] or 0)
                row["net_ktc_today_subset"] += float(swing or 0)
```

Whatever response model the Owners-tab builder emits should carry
`net_ktc_at_trade` and a derived `net_ktc_aged = net_ktc_today_subset - net_ktc_at_trade`.
Read the builder that consumes `_aggregate_owner_rows` (search `aggregations.py`
for where rows become the response) and add those two fields to its row model +
mapping. If the row model is a `dict` passed straight through, just include the
two keys (compute `net_ktc_aged` when building the response).

- [ ] **Step 4: Run** the api suite → PASS. **Step 5: Commit**
```bash
git add api/app/services/owner_view.py api/app/services/aggregations.py api/app/models/owner.py api/tests/test_owner.py api/tests/test_aggregations.py
git commit -m "feat: owner aggregates expose at-trade + aged net KTC (over subset)"
```

---

## Task 9: Trade-detail UI — At Trade + Δ Aged

**Files:**
- Modify: `web/lib/types.ts` (`TradeSideView`), `web/components/TradeSidePanel.tsx`
- Verify: `cd web && npx tsc --noEmit`

- [ ] **Step 1: Add the fields to the type** — in `web/lib/types.ts`, in `interface TradeSideView`, add:

```ts
  at_trade_ktc_swing: number | null;
  aged_ktc_swing: number | null;
  at_trade_approx: boolean;
  at_trade_snapshot_date: string | null;
```

- [ ] **Step 2: Render the new stat boxes** — in `web/components/TradeSidePanel.tsx`, the Value Swing card is a `grid grid-cols-2` of two boxes (Value Swing today, Points Scored). Add two more boxes — **At Trade** and **Δ Aged** — by extending the array literal that maps to boxes. Insert after the existing "Value Swing" entry:

```tsx
          { label: "At Trade", sub: side.at_trade_approx ? "ktc · approx" : "ktc · at trade",
            v: side.at_trade_ktc_swing == null ? "—"
               : `${side.at_trade_ktc_swing > 0 ? "+" : ""}${Math.round(side.at_trade_ktc_swing).toLocaleString()}`,
            color: side.at_trade_ktc_swing == null ? "text-dim"
               : side.at_trade_ktc_swing > 0 ? "text-pos" : side.at_trade_ktc_swing < 0 ? "text-neg" : "text-dim" },
          { label: "Δ Aged", sub: "today − at trade",
            v: side.aged_ktc_swing == null ? "—"
               : `${side.aged_ktc_swing > 0 ? "+" : ""}${Math.round(side.aged_ktc_swing).toLocaleString()}`,
            color: side.aged_ktc_swing == null ? "text-dim"
               : side.aged_ktc_swing > 0 ? "text-pos" : side.aged_ktc_swing < 0 ? "text-neg" : "text-dim" },
```

The grid now has 4 boxes; keep `grid-cols-2` (they wrap to 2×2) or change to
`grid-cols-2` rows — 2×2 reads well. Leave the impact (SW/SPC/…) grid below
unchanged.

- [ ] **Step 3: Typecheck** — `cd web && npx tsc --noEmit` → clean. **Step 4: Commit**
```bash
git add web/lib/types.ts web/components/TradeSidePanel.tsx
git commit -m "feat(web): show At Trade + Δ Aged on the trade detail card"
```

---

## Task 10: Owners-tab UI — Net KTC (at trade) + Aged

**Files:**
- Modify: `web/components/OwnersTab.tsx` and `web/lib/types.ts` (owner-row type)
- Verify: `cd web && npx tsc --noEmit`

- [ ] **Step 1: Read** `web/components/OwnersTab.tsx` to see the existing column set and the row type it consumes. Add `net_ktc_at_trade: number` and `net_ktc_aged: number` to that row interface in `web/lib/types.ts`.

- [ ] **Step 2: Add two columns** — "Net KTC (At Trade)" and "Aged" — next to the existing Net KTC column, formatted the same way (rounded, +/- sign, `text-pos`/`text-neg`/`text-dim`). Render `—` when a value is absent/zero-with-no-data. Match the existing column markup in the file exactly (same cell classes).

- [ ] **Step 3: Typecheck** — `cd web && npx tsc --noEmit` → clean. **Step 4: Commit**
```bash
git add web/components/OwnersTab.tsx web/lib/types.ts
git commit -m "feat(web): Owners tab shows Net KTC (at trade) + Aged"
```

---

## Task 11: Full verification

- [ ] **Step 1: Engine** — `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && .venv/bin/python -m pytest tests/ -q --import-mode=importlib` → all PASS.
- [ ] **Step 2: API** — `cd api && ../.venv/bin/python -m pytest -q` → all PASS.
- [ ] **Step 3: Web typecheck** — `cd web && npx tsc --noEmit` → clean.
- [ ] **Step 4:** commit any stragglers.

---

## Notes / out of scope (per spec)

- No backfill before `BACKFILL_CUTOFF`; no third-party historical KTC.
- FantasyCalc fallback is NOT applied to dated snapshots (current-only; would be anachronistic) — only the today lens uses it.
- No scheduled daily capture job (opportunistic-on-refresh); `ChainCache` TTL and 409/SSE contract unchanged.
