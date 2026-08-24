# Trade Story — Realized Haul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a trade's LLM story re-fire and tell the truth when its received assets' *realized fate* changes — most importantly when a received pick is drafted into a player who is then dropped.

**Architecture:** The story regenerates whenever the trade's `facts_hash` changes (`api/app/services/story_gen.py` diffs the rebuilt `TradeStoryFacts` against the cached one). Today the packet is blind to what received assets *became*, so the drop neither changes the hash nor gives the writer a fact. We feed each received asset's realized terminal fate (kept / dropped / flipped / undrafted, plus the production the haul scored) into the packet, reusing the exact bounded lineage walk the became-grade already uses (`engine/lineage.py::build_trade_lineage` / `terminal_assets`). No new walk; the new fields flow through `to_dict()` → `facts_hash`, so the drop auto-re-fires the story and the writer can tell it.

**Tech Stack:** Python 3.11, pytest. Pure engine + model + LLM-prompt changes plus a thin API thread-through. No web, no API-route, no cache-schema changes (new packet fields are additive; a changed `facts_hash` just triggers a one-time regen on next refresh).

**Spec:** `docs/superpowers/specs/2026-06-13-trade-story-realized-haul-design.md`

---

## File Structure

- **Modify** `src/sleeper_dynasty/models/trade_story.py` — add `dropped` + `last_rostered_week` to `PlayerArc`; add `terminal_state` + `dropped_before_week` to `PickOutcome`. (Tasks 1, 3)
- **Modify** `src/sleeper_dynasty/engine/lineage.py` — `terminal_assets` returns the draftee's player `name` (not the pick label). (Task 4)
- **Modify** `src/sleeper_dynasty/engine/trade_story.py` — `build_player_arc` computes `dropped` / `last_rostered_week` from `current_holders`; `build_trade_story_facts` accepts `current_holders`, stamps `terminal_state` / `dropped_before_week` / `points_per_game` onto pick outcomes, and emits a per-side `realized_players` list. (Tasks 2, 5)
- **Modify** `api/app/services/story_gen.py` + `api/app/services/grader.py` — thread `current_holders` from the grader into `generate_stories` → `build_trade_story_facts`. (Task 6)
- **Modify** `src/sleeper_dynasty/llm/prompts/trade_story_persona.md` — vocabulary for busts / cuts / realized hauls. (Task 7)
- **Tests:** `tests/test_trade_story_engine.py`, `tests/test_trade_story_writer.py`, `api/tests/test_story_gen.py` (new file if absent).

### Field semantics (read once before starting)

- `PlayerArc.dropped` — `True` when the owner no longer holds this player **and** did not flip him: i.e. he was cut. Mirrors the became-grade's `terminal_state == "dropped"` (which is "not on the current roster"). `flipped` always wins over `dropped` (a flipped player is not a cut player).
- `PlayerArc.last_rostered_week` — the highest NFL week this player appeared on **this owner's** roster post-trade, or `None` if he never did (e.g. drafted then cut before Week 1).
- `PickOutcome.terminal_state` — `"kept"` (drafted, still held / played) | `"dropped"` (drafted then cut) | `"flipped"` (pick traded before the draft; pairs with existing `flipped_for`) | `"undrafted"` (future pick) | `None` (no lineage context available).
- `PickOutcome.dropped_before_week` — when `terminal_state == "dropped"`: the draftee's `last_rostered_week`, or `0` if he never played a snap for this owner. `None` otherwise. `0` is the sharp "drafted and cut before the season" beat.

---

## Task 1: Add `dropped` + `last_rostered_week` to `PlayerArc`

**Files:**
- Modify: `src/sleeper_dynasty/models/trade_story.py:17-52`
- Test: `tests/test_trade_story_models.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_trade_story_models.py`:

```python
from sleeper_dynasty.models.trade_story import PlayerArc


def test_player_arc_to_dict_carries_dropped_and_last_rostered_week():
    arc = PlayerArc(
        player="Bust Guy", position="WR", received_by="u_a",
        starter_weeks=0, points_total=0.0, season_high_points=None,
        season_high_week=None, season_high_is_playoff=False,
        playoff_vs_regular_pct=None, decisive_starts=0, benched_weeks=0,
        phantom_points=0.0, flipped=False, dropped=True,
        last_rostered_week=None,
    )
    d = arc.to_dict()
    assert d["dropped"] is True
    assert d["last_rostered_week"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_trade_story_models.py::test_player_arc_to_dict_carries_dropped_and_last_rostered_week -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'dropped'`

