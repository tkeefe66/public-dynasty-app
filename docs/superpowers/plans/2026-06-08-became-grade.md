# Became-Grade + Bounded Lineage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Re-bound the lineage tree to the "one player-flip, follow picks to players, players are terminal" rule, and add a parallel "what it became" grade (four metrics on the terminal players) shown beside the direct receipts.

**Architecture:** One bounded forward-walk in `engine/lineage.py` feeds both the tree (Phase 1) and a new `engine/regrade.py` that values + scores the terminal players. The became-grade is computed during refresh and cached on `ChainCacheEntry.became_grades`, exposed on `TradeDetailResp.became`, and rendered by a new `TradeBecame` component.

**Tech Stack:** Python/pytest (engine + api), FastAPI/Pydantic, Next.js/vitest. Engine operates on the cached dict-form trades.

**Reference spec:** `docs/superpowers/specs/2026-06-08-became-grade-design.md`. Mirror the Phase-1 lineage + trade-story patterns: `became_grades` parallels `trade_stories`; `became` parallels `lineage`; `TradeBecame.tsx` parallels `TradeLineage.tsx`.

**Conventions:** Engine tests in repo-root `tests/` (`pytest`); api tests in `api/tests/` (`cd api && pytest`); web from `web/` (`npx vitest run --config tests/vitest.config.ts`). Use python3.11 if bare `pytest` resolves to 3.9.

**THE RULE (memorize):** a *received player* follows exactly **one flip** (its result players are terminal); a *pick* (received or derived) is followed through every flip/draft until it becomes **players**; **derived players are terminal** (never followed). Terminal players are valued at current KTC + the points they scored while this side owned them.

---

## Task 1: Bounded lineage walk (revise `engine/lineage.py`)

**Files:** Modify `src/sleeper_dynasty/engine/lineage.py`; Test `tests/test_lineage.py` (append new cases)

> The current `build_trade_lineage` recurses on ALL children without limit. Change it so the recursion distinguishes the **root** received asset (a player gets one flip) from **derived** assets (a player is terminal; a pick keeps following). Picks always follow.

- [ ] **Step 1: Append failing tests** to `tests/test_lineage.py`:

```python
def test_received_player_one_flip_then_terminal():
    # A received; A -> flip -> B(player) + P1(pick). B is terminal; if B is later
    # flipped, we do NOT follow it.
    A = _player("A", "Player A"); B = _player("B", "Player B")
    P1 = _pick(2026, 1, "u_x", drafted_id="C", drafted_name="Player C")
    later = _player("Z", "Player Z")
    trades = [
        _trade("t1", "2025-01-01T00:00:00", {
            "u_a": {"user_id": "u_a", "received": [A], "given": []},
            "u_b": {"user_id": "u_b", "received": [], "given": [A]}}),
        _trade("t2", "2025-02-01T00:00:00", {
            "u_a": {"user_id": "u_a", "received": [B, P1], "given": [A]},
            "u_c": {"user_id": "u_c", "received": [A], "given": [B, P1]}}),
        # u_a later flips B -> Z. Must NOT be followed (B is a derived player).
        _trade("t3", "2025-03-01T00:00:00", {
            "u_a": {"user_id": "u_a", "received": [later], "given": [B]},
            "u_c": {"user_id": "u_c", "received": [B], "given": [later]}}),
    ]
    out = build_trade_lineage(trades, "t1", current_holders={})
    root = out["u_a"][0]
    assert root.flipped_at == "2025-02-01"
    kids = {c.label: c for c in root.children}
    assert kids["Player B"].children == []          # derived player: terminal, NOT followed
    assert kids["Player B"].flipped_at is None
    # P1 is a pick -> followed -> drafted into Player C (terminal player)
    pick_kid = next(c for c in root.children if c.kind == "pick")
    assert pick_kid.became_player == "Player C"


def test_pick_followed_through_multiple_flips():
    # P1 flipped -> C(player, terminal) + P2(pick) ; P2 flipped -> D(player) + nothing.
    P1 = _pick(2026, 1, "u_x"); C = _player("C", "Player C")
    P2 = _pick(2027, 1, "u_x"); D = _player("D", "Player D")
    trades = [
        _trade("t1", "2025-01-01T00:00:00", {
            "u_a": {"user_id": "u_a", "received": [P1], "given": []},
            "u_b": {"user_id": "u_b", "received": [], "given": [P1]}}),
        _trade("t2", "2025-02-01T00:00:00", {
            "u_a": {"user_id": "u_a", "received": [C, P2], "given": [P1]},
            "u_b": {"user_id": "u_b", "received": [P1], "given": [C, P2]}}),
        _trade("t3", "2025-03-01T00:00:00", {
            "u_a": {"user_id": "u_a", "received": [D], "given": [P2]},
            "u_b": {"user_id": "u_b", "received": [P2], "given": [D]}}),
    ]
    out = build_trade_lineage(trades, "t1", current_holders={})
    root = out["u_a"][0]                 # P1
    labels = {c.label for c in root.children}
    assert any("Player C" in l for l in labels)         # C terminal
    p2 = next(c for c in root.children if c.kind == "pick" and c.children)
    assert any(gc.label == "Player D" for gc in p2.children)  # P2 followed -> D terminal
```

