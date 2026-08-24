> _Historical doc — paths/names have changed. Repo is now `Code Apps/public-dynasty` (GitHub `tkeefe66/public-dynasty-app`), Railway project **shimmering-nature**, live at https://ffbdynasty.com. Ignore stale refs to `sleeper-dynasty` / `sleeper-trade-grader` / `web-production-f949`._

# Draft Capital (live) + Draft Skill (new) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the stubbed `draft_capital` signal with a live KTC-weighted value of each owner's future rookie picks, and add a new `draft_skill` signal that scores how an owner's past rookie picks panned out vs their slot tier — both in the GM rating's Outlook pillar.

**Architecture:** Two pure engine functions plus a normalizer in a new `engine/draft_signals.py`; the refresh fetches traded picks + rookie-draft results and threads them into `compute_rating_signals`, which un-stubs `draft_capital` and emits `draft_skill`. Outlook is rebalanced to four signals. The LLM blurb and the breakdown UI gain the new signal.

**Tech Stack:** Python (engine + FastAPI), pytest; Next.js/Tailwind frontend, tsc.

**Test commands** (the engine `tests/` and `api/tests/` collide if run together — run them scoped, as the Makefile does):
- Engine: `./.venv/bin/python -m pytest tests/<file> -q`
- API: `cd api && ./.venv/bin/python -m pytest tests/<file> -q`

---

## File Structure

**New**
- `src/sleeper_dynasty/engine/draft_signals.py` — `DraftedPick`, `pick_holdings_value` (capital), `build_rookie_picks` (normalize Sleeper draft dicts, exclude startup), `draft_skill`.
- `tests/test_draft_signals.py`

**Modified**
- `src/sleeper_dynasty/engine/gm_rating.py` — Outlook weights → 4 signals.
- `tests/test_gm_rating.py` — update the pinned outlook signal set.
- `api/app/services/rating_signals.py` — dynamic window, production map, both draft signals, un-stub.
- `api/tests/` — new `test_rating_signals_draft.py`.
- `api/app/services/grader.py` — fetch traded picks + rookie drafts, thread through.
- `src/sleeper_dynasty/engine/gm_rating_blurb.py` — `draft_skill` label; `draft_capital_counted=True`.
- `tests/test_gm_rating_blurb_facts.py` — `draft_capital_counted` now True.
- `src/sleeper_dynasty/llm/prompts/gm_rating_blurb_persona.md` — allow draft mentions.
- `web/components/Leaderboard.tsx` — `draft_skill` label + help, update `draft_capital` help.

---

## Task 1: Rebalance Outlook to four signals

**Files:**
- Modify: `src/sleeper_dynasty/engine/gm_rating.py:27`
- Test: `tests/test_gm_rating.py:26`

- [ ] **Step 1: Update the pinned test to the new signal set**

In `tests/test_gm_rating.py`, change line 26 from:

```python
    assert set(SIGNAL_WEIGHTS["outlook"]) == {"roster_value", "draft_capital", "youth"}
```

to:

```python
    assert set(SIGNAL_WEIGHTS["outlook"]) == {"roster_value", "draft_capital", "draft_skill", "youth"}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_gm_rating.py -q`
Expected: FAIL on the outlook-set assertion (draft_skill missing from SIGNAL_WEIGHTS).

- [ ] **Step 3: Update the weights**

In `src/sleeper_dynasty/engine/gm_rating.py`, change line 27 from:

```python
    "outlook": {"roster_value": 0.40, "draft_capital": 0.35, "youth": 0.25},
```

to:

```python
    "outlook": {"roster_value": 0.35, "draft_capital": 0.25, "draft_skill": 0.20, "youth": 0.20},
```

Also update the module docstring line 9 to read:
`  - Outlook      (0.25): future franchise health — roster value, draft capital, draft skill, youth`

- [ ] **Step 4: Run the full gm_rating suite**

