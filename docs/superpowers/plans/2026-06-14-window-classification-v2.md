> _Historical doc — paths/names have changed. Repo is now `Code Apps/public-dynasty` (GitHub `tkeefe66/public-dynasty-app`), Railway project **shimmering-nature**, live at https://ffbdynasty.com. Ignore stale refs to `sleeper-dynasty` / `sleeper-trade-grader` / `web-production-f949`._

# Window Classification v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 3-signal decision tree (KTC rank, avg age, draft capital) with a two-axis Strength × Trajectory framework that incorporates draft skill and competitive history.

**Architecture:** Two new pure functions (`compute_strength_score`, `compute_trajectory_score`) in `dynasty.py` feed an updated `classify_window`. `build_dynasty_outlook` gains optional params and computes `youth_quality_pct` internally. Scores are stored on `DynastyOutlook` and threaded through `build_outlooks_by_owner` → `grader.py`. YoY delta is back-filled by `refresh_service.py` after `season_ratings` are computed.

**Tech Stack:** Python/dataclasses, pytest

**Test commands:**
- Engine tests: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && pytest tests/ -v`
- API tests: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && make test-api`

---

## File Map

| File | Change |
|---|---|
| `src/sleeper_dynasty/engine/dynasty.py` | Add `strength_score`/`trajectory_score` to `DynastyOutlook`; add `compute_strength_score`, `compute_trajectory_score`; update `classify_window`; update `build_dynasty_outlook` |
| `src/sleeper_dynasty/engine/outlook_build.py` | Export scores in `outlook_to_dict`; add 4 new optional params to `build_outlooks_by_owner`; pass `ktc_value_by_player` through |
| `api/app/services/grader.py` | Extract and pass `draft_skill_by_uid`, `playoff_rate_by_uid`, `outlook_signals_by_uid` to `build_outlooks_by_owner` |
| `api/app/services/refresh_service.py` | Back-fill YoY delta into `dynasty_outlooks` after `season_ratings` are computed |
| `tests/test_dynasty.py` | Update 3 old `classify_window` tests; add score function tests; add `build_dynasty_outlook` tests |
| `tests/test_outlook_build.py` | Assert `strength_score` and `trajectory_score` in serialized dict |
| `web/app/methodology/page.tsx` | Add Window, Draft Capital, Grade explanations |

---

## Task 1: Score functions + updated `DynastyOutlook` + updated `classify_window`

**Files:**
- Modify: `src/sleeper_dynasty/engine/dynasty.py`
- Modify: `tests/test_dynasty.py`

- [ ] **Step 1: Add `strength_score` and `trajectory_score` to `DynastyOutlook`**

In `src/sleeper_dynasty/engine/dynasty.py`, find the `DynastyOutlook` dataclass (around line 81) and add two default fields after `trajectory`:

```python
@dataclass
class DynastyOutlook:
    """Complete dynasty outlook for a single roster."""

    window: str
    age_profile: AgeProfile
    draft_capital: DraftCapital
    draft_needs: list[DraftNeed]
    trajectory: str
    strength_score: float = 0.0    # 0–100 Strength axis
    trajectory_score: float = 0.0  # 0–100 Trajectory axis
```

- [ ] **Step 2: Add `compute_strength_score` and `compute_trajectory_score`**

Add both functions immediately before `classify_window`:

```python
def compute_strength_score(roster_rank_pct: float, playoff_rate: float) -> float:
    """Strength axis (0–100): how good is the team right now?

    Args:
        roster_rank_pct: KTC value percentile (0.0 = best, 1.0 = worst).
        playoff_rate: Fraction of seasons made playoffs (0.0–1.0).
    """
    return 0.60 * (1 - roster_rank_pct) * 100 + 0.40 * playoff_rate * 100


def compute_trajectory_score(
    youth_quality_pct: float,
    draft_skill_z: float,
    draft_capital_pct_rank: float,
    yoy_rating_delta: float,
) -> float:
    """Trajectory axis (0–100): which way is the team headed?

    Args:
        youth_quality_pct: Fraction of KTC held by players ≤25 (0.0–1.0).
        draft_skill_z: League z-score of draft skill (typically −2 to +2).
        draft_capital_pct_rank: Capital percentile rank (0.0=most, 1.0=least).
        yoy_rating_delta: GM rating change vs prior season (−300 to +300 typical).
    """
    youth_score = min(100.0, youth_quality_pct * 250)             # 40% young = 100
    skill_score = max(0.0, min(100.0, 50 + draft_skill_z * 25))   # z=0 → 50
    capital_score = (1 - draft_capital_pct_rank) * 100
    yoy_score = max(0.0, min(100.0, (yoy_rating_delta + 200) / 4))  # ±200 → 0–100
    return (
        0.35 * youth_score
        + 0.30 * skill_score
        + 0.25 * capital_score
        + 0.10 * yoy_score
    )
```