(Keep the existing `test_lineage.py` cases — they only go one hop deep and stay green under the bounded rule.)

- [ ] **Step 2: Run** `pytest tests/test_lineage.py -v` → the two new tests fail (current code follows B's flip / behaves differently).

- [ ] **Step 3: Rewrite the recursion** in `build_trade_lineage`. Replace the inner `node(...)` with a root/derived split. The walk: for the **root** received assets call `walk_root`; children of any flip are built with `walk_derived`.

```python
    def _flip_after(owner, aid, since):
        flips = [r for r in given_index.get((owner, aid), [])
                 if r["trade"]["traded_at"] > since]
        return flips[0] if flips else None

    def _children(flip, owner):
        got = flip["sides"][owner].get("received") or []
        return [walk_derived(c, owner, flip["trade"]["traded_at"])
                for c in got if _asset_id(c)]

    def _label_kind_became(asset):
        aid = _asset_id(asset); vp = asset.get("via_pick")
        is_player = aid[0] == "player"
        if is_player and vp:
            return (f'{vp["season"]} {_ordinal(vp["round"])} -> {asset.get("name")}',
                    "pick", asset.get("name"))
        if is_player:
            return (asset.get("name") or asset["player_id"], "player", None)
        return (f'{asset["season"]} {_ordinal(asset["round"])} pick', "pick",
                asset.get("drafted_player_name"))

    def _terminal_player(asset, owner, label, kind, became):
        is_player = _asset_id(asset)[0] == "player"
        held_id = asset["player_id"] if is_player else asset.get("drafted_player_id")
        if held_id:
            state = "on_roster" if current_holders.get(held_id) == owner else "dropped"
            return LineageNode(label, kind, None, state, became, [])
        return LineageNode(label, "pick", None, "undrafted", None, [])

    def walk_pick(asset, owner, since):
        label, kind, became = _label_kind_became(asset)
        flip = _flip_after(owner, _asset_id(asset), since)
        if flip:
            return LineageNode(label, kind, flip["trade"]["traded_at"][:10], None,
                               became, _children(flip, owner))
        return _terminal_player(asset, owner, label, kind, became)  # drafted or undrafted

    def walk_derived(asset, owner, since):
        # Derived PLAYER -> terminal (no flip). Derived PICK -> keep following.
        if _asset_id(asset)[0] == "player":
            label, kind, became = _label_kind_became(asset)
            return _terminal_player(asset, owner, label, kind, became)
        return walk_pick(asset, owner, since)

    def walk_root(asset, owner, since):
        # Root PLAYER -> exactly one flip. Root PICK -> follow like a pick.
        if _asset_id(asset)[0] == "pick":
            return walk_pick(asset, owner, since)
        label, kind, became = _label_kind_became(asset)
        flip = _flip_after(owner, _asset_id(asset), since)
        if flip:
            return LineageNode(label, kind, flip["trade"]["traded_at"][:10], None,
                               became, _children(flip, owner))
        return _terminal_player(asset, owner, label, kind, became)
```

Then change the root loop to use `walk_root`:

```python
    root = next(r for r in trades if r["trade"]["transaction_id"] == root_trade_id)
    out: dict[str, list[LineageNode]] = {}
    for uid, side in (root.get("sides") or {}).items():
        out[uid] = [walk_root(a, uid, root["trade"]["traded_at"])
                    for a in (side.get("received") or []) if _asset_id(a)]
    return out
```

- [ ] **Step 4: Run** `pytest tests/test_lineage.py -v` → all pass (old + 2 new).

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/lineage.py tests/test_lineage.py
git commit -m "feat(engine): bound the lineage walk (player one flip, picks to players)"
```

---

## Task 2: `terminal_assets` (the terminal players/picks per side)

**Files:** Modify `src/sleeper_dynasty/engine/lineage.py`; Test `tests/test_lineage.py` (append)

> Reuse the exact same bounded walk, but collect the terminal leaves' identities (player_id, or an undrafted pick's season/round) instead of building display nodes. Implement by traversing the `build_trade_lineage` tree and reading ids off the nodes — so extend `LineageNode` with the underlying ids (the API can ignore them) OR collect during a parallel walk. Simplest: add optional `player_id` / `pick` ids to the terminal-relevant nodes.

- [ ] **Step 1: Add ids to terminal nodes.** In `engine/lineage.py`, give `_terminal_player` access to the id and attach it. Easiest: extend `LineageNode` (models/lineage.py) with `terminal_player_id: str | None = None` and `terminal_pick: tuple | None = None`, set them in `_terminal_player`, and add to `to_dict` (the API and tree ignore them harmlessly). Then:

```python
def terminal_assets(resolved_trades, root_trade_id):
    """Per side: the terminal players (player_id) + undrafted picks from the bounded walk."""
    tree = build_trade_lineage(resolved_trades, root_trade_id, current_holders={})
    out: dict[str, list[dict]] = {}
    def collect(node, acc):
        if not node.children:
            if node.terminal_player_id:
                acc.append({"kind": "player", "player_id": node.terminal_player_id, "label": node.label})
            elif node.terminal_pick:
                acc.append({"kind": "pick", "season": node.terminal_pick[0], "round": node.terminal_pick[1], "label": node.label})
        for c in node.children:
            collect(c, acc)
    for uid, nodes in tree.items():
        acc: list[dict] = []
        for n in nodes:
            collect(n, acc)
        out[uid] = acc
    return out
```

- [ ] **Step 2: Test** (append to `tests/test_lineage.py`): for the multi-hop pick fixture from Task 1, `terminal_assets` returns Player C and Player D (the terminal players) for `u_a`. Run; fix until green.

- [ ] **Step 3: Commit** `feat(engine): terminal_assets from the bounded walk`.

---

## Task 3: `engine/regrade.py` — the became-grade

**Files:** Create `src/sleeper_dynasty/engine/regrade.py`; Test `tests/test_regrade.py`

> Value the terminal players at current KTC; score their points while this side owned them, reusing the matchup-walk pattern from `grade_hindsight_production` (iterate matchups, count weeks where `roster_to_user_by_league[lg][rid] == uid` and the player is on that roster; total / starters-only / starters-and-playoff).

- [ ] **Step 1: Write failing tests** covering: a terminal player valued at his KTC + points while owned; a player flipped immediately (0 points, still his KTC); an undrafted-pick terminal (pick_value only, 0 points); the per-side `BecameMetrics` shape `{ktc, production, started, playoff, terminal_labels}`. (Use small matchup + ktc fixtures mirroring `tests/test_trade_grader.py`.)

- [ ] **Step 2: Implement** `build_became_grade(trade, resolved_trades, *, matchups, roster_to_user_by_league, playoff_weeks_by_league, league_season_by_id, ktc_values, pick_values, fmt="superflex")`:
  - `terms = terminal_assets(resolved_trades, trade["trade"]["transaction_id"])`.
  - For each `uid`, for each terminal: if player → `ktc += ktc_values[pid].value`; sum points over weeks the uid owned the player (reuse a helper like `grade_hindsight_production`'s per-player loop with `starters_only`/`playoff_only` variants). If undrafted pick → `ktc += pick_values[(season, round)].value` (guard missing), 0 points. Collect `terminal_labels`.
  - Return `{uid: {"ktc", "production", "started", "playoff", "terminal_labels"}}`.

- [ ] **Step 3: Run** the tests → green. **Step 4: Commit** `feat(engine): build_became_grade (value + production of terminal players)`.

---

## Task 4: Cache `became_grades` + compute during refresh (incremental)

**Files:** Modify `api/app/services/chain_cache.py`, `api/app/services/grader.py`; Tests `api/tests/test_chain_cache_became.py`, `api/tests/test_grader_became.py`

> Mirror `trade_stories`: add a `became_grades: dict[str, dict] = field(default_factory=dict)` field (Task pattern identical to the existing `trade_stories`/`current_holders` fields — test round-trip + pre-migration default). In `GraderService.run`, after grading + `current_holders`, compute `build_became_grade` per trade with the in-scope `matchups`, `ktc_by_player_id`, `pick_value_table`, etc., and store `became_grades[tx]`. Incremental: skip recompute when the trade's terminal-set is unchanged (hash the `terminal_assets` output per trade and compare to the prior cache entry's stored hash, mirroring the story `facts_hash` skip). Best-effort: a failure logs and leaves that trade's became empty; never fails refresh.

- [ ] TDD each (cache field round-trip; `run` populates `became_grades` with an injected/fake grade). Commit per task.

---

## Task 5: Expose `became` on the trade response

**Files:** Modify `api/app/models/trade.py`, `api/app/services/trade_view.py`; Test `api/tests/test_became_view.py`

> Mirror the lineage wiring: add a `BecameMetrics` Pydantic model and `became: dict[str, BecameMetrics] = {}` on `TradeDetailResp`; in `build_trade_detail`, read `entry.became_grades.get(trade_id)` and map to the model. TDD that a fixture entry surfaces `became` per side. Commit.

---

## Task 6: Web types + `TradeBecame` component + render

**Files:** Modify `web/lib/types.ts`; Create `web/components/TradeBecame.tsx`; Test `web/tests/TradeBecame.test.tsx`; Modify `web/app/league/[id]/trade/[tid]/page.tsx`

> `BecameMetrics` TS type + `became?: Record<string, BecameMetrics>` on `TradeDetailResp`. `TradeBecame` renders a "What it became" block per side: the four metrics (Trade Value / Total Points / Points Started / Playoff Points) + the `terminal_labels` ("→ Player B, Player C"), visually distinct from the direct receipts, rendering nothing for an empty side. Mirror `TradeLineage.tsx`'s structure + tests. Wire it onto the trade page beside/below `TradeLineage`. TDD the render + the empty-side no-render. `npm run build` clean. Commit per file group.

---

## Final verification

- [ ] `pytest tests/test_lineage.py tests/test_regrade.py -q` (root) → PASS.
- [ ] `cd api && pytest -q` → PASS (incl. new became cache/view tests).
- [ ] from `web/`: `npx vitest run --config tests/vitest.config.ts` + `npm run build` → PASS.
- [ ] Post-deploy (outside this plan): a forced refresh repopulates; a flipped-asset trade shows the bounded tree AND the "What it became" four metrics.

## Self-review notes (author)
- The bounded rule lives in ONE walk (Task 1) that both the tree and `terminal_assets` (Task 2) use → tree and grade tell the same story.
- `became_grades`/`became`/`TradeBecame` deliberately mirror `trade_stories`/`story`/`TradeStory` and `lineage`/`TradeLineage` so the patterns are familiar.
- Cache shape changed → a refresh is required after deploy for `became` to populate (Liveness's scheduler will do it within the interval; or force-refresh).
