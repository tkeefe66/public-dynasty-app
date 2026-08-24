> _Historical doc — paths/names have changed. Repo is now `Code Apps/public-dynasty` (GitHub `tkeefe66/public-dynasty-app`), Railway project **shimmering-nature**, live at https://ffbdynasty.com. Ignore stale refs to `sleeper-dynasty` / `sleeper-trade-grader` / `web-production-f949`._

# Trade Story — given_summary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a pre-computed `given_summary` string to each side of the trade-story facts packet so the LLM writer always knows what each side gave up, preventing directional hallucination ("ChocGummyBear walked off with Mike Evans" when Evans went the other way).

**Architecture:** In `build_trade_story_facts`, for each side, compute a human-readable string from `side.given` (the assets that side traded away) and add it to the side dict. The per-side loop already has access to `side.given`, `positions`, and the asset types. The persona gets a new instruction to anchor the opening sentence on `given_summary`. No new data structures — `given_summary` is a plain string key in the existing side dict (which is already an untyped `dict[str, Any]`).

**Tech Stack:** Python 3.11, pytest. Engine-only + persona change — no API, web, or cache-schema changes.

---

## File Structure

- **Modify** `src/sleeper_dynasty/engine/trade_story.py` — compute `given_summary` per side in `build_trade_story_facts` (Task 1)
- **Modify** `src/sleeper_dynasty/llm/prompts/trade_story_persona.md` — instruct the writer to use `given_summary` (Task 2)
- **Tests** `tests/test_trade_story_engine.py`, `tests/test_trade_story_writer.py`

### given_summary format (read before starting)

- Players: `"{name} ({position})"` if position available, else `"{name}"`
- Picks: `"{season} {ordinal} pick"` where ordinal = 1st/2nd/3rd/4th/5th (append "th" for anything > 3)
- `via_pick` PlayerAssets (a pick that resolved to its draftee) are also picks from the giver's perspective: format as `"{season} {ordinal} pick"`
- FaabAsset: skip entirely (not mentioned)
- Multiple assets: join with `" · "` (middle dot, matches app UI conventions)
- Empty given (edge case): `""` (never happens in real trades but handle defensively)

Examples:
- `"Mike Evans (WR)"`
- `"2026 3rd pick · 2027 2nd pick"`
- `"Josh Allen (QB) · 2026 1st pick"`

---

## Task 1: Add `given_summary` to the per-side facts dict

**Files:**
- Modify: `src/sleeper_dynasty/engine/trade_story.py` (inside `build_trade_story_facts`, the `sides.append({...})` call ~line 358)
- Test: `tests/test_trade_story_engine.py`

The per-side loop in `build_trade_story_facts` already has `uid`, `side` (a `TradeSide` with `.given: list[PlayerAsset | PickAsset | FaabAsset]`), and `positions: dict[str, str]` (player_id → position string). The `sides.append({...})` call is where the new key is added.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_trade_story_engine.py` (all imports already present — `_rt`, `build_trade_story_facts`, and `OwnerStrategyFacts` are used earlier in the file):

```python
def test_given_summary_player_with_position():
    # tkeefe6689 GIVES a player; Mike side gives a pick.
    # _rt("t1", 9, True) -> Mike gets player p1 (Bijan Robinson), Tom gets a 2025 1st pick
    # So Tom's given is [player p1], Mike's given is [pick].
    rt = _rt("t1", 9, True)
    facts = build_trade_story_facts(
        rt=rt, grade={}, owner_strategy={},
        owners_display={"u_mike": "Mike", "u_tom": "Tom"},
        matchups={}, roster_to_user_by_league={}, playoff_weeks_by_league={},
        league_season_by_id={"L": 2024}, positions={"p1": "RB"})
    tom = next(s for s in facts.sides if s["user_id"] == "u_tom")
    mike = next(s for s in facts.sides if s["user_id"] == "u_mike")
    # Tom gave the player (Bijan Robinson, RB)
    assert tom["given_summary"] == "Bijan Robinson (RB)"
    # Mike gave a pick (2025 1st)
    assert mike["given_summary"] == "2025 1st pick"