- [ ] **Step 3: Replace `classify_window` with two-axis version**

Find the current `classify_window` function and replace it entirely:

```python
def classify_window(
    strength: float,
    trajectory: float,
    draft_capital_status: str,
) -> str:
    """Classify a team's competitive window from Strength × Trajectory scores.

    Args:
        strength: Strength score 0–100 (≥60 = strong, <40 = weak).
        trajectory: Trajectory score 0–100 (≥50 = positive, <40 = declining).
        draft_capital_status: "pick-rich" | "neutral" | "pick-poor".

    Returns:
        One of: "Competing now", "Ascending", "Peaking", "Descending", "Rebuilding".
    """
    if strength >= 60:
        return "Competing now" if trajectory >= 50 else "Peaking"
    if strength < 40:
        if trajectory >= 55:
            return "Ascending"
        return "Rebuilding" if draft_capital_status == "pick-rich" else "Descending"
    # Middle zone 40–60: trajectory decides
    if trajectory >= 60:
        return "Ascending"
    if trajectory < 40:
        return "Descending"
    return "Ascending"  # default optimistic for mid-pack
```

- [ ] **Step 4: Update `tests/test_dynasty.py` — imports, replace old tests, add new ones**

Update the import at the top of `tests/test_dynasty.py`:

```python
from sleeper_dynasty.engine.dynasty import (
    analyze_age_profile,
    analyze_draft_capital,
    classify_window,
    compute_strength_score,
    compute_trajectory_score,
    build_dynasty_outlook,
    DynastyOutlook,
    AgeProfile,
    DraftCapital,
)
```

Replace the three old `classify_window` tests and add new score tests:

```python
# --- compute_strength_score ---

def test_strength_score_top_roster_proven_winner():
    assert compute_strength_score(roster_rank_pct=0.0, playoff_rate=1.0) == 100.0

def test_strength_score_worst_roster_no_playoffs():
    assert compute_strength_score(roster_rank_pct=1.0, playoff_rate=0.0) == 0.0

def test_strength_score_middle():
    score = compute_strength_score(roster_rank_pct=0.5, playoff_rate=0.5)
    assert abs(score - 50.0) < 0.01

# --- compute_trajectory_score ---

def test_trajectory_score_all_positive():
    score = compute_trajectory_score(
        youth_quality_pct=0.5, draft_skill_z=2.0,
        draft_capital_pct_rank=0.0, yoy_rating_delta=200.0)
    assert score > 90.0

def test_trajectory_score_all_negative():
    score = compute_trajectory_score(
        youth_quality_pct=0.0, draft_skill_z=-2.0,
        draft_capital_pct_rank=1.0, yoy_rating_delta=-200.0)
    assert score < 15.0

def test_trajectory_score_neutral_draft_z_zero():
    # z=0 → skill_score=50; capital_rank=0.5 → capital_score=50; yoy=0 → yoy_score=50
    # youth=0; result = 0 + 0.30*50 + 0.25*50 + 0.10*50 = 32.5
    score = compute_trajectory_score(
        youth_quality_pct=0.0, draft_skill_z=0.0,
        draft_capital_pct_rank=0.5, yoy_rating_delta=0.0)
    assert abs(score - 32.5) < 0.1

# --- classify_window ---

def test_classify_window_competing():
    assert classify_window(72.0, 55.0, "neutral") == "Competing now"

def test_classify_window_peaking():
    assert classify_window(65.0, 42.0, "pick-poor") == "Peaking"

def test_classify_window_rebuilding():
    assert classify_window(25.0, 35.0, "pick-rich") == "Rebuilding"

def test_classify_window_descending():
    assert classify_window(20.0, 30.0, "pick-poor") == "Descending"

def test_classify_window_ascending_low_strength():
    assert classify_window(20.0, 60.0, "neutral") == "Ascending"

def test_classify_window_ascending_middle():
    assert classify_window(50.0, 65.0, "neutral") == "Ascending"
```

