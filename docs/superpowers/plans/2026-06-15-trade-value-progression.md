> _Historical doc — paths/names have changed. Repo is now `Code Apps/public-dynasty` (GitHub `tkeefe66/public-dynasty-app`), Railway project **shimmering-nature**, live at https://ffbdynasty.com. Ignore stale refs to `sleeper-dynasty` / `sleeper-trade-grader` / `web-production-f949`._

# Trade Value Progression Curve Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show, over time, whether a trade panned out — a per-trade "what you got vs what you gave up" card and a per-owner aggregate value line — using plain signed numbers + a one-sentence verdict, no math shown.

**Architecture:** A pure engine leaf module (`value_series.py`) evaluates each received/given asset's value at every stored KTC snapshot date (held → floats; flipped → locks at flip date; dropped → cliffs to 0 on the real drop date). Drop dates are ingested from the Sleeper transaction stream already pulled for trade-finding. Series are summed per side / per owner, computed + cached during refresh (mirroring the `became_grades` incremental pattern), exposed on the trade-detail and owner-detail responses, and rendered as inline-SVG cards (following the existing `TradeValueSpark` precedent).

**Tech Stack:** Python 3.11 engine (pytest), FastAPI + Pydantic backend, Next.js 14 + Tailwind frontend (vitest + @testing-library/react). No chart library — inline SVG only.

**Spec:** `docs/superpowers/specs/2026-06-15-trade-value-progression-design.md`

---

## Shared definitions (read before starting)

These shapes recur across tasks. Defined concretely in Task 1 and Task 6; repeated here so tasks read independently.

- **Series:** `list[tuple[str, float]]` in Python (one `(iso_date, value)` per snapshot date). JSON-serialized as `list[list]`; element value is always `pt[1]`.
- **`AssetTenure`** (engine dataclass, Task 1): `kind: str` (`"player"`|`"pick"`), `player_id: str | None`, `season: int | None`, `round: int | None`, `terminal: str` (`"held"`|`"flipped"`|`"dropped"`), `terminal_date: str | None` (ISO `YYYY-MM-DD`, None when held).
- **Price callables** (existing, `api/app/services/realized_value.py::make_price_providers`): `price_player(pid: str, d_iso: str | None) -> float`, `price_pick(season: int, round: int, d_iso: str | None) -> float`. `d_iso=None` means "today".
- **Verdict labels** (exact strings, do not reword): `"Great trade."`, `"Good trade."`, `"Mixed, they got the better of it."`, `"Trash."`, `"Brutal."`, `"Boring."` (per-trade); `"Trending up."`, `"Flat."`, `"Down."` (aggregate). Tone is one of `"good"`, `"bad"`, `"neutral"`.
- **Flat threshold:** a side reads `flat` when `abs(change) < 0.05 * abs(base)` (and base is non-zero); else `up`/`down` by sign.

---

### Task 1: Engine — pure `value_series` primitive

**Files:**
- Create: `src/sleeper_dynasty/engine/value_series.py`
- Test: `tests/test_value_series.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_value_series.py`:

```python
from sleeper_dynasty.engine.value_series import (
    AssetTenure,
    value_series,
    series_change,
    sum_series,
)

DATES = ["2026-06-07", "2026-06-10", "2026-06-14"]


def _pp(prices):
    # prices: {(pid, d_iso): value}; d_iso None => "today"
    return lambda pid, d: float(prices.get((pid, d), 0.0))


def _pk(prices):
    return lambda season, rnd, d: float(prices.get((season, rnd, d), 0.0))


def test_held_player_floats_with_market():
    price_player = _pp({("p1", "2026-06-07"): 100, ("p1", "2026-06-10"): 120, ("p1", "2026-06-14"): 150})
    t = AssetTenure("player", "p1", None, None, "held", None)
    s = value_series(t, DATES, price_player, _pk({}))
    assert s == [("2026-06-07", 100.0), ("2026-06-10", 120.0), ("2026-06-14", 150.0)]


def test_flipped_player_locks_at_flip_date():
    # flips on 06-10; later dates lock at the 06-10 price (120), ignoring 06-14 market (999)
    price_player = _pp({("p1", "2026-06-07"): 100, ("p1", "2026-06-10"): 120, ("p1", "2026-06-14"): 999})
    t = AssetTenure("player", "p1", None, None, "flipped", "2026-06-10")
    s = value_series(t, DATES, price_player, _pk({}))
    assert s == [("2026-06-07", 100.0), ("2026-06-10", 120.0), ("2026-06-14", 120.0)]


def test_dropped_player_cliffs_to_zero_on_drop_date():
    price_player = _pp({("p1", "2026-06-07"): 100, ("p1", "2026-06-10"): 120, ("p1", "2026-06-14"): 150})
    t = AssetTenure("player", "p1", None, None, "dropped", "2026-06-10")
    s = value_series(t, DATES, price_player, _pk({}))
    assert s == [("2026-06-07", 100.0), ("2026-06-10", 0.0), ("2026-06-14", 0.0)]


def test_held_pick_uses_pick_pricer():
    price_pick = _pk({(2027, 1, "2026-06-07"): 50, (2027, 1, "2026-06-10"): 55, (2027, 1, "2026-06-14"): 60})
    t = AssetTenure("pick", None, 2027, 1, "held", None)
    s = value_series(t, DATES, _pp({}), price_pick)
    assert s == [("2026-06-07", 50.0), ("2026-06-10", 55.0), ("2026-06-14", 60.0)]


def test_series_change_is_last_minus_first():
    assert series_change([("a", 100.0), ("b", 150.0)]) == 50.0
    assert series_change([]) == 0.0
    assert series_change([("a", 100.0)]) == 0.0


def test_sum_series_adds_aligned_points():
    a = [("2026-06-07", 100.0), ("2026-06-10", 120.0)]
    b = [("2026-06-07", 10.0), ("2026-06-10", 20.0)]
    assert sum_series([a, b]) == [("2026-06-07", 110.0), ("2026-06-10", 140.0)]
    assert sum_series([]) == []
    assert sum_series([[], a]) == a
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && python -m pytest tests/test_value_series.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sleeper_dynasty.engine.value_series'`

- [ ] **Step 3: Write minimal implementation**

Create `src/sleeper_dynasty/engine/value_series.py`:

```python
"""Value-over-time for a received/given asset, evaluated at KTC snapshot dates.

The one primitive behind the Trade Value progression curve. Per asset, value at
each snapshot date ``d`` follows the float/lock/cliff rule:

- ``held``    -> priced at ``d`` (floats with the market)
- ``flipped`` -> priced at ``d`` until the flip date, then LOCKED at the flip-date
                 price for all later ``d``
- ``dropped`` -> priced at ``d`` until the drop date, then 0 for all later ``d``

Pure and dependency-free so it is trivially testable. Callers build the
``AssetTenure`` list (see ``engine/lineage.py::side_value_tenures``) and supply
the price callables from ``make_price_providers``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

Series = list[tuple[str, float]]
FLAT_FRACTION = 0.05


@dataclass
class AssetTenure:
    """One asset's terminal state for the float/lock/cliff evaluation."""

    kind: str                  # "player" | "pick"
    player_id: str | None
    season: int | None
    round: int | None
    terminal: str              # "held" | "flipped" | "dropped"
    terminal_date: str | None  # ISO "YYYY-MM-DD"; None when held


def _price(
    tenure: AssetTenure,
    d_iso: str,
    price_player: Callable[[str, str | None], float],
    price_pick: Callable[[int, int, str | None], float],
) -> float:
    if tenure.kind == "player":
        return float(price_player(tenure.player_id, d_iso))
    return float(price_pick(tenure.season, tenure.round, d_iso))


def _value_at(
    tenure: AssetTenure,
    d: str,
    price_player: Callable[[str, str | None], float],
    price_pick: Callable[[int, int, str | None], float],
) -> float:
    t, td = tenure.terminal, tenure.terminal_date
    if t == "flipped" and td is not None and d >= td:
        return _price(tenure, td, price_player, price_pick)  # locked at flip
    if t == "dropped" and td is not None and d >= td:
        return 0.0                                           # cliff
    return _price(tenure, d, price_player, price_pick)       # held / pre-event


def value_series(
    tenure: AssetTenure,
    snapshot_dates: list[str],
    price_player: Callable[[str, str | None], float],
    price_pick: Callable[[int, int, str | None], float],
) -> Series:
    """Value of one asset at each snapshot date (ISO strings, ascending)."""
    return [
        (d, _value_at(tenure, d, price_player, price_pick))
        for d in snapshot_dates
    ]


def series_change(series: Series) -> float:
    """Signed change from first to last point; 0.0 if fewer than 2 points."""
    if len(series) < 2:
        return 0.0
    return float(series[-1][1]) - float(series[0][1])


def sum_series(serieses: list[Series]) -> Series:
    """Element-wise sum of date-aligned series. Empty series are ignored."""
    present = [s for s in serieses if s]
    if not present:
        return []
    dates = [pt[0] for pt in present[0]]
    return [
        (d, sum(float(s[i][1]) for s in present))
        for i, d in enumerate(dates)
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && python -m pytest tests/test_value_series.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty"
git add src/sleeper_dynasty/engine/value_series.py tests/test_value_series.py
git commit -m "feat(engine): pure value_series primitive (float/lock/cliff)"
```

