> _Historical doc — paths/names have changed. Repo is now `Code Apps/public-dynasty` (GitHub `tkeefe66/public-dynasty-app`), Railway project **shimmering-nature**, live at https://ffbdynasty.com. Ignore stale refs to `sleeper-dynasty` / `sleeper-trade-grader` / `web-production-f949`._

# Early/Mid/Late Pick Tiering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Value future/unresolved draft picks by their early/mid/late tier (estimated from the original team's current roster strength) instead of a flat round-average — first in Draft Capital (Phase 1), then in the trade grader's snapshot value (Phase 2).

**Architecture:** A tier-aware KTC pick table `(season, round, tier) → value` plus a `strength_tiers` ranking, both pure. Phase 1 wires them into `pick_holdings_value`; Phase 2 wires them into `trade_grader._ktc_value` (snapshot path only). Ship + verify Phase 1 before Phase 2.

**Tech Stack:** Python (engine + FastAPI), pytest; Next.js/Tailwind, tsc.

**Test commands** (run scoped — engine `tests/` and `api/tests/` collide together):
- Engine: `./.venv/bin/python -m pytest tests/<file> -q`
- API: `cd api && ./.venv/bin/python -m pytest tests/<file> -q`

---

# PHASE 1 — Draft Capital tiered

## Task 1: Tier-aware KTC pick table

**Files:**
- Modify: `src/sleeper_dynasty/api/ktc.py` (regex line ~159; add two functions)
- Test: `tests/test_ktc_tiered.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ktc_tiered.py
from sleeper_dynasty.api.ktc import (
    build_pick_value_table, build_pick_value_table_tiered, parse_pick_name_tiered,
)
from sleeper_dynasty.models.player import KTCValue


def _pick(name, sf):
    return KTCValue(name=name, normalized_name=name.lower(), position="PICK",
                    superflex_value=sf, one_qb_value=sf)


def test_parse_pick_name_tiered():
    assert parse_pick_name_tiered("2027 Early 1st") == (2027, 1, "early")
    assert parse_pick_name_tiered("2027 Late 2nd") == (2027, 2, "late")
    assert parse_pick_name_tiered("2027 1st") == (2027, 1, "")
    assert parse_pick_name_tiered("Josh Allen") is None


def test_tiered_table_keeps_tiers_unaveraged():
    vals = {
        "a": _pick("2027 Early 1st", 9000),
        "b": _pick("2027 Late 1st", 4000),
    }
    t = build_pick_value_table_tiered(vals)
    assert t[(2027, 1, "early")].superflex_value == 9000
    assert t[(2027, 1, "late")].superflex_value == 4000
    # round-average table still averages them (unchanged behavior)
    r = build_pick_value_table(vals)
    assert r[(2027, 1)].superflex_value == 6500
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_ktc_tiered.py -q`
Expected: FAIL — `parse_pick_name_tiered` / `build_pick_value_table_tiered` don't exist.

- [ ] **Step 3: Make the regex tier group capturing**

In `src/sleeper_dynasty/api/ktc.py`, change `_PICK_NAME_RE` (line ~159) from:

```python
_PICK_NAME_RE = re.compile(
    r"^(?P<year>\d{4})\s+(?:(?:early|mid|late)\s+)?(?P<ord>\d(?:st|nd|rd|th))$",
    re.IGNORECASE,
)
```

to:

```python
_PICK_NAME_RE = re.compile(
    r"^(?P<year>\d{4})\s+(?:(?P<tier>early|mid|late)\s+)?(?P<ord>\d(?:st|nd|rd|th))$",
    re.IGNORECASE,
)
```