- [ ] **Step 3: Add the fields**

In `src/sleeper_dynasty/models/trade_story.py`, in the `PlayerArc` dataclass, after the `flipped: bool = False` field (line 37) add:

```python
    # True when the owner no longer holds this player and did not flip him
    # (he was cut). flipped always wins over dropped.
    dropped: bool = False
    # Highest NFL week this player appeared on THIS owner's roster post-trade,
    # or None if he never did (e.g. drafted then cut before Week 1).
    last_rostered_week: int | None = None
```

In the same class's `to_dict` (ends line 52), add to the returned dict before the closing brace:

```python
            "dropped": self.dropped,
            "last_rostered_week": self.last_rostered_week,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_trade_story_models.py::test_player_arc_to_dict_carries_dropped_and_last_rostered_week -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/models/trade_story.py tests/test_trade_story_models.py
git commit -m "feat(trade-story): add dropped + last_rostered_week to PlayerArc"
```

---

## Task 2: `build_player_arc` computes `dropped` + `last_rostered_week`

**Files:**
- Modify: `src/sleeper_dynasty/engine/trade_story.py:104-167`
- Test: `tests/test_trade_story_engine.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_trade_story_engine.py`:

```python
def test_player_arc_flags_drafted_then_dropped_before_season():
    # Mike RECEIVES p1 (think: a draftee) but never rosters him in any matchup,
    # and he is NOT in current_holders -> cut before he ever played.
    rt = _rt("t1", 9, True)
    arc = build_player_arc(
        pid="p1", player_name="Cut Guy", position="WR",
        owner_uid="u_mike", rt=rt, matchups={},
        roster_to_user_by_league={"L": {1: "u_mike"}},
        playoff_weeks_by_league={"L": 15},
        league_season_by_id={"L": 2024},
        current_holders={},  # nobody holds him -> dropped
    )
    assert arc.dropped is True
    assert arc.flipped is False
    assert arc.last_rostered_week is None
    assert arc.starter_weeks == 0 and arc.benched_weeks == 0


def test_player_arc_kept_player_not_dropped_and_tracks_last_week():
    rt = _rt("t1", 9, True)
    matchups = {
        ("L", 5, 1): {"players": ["p1"], "starters": ["p1"],
                      "players_points": {"p1": 10.0},
                      "team_points": 100.0, "opponent_points": 96.0},
        ("L", 8, 1): {"players": ["p1"], "starters": [],  # benched wk 8
                      "players_points": {"p1": 4.0},
                      "team_points": 100.0, "opponent_points": 96.0},
    }
    arc = build_player_arc(
        pid="p1", player_name="Kept Guy", position="RB",
        owner_uid="u_mike", rt=rt, matchups=matchups,
        roster_to_user_by_league={"L": {1: "u_mike"}},
        playoff_weeks_by_league={"L": 15},
        league_season_by_id={"L": 2024},
        current_holders={"p1": "u_mike"},  # still held -> not dropped
    )
    assert arc.dropped is False
    assert arc.last_rostered_week == 8  # appeared (started wk5, benched wk8)


def test_player_arc_flipped_beats_dropped():
    # Received, never rostered here, but scored elsewhere -> flipped, not cut.
    rt = _rt("t1", 9, True)
    matchups = {
        ("L", 5, 2): {"players": ["p1"], "starters": ["p1"],
                      "players_points": {"p1": 18.0},
                      "team_points": 100.0, "opponent_points": 90.0},
    }
    arc = build_player_arc(
        pid="p1", player_name="Flipped Guy", position="RB",
        owner_uid="u_mike", rt=rt, matchups=matchups,
        roster_to_user_by_league={"L": {1: "u_mike", 2: "u_other"}},
        playoff_weeks_by_league={"L": 15},
        league_season_by_id={"L": 2024},
        current_holders={},  # not held, but he was flipped
    )
    assert arc.flipped is True
    assert arc.dropped is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_trade_story_engine.py -k "drafted_then_dropped or kept_player_not_dropped or flipped_beats_dropped" -v`
Expected: FAIL — `TypeError: build_player_arc() got an unexpected keyword argument 'current_holders'`

- [ ] **Step 3: Implement**

In `src/sleeper_dynasty/engine/trade_story.py`, change the `build_player_arc` signature (line 104-114) to add the new parameter — add `current_holders: dict[str, str] | None = None,` as the last parameter before the closing `)`:

```python
def build_player_arc(
    pid: str,
    player_name: str,
    position: str | None,
    owner_uid: str,
    rt: ResolvedTrade,
    matchups: dict[tuple[str, int, int], dict],
    roster_to_user_by_league: dict[str, dict[int, str]],
    playoff_weeks_by_league: dict[str, int],
    league_season_by_id: dict[str, int] | None = None,
    current_holders: dict[str, str] | None = None,
) -> PlayerArc:
```

Just below `league_season_by_id = league_season_by_id or {}` (line 115), initialize the tracker:

```python
    last_rostered_week: int | None = None
```

Inside the matchup loop, the line `if roster_to_user_by_league.get(lg, {}).get(rid) != owner_uid:` then `continue` (lines 134-135) filters to this owner's weeks. Immediately AFTER that `continue` (so it runs only for the owner's own roster-weeks, started or benched), record the week — insert before the `if not is_starter:` check (line 137):

```python
        last_rostered_week = (
            wk if last_rostered_week is None else max(last_rostered_week, wk)
        )
```

Just before the `return PlayerArc(...)` (line 160), compute `dropped`:

```python
    held = (current_holders or {}).get(pid) == owner_uid
    dropped = (not flipped) and (not held)
```

Add the two new fields to the `PlayerArc(...)` constructor call (after `flipped=flipped,`):

```python
        dropped=dropped, last_rostered_week=last_rostered_week,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_trade_story_engine.py -k "drafted_then_dropped or kept_player_not_dropped or flipped_beats_dropped" -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Run the full story-engine suite (no regressions)**

Run: `pytest tests/test_trade_story_engine.py -v`
Expected: PASS (all prior tests still green — `current_holders` defaults to `None`)

- [ ] **Step 6: Commit**

```bash
git add src/sleeper_dynasty/engine/trade_story.py tests/test_trade_story_engine.py
git commit -m "feat(trade-story): build_player_arc computes dropped + last_rostered_week"
```

---

## Task 3: Add `terminal_state` + `dropped_before_week` to `PickOutcome`

**Files:**
- Modify: `src/sleeper_dynasty/models/trade_story.py:55-78`
- Test: `tests/test_trade_story_models.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_trade_story_models.py`:

```python
from sleeper_dynasty.models.trade_story import PickOutcome