---

### Task 2: Engine — verdict classifiers

**Files:**
- Modify: `src/sleeper_dynasty/engine/value_series.py` (append functions)
- Test: `tests/test_value_verdict.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_value_verdict.py`:

```python
from sleeper_dynasty.engine.value_series import per_trade_verdict, aggregate_verdict


def test_great_trade_got_up_gave_down():
    v = per_trade_verdict(received_change=6800, received_base=10000,
                          given_change=-3000, given_base=8000)
    assert v["label"] == "Great trade."
    assert v["tone"] == "good"
    assert v["received_change"] == 6800
    assert v["given_change"] == -3000


def test_good_trade_both_up_yours_more():
    v = per_trade_verdict(received_change=4000, received_base=10000,
                          given_change=1000, given_base=8000)
    assert v["label"] == "Good trade."
    assert v["tone"] == "good"


def test_mixed_both_up_theirs_more():
    v = per_trade_verdict(received_change=1000, received_base=10000,
                          given_change=5000, given_base=8000)
    assert v["label"] == "Mixed, they got the better of it."
    assert v["tone"] == "bad"


def test_trash_both_down():
    v = per_trade_verdict(received_change=-2000, received_base=10000,
                          given_change=-2000, given_base=8000)
    assert v["label"] == "Trash."
    assert v["tone"] == "bad"


def test_brutal_got_down_gave_up():
    v = per_trade_verdict(received_change=-2000, received_base=10000,
                          given_change=4000, given_base=8000)
    assert v["label"] == "Brutal."
    assert v["tone"] == "bad"


def test_boring_both_flat():
    # both changes under 5% of base -> flat
    v = per_trade_verdict(received_change=100, received_base=10000,
                          given_change=100, given_base=8000)
    assert v["label"] == "Boring."
    assert v["tone"] == "neutral"


def test_flat_threshold_boundary():
    # exactly 5% is NOT flat (>= threshold reads as a move)
    v = per_trade_verdict(received_change=500, received_base=10000,   # 5% -> up
                          given_change=0, given_base=8000)            # flat
    assert v["label"] == "Good trade."


def test_single_side_flat_collapses_by_other_side():
    # received up, given flat -> Good trade.
    up_flat = per_trade_verdict(2000, 10000, 50, 8000)
    assert up_flat["label"] == "Good trade."
    # received down, given flat -> Trash.
    down_flat = per_trade_verdict(-2000, 10000, 50, 8000)
    assert down_flat["label"] == "Trash."
    # received flat, given down -> Good trade. (gave-away cooled = good)
    flat_down = per_trade_verdict(50, 10000, -2000, 8000)
    assert flat_down["label"] == "Good trade."
    # received flat, given up -> Mixed.
    flat_up = per_trade_verdict(50, 10000, 2000, 8000)
    assert flat_up["label"] == "Mixed, they got the better of it."


def test_aggregate_trending_up():
    v = aggregate_verdict(value_change=12400, value_base=40000, production_change=840)
    assert v["label"] == "Trending up."
    assert v["tone"] == "good"
    assert "scoring more" in v["sentence"]


def test_aggregate_down():
    v = aggregate_verdict(value_change=-9000, value_base=40000, production_change=-200)
    assert v["label"] == "Down."
    assert v["tone"] == "bad"


def test_aggregate_flat():
    v = aggregate_verdict(value_change=100, value_base=40000, production_change=0)
    assert v["label"] == "Flat."
    assert v["tone"] == "neutral"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && python -m pytest tests/test_value_verdict.py -v`
Expected: FAIL with `ImportError: cannot import name 'per_trade_verdict'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/sleeper_dynasty/engine/value_series.py`:

```python
def _direction(change: float, base: float) -> str:
    """'up' | 'down' | 'flat' — flat when the move is under FLAT_FRACTION of base."""
    if base and abs(change) < FLAT_FRACTION * abs(base):
        return "flat"
    if change > 0:
        return "up"
    if change < 0:
        return "down"
    return "flat"


# (received_dir, given_dir) -> (label, tone). The up/up case is split downstream.
_PER_TRADE = {
    ("up", "down"): ("Great trade.", "good"),
    ("up", "flat"): ("Good trade.", "good"),
    ("flat", "down"): ("Good trade.", "good"),
    ("flat", "flat"): ("Boring.", "neutral"),
    ("flat", "up"): ("Mixed, they got the better of it.", "bad"),
    ("down", "up"): ("Brutal.", "bad"),
    ("down", "flat"): ("Trash.", "bad"),
    ("down", "down"): ("Trash.", "bad"),
}

_SENTENCE = {
    "Great trade.": "What you got gained value, and the player you gave up cooled off.",
    "Good trade.": "What you got came out ahead of what you gave up.",
    "Mixed, they got the better of it.": "What you gave up gained more than what you got.",
    "Trash.": "Both sides cooled off — nothing gained here.",
    "Brutal.": "What you got cooled off while the player you gave up took off.",
    "Boring.": "Neither side has moved much yet.",
}


def per_trade_verdict(
    received_change: float,
    received_base: float,
    given_change: float,
    given_base: float,
) -> dict:
    """Plain-English verdict for one side of a trade.

    Returns ``{"label", "sentence", "tone", "received_change", "given_change"}``.
    """
    rd = _direction(received_change, received_base)
    gd = _direction(given_change, given_base)
    if rd == "up" and gd == "up":
        if received_change > given_change:
            label, tone = "Good trade.", "good"
        else:
            label, tone = "Mixed, they got the better of it.", "bad"
    else:
        label, tone = _PER_TRADE[(rd, gd)]
    return {
        "label": label,
        "sentence": _SENTENCE[label],
        "tone": tone,
        "received_change": float(received_change),
        "given_change": float(given_change),
    }


def aggregate_verdict(
    value_change: float,
    value_base: float,
    production_change: float,
) -> dict:
    """Owner-wide trend verdict. Trade-Value line drives the label; Production
    confirms in a second sentence.

    Returns ``{"label", "sentence", "tone", "value_change", "production_change"}``.
    """
    vd = _direction(value_change, value_base)
    if vd == "up":
        label, tone = "Trending up.", "good"
    elif vd == "down":
        label, tone = "Down.", "bad"
    else:
        label, tone = "Flat.", "neutral"
    if production_change > 0:
        prod = "and scoring more than when tracking began."
    elif production_change < 0:
        prod = "and scoring less than when tracking began."
    else:
        prod = "with scoring about flat since tracking began."
    head = {
        "Trending up.": "Your trade haul is worth more",
        "Down.": "Your trade haul is worth less",
        "Flat.": "Your trade haul is worth about the same",
    }[label]
    return {
        "label": label,
        "sentence": f"{head} {prod}",
        "tone": tone,
        "value_change": float(value_change),
        "production_change": float(production_change),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && python -m pytest tests/test_value_verdict.py -v`
Expected: PASS (11 tests)