def test_given_summary_player_no_position():
    rt = _rt("t1", 9, True)
    facts = build_trade_story_facts(
        rt=rt, grade={}, owner_strategy={},
        owners_display={"u_mike": "Mike", "u_tom": "Tom"},
        matchups={}, roster_to_user_by_league={}, playoff_weeks_by_league={},
        league_season_by_id={"L": 2024}, positions={})  # no position data
    tom = next(s for s in facts.sides if s["user_id"] == "u_tom")
    assert tom["given_summary"] == "Bijan Robinson"


def test_given_summary_ordinals():
    # Build a trade where one side gives picks of various rounds.
    from datetime import datetime
    from sleeper_dynasty.models.trade import PickAsset, Trade, TradeSide, ResolvedTrade
    p2 = PickAsset(season=2026, round=2, original_owner_user_id="u_a")
    p4 = PickAsset(season=2027, round=4, original_owner_user_id="u_a")
    p5 = PickAsset(season=2027, round=5, original_owner_user_id="u_a")
    a_side = TradeSide(user_id="u_a", received=[], given=[p2, p4, p5])
    b_side = TradeSide(user_id="u_b", received=[p2, p4, p5], given=[])
    t = Trade(transaction_id="t1", league_id="L", season=2025, week=1,
              traded_at=datetime(2025, 6, 1),
              sides={"u_a": a_side, "u_b": b_side})
    rt = ResolvedTrade(trade=t, sides={"u_a": a_side, "u_b": b_side})
    facts = build_trade_story_facts(
        rt=rt, grade={}, owner_strategy={},
        owners_display={"u_a": "A", "u_b": "B"},
        matchups={}, roster_to_user_by_league={}, playoff_weeks_by_league={},
        league_season_by_id={}, positions={})
    a = next(s for s in facts.sides if s["user_id"] == "u_a")
    assert a["given_summary"] == "2026 2nd pick · 2027 4th pick · 2027 5th pick"
    b = next(s for s in facts.sides if s["user_id"] == "u_b")
    assert b["given_summary"] == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_trade_story_engine.py -k "given_summary" -v`
Expected: FAIL — `KeyError: 'given_summary'`

- [ ] **Step 3: Implement**

In `src/sleeper_dynasty/engine/trade_story.py`, add a helper just above the `build_trade_story_facts` function (before `def build_trade_story_facts`):

```python
def _given_summary(given: list, positions: dict[str, str]) -> str:
    """Human-readable list of assets a side gave up.

    Players: "Name (POS)" or "Name". Picks: "YYYY Nth pick".
    via_pick PlayerAssets are treated as picks (the giver gave a pick).
    FaabAssets are skipped. Multiple items joined with " · ".
    """
    def _ordinal(n: int) -> str:
        return {1: "1st", 2: "2nd", 3: "3rd"}.get(n, f"{n}th")

    parts: list[str] = []
    for a in given:
        if isinstance(a, PlayerAsset):
            if a.via_pick is not None:
                # This player was a pick at trade time; giver gave a pick.
                parts.append(
                    f"{a.via_pick.season} {_ordinal(a.via_pick.round)} pick")
            else:
                pos = positions.get(a.player_id)
                parts.append(f"{a.name} ({pos})" if pos else a.name)
        elif isinstance(a, PickAsset):
            parts.append(f"{a.season} {_ordinal(a.round)} pick")
        # FaabAsset: skip
    return " · ".join(parts)
```

Then, in the per-side loop's `sides.append({...})` block (~line 358), add the new key. Change:

```python
        sides.append({
            "user_id": uid, "owner_name": owners_display.get(uid, uid),
            "player_arcs": arcs, "pick_outcomes": outs,
            "realized_players": realized_players,
        })
```

to:

```python
        sides.append({
            "user_id": uid, "owner_name": owners_display.get(uid, uid),
            "given_summary": _given_summary(list(side.given), positions),
            "player_arcs": arcs, "pick_outcomes": outs,
            "realized_players": realized_players,
        })
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_trade_story_engine.py -k "given_summary" -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Run the full engine suite (no regressions)**

Run: `.venv/bin/python -m pytest tests/test_trade_story_engine.py tests/test_trade_story_models.py -q`
Expected: PASS (all green — `given_summary` is additive)

- [ ] **Step 6: Commit**

```bash
git add src/sleeper_dynasty/engine/trade_story.py tests/test_trade_story_engine.py
git commit -m "feat(trade-story): add given_summary to facts packet (prevent directional hallucination)"
```

