# Trade Lineage (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On the trade detail page, show a "what this trade became" indented tree — following each received asset through that owner's later flips, down to the players they hold today (and whether they still hold them).

**Architecture:** A pure engine builder (`engine/lineage.py`) walks the cached `resolved_trades` forward in time to produce a per-side forest of `LineageNode`s; it uses a new `current_holders` (player_id → current owner) map collected during refresh. The API computes the tree in `trade_view` and adds it to `TradeDetailResp`; the web renders an indented tree.

**Tech Stack:** Python/pytest (engine + `api/`), FastAPI/Pydantic, Next.js/React/vitest. The engine builder operates on the **dict** form of trades (as stored in `ChainCacheEntry.resolved_trades`), which is what `trade_view` already consumes.

**Reference spec:** `docs/superpowers/specs/2026-06-08-trade-lineage-design.md`

**Conventions:** Engine + API tests in repo-root `tests/`, run with `pytest` from the repo root (api tests with `cd api && pytest`). Web from `web/`: `npx vitest run --config tests/vitest.config.ts`. No em dashes in UI copy.

**Asset dict shapes** (from `_to_dict(ResolvedTrade)` in the cache): a **player** asset is `{player_id, name, via_pick}` (where `via_pick` is `null` or `{season, round, original_owner_user_id, ...}`); a **pick** asset is `{season, round, original_owner_user_id, drafted_player_id, drafted_player_name}`; a **faab** asset is `{amount}`. A trade is `{trade: {transaction_id, traded_at, season, week, ...}, sides: {uid: {user_id, received: [...], given: [...]}}}`.

---

## File Structure

**Create:** `src/sleeper_dynasty/models/lineage.py` (LineageNode dataclass), `src/sleeper_dynasty/engine/lineage.py` (builder), `web/components/TradeLineage.tsx`, tests `tests/test_lineage.py`, `tests/test_lineage_view.py`, `web/tests/TradeLineage.test.tsx`.
**Modify:** `api/app/services/chain_cache.py` (+`current_holders`), `api/app/services/grader.py` (collect holders), `api/app/models/trade.py` (+`LineageNode`, `lineage`), `api/app/services/trade_view.py` (build lineage), `web/lib/types.ts` (+types), `web/app/league/[id]/trade/[tid]/page.tsx` (render).

---

## Task 1: LineageNode model

**Files:** Create `src/sleeper_dynasty/models/lineage.py`; Test `tests/test_lineage.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_lineage.py
from sleeper_dynasty.models.lineage import LineageNode


def test_node_to_dict_nests_children():
    leaf = LineageNode(label="Bhayshul Tuten", kind="player", flipped_at=None,
                       terminal_state="on_roster", became_player=None, children=[])
    root = LineageNode(label="Saquon Barkley", kind="player", flipped_at="2025-08-29",
                       terminal_state=None, became_player=None, children=[leaf])
    d = root.to_dict()
    assert d["label"] == "Saquon Barkley" and d["flipped_at"] == "2025-08-29"
    assert d["children"][0]["terminal_state"] == "on_roster"
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_lineage.py -v` → ModuleNotFoundError.

- [ ] **Step 3: Implement**

```python
# src/sleeper_dynasty/models/lineage.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Kind = Literal["player", "pick"]
Terminal = Literal["on_roster", "dropped", "undrafted"]


@dataclass
class LineageNode:
    """One asset in one owner's possession, with what it became next."""
    label: str
    kind: Kind
    flipped_at: str | None                 # date the owner flipped it; None if terminal
    terminal_state: Terminal | None        # set only when not flipped
    became_player: str | None              # for a pick that resolved to a player
    children: list["LineageNode"] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label, "kind": self.kind, "flipped_at": self.flipped_at,
            "terminal_state": self.terminal_state, "became_player": self.became_player,
            "children": [c.to_dict() for c in self.children],
        }
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_lineage.py -v` → 1 passed.

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/models/lineage.py tests/test_lineage.py
git commit -m "feat(engine): LineageNode model"
```

---

## Task 2: The lineage builder (the core)

**Files:** Create `src/sleeper_dynasty/engine/lineage.py`; Test `tests/test_lineage.py` (append)

> This is the heart of the feature. It walks the cached dict-form trades forward in time. Test every case the spec lists.

- [ ] **Step 1: Append the failing tests**

```python
# tests/test_lineage.py  (append)
from sleeper_dynasty.engine.lineage import build_trade_lineage