- [ ] **Step 5: Commit**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty"
git add src/sleeper_dynasty/engine/value_series.py tests/test_value_verdict.py
git commit -m "feat(engine): per-trade + aggregate value verdict classifiers"
```

---

### Task 3: Engine — drop-timestamp ingestion

**Files:**
- Modify: `src/sleeper_dynasty/engine/trade_history.py`
- Test: `tests/test_drop_index.py`
- Create fixture: `tests/fixtures/transactions_with_drops.json`

The drop index maps `(owner_user_id, player_id) -> earliest ISO drop date`. Built from `type` in `drop`/`waiver`/`free_agent` transactions (their `drops` dict). Threaded out of `build_trade_history` behind a `return_drops` flag so existing callers (CLI) are unaffected.

- [ ] **Step 1: Write the failing test + fixture**

Create `tests/fixtures/transactions_with_drops.json`:

```json
[
  {
    "type": "drop",
    "status": "complete",
    "transaction_id": "tx_drop_1",
    "created": 1726185600000,
    "leg": 3,
    "roster_ids": [1],
    "adds": null,
    "drops": {"8888": 1}
  },
  {
    "type": "waiver",
    "status": "complete",
    "transaction_id": "tx_wv_1",
    "created": 1726272000000,
    "leg": 3,
    "roster_ids": [2],
    "adds": {"7777": 2},
    "drops": {"9999": 2}
  },
  {
    "type": "trade",
    "status": "complete",
    "transaction_id": "tx_trade_1",
    "created": 1726358400000,
    "leg": 3,
    "roster_ids": [1, 2],
    "adds": {"5555": 1},
    "drops": {"5555": 2}
  }
]
```

Create `tests/test_drop_index.py`:

```python
import json
from pathlib import Path

from sleeper_dynasty.engine.trade_history import build_drop_index

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name):
    with open(FIXTURES / name) as f:
        return json.load(f)


def test_build_drop_index_captures_drop_and_waiver_legs():
    txs = load_fixture("transactions_with_drops.json")
    roster_to_user = {1: "u_alice", 2: "u_bob"}
    idx = build_drop_index(txs, roster_to_user)
    # 1726185600000 ms = 2024-09-13 UTC; 8888 dropped by roster 1 (alice)
    assert idx[("u_alice", "8888")] == "2024-09-13"
    # waiver drop of 9999 by roster 2 (bob)
    assert idx[("u_bob", "9999")] == "2024-09-14"
    # trade drops are NOT in the drop index (trades handled separately)
    assert ("u_bob", "5555") not in idx


def test_build_drop_index_keeps_earliest_date():
    txs = [
        {"type": "drop", "status": "complete", "created": 1726358400000,
         "drops": {"8888": 1}},
        {"type": "drop", "status": "complete", "created": 1726185600000,
         "drops": {"8888": 1}},
    ]
    idx = build_drop_index(txs, {1: "u_alice"})
    assert idx[("u_alice", "8888")] == "2024-09-13"  # earlier of the two
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && python -m pytest tests/test_drop_index.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_drop_index'`

- [ ] **Step 3: Write `build_drop_index`**

Add to `src/sleeper_dynasty/engine/trade_history.py` (near `normalize_trade`, after its definition ends around line 154). It uses `datetime`/`timezone` already imported at the top of the file:

```python
_DROP_TX_TYPES = ("drop", "waiver", "free_agent")


def build_drop_index(
    raw_txs: list[dict],
    roster_to_user: dict[int, str],
) -> dict[tuple[str, str], str]:
    """Map ``(owner_user_id, player_id) -> earliest ISO drop date`` from the
    drop legs of drop/waiver/free-agent transactions. Trade drops are excluded
    (trades are handled by the lineage walk).
    """
    out: dict[tuple[str, str], str] = {}
    for tx in raw_txs:
        if tx.get("status") != "complete":
            continue
        if tx.get("type") not in _DROP_TX_TYPES:
            continue
        drops = tx.get("drops") or {}
        if not drops:
            continue
        d_iso = datetime.fromtimestamp(
            int(tx["created"]) / 1000.0, tz=timezone.utc
        ).date().isoformat()
        for player_id, src_roster_id in drops.items():
            owner = roster_to_user.get(src_roster_id)
            if owner is None:
                continue
            key = (owner, str(player_id))
            if key not in out or d_iso < out[key]:
                out[key] = d_iso
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && python -m pytest tests/test_drop_index.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Collect raw drops in the fetch bundle**

In `src/sleeper_dynasty/engine/trade_history.py`, in `_fetch_league_season_data` (lines ~342–356), the transaction loop currently keeps only trades. Extend it to also collect drop transactions. Replace the loop:

```python
    weeks = range(1, _MAX_WEEK + 1)
    tx_chunks = await asyncio.gather(*(_one_week(w) for w in weeks))
    raw_trades: list[dict] = []
    for week_txs in tx_chunks:
        for tx in week_txs or []:
            if tx.get("type") == "trade" and tx.get("status") == "complete":
                tx_id = str(tx.get("transaction_id", ""))
                if tx_id in BLACKLISTED_TRANSACTION_IDS:
                    log.info("Skipping blacklisted transaction %s", tx_id)
                    continue
                raw_trades.append(tx)
```

with:

```python
    weeks = range(1, _MAX_WEEK + 1)
    tx_chunks = await asyncio.gather(*(_one_week(w) for w in weeks))
    raw_trades: list[dict] = []
    raw_drops: list[dict] = []
    for week_txs in tx_chunks:
        for tx in week_txs or []:
            if tx.get("status") != "complete":
                continue
            if tx.get("type") == "trade":
                tx_id = str(tx.get("transaction_id", ""))
                if tx_id in BLACKLISTED_TRANSACTION_IDS:
                    log.info("Skipping blacklisted transaction %s", tx_id)
                    continue
                raw_trades.append(tx)
            elif tx.get("type") in _DROP_TX_TYPES and (tx.get("drops") or {}):
                raw_drops.append(tx)
```

Then add `raw_drops` to the bundle dict (the `bundle = {...}` block a few lines below):

```python
    bundle = {
        "users": users,
        "roster_to_user": roster_to_user,
        "raw_trades": raw_trades,
        "raw_drops": raw_drops,
        "drafts": drafts,
        "draft_picks_by_draft_id": draft_picks_by_draft_id,
    }
```

- [ ] **Step 6: Thread the drop index out of `build_trade_history`**

In `build_trade_history`, change the signature to accept `return_drops` and build the merged drop index from all bundles. Update the signature line:

```python
async def build_trade_history(
    client,
    current_league_id: str,
    player_names: dict[str, str],
    league_cache=None,
    return_drops: bool = False,
):
```

At the end of the function, replace the final two lines:

```python
    # Newest first.
    resolved.sort(key=lambda rt: rt.trade.traded_at, reverse=True)
    return resolved
```

with:

```python
    # Newest first.
    resolved.sort(key=lambda rt: rt.trade.traded_at, reverse=True)

    if not return_drops:
        return resolved

    drop_index: dict[tuple[str, str], str] = {}
    for bundle in bundles:
        season_idx = build_drop_index(
            bundle.get("raw_drops", []), bundle["roster_to_user"]
        )
        for key, d_iso in season_idx.items():
            if key not in drop_index or d_iso < drop_index[key]:
                drop_index[key] = d_iso
    return resolved, drop_index
```

- [ ] **Step 7: Run the full engine suite to confirm no regressions**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && python -m pytest tests/test_trade_history.py tests/test_drop_index.py -v`
Expected: PASS (existing trade-history tests still green; new drop tests green). The default `return_drops=False` path is unchanged, so existing callers are unaffected.

- [ ] **Step 8: Commit**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty"
git add src/sleeper_dynasty/engine/trade_history.py tests/test_drop_index.py tests/fixtures/transactions_with_drops.json
git commit -m "feat(engine): ingest drop timestamps from the transaction stream"
```

---

### Task 4: Engine — `side_value_tenures` (trade walk → AssetTenure list)

**Files:**
- Modify: `src/sleeper_dynasty/engine/lineage.py`
- Test: `tests/test_side_value_tenures.py`

Reuses the private helpers already in `lineage.py` (`_given_index`, `_asset_id`) and the existing realized-value flip/held/dropped logic, plus the new `drop_index`. For the **received** side it produces real terminal states; for the **given** side (the counterfactual "as if you'd held it") every asset is `held`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_side_value_tenures.py`:

```python
from sleeper_dynasty.engine.lineage import side_value_tenures

# Minimal resolved-trade dicts. Shape mirrors _to_dict(ResolvedTrade): each item
# has "trade" (with transaction_id, traded_at) and "sides" {uid: {received, given}}.
ROOT = {
    "trade": {"transaction_id": "t1", "traded_at": "2026-06-01T00:00:00+00:00"},
    "sides": {
        "alice": {
            "received": [{"player_id": "p_kept", "name": "Kept"},
                         {"player_id": "p_flip", "name": "Flip"},
                         {"player_id": "p_drop", "name": "Drop"}],
            "given": [{"player_id": "p_gave", "name": "Gave"}],
        },
        "bob": {"received": [{"player_id": "p_gave", "name": "Gave"}],
                "given": [{"player_id": "p_kept", "name": "Kept"},
                          {"player_id": "p_flip", "name": "Flip"},
                          {"player_id": "p_drop", "name": "Drop"}]},
    },
}
# Alice later flips p_flip to bob on 2026-06-10.
FLIP = {
    "trade": {"transaction_id": "t2", "traded_at": "2026-06-10T00:00:00+00:00"},
    "sides": {
        "bob": {"received": [{"player_id": "p_flip", "name": "Flip"}], "given": []},
        "alice": {"received": [], "given": [{"player_id": "p_flip", "name": "Flip"}]},
    },
}
TRADES = [ROOT, FLIP]


def test_received_tenures_classify_held_flipped_dropped():
    current_holders = {"p_kept": "alice"}  # only p_kept still on alice's roster
    drop_index = {("alice", "p_drop"): "2026-06-08"}
    tens = side_value_tenures(
        TRADES, "t1", "alice", which="received",
        current_holders=current_holders, drop_index=drop_index,
    )
    by_pid = {t.player_id: t for t in tens}
    assert by_pid["p_kept"].terminal == "held"
    assert by_pid["p_kept"].terminal_date is None
    assert by_pid["p_flip"].terminal == "flipped"
    assert by_pid["p_flip"].terminal_date == "2026-06-10"
    assert by_pid["p_drop"].terminal == "dropped"
    assert by_pid["p_drop"].terminal_date == "2026-06-08"


def test_given_tenures_are_all_held_counterfactual():
    tens = side_value_tenures(
        TRADES, "t1", "alice", which="given",
        current_holders={}, drop_index={},
    )
    assert len(tens) == 1
    assert tens[0].player_id == "p_gave"
    assert tens[0].terminal == "held"
    assert tens[0].terminal_date is None


def test_dropped_player_without_drop_record_still_terminal_zero():
    # p_drop not held, not flipped, and no drop record -> dropped with None date
    tens = side_value_tenures(
        TRADES, "t1", "alice", which="received",
        current_holders={"p_kept": "alice", "p_flip": "alice"}, drop_index={},
    )
    by_pid = {t.player_id: t for t in tens}
    assert by_pid["p_drop"].terminal == "dropped"
    assert by_pid["p_drop"].terminal_date is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && python -m pytest tests/test_side_value_tenures.py -v`
Expected: FAIL with `ImportError: cannot import name 'side_value_tenures'`

- [ ] **Step 3: Write `side_value_tenures`**

Append to `src/sleeper_dynasty/engine/lineage.py`:

```python
def _player_tenure(pid, owner, since, idx, current_holders, drop_index):
    """Terminal state for a received PLAYER: flipped (first flip after `since`),
    else held (still on roster), else dropped (real date if known, else None)."""
    from sleeper_dynasty.engine.value_series import AssetTenure

    flips = [r for r in idx.get((owner, ("player", pid)), [])
             if r["trade"]["traded_at"] > since]
    if flips:
        return AssetTenure("player", pid, None, None, "flipped",
                           flips[0]["trade"]["traded_at"][:10])
    if current_holders.get(pid) == owner:
        return AssetTenure("player", pid, None, None, "held", None)
    return AssetTenure("player", pid, None, None, "dropped",
                       drop_index.get((owner, pid)))


def side_value_tenures(
    resolved_trades: list[dict],
    root_trade_id: str,
    owner_uid: str,
    *,
    which: str,                 # "received" | "given"
    current_holders: dict[str, str],
    drop_index: dict[tuple[str, str], str],
) -> list:
    """Build the AssetTenure list for one side of one trade.

    ``received`` assets carry their real terminal state (held/flipped/dropped);
    ``given`` assets are the counterfactual — priced as if the owner had kept
    them, so every one is ``held``. Picks resolve to their drafted player when
    known (mirrors ``realized_received_values``); a flipped-as-a-pick stays a
    pick locked at the flip date.
    """
    from sleeper_dynasty.engine.value_series import AssetTenure

    idx = _given_index(resolved_trades)
    root = next(
        (r for r in resolved_trades
         if r["trade"]["transaction_id"] == root_trade_id),
        None,
    )
    if root is None:
        raise ValueError(f"trade {root_trade_id!r} not found in resolved_trades")
    since = root["trade"]["traded_at"]
    side = (root.get("sides") or {}).get(owner_uid) or {}

    out = []
    for a in (side.get(which) or []):
        aid = _asset_id(a)
        if aid is None:
            continue  # faab / unknown
        if which == "given":
            # Counterfactual: price as if held. Resolve a drafted pick to its player.
            if aid[0] == "player":
                out.append(AssetTenure("player", a["player_id"], None, None, "held", None))
            elif a.get("drafted_player_id"):
                out.append(AssetTenure("player", a["drafted_player_id"], None, None, "held", None))
            else:
                out.append(AssetTenure("pick", None, a["season"], a["round"], "held", None))
            continue
        # received side
        if aid[0] == "player":
            out.append(_player_tenure(a["player_id"], owner_uid, since, idx,
                                      current_holders, drop_index))
            continue
        # pick: flipped as a pick first, else resolve to drafted player, else held pick
        flips = [r for r in idx.get((owner_uid, aid), [])
                 if r["trade"]["traded_at"] > since]
        if flips:
            out.append(AssetTenure("pick", None, a["season"], a["round"], "flipped",
                                   flips[0]["trade"]["traded_at"][:10]))
        elif a.get("drafted_player_id"):
            out.append(_player_tenure(a["drafted_player_id"], owner_uid, since, idx,
                                      current_holders, drop_index))
        else:
            out.append(AssetTenure("pick", None, a["season"], a["round"], "held", None))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && python -m pytest tests/test_side_value_tenures.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty"
git add src/sleeper_dynasty/engine/lineage.py tests/test_side_value_tenures.py
git commit -m "feat(engine): side_value_tenures — trade walk to AssetTenure list"
```

---

### Task 5: Backend — cache fields + refresh-time series computation

**Files:**
- Modify: `api/app/services/chain_cache.py` (add fields)
- Modify: `api/app/services/grader.py` (new `_compute_value_series` stage + wire in)
- Test: `api/tests/test_value_series_stage.py`

The series are computed during refresh (like `became_grades`) and stored on the entry. Verdicts are derived at read time (Tasks 7–8) since they are pure functions of the series. No `SCHEMA_VERSION` bump — new fields use `field(default_factory=...)`, so an older cached entry deserializes with empty series and the next refresh populates them (matches the spec).

- [ ] **Step 1: Add the cache fields**

In `api/app/services/chain_cache.py`, in the `ChainCacheEntry` dataclass (after `drafted_picks` near line 60), add:

```python
    # Trade Value progression (sub-project #2). Computed at refresh.
    # trade_value_series: trade_id -> uid -> {"received": [[date, val], ...],
    #                                         "given":    [[date, val], ...]}
    trade_value_series: dict[str, dict[str, dict[str, list]]] = field(default_factory=dict)
    # owner_value_series: uid -> [[date, val], ...] (all received assets summed)
    owner_value_series: dict[str, list] = field(default_factory=dict)
    # The snapshot dates the series were sampled at (ISO strings, ascending).
    value_series_dates: list[str] = field(default_factory=list)
```

- [ ] **Step 2: Write the failing test for the compute stage**

Create `api/tests/test_value_series_stage.py`. This tests the pure helper that the grader stage delegates to, so it needs no live Sleeper client:

```python
from app.services.grader import compute_value_series_payload


def _series_dates():
    return ["2026-06-07", "2026-06-14"]


def test_compute_value_series_payload_shapes():
    resolved_dicts = [{
        "trade": {"transaction_id": "t1", "traded_at": "2026-06-01T00:00:00+00:00"},
        "sides": {
            "alice": {"received": [{"player_id": "p1", "name": "P1"}],
                      "given": [{"player_id": "p2", "name": "P2"}]},
            "bob": {"received": [{"player_id": "p2", "name": "P2"}],
                    "given": [{"player_id": "p1", "name": "P1"}]},
        },
    }]
    prices = {("p1", "2026-06-07"): 100, ("p1", "2026-06-14"): 150,
              ("p2", "2026-06-07"): 80, ("p2", "2026-06-14"): 60}
    price_player = lambda pid, d: float(prices.get((pid, d), 0.0))
    price_pick = lambda s, r, d: 0.0

    payload = compute_value_series_payload(
        resolved_dicts=resolved_dicts,
        snapshot_dates=_series_dates(),
        current_holders={"p1": "alice", "p2": "bob"},
        drop_index={},
        price_player=price_player,
        price_pick=price_pick,
    )
    assert payload["value_series_dates"] == ["2026-06-07", "2026-06-14"]
    alice = payload["trade_value_series"]["t1"]["alice"]
    assert alice["received"] == [["2026-06-07", 100.0], ["2026-06-14", 150.0]]
    # given side (p2) priced as-if-held
    assert alice["given"] == [["2026-06-07", 80.0], ["2026-06-14", 60.0]]
    # owner aggregate for alice = her received haul summed
    assert payload["owner_value_series"]["alice"] == [["2026-06-07", 100.0], ["2026-06-14", 150.0]]


def test_compute_value_series_payload_empty_when_no_dates():
    payload = compute_value_series_payload(
        resolved_dicts=[], snapshot_dates=[], current_holders={},
        drop_index={}, price_player=lambda *a: 0.0, price_pick=lambda *a: 0.0,
    )
    assert payload == {"trade_value_series": {}, "owner_value_series": {},
                       "value_series_dates": []}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/api" && python -m pytest tests/test_value_series_stage.py -v`
Expected: FAIL with `ImportError: cannot import name 'compute_value_series_payload'`

- [ ] **Step 4: Write the pure payload builder**

Add to `api/app/services/grader.py` (module-level function, near the other helpers; place above the `GraderService` class):

```python
def compute_value_series_payload(
    *,
    resolved_dicts: list[dict],
    snapshot_dates: list[str],
    current_holders: dict[str, str],
    drop_index: dict[tuple[str, str], str],
    price_player,
    price_pick,
) -> dict:
    """Pure builder for the Trade Value progression payload. Returns the three
    fields stored on ChainCacheEntry: per-trade per-side series, per-owner
    aggregate series, and the snapshot dates used. Series points are [date, val]
    lists (JSON-friendly)."""
    from sleeper_dynasty.engine.lineage import side_value_tenures
    from sleeper_dynasty.engine.value_series import sum_series, value_series

    if not snapshot_dates:
        return {"trade_value_series": {}, "owner_value_series": {},
                "value_series_dates": []}

    def _series(tenures):
        summed = sum_series([
            value_series(t, snapshot_dates, price_player, price_pick)
            for t in tenures
        ])
        return [[d, v] for d, v in summed]

    trade_series: dict[str, dict[str, dict[str, list]]] = {}
    owner_tenures: dict[str, list] = {}
    for rt in resolved_dicts:
        tx = rt["trade"]["transaction_id"]
        per_side: dict[str, dict[str, list]] = {}
        for uid in (rt.get("sides") or {}):
            recv = side_value_tenures(resolved_dicts, tx, uid, which="received",
                                      current_holders=current_holders,
                                      drop_index=drop_index)
            give = side_value_tenures(resolved_dicts, tx, uid, which="given",
                                      current_holders=current_holders,
                                      drop_index=drop_index)
            per_side[uid] = {"received": _series(recv), "given": _series(give)}
            owner_tenures.setdefault(uid, []).extend(recv)
        trade_series[tx] = per_side

    owner_series = {uid: _series(tens) for uid, tens in owner_tenures.items()}
    return {
        "trade_value_series": trade_series,
        "owner_value_series": owner_series,
        "value_series_dates": list(snapshot_dates),
    }
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/api" && python -m pytest tests/test_value_series_stage.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Wire the stage into `GraderService.run()`**

In `api/app/services/grader.py`:

(a) Change the trade-history call (lines ~110–114) to request the drop index:

```python
    await progress_cb("trades", "Normalizing trades")
    resolved, drop_index = await _build_trade_history(
        client, current_league_id=current_league_id, player_names=player_names,
        league_cache=league_cache, return_drops=True,
    )
```

(b) After the became-grades stage completes and `price_player` / `price_pick` are available (they are created at lines ~189–194 via `make_price_providers`; the became stage is at ~279–286 — place this block **after** line 286, where `snapshot_store`, `current_holders`, `resolved_dicts`, `price_player`, `price_pick` are all in scope), add:

```python
    await progress_cb("value_series", "Tracing value over time")
    try:
        snapshot_dates = (
            [d.isoformat() for d in snapshot_store.list_dates()]
            if snapshot_store is not None else []
        )
        value_series_payload = compute_value_series_payload(
            resolved_dicts=resolved_dicts,
            snapshot_dates=snapshot_dates,
            current_holders=current_holders,
            drop_index=drop_index,
            price_player=price_player,
            price_pick=price_pick,
        )
    except Exception:  # never fail refresh on series errors
        log.exception("value-series stage failed")
        value_series_payload = {"trade_value_series": {}, "owner_value_series": {},
                                "value_series_dates": []}
```

(c) Add the three fields to the `ChainCacheEntry(...)` constructor (lines ~413–436), after `drafted_picks=drafted_picks,`:

```python
        trade_value_series=value_series_payload["trade_value_series"],
        owner_value_series=value_series_payload["owner_value_series"],
        value_series_dates=value_series_payload["value_series_dates"],
```

- [ ] **Step 7: Run the backend suite to confirm wiring compiles and nothing regresses**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/api" && python -m pytest tests/test_value_series_stage.py -v && python -c "import app.services.grader, app.services.chain_cache"`
Expected: tests PASS; import line prints nothing and exits 0 (no syntax/name errors in the wired code).

- [ ] **Step 8: Commit**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty"
git add api/app/services/chain_cache.py api/app/services/grader.py api/tests/test_value_series_stage.py
git commit -m "feat(api): compute + cache Trade Value progression series at refresh"
```

---

### Task 6: Backend — response models

**Files:**
- Modify: `api/app/models/trade.py` (ValuePoint, ValueSidesView, PerTradeVerdictView; extend TradeDetailResp)
- Modify: `api/app/models/owner.py` (AggregateVerdictView; extend OwnerDetailResp)
- Test: `api/tests/test_value_models.py`

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_value_models.py`:

```python
from app.models.trade import (
    ValuePoint, ValueSidesView, PerTradeVerdictView, TradeDetailResp,
)
from app.models.owner import AggregateVerdictView


def test_value_models_construct():
    sides = ValueSidesView(
        received=[ValuePoint(date="2026-06-07", value=100.0)],
        given=[ValuePoint(date="2026-06-07", value=80.0)],
    )
    verdict = PerTradeVerdictView(
        label="Great trade.", sentence="...", tone="good",
        received_change=6800.0, given_change=-3000.0,
    )
    assert sides.received[0].value == 100.0
    assert verdict.tone == "good"


def test_aggregate_verdict_view():
    v = AggregateVerdictView(
        label="Trending up.", sentence="...", tone="good",
        value_change=12400.0, production_change=840.0,
    )
    assert v.label == "Trending up."


def test_trade_detail_resp_has_value_fields_with_defaults():
    # value_series / value_verdict default to empty so old callers still build.
    r = TradeDetailResp(
        league_id="l", trade_id="t", date="2026-06-01", week=1, season=2026,
        league_name="L", sides=[],
    )
    assert r.value_series == {}
    assert r.value_verdict == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/api" && python -m pytest tests/test_value_models.py -v`
Expected: FAIL with `ImportError: cannot import name 'ValuePoint'`

- [ ] **Step 3: Add the trade models**

In `api/app/models/trade.py`, add these classes above `TradeDetailResp` (the file already imports `BaseModel`; if it uses `from pydantic import BaseModel`, no new import is needed):

```python
class ValuePoint(BaseModel):
    date: str
    value: float


class ValueSidesView(BaseModel):
    received: list[ValuePoint] = []
    given: list[ValuePoint] = []


class PerTradeVerdictView(BaseModel):
    label: str
    sentence: str
    tone: str  # "good" | "bad" | "neutral"
    received_change: float
    given_change: float
```

Then add two fields to `TradeDetailResp` (after `owner_names: dict[str, str] = {}`):

```python
    # Trade Value progression (sub-project #2): per-side series + verdict, by uid.
    value_series: dict[str, ValueSidesView] = {}
    value_verdict: dict[str, PerTradeVerdictView] = {}
```

- [ ] **Step 4: Add the owner model**

In `api/app/models/owner.py`, add above `OwnerDetailResp` (match the existing import style — the file uses `from pydantic import BaseModel`, and `Field` if defaults need a factory):

```python
class AggregateVerdictView(BaseModel):
    label: str
    sentence: str
    tone: str  # "good" | "bad" | "neutral"
    value_change: float
    production_change: float
```