- [ ] **Step 5: Run engine tests**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && pytest tests/test_dynasty.py -v 2>&1 | tail -20
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/sleeper_dynasty/engine/dynasty.py tests/test_dynasty.py
git commit -m "feat(engine): two-axis Window — compute_strength_score, compute_trajectory_score, updated classify_window + DynastyOutlook"
```

---

## Task 2: Update `build_dynasty_outlook` with youth quality and score computation

**Files:**
- Modify: `src/sleeper_dynasty/engine/dynasty.py`
- Modify: `tests/test_dynasty.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_dynasty.py`:

```python
def test_build_dynasty_outlook_stores_scores():
    """build_dynasty_outlook populates strength_score and trajectory_score."""
    from datetime import date
    from sleeper_dynasty.models.league import Roster
    players = [
        _make_player("rb1", "Young RB", "RB", 2002),  # age 24
        _make_player("wr1", "Old WR", "WR", 1994),    # age 32
    ]
    roster = Roster(
        roster_id=1, owner_id="u1", owner_name="Test",
        players=["rb1", "wr1"], wins=3, losses=3, ties=0,
        points_for=1200.0, points_against=1100.0,
    )
    ktc = {"rb1": 6000.0, "wr1": 2000.0}
    outlook = build_dynasty_outlook(
        roster=roster, roster_players=players, traded_picks=[],
        projected_rank_pct=0.2,          # top 20%
        position_rankings={}, total_rosters=10,
        ktc_value_by_player=ktc,
        draft_skill=1.0,                 # above average
        playoff_rate=0.8,                # 80% playoff rate
        yoy_rating_delta=100.0,
        draft_capital_pct_rank=0.3,
    )
    # strength = 0.60*(1−0.2)*100 + 0.40*0.8*100 = 48+32 = 80
    assert abs(outlook.strength_score - 80.0) < 1.0
    assert outlook.trajectory_score > 0.0
    assert outlook.window in ("Competing now", "Peaking")


def test_build_dynasty_outlook_backward_compat():
    """Old callers without new params still get a valid outlook."""
    from sleeper_dynasty.models.league import Roster
    roster = Roster(
        roster_id=1, owner_id="u1", owner_name="Test",
        players=[], wins=0, losses=0, ties=0,
        points_for=0.0, points_against=0.0,
    )
    outlook = build_dynasty_outlook(
        roster=roster, roster_players=[], traded_picks=[],
        projected_rank_pct=0.5, position_rankings={}, total_rosters=10,
    )
    assert outlook.window in ("Competing now", "Ascending", "Peaking", "Descending", "Rebuilding")
    assert isinstance(outlook.strength_score, float)
    assert isinstance(outlook.trajectory_score, float)
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && pytest tests/test_dynasty.py::test_build_dynasty_outlook_stores_scores -v 2>&1 | tail -10
```

Expected: FAIL — TypeError (unexpected kwargs).

- [ ] **Step 3: Update `build_dynasty_outlook` signature**

Add 5 new optional params to `build_dynasty_outlook`:

```python
def build_dynasty_outlook(
    roster: Roster,
    roster_players: list[Player],
    traded_picks: list[DraftPick],
    projected_rank_pct: float,
    position_rankings: dict[str, list[str]],
    total_rosters: int,
    num_rounds: int = 4,
    # New optional params for two-axis scoring:
    ktc_value_by_player: dict[str, float] | None = None,
    draft_skill: float = 0.0,
    playoff_rate: float = 0.0,
    yoy_rating_delta: float = 0.0,
    draft_capital_pct_rank: float = 0.5,
) -> DynastyOutlook:
```

- [ ] **Step 4: Compute `youth_quality_pct` and scores inside `build_dynasty_outlook`**

After the `age_profile = analyze_age_profile(roster_players)` and `draft_capital = analyze_draft_capital(...)` lines, add:

```python
    # Youth quality: fraction of KTC value in players ≤ CORE_YOUNG_MAX_AGE (25).
    youth_quality_pct = 0.0
    if ktc_value_by_player:
        ref = date.today()
        total_ktc = sum(
            ktc_value_by_player.get(p.player_id, 0.0)
            for p in roster_players
            if p.position not in _SKIP_POSITIONS
        )
        young_ktc = sum(
            ktc_value_by_player.get(p.player_id, 0.0)
            for p in roster_players
            if p.position not in _SKIP_POSITIONS
            and p.age(as_of=ref) is not None
            and p.age(as_of=ref) <= CORE_YOUNG_MAX_AGE
        )
        if total_ktc > 0:
            youth_quality_pct = young_ktc / total_ktc

    strength = compute_strength_score(
        roster_rank_pct=projected_rank_pct,
        playoff_rate=playoff_rate,
    )
    trajectory = compute_trajectory_score(
        youth_quality_pct=youth_quality_pct,
        draft_skill_z=draft_skill,
        draft_capital_pct_rank=draft_capital_pct_rank,
        yoy_rating_delta=yoy_rating_delta,
    )
    window = classify_window(
        strength=strength,
        trajectory=trajectory,
        draft_capital_status=draft_capital.status,
    )