Run: `./.venv/bin/python -m pytest tests/test_gm_rating.py -q`
Expected: PASS (owners passing outlook without `draft_skill` get 0 for it; the sig-sum≈pillar invariant holds).

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/gm_rating.py tests/test_gm_rating.py
git commit -m "feat(engine): Outlook = roster/capital/skill/youth (0.35/0.25/0.20/0.20)"
```

---

## Task 2: `pick_holdings_value` (Draft Capital)

**Files:**
- Create: `src/sleeper_dynasty/engine/draft_signals.py`
- Test: `tests/test_draft_signals.py`

`DraftPick` already exists (`src/sleeper_dynasty/models/league.py`): fields `season`, `round`, `original_owner_id`, `current_owner_id`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_draft_signals.py
from sleeper_dynasty.engine.draft_signals import pick_holdings_value
from sleeper_dynasty.models.league import DraftPick


def test_default_slate_valued_by_ktc():
    # 2 rosters, seasons [2027], 2 rounds. No trades.
    pv = {(2027, 1): 1000.0, (2027, 2): 400.0}
    val = pick_holdings_value(
        traded_picks=[], roster_ids=[1, 2], seasons=[2027], num_rounds=2, pick_values=pv)
    assert val[1] == 1400.0 and val[2] == 1400.0


def test_traded_away_moves_value_to_acquirer():
    pv = {(2027, 1): 1000.0, (2027, 2): 400.0}
    # roster 1's 2027 1st now owned by roster 2.
    tp = [DraftPick(season=2027, round=1, original_owner_id=1, current_owner_id=2)]
    val = pick_holdings_value(
        traded_picks=tp, roster_ids=[1, 2], seasons=[2027], num_rounds=2, pick_values=pv)
    assert val[1] == 400.0          # lost the 1st
    assert val[2] == 2400.0         # own slate (1400) + acquired 1st (1000)


def test_reacquired_own_pick_not_double_counted():
    pv = {(2027, 1): 1000.0}
    # roster 1's own 1st recorded as traded but currently back with roster 1.
    tp = [DraftPick(season=2027, round=1, original_owner_id=1, current_owner_id=1)]
    val = pick_holdings_value(
        traded_picks=tp, roster_ids=[1, 2], seasons=[2027], num_rounds=1, pick_values=pv)
    assert val[1] == 1000.0 and val[2] == 1000.0


def test_missing_pick_value_is_zero():
    pv = {(2027, 1): 1000.0}            # 2028 not published
    val = pick_holdings_value(
        traded_picks=[], roster_ids=[1], seasons=[2027, 2028], num_rounds=1, pick_values=pv)
    assert val[1] == 1000.0
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_draft_signals.py -q`
Expected: FAIL with `ModuleNotFoundError: sleeper_dynasty.engine.draft_signals`.

- [ ] **Step 3: Implement**

```python
# src/sleeper_dynasty/engine/draft_signals.py
"""Pure draft-based Outlook signals: future pick value (capital) and past pick
quality vs slot tier (skill). No I/O — callers pass clean inputs."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from sleeper_dynasty.models.league import DraftPick


def pick_holdings_value(
    *,
    traded_picks: list[DraftPick],
    roster_ids: list[int],
    seasons: list[int],
    num_rounds: int,
    pick_values: dict[tuple[int, int], float],
) -> dict[int, float]:
    """KTC value of the future picks each roster holds.

    Every roster starts owning its own ``(season, round)`` pick across the
    outlook ``seasons``; ``traded_picks`` reassign ownership. Value = sum of
    ``pick_values[(season, round)]`` over held picks (missing slot -> 0).
    """
    owner_of: dict[tuple[int, int, int], int] = {}
    for rid in roster_ids:
        for s in seasons:
            for rd in range(1, num_rounds + 1):
                owner_of[(s, rd, rid)] = rid
    for p in traded_picks:
        key = (p.season, p.round, p.original_owner_id)
        if key in owner_of:
            owner_of[key] = p.current_owner_id

    value: dict[int, float] = {rid: 0.0 for rid in roster_ids}
    for (s, rd, _orig), owner in owner_of.items():
        value[owner] = value.get(owner, 0.0) + float(pick_values.get((s, rd), 0.0))
    return value
```

- [ ] **Step 4: Run to verify it passes**

Run: `./.venv/bin/python -m pytest tests/test_draft_signals.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/draft_signals.py tests/test_draft_signals.py
git commit -m "feat(engine): pick_holdings_value — KTC-weighted draft capital"
```

---

## Task 3: `DraftedPick` + `build_rookie_picks` (normalize, exclude startup)

**Files:**
- Modify: `src/sleeper_dynasty/engine/draft_signals.py`
- Test: `tests/test_draft_signals.py` (append)