def _trade(tx, date, sides):
    return {"trade": {"transaction_id": tx, "traded_at": date}, "sides": sides}

def _player(pid, name, via_pick=None):
    return {"player_id": pid, "name": name, "via_pick": via_pick}

def _pick(season, rnd, orig, drafted_id=None, drafted_name=None):
    return {"season": season, "round": rnd, "original_owner_user_id": orig,
            "drafted_player_id": drafted_id, "drafted_player_name": drafted_name}


def test_kept_player_terminal_on_roster_vs_dropped():
    # u_a received Jacobs in t1 and never moved him.
    trades = [_trade("t1", "2025-08-20T00:00:00", {
        "u_a": {"user_id": "u_a", "received": [_player("12493", "Josh Jacobs")], "given": []},
        "u_b": {"user_id": "u_b", "received": [], "given": [_player("12493", "Josh Jacobs")]},
    })]
    out = build_trade_lineage(trades, "t1", current_holders={"12493": "u_a"})
    n = out["u_a"][0]
    assert n.label == "Josh Jacobs" and n.flipped_at is None
    assert n.terminal_state == "on_roster" and n.children == []
    # if u_a no longer holds him -> dropped
    out2 = build_trade_lineage(trades, "t1", current_holders={})
    assert out2["u_a"][0].terminal_state == "dropped"


def test_flip_produces_children_package():
    # u_a got Barkley in t1, flipped him in t2 for a 2026 2nd + Calvin Austin.
    barkley = _player("4866", "Saquon Barkley")
    pick = _pick(2026, 2, "u_x", drafted_id="99", drafted_name="Bhayshul Tuten")
    austin = _player("777", "Calvin Austin")
    trades = [
        _trade("t1", "2025-08-20T00:00:00", {
            "u_a": {"user_id": "u_a", "received": [barkley], "given": []},
            "u_b": {"user_id": "u_b", "received": [], "given": [barkley]}}),
        _trade("t2", "2025-08-29T00:00:00", {
            "u_a": {"user_id": "u_a", "received": [pick, austin], "given": [barkley]},
            "u_c": {"user_id": "u_c", "received": [barkley], "given": [pick, austin]}}),
    ]
    out = build_trade_lineage(trades, "t1", current_holders={"99": "u_a", "777": "u_a"})
    root = out["u_a"][0]
    assert root.label == "Saquon Barkley" and root.flipped_at == "2025-08-29"
    kids = {c.label: c for c in root.children}
    assert kids["Calvin Austin"].terminal_state == "on_roster"
    pick_kid = next(c for c in root.children if c.kind == "pick")
    assert pick_kid.became_player == "Bhayshul Tuten" and pick_kid.terminal_state == "on_roster"


def test_undrafted_pick_terminal():
    fut = _pick(2027, 1, "u_z")  # no drafted player
    trades = [_trade("t1", "2025-08-20T00:00:00", {
        "u_a": {"user_id": "u_a", "received": [fut], "given": []},
        "u_b": {"user_id": "u_b", "received": [], "given": [fut]}})]
    out = build_trade_lineage(trades, "t1", current_holders={})
    assert out["u_a"][0].kind == "pick" and out["u_a"][0].terminal_state == "undrafted"