Then add two fields to `OwnerDetailResp` (after `draft_picks_by_season=...`'s field declaration; use `Field(default_factory=list)` for the list to match the file's convention):

```python
    # Trade Value progression aggregate (sub-project #2).
    value_progression: list["ValuePoint"] = Field(default_factory=list)
    value_verdict: "AggregateVerdictView | None" = None
```

`ValuePoint` lives in `app.models.trade`; add to the imports at the top of `owner.py`:

```python
from app.models.trade import ValuePoint
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/api" && python -m pytest tests/test_value_models.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty"
git add api/app/models/trade.py api/app/models/owner.py api/tests/test_value_models.py
git commit -m "feat(api): response models for Trade Value progression"
```

---

### Task 7: Backend — assemble per-trade series + verdict in `trade_view`

**Files:**
- Modify: `api/app/services/trade_view.py`
- Test: `api/tests/test_trade_view_value.py`

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_trade_view_value.py`. It builds a minimal `ChainCacheEntry` carrying a `trade_value_series` and asserts `build_trade_detail` surfaces series + verdict. Mirror the construction used by existing `trade_view` tests (inspect `api/tests/` for the closest existing `build_trade_detail` test and copy its entry-construction helper). The assertions that matter:

```python
def test_build_trade_detail_attaches_series_and_verdict(minimal_entry_with_series):
    # minimal_entry_with_series: a ChainCacheEntry whose trade_value_series["t1"]
    # has alice received rising 100 -> 150 and given falling 80 -> 60.
    from app.services.trade_view import build_trade_detail
    resp = build_trade_detail(minimal_entry_with_series, "t1")
    alice = resp.value_series["alice"]
    assert alice.received[-1].value == 150.0
    assert alice.given[-1].value == 60.0
    v = resp.value_verdict["alice"]
    assert v.received_change == 50.0    # 150 - 100
    assert v.given_change == -20.0      # 60 - 80
    assert v.label == "Great trade."    # got up, gave-away down
```

Build `minimal_entry_with_series` as a pytest fixture constructing a `ChainCacheEntry` with: one resolved trade `t1` (two sides alice/bob), a matching `grades["t1"]`, `owners={"alice","bob"}`, and
`trade_value_series={"t1": {"alice": {"received": [["2026-06-07",100],["2026-06-14",150]], "given": [["2026-06-07",80],["2026-06-14",60]]}, "bob": {...}}}`,
`value_series_dates=["2026-06-07","2026-06-14"]`. Use the same field set the existing trade_view tests use so the entry validates.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/api" && python -m pytest tests/test_trade_view_value.py -v`
Expected: FAIL — `resp.value_series` is `{}` (not yet populated by `build_trade_detail`).

- [ ] **Step 3: Populate series + verdict in `build_trade_detail`**

In `api/app/services/trade_view.py`, add imports at the top:

```python
from sleeper_dynasty.engine.value_series import per_trade_verdict, series_change
from app.models.trade import ValuePoint, ValueSidesView, PerTradeVerdictView
```

In `build_trade_detail` (lines ~94–218), after the trade is looked up (around line 113, where `entry.became_grades` is read), add:

```python
    series_for_trade = (entry.trade_value_series or {}).get(trade_id) or {}
    value_series_view: dict[str, ValueSidesView] = {}
    value_verdict_view: dict[str, PerTradeVerdictView] = {}
    for uid, sides in series_for_trade.items():
        recv = sides.get("received") or []
        give = sides.get("given") or []
        value_series_view[uid] = ValueSidesView(
            received=[ValuePoint(date=d, value=v) for d, v in recv],
            given=[ValuePoint(date=d, value=v) for d, v in give],
        )
        recv_base = recv[0][1] if recv else 0.0
        give_base = give[0][1] if give else 0.0
        v = per_trade_verdict(
            received_change=series_change(recv),
            received_base=recv_base,
            given_change=series_change(give),
            given_base=give_base,
        )
        value_verdict_view[uid] = PerTradeVerdictView(**v)
```

Then in the `TradeDetailResp(...)` constructor (lines ~204–218), add:

```python
        value_series=value_series_view,
        value_verdict=value_verdict_view,
```

Note: `series_change` accepts `list[list]` because it indexes `series[-1][1]` / `series[0][1]`, which works for the JSON `[date, value]` lists.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/api" && python -m pytest tests/test_trade_view_value.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty"
git add api/app/services/trade_view.py api/tests/test_trade_view_value.py
git commit -m "feat(api): surface per-trade value series + verdict on trade detail"
```

---

### Task 8: Backend — assemble aggregate series + verdict in `owner_view`

**Files:**
- Modify: `api/app/services/owner_view.py`
- Test: `api/tests/test_owner_view_value.py`

The owner aggregate Trade Value line comes from `entry.owner_value_series[uid]` (cached). The production change is derived at read time from the already-computed `career_arc` (last season's `production_total` minus the prior season's), so no new production-by-date plumbing is needed (per spec: twin readouts, not a shared axis).

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_owner_view_value.py`:

```python
from app.services.owner_view import _aggregate_value_view
from app.models.owner import AggregateVerdictView
from app.models.trade import ValuePoint


class _Arc:
    def __init__(self, production_total):
        self.production_total = production_total


def test_aggregate_value_view_trending_up():
    series = [["2026-06-07", 40000.0], ["2026-06-14", 52400.0]]
    arc = [_Arc(1000.0), _Arc(1840.0)]  # latest - prior = +840 production
    progression, verdict = _aggregate_value_view(series, arc)
    assert progression[-1] == ValuePoint(date="2026-06-14", value=52400.0)
    assert isinstance(verdict, AggregateVerdictView)
    assert verdict.label == "Trending up."
    assert verdict.value_change == 12400.0
    assert verdict.production_change == 840.0


def test_aggregate_value_view_empty_series_returns_none_verdict():
    progression, verdict = _aggregate_value_view([], [])
    assert progression == []
    assert verdict is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/api" && python -m pytest tests/test_owner_view_value.py -v`
Expected: FAIL with `ImportError: cannot import name '_aggregate_value_view'`

- [ ] **Step 3: Write the helper and wire it into `build_owner_detail`**

In `api/app/services/owner_view.py`, add imports near the top:

```python
from sleeper_dynasty.engine.value_series import aggregate_verdict, series_change
from app.models.owner import AggregateVerdictView
from app.models.trade import ValuePoint
```

Add the helper (module level):

```python
def _aggregate_value_view(series, arc):
    """Build (value_progression, value_verdict) for the owner aggregate card.

    series: list of [date, value]; arc: list of SeasonArc (ascending by season).
    Production change = last season's production_total minus the prior season's.
    """
    progression = [ValuePoint(date=d, value=v) for d, v in series]
    if not series:
        return progression, None
    value_change = series_change(series)
    value_base = series[0][1]
    if len(arc) >= 2:
        production_change = arc[-1].production_total - arc[-2].production_total
    elif arc:
        production_change = arc[-1].production_total
    else:
        production_change = 0.0
    verdict = AggregateVerdictView(
        **aggregate_verdict(value_change, value_base, production_change)
    )
    return progression, verdict
```

In `build_owner_detail`, after `arc` is built (lines ~99–107) and before the `return OwnerDetailResp(...)`, add:

```python
    owner_series = (entry.owner_value_series or {}).get(user_id) or []
    value_progression, value_verdict = _aggregate_value_view(owner_series, arc)
```

Then in the `OwnerDetailResp(...)` constructor (lines ~175–191), add:

```python
        value_progression=value_progression,
        value_verdict=value_verdict,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/api" && python -m pytest tests/test_owner_view_value.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty"
git add api/app/services/owner_view.py api/tests/test_owner_view_value.py
git commit -m "feat(api): surface aggregate value progression + verdict on owner detail"
```

---

### Task 9: Frontend — per-trade `TradeValueProgress` card

**Files:**
- Modify: `web/lib/types.ts` (new interfaces + extend `TradeDetailResp`)
- Create: `web/components/TradeValueProgress.tsx`
- Modify: `web/app/league/[id]/trade/[tid]/page.tsx` (render the card)
- Create: `web/tests/TradeValueProgress.test.tsx`

- [ ] **Step 1: Add TypeScript types**

In `web/lib/types.ts`, add near the trade types:

```typescript
export interface ValuePoint {
  date: string;
  value: number;
}

export interface ValueSidesView {
  received: ValuePoint[];
  given: ValuePoint[];
}

export interface PerTradeVerdict {
  label: string;
  sentence: string;
  tone: "good" | "bad" | "neutral";
  received_change: number;
  given_change: number;
}

export interface AggregateVerdict {
  label: string;
  sentence: string;
  tone: "good" | "bad" | "neutral";
  value_change: number;
  production_change: number;
}
```

Extend `TradeDetailResp` (lines ~334–346) — add:

```typescript
  value_series?: Record<string, ValueSidesView>;
  value_verdict?: Record<string, PerTradeVerdict>;
```

Extend `OwnerDetailResp` (lines ~234–250) — add:

```typescript
  value_progression?: ValuePoint[];
  value_verdict?: AggregateVerdict | null;
```

- [ ] **Step 2: Write the failing component test**

Create `web/tests/TradeValueProgress.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { TradeValueProgress } from "../components/TradeValueProgress";
import type { ValueSidesView, PerTradeVerdict } from "../lib/types";

const sides: ValueSidesView = {
  received: [{ date: "2026-06-07", value: 100 }, { date: "2026-06-14", value: 6900 }],
  given: [{ date: "2026-06-07", value: 8000 }, { date: "2026-06-14", value: 5000 }],
};
const verdict: PerTradeVerdict = {
  label: "Great trade.",
  sentence: "What you got gained value, and the player you gave up cooled off.",
  tone: "good",
  received_change: 6800,
  given_change: -3000,
};

describe("TradeValueProgress", () => {
  it("shows signed got/gave numbers and the verdict, with no 'KTC' leak", () => {
    const { container } = render(
      <TradeValueProgress ownerName="Tom" sides={sides} verdict={verdict} />,
    );
    expect(screen.getByText("Great trade.")).toBeInTheDocument();
    expect(screen.getByText(/What you got gained value/)).toBeInTheDocument();
    expect(screen.getByText("What you got")).toBeInTheDocument();
    expect(screen.getByText("What you gave up")).toBeInTheDocument();
    // signed numbers with arrows
    expect(screen.getByText(/▲/)).toBeInTheDocument();
    expect(screen.getByText(/▼/)).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/KTC/);
  });

  it("renders nothing when there is no series data", () => {
    const { container } = render(
      <TradeValueProgress ownerName="Tom"
        sides={{ received: [], given: [] }} verdict={undefined} />,
    );
    expect(container.firstChild).toBeNull();
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/web" && npm test -- TradeValueProgress`
Expected: FAIL — cannot resolve `../components/TradeValueProgress`.

- [ ] **Step 4: Write the component**

Create `web/components/TradeValueProgress.tsx`:

```tsx
import type { ValuePoint, ValueSidesView, PerTradeVerdict } from "../lib/types";

function fmtSigned(n: number): string {
  const arrow = n >= 0 ? "▲" : "▼";
  const sign = n >= 0 ? "+" : "−";
  return `${arrow} ${sign}${Math.abs(Math.round(n)).toLocaleString()}`;
}

function change(points: ValuePoint[]): number {
  if (points.length < 2) return 0;
  return points[points.length - 1].value - points[0].value;
}

/** Inline-SVG two-line chart: received (green) vs given (red), baseline dashed
 *  at the received series' first value. Follows the TradeValueSpark precedent. */
function Lines({ received, given }: ValueSidesView) {
  const all = [...received, ...given].map((p) => p.value);
  if (all.length === 0) return null;
  const max = Math.max(...all, 1);
  const min = Math.min(...all, 0);
  const span = max - min || 1;
  const W = 360;
  const H = 96;
  const x = (i: number, n: number) => (n <= 1 ? 0 : (i / (n - 1)) * W);
  const y = (v: number) => H - ((v - min) / span) * H;
  const path = (pts: ValuePoint[]) =>
    pts.map((p, i) => `${x(i, pts.length)},${y(p.value)}`).join(" ");
  const baseY = received.length ? y(received[0].value) : H / 2;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" className="rounded-md bg-surface">
      <line x1="0" y1={baseY} x2={W} y2={baseY} stroke="var(--divider)" strokeDasharray="3 3" />
      {received.length > 0 && (
        <polyline points={path(received)} fill="none" stroke="var(--pos)" strokeWidth="3" />
      )}
      {given.length > 0 && (
        <polyline points={path(given)} fill="none" stroke="var(--neg)" strokeWidth="3" />
      )}
    </svg>
  );
}

export function TradeValueProgress({
  ownerName,
  sides,
  verdict,
}: {
  ownerName: string;
  sides: ValueSidesView;
  verdict?: PerTradeVerdict;
}) {
  if (!sides || (sides.received.length === 0 && sides.given.length === 0)) return null;
  const gotChange = verdict ? verdict.received_change : change(sides.received);
  const gaveChange = verdict ? verdict.given_change : change(sides.given);
  const tint =
    verdict?.tone === "good" ? "bg-pos/10" : verdict?.tone === "bad" ? "bg-neg/10" : "bg-surface";
  return (
    <div className="bg-surface border border-divider rounded-card p-4">
      <div className="font-mono text-[10px] uppercase tracking-widest text-dim mb-2">
        {ownerName} · did it pan out?
      </div>
      <Lines received={sides.received} given={sides.given} />
      <div className="flex gap-6 mt-3">
        <div>
          <div className="text-[12px] text-dim">What you got</div>
          <div className={`text-[20px] font-semibold ${gotChange >= 0 ? "text-pos" : "text-neg"}`}>
            {fmtSigned(gotChange)}
          </div>
        </div>
        <div>
          <div className="text-[12px] text-dim">What you gave up</div>
          <div className={`text-[20px] font-semibold ${gaveChange >= 0 ? "text-pos" : "text-neg"}`}>
            {fmtSigned(gaveChange)}
          </div>
        </div>
      </div>
      {verdict && (
        <div className={`mt-3 rounded-md p-2.5 text-[13px] ${tint}`}>
          <strong>{verdict.label}</strong> {verdict.sentence}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/web" && npm test -- TradeValueProgress`
Expected: PASS (2 tests)

- [ ] **Step 6: Render the card on the trade detail page**

In `web/app/league/[id]/trade/[tid]/page.tsx`, import the component near the top:

```tsx
import { TradeValueProgress } from "../../../../../components/TradeValueProgress";
```

(Verify the relative depth matches the file's other component imports; copy the `../` prefix length from the existing `TradeStory`/`TradeSidePanel` imports in that file.)

Inside the `<TradeStory>` block (lines ~62–87), after the `<div className={...grid...}>` of `TradeSidePanel`s closes, add a per-side progression grid:

```tsx
        {data.value_series && Object.keys(data.value_series).length > 0 && (
          <div className={`grid gap-5 ${gridClass} mt-5`}>
            {data.sides.map((s) => (
              <TradeValueProgress
                key={`vp-${s.user_id}`}
                ownerName={displayNames[s.user_id] ?? s.owner_name}
                sides={data.value_series![s.user_id]}
                verdict={data.value_verdict?.[s.user_id]}
              />
            ))}
          </div>
        )}
```

(`gridClass` and `displayNames` already exist in this file — reuse them. If `displayNames` is keyed differently, match the existing `TradeSidePanel` usage.)

- [ ] **Step 7: Run the web test suite + typecheck**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/web" && npm test -- TradeValueProgress && npx tsc --noEmit`
Expected: tests PASS; `tsc` reports no errors (confirms the page wiring + new types compile).

- [ ] **Step 8: Commit**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty"
git add web/lib/types.ts web/components/TradeValueProgress.tsx web/app/league/[id]/trade/[tid]/page.tsx web/tests/TradeValueProgress.test.tsx
git commit -m "feat(web): per-trade Trade Value progression card"
```

---

### Task 10: Frontend — owner aggregate card on the Overview tab

**Files:**
- Create: `web/components/ownerdeepdive/ValueProgressionCard.tsx`
- Modify: `web/components/ownerdeepdive/OverviewTab.tsx` (render it)
- Create: `web/tests/ValueProgressionCard.test.tsx`

- [ ] **Step 1: Write the failing component test**

Create `web/tests/ValueProgressionCard.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ValueProgressionCard } from "../components/ownerdeepdive/ValueProgressionCard";
import type { ValuePoint, AggregateVerdict } from "../lib/types";

const progression: ValuePoint[] = [
  { date: "2026-06-07", value: 40000 },
  { date: "2026-06-14", value: 52400 },
];
const verdict: AggregateVerdict = {
  label: "Trending up.",
  sentence: "Your trade haul is worth more and scoring more than when tracking began.",
  tone: "good",
  value_change: 12400,
  production_change: 840,
};