Consumes raw Sleeper draft + pick dicts (same style as `engine/trade_history.py`).
A draft dict has `draft_id`, `season`, `status`, `settings.rounds`, `settings.teams`.
A pick dict has `round`, `draft_slot`, `player_id`, `roster_id`, `picked_by` (uid or "").

- [ ] **Step 1: Write the failing test (append)**

```python
from sleeper_dynasty.engine.draft_signals import DraftedPick, build_rookie_picks


def test_build_rookie_picks_excludes_startup_and_normalizes():
    drafts_by_league = {
        "L1": [{"draft_id": "d_start", "season": 2024, "status": "complete",
                "settings": {"rounds": 4, "teams": 2}}],     # origin season => startup
        "L2": [{"draft_id": "d_rook", "season": 2025, "status": "complete",
                "settings": {"rounds": 2, "teams": 2}}],
    }
    picks_by_draft_id = {
        "d_start": [{"round": 1, "draft_slot": 1, "player_id": "px", "roster_id": 1, "picked_by": "uA"}],
        "d_rook": [
            {"round": 1, "draft_slot": 1, "player_id": "p1", "roster_id": 1, "picked_by": "uA"},
            {"round": 1, "draft_slot": 2, "player_id": "p2", "roster_id": 2, "picked_by": ""},
        ],
    }
    r2u = {"L1": {1: "uA", 2: "uB"}, "L2": {1: "uA", 2: "uB"}}
    out = build_rookie_picks(
        drafts_by_league=drafts_by_league, picks_by_draft_id=picks_by_draft_id,
        origin_season=2024, roster_to_user_by_league=r2u)
    # startup pick (px) excluded; both rookie picks present
    assert {p.player_id for p in out} == {"p1", "p2"}
    p1 = next(p for p in out if p.player_id == "p1")
    assert p1.drafter_id == "uA" and p1.round == 1 and p1.slot == 1 and p1.picks_in_round == 2
    # empty picked_by falls back to the slot roster's owner
    p2 = next(p for p in out if p.player_id == "p2")
    assert p2.drafter_id == "uB"


def test_build_rookie_picks_skips_incomplete_drafts():
    drafts_by_league = {"L2": [{"draft_id": "d", "season": 2025, "status": "drafting",
                                "settings": {"rounds": 2, "teams": 2}}]}
    picks_by_draft_id = {"d": [{"round": 1, "draft_slot": 1, "player_id": "p1",
                                "roster_id": 1, "picked_by": "uA"}]}
    out = build_rookie_picks(
        drafts_by_league=drafts_by_league, picks_by_draft_id=picks_by_draft_id,
        origin_season=2024, roster_to_user_by_league={"L2": {1: "uA"}})
    assert out == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_draft_signals.py -k build_rookie -q`
Expected: FAIL with `ImportError: cannot import name 'DraftedPick'` / `build_rookie_picks`.

- [ ] **Step 3: Implement (append to draft_signals.py)**

```python
@dataclass
class DraftedPick:
    draft_id: str
    round: int
    slot: int            # 1-based position within the round
    picks_in_round: int
    player_id: str
    drafter_id: str      # owner uid who made the selection


def build_rookie_picks(
    *,
    drafts_by_league: dict[str, list[dict]],
    picks_by_draft_id: dict[str, list[dict]],
    origin_season: int,
    roster_to_user_by_league: dict[str, dict[int, str]],
) -> list[DraftedPick]:
    """Normalize completed rookie-draft picks. Excludes the inaugural startup
    draft (any draft in ``origin_season``). Credits ``picked_by``, falling back
    to the slot roster's current owner."""
    out: list[DraftedPick] = []
    for league_id, drafts in drafts_by_league.items():
        r2u = roster_to_user_by_league.get(league_id, {})
        for d in drafts:
            if d.get("status") != "complete":
                continue
            if int(d.get("season", 0)) == origin_season:
                continue  # startup draft
            settings = d.get("settings") or {}
            teams = int(settings.get("teams") or len(r2u) or 1)
            for pk in picks_by_draft_id.get(d["draft_id"], []):
                player_id = pk.get("player_id")
                if not player_id:
                    continue
                drafter = pk.get("picked_by") or r2u.get(pk.get("roster_id"))
                if not drafter:
                    continue
                out.append(DraftedPick(
                    draft_id=d["draft_id"], round=int(pk["round"]),
                    slot=int(pk["draft_slot"]), picks_in_round=teams,
                    player_id=player_id, drafter_id=drafter))
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `./.venv/bin/python -m pytest tests/test_draft_signals.py -k build_rookie -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/draft_signals.py tests/test_draft_signals.py
git commit -m "feat(engine): build_rookie_picks — normalize rookie drafts, drop startup"
```

---

## Task 4: `draft_skill` (vs-tier, KTC+production blend, shrinkage)

**Files:**
- Modify: `src/sleeper_dynasty/engine/draft_signals.py`
- Test: `tests/test_draft_signals.py` (append)

- [ ] **Step 1: Write the failing test (append)**

```python
from sleeper_dynasty.engine.draft_signals import draft_skill