```

Also add the `date` import at the top of the file if not already present:
```python
from datetime import date
```

- [ ] **Step 5: Find the OLD `classify_window` call and `DynastyOutlook` constructor inside `build_dynasty_outlook`**

The old code block (around line 552) currently reads:
```python
    window = classify_window(
        projected_rank_pct=projected_rank_pct,
        avg_age=age_profile.overall_avg_age,
        draft_capital_status=draft_capital.status,
    )
```

Delete these 4 lines (they're replaced by the new block added in Step 4 above).

Also rename the existing `trajectory = _describe_trajectory(...)` line to `trajectory_text = _describe_trajectory(...)` to avoid name collision with the new `trajectory` float.

Update the `DynastyOutlook(...)` constructor:

```python
    outlook = DynastyOutlook(
        window=window,
        age_profile=age_profile,
        draft_capital=draft_capital,
        draft_needs=draft_needs,
        trajectory=trajectory_text,
        strength_score=round(strength, 1),
        trajectory_score=round(trajectory, 1),
    )
```

- [ ] **Step 6: Run tests**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && pytest tests/test_dynasty.py -v 2>&1 | tail -15
```

Expected: all passing.

- [ ] **Step 7: Commit**

```bash
git add src/sleeper_dynasty/engine/dynasty.py tests/test_dynasty.py
git commit -m "feat(engine): build_dynasty_outlook computes youth_quality_pct and stores two-axis scores"
```

---

## Task 3: Thread scores through `outlook_to_dict` and `build_outlooks_by_owner`

**Files:**
- Modify: `src/sleeper_dynasty/engine/outlook_build.py`
- Modify: `tests/test_outlook_build.py`

- [ ] **Step 1: Export scores in `outlook_to_dict`**

In `src/sleeper_dynasty/engine/outlook_build.py`, find `outlook_to_dict` and add `strength_score` and `trajectory_score` immediately after `"trajectory"`:

```python
    return {
        "window": outlook.window,
        "trajectory": outlook.trajectory,
        "strength_score": outlook.strength_score,
        "trajectory_score": outlook.trajectory_score,
        "age_profile": { ... },   # unchanged
        ...
    }
```

- [ ] **Step 2: Add 4 new optional params to `build_outlooks_by_owner`**

Replace the current function signature and body:

```python
def build_outlooks_by_owner(
    *,
    rosters: list[Roster],
    players: dict[str, Player],
    traded_picks: list[DraftPick],
    positions: dict[str, str],
    ktc_value_by_player: dict[str, float],
    roster_to_user: dict[int, str],
    total_rosters: int,
    num_rounds: int = 4,
    # New optional params for two-axis scoring:
    draft_skill_by_uid: dict[str, float] | None = None,
    playoff_rate_by_uid: dict[str, float] | None = None,
    yoy_rating_by_uid: dict[str, float] | None = None,
    outlook_signals_by_uid: dict[str, dict[str, float]] | None = None,
) -> dict[str, DynastyOutlook]:
    """Build a DynastyOutlook per current owner uid (offseason-safe).

    position_rankings come from KTC; projected_rank_pct from roster-value rank.
    Optional signal params enable two-axis Strength × Trajectory scoring.
    """
    rankings = ktc_position_rankings(rosters, positions, ktc_value_by_player)
    rv_by_roster = {
        r.roster_id: sum(
            ktc_value_by_player.get(pid, 0.0) for pid in (r.players or []))
        for r in rosters
    }
    rank_pct = roster_value_rank_pct(rv_by_roster)

    # Draft capital percentile rank across league (for trajectory score).
    # Rank by outlook_signals["draft_capital"] if provided, else uniform 0.5.
    dc_pct_rank_by_uid: dict[str, float] = {}
    if outlook_signals_by_uid:
        all_uids = [uid for uid in roster_to_user.values() if uid]
        cap_vals = {
            uid: float((outlook_signals_by_uid.get(uid) or {}).get("draft_capital") or 0)
            for uid in all_uids
        }
        sorted_uids = sorted(cap_vals, key=lambda u: cap_vals[u], reverse=True)
        n = len(sorted_uids)
        dc_pct_rank_by_uid = {
            uid: (i / (n - 1)) if n > 1 else 0.5
            for i, uid in enumerate(sorted_uids)
        }

    out: dict[str, DynastyOutlook] = {}
    for r in rosters:
        uid = roster_to_user.get(r.roster_id)
        if not uid:
            continue
        roster_players = [
            players[pid] for pid in (r.players or []) if pid in players]
        out[uid] = build_dynasty_outlook(
            roster=r,
            roster_players=roster_players,
            traded_picks=traded_picks,
            projected_rank_pct=rank_pct.get(r.roster_id, 0.5),
            position_rankings=rankings,
            total_rosters=total_rosters,
            num_rounds=num_rounds,
            ktc_value_by_player=ktc_value_by_player,
            draft_skill=float((draft_skill_by_uid or {}).get(uid) or 0),
            playoff_rate=float((playoff_rate_by_uid or {}).get(uid) or 0),
            yoy_rating_delta=float((yoy_rating_by_uid or {}).get(uid) or 0),
            draft_capital_pct_rank=dc_pct_rank_by_uid.get(uid, 0.5),
        )
    return out
```

- [ ] **Step 3: Add score assertions to `tests/test_outlook_build.py`**

In `test_build_and_serialize_outlook_is_json_safe`, after the existing assertions, add:

```python
    assert "strength_score" in d
    assert "trajectory_score" in d
    assert isinstance(d["strength_score"], float)
    assert isinstance(d["trajectory_score"], float)
    assert 0.0 <= d["strength_score"] <= 100.0
    assert 0.0 <= d["trajectory_score"] <= 100.0
```

- [ ] **Step 4: Run engine tests**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && pytest tests/test_dynasty.py tests/test_outlook_build.py tests/test_gm_signals.py -v 2>&1 | tail -15
```

Expected: all passing. (`test_gm_signals.py` constructs `DynastyOutlook` with old params — the new fields have defaults so no breakage.)

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/outlook_build.py tests/test_outlook_build.py
git commit -m "feat(engine): export strength_score/trajectory_score in outlook_to_dict; thread signals through build_outlooks_by_owner"
```

---

## Task 4: Wire signals through `grader.py` and back-fill YoY in `refresh_service.py`

**Files:**
- Modify: `api/app/services/grader.py`
- Modify: `api/app/services/refresh_service.py`

- [ ] **Step 1: Pass signals into `build_outlooks_by_owner` in `grader.py`**

Find the `build_outlooks_by_owner(...)` call in `api/app/services/grader.py` (around line 324) and replace:

```python
            outlooks = build_outlooks_by_owner(
                rosters=current_rosters, players=players_obj,
                traded_picks=traded_picks, positions=positions,
                ktc_value_by_player=ktc_floats, roster_to_user=r2u_current,
                total_rosters=len(current_rosters),
                num_rounds=num_draft_rounds)
```

With:

```python
            # Extract signals for two-axis Window scoring.
            _draft_skill_by_uid = {
                uid: float((outlook_signals.get(uid) or {}).get("draft_skill") or 0)
                for uid in outcome_signals
            }
            _playoff_rate_by_uid = {
                uid: float((outcome_signals.get(uid) or {}).get("made_playoffs") or 0)
                for uid in outcome_signals
            }
            outlooks = build_outlooks_by_owner(
                rosters=current_rosters, players=players_obj,
                traded_picks=traded_picks, positions=positions,
                ktc_value_by_player=ktc_floats, roster_to_user=r2u_current,
                total_rosters=len(current_rosters),
                num_rounds=num_draft_rounds,
                draft_skill_by_uid=_draft_skill_by_uid,
                playoff_rate_by_uid=_playoff_rate_by_uid,
                yoy_rating_by_uid={},           # back-filled in refresh_service.py
                outlook_signals_by_uid=outlook_signals,
            )
```

- [ ] **Step 2: Back-fill YoY delta in `refresh_service.py`**

In `api/app/services/refresh_service.py`, after `entry.season_ratings = compute_season_ratings(entry)` and before `ChainCache(cache_dir=cache_dir).write(league_id, entry)`, add:

```python
    # Back-fill YoY GM rating delta into dynasty_outlooks Window scores.
    # season_ratings are now available so we can compute real year-over-year change.
    # The trajectory_score was computed with yoy_delta=0 (neutral yoy_score=50).
    # We adjust: remove the neutral yoy contribution and add the real one.
    _sr = entry.season_ratings or {}
    if len(_sr) >= 2:
        from sleeper_dynasty.engine.dynasty import classify_window as _cw
        _s_sorted = sorted(int(k) for k in _sr if k.isdigit())
        _cur_key = str(_s_sorted[-1])
        _prev_key = str(_s_sorted[-2])
        for uid, ol in (entry.dynasty_outlooks or {}).items():
            _cur_r  = (_sr.get(_cur_key)  or {}).get(uid)
            _prev_r = (_sr.get(_prev_key) or {}).get(uid)
            if _cur_r is None or _prev_r is None:
                continue
            delta = float(_cur_r) - float(_prev_r)
            new_yoy = max(0.0, min(100.0, (delta + 200) / 4))
            # Adjust trajectory: remove neutral yoy (50 × 0.10 = 5) add real one
            old_traj = float(ol.get("trajectory_score") or 0)
            new_traj = max(0.0, min(100.0, round(old_traj - 5.0 + new_yoy * 0.10, 1)))
            strength = float(ol.get("strength_score") or 0)
            dc_status = (ol.get("draft_capital") or {}).get("status", "neutral")
            ol["trajectory_score"] = new_traj
            ol["window"] = _cw(
                strength=strength,
                trajectory=new_traj,
                draft_capital_status=dc_status,
            )
```