def test_pick_outcome_to_dict_carries_terminal_state_and_drop_week():
    po = PickOutcome(
        season=2026, round=1, became_player="Cut Guy",
        points_per_game=None, flipped_for=None,
        terminal_state="dropped", dropped_before_week=0,
    )
    d = po.to_dict()
    assert d["terminal_state"] == "dropped"
    assert d["dropped_before_week"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_trade_story_models.py::test_pick_outcome_to_dict_carries_terminal_state_and_drop_week -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'terminal_state'`

- [ ] **Step 3: Add the fields**

In `src/sleeper_dynasty/models/trade_story.py`, in the `PickOutcome` dataclass, after `flipped_for: str | None = None` (line 69) add:

```python
    # Realized fate of the pick: "kept" | "dropped" | "flipped" | "undrafted"
    # | None (no lineage context). "dropped" = drafted then cut.
    terminal_state: str | None = None
    # When dropped: the draftee's last rostered week for this owner, or 0 if he
    # never played a snap (drafted and cut before the season). None otherwise.
    dropped_before_week: int | None = None
```

In `to_dict` (ends line 78), add before the closing brace:

```python
            "terminal_state": self.terminal_state,
            "dropped_before_week": self.dropped_before_week,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_trade_story_models.py::test_pick_outcome_to_dict_carries_terminal_state_and_drop_week -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/models/trade_story.py tests/test_trade_story_models.py
git commit -m "feat(trade-story): add terminal_state + dropped_before_week to PickOutcome"
```

---

## Task 4: `terminal_assets` returns the terminal player's name

`terminal_assets` returns each terminal leaf's `label`, but for a pick-derived
player that label is the *pick* string (e.g. `"2026 1st pick"`), not the
player's name — the name lives in `node.became_player`. The realized-player arcs
(Task 5) need the real name. Add an additive `"name"` field. Safe: the
became-grade (`engine/regrade.py:130-172`) only reads `label` / `player_id` /
`season` / `round`.

**Files:**
- Modify: `src/sleeper_dynasty/engine/lineage.py:160-170`
- Test: `tests/test_lineage.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_lineage.py`:

```python
def test_terminal_assets_includes_player_name_for_pick_draftee():
    from sleeper_dynasty.engine.lineage import terminal_assets
    dicts = [{
        "trade": {"transaction_id": "t1", "traded_at": "2025-11-07T00:00:00"},
        "sides": {
            "u_a": {"user_id": "u_a", "received": [{
                "season": 2026, "round": 1, "original_owner_user_id": "u_x",
                "drafted_player_id": "ML", "drafted_player_name": "Makai Lemon"}],
                "given": []},
            "u_b": {"user_id": "u_b", "received": [], "given": [{
                "season": 2026, "round": 1, "original_owner_user_id": "u_x",
                "drafted_player_id": "ML", "drafted_player_name": "Makai Lemon"}]},
        },
    }]
    terms = terminal_assets(dicts, "t1")
    player = next(t for t in terms["u_a"] if t["kind"] == "player")
    assert player["player_id"] == "ML"
    assert player["name"] == "Makai Lemon"   # the draftee, not "2026 1st pick"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_lineage.py::test_terminal_assets_includes_player_name_for_pick_draftee -v`
Expected: FAIL — `KeyError: 'name'`

- [ ] **Step 3: Implement**

In `src/sleeper_dynasty/engine/lineage.py`, in the `collect` closure inside
`terminal_assets` (lines 160-170), add `"name"` to the player branch
(`node.became_player` holds the draftee's name for a pick-derived player; for a
directly-held player it is `None`, so fall back to `node.label`, which is the
player's name in that case):

```python
    def collect(node: LineageNode, acc: list[dict]) -> None:
        if not node.children:
            if node.terminal_player_id:
                acc.append({"kind": "player", "player_id": node.terminal_player_id,
                            "label": node.label,
                            "name": node.became_player or node.label})
            elif node.terminal_pick:
                acc.append({"kind": "pick", "season": node.terminal_pick[0],
                            "round": node.terminal_pick[1], "label": node.label})
        for c in node.children:
            collect(c, acc)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_lineage.py::test_terminal_assets_includes_player_name_for_pick_draftee -v`
Expected: PASS

- [ ] **Step 5: Run the lineage + regrade suites (no regressions)**

Run: `pytest tests/test_lineage.py tests/test_lineage_realized.py tests/test_regrade.py -v`
Expected: PASS (the became-grade ignores the new key)

- [ ] **Step 6: Commit**

```bash
git add src/sleeper_dynasty/engine/lineage.py tests/test_lineage.py
git commit -m "feat(lineage): terminal_assets returns the draftee's player name"
```

---

## Task 5: `build_trade_story_facts` emits realized fate + `realized_players`

**Files:**
- Modify: `src/sleeper_dynasty/engine/trade_story.py:207-292`
- Test: `tests/test_trade_story_engine.py`

This is the core task. `build_trade_story_facts` gains a `current_holders` argument, builds the lineage tree *with* it (so terminal leaves know dropped vs kept), builds production arcs for the terminal players reached through picks/flips, stamps `terminal_state` / `dropped_before_week` / `points_per_game` onto each `PickOutcome`, and adds a per-side `realized_players` list.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_trade_story_engine.py`. These build on the existing `_pick_facts_inputs` / `_build_facts` helpers (lines 161-195), extending `_build_facts` to forward `current_holders`:

```python
from sleeper_dynasty.models.trade_story import facts_hash


def _build_facts_ch(rt, dicts, current_holders, matchups=None):
    return build_trade_story_facts(
        rt=rt, grade={}, owner_strategy={},
        owners_display={"u_a": "A", "u_b": "B"},
        matchups=matchups or {}, roster_to_user_by_league={"L": {1: "u_a"}},
        playoff_weeks_by_league={"L": 15},
        league_season_by_id={"L": 2025}, positions={},
        resolved_trades=dicts, current_holders=current_holders)


def test_kept_pick_draftee_is_terminal_state_kept():
    # u_a held the pick, drafted Makai Lemon, and still rosters him.
    rt, dicts = _pick_facts_inputs(flip=False)
    facts = _build_facts_ch(rt, dicts, current_holders={"ML": "u_a"})
    a = next(s for s in facts.sides if s["user_id"] == "u_a")
    po = a["pick_outcomes"][0]
    assert po["became_player"] == "Makai Lemon"
    assert po["terminal_state"] == "kept"
    assert po["dropped_before_week"] is None


def test_drafted_then_dropped_pick_sets_dropped_state_and_changes_hash():
    # Same trade, but u_a no longer holds Makai Lemon (cut, never played).
    rt, dicts = _pick_facts_inputs(flip=False)
    kept = _build_facts_ch(rt, dicts, current_holders={"ML": "u_a"})
    dropped = _build_facts_ch(rt, dicts, current_holders={})  # ML not held

    a = next(s for s in dropped.sides if s["user_id"] == "u_a")
    po = a["pick_outcomes"][0]
    assert po["terminal_state"] == "dropped"
    assert po["dropped_before_week"] == 0  # never played a snap

    # The drop must change the packet so the story re-fires.
    assert facts_hash(kept) != facts_hash(dropped)


def test_realized_players_lists_terminal_player_from_a_pick():
    # realized_players is built from terminal_assets (the bounded walk), so the
    # draftee shows up by NAME regardless of matchup production.
    rt, dicts = _pick_facts_inputs(flip=False)
    facts = _build_facts_ch(rt, dicts, current_holders={"ML": "u_a"})
    a = next(s for s in facts.sides if s["user_id"] == "u_a")
    names = [p["player"] for p in a["realized_players"]]
    assert "Makai Lemon" in names
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_trade_story_engine.py -k "kept_pick_draftee or drafted_then_dropped_pick or realized_players_lists" -v`
Expected: FAIL — `TypeError: build_trade_story_facts() got an unexpected keyword argument 'current_holders'`

- [ ] **Step 3: Implement**

In `src/sleeper_dynasty/engine/trade_story.py`:

**(a)** Add the parameter to the signature (line 207-218). Insert `current_holders: dict[str, str] | None = None,` as the last parameter before the closing `)`:

```python
def build_trade_story_facts(
    rt: ResolvedTrade,
    grade: dict,
    owner_strategy: dict[str, OwnerStrategyFacts],
    owners_display: dict[str, str],
    matchups: dict[tuple[str, int, int], dict],
    roster_to_user_by_league: dict[str, dict[int, str]],
    playoff_weeks_by_league: dict[str, int],
    league_season_by_id: dict[str, int] | None = None,
    positions: dict[str, str] | None = None,
    resolved_trades: list[dict] | None = None,
    current_holders: dict[str, str] | None = None,
) -> TradeStoryFacts:
```

**(b)** Just after `positions = positions or {}` (line 219) add:

```python
    current_holders = current_holders or {}
```

**(c)** Build the lineage tree WITH `current_holders` (so terminal leaves know dropped vs kept) and prepare terminal-player arcs. Replace the existing block (lines 247-253):

```python
    # Lineage tells us which received picks the owner flipped *as a pick* before
    # the draft — those rows must not claim they became the slot's draftee, but
    # report what the flip ultimately landed instead.
    flipped_tree: dict[str, list] = {}
    if resolved_trades:
        from sleeper_dynasty.engine.lineage import build_trade_lineage
        flipped_tree = build_trade_lineage(
            resolved_trades, rt.trade.transaction_id, current_holders={})
```

with:

```python
    # Lineage tells us (a) which received picks the owner flipped *as a pick*
    # before the draft, and (b) each terminal leaf's realized state (kept /
    # dropped / undrafted). Built WITH current_holders so dropped vs kept is
    # accurate. terminal_assets reuses the same bounded walk for the realized
    # production arcs, so story and became-grade tell one story.
    flipped_tree: dict[str, list] = {}
    terminals_by_uid: dict[str, list[dict]] = {}
    if resolved_trades:
        from sleeper_dynasty.engine.lineage import (
            build_trade_lineage, terminal_assets,
        )
        tx_id = rt.trade.transaction_id
        flipped_tree = build_trade_lineage(
            resolved_trades, tx_id, current_holders=current_holders)
        terminals_by_uid = terminal_assets(resolved_trades, tx_id)
```

**(d)** Inside the `for uid, side in rt.sides.items():` loop, build an arc for every terminal player and index it by player_id. After the existing `arcs = [...]` list comprehension (ends line 266), add:

```python
        # Production arcs for the terminal players this side's assets became.
        terminal_arcs: dict[str, PlayerArc] = {}
        for t in terminals_by_uid.get(uid, []):
            if t.get("kind") != "player":
                continue
            tpid = t["player_id"]
            terminal_arcs[tpid] = build_player_arc(
                pid=tpid, player_name=t.get("name") or t.get("label") or tpid,
                position=positions.get(tpid), owner_uid=uid, rt=rt,
                matchups=matchups,
                roster_to_user_by_league=roster_to_user_by_league,
                playoff_weeks_by_league=playoff_weeks_by_league,
                league_season_by_id=league_season_by_id,
                current_holders=current_holders,
            )
        direct_pids = {
            a.player_id for a in side.received if isinstance(a, PlayerAsset)
        }
        realized_players = [
            arc.to_dict() for pid, arc in terminal_arcs.items()
            if pid not in direct_pids
        ]
```

**(e)** Enrich each `PickOutcome` with terminal_state / drop / points. The existing `_outcome(a)` closure (lines 273-278) maps a received asset to a `PickOutcome`. Replace it and the `outs = [...]` line (lines 273-280) with:

```python
        def _outcome(a):
            n = node_of.get(id(a))
            flipped = bool(getattr(n, "flipped_as_pick", False))
            realized = ", ".join(_terminal_player_names(n)) if flipped else ""
            po = _pick_outcome(a, flipped_as_pick=flipped,
                               flipped_for=realized or None)
            if po is None or n is None:
                return po
            if flipped:
                po.terminal_state = "flipped"
                return po
            # A kept/dropped/undrafted pick: read the realized state off the
            # terminal leaf, and pull production from the draftee's arc.
            leaf_state = getattr(n, "terminal_state", None)
            tpid = getattr(n, "terminal_player_id", None)
            if leaf_state == "on_roster":
                po.terminal_state = "kept"
            elif leaf_state == "dropped":
                po.terminal_state = "dropped"
            elif leaf_state == "undrafted":
                po.terminal_state = "undrafted"
            arc = terminal_arcs.get(tpid) if tpid else None
            if arc is not None:
                if arc.starter_weeks > 0:
                    po.points_per_game = arc.points_total / arc.starter_weeks
                if po.terminal_state == "dropped":
                    po.dropped_before_week = arc.last_rostered_week or 0
            return po

        outs = [o.to_dict() for o in map(_outcome, side.received) if o is not None]
```

**(f)** Add `realized_players` to the appended side dict (lines 281-284):

```python
        sides.append({
            "user_id": uid, "owner_name": owners_display.get(uid, uid),
            "player_arcs": arcs, "pick_outcomes": outs,
            "realized_players": realized_players,
        })
```

Note: `_pick_outcome` returns a `PickOutcome` dataclass instance (mutable), so setting `po.terminal_state = ...` before `.to_dict()` is valid. For directly-received PLAYER assets, `_pick_outcome` already returns the via_pick branch or `None`; those have `terminal_state=None`, which is correct (their fate lives in `player_arcs`, now carrying `dropped`).

- [ ] **Step 4: Run the new tests**

Run: `pytest tests/test_trade_story_engine.py -k "kept_pick_draftee or drafted_then_dropped_pick or realized_players_lists" -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Run the full story-engine suite (no regressions)**

Run: `pytest tests/test_trade_story_engine.py -v`
Expected: PASS — including the existing `test_pick_outcome_*` cases (they pass `dicts` but no `current_holders`, which defaults to `{}`; they only assert `became_player` / `flipped_for`, both unchanged).

- [ ] **Step 6: Commit**

```bash
git add src/sleeper_dynasty/engine/trade_story.py tests/test_trade_story_engine.py
git commit -m "feat(trade-story): emit realized fate (terminal_state, drop week, realized_players)"
```

---

## Task 6: Thread `current_holders` from the grader into story generation

**Files:**
- Modify: `api/app/services/story_gen.py:28-66`
- Modify: `api/app/services/grader.py:221-225`
- Test: `api/tests/test_story_gen.py` (create if absent)

- [ ] **Step 1: Write the failing test**

Create or append to `api/tests/test_story_gen.py`:

```python
import asyncio
from datetime import datetime

from sleeper_dynasty.models.trade import (
    PickAsset, Trade, TradeSide, ResolvedTrade,
)
from app.services.story_gen import generate_stories


class _FakeWriter:
    def __init__(self):
        self.seen = []

    def write(self, facts):
        self.seen.append(facts)
        return {"verdict": "v", "body": "b"}


def _resolved_and_dicts():
    recv = PickAsset(season=2026, round=1, original_owner_user_id="u_x",
                     drafted_player_id="ML", drafted_player_name="Makai Lemon")
    a = TradeSide(user_id="u_a", received=[recv], given=[])
    b = TradeSide(user_id="u_b", received=[], given=[recv])
    t = Trade(transaction_id="t1", league_id="L", season=2025, week=10,
              traded_at=datetime(2025, 11, 7),
              sides={"u_a": a, "u_b": b})
    rt = ResolvedTrade(trade=t, sides={"u_a": a, "u_b": b})
    dicts = [{"trade": {"transaction_id": "t1",
                        "traded_at": "2025-11-07T00:00:00"},
              "sides": {"u_a": {"user_id": "u_a",
                                "received": [{"season": 2026, "round": 1,
                                              "original_owner_user_id": "u_x",
                                              "drafted_player_id": "ML",
                                              "drafted_player_name": "Makai Lemon"}],
                                "given": []},
                        "u_b": {"user_id": "u_b", "received": [],
                                "given": [{"season": 2026, "round": 1,
                                           "original_owner_user_id": "u_x",
                                           "drafted_player_id": "ML",
                                           "drafted_player_name": "Makai Lemon"}]}}}]
    return rt, dicts


def test_generate_stories_passes_current_holders_into_facts():
    rt, dicts = _resolved_and_dicts()
    writer = _FakeWriter()
    supporting = {
        "owners_display": {"u_a": "A", "u_b": "B"},
        "matchups": {}, "roster_to_user_by_league": {},
        "playoff_weeks_by_league": {}, "league_season_by_id": {"L": 2025},
        "positions": {},
    }
    stories, _ = asyncio.run(generate_stories(
        resolved=[rt], grades={}, supporting=supporting,
        prior_stories={}, writer=writer, resolved_dicts=dicts,
        current_holders={},  # ML not held -> dropped fate reaches the writer
    ))
    assert "t1" in stories
    a = next(s for s in writer.seen[0].sides if s["user_id"] == "u_a")
    assert a["pick_outcomes"][0]["terminal_state"] == "dropped"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest api/tests/test_story_gen.py::test_generate_stories_passes_current_holders_into_facts -v`
Expected: FAIL — `TypeError: generate_stories() got an unexpected keyword argument 'current_holders'`

- [ ] **Step 3: Implement**

In `api/app/services/story_gen.py`, add the parameter to `generate_stories` (signature ends line 39-40). Add `current_holders: dict[str, str] | None = None,` to the keyword-only args (e.g. after `resolved_dicts`):

```python
    resolved_dicts: list[dict] | None = None,
    current_holders: dict[str, str] | None = None,
    max_concurrency: int = 3,
```

In the `build_trade_story_facts(...)` call inside the loop (lines 51-60), add the argument:

```python
            resolved_trades=resolved_dicts,
            current_holders=current_holders or {},
        )
```

In `api/app/services/grader.py`, the `generate_stories(...)` call (lines 221-225) — add the argument. `current_holders` is already in scope (built at lines 118-126):

```python
            trade_stories, owner_dossiers = await generate_stories(
                resolved=resolved, grades=grades, supporting=supporting,
                prior_stories=prior, writer=writer, progress_cb=progress_cb,
                resolved_dicts=resolved_dicts, current_holders=current_holders,
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest api/tests/test_story_gen.py::test_generate_stories_passes_current_holders_into_facts -v`
Expected: PASS

- [ ] **Step 5: Run the api story/grader tests (no regressions)**

Run: `pytest api/tests/ -k "story or grader" -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add api/app/services/story_gen.py api/app/services/grader.py api/tests/test_story_gen.py
git commit -m "feat(api): thread current_holders into trade-story facts"
```

---

## Task 7: Teach the writer persona the realized-fate vocabulary

**Files:**
- Modify: `src/sleeper_dynasty/llm/prompts/trade_story_persona.md`
- Test: `tests/test_trade_story_writer.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_trade_story_writer.py`:

```python
def test_build_request_serializes_realized_fate_facts():
    facts = TradeStoryFacts(
        trade_id="t1", season=2025, is_offseason=False, winner_user_id="u_a",
        lopsidedness=0.4, margins={"ktc": 500.0},
        sides=[{
            "user_id": "u_a", "owner_name": "A", "player_arcs": [],
            "pick_outcomes": [{
                "season": 2026, "round": 1, "became_player": "Cut Guy",
                "flipped_for": None, "points_per_game": None,
                "terminal_state": "dropped", "dropped_before_week": 0,
            }],
            "realized_players": [],
        }],
        owners={"u_a": {"owner_name": "A", "tilt": "win-now"}},
    )
    w = TradeStoryWriter(api_key="test")
    _, messages = w.build_request(facts)
    blob = str(messages)
    assert "dropped" in blob and "dropped_before_week" in blob


def test_persona_explains_realized_fate():
    p = load_persona()
    assert "terminal_state" in p
    assert "realized_players" in p
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_trade_story_writer.py -k "realized_fate or realized" -v`
Expected: `test_build_request_serializes_realized_fate_facts` PASSES already (serialization is automatic); `test_persona_explains_realized_fate` FAILS — `terminal_state` not in persona.

- [ ] **Step 3: Update the persona**

In `src/sleeper_dynasty/llm/prompts/trade_story_persona.md`, after the existing `## Pick outcomes: a flipped pick is not a draftee` section (the last block in the file), append:

```markdown

## Realized fate: tell the CURRENT truth about what the haul became
Each `pick_outcomes` entry now carries `terminal_state`, and each side carries a
`realized_players` list (the players its assets ultimately became, with the same
production fields as `player_arcs`). Always tell how the deal looks NOW:
- `terminal_state: "kept"` means they drafted the player and kept him. If
  `points_per_game` is set, cite what he produced.
- `terminal_state: "dropped"` means they drafted the player and then CUT him.
  When `dropped_before_week` is 0, they cut him before he played a single snap:
  the pick turned into nothing. This is a story, tell it ("drafted X and cut him
  before Week 1", "turned a first-round pick into air"). If the value looked
  fine on trade day but the haul evaporated, the verdict should reflect the
  evaporation, not the trade-day grade.
- `terminal_state: "flipped"` pairs with `flipped_for` (already covered above):
  they traded the pick before the draft.
- `terminal_state: "undrafted"` or `null`: a future or unresolved pick, or no
  outcome data; do not invent one.
- Use `realized_players` to say what a pick or flip BECAME in production terms
  (e.g., "the pick became <player>, who averaged <points_per_game>"). A
  `realized_players` entry with `dropped: true` is a player this side ended up
  cutting; you may call him a bust for them.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_trade_story_writer.py -k "realized_fate or realized" -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Run the full writer suite (no regressions)**

Run: `pytest tests/test_trade_story_writer.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/sleeper_dynasty/llm/prompts/trade_story_persona.md tests/test_trade_story_writer.py
git commit -m "feat(trade-story): persona tells the realized-fate story (cuts, busts, hauls)"
```

---

## Task 8: Full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the engine + model + writer suites**

Run: `pytest tests/test_trade_story_engine.py tests/test_trade_story_models.py tests/test_trade_story_writer.py tests/test_lineage.py tests/test_regrade.py -v`
Expected: PASS (all green)

- [ ] **Step 2: Run the api suite**

Run: `pytest api/tests/ -v`
Expected: PASS (all green)

- [ ] **Step 3: Run the whole backend suite from the repo root**

Run: `pytest -q`
Expected: PASS (no regressions across the engine/CLI suite)

- [ ] **Step 4: Final commit (if any uncommitted verification fixes)**

```bash
git status
# only if there are stragglers:
git add -A && git commit -m "test(trade-story): verify realized-haul suite green"
```

---

## Self-Review notes

- **Spec coverage:** model fields (Tasks 1, 3) ✓; `terminal_assets` returns the draftee name so realized arcs are correctly labelled (Task 4) ✓; facts-builder realized fate + `realized_players` reusing `terminal_assets` (Task 5) ✓; re-fire proven via `facts_hash` differing on drop (Task 5 Step 1) ✓; `current_holders` thread-through so dropped vs kept is real (Task 6) ✓; persona vocabulary (Task 7) ✓; stateless current-truth (no version history) — honored, nothing persists past versions ✓; additive, day-of `player_arcs`/`pick_outcomes` retained ✓.
- **`dropped_before_week` definition:** refined during planning from the spec's open phrasing to a concrete rule (last rostered week, or 0 if never played). Same intent — "cut before the season" is the `0` case — just made unambiguous, as the spec self-review anticipated.
- **No new cost class:** terminal-player arcs now contribute to `facts_hash`, extending the existing weekly-during-season regen behavior that rostered-player arcs already cause. Accepted in the spec.