describe("ValueProgressionCard", () => {
  it("shows the trend verdict and signed value/production, no 'KTC' leak", () => {
    const { container } = render(
      <ValueProgressionCard progression={progression} verdict={verdict} />,
    );
    expect(screen.getByText("Trending up.")).toBeInTheDocument();
    expect(screen.getByText("Trade value")).toBeInTheDocument();
    expect(screen.getByText("Points produced")).toBeInTheDocument();
    expect(screen.getByText(/▲ \+12,400/)).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/KTC/);
  });

  it("renders a friendly placeholder when there is no series yet", () => {
    render(<ValueProgressionCard progression={[]} verdict={null} />);
    expect(screen.getByText(/since we started tracking/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/web" && npm test -- ValueProgressionCard`
Expected: FAIL — cannot resolve the component.

- [ ] **Step 3: Write the component**

Create `web/components/ownerdeepdive/ValueProgressionCard.tsx`:

```tsx
import type { ValuePoint, AggregateVerdict } from "../../lib/types";

function fmtSigned(n: number): string {
  const arrow = n >= 0 ? "▲" : "▼";
  const sign = n >= 0 ? "+" : "−";
  return `${arrow} ${sign}${Math.abs(Math.round(n)).toLocaleString()}`;
}

function Spark({ points }: { points: ValuePoint[] }) {
  if (points.length < 2) return null;
  const vals = points.map((p) => p.value);
  const max = Math.max(...vals, 1);
  const min = Math.min(...vals, 0);
  const span = max - min || 1;
  const W = 360;
  const H = 64;
  const path = points
    .map((p, i) => `${(i / (points.length - 1)) * W},${H - ((p.value - min) / span) * H}`)
    .join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" className="rounded-md bg-surface">
      <polyline points={path} fill="none" stroke="var(--pos)" strokeWidth="3" />
    </svg>
  );
}

export function ValueProgressionCard({
  progression,
  verdict,
}: {
  progression?: ValuePoint[];
  verdict?: AggregateVerdict | null;
}) {
  if (!progression || progression.length < 2 || !verdict) {
    return (
      <div className="bg-surface border border-divider rounded-card p-4">
        <div className="font-mono text-[10px] uppercase tracking-widest text-dim mb-2">
          did your trades pan out?
        </div>
        <p className="text-[12px] text-dim">
          We&apos;ll show how your trade haul moves since we started tracking (Jun 2026).
        </p>
      </div>
    );
  }
  const tint =
    verdict.tone === "good" ? "bg-pos/10" : verdict.tone === "bad" ? "bg-neg/10" : "bg-surface";
  return (
    <div className="bg-surface border border-divider rounded-card p-4">
      <div className="font-mono text-[10px] uppercase tracking-widest text-dim mb-2">
        did your trades pan out?
      </div>
      <Spark points={progression} />
      <div className="flex gap-6 mt-3">
        <div>
          <div className="text-[12px] text-dim">Trade value</div>
          <div className={`text-[20px] font-semibold ${verdict.value_change >= 0 ? "text-pos" : "text-neg"}`}>
            {fmtSigned(verdict.value_change)}
          </div>
        </div>
        <div>
          <div className="text-[12px] text-dim">Points produced</div>
          <div className={`text-[20px] font-semibold ${verdict.production_change >= 0 ? "text-pos" : "text-neg"}`}>
            {fmtSigned(verdict.production_change)}
          </div>
        </div>
      </div>
      <div className={`mt-3 rounded-md p-2.5 text-[13px] ${tint}`}>
        <strong>{verdict.label}</strong> {verdict.sentence}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/web" && npm test -- ValueProgressionCard`
Expected: PASS (2 tests)

- [ ] **Step 5: Render it on the Overview tab**

In `web/components/ownerdeepdive/OverviewTab.tsx`, import the card near the top:

```tsx
import { ValueProgressionCard } from "./ValueProgressionCard";
```

In the returned grid (lines ~106–146), add a new cell after the existing "Track record" `Teaser`:

```tsx
      <ValueProgressionCard
        progression={detail.value_progression}
        verdict={detail.value_verdict}
      />
```

(The card renders its own bordered container, so it sits in the grid alongside the `Teaser` cards without wrapping in `Teaser`.)

- [ ] **Step 6: Run the web suite + typecheck**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/web" && npm test && npx tsc --noEmit`
Expected: all web tests PASS; `tsc` clean.

- [ ] **Step 7: Commit**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty"
git add web/components/ownerdeepdive/ValueProgressionCard.tsx web/components/ownerdeepdive/OverviewTab.tsx web/tests/ValueProgressionCard.test.tsx
git commit -m "feat(web): owner aggregate Trade Value progression card"
```

---

### Task 11: Full-suite verification + live smoke

**Files:** none (verification only)

- [ ] **Step 1: Run the entire backend + engine suite**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && python -m pytest -q && cd api && python -m pytest -q`
Expected: all PASS.

- [ ] **Step 2: Run the entire web suite + typecheck**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/web" && npm test && npx tsc --noEmit`
Expected: all PASS, `tsc` clean.

- [ ] **Step 3: Live smoke (dev league)**

With the backend running (`make dev-api`) and frontend (`make dev-web`), refresh the dev league `9000000000000000001` (trigger `GET /api/league/9000000000000000001/refresh` to repopulate the cache with the new series), then:

```bash
curl -s "http://localhost:8000/api/league/9000000000000000001/trade/<a-real-trade-id>" | python -m json.tool | grep -A3 value_verdict
curl -s "http://localhost:8000/api/league/9000000000000000001/owner/<a-real-uid>" | python -m json.tool | grep -A3 value_progression
```

Expected: `value_verdict` carries a `label` from the approved vocabulary; `value_progression` is a list of `{date, value}`. In the browser, the trade detail page shows the per-trade "did it pan out?" cards and the owner Overview tab shows the aggregate card. Confirm NO "KTC" string appears in either (it is "Trade Value" / "Value"). With only ~5 snapshot dates all in Jun 2026, lines will be short and mostly flat — that is expected (honesty limit #1) and the cards should still read cleanly.

- [ ] **Step 4: Final commit (if any smoke fixes were needed)**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty"
git add -A
git commit -m "test: verify Trade Value progression end-to-end"
```

---

## Self-Review

**Spec coverage:**
- Per-trade view (got vs gave, baseline = trade date) → Tasks 1, 4, 5, 7, 9 ✓
- Owner-aggregate view (Trade Value line + Production readout, baseline = first snapshot) → Tasks 1, 5, 8, 10 ✓
- `value_series` primitive reusing `make_price_providers` → Tasks 1, 5 ✓
- Given-side "sold high" counterfactual → Task 4 (`which="given"` → all held), Tasks 7, 9 ✓
- Drop-timestamp ingestion → Task 3 ✓
- Verdict classification (exact labels incl. user's edits, 5% flat threshold, single-side-flat collapse, up/up tiebreak) → Task 2 ✓
- Plain signed numbers + arrows + verdict card, literal colors, no index/"KTC" → Tasks 9, 10 (tests assert no "KTC" leak) ✓
- ChainCacheEntry fields, no SCHEMA bump → Task 5 ✓
- Honesty limits surfaced (pre-2026 flat, "since we started tracking") → Task 10 placeholder copy + Task 11 smoke ✓

**Placeholder scan:** Task 7 Step 1 describes a fixture rather than quoting it verbatim, because the exact `ChainCacheEntry` construction depends on the closest existing `trade_view` test helper — the step names the precise fields the fixture must carry and the assertions that gate the task, so there is no ambiguity about behavior. All other steps contain complete code.

**Type consistency:** `AssetTenure` fields are identical across Tasks 1/4/5. `value_series`/`series_change`/`sum_series`/`per_trade_verdict`/`aggregate_verdict` signatures match between definition (Tasks 1–2) and use (Tasks 5, 7, 8). Series JSON shape `[date, value]` is consistent: produced in Task 5 (`[[d, v] ...]`), consumed by `series_change` (indexes `[1]`) and the view assemblers (Tasks 7, 8) and TS `ValuePoint` (Task 9). Pydantic model names (`ValuePoint`, `ValueSidesView`, `PerTradeVerdictView`, `AggregateVerdictView`) match between Task 6 (definition) and Tasks 7, 8 (use) and the TS interfaces (Task 9).