- [ ] **Step 3: Run full API test suite**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && make test-api 2>&1 | tail -5
```

Expected: all passing.

- [ ] **Step 4: Commit**

```bash
git add api/app/services/grader.py api/app/services/refresh_service.py
git commit -m "feat(grader): pass draft_skill + playoff_rate to build_outlooks_by_owner; back-fill YoY delta in refresh_service"
```

---

## Task 5: Methodology page — add Window, Draft Capital, Grade explanations

**Files:**
- Modify: `web/app/methodology/page.tsx`

- [ ] **Step 1: Add Window, Draft Capital, and Grade to the page**

In `web/app/methodology/page.tsx`, add a new `FRANCHISE_SIGNALS` section after the `METRICS` array and before `PILLARS`. Then render it on the page between the metrics section and the GM Rating section.

Add this constant after `METRICS`:

```tsx
const FRANCHISE_SIGNALS = [
  {
    name: "Window",
    description:
      "Your franchise's dynasty stage, computed from two scores. Strength (60% KTC roster rank + 40% all-time playoff rate) measures how competitive you are right now. Trajectory (35% youth quality — fraction of KTC in players ≤25 — + 30% draft skill + 25% draft capital + 10% year-over-year momentum) measures which direction you're headed. The five stages map from the intersection of those scores.",
    values: "Competing now · Peaking · Ascending · Descending · Rebuilding",
  },
  {
    name: "Draft Capital",
    description:
      "KTC market value of all future rookie picks currently held, tiered by the originating team's current roster strength — weaker teams have earlier picks worth more. Not year-scoped; always reflects today's holdings.",
    formula: "Σ KTC(held future picks, tier-adjusted)",
  },
  {
    name: "Grade",
    description:
      "Letter grade derived from your Trade Value relative to your leaguemates. Every owner's realized Trade Value is z-scored against the league and bucketed. League-relative — a B in one league isn't the same as a B in another.",
    formula: "A ≥ +1.25σ · A− ≥ +0.75σ · B+ ≥ +0.25σ · B ≈ 0 · B− ≥ −0.75σ · C ≥ −1.25σ · D below",
  },
];
```

Add a new section to the JSX, between the metrics list and the GM Rating section:

```tsx
      <section className="mt-14 max-w-3xl border-t border-divider pt-10">
        <h2 className="text-[22px] font-bold tracking-tight">
          Franchise intelligence columns
        </h2>
        <p className="mt-2 text-[14px] text-dim leading-relaxed max-w-xl">
          These columns appear in the Owner Rankings table on the dashboard. Unlike trade metrics, they reflect current roster state and career-long patterns.
        </p>
        <div className="mt-6">
          {FRANCHISE_SIGNALS.map((s, i) => (
            <div
              key={s.name}
              className={`py-6 border-t border-divider grid grid-cols-1 sm:grid-cols-[1fr_auto] gap-3 sm:gap-10 sm:items-start${
                i === FRANCHISE_SIGNALS.length - 1 ? " border-b border-divider" : ""
              }`}
            >
              <div>
                <h3 className="text-[16px] font-bold tracking-tight">{s.name}</h3>
                <p className="mt-1.5 text-[13px] text-dim leading-relaxed">
                  {s.description}
                </p>
              </div>
              {"formula" in s && s.formula ? (
                <div className="self-start font-mono text-[10.5px] bg-surface border border-divider rounded px-3 py-2 text-dim sm:whitespace-nowrap">
                  {s.formula}
                </div>
              ) : "values" in s && s.values ? (
                <div className="self-start font-mono text-[10.5px] bg-surface border border-divider rounded px-3 py-2 text-dim">
                  {s.values}
                </div>
              ) : null}
            </div>
          ))}
        </div>
      </section>
```

- [ ] **Step 2: TypeScript check**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/web" && npx tsc --noEmit 2>&1 | head -5
```

Expected: no errors.

- [ ] **Step 3: Run full test suite**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && make test 2>&1 | tail -5
```

Expected: all passing.

- [ ] **Step 4: Commit and push**

```bash
git add web/app/methodology/page.tsx
git commit -m "feat(methodology): add Window, Draft Capital, Grade explanations for dashboard columns"
git push origin main
```

---

## Task 6: Deploy and force refresh

- [ ] **Step 1: Deploy API**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && railway up --service api --detach -m "feat: Window v2 two-axis classification" 2>&1
```

- [ ] **Step 2: Poll until deployed**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && until railway deployment list --service api --limit 1 --json 2>/dev/null | python3 -c "import sys,json; s=json.load(sys.stdin)[0]['status']; print('api:',s); exit(0 if s in ['SUCCESS','FAILED','CRASHED'] else 1)" 2>/dev/null; do sleep 10; done
```

- [ ] **Step 3: Trigger force refresh to apply new Window scores**

```bash
curl -s -N "https://web-production-f949.up.railway.app/api/league/9000000000000000001/refresh?force=true" | grep -E "stage.*done|error"
```

- [ ] **Step 4: Verify Window scores in API response**

```bash
curl -s "https://web-production-f949.up.railway.app/api/league/9000000000000000001/owner/$(curl -s "https://web-production-f949.up.railway.app/api/league/9000000000000000001" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['standings'][0]['user_id'])")" | python3 -c "
import sys,json; d=json.load(sys.stdin)
ol = d.get('outlook') or {}
print('window:', ol.get('window'))
print('strength_score:', ol.get('strength_score'))
print('trajectory_score:', ol.get('trajectory_score'))
"
```

Expected: `window`, `strength_score`, and `trajectory_score` all populated with real values.