(The existing `_parse_pick_name` only reads `year`/`ord`, so it's unaffected.)

- [ ] **Step 4: Add the two functions**

After `build_pick_value_table` (ends ~line 212), add:

```python
def parse_pick_name_tiered(name: str) -> tuple[int, int, str] | None:
    """Parse a KTC pick name into (season, round, tier); tier is "" if untiered."""
    m = _PICK_NAME_RE.match(name.strip())
    if not m:
        return None
    rnd = _PICK_ORDINALS.get(m.group("ord").lower())
    if rnd is None:
        return None
    return int(m.group("year")), rnd, (m.group("tier") or "").lower()


def build_pick_value_table_tiered(
    ktc_values: dict[str, KTCValue],
) -> dict[tuple[int, int, str], KTCValue]:
    """Tier-aware pick table: (season, round, tier) -> KTCValue, NOT averaged.

    Parallel to build_pick_value_table, which keeps the round-average fallback.
    """
    table: dict[tuple[int, int, str], KTCValue] = {}
    for val in ktc_values.values():
        key = parse_pick_name_tiered(val.name)
        if key is not None:
            table[key] = val
    return table
```

- [ ] **Step 5: Run to verify it passes**

Run: `./.venv/bin/python -m pytest tests/test_ktc_tiered.py -q`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add src/sleeper_dynasty/api/ktc.py tests/test_ktc_tiered.py
git commit -m "feat(ktc): tier-aware pick value table (season, round, early/mid/late)"
```

---

## Task 2: `strength_tiers` + `tiered_pick_value`

**Files:**
- Modify: `src/sleeper_dynasty/engine/draft_signals.py`
- Test: `tests/test_draft_signals.py` (append)

- [ ] **Step 1: Write the failing test (append)**

```python
from sleeper_dynasty.engine.draft_signals import strength_tiers, tiered_pick_value


def test_strength_tiers_thirds_by_rank():
    # 6 owners, strongest -> late, weakest -> early.
    vals = {f"u{i}": v for i, v in enumerate([100, 90, 80, 70, 60, 50])}
    t = strength_tiers(vals)
    assert t["u0"] == "late" and t["u1"] == "late"
    assert t["u2"] == "mid" and t["u3"] == "mid"
    assert t["u4"] == "early" and t["u5"] == "early"


def test_strength_tiers_tiny_league_all_mid():
    assert strength_tiers({"a": 5, "b": 3}) == {"a": "mid", "b": "mid"}


def test_tiered_pick_value_falls_back_to_round_avg():
    tiered = {(2027, 1, "early"): 9000.0}
    rnd = {(2027, 1): 6500.0}
    assert tiered_pick_value(2027, 1, "early", tiered, rnd) == 9000.0
    assert tiered_pick_value(2027, 1, "late", tiered, rnd) == 6500.0   # no late -> round avg
    assert tiered_pick_value(2028, 1, "early", tiered, rnd) == 0.0     # nothing
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_draft_signals.py -k "strength_tiers or tiered_pick" -q`
Expected: FAIL — names don't exist.

- [ ] **Step 3: Implement (append to draft_signals.py)**

```python
def strength_tiers(value_by_owner: dict) -> dict:
    """Rank owners by value desc, split into thirds: strongest third -> 'late'
    (picks land late, worth less), middle -> 'mid', weakest -> 'early' (worth
    most). Fewer than 3 owners -> all 'mid' (no meaningful ranking)."""
    owners = sorted(value_by_owner, key=lambda o: value_by_owner[o], reverse=True)
    n = len(owners)
    if n < 3:
        return {o: "mid" for o in owners}
    labels = ("late", "mid", "early")
    return {o: labels[min(2, i * 3 // n)] for i, o in enumerate(owners)}


def tiered_pick_value(
    season: int, rnd: int, tier: str,
    tiered: dict[tuple[int, int, str], float],
    round_avg: dict[tuple[int, int], float],
) -> float:
    """Tiered value with round-average fallback, then 0."""
    v = tiered.get((season, rnd, tier))
    if v is not None:
        return float(v)
    return float(round_avg.get((season, rnd), 0.0))
```

- [ ] **Step 4: Run to verify it passes**

Run: `./.venv/bin/python -m pytest tests/test_draft_signals.py -q`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/draft_signals.py tests/test_draft_signals.py
git commit -m "feat(engine): strength_tiers + tiered_pick_value helpers"
```

---

## Task 3: `pick_holdings_value` tiers each held pick

**Files:**
- Modify: `src/sleeper_dynasty/engine/draft_signals.py` (`pick_holdings_value`)
- Test: `tests/test_draft_signals.py` (append)

- [ ] **Step 1: Write the failing test (append)**

```python
def test_pick_holdings_value_tiers_by_original_team():
    # roster 1 is a weak team (early picks), roster 2 strong (late picks).
    pv = {(2027, 1): 6500.0}                       # round average fallback
    tiered = {(2027, 1, "early"): 9000.0, (2027, 1, "late"): 4000.0}
    tiers = {1: "early", 2: "late"}
    val = pick_holdings_value(
        traded_picks=[], roster_ids=[1, 2], seasons=[2027], num_rounds=1,
        pick_values=pv, tier_by_roster=tiers, tiered_values=tiered)
    assert val[1] == 9000.0      # own early 1st
    assert val[2] == 4000.0      # own late 1st


def test_pick_holdings_value_backcompat_round_average():
    pv = {(2027, 1): 6500.0}
    val = pick_holdings_value(
        traded_picks=[], roster_ids=[1], seasons=[2027], num_rounds=1, pick_values=pv)
    assert val[1] == 6500.0      # no tier args -> round average
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_draft_signals.py -k pick_holdings_value_tiers -q`
Expected: FAIL — `pick_holdings_value` has no `tier_by_roster`/`tiered_values`.

- [ ] **Step 3: Update `pick_holdings_value`**

Replace the function body's signature + value loop. New signature:

```python
def pick_holdings_value(
    *,
    traded_picks: list[DraftPick],
    roster_ids: list[int],
    seasons: list[int],
    num_rounds: int,
    pick_values: dict[tuple[int, int], float],
    tier_by_roster: dict[int, str] | None = None,
    tiered_values: dict[tuple[int, int, str], float] | None = None,
) -> dict[int, float]:
```

Replace the final value-accumulation loop:

```python
    tier_by_roster = tier_by_roster or {}
    tiered_values = tiered_values or {}
    value: dict[int, float] = {rid: 0.0 for rid in roster_ids}
    for (s, rd, orig), owner in owner_of.items():
        tier = tier_by_roster.get(orig, "")
        value[owner] = value.get(owner, 0.0) + tiered_pick_value(
            s, rd, tier, tiered_values, pick_values)
    return value
```

- [ ] **Step 4: Run to verify it passes**

Run: `./.venv/bin/python -m pytest tests/test_draft_signals.py -q`
Expected: PASS (all, including the earlier round-average tests via fallback).

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/draft_signals.py tests/test_draft_signals.py
git commit -m "feat(engine): pick_holdings_value tiers by original team's strength"
```

---

## Task 4: Thread the tiered table through refresh I/O

**Files:**
- Modify: `api/app/services/grader_io.py` (import + add to `supporting`)

- [ ] **Step 1: Add the tiered table to supporting**

In `api/app/services/grader_io.py`, find the import of `build_pick_value_table` and add `build_pick_value_table_tiered` alongside it. Then after line 145 (`pick_value_table = build_pick_value_table(ktc_values)`), add:

```python
    pick_value_table_tiered = build_pick_value_table_tiered(ktc_values)
```

And in the returned `supporting` dict (the big `return {...}`), add the key:

```python
        "pick_value_table_tiered": pick_value_table_tiered,
```

- [ ] **Step 2: Verify the api suite still imports/passes**

Run: `cd api && ./.venv/bin/python -m pytest tests/ -k "grader or rating" -q`
Expected: PASS (no behavior change yet; the key is just available).

- [ ] **Step 3: Commit**

```bash
git add api/app/services/grader_io.py
git commit -m "feat(api): expose tiered pick value table in supporting"
```

---

## Task 5: Draft Capital uses the tiers

**Files:**
- Modify: `api/app/services/rating_signals.py`
- Test: `api/tests/test_rating_signals_draft.py` (append)

- [ ] **Step 1: Write the failing test (append)**

```python
def test_draft_capital_tiered_by_roster_strength():
    # 3 owners so strength_tiers produces early/mid/late (it returns all "mid"
    # for fewer than 3). uB strongest -> late picks; uA weakest -> early picks.
    s = _supporting()
    s["roster_to_user_by_league"] = {"L": {1: "uA", 2: "uB", 3: "uC"}}
    s["owners"] = {"uA": {}, "uB": {}, "uC": {}}
    s["pick_value_table"] = {(2027, 1): _KTC(6500)}
    s["pick_value_table_tiered"] = {
        (2027, 1, "early"): _KTC(9000), (2027, 1, "mid"): _KTC(6500),
        (2027, 1, "late"): _KTC(4000)}
    s["ktc_by_player_id"].update({"b1": _KTC(9000), "b2": _KTC(9000),
                                  "c1": _KTC(5000), "a1": _KTC(100)})
    holders = {"b1": "uB", "b2": "uB", "c1": "uC", "a1": "uA"}
    _, outlook = compute_rating_signals(
        s, current_holders=holders, traded_picks=[], rookie_picks=[],
        num_draft_rounds=1)
    # uA holds an EARLY-tier 1st (9000) > uB's LATE-tier 1st (4000)
    assert outlook["uA"]["draft_capital"] > outlook["uB"]["draft_capital"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd api && ./.venv/bin/python -m pytest tests/test_rating_signals_draft.py -k tiered -q`
Expected: FAIL — draft_capital still uses round-average (uA == uB).

- [ ] **Step 3: Wire tiers into the draft-capital block**

In `api/app/services/rating_signals.py`, import the helpers (add to the existing draft_signals import line):

```python
from sleeper_dynasty.engine.draft_signals import (
    DraftedPick, draft_skill, pick_holdings_value, strength_tiers,
)
```

In the draft-capital block, replace the `holdings = pick_holdings_value(...)` call with tier computation + tiered args:

```python
    roster_value_by_id = {
        rid: roster_value.get(uid, 0.0) for rid, uid in r2u_current.items()
    }
    tier_by_roster = strength_tiers(roster_value_by_id)
    tiered_pick_values = {
        k: _ktc_value(v)
        for k, v in (supporting.get("pick_value_table_tiered") or {}).items()
    }
    holdings = pick_holdings_value(
        traded_picks=traded_picks or [], roster_ids=list(r2u_current),
        seasons=outlook_seasons, num_rounds=num_draft_rounds, pick_values=pick_values,
        tier_by_roster=tier_by_roster, tiered_values=tiered_pick_values)
```

(`_ktc_value(v)` here is the module-local KTCValue→float helper, applied to the
tiered table's `(season, round, tier)` KTCValue entries.)

- [ ] **Step 4: Run to verify it passes**

Run: `cd api && ./.venv/bin/python -m pytest tests/test_rating_signals_draft.py -q`
Expected: PASS (all, including the prior draft tests).

- [ ] **Step 5: Commit**

```bash
git add api/app/services/rating_signals.py api/tests/test_rating_signals_draft.py
git commit -m "feat(api): Draft Capital valued by early/mid/late tier of original team"
```

---

## Task 6: Frontend help + Phase 1 verify + deploy

**Files:**
- Modify: `web/components/Leaderboard.tsx` (`draft_capital` help)

- [ ] **Step 1: Update the Draft Capital help copy**

In `web/components/Leaderboard.tsx`, change the `draft_capital` entry in `SIGNAL_HELP` to:

```tsx
  draft_capital:
    "Market value of the future rookie picks you hold across the next three drafts, tiered early/mid/late by each pick's original team strength (a rebuilder's pick is worth more).",
```

- [ ] **Step 2: Typecheck**

Run: `cd web && npx tsc --noEmit 2>&1 | grep -v "dev/loading"`
Expected: no errors.

- [ ] **Step 3: Full suites green**

Run: `./.venv/bin/python -m pytest tests/ -q`
Run: `cd api && ./.venv/bin/python -m pytest tests/ -q`
Expected: engine + api pass.

- [ ] **Step 4: Commit**

```bash
git add web/components/Leaderboard.tsx
git commit -m "feat(web): Draft Capital help notes early/mid/late tiering"
```

- [ ] **Step 5: Deploy Phase 1 + verify**

Merge to main isn't required between phases (same branch), but DEPLOY and verify
Phase 1 before starting Phase 2. Deploy both services (`railway up --service api/web --detach`),
poll SUCCESS, trigger a prod refresh, then confirm Draft Capital contributions
shifted and spread wider than the old round-average (pick-rich rebuilders rise):

```bash
curl -s "https://web-production-f949.up.railway.app/api/league/9000000000000000001/leaderboard?year=all" \
  | python3 -c "import sys,json; rows=json.load(sys.stdin)['rows']; print(sorted(r['pillars']['outlook']['signals']['draft_capital']['contribution'] for r in rows))"
```

Expected: a wider spread of draft_capital contributions than before (tiering
separates rebuilders from contenders).

---

# PHASE 2 — Trade grader snapshot tiered

## Task 7: `_ktc_value` tiers unresolved snapshot picks

**Files:**
- Modify: `src/sleeper_dynasty/engine/trade_grader.py` (`_ktc_value`, `grade_snapshot_value`, `build_asset_breakdown`, `grade_trade`)
- Test: `tests/test_trade_grader_tiering.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_trade_grader_tiering.py
from sleeper_dynasty.engine.trade_grader import _ktc_value
from sleeper_dynasty.models.player import KTCValue
from sleeper_dynasty.models.trade import PickAsset


def _kv(sf):
    return KTCValue(name="p", normalized_name="p", position="PICK",
                    superflex_value=sf, one_qb_value=sf)


def _future_pick(owner_uid):
    return PickAsset(season=2027, round=1, original_owner_user_id=owner_uid,
                     drafted_player_id=None, drafted_player_name=None)


def test_snapshot_pick_tiered_by_original_owner():
    round_avg = {(2027, 1): _kv(6500)}
    tiered = {(2027, 1, "early"): _kv(9000), (2027, 1, "late"): _kv(4000)}
    tiers = {"weak": "early", "strong": "late"}
    early = _ktc_value(_future_pick("weak"), {}, "superflex", round_avg,
                       tier_by_user=tiers, tiered_values=tiered)
    late = _ktc_value(_future_pick("strong"), {}, "superflex", round_avg,
                      tier_by_user=tiers, tiered_values=tiered)
    assert early == 9000.0 and late == 4000.0


# PickAsset fields: season:int, round:int, original_owner_user_id:str,
# drafted_player_id: str|None=None, drafted_player_name: str|None=None.
def test_at_trade_path_stays_round_average():
    round_avg = {(2027, 1): _kv(6500)}
    tiered = {(2027, 1, "early"): _kv(9000)}
    v = _ktc_value(_future_pick("weak"), {}, "superflex", round_avg,
                   ignore_drafted_player=True,
                   tier_by_user={"weak": "early"}, tiered_values=tiered)
    assert v == 6500.0     # at-trade -> round average, not tiered
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_trade_grader_tiering.py -q`
Expected: FAIL — `_ktc_value` has no `tier_by_user`/`tiered_values`.

- [ ] **Step 3: Add tier args to `_ktc_value`**

In `src/sleeper_dynasty/engine/trade_grader.py`, update `_ktc_value`'s signature
and the PickAsset branch (lines ~33-75):

```python
def _ktc_value(
    asset: TradeAsset,
    ktc: dict[str, KTCValue],
    fmt: str,
    pick_values: dict[tuple[int, int], KTCValue] | None = None,
    ignore_drafted_player: bool = False,
    tier_by_user: dict[str, str] | None = None,
    tiered_values: dict[tuple[int, int, str], KTCValue] | None = None,
) -> float:
```

Replace the PickAsset tail (the `table = pick_values or {}` / `return _from_ktc(table.get(...))` lines) with:

```python
        table = pick_values or {}
        # Snapshot value of an unresolved future pick: tier by the original
        # team's current strength. At-trade (ignore_drafted_player) stays
        # round-average (no historical roster strength).
        if not ignore_drafted_player and tier_by_user is not None:
            tier = tier_by_user.get(asset.original_owner_user_id, "")
            tv = (tiered_values or {}).get((asset.season, asset.round, tier))
            if tv is not None:
                return _from_ktc(tv)
        return _from_ktc(table.get((asset.season, asset.round)))
```

- [ ] **Step 4: Thread the args through callers**

`grade_snapshot_value` — add the two params and pass them to `_ktc_value`:

```python
def grade_snapshot_value(
    rt: ResolvedTrade,
    ktc_values: dict[str, KTCValue],
    fmt: str = "superflex",
    pick_values: dict[tuple[int, int], KTCValue] | None = None,
    ignore_drafted_player: bool = False,
    tier_by_user: dict[str, str] | None = None,
    tiered_values: dict[tuple[int, int, str], KTCValue] | None = None,
) -> dict[str, float]:
    swings: dict[str, float] = {}
    for uid, side in rt.sides.items():
        received = sum(_ktc_value(a, ktc_values, fmt, pick_values, ignore_drafted_player,
                                  tier_by_user, tiered_values) for a in side.received)
        given = sum(_ktc_value(a, ktc_values, fmt, pick_values, ignore_drafted_player,
                               tier_by_user, tiered_values) for a in side.given)
        swings[uid] = received - given
    return swings
```

`build_asset_breakdown` — add the same two params to its signature and pass them
into its internal `_ktc_value(a, ktc_values, fmt, pick_values)` call (the one
that sets each row's `.ktc`, ~line 272) as
`_ktc_value(a, ktc_values, fmt, pick_values, False, tier_by_user, tiered_values)`.

`grade_trade` — add the two params to its signature (after `pick_values`) and
pass them into both the `grade_snapshot_value(...)` call (line ~335) and the
`build_asset_breakdown(...)` call (line ~343):

```python
    snapshot = grade_snapshot_value(rt, ktc_values, fmt=fmt, pick_values=pick_values,
                                    tier_by_user=tier_by_user, tiered_values=tiered_values)
    ...
    breakdown = build_asset_breakdown(
        rt, ktc_values=ktc_values, matchups=matchups,
        roster_to_user_by_league=roster_to_user_by_league,
        league_season_by_id=league_season_by_id,
        phase_by_lwr=phase_by_lwr or {},
        playoff_week_start_by_league=playoff_week_start_by_league,
        pick_values=pick_values, fmt=fmt,
        tier_by_user=tier_by_user, tiered_values=tiered_values,
    )
```

with `grade_trade` signature gaining:

```python
    tier_by_user: dict[str, str] | None = None,
    tiered_values: dict[tuple[int, int, str], KTCValue] | None = None,
```

- [ ] **Step 5: Run to verify it passes**

Run: `./.venv/bin/python -m pytest tests/test_trade_grader_tiering.py -q`
Run: `./.venv/bin/python -m pytest tests/ -k trade_grader -q`
Expected: new tests PASS; existing trade-grader tests PASS (tier args default None → round-average, unchanged).

- [ ] **Step 6: Commit**

```bash
git add src/sleeper_dynasty/engine/trade_grader.py tests/test_trade_grader_tiering.py
git commit -m "feat(engine): trade grader tiers unresolved snapshot picks by original team"
```

---

## Task 8: Compute `tier_by_user` before grading + thread in

**Files:**
- Modify: `api/app/services/grader.py`

- [ ] **Step 1: Compute tier_by_user before the grading loop**

In `api/app/services/grader.py`, right AFTER `supporting = await _pull_supporting_data(...)`
(ends ~line 112) and BEFORE the grading loop (`await progress_cb("grading", ...)`),
insert:

```python
        # Current roster strength -> early/mid/late tier per owner (for snapshot
        # pick valuation). Computed before grading so grade_trade can use it.
        from sleeper_dynasty.engine.draft_signals import strength_tiers
        tier_by_user: dict[str, str] = {}
        try:
            current_rosters = await client.get_rosters(current_league_id)
            for r in current_rosters:
                for pid in (r.players or []):
                    current_holders[pid] = r.owner_id
            ktc_now = supporting["ktc_by_player_id"]
            rv: dict[str, float] = {}
            for r in current_rosters:
                total = 0.0
                for pid in (r.players or []):
                    v = ktc_now.get(pid)
                    if v is not None and v.superflex_value is not None:
                        total += float(v.superflex_value)
                rv[r.owner_id] = total
            tier_by_user = strength_tiers(rv)
        except Exception:
            log.exception("could not compute roster-strength tiers")
```

Add `current_holders: dict[str, str] = {}` and `current_rosters: list = []`
initialization just before this block (move them up from their current spot), and
**delete** the later duplicate fetch block (the `current_holders = {}` /
`current_rosters = await client.get_rosters(...)` try/except near line 175 that
this replaces). Keep `current_rosters` available for `_snapshot_standings`.

- [ ] **Step 2: Pass tiers into grade_trade**

In the grading loop, change the `grade_trade(...)` call to add:

```python
                pick_values=supporting["pick_value_table"],
                tier_by_user=tier_by_user,
                tiered_values=supporting.get("pick_value_table_tiered") or {},
            )
```

- [ ] **Step 3: Run the full api suite**

Run: `cd api && ./.venv/bin/python -m pytest tests/ -q`
Expected: PASS (136+; grading still works, now tier-aware when data present).

- [ ] **Step 4: Commit**

```bash
git add api/app/services/grader.py
git commit -m "feat(api): compute roster-strength tiers before grading, tier snapshot picks"
```

---

## Task 9: Phase 2 verify + deploy

**Files:** none.

- [ ] **Step 1: Full suites green**

Run: `./.venv/bin/python -m pytest tests/ -q`
Run: `cd api && ./.venv/bin/python -m pytest tests/ -q`
Run: `cd web && npx tsc --noEmit 2>&1 | grep -v "dev/loading"`
Expected: all pass; tsc clean.

- [ ] **Step 2: Merge to main + deploy both**

Per `superpowers:finishing-a-development-branch` (merge), then `railway-deploy`:

```bash
railway up --service api --detach -m "pick tiering early/mid/late"
railway up --service web --detach -m "pick tiering early/mid/late"
```

Poll each to SUCCESS.

- [ ] **Step 3: Refresh + verify Trade Value shifted sensibly**

Trigger a prod refresh, then spot-check a trade involving a future pick: the
headline Trade Value should reflect the pick's tier (a rebuilder's early-pick
haul worth more than the old round-average; a contender's late pick worth less).

```bash
curl -s "https://web-production-f949.up.railway.app/api/league/9000000000000000001/leaderboard?year=all" \
  | python3 -c "import sys,json; rows=json.load(sys.stdin)['rows']; print([(r['owner']['owner_name'], r['pillars']['trade_impact']['signals']['value']['contribution']) for r in rows])"
```

Expected: the trade-impact `value` signal contributions shifted (not broken);
trade pages render Trade Value with the new tiered numbers.

- [ ] **Step 4: Visual spot-check**

Open a trade-detail page that includes a future pick and confirm the Trade Value
swing reads sensibly; open `/gm` and confirm Draft Capital still renders.

---

## Notes for the implementer

- **Back-compat:** every new tier param defaults to `None`/`{}` → round-average
  behavior, so existing engine tests pass unchanged. Tiering only activates when
  the refresh passes the tier map + tiered table.
- **At-trade stays round-average** by design (the `ignore_drafted_player` branch
  never tiers). Only snapshot (today) values tier.
- **Single source of tiers:** Phase 2 computes `tier_by_user` once in grader.py;
  Phase 1's Draft Capital derives its `tier_by_roster` from the same roster-value
  ranking inside rating_signals. Both rank current roster KTC into thirds via
  `strength_tiers`.
- **Blast radius:** Phase 2 shifts the snapshot Trade Value everywhere it's shown
  (trade pages, owner rollups, GM rating value signal, became-grades). Verify the
  numbers moved sensibly, not that they're identical.
```