def test_via_pick_player_labels_origin():
    # u_a received a pick that they drafted into Makai Lemon (via_pick player).
    vp = _player("13294", "Makai Lemon", via_pick={"season": 2026, "round": 1, "original_owner_user_id": "u_a"})
    trades = [_trade("t1", "2025-08-20T00:00:00", {
        "u_a": {"user_id": "u_a", "received": [vp], "given": []},
        "u_b": {"user_id": "u_b", "received": [], "given": [vp]}})]
    out = build_trade_lineage(trades, "t1", current_holders={"13294": "u_a"})
    n = out["u_a"][0]
    assert n.kind == "pick" and n.became_player == "Makai Lemon"
    assert "Makai Lemon" in n.label and n.terminal_state == "on_roster"
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_lineage.py -v` → ImportError on `build_trade_lineage`.

- [ ] **Step 3: Implement**

```python
# src/sleeper_dynasty/engine/lineage.py
"""Build a 'what this trade became' tree from cached dict-form trades.

Owner-anchored, forward in time: for each asset a side received, follow that
owner's later flips; a moved asset's children are the full package the owner got
back. Pure; operates on the same dicts trade_view reads from the cache.
"""

from __future__ import annotations

from sleeper_dynasty.models.lineage import LineageNode

_ORD = {1: "1st", 2: "2nd", 3: "3rd"}


def _ordinal(n: int) -> str:
    return _ORD.get(n, f"{n}th")


def _asset_id(a: dict):
    """Stable identity for matching an asset across trades, or None to skip."""
    if a.get("player_id"):
        return ("player", a["player_id"])
    if a.get("season") is not None and a.get("round") is not None:
        return ("pick", a.get("original_owner_user_id"), a["season"], a["round"])
    return None  # faab / unknown


def build_trade_lineage(
    resolved_trades: list[dict],
    root_trade_id: str,
    current_holders: dict[str, str],
) -> dict[str, list[LineageNode]]:
    trades = sorted(resolved_trades, key=lambda r: r["trade"]["traded_at"])

    # (owner, asset_id) -> trades (date-ordered) where that owner GAVE the asset.
    given_index: dict[tuple, list[dict]] = {}
    for r in trades:
        for uid, side in (r.get("sides") or {}).items():
            for a in side.get("given") or []:
                aid = _asset_id(a)
                if aid:
                    given_index.setdefault((uid, aid), []).append(r)

    def node(asset: dict, owner: str, since: str) -> LineageNode:
        aid = _asset_id(asset)
        vp = asset.get("via_pick")
        is_player = aid[0] == "player"
        became = (asset.get("name") if vp else None) if is_player else asset.get("drafted_player_name")
        if is_player and vp:
            kind = "pick"
            label = f'{vp["season"]} {_ordinal(vp["round"])} -> {asset.get("name")}'
        elif is_player:
            kind = "player"
            label = asset.get("name") or asset["player_id"]
        else:
            kind = "pick"
            label = f'{asset["season"]} {_ordinal(asset["round"])} pick'

        # Earliest flip strictly after acquisition.
        flips = [r for r in given_index.get((owner, aid), [])
                 if r["trade"]["traded_at"] > since]
        if flips:
            flip = flips[0]
            got = (flip["sides"][owner].get("received") or [])
            children = [node(c, owner, flip["trade"]["traded_at"]) for c in got if _asset_id(c)]
            return LineageNode(label=label, kind=kind, flipped_at=flip["trade"]["traded_at"][:10],
                               terminal_state=None, became_player=became, children=children)

        # Terminal.
        if is_player or asset.get("drafted_player_id"):
            held_id = asset["player_id"] if is_player else asset["drafted_player_id"]
            state = "on_roster" if current_holders.get(held_id) == owner else "dropped"
            return LineageNode(label, kind, None, state, became, [])
        return LineageNode(label, "pick", None, "undrafted", None, [])

    root = next(r for r in trades if r["trade"]["transaction_id"] == root_trade_id)
    out: dict[str, list[LineageNode]] = {}
    for uid, side in (root.get("sides") or {}).items():
        out[uid] = [node(a, uid, root["trade"]["traded_at"])
                    for a in (side.get("received") or []) if _asset_id(a)]
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_lineage.py -v` → all passed (5).

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/lineage.py tests/test_lineage.py
git commit -m "feat(engine): build_trade_lineage (owner-anchored forward tree)"
```