def _pick(draft, rnd, slot, teams, pid, who):
    return DraftedPick(draft_id=draft, round=rnd, slot=slot, picks_in_round=teams,
                       player_id=pid, drafter_id=who)


def test_draft_skill_rewards_beating_the_tier():
    # One draft, round 1, 6 teams -> tiers early(1-2)/mid(3-4)/late(5-6).
    # uA has the late-tier steal (high KTC+prod); uB has an early bust.
    picks = [
        _pick("d", 1, 1, 6, "bust", "uB"),     # early tier, low outcome
        _pick("d", 1, 2, 6, "ok1", "uC"),
        _pick("d", 1, 3, 6, "ok2", "uC"),
        _pick("d", 1, 4, 6, "ok3", "uC"),
        _pick("d", 1, 5, 6, "steal", "uA"),    # late tier, high outcome
        _pick("d", 1, 6, 6, "ok4", "uC"),
    ]
    ktc = {"steal": 9000, "bust": 100, "ok1": 3000, "ok2": 3000, "ok3": 3000, "ok4": 3000}
    prod = {"steal": 1800, "bust": 0, "ok1": 600, "ok2": 600, "ok3": 600, "ok4": 600}
    sk = draft_skill(picks=picks, ktc_by_player=ktc, production_by_player=prod)
    assert sk["uA"] > 0          # beat the late tier
    assert sk["uB"] < 0          # below the early tier
    assert sk["uA"] > sk["uB"]


def test_draft_skill_shrinks_small_samples():
    # Identical per-pick skill, but uA made 1 pick and uB made 6: uB less shrunk.
    picks = [_pick("d", 1, 1, 2, "p1", "uA"), _pick("d", 1, 2, 2, "p2", "uB")]
    ktc = {"p1": 5000, "p2": 1000}
    prod = {"p1": 1000, "p2": 200}
    sk = draft_skill(picks=picks, ktc_by_player=ktc, production_by_player=prod, shrink_k=3.0)
    # uA above tier (its round-2-team group mean), uB below; both shrunk by /(1+3).
    assert sk["uA"] > 0 and sk["uB"] < 0


def test_draft_skill_empty_is_empty():
    assert draft_skill(picks=[], ktc_by_player={}, production_by_player={}) == {}
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_draft_signals.py -k draft_skill -q`
Expected: FAIL with `ImportError: cannot import name 'draft_skill'`.

- [ ] **Step 3: Implement (append to draft_signals.py)**

```python
def _zscores(vals: list[float]) -> list[float]:
    n = len(vals)
    if n == 0:
        return []
    mean = sum(vals) / n
    sd = (sum((x - mean) ** 2 for x in vals) / n) ** 0.5
    return [0.0 if sd == 0 else (x - mean) / sd for x in vals]