---

## Task 2: Teach the persona to use `given_summary`

**Files:**
- Modify: `src/sleeper_dynasty/llm/prompts/trade_story_persona.md`
- Test: `tests/test_trade_story_writer.py`

The persona already tells the writer to use player_arcs and pick_outcomes (received). This task adds an instruction to anchor the direction of the trade on `given_summary` so the writer never inverts who gave what.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_trade_story_writer.py`:

```python
def test_persona_includes_given_summary_instruction():
    p = load_persona()
    assert "given_summary" in p
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_trade_story_writer.py::test_persona_includes_given_summary_instruction -v`
Expected: FAIL — `AssertionError`

- [ ] **Step 3: Update the persona**

In `src/sleeper_dynasty/llm/prompts/trade_story_persona.md`, insert a new section **immediately before** the existing `## Player arcs: never misread a flip as a flop` section. The existing file ends with the `## Realized fate: ...` section added recently; this new section goes before the player-arcs section (which is earlier in the file). Find the line:

```
## Player arcs: never misread a flip as a flop
```

And insert this **above** it:

```markdown
## Trade direction: anchor on given_summary before writing a word
Each side carries `given_summary`: a pre-computed list of what that side GAVE
UP in the trade (e.g. "Mike Evans (WR)" or "2026 3rd pick · 2027 2nd pick").
This is a hard fact, not something you infer.

**Read both sides' `given_summary` first.** The winner is `winner_user_id`.
Before writing the verdict, state (internally) what the winner gave and what
the loser gave. Never say a side "walked off with X" or "landed X" or "got X"
unless X appears in that side's `player_arcs` or `pick_outcomes` (what they
RECEIVED). A side "gave up X" only when X appears in their `given_summary`.

Getting this backwards is the single worst error you can make.

```

Note: keep the blank line between the new section and the existing `## Player arcs` section.

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_trade_story_writer.py -v`
Expected: PASS (all tests including the new one)

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/llm/prompts/trade_story_persona.md tests/test_trade_story_writer.py
git commit -m "feat(trade-story): persona anchors on given_summary to prevent direction inversion"
```

---

## Task 3: Full-suite verification + push + deploy

**Files:** none (verification + git)

- [ ] **Step 1: Run the full engine suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS (all green)

- [ ] **Step 2: Run the targeted api story/grader suite**

Run: `cd api && ../.venv/bin/python -m pytest tests/ -q -k "story or grader"`
Expected: PASS

- [ ] **Step 3: Push to origin (triggers Railway auto-deploy)**

```bash
git push origin main
```

- [ ] **Step 4: Poll api deploy to completion**

```bash
for i in $(seq 1 30); do
  st=$(railway deployment list --service api --limit 1 --json 2>/dev/null | grep -m1 '"status"' | sed 's/.*: *"//; s/".*//')
  echo "[$i] api: $st"
  case "$st" in SUCCESS|FAILED|CRASHED) break;; esac
  sleep 20
done
```

Expected: `api: SUCCESS`

- [ ] **Step 5: Verify end-to-end**

```bash
echo "health: $(curl -s https://web-production-f949.up.railway.app/api/health)"
```

Expected: `health: {"status":"ok"}`

---

## Self-Review notes

- **Spec coverage:** `given_summary` string in the packet (Task 1) ✓; persona anchors direction on it (Task 2) ✓; deploy (Task 3) ✓.
- **No placeholders.** All code shown in full.
- **Type consistency:** `_given_summary` takes `list` + `dict[str, str]`, matches call site. Key `"given_summary"` consistent across Task 1 implementation and Task 2 test.
- **`side.given` is a `list`** — the `list(side.given)` call in the append is defensive but harmless (it's already a list per the `TradeSide` dataclass); either works.
- **`given_summary` in `facts_hash`:** It flows through `to_dict()` → `facts_hash`, so a change to what was given changes the hash → re-fires the story. This is correct and already works because the side dicts are embedded in `TradeStoryFacts.sides` which is included in `to_dict()`.
- **`via_pick` branch on the given side:** A `PlayerAsset` with `via_pick` set means the person was traded as "the draftee of this pick" — from the giver's perspective they gave a pick-that-resolved. The summary correctly labels it as a pick for the giver's side. This matches how `_pick_outcome` handles this on the received side.