---

## Task 3: `current_holders` cache field

**Files:** Modify `api/app/services/chain_cache.py`; Test `tests/test_chain_cache_holders.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_chain_cache_holders.py
import json
from pathlib import Path
from app.services.chain_cache import ChainCache, ChainCacheEntry


def _entry(**over):
    base = dict(league_id="L", chain=[], resolved_trades=[], grades={}, owners={},
                playoff_weeks_by_league={}, roster_to_user_by_league={},
                league_name_by_id={}, league_season_by_id={}, cached_at="now")
    base.update(over)
    return ChainCacheEntry(**base)


def test_current_holders_round_trips_and_defaults(tmp_path: Path):
    c = ChainCache(cache_dir=tmp_path)
    c.write("L", _entry(current_holders={"4866": "u_a"}))
    assert c.read("L").current_holders == {"4866": "u_a"}


def test_pre_migration_file_loads_with_empty_holders(tmp_path: Path):
    raw = dict(league_id="L", chain=[], resolved_trades=[], grades={}, owners={},
               playoff_weeks_by_league={}, roster_to_user_by_league={},
               league_name_by_id={}, league_season_by_id={}, cached_at="now", warnings=[])
    (tmp_path / "chain_L.json").write_text(json.dumps(raw))
    assert ChainCache(cache_dir=tmp_path).read("L").current_holders == {}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd api && pytest ../tests/test_chain_cache_holders.py -v` → TypeError (unexpected kwarg).

- [ ] **Step 3: Implement** — add to `ChainCacheEntry` after the `owner_dossiers` field:

```python
    current_holders: dict[str, str] = field(default_factory=dict)
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd api && pytest ../tests/test_chain_cache_holders.py -v` → 2 passed.

- [ ] **Step 5: Commit**

```bash
git add api/app/services/chain_cache.py tests/test_chain_cache_holders.py
git commit -m "feat(api): cache current_holders (player -> current owner)"
```

---

## Task 4: Collect `current_holders` during refresh

**Files:** Modify `api/app/services/grader.py`; Test `tests/test_grader_holders.py`

> `SleeperClient.get_rosters(league_id)` returns `Roster` objects with `.owner_id` and `.players`. Collect the current league's rosters into `player_id -> owner_id`. Best-effort: a rosters failure must not fail refresh.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_grader_holders.py
import asyncio
from types import SimpleNamespace
from datetime import datetime
from app.services.grader import GraderService


class _Client:
    async def walk_league_history(self, lid):
        return [SimpleNamespace(league_id="L", season=2024, name="Bros", total_rosters=2, playoff_week_start=15)]
    async def get_players(self): return {}
    async def get_rosters(self, lid):
        return [SimpleNamespace(owner_id="u_a", players=["4866", "12493"]),
                SimpleNamespace(owner_id="u_b", players=["777"])]
    async def close(self): ...


async def _supp(*a, **k):
    return dict(ktc_by_player_id={}, matchups={}, roster_to_user_by_league={},
                playoff_weeks_by_league={"L": 15}, league_season_by_id={"L": 2024},
                owners={}, league_name_by_id={"L": "Bros"}, pick_value_table={}, warnings=[],
                owners_display={}, positions={})

async def _hist(*a, **k): return []