def _tier(slot: int, picks_in_round: int) -> int:
    return min(2, (slot - 1) * 3 // max(1, picks_in_round))


def draft_skill(
    *,
    picks: list[DraftedPick],
    ktc_by_player: dict[str, float],
    production_by_player: dict[str, float],
    shrink_k: float = 3.0,
) -> dict[str, float]:
    """Per-owner drafting skill: each rookie pick's blended outcome minus the
    average outcome of its (draft, round, tier) peers, averaged over the owner's
    picks with small-sample shrinkage. Owners with no picks are absent."""
    if not picks:
        return {}
    zk = _zscores([float(ktc_by_player.get(p.player_id, 0.0)) for p in picks])
    zp = _zscores([float(production_by_player.get(p.player_id, 0.0)) for p in picks])
    outcome = [0.5 * zk[i] + 0.5 * zp[i] for i in range(len(picks))]

    tier_groups: dict[tuple, list[int]] = defaultdict(list)
    round_groups: dict[tuple, list[int]] = defaultdict(list)
    for i, p in enumerate(picks):
        tier_groups[(p.draft_id, p.round, _tier(p.slot, p.picks_in_round))].append(i)
        round_groups[(p.draft_id, p.round)].append(i)

    tot: dict[str, float] = defaultdict(float)
    cnt: dict[str, int] = defaultdict(int)
    for i, p in enumerate(picks):
        g = tier_groups[(p.draft_id, p.round, _tier(p.slot, p.picks_in_round))]
        idxs = g if len(g) >= 2 else round_groups[(p.draft_id, p.round)]
        exp = sum(outcome[j] for j in idxs) / len(idxs)
        tot[p.drafter_id] += outcome[i] - exp
        cnt[p.drafter_id] += 1
    return {uid: tot[uid] / (cnt[uid] + shrink_k) for uid in tot}
```

- [ ] **Step 4: Run to verify it passes**

Run: `./.venv/bin/python -m pytest tests/test_draft_signals.py -q`
Expected: PASS (all draft_signals tests).

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/draft_signals.py tests/test_draft_signals.py
git commit -m "feat(engine): draft_skill — outcome vs slot-tier, shrunk per owner"
```

---

## Task 5: Wire both signals into `compute_rating_signals`

**Files:**
- Modify: `api/app/services/rating_signals.py`
- Test: `api/tests/test_rating_signals_draft.py`

- [ ] **Step 1: Write the failing test**

```python
# api/tests/test_rating_signals_draft.py
from app.services.rating_signals import compute_rating_signals
from sleeper_dynasty.engine.draft_signals import DraftedPick
from sleeper_dynasty.models.league import DraftPick


class _KTC:
    def __init__(self, v): self.superflex_value = v; self.one_qb_value = v


def _supporting():
    return {
        "matchups": {
            ("L", 1, 1): {"players_points": {"win": 200.0, "bust": 5.0}},
            ("L", 1, 2): {"players_points": {"mid": 90.0}},
        },
        "roster_to_user_by_league": {"L": {1: "uA", 2: "uB"}},
        "league_season_by_id": {"L": 2026},
        "playoff_week_start_by_league": {"L": 15},
        "winners_bracket_by_league": {"L": []},
        "num_playoff_teams_by_league": {"L": 0},
        "ktc_by_player_id": {"win": _KTC(9000), "bust": _KTC(100), "mid": _KTC(3000)},
        "player_ages": {},
        "owners": {"uA": {}, "uB": {}},
        "pick_value_table": {(2027, 1): _KTC(1000), (2027, 2): _KTC(400)},
    }


def test_draft_capital_is_live_and_reflects_holdings():
    # uA (roster 1) acquired uB's 2027 1st.
    tp = [DraftPick(season=2027, round=1, original_owner_id=2, current_owner_id=1)]
    _, outlook = compute_rating_signals(
        _supporting(), current_holders={}, traded_picks=tp, rookie_picks=[],
        num_draft_rounds=2)
    assert outlook["uA"]["draft_capital"] > outlook["uB"]["draft_capital"]
    assert outlook["uA"]["draft_capital"] > 0


def test_draft_skill_signal_present_and_separates():
    picks = [
        DraftedPick("d", 1, 1, 2, "win", "uA"),   # early tier, big outcome
        DraftedPick("d", 1, 2, 2, "bust", "uB"),  # late tier, low outcome
    ]
    _, outlook = compute_rating_signals(
        _supporting(), current_holders={}, traded_picks=[], rookie_picks=picks,
        num_draft_rounds=2)
    assert "draft_skill" in outlook["uA"]
    assert outlook["uA"]["draft_skill"] >= outlook["uB"]["draft_skill"]


def test_skill_zero_and_capital_equal_without_inputs():
    # No rookie picks -> draft_skill 0 for everyone. No trades -> every roster
    # still holds its identical default slate, so draft_capital is equal (and
    # non-zero), not absent.
    _, outlook = compute_rating_signals(_supporting(), current_holders={})
    assert outlook["uA"]["draft_skill"] == 0.0
    assert outlook["uB"]["draft_skill"] == 0.0
    assert outlook["uA"]["draft_capital"] == outlook["uB"]["draft_capital"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd api && ./.venv/bin/python -m pytest tests/test_rating_signals_draft.py -q`
Expected: FAIL — `compute_rating_signals` has no `traded_picks`/`rookie_picks` params, or `draft_skill` key missing.

- [ ] **Step 3: Implement**

In `api/app/services/rating_signals.py`, add imports near the top (after the existing engine imports):

```python
from sleeper_dynasty.engine.draft_signals import (
    DraftedPick, draft_skill, pick_holdings_value,
)
```

Change the signature:

```python
def compute_rating_signals(
    supporting: dict, current_holders: dict[str, str],
    *,
    traded_picks: list | None = None,
    rookie_picks: list[DraftedPick] | None = None,
    num_draft_rounds: int = 4,
) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, float]]]:
```

Then, after the existing `roster_value` / `age_sum` accumulation loop (just before the `olsig` build), insert:

```python
    # --- Draft capital: KTC value of future picks held (current league). ---
    current_league = max(season_by_league, key=lambda lg: season_by_league[lg]) \
        if season_by_league else None
    r2u_current = r2u_by_league.get(current_league, {}) if current_league else {}
    current_season = max((int(s) for s in season_by_league.values()), default=0)
    outlook_seasons = [current_season + 1, current_season + 2, current_season + 3]
    pick_values = {
        k: _ktc_value(v) for k, v in (supporting.get("pick_value_table") or {}).items()
    }
    holdings = pick_holdings_value(
        traded_picks=traded_picks or [], roster_ids=list(r2u_current),
        seasons=outlook_seasons, num_rounds=num_draft_rounds, pick_values=pick_values)
    draft_capital_by_uid: dict[str, float] = {}
    for rid, dval in holdings.items():
        uid = r2u_current.get(rid)
        if uid:
            draft_capital_by_uid[uid] = draft_capital_by_uid.get(uid, 0.0) + dval

    # --- Draft skill: how past rookie picks panned out vs their slot tier. ---
    production_by_player: dict[str, float] = {}
    for entry in matchups.values():
        for pid, pts in (entry.get("players_points") or {}).items():
            production_by_player[pid] = production_by_player.get(pid, 0.0) + float(pts)
    ktc_floats = {pid: _ktc_value(v) for pid, v in ktc.items()}
    draft_skill_by_uid = draft_skill(
        picks=rookie_picks or [], ktc_by_player=ktc_floats,
        production_by_player=production_by_player)
```

Finally, change the `olsig` build to emit both:

```python
    olsig: dict[str, dict[str, float]] = {}
    for u in roster_value:
        avg_age = age_sum[u] / age_n[u] if age_n[u] else 0.0
        olsig[u] = {
            "roster_value": roster_value[u],
            "draft_capital": draft_capital_by_uid.get(u, 0.0),
            "draft_skill": draft_skill_by_uid.get(u, 0.0),
            "youth": -avg_age,
        }
```

Update the module docstring (lines 5-6) to drop the "deferred / 0 for now" note:
`signals. Draft capital + draft skill are computed from traded picks and rookie-draft results.`

- [ ] **Step 4: Run to verify it passes**

Run: `cd api && ./.venv/bin/python -m pytest tests/test_rating_signals_draft.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the existing rating-signals tests**

Run: `cd api && ./.venv/bin/python -m pytest tests/ -k rating_signal -q`
Expected: PASS (no regressions; existing callers pass no draft inputs → signals 0).

- [ ] **Step 6: Commit**

```bash
git add api/app/services/rating_signals.py api/tests/test_rating_signals_draft.py
git commit -m "feat(api): live draft_capital + draft_skill in rating signals"
```

---

## Task 6: Fetch draft inputs during refresh

**Files:**
- Modify: `api/app/services/grader.py` (near the current-roster fetch ~line 175, and the `compute_rating_signals` call ~line 204)

- [ ] **Step 1: Add the fetch + thread-through**

In `api/app/services/grader.py`, immediately AFTER the existing `current_holders` / `current_rosters` try/except block (the one ending around line 182), insert:

```python
        traded_picks: list = []
        rookie_picks: list = []
        num_draft_rounds = 4
        try:
            from sleeper_dynasty.engine.draft_signals import build_rookie_picks
            traded_picks = await client.get_traded_picks(current_league_id)
            origin_season = min(lg.season for lg in chain)
            drafts_by_league: dict[str, list] = {}
            picks_by_draft_id: dict[str, list] = {}
            latest_rookie: tuple[int, int] | None = None  # (season, rounds)
            for lg in chain:
                drafts = await client.get_drafts(lg.league_id)
                drafts_by_league[lg.league_id] = drafts
                for d in drafts:
                    if d.get("status") != "complete":
                        continue
                    if int(d.get("season", 0)) == origin_season:
                        continue
                    picks_by_draft_id[d["draft_id"]] = \
                        await client.get_draft_picks(d["draft_id"])
                    rounds = int((d.get("settings") or {}).get("rounds", 4))
                    season = int(d.get("season", 0))
                    if latest_rookie is None or season > latest_rookie[0]:
                        latest_rookie = (season, rounds)
            rookie_picks = build_rookie_picks(
                drafts_by_league=drafts_by_league,
                picks_by_draft_id=picks_by_draft_id,
                origin_season=origin_season,
                roster_to_user_by_league=supporting["roster_to_user_by_league"])
            if latest_rookie is not None:
                num_draft_rounds = latest_rookie[1]
        except Exception:
            log.exception("draft inputs fetch failed; draft signals will be 0")
```

Then change the `compute_rating_signals` call (~line 204) from:

```python
            outcome_signals, outlook_signals = compute_rating_signals(
                supporting, current_holders)
```

to:

```python
            outcome_signals, outlook_signals = compute_rating_signals(
                supporting, current_holders,
                traded_picks=traded_picks, rookie_picks=rookie_picks,
                num_draft_rounds=num_draft_rounds)
```

- [ ] **Step 2: Run the api suite (no regressions; grader stage is import-guarded)**

Run: `cd api && ./.venv/bin/python -m pytest tests/ -q`
Expected: PASS (all). The grader's existing tests don't fetch real drafts; the new block is best-effort and leaves `rookie_picks`/`traded_picks` empty on any failure.

- [ ] **Step 3: Commit**

```bash
git add api/app/services/grader.py
git commit -m "feat(api): fetch traded picks + rookie drafts during refresh"
```

---

## Task 7: Blurb coupling (facts flag, label, persona)

**Files:**
- Modify: `src/sleeper_dynasty/engine/gm_rating_blurb.py`
- Modify: `src/sleeper_dynasty/llm/prompts/gm_rating_blurb_persona.md`
- Test: `tests/test_gm_rating_blurb_facts.py`

- [ ] **Step 1: Update the facts test for the now-live flag**

In `tests/test_gm_rating_blurb_facts.py`, in `test_build_facts_selects_top_and_worst_signals`, change:

```python
    assert f.draft_capital_counted is False
```

to:

```python
    assert f.draft_capital_counted is True
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_gm_rating_blurb_facts.py -q`
Expected: FAIL (`draft_capital_counted` is still False).

- [ ] **Step 3: Update the facts builder + label**

In `src/sleeper_dynasty/engine/gm_rating_blurb.py`:

Add `draft_skill` to `SIGNAL_LABELS` (in the outlook group):

```python
    "roster_value": "Roster Value", "draft_capital": "Draft Capital",
    "draft_skill": "Draft Skill", "youth": "Youth",
```

Change the `build_owner_rating_facts` return so `draft_capital_counted=True`:

```python
        draft_capital_counted=True,
```

- [ ] **Step 4: Run to verify it passes**

Run: `./.venv/bin/python -m pytest tests/test_gm_rating_blurb_facts.py -q`
Expected: PASS.

- [ ] **Step 5: Update the persona to allow draft mentions**

In `src/sleeper_dynasty/llm/prompts/gm_rating_blurb_persona.md`:

Remove the hard rule:
```
- If `draft_capital_counted` is false, do NOT claim draft capital helps or hurts
  the grade; it is not counted yet.
```

In the "Close with the forward look from the Outlook pillar" bullet, change it to:
```
- Close with the forward look from the Outlook pillar — roster value, youth,
  how much future draft capital they hold (pick-rich or pick-poor), and whether
  they have drafted well or badly (Draft Skill): a win-now team, a young riser,
  a roster aging out, a stockpiler, a sharp or shaky drafter, etc.
```

- [ ] **Step 6: Commit**

```bash
git add src/sleeper_dynasty/engine/gm_rating_blurb.py src/sleeper_dynasty/llm/prompts/gm_rating_blurb_persona.md tests/test_gm_rating_blurb_facts.py
git commit -m "feat(llm): blurb counts draft capital + skill in the forward look"
```

---

## Task 8: Frontend — Draft Skill label + help, update Draft Capital help

**Files:**
- Modify: `web/components/Leaderboard.tsx`

- [ ] **Step 1: Add the label**

In `web/components/Leaderboard.tsx`, in `SIGNAL_LABELS`, add `draft_skill`:

```tsx
  roster_value: "Roster Value", draft_capital: "Draft Capital",
  draft_skill: "Draft Skill", youth: "Youth",
```

- [ ] **Step 2: Update the help copy**

In `SIGNAL_HELP`, replace the `draft_capital` entry and add `draft_skill`:

```tsx
  draft_capital:
    "Market value of the future rookie picks you hold across the next three drafts, by KTC.",
  draft_skill:
    "How your past rookie picks panned out — each pick's player value (market + production) vs what its draft slot tier usually returns. Rookie drafts only; the startup draft doesn't count.",
```

- [ ] **Step 3: Typecheck**

Run: `cd web && npx tsc --noEmit 2>&1 | grep -v "dev/loading"`
Expected: no errors from `components/Leaderboard.tsx`.

- [ ] **Step 4: Commit**

```bash
git add web/components/Leaderboard.tsx
git commit -m "feat(web): Draft Skill row + help; Draft Capital help now live"
```

---

## Task 9: Verify + deploy

**Files:** none.

- [ ] **Step 1: Full suites green**

Run: `./.venv/bin/python -m pytest tests/ -q`
Run: `cd api && ./.venv/bin/python -m pytest tests/ -q`
Run: `cd web && npx tsc --noEmit 2>&1 | grep -v "dev/loading"`
Expected: engine + api pass; tsc clean.

- [ ] **Step 2: Merge to main + deploy both services**

Per `superpowers:finishing-a-development-branch` (merge to main), then `railway-deploy`:

```bash
railway up --service api --detach -m "draft capital live + draft skill"
railway up --service web --detach -m "draft capital live + draft skill"
```

Poll each `railway deployment list --service <svc> --limit 1 --json` → `.status` SUCCESS.

- [ ] **Step 3: Trigger a prod refresh and verify the signals are live**

```bash
curl -sN "https://web-production-f949.up.railway.app/api/league/9000000000000000001/refresh" >/dev/null
```

Then poll the leaderboard and confirm Draft Capital and Draft Skill are no longer 0 for everyone, and ratings shifted:

```bash
curl -s "https://web-production-f949.up.railway.app/api/league/9000000000000000001/leaderboard?year=all" \
  | python3 -c "import sys,json; r=json.load(sys.stdin)['rows'][0]; ol=r['pillars']['outlook']['signals']; print({k: ol[k]['contribution'] for k in ('roster_value','draft_capital','draft_skill','youth')})"
```

Expected: non-zero `draft_capital` and `draft_skill` contributions; the panel's Draft Capital / Draft Skill rows show bars; blurbs (regenerated) may reference pick stock / drafting.

- [ ] **Step 4: Visual check**

Drive `https://web-production-f949.up.railway.app/league/9000000000000000001?tab=gm`, expand a row, confirm the new Draft Skill row + `?` help render and Draft Capital is no longer 0 (reuse the prod Playwright harness).

---

## Notes for the implementer

- **Never break refresh.** The draft-fetch block in grader.py is best-effort
  (try/except → empty inputs → both signals 0). `compute_rating_signals` and the
  blurb stage are already try/except-wrapped in grader.py.
- **DRY label maps:** `SIGNAL_LABELS` exists in three places that must agree —
  `engine/gm_rating_blurb.py`, `web/components/Leaderboard.tsx`, and (implicitly)
  the signal keys in `engine/gm_rating.py`. All three get `draft_skill` here.
- **Cost:** the prod refresh re-z-scores ratings (Outlook shifts) which changes
  blurb facts → blurbs regenerate (~Opus calls, incremental-skip as before).
- **Outlook seasons** derive from the latest league season at refresh time, so
  this stays correct past 2026 with no code change.
```