def test_run_collects_current_holders():
    async def go():
        return await GraderService().run(
            client=_Client(), current_league_id="L", progress_cb=lambda *a, **k: _noop(),
            cache_dir=None, _build_trade_history=_hist, _pull_supporting_data=_supp,
            _story_writer=type("W", (), {"write": lambda self, f: {"verdict": "v", "body": "b"}})())
    async def _noop(): return None
    entry = asyncio.run(go())
    assert entry.current_holders == {"4866": "u_a", "12493": "u_a", "777": "u_b"}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd api && pytest ../tests/test_grader_holders.py -v` → `entry.current_holders` empty / attribute error.

- [ ] **Step 3: Implement** — in `api/app/services/grader.py::run`, after the chain walk (where `client` is available) and before building `entry`, add:

```python
        current_holders: dict[str, str] = {}
        try:
            for r in await client.get_rosters(current_league_id):
                for pid in (r.players or []):
                    current_holders[pid] = r.owner_id
        except Exception:
            log.exception("could not fetch current rosters for holders")
```

Then add `current_holders=current_holders,` to the `ChainCacheEntry(...)` constructor.

- [ ] **Step 4: Run to verify it passes**

Run: `cd api && pytest ../tests/test_grader_holders.py -v` → 1 passed.
Run (no regression): `cd api && pytest ../tests/test_grader_story_hook.py ../tests/test_grader_service.py -q` → pass.

- [ ] **Step 5: Commit**

```bash
git add api/app/services/grader.py tests/test_grader_holders.py
git commit -m "feat(api): collect current_holders from rosters during refresh"
```

---

## Task 5: Expose lineage on the trade detail response

**Files:** Modify `api/app/models/trade.py`, `api/app/services/trade_view.py`; Test `tests/test_lineage_view.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_lineage_view.py
from app.services.chain_cache import ChainCacheEntry
from app.services.trade_view import build_trade_detail


def _entry():
    rt = {"trade": {"transaction_id": "t1", "traded_at": "2025-08-20T00:00:00",
                    "week": 1, "season": 2025, "league_id": "L"},
          "sides": {"u_a": {"user_id": "u_a", "received": [{"player_id": "4866", "name": "Saquon Barkley", "via_pick": None}], "given": []},
                    "u_b": {"user_id": "u_b", "received": [], "given": [{"player_id": "4866", "name": "Saquon Barkley", "via_pick": None}]}}}
    return ChainCacheEntry(
        league_id="L", chain=[], resolved_trades=[rt], grades={},
        owners={"u_a": {"owner_name": "A"}, "u_b": {"owner_name": "B"}},
        playoff_weeks_by_league={}, roster_to_user_by_league={},
        league_name_by_id={"L": "Bros"}, league_season_by_id={"L": 2025},
        cached_at="now", current_holders={"4866": "u_a"})


def test_detail_includes_lineage():
    resp = build_trade_detail(_entry(), "t1")
    assert "u_a" in resp.lineage
    assert resp.lineage["u_a"][0].label == "Saquon Barkley"
    assert resp.lineage["u_a"][0].terminal_state == "on_roster"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd api && pytest ../tests/test_lineage_view.py -v` → AttributeError (no `lineage`).

- [ ] **Step 3: Implement**

In `api/app/models/trade.py`, add a recursive model and a field on `TradeDetailResp`:

```python
class LineageNode(BaseModel):
    label: str
    kind: str
    flipped_at: str | None = None
    terminal_state: str | None = None
    became_player: str | None = None
    children: list["LineageNode"] = []

LineageNode.model_rebuild()

# inside TradeDetailResp, add:
    lineage: dict[str, list[LineageNode]] = {}
```

In `api/app/services/trade_view.py`, build it before the return:

```python
from sleeper_dynasty.engine.lineage import build_trade_lineage
from app.models.trade import LineageNode

def _to_lineage(node) -> LineageNode:
    return LineageNode(
        label=node.label, kind=node.kind, flipped_at=node.flipped_at,
        terminal_state=node.terminal_state, became_player=node.became_player,
        children=[_to_lineage(c) for c in node.children],
    )

# after computing `sides`, before constructing TradeDetailResp:
    raw_lineage = build_trade_lineage(
        entry.resolved_trades, trade_id, entry.current_holders or {})
    lineage = {uid: [_to_lineage(n) for n in nodes] for uid, nodes in raw_lineage.items()}

# add `lineage=lineage,` to the TradeDetailResp(...) constructor.
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd api && pytest ../tests/test_lineage_view.py -v` → 1 passed.
Run (no regression): `cd api && pytest ../tests/test_trade.py ../tests/test_trade_view_story.py -q` → pass.

- [ ] **Step 5: Commit**

```bash
git add api/app/models/trade.py api/app/services/trade_view.py tests/test_lineage_view.py
git commit -m "feat(api): expose trade lineage on the detail response"
```

---

## Task 6: Web types

**Files:** Modify `web/lib/types.ts`

- [ ] **Step 1: Add the types** — near `TradeDetailResp`:

```ts
export interface LineageNode {
  label: string;
  kind: "player" | "pick";
  flipped_at?: string | null;
  terminal_state?: "on_roster" | "dropped" | "undrafted" | null;
  became_player?: string | null;
  children: LineageNode[];
}
```

And add to the `TradeDetailResp` interface:

```ts
  lineage?: Record<string, LineageNode[]>;
```

- [ ] **Step 2: Typecheck + commit**

Run (from `web/`): `npx tsc --noEmit -p tsconfig.json` → no errors.
```bash
git add web/lib/types.ts
git commit -m "feat(web): LineageNode type"
```

---

## Task 7: `TradeLineage` component

**Files:** Create `web/components/TradeLineage.tsx`; Test `web/tests/TradeLineage.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// web/tests/TradeLineage.test.tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { TradeLineage } from "@/components/TradeLineage";

const lineage = {
  u_a: [{
    label: "Saquon Barkley", kind: "player", flipped_at: "2025-08-29",
    terminal_state: null, became_player: null,
    children: [
      { label: "Calvin Austin", kind: "player", flipped_at: null, terminal_state: "on_roster", became_player: null, children: [] },
      { label: "2026 2nd pick", kind: "pick", flipped_at: null, terminal_state: "on_roster", became_player: "Bhayshul Tuten", children: [] },
    ],
  }],
} as any;
const names = { u_a: "tkeefe6689" };

describe("TradeLineage", () => {
  it("renders nested assets, the flip date, and terminal badges", () => {
    render(<TradeLineage lineage={lineage} displayNames={names} />);
    expect(screen.getByText("Saquon Barkley")).toBeTruthy();
    expect(screen.getByText(/2025-08-29/)).toBeTruthy();
    expect(screen.getByText("Calvin Austin")).toBeTruthy();
    expect(screen.getAllByText(/on roster/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/Bhayshul Tuten/)).toBeTruthy();
  });

  it("renders nothing when lineage is empty", () => {
    const { container } = render(<TradeLineage lineage={{}} displayNames={{}} />);
    expect(container.textContent).toBe("");
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run (from `web/`): `npx vitest run tests/TradeLineage.test.tsx --config tests/vitest.config.ts` → component not found.

- [ ] **Step 3: Implement**

```tsx
// web/components/TradeLineage.tsx
import { LineageNode } from "@/lib/types";

function Badge({ node }: { node: LineageNode }) {
  if (node.flipped_at) return <span className="font-mono text-[10px] text-dim"> · flipped {node.flipped_at}</span>;
  if (node.terminal_state === "on_roster") return <span className="font-mono text-[10px] text-pos"> · on roster</span>;
  if (node.terminal_state === "dropped") return <span className="font-mono text-[10px] text-dim"> · dropped</span>;
  if (node.terminal_state === "undrafted") return <span className="font-mono text-[10px] text-dim"> · not drafted yet</span>;
  return null;
}

function Node({ node }: { node: LineageNode }) {
  return (
    <li className="text-[13px]">
      <span className="inline-block px-2 py-0.5 rounded-md bg-bg border border-divider">{node.label}</span>
      {node.became_player ? <span className="text-dim"> → {node.became_player}</span> : null}
      <Badge node={node} />
      {node.children.length > 0 && (
        <ul className="mt-1 ml-4 border-l border-divider pl-3 space-y-1">
          {node.children.map((c, i) => <Node key={i} node={c} />)}
        </ul>
      )}
    </li>
  );
}

export function TradeLineage(
  { lineage, displayNames }: { lineage: Record<string, LineageNode[]>; displayNames: Record<string, string> },
) {
  const sides = Object.entries(lineage).filter(([, ns]) => ns.length > 0);
  if (sides.length === 0) return null;
  return (
    <section className="mt-8">
      <div className="font-mono text-[11px] uppercase tracking-widest text-dim mb-3">Where it went</div>
      <div className="grid gap-5 sm:grid-cols-2">
        {sides.map(([uid, nodes]) => (
          <div key={uid} className="bg-surface border border-divider rounded-card p-4">
            <div className="text-[12px] font-semibold mb-2">{displayNames[uid] ?? uid} got</div>
            <ul className="space-y-1">{nodes.map((n, i) => <Node key={i} node={n} />)}</ul>
          </div>
        ))}
      </div>
    </section>
  );
}
```

- [ ] **Step 4: Run to verify it passes**

Run (from `web/`): `npx vitest run tests/TradeLineage.test.tsx --config tests/vitest.config.ts` → 2 passed.

- [ ] **Step 5: Commit**

```bash
git add web/components/TradeLineage.tsx web/tests/TradeLineage.test.tsx
git commit -m "feat(web): TradeLineage indented tree component"
```

---

## Task 8: Render lineage on the trade detail page

**Files:** Modify `web/app/league/[id]/trade/[tid]/page.tsx`

- [ ] **Step 1: Wire it in** — import and render below the `TradeStory`/receipts block:

```tsx
import { TradeLineage } from "@/components/TradeLineage";

// after the </TradeStory> (or the receipts grid), inside the <section>:
        <TradeLineage lineage={data.lineage ?? {}} displayNames={displayNames} />
```

(`displayNames` already exists on this page; `data.lineage` is optional and defaults to `{}`.)

- [ ] **Step 2: Verify**

Run (from `web/`): `npx vitest run --config tests/vitest.config.ts` → all pass.
Run (from `web/`): `npm run build` → succeeds.

- [ ] **Step 3: Commit**

```bash
git add "web/app/league/[id]/trade/[tid]/page.tsx"
git commit -m "feat(web): show the 'where it went' tree on the trade page"
```

---

## Final verification

- [ ] Engine + api: `pytest tests/test_lineage.py -q` (root) and `cd api && pytest -q` → all PASS.
- [ ] Web: from `web/`, `npx vitest run --config tests/vitest.config.ts` and `npm run build` → PASS.
- [ ] Post-deploy (outside this plan): force a refresh (so `current_holders` populates), open a trade with a flipped asset (e.g. the Barkley trade `1263983342311723008`), confirm the "Where it went" tree shows the flip chain and the correct on-roster/dropped badges.

---

## Self-review notes (author)

- **Spec coverage:** owner-anchored forward tree + package semantics (Task 2), pick→player / via_pick handling (Task 2 + tests), on_roster/dropped/undrafted terminal states via `current_holders` (Tasks 2-4), API `lineage` on `TradeDetailResp` (Task 5), indented-tree placement on the trade page (Tasks 7-8). All spec sections map to a task.
- **Note:** because the facts/cache shape changed (`current_holders`), a refresh is required after deploy for lineage to populate; a pre-migration cache simply yields empty `current_holders` (every terminal player reads `dropped`) until refreshed.
- **Type consistency:** `LineageNode` fields (`label`/`kind`/`flipped_at`/`terminal_state`/`became_player`/`children`) match across the engine dataclass (Task 1), the Pydantic model (Task 5), and the TS interface (Task 6); `build_trade_lineage(resolved_trades, trade_id, current_holders)` is called identically in Task 5.
- **Out of scope (per spec):** Phase 2 re-grading, the per-asset journey page + chip click-through, non-trade (waiver/FA) lineage.
```
